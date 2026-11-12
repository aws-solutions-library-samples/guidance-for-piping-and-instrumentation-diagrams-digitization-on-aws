import * as cdk from 'aws-cdk-lib';
import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as sfn from 'aws-cdk-lib/aws-stepfunctions';
import { Construct } from 'constructs';
import { NagSuppressions } from 'cdk-nag';
import * as path from 'path';

import { pythonBundle } from './bundling';
import { StackConfig, digitizationDefaults } from './config';
import { NetworkingConstruct } from './constructs/networking';
import { suppressCdkHelperFindings } from './nag';
import { userAgentEnvironment } from './solution';

/** SDMA requires derive connector roles to start with this. */
const ROLE_PREFIX = 'SpatialDataManagementContentDerivation-';

export interface PNIDSdmaStackProps extends cdk.StackProps {
  config: StackConfig;
  networking: NetworkingConstruct;
  stateMachine: sfn.IStateMachine;
  outputBucket: s3.IBucket;
  runtime: agentcore.IBedrockAgentRuntime;
}

/**
 * Optional connector for Spatial Data Management on AWS (docs/SDMA_CONNECTOR.md): the bridge Lambda the
 * connector invokes to start the workflow, and the role SDMA assumes to invoke it and to read the results.
 * The connector itself is configuration in SDMA, rendered from these outputs by sdma/render-connector.mjs.
 */
export class PNIDSdmaStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: PNIDSdmaStackProps) {
    super(scope, id, props);
    const { sdma } = props.config;

