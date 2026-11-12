# SDMA connector

[Spatial Data Management on AWS](https://docs.aws.amazon.com/solutions/latest/spatial-data-management-on-aws/)
(SDMA) keeps governed, versioned assets and runs
[connectors](https://docs.aws.amazon.com/solutions/latest/spatial-data-management-on-aws/connectors-overview.html)
when they change. This Guidance can deploy a connector so that each P&ID uploaded to an SDMA asset is
digitized automatically. The plant graph, DEXPI export, rule violations and sheet overlays come back
as derived files of the drawing, and the run's status and counts become metadata on it.

The connector is optional and off by default. Without it, nothing below is deployed.

## How it works

```
SDMA asset: upload area-7.pdf
  └─ connector "P&ID digitization" (approved on the asset template)
       1. lambdaInvoke  SdmaStart ──StartExecution──> digitization workflow (name = invocation id)
                                                       reads the drawing in place from SDMA's content bucket
                                                       writes s3://<OutputBucket>/<invocation id>/...
       2. wait          polls the output prefix every 60 s; no compute is held while waiting
            on success: derived files  plant.dexpi.xml, plant.graph.json, plant.issues.json,
                                       overlays/<sheet>.overlay.png (previews)
                        file metadata  pnidStatus, pnidSheets, pnidSheetsSucceeded, pnidNodes,
                                       pnidEdges, pnidModelId, pnidCostUsd, pnidExecutionArn
            on _FAILED.json: the invocation fails with the workflow's error
```

- **Why a Lambda step.** SDMA signs `rest` steps with Signature Version 4 for SageMaker, Lambda,
  Bedrock and API Gateway only, so it cannot call Step Functions directly. `SdmaStart` is a small
  function that checks the request and starts the execution.
- **One run per file version.** The execution is named after the connector invocation, so its output
  prefix is known to the wait step, and a retried step does not start a second run.
- **Partial runs.** If some sheets fail, the run's plant graph covers the sheets that succeeded. SDMA
  ingests it and sets `pnidStatus` to `PARTIAL`. If every sheet fails, or the drawing cannot be read,
  the workflow writes `_FAILED.json` and the connector invocation fails.
- **Re-running.** Run the connector on demand from the file in the Spatial Data Portal. The trigger
  takes optional `modelId`, `detect` (`tiled` or `single`) and `reviewModelId` parameters. Leave
  them empty for the deployment defaults. Models must be in `digitization.allowedModelIds`.

### Networking

By default this Guidance runs in its own VPC, separate from SDMA's. The two need no network path
between them, because every call goes through an AWS API:

- SDMA's connector Lambda assumes the connector role and invokes `SdmaStart` through its STS and
  Lambda endpoints, and reads the results through its S3 endpoint.
- The Guidance reads drawings from SDMA's content bucket through its own S3 gateway endpoint.

IAM roles and bucket permissions control access; neither VPC needs a route to the other.

You can deploy into SDMA's VPC instead, with `vpc.vpcId`, `vpc.subnetIds` and `vpc.routeTableIds`
(see [Configuration](CONFIGURATION.md#vpc-and-endpoints-networking)). That saves the cost of a
second set of interface endpoints, but it changes SDMA's network:

- SDMA's VPC has no endpoints for Bedrock Runtime, Bedrock AgentCore or Step Functions, so they
  must be added to it. Either set `vpc.createVpcEndpoints` with only `endpoints.bedrockRuntime`,
  `endpoints.agentCore` and `endpoints.stepFunctions` turned on, or add them yourself. SDMA's VPC
  already has CloudWatch Logs and S3 endpoints, and a second Logs endpoint with private DNS would
  conflict with it.
- SDMA's S3 gateway endpoint allows only principals of your account. AgentCore Runtime fetches the
  agent's code from service-owned `acr-code-*` buckets as the AgentCore service, so that endpoint's
  policy needs the same extra statement as this Guidance's own S3 endpoint
  (`cdk/lib/constructs/networking.ts`). Otherwise the agent cannot start.
- The subnets must be in Availability Zones where AgentCore Runtime supports VPC connectivity.

Keeping a separate VPC is simpler: the Guidance then deploys and deletes without touching SDMA.

## Prerequisites

- SDMA deployed in the same account and Region as this Guidance.
- This Guidance's prerequisites (see the [README](../README.md#prerequisites)).

## 1. Find the SDMA values

Run these in the SDMA deployment's Region:

```bash
# roles SDMA uses with the connector: the two invocation functions run it (they usually share a
# role), and ResourceOperationFunction test-assumes the role when you create the connector
for f in ConnectorInvocationFunction ConnectorInvocationAsyncFunction ResourceOperationFunction; do
  aws lambda get-function-configuration --function-name SpatialDataManagement-$f --query Role --output text
done

# content bucket: the AssetBucketName output of SDMA's AssetManagementStack nested stack
aws cloudformation describe-stacks \
  --stack-name "$(aws cloudformation describe-stack-resources --stack-name <sdma stack> \
      --query "StackResources[?starts_with(LogicalResourceId,'AssetManagementStack')].PhysicalResourceId" --output text)" \
  --query "Stacks[0].Outputs[?OutputKey=='AssetBucketName'].OutputValue" --output text

# its default encryption: leave contentBucketKmsKeyArn empty for AES256 (SSE-S3)
aws s3api get-bucket-encryption --bucket <content bucket> \
  --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault'
```

## 2. Deploy

Add the values to `cdk/config.json`:

```json
{
  "sdma": {
    "enabled": true,
    "contentBucketName": "<content bucket>",
    "contentBucketKmsKeyArn": "<key ARN, or empty>",
    "trustedRoleArns": ["<invocation role ARN>", "<resource operation role ARN>"]
  }
}
```

Then deploy as usual, in the SDMA Region:

```bash
cd cdk
AWS_REGION=<sdma region> cdk deploy --all
```

Besides the two usual stacks, this deploys `PNIDDigitization-Sdma` with:

- `SdmaStart`, the bridge function, in the Guidance's VPC;
- the role SDMA assumes, `SpatialDataManagementContentDerivation-PNIDDigitization-Sdma`. It may
  only invoke `SdmaStart` and read the output bucket.

It also lets `PrepareInput` read the content bucket, and allows `states:StartExecution` through the
Step Functions VPC endpoint.

## 3. Create the connector in SDMA

Render the connector configuration from the stack outputs:

```bash
AWS_REGION=<sdma region> node sdma/render-connector.mjs > pnid-connector.json
```

In the Spatial Data Portal:

1. Go to **Library settings** > **Connectors** > **Derive content**, and choose **Create deriver**.
2. Name it, choose the **AWS Lambda** connector type, paste `pnid-connector.json`, and choose
   **Create**. SDMA checks the configuration and that it can assume the role.
3. Open the asset template for your drawings and add the connector to its permitted connectors.
   The connector runs only for assets created from templates that permit it.

## 4. Try it

Create an asset from that template and upload a drawing, for example
`samples/synthetic_pid_1001.png`. The file's connector invocations show the run as in progress
until the workflow finishes, typically a few minutes per sheet. The derived files then appear under
the drawing.

To follow the run in Step Functions, open the execution named after the invocation id, or the
`pnidExecutionArn` metadata once it is set.

## Cleanup

Remove the connector from the asset templates and delete it in SDMA first. Then, with
`sdma.enabled` still `true`:

```bash
cdk destroy PNIDDigitization-Sdma
```

The connector stack uses exports of the application stack, so destroy it before you turn
`sdma.enabled` off and redeploy, or before you destroy `PNIDDigitization` (see the
[README](../README.md#cleanup)).
