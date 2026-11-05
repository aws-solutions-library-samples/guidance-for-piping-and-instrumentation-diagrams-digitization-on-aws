import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as sfn from 'aws-cdk-lib/aws-stepfunctions';
import { Construct } from 'constructs';
import { NagSuppressions } from 'cdk-nag';
import * as path from 'path';

import { pythonBundle } from './bundling';
import { StackConfig } from './config';
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

    const role = new iam.Role(this, 'ConnectorRole', {
      roleName: `${ROLE_PREFIX}${this.stackName}`.slice(0, 64),
      description: 'Assumed by SDMA to run the P&ID digitization connector',
      // both invocation functions usually share one role
      assumedBy: new iam.CompositePrincipal(...[...new Set(sdma.trustedRoleArns)].map((arn) => new iam.ArnPrincipal(arn))),
    });
    start.grantInvoke(role);
    // the wait step reads summary.json and ingests the plant files and overlays
    props.outputBucket.grantRead(role);

    NagSuppressions.addResourceSuppressions(start, [
      { id: 'AwsSolutions-IAM4', reason: 'AWS managed basic execution (and VPC access) policies for Lambda logging' },
    ], true);
    NagSuppressions.addResourceSuppressions(role, [{
      id: 'AwsSolutions-IAM5',
      reason: 'CDK grant wildcards: objects in the output bucket (run prefixes are per invocation) and versions of the bridge function',
    }], true);

    new cdk.CfnOutput(this, 'SdmaConnectorRoleArn', { value: role.roleArn, description: 'securityConfig.assumeRoleArn of the connector' });
    new cdk.CfnOutput(this, 'SdmaStartFunctionArn', { value: start.functionArn, description: 'lambdaConfig.functionArn of the connector' });
    new cdk.CfnOutput(this, 'OutputBucketName', { value: props.outputBucket.bucketName, description: 'Where the workflow writes each run' });
    new cdk.CfnOutput(this, 'RenderConnector', {
      value: `node sdma/render-connector.mjs ${this.stackName} > pnid-connector.json`,
      description: 'Run from cdk/ to render the connector configuration to paste into SDMA',
    });

    suppressCdkHelperFindings(this);
  }
}
