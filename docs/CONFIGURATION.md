# Configuration

There are two levels of settings:

- **Deployment settings** live in `cdk/config.json`. Copy `cdk/config.json.template` and edit it,
  then run `cdk deploy --all`. Any key you leave out keeps its value from the template, so the file is
  optional.
- **Per-run settings** go under `config` in a Step Functions execution input. They override the
  deployed `digitization` defaults for that run only.

## Deployment settings (`cdk/config.json`)

```json
{
  "vpc": { "vpcId": "", "cidr": "10.42.0.0/16", "availabilityZoneIds": [],
           "subnetIds": [], "routeTableIds": [], "createVpcEndpoints": true },
  "endpoints": { "bedrockRuntime": true, "agentCore": true, "stepFunctions": true, "logs": true, "s3": true },
  "digitization": {
    "modelId": "us.openai.gpt-6.1-sol",
    "allowedModelIds": ["us.openai.gpt-6.1-sol", "us.openai.gpt-6.1-terra", "us.openai.gpt-6-astra",
                        "us.anthropic.claude-sonnet-5-5", "global.anthropic.claude-opus-5-5"],
    "review": { "enabled": true, "maxViews": 40 },
    "dashedAsPiping": false,
    "pdf": { "dpi": 300, "maxPages": 50 }
  },
  "orchestration": {
    "maxConcurrentSheets": 4,
    "sheetTimeoutMinutes": 120,
    "uploadTrigger": { "enabled": true, "prefix": "drawings/" }
  }
}
```

### `digitization`: what each sheet run does

These are the deployed defaults. Every key except `allowedModelIds` can be overridden per run.

| Key | Default | Meaning |
|---|---|---|
| `modelId` | `us.openai.gpt-6.1-sol` | Bedrock model or inference profile used for all three steps. It must be in `allowedModelIds`. |
| `allowedModelIds` | five models, see above | The models a run may ask for. The agent's IAM role can invoke only these, and PrepareInput and the agent both reject any other model. Changing the list needs a redeploy. |
| `review.enabled` | `true` | Run the review agent after detect and trace. When it is off, the run is faster and cheaper but less accurate. |
| `review.maxViews` | `40` | How many zoomed views the review agent may request (1–200). Dense or large sheets benefit from more. |
| `dashedAsPiping` | `false` | Treat every dashed line as piping, for drawing sets whose notes say dotted lines are alternate routes. Even when this is off, a dashed line that carries a line number, or that piping tees into, is treated as piping, and `issues.json` lists it. |
| `pdf.dpi` | `300` | Resolution used to render PDF pages. Pages are capped at 20,000 px per side. |
| `pdf.maxPages` | `50` | Reject PDFs with more pages than this. |

### Choosing a model

