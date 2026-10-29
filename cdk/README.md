# P&ID Digitization CDK stack

Deploys the workflow described in the [top-level README](../README.md) as two stacks:

| Stack | Class | Contents |
|---|---|---|
| `PNIDDigitization-Network` | [`PNIDNetworkStack`](lib/network-stack.ts) | `Networking` |
| `PNIDDigitization` | [`PNIDDigitizationStack`](lib/pnid-digitization-stack.ts) | `Storage`, `Digitizer`, `Functions`, `Orchestration` |

The application stack imports the VPC, subnets and security group from the network stack. The
references are strong (`@aws-cdk/core:defaultCrossStackReferences` in `cdk.json`), so the network
stack cannot be deleted while the application stack uses it. The split exists because AgentCore
keeps its network interfaces in the subnets for up to 8 hours after a runtime is deleted. A failed
deploy or a `cdk destroy` of the application stack never has to wait for them. Set
`CDK_STACK_NAME` to change the name prefix of both stacks.

## What it creates

| Construct | Resources |
|---|---|
| `Storage` ([storage.ts](lib/constructs/storage.ts)) | Input and output buckets: KMS-encrypted (one customer managed key each), versioned, TLS only, public access blocked, access logs under `access-logs/`. EventBridge notifications are on for the input bucket. |
| `Digitizer` ([agent.ts](lib/constructs/agent.ts)) | AgentCore Runtime, a Python 3.13 zip deployment of [`agent/`](agent/) plus the `pidtwin` package. Its execution role can read and write the output bucket, invoke only the allowed Bedrock models, and send Step Functions task callbacks. |
| `Functions` ([functions.ts](lib/constructs/functions.ts)) | `PrepareInput`, `DispatchSheet` and `MergeSheets`: Python 3.13 Lambdas on arm64, from [`lambda/`](lambda/), with least-privilege grants. |
| `Orchestration` ([orchestration.ts](lib/constructs/orchestration.ts)) | Standard Step Functions state machine with logging and X-Ray tracing, plus the EventBridge upload rule. |
| `Networking` ([networking.ts](lib/constructs/networking.ts)) | By default a new isolated VPC: two private subnets placed by AgentCore-supported AZ ID, no internet or NAT gateway, flow logs, interface endpoints (bedrock-runtime, bedrock-agentcore, states, logs) and an S3 gateway endpoint (limited to buckets of this account plus AgentCore's code buckets), all with scoped endpoint policies. Alternatively an existing VPC (`vpc.vpcId`). The Lambdas and the agent runtime share one workload security group (HTTPS egress only). |

Settings are read from `config.json` over the defaults in `config.json.template`
([lib/config.ts](lib/config.ts)). See [Configuration](../docs/CONFIGURATION.md).

## Packaging

The agent and the Lambdas run on Linux arm64. [`lib/bundling.ts`](lib/bundling.ts) builds each
asset as follows:

1. Install the directory's `requirements.txt`, if it has one, with
   `uv pip install --python-platform aarch64-manylinux2014 --python-version 3.13 --only-binary=:all:`.
2. Copy in the handler.

   The Lambdas use the boto3 that ships with the Lambda runtime, so it isn't bundled. The agent
   bundles boto3, because AgentCore's zip runtime doesn't include it.
3. For the agent, PrepareInput and MergeSheets, also copy in
   [`../pidtwin/src/pidtwin`](../pidtwin/src/pidtwin).

This needs uv on the deploying machine, not Docker. Without uv, the same build runs in the
`public.ecr.aws/sam/build-python3.13` arm64 image. Asset hashes cover the source files and
requirements, so unchanged code is not re-uploaded.

## Checks

`cdk synth` runs [cdk-nag](https://github.com/cdklabs/cdk-nag) with the AWS Solutions pack and a
prototype security pack ([lib/prototype-security.ts](lib/prototype-security.ts)). Each suppression
in the code gives its reason.

One warning is left: *Bedrock Guardrails Exists*. The digitizer reads engineering drawings and
returns structured data. It does not chat with end users, so no guardrail is attached. If your
drawings can contain text that should never reach a model or its output, add a guardrail to the
model calls in `pidtwin/digitize/pipeline.py` and `review.py`.

## Commands

```bash
npm install
npx tsc --noEmit            # type-check
cdk synth                   # template + cdk-nag
cdk deploy --all
cdk destroy PNIDDigitization            # then, once AgentCore's ENIs are gone:
cdk destroy PNIDDigitization-Network
```

Python unit tests for the digitizer, the Lambdas and the agent entrypoint are in
[`../pidtwin/tests`](../pidtwin/tests).
