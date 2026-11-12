# SDMA staged connectors (prototype)

This prototype runs each step of the digitization as its own SDMA connector. It is an alternative
to the single connector in [SDMA_CONNECTOR.md](SDMA_CONNECTOR.md), which hands the whole run to
Step Functions. It ran end to end on SDMA 1.7.0 with a two-sheet PDF: two pages, two sheets
digitized in parallel, one plant graph of 62 nodes and 67 edges, for $0.45.

## The three connectors

| Stage | Connector | Trigger | Runs | Attaches |
|---|---|---|---|---|
| 1 | P&ID 1 - render pages | Drawing (PDF or image), `upload` or `onDemand` | PrepareInput: validate, render PDF pages | One `<sheet>.page.png` per sheet, as derived files of the drawing. Metadata on the drawing: `pnidRunId`, `pnidPages` |
| 2 | P&ID 2 - digitize sheet | Each `*.page.png`, `upload` or `onDemand` | Starts the AgentCore agent for the page, then an output-driven `wait` that holds no compute | `<sheet>.graph.json`, `.dexpi.xml`, `.issues.json`, `.result.json` and `.overlay.png` (preview), next to the page. Metadata on the page: status, nodes, edges, cost, model |
| 3 | P&ID 3 - merge plant | Each `*.result.json`, `upload` or `onDemand` | Once every sheet of the run has a result: MergeSheets | `plant.dexpi.xml`, `plant.graph.json`, `plant.issues.json` and `summary.json`, next to the pages. Metadata on the asset: `pnidPlantStatus`, sheet counts, plant nodes and edges, cost, `pnidReviewNeeded`, `pnidReviewReasons` |
| 4 | P&ID 4 - review alert (notification) | Each `*.review.json`, `upload` | Sends an in-app message to the project's owners and managers | Nothing; the delivery is an invocation record |

All derived files sit under the drawing, so the Spatial Data Portal shows the pages, the per-sheet
files and the plant files together. Each sheet has its own invocation record, and a sheet can be
re-run on demand from its page.

The connectors are configuration in `cdk/sdma/stages/`. They are rendered with
`node sdma/render-connector.mjs <stack> stages/<render|digitize|merge>`. The Lambdas reuse the
existing PrepareInput, DispatchSheet and MergeSheets code, and the agent gains an export mode that
writes results to S3 instead of calling back a Step Functions task token. Templates that use stage 3
must declare the asset attributes in `cdk/sdma/stages/template-attributes.json`. The alert is a
`notification` connector (publish direction), rendered with
`node sdma/render-connector.mjs <stack> stages/alert`.

## When a result needs review

MergeSheets decides, for both this path and the Step Functions path, and records it in
`summary.json` (`review.needed`, `review.reasons`). A person should check the result when:

- a sheet failed;
- the review agent ran out of views on a sheet before it finished;
- an error, a dangling pipe, unpiped equipment, an isolated item or a duplicate tag remains;
- off-page connectors were not joined across sheets.

Routine warnings, such as a valve with one connection or a tag that does not match the usual
pattern, do not ask for a review on their own. Stage 3 writes the decision to the asset. When a
review is needed, it also attaches `<drawing>.review.json` with the reasons, and that upload starts
stage 4, which sends a message such as "P&ID area-7 needs review: 1 sheet(s) failed: area-7.p3;
2 dangling pipes". The alert fires once per merge that needs review, and later edits of the asset
do not repeat it.

The alert does not trigger on the asset metadata itself, although the docs suggest asset `update`
for "after the asset's metadata changed". In SDMA 1.7.0, a connector's metadata write raises no asset
event: asset events come from uploads, Deadline Cloud job completions and deletes. On an asset with
a single version, they are also classed as `create`, not `update`.

## How the stages hand over

- **Stage 1 to 2.** Each page is a derived file, so its upload starts stage 2. Stage 2 takes the sheet
  from the page's file name. It finds the run through an index that stage 1 writes, keyed by the
  page's xxh128 hash, which is the hash SDMA gives the ingested page.
- **Stage 2 to 3.** The agent writes `<sheet>.result.json` last, whether or not the sheet
  succeeded. It completes stage 2's wait, and its upload starts stage 3.
- **Fan-in.** Stage 3 runs once per sheet. It merges only when all of the run's pages have a result,
  and otherwise returns `PENDING` and ingests nothing. Each run of stage 3 starts after its own
  sheet's result is written, so the run for the last sheet always sees every result. When two
  sheets finish within seconds, both runs may merge. The result is the same, and SDMA keeps one
  current set of plant files.

## SDMA 1.7.0 behaviour this design works around

Each of these was found in SDMA's connector code and confirmed on the test deployment.

1. **No fan-out over derived files.** `applyTo` with `resource: derivedFile` iterates nothing,
   because the asset's derived-file list is never populated for the trigger. Pages therefore chain
   through derived-file `upload` events, one invocation per page.
2. **No fan-in.** `dependsOn` is satisfied by the first finished invocation of the upstream
   connector, not by all of them. A run started by `derivationComplete` does not announce its own
   completion. Stage 3 therefore counts results itself.
3. **Stale metadata.** SDMA caches an asset's metadata document for 10 seconds per container. Stage 2
   starts within that window, so it cannot read metadata that stage 1 just wrote. This is why the
   run is found through the page-hash index.
4. **Unresolved sibling URIs.** In an output-driven `wait`, `${...}` is resolved in the URIs of
   `metadataAttributes`, `derivedFiles`, `files` and `assets`, but not of `siblingDerivedFiles`.
   Stage 2 therefore reads the prefix from the result document as `${response.exportPrefix}`.
5. **Nested derived files are shown as outdated.** The portal groups derived files only under
   first-class files. Output attached beneath a derived file appears under "Outdated derived
   files", so every stage attaches its output next to its trigger file (`siblingDerivedFiles`).
6. **Asset metadata against the template.** A connector can write asset attributes that the
   template does not allow. The asset then fails validation the next time it is edited, hence the
   template attributes above.
7. **Chaining reaches every enabled connector.** Derived-file events are evaluated against every
   enabled connector in the library, not only those the template permits. The stages' file-name
   filters keep them apart.

## Compared with the single connector

| | Single connector (Step Functions) | Staged connectors |
|---|---|---|
| Visibility in SDMA | One invocation per drawing | One invocation per stage and sheet; per-sheet files and metadata |
| Re-run one sheet | No | Yes, on demand from its page |
| Concurrency | Capped (`maxConcurrentSheets`, default 4) | Not capped: every page starts at once, so large PDFs can be throttled by Bedrock |
| Retries | Throttled or hung sheets are retried on a fresh session, reusing saved detect results | None. A failed sheet records `FAILED` in its result, and the plant is merged without it (`PARTIAL`) |
| Failure policy | Not affected by sheet failures | Five failed starts in 10 minutes disable the connector |
| Moving parts | One connector, one Lambda, the state machine | Three connectors, three Lambdas, a page index and an agent export mode |

## Open before production

- Retries and backoff inside the agent for throttling, since SDMA does not retry.
- A concurrency limit for stage 2, for example a semaphore in the dispatch Lambda, so a 50-page PDF
  does not start 50 sessions at once.
- Deciding whether both paths are kept, or the staged connectors replace the single connector for
  SDMA users. Step Functions stays for S3-upload users either way.