On the 10-sheet benchmark in the [README](../README.md#accuracy-and-model-choice), every allowed model
except Opus reached 99% label accuracy. The choice is mostly about connection tracing and cost:

- **GPT-6.1 Sol** (default): good tracing (89% connection F1) at $1.24 a sheet.
- **GPT-6.1 Terra**: the cheapest ($0.55 a sheet) and the fastest, with slightly weaker tracing
  (87%).
- **GPT-6 Astra**: the best tracing (91%), at about $6.80 a sheet.
- **Claude Sonnet 5.5**: weaker tracing (81%) at a price similar to Sol.
- **Claude Opus 5.5**: weaker on instrument tags (85% precision) and $3.31 a sheet.

To use a model that is not in the list, add its inference profile ID to `allowedModelIds`, add its
token prices to `PRICES` in `pidtwin/src/pidtwin/digitize/pipeline.py` (otherwise its cost is
reported as `null`), and redeploy. The model must support images and tool use through the Converse
API. Some providers don't accept images inside tool results. For those, the review agent moves the
images into the user message instead. That workaround is on for `openai` models
(`TOOL_RESULT_IMAGES` in `review.py`). If your model's review step fails with a validation error
about images, add its provider there: the part of the model ID after the Region prefix.

### `orchestration`

| Key | Default | Meaning |
|---|---|---|
| `maxConcurrentSheets` | `4` | How many sheets of one run are digitized at once. Raise it if your Bedrock quotas allow. Every sheet is one AgentCore session plus a stream of model calls. |
| `sheetTimeoutMinutes` | `120` | The longest one sheet may take, from 5 to 465. The AgentCore session lifetime is set 15 minutes above this. |
| `uploadTrigger.enabled` | `true` | Start a run for each drawing uploaded to the input bucket. |
| `uploadTrigger.prefix` | `drawings/` | Only uploads under this prefix start a run. Uploads under the prefix whose extension is not supported end at once in an `IgnoredUpload` state. Keep a prefix: with `""`, the bucket's own access logs under `access-logs/` would start (and immediately end) a run every few minutes. |

The upload trigger starts one execution per file, and `maxConcurrentSheets` applies within each
execution. If you upload a large batch at once, many sheets will run together, and Bedrock may
throttle them. Throttled sheets are retried, but for big batches it is better to start executions
yourself at a controlled rate, or to raise your Bedrock quotas first.

### `vpc` and `endpoints`: networking

The Lambdas and the agent runtime always run in a VPC.

**Default: a new isolated VPC.** With `vpc.vpcId` empty, the stack creates:

- a VPC (`vpc.cidr`, default `10.42.0.0/16`) with two private subnets (`/20`). There is no internet
  gateway and no NAT gateway.
- subnets placed by **Availability Zone ID** in zones where AgentCore Runtime supports VPC
  connectivity
  ([list](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html#agentcore-vpc-supported-azs)).
  The default is the first two supported zones of the Region, for example `usw2-az1` and `usw2-az2`
  in us-west-2. To choose others, set `vpc.availabilityZoneIds`, for example
  `["usw2-az2", "usw2-az3"]`.
- interface endpoints for `bedrock-runtime`, `bedrock-agentcore`, `states` and `logs`, each with
  an endpoint policy limited to the calls the workload makes.
- an S3 gateway endpoint. Its policy allows only buckets owned by this account (the network stack
  is deployed before the buckets, so it cannot name them), plus the AgentCore code-artifact buckets (`acr-code-*-<region>-an`) for the AgentCore service. AgentCore downloads
  the agent's zip from those buckets through the VPC when a session starts.
- VPC flow logs to CloudWatch Logs (kept for one month).
- one workload security group with HTTPS egress only. Each endpoint's security group admits only
  the workload security group.

The `endpoints` flags have no effect on a created VPC: it always gets every endpoint.

**Existing VPC.** To deploy into a VPC you already have:

```json
{
  "vpc": {
    "vpcId": "vpc-0123456789abcdef0",
    "subnetIds": ["subnet-aaa", "subnet-bbb"],
    "routeTableIds": ["rtb-aaa", "rtb-bbb"],
    "createVpcEndpoints": true
  },
  "endpoints": { "bedrockRuntime": true, "agentCore": true, "stepFunctions": true, "logs": true, "s3": true }
}
```

- Use private subnets in at least two AgentCore-supported Availability Zones. Check a subnet's
  zone ID with `aws ec2 describe-subnets --subnet-ids <id> --query 'Subnets[0].AvailabilityZoneId'`.
- The workload must reach S3, Bedrock Runtime, Bedrock AgentCore, Step Functions and CloudWatch
  Logs. Either let the stack create endpoints (`createVpcEndpoints: true`, choosing them with the
  `endpoints` flags), or provide a NAT gateway or endpoints of your own.
- S3 must be reachable even for agent startup, because AgentCore fetches the agent code from S3
  through your VPC.
- The S3 endpoint is a gateway endpoint. It needs `routeTableIds`, one per subnet, in the same
  order as `subnetIds`. If your VPC already has an S3 endpoint, set `endpoints.s3` to false and
  make sure its policy allows the buckets above.
- `cdk deploy` looks up the VPC, so it needs credentials for the target account. The lookup is
  cached in `cdk.context.json`.

## Per-run settings

Pass overrides under `config` when you start an execution:

```json
{
  "bucket": "<InputBucketName>",
  "key": "drawings/area-7.pdf",
  "config": {
    "modelId": "global.anthropic.claude-opus-5-5",
    "review": { "maxViews": 80 },
    "dashedAsPiping": true,
    "pdf": { "dpi": 400 }
  }
}
```

Nested objects are merged with the deployed defaults, so `"review": {"maxViews": 80}` keeps
`review.enabled`. The merged config is saved in `<execution name>/input.json`. Bad values fail the
run in `PrepareInput` with an `InputError` and are not retried.

The execution name becomes the S3 prefix of the run's outputs. Name runs yourself (`--name`) so
the prefixes are easy to find. Runs started by the upload trigger get generated names.