    const bundle = pythonBundle({ sourceDir: path.join(__dirname, '..', 'lambda', 'sdma_start') });
    const start = new lambda.Function(this, 'SdmaStart', {
      description: 'Starts the digitization workflow for a drawing handed over by the SDMA connector',
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.ARM_64,
      code: lambda.Code.fromAsset(bundle.path, bundle.options),
      handler: 'index.lambda_handler',
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
      logGroup: new logs.LogGroup(this, 'SdmaStartLogs', {
        retention: logs.RetentionDays.ONE_MONTH,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
      ...props.networking.getVpcConfig(),
      environment: {
        LOG_LEVEL: 'INFO',
        ...userAgentEnvironment(),
        STATE_MACHINE_ARN: props.stateMachine.stateMachineArn,
        CONTENT_BUCKET: sdma.contentBucketName,
        OUTPUT_BUCKET: props.outputBucket.bucketName,
      },
    });
    props.stateMachine.grantStartExecution(start);

    // prototype: SDMA stage connectors (cdk/sdma/stages/), the workflow's steps run one connector each
    const makeStage = (name: string, dir: string, includePidtwin: boolean, extra: Partial<lambda.FunctionProps>) => {
      const b = pythonBundle({ sourceDir: path.join(__dirname, '..', 'lambda', dir), includePidtwin });
      return new lambda.Function(this, name, {
        runtime: lambda.Runtime.PYTHON_3_13,
        architecture: lambda.Architecture.ARM_64,
        code: lambda.Code.fromAsset(b.path, b.options),
        handler: 'sdma.lambda_handler',
        timeout: cdk.Duration.minutes(1),
        memorySize: 256,
        logGroup: new logs.LogGroup(this, `${name}Logs`, {
          retention: logs.RetentionDays.ONE_MONTH,
          removalPolicy: cdk.RemovalPolicy.DESTROY,
        }),
        ...props.networking.getVpcConfig(),
        ...extra,
        environment: { LOG_LEVEL: 'INFO', ...userAgentEnvironment(), ...(extra.environment ?? {}) },
      });
    };
    const d = props.config.digitization;
    const render = makeStage('SdmaRenderPages', 'prepare_input', true, {
      description: 'SDMA stage 1: validate a drawing and render its pages',
      timeout: cdk.Duration.minutes(10),
      memorySize: 3008,
      ephemeralStorageSize: cdk.Size.gibibytes(4),
      environment: {
        INPUT_BUCKET: props.outputBucket.bucketName, // unused: SDMA drawings come from SOURCE_BUCKETS
        OUTPUT_BUCKET: props.outputBucket.bucketName,
        SOURCE_BUCKETS: JSON.stringify([sdma.contentBucketName]),
        DEFAULT_CONFIG: JSON.stringify(digitizationDefaults(d)),
        ALLOWED_MODEL_IDS: JSON.stringify(d.allowedModelIds),
      },
    });
    render.addToRolePolicy(new iam.PolicyStatement({
      actions: ['s3:GetObject'],
      resources: [`arn:aws:s3:::${sdma.contentBucketName}/*`],
    }));
    if (sdma.contentBucketKmsKeyArn) {
      render.addToRolePolicy(new iam.PolicyStatement({ actions: ['kms:Decrypt'], resources: [sdma.contentBucketKmsKeyArn] }));
    }
    props.outputBucket.grantReadWrite(render);
    const dispatch = makeStage('SdmaDigitizeSheet', 'dispatch_sheet', false, {
      description: 'SDMA stage 2: start the agent for one rendered page',
      environment: { AGENT_RUNTIME_ARN: props.runtime.agentRuntimeArn, OUTPUT_BUCKET: props.outputBucket.bucketName },
    });
    props.runtime.grantInvokeRuntime(dispatch);
    props.outputBucket.grantRead(dispatch);
    const merge = makeStage('SdmaMergePlant', 'merge_sheets', true, {
      description: 'SDMA stage 3: merge the sheet graphs once every sheet of a run has a result',
      timeout: cdk.Duration.minutes(5),
      memorySize: 1024,
      environment: { OUTPUT_BUCKET: props.outputBucket.bucketName, CONTENT_BUCKET: sdma.contentBucketName },
    });
    props.outputBucket.grantReadWrite(merge);
    merge.addToRolePolicy(new iam.PolicyStatement({
      actions: ['s3:GetObject'],
      resources: [`arn:aws:s3:::${sdma.contentBucketName}/*`],
    }));
    if (sdma.contentBucketKmsKeyArn) {
      merge.addToRolePolicy(new iam.PolicyStatement({ actions: ['kms:Decrypt'], resources: [sdma.contentBucketKmsKeyArn] }));
    }

    const role = new iam.Role(this, 'ConnectorRole', {
      roleName: `${ROLE_PREFIX}${this.stackName}`.slice(0, 64),
      description: 'Assumed by SDMA to run the P&ID digitization connector',
      // both invocation functions usually share one role
      assumedBy: new iam.CompositePrincipal(...[...new Set(sdma.trustedRoleArns)].map((arn) => new iam.ArnPrincipal(arn))),
    });
    start.grantInvoke(role);
    render.grantInvoke(role);
    dispatch.grantInvoke(role);
    merge.grantInvoke(role);
    // the wait step reads summary.json and ingests the plant files and overlays
    props.outputBucket.grantRead(role);

    NagSuppressions.addResourceSuppressions(start, [
      { id: 'AwsSolutions-IAM4', reason: 'AWS managed basic execution (and VPC access) policies for Lambda logging' },
    ], true);
    for (const fn of [render, dispatch, merge]) {
      NagSuppressions.addResourceSuppressions(fn, [
        { id: 'AwsSolutions-IAM4', reason: 'AWS managed basic execution (and VPC access) policies for Lambda logging' },
        {
          id: 'AwsSolutions-IAM5',
          reason: 'CDK grant wildcards on objects in the output bucket and its key, the SDMA content bucket, '
            + 'and the agent runtime endpoints (<runtime ARN>/*)',
        },
      ], true);
    }
    NagSuppressions.addResourceSuppressions(role, [{
      id: 'AwsSolutions-IAM5',
      reason: 'CDK grant wildcards: objects in the output bucket (run prefixes are per invocation) and versions of the bridge function',
    }], true);

    new cdk.CfnOutput(this, 'SdmaConnectorRoleArn', { value: role.roleArn, description: 'securityConfig.assumeRoleArn of the connector' });
    new cdk.CfnOutput(this, 'SdmaStartFunctionArn', { value: start.functionArn, description: 'lambdaConfig.functionArn of the connector' });
    new cdk.CfnOutput(this, 'SdmaRenderPagesFunctionArn', { value: render.functionArn, description: 'Stage 1 connector function (prototype)' });
    new cdk.CfnOutput(this, 'SdmaDigitizeSheetFunctionArn', { value: dispatch.functionArn, description: 'Stage 2 connector function (prototype)' });
    new cdk.CfnOutput(this, 'SdmaMergePlantFunctionArn', { value: merge.functionArn, description: 'Stage 3 connector function (prototype)' });
    new cdk.CfnOutput(this, 'OutputBucketName', { value: props.outputBucket.bucketName, description: 'Where the workflow writes each run' });
    new cdk.CfnOutput(this, 'RenderConnector', {
      value: `node sdma/render-connector.mjs ${this.stackName} > pnid-connector.json`,
      description: 'Run from cdk/ to render the connector configuration to paste into SDMA',
    });

    suppressCdkHelperFindings(this);
  }
}
