# Troubleshooting

Start with the failed execution in the Step Functions console:

- **Failed sheets.** A failed sheet shows up as a `SheetFailed` result in the `Sheets` Map. Its
  `error` and `cause` come from the agent.
- **Run summary.** `summary.json` in the run's output prefix lists every sheet's status.
- **Agent logs** are in CloudWatch Logs under `/aws/bedrock-agentcore/runtimes/<runtime id>-DEFAULT`.
  Filter on the sheet ID.
- **Lambda logs** are in the `PrepareInput`, `DispatchSheet` and `MergeSheets` log groups of the
  stack.

## The run fails in PrepareInput with `InputError`

The drawing or the per-run config was rejected. The cause names the problem:

| Message | Fix |
|---|---|
| `modelId ... is not allowed` | Use a model listed in `digitization.allowedModelIds`, or add it there and redeploy. |
| `unsupported file type` | Convert the drawing to PDF, PNG, JPEG, TIFF or WebP. |
| `... has N pages; the limit is M` | Split the PDF, or raise `pdf.maxPages`. |
| `cannot read ...` | The file is corrupt, or is not what its extension says. |
| `drawings must be uploaded to the input bucket` | Start runs on objects in the stack's input bucket. |
| `... not found` | Check the key. Keys are case-sensitive. |

## A sheet fails with `AccessDeniedException` from Bedrock

- The model is not enabled in the account and Region, or the account has not accepted the model's
  offer. Check Bedrock **Model access**. Third-party models can need a one-time offer acceptance,
  done by an identity with `aws-marketplace:Subscribe`.
- The inference profile isn't available in your deployment Region. Choose a profile that is, such
  as `us.`, `eu.`, `apac.` or `global.`, add it to `allowedModelIds`, and redeploy.

## Sheets fail with `ThrottlingException` or `ModelThrottledException`

The run is making more model calls than your Bedrock quota allows. Each sheet sends one request
per tile in parallel during detect, then a stream of requests during review. Sheets are retried
twice with backoff. If they still fail:

- lower `orchestration.maxConcurrentSheets`, or start fewer runs at a time;
- request higher quotas for the model (Service Quotas → Amazon Bedrock → tokens and requests per
  minute for the inference profile);
- use a `global.` inference profile, if one exists for your model, to spread the load.

## A sheet fails with `States.HeartbeatTimeout`

The agent sent no heartbeat for 5 minutes. Usually its session ended: it crashed, ran out of
memory, or reached its maximum lifetime. Look at the agent logs around the last heartbeat.

- **The session ran out of memory.** Very large sheets can cause this. Pages are capped at
  20,000 px per side; render PDFs at a lower `pdf.dpi` (200 is usually enough to read tags).
- **The sheet keeps timing out.** Raise `orchestration.sheetTimeoutMinutes`. The session's
  maximum lifetime follows it.

The retry reuses the detect and trace results already in S3, so only the review step runs again.

## A sheet fails with `States.Timeout`

The sheet took longer than `sheetTimeoutMinutes`. Dense sheets with a high `review.maxViews` on a
slow model are the usual cause. Raise the timeout, lower `maxViews`, or use a faster model.

## The review step fails with a validation error about images (non-Claude models)

Some providers reject images inside tool results. The review agent works around this for `openai`
models. For another provider, add its provider name to `TOOL_RESULT_IMAGES` in
`pidtwin/src/pidtwin/digitize/review.py` and redeploy. The provider name is the part of the model ID
after the Region prefix, for example `openai` in `us.openai.gpt-6.1-sol`.

## Uploading a file did not start a run

- The object must be under `uploadTrigger.prefix`, which defaults to `drawings/`, and must end in a
  supported extension. Both upper and lower case work, but not mixed case such as `.Pdf`.
- `uploadTrigger.enabled` must be true when you deploy.
- EventBridge notifications must be enabled on the input bucket. The stack turns them on, so check
  that nobody turned them off.

## Results look wrong

- Open `sheets/<sheet>/overlay.png` to see what the model found and where.
- Read `issues.json` for the rule violations left after review. A cluster of `valve_degree` or
  `dangling_pipe` issues in one area usually means a missed or misrouted line there.
- Compare `draft.json` (before review) with `sheet.json`, and read the agent's notes in
  `review.json`. If the review ran out of views (`views` equals `maxViews` and `finished` is false),
  raise `review.maxViews`.
- If the notes on your drawings say dashed lines are piping alternates, set `dashedAsPiping: true`.
- Try another model on the same sheet. See the benchmark in the [README](../README.md#accuracy-and-model-choice).

## Deployment problems

| Symptom | Fix |
|---|---|
| `Cannot find module` / TypeScript errors | Run `npm install` in `cdk/`. |
| Bundling tries to run Docker | Install [uv](https://docs.astral.sh/uv/). The stack bundles Python locally with uv, and only falls back to Docker. |
| `uv pip install` cannot find a wheel | A dependency has no Linux arm64 wheel for Python 3.13. Pin a version that has one in the `requirements.txt` that fails. |
| `digitization.modelId ... must be one of digitization.allowedModelIds` | Fix `config.json`. |
| `cdk destroy PNIDDigitization-Network` fails on the security group or subnets | AgentCore keeps its network interfaces for up to 8 hours after the runtime is deleted. Run it again later. |
| `cdk destroy PNIDDigitization-Network` says an export is in use | Destroy the application stack `PNIDDigitization` first. |
| AgentCore Runtime creation fails in a VPC | Use subnets in [Availability Zones that AgentCore supports](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html), and make S3 reachable from them, because the runtime downloads its code from S3. |
