# How digitization works

Each sheet goes through three model stages: **detect**, **trace** and an optional **review**. In
between, plain Python code merges, numbers, checks and exports the results. Detect and trace are
single Amazon Bedrock `Converse` calls with a fixed prompt. Review is a
[Strands](https://strandsagents.com/) agent that decides for itself which tools to call. All three
stages use the same model ID.

This describes the default `tiled` mode. With `"detect": "single"`, steps 1–4 are replaced by one
call on the whole sheet (see [Single mode](#single-mode)); the review is optional in both modes
(`review.enabled`).

The entry point is `digitize_sheet` in
[`job.py`](../pidtwin/src/pidtwin/digitize/job.py). It calls `run_pipeline` in
[`pipeline.py`](../pidtwin/src/pidtwin/digitize/pipeline.py).

## Stages at a glance

| # | Step | Kind | Code |
|---|---|---|---|
| 1 | Split the sheet into overlapping tiles | Deterministic | `tile_boxes` |
| 2 | Detect symbols and labels in each tile | **Bedrock call** (one per tile, run in parallel) | `detect`, `call_json`, `call` |
| 3 | Map tile boxes to sheet coordinates, remove duplicates, assign IDs | Deterministic | `to_sheet`, `valid_box`, `merge`, `assign_ids` |
| 4 | Trace pipe and signal lines through the detected items | **Bedrock call** (one per sheet) | `trace` |
| 5 | Build the draft and derive connections | Deterministic | `assemble`, `derive_connections` |
| 6 | Check the draft against graph rules | Deterministic | `graph_issues` |
| 7 | Review and fix the draft | **Strands agent** (on Bedrock) | `review_with_agent` in [`review.py`](../pidtwin/src/pidtwin/digitize/review.py) |
| 8 | Build the final graph, validate it, export files | Deterministic | `digitize_sheet` in `job.py` |

Unless noted otherwise, the functions are in `pipeline.py`, and `derive_connections` is in
[`common.py`](../pidtwin/src/pidtwin/common.py).

## Coordinates and IDs

- **Bounding boxes** are `[x_min, y_min, x_max, y_max]` in normalized coordinates from 0 to 1000
  on both axes, with `(0, 0)` at the top-left. Detect returns boxes relative to its tile, and
  step 3 converts them to sheet coordinates. Every later stage uses sheet coordinates.
- **Item IDs** are the printed tag when the tag appears once on the sheet (for example `FT-101`). A
  tag that appears more than once gets a number, such as `STA#1` and `STA#2`. Items without a tag get
  a category prefix and a number: `EQ` equipment, `V` valve, `I` instrument, `F` fitting,
  `OP` off-page connector, `L` line-number label. Numbering follows reading order: top to bottom,
  then left to right.
- **Run IDs** are `R1`, `R2`, …. A *run* is one continuous drawn line (a pipe, signal or impulse
  line) together with the ordered list of items along it.

## 1. Tiling (deterministic)

`tile_boxes` splits the sheet into a grid whose tiles have a long edge of at most `TILE` = 2576 px,
the largest image size Claude 5.x reads without downscaling. Neighbouring tiles overlap by
`OVERLAP` = 12 % of a tile step, so a symbol cut by one tile's edge appears whole in the next tile.

## 2. Detect (Bedrock)

Each tile goes to `bedrock-runtime` `converse` with `DETECT_PROMPT`. The tiles are sent in parallel
from a thread pool. The prompt tells the model where the tile sits on the sheet and asks for JSON
only:

```json
{"items": [{"category": "valve", "type": "gate valve", "tag": "HV-12", "text": null,
            "bbox": [x_min, y_min, x_max, y_max], "partial": false}]}
```

`partial: true` marks a symbol cut by the tile edge. `call_json` asks again (up to 3 attempts in
total) when the reply contains no valid JSON. Token usage from every attempt is added up.

Output: `detect.json`

## 3. Merge and assign IDs (deterministic)

- `valid_box` drops malformed boxes and puts each box's corner coordinates in order.
- `to_sheet` converts tile coordinates to sheet coordinates.
- `merge` removes duplicates of the same symbol found in overlapping tiles. Two detections count as
  the same symbol when they have the same category and no conflicting tags, and either their boxes
  overlap with an IoU above 0.25 or their centres are closer than 0.6 of the symbol size. When
  detections clash, complete ones win over partial ones, tagged ones over untagged ones, and larger
  boxes over smaller ones.
- `assign_ids` assigns the IDs described in [Coordinates and IDs](#coordinates-and-ids).

## 4. Trace (Bedrock)

The trace stage is one `converse` call with two images and a text inventory:

1. The full sheet.
2. The same sheet with every detected item boxed and labelled with its ID (drawn by `draw_state`).
3. An inventory with one line per item: `id | category | type | tag or text | bbox`.

`TRACE_PROMPT` asks the model to trace every line on the sheet and return:

```json
{"drawing": {"number": "...", "revision": "...", "title": "..."},
 "runs": [{"id": "R1", "kind": "process", "line_number": "6\"-DW-1865",
           "items": ["P-101", "V3", "HV-12", "R4"], "path": [[x, y], ...]}],
 "added": [{"id": "X1", "category": "fitting", "type": "drain", "bbox": [...]}]}
```

Run rules (`RUN_RULES`):

- `items` starts with whatever sits at one end of the line, lists every item the line passes
  through in order, and ends with whatever sits at the other end.
- An end of a run is one of three things: an item ID; another run's ID, when the line tees into
  that run; or `END`, for a bare line end with no symbol.
- Dashed lines are `signal`. Thin lines joining an instrument to a process line are `impulse`.
  Everything else is `process`.

Symbols the model spots but that detect missed come back under `added`. Those with a valid box are
appended to the item list.

Output: `trace.raw.txt` (the model's raw reply) and `trace.json`

## 5. Assemble the draft (deterministic)

`assemble` groups items by category into `equipment`, `valves`, `instruments`, `fittings`,
`offpage` and `lines`. A line number that appears only on a run, with no matching label item, is
still added to `lines`.

`derive_connections` turns runs into `from → to` connections:

- Consecutive items along a run are connected.
- When a run ends on another run's ID (a tee), that end connects to the last item on the other run
  that comes before the tee point. This is the usual convention for instrument taps. If no item
  comes before the tee point, the end connects to the nearest item instead.
- Each connection records its `kind` and the ID of the run it came from.

Output: `draft.json` (written only when review is on)

## 6. Graph checks (deterministic)

`graph_issues` builds the plant graph (`pidtwin.graph.build`) and runs the rule checks
(`pidtwin.graph.validate`). Examples: isolated items, dangling pipes, valves or tees with the wrong
number of connections, equipment with no piping, and duplicate tags. Warnings and errors are passed
to the review stage as hints. Info-level findings, such as the count of open line ends, are dropped.

## 7. Review (Strands agent)

When `review` is on, `review_with_agent` starts a Strands `Agent` on a `BedrockModel` with the same
model ID. The first message holds the full sheet with the draft drawn on it, the item and run
inventories, and the graph-check hints. The system prompt tells the agent to:

1. Sweep the sheet in about 6–12 overlapping windows with `view_region`, comparing the drawn
   draft with the drawing underneath.
2. Fix every difference: symbols that are missing or misread, wrong boxes, missing fittings or
   labels, and runs that are missing, stop short, jump across the sheet, or list the wrong items.
3. Make sure every drawn line is covered by a run.
4. Call `finish` with a summary.

The tools are deterministic Python functions. The model decides which ones to call and in what
order:

| Tool | What it does |
|---|---|
| `view_region(x_min, y_min, x_max, y_max, overlay=True)` | Crops the original sheet at full resolution (long edge up to 1600 px), optionally draws the current items and runs on it, and lists the items and runs inside the region. Each call uses one view from the budget (`maxViews`, default 40). |
| `add_item` | Adds a missing item. Its ID is the tag if that tag is unused, otherwise the next free prefix ID. |
| `update_item` | Changes only the fields passed in: category, type, tag, text, bbox. |
| `delete_item` | Removes an item and removes its ID from every run. |
| `upsert_run` | Creates a run, or replaces one when `id` is given. Refuses unknown item IDs. |
| `delete_run` | Removes a run. |
| `finish(summary)` | Ends the review. |

The tools edit the `items` and `runs` lists in place, and a `log` counts views, additions, updates
and deletions. With OpenAI models on Bedrock, a `BeforeModelCallEvent` hook (`_hoist_tool_images`)
moves images out of `toolResult` blocks into the user message, because Bedrock rejects images
inside tool results for those models.

After the review, `assemble` runs again on the edited items and runs.

Output: `review.json` (the log and the agent's final message)

## 8. Final graph and exports (deterministic)

`digitize_sheet` saves `sheet.json` with token usage and cost, then builds the sheet graph and
validates it. It writes:

| File | Contents |
|---|---|
| `sheet.json` | Digitized sheet: items, runs, connections, usage |
| `graph.json` | Sheet graph (`pidtwin.graph.schema`) |
| `issues.json` | Rule violations still present after review |
| `dexpi.xml` | DEXPI-style Proteus XML (not schema-validated) |
| `graph.dot` | Graphviz view of the topology |
| `overlay.png` | Final result drawn over the sheet (long edge 4096 px) |

### Reading `overlay.png`

`overlay.png` is drawn by the same `draw_state` function the review agent sees:

- **Red boxes** are items; the **blue text** next to each box is its ID.
- **Orange lines** are run paths; the **orange-red text** at the middle of each path is the run ID
  (`R18`, for example). Look up that ID in `sheet.json` under `runs` to see the run's items, and
  under `connections[].run` to see the connections that came from it.

## Single mode

With `"detect": "single"`, `single()` sends the whole sheet, scaled to 2,576 px on the long edge
(`TILE`), in one `converse` call with `SINGLE_PROMPT`. The prompt uses the same categories
(`CATEGORY_DOC`) and run rules (`RUN_RULES`) as tiled mode and asks for items and runs together:

```json
{"drawing": {...}, "items": [{"id": "HV-12", "category": "valve", ...}], "runs": [...]}
```

The model gives each item its own ID. Items with a malformed box are dropped, and a repeated ID gets
a `#2`, `#3`… suffix. There is no tiling, merging or separate trace call. The result is saved as
`trace.json`, in the same shape as tiled mode, and from there steps 5–8 are the same: the draft is
assembled, checked against the graph rules and, when review is on, handed to the review agent.

Output: `single.raw.txt` (the model's raw reply) and `trace.json`

## Model calls per sheet

| Stage | Calls |
|---|---|
| Detect | One per tile, sent in parallel; a typical 300-dpi sheet has a handful of tiles. Up to 3 attempts each if the reply has no valid JSON. |
| Trace | One, with up to 3 attempts. |
| Single call (single mode, replaces detect and trace) | One, with up to 3 attempts. |
| Review | One per agent turn, until the agent calls `finish`. The view budget limits how many crops it can request. |

## Resuming a failed sheet

When `resume` is on (the default in `digitize_sheet`), stages whose output file is already in the
sink are not run again. If `trace.json` exists and was written in the same `detect` mode, both
detect and trace (or the single call) are skipped. If only
`detect.json` exists, only detect is skipped. Review always runs again. This lets a retried sheet
continue from where it stopped instead of paying for the earlier stages a second time.
