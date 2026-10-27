# API Reference

This page covers:

- what you pass to the workflow;
- what each step passes to the next;
- what ends up in S3.

All coordinates on a sheet are normalized to 0–1000 on both axes, with (0, 0) at the top-left
corner.

## Workflow input

Start the state machine with:

```json
{
  "bucket": "<InputBucketName>",
  "key": "drawings/area-7.pdf",
  "config": { "modelId": "us.openai.gpt-6.1-sol" }
}
```

| Field | Required | Meaning |
|---|---|---|
| `bucket` | yes | The stack's input bucket. Other buckets are rejected. |
| `key` | yes | Object key of a `.pdf`, `.png`, `.jpg`/`.jpeg`, `.tif`/`.tiff` or `.webp` file. |
| `config` | no | Per-run overrides of the `digitization` settings. See [Configuration](CONFIGURATION.md#per-run-settings). |

The upload trigger starts runs with `{"bucket", "key", "trigger": "upload"}` and no `config`.

## Workflow states

| State | Type | Does |
|---|---|---|
| `SupportedFile?` | Choice | Uploads (`"trigger": "upload"`, set by the upload rule) whose key does not end in a supported extension go to `IgnoredUpload` and end. Manual starts always continue. |
| `DefaultConfig`, `MergeInput` | Pass | Add `"config": {}` when the input has none. |
| `PrepareInput` | Lambda | Validate the input and config, write `pages/` and `input.json`, return the page list. |
| `Sheets` | Map | For each page, run `DigitizeSheet`, up to `maxConcurrentSheets` at a time. |
| `DigitizeSheet` | Lambda, `.waitForTaskToken` | Start an AgentCore session, then wait for its callback (heartbeat 300 s, timeout `sheetTimeoutMinutes`). |
| `SheetFailed` | Pass | Turn a failed sheet into `{"status": "FAILED", "sheetId", "error", "cause"}` so the other sheets continue. |
| `MergeSheets` | Lambda | Write the plant graph and `summary.json`. |
| `AllSheetsDone?` | Choice | Succeed if every sheet succeeded. Otherwise fail with `SheetsFailed`; the outputs of the good sheets are still written. |

`DigitizeSheet` is retried on a new session twice, starting after 1 minute and backing off ×2,
for these errors: `States.HeartbeatTimeout`, `ThrottlingException`, `ModelThrottledException`,
`ServiceUnavailableException`, `ModelNotReadyException`, `ModelErrorException` and
`InternalServerException`. A retry reuses the `detect.json` and `trace.json` already written for
the sheet.

## PrepareInput (Lambda)

Input, as built by the state machine:

```json
{ "bucket": "...", "key": "...", "config": { }, "executionName": "<execution name>" }
```

Output:

```json
{
  "bucket": "<OutputBucketName>",
  "prefix": "<execution name>/",
  "source": { "bucket": "...", "key": "drawings/area-7.pdf", "versionId": "..." },
  "config": { "modelId": "...", "review": { "enabled": true, "maxViews": 40 },
              "dashedAsPiping": false, "pdf": { "dpi": 300, "maxPages": 50 } },
  "pages": [ { "sheetId": "area-7.p1", "pageKey": "<execution name>/pages/area-7.p1.png",
               "outputPrefix": "<execution name>/sheets/area-7.p1/" } ]
}
```

Sheet IDs come from the file name. A multi-page PDF gets `.p1`, `.p2`, … suffixes. Validation
errors are raised as `InputError` and are not retried.

## DispatchSheet (Lambda) and the agent payload

DispatchSheet receives the task token, the execution ARN, the retry count, the bucket, one page
and the config. It calls `InvokeAgentRuntime` with a session ID derived from
(execution, sheet, retry count). It then passes this payload to the agent:

```json
{
  "bucket": "<OutputBucketName>",
  "pageKey": "<execution name>/pages/area-7.p1.png",
  "outputPrefix": "<execution name>/sheets/area-7.p1/",
  "sheetId": "area-7.p1",
  "config": { "modelId": "...", "review": { "enabled": true, "maxViews": 40 }, "dashedAsPiping": false },
  "taskToken": "..."
}
```

The agent ([`cdk/agent/main.py`](../cdk/agent/main.py)) answers `{"status": "accepted"}` at once,
digitizes in a background thread, and sends `SendTaskHeartbeat` every 60 seconds. When it
finishes, it calls `SendTaskSuccess` with the sheet summary:

```json
{
  "status": "SUCCEEDED",
  "sheet_id": "area-7.p1",
  "outputPrefix": "<execution name>/sheets/area-7.p1/",
  "drawing": { "number": "...", "revision": "...", "title": "..." },
  "counts": { "equipment": 6, "valves": 42, "instruments": 17, "fittings": 31, "offpage": 9,
              "lines": 11, "runs": 64, "connections": 151 },
  "graph": { "nodes": 412, "edges": 431 },
  "issues": { "warning:valve_degree": 2 },
  "usage": { "inputTokens": 10208, "outputTokens": 22226, "cacheWriteInputTokens": 336272, "cacheReadInputTokens": 410269 },
  "seconds": 350, "usd": 1.24, "model_id": "us.openai.gpt-6.1-sol",
  "review": { "views": 31, "added": 4, "updated": 9, "deleted": 1, "runs_added": 3, "runs_updated": 6,
              "runs_deleted": 0, "finished": true, "summary": "..." }
}
```

On any exception, the agent calls `SendTaskFailure` instead. The error is the exception class name,
for example `ThrottlingException`, and the cause is its message.

## MergeSheets (Lambda)

Input: `{"bucket", "prefix", "source", "config", "results": [<one entry per page>]}`.
Output: `{"status": "SUCCEEDED" | "PARTIAL" | "FAILED", "sheets": {"total", "succeeded"}, "usd",
"outputs": {"graph", "issues", "dexpi", "dot", "summary"}}`.

## Output files

### `sheets/<sheet>/sheet.json`: digitized sheet

```json
{
  "drawing": { "number": "PID-1001", "revision": "B", "title": "..." },
  "equipment":   [ { "id": "T-101", "tag": "T-101", "type": "tank", "description": null, "bbox": [x0, y0, x1, y1] } ],
  "valves":      [ { "id": "HV-101", "tag": "HV-101", "type": "gate valve", "bbox": [...] } ],
  "instruments": [ { "id": "FT-101", "tag": "FT-101", "function": "ISA bubble", "text": null, "bbox": [...] } ],
  "fittings":    [ { "id": "F3", "type": "blind flange", "text": "6\"", "bbox": [...] } ],
  "offpage":     [ { "label": "OP1", "text": "TO UNIT 200", "bbox": [...] } ],
  "lines":       [ { "id": "L2", "line_number": "6\"-DW-1865", "bbox": [...] } ],
  "runs": [ { "id": "R1", "kind": "process", "line_number": "6\"-DW-1865",
              "items": ["T-101", "HV-101", "F3", "OP1"], "path": [[x, y], ...] } ],
  "connections": [ { "from": "T-101", "to": "HV-101", "kind": "process", "run": "R1" } ],
  "_usage": { "inputTokens": 0, "outputTokens": 0, "seconds": 0, "usd": 0.0, "model_id": "..." },
  "_pipeline": { "tiles": 6, "raw_detections": 212, "items": 180, "runs": 64, "review": { } }
}
```

- **Runs** are the traced lines. Each one lists the item ids it passes, in order.
- **End of a run.** A run can end at an item id, at another run's id (a tee into that run), or at
  `"END"` (a bare line end).
- **`kind`** is `process` for piping, `signal` for dashed signal lines, and `impulse` for
  instrument tubing.
- **Connections** are derived from the runs.

### `graph.json` and `plant.graph.json`: plant graph

The schema is defined by the pydantic models in
[`pidtwin/src/pidtwin/graph/schema.py`](../pidtwin/src/pidtwin/graph/schema.py):

```json
{
  "schema_version": "1.0",
  "source": "pid",
  "sheets": [ { "id": "area-7.p1", "number": "PID-1001", "title": "...", "image": "s3://..." } ],
  "nodes": [ { "id": "HV-101", "category": "valve", "dexpi_class": "GateValve", "type": "gate valve",
               "tag": "HV-101", "sheet": "area-7.p1", "bbox": [...] },
             { "id": "P4", "category": "pipe", "dexpi_class": "PipingNetworkSegment",
               "line_number": "6\"-DW-1865", "nominal_size": "6\"", "service": "DW", "attrs": { "run": "R1" } } ],
  "edges": [ { "src": "HV-101", "dst": "P4", "kind": "process", "run": "R1" } ],
  "warnings": [ "R7: signal run carries line number 2\"-D-5 - treated as piping" ]
}
```

The graph follows one convention throughout:

- **Nodes are physical items.** The categories are `equipment`, `valve`, `instrument`, `fitting`,
  `offpage`, `tee`, `end` and `pipe`.
- **Pipes are cut at items and tees.** A `pipe` node runs between two neighbouring non-pipe nodes,
  so every run is cut at each inline item and at each tee.
- **Edges are direct contact.** Edge `kind` is `process` (piping), `impulse` (instrument tubing) or
  `signal` (information only).
- **Pipe attributes come from the line number.** `line_number`, `nominal_size` and `service` are
  parsed from line numbers such as `6"-DW-1865`.
- **DEXPI classes.** `dexpi_class` uses DEXPI 1.3 names, chosen by keyword from the model's
  free-text `type`. Classes starting with `Custom` mean the kind was not recognized.
- **Node ids in the plant graph.** Ids are prefixed with `<sheet>/`. Equipment drawn on several
  sheets with the same tag becomes one node. Off-page connectors are paired across sheets when
  their pipes carry the same line number, or when one connector's text names the other sheet.

### `issues.json` and `plant.issues.json`: rule violations

```json
[ { "level": "warning", "code": "valve_degree", "node": "HV-104",
    "message": "valve HV-104 has 1 process connections (expected 2: one in, one out)" } ]
```

| Code | What it flags |
|---|---|
| `isolated` | An item with no connections |
| `dangling_pipe` | A pipe segment without exactly 2 connections |
| `valve_degree` | A valve without exactly 2 process connections |
| `tee_degree` | A tee with fewer than 3 connections |
| `equipment_unpiped` | Equipment with no piping connection |
| `offpage_target` | An off-page connector without destination text |
| `tag_pattern` | A tag that does not look like a valve or instrument tag |
| `duplicate_tag` | A valve or instrument tag that appears more than once |
| `multiple_line_numbers` | A run with several different line-number labels along it, which may be two lines |
| `unknown_node` | An edge that refers to a missing node |
| `open_ends` (info) | The number of line ends without a symbol |

The same rules run on the draft before review, and their findings are given to the review agent as
hints.

### `dexpi.xml` and `plant.dexpi.xml`

The export is DEXPI-style Proteus XML. It uses DEXPI 1.3 class names and the Proteus 4 element
layout, and contains:

- Equipment, with one Nozzle per piping connection;
- one PipingNetworkSystem per line number, holding PipingNetworkSegments, which are chains of pipes
  and inline components between two terminals;
- one ProcessInstrumentationFunction per instrument;
- one InformationFlow per signal edge.

Geometry is not written. The file has not been validated against the DEXPI XSD, so check it with
your target tool.

### `graph.dot` and `plant.dot`

The topology as a Graphviz file, with pipes drawn as labelled edges. Render it with
`dot -Tsvg graph.dot -o graph.svg`.

### `overlay.png`

The sheet, scaled to at most 4096 px on its long edge, with the final result drawn on top:

- item boxes in red, with their ids in blue;
- traced runs in orange, with their run ids.

### Intermediate files

| File | Written by | Contents |
|---|---|---|
| `detect.json` | detect | Merged items with ids, tile count, raw detection count, token usage |
| `trace.raw.txt`, `trace.json` | trace | The model's raw reply; the items and the traced runs |
| `draft.json` | before review | The result before review, in the same format as `sheet.json` |
| `review.json` | review | The agent's edit log and final message |

### `summary.json`

The run's status, source file, model, sheet counts, total token usage and cost, the result entry of
every page (the sheet summary above, or the failure), plant-graph statistics, and the S3 URIs of
the plant outputs.
