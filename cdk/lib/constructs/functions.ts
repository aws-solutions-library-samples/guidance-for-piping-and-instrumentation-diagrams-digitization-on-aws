import * as cdk from 'aws-cdk-lib';
import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';
import { NagSuppressions } from 'cdk-nag';
import * as path from 'path';
import { pythonBundle } from '../bundling';
import { DigitizationConfig, digitizationDefaults } from '../config';

export interface FunctionsConstructProps {
  inputBucket: s3.IBucket;
  outputBucket: s3.IBucket;
  runtime: agentcore.IBedrockAgentRuntime;
  digitization: DigitizationConfig;
  vpcConfig?: { vpc: ec2.IVpc; vpcSubnets: ec2.SubnetSelection; securityGroups: ec2.ISecurityGroup[] };
}

/** The three Lambdas around the agent: PrepareInput, DispatchSheet, MergeSheets. */
export class FunctionsConstruct extends Construct {
  public readonly prepareInput: lambda.Function;
  public readonly dispatchSheet: lambda.Function;
  public readonly mergeSheets: lambda.Function;

  constructor(scope: Construct, id: string, props: FunctionsConstructProps) {
    super(scope, id);

    const make = (name: string, dir: string, includePidtwin: boolean, extra: Partial<lambda.FunctionProps>) => {
      const bundle = pythonBundle({ sourceDir: path.join(__dirname, '..', '..', 'lambda', dir), includePidtwin });
      const fn = new lambda.Function(this, name, {
        runtime: lambda.Runtime.PYTHON_3_13,
        architecture: lambda.Architecture.ARM_64,
        code: lambda.Code.fromAsset(bundle.path, bundle.options),
        handler: 'index.lambda_handler',
        timeout: cdk.Duration.minutes(1),
        memorySize: 256,
        logGroup: new logs.LogGroup(this, `${name}Logs`, {
          retention: logs.RetentionDays.ONE_MONTH,
          removalPolicy: cdk.RemovalPolicy.DESTROY,
        }),
        ...(props.vpcConfig ?? {}),
        ...extra,
        environment: { LOG_LEVEL: 'INFO', ...(extra.environment ?? {}) },
      });
      if (!props.vpcConfig) {
        NagSuppressions.addResourceSuppressions(fn, [{
          id: 'Prototype Security Nag Pack-LambdaInsideVPC',
          reason: 'VPC deployment is optional; set vpc.vpcId and vpc.subnetIds in config.json to enable it',
        }]);
      }
      return fn;
    };

    this.prepareInput = make('PrepareInput', 'prepare_input', true, {
      description: 'Validates a drawing, merges config, renders PDF pages to PNG',
      timeout: cdk.Duration.minutes(10),
      memorySize: 3008,
      ephemeralStorageSize: cdk.Size.gibibytes(4),
      environment: {
        INPUT_BUCKET: props.inputBucket.bucketName,
        OUTPUT_BUCKET: props.outputBucket.bucketName,
        DEFAULT_CONFIG: JSON.stringify(digitizationDefaults(props.digitization)),
        ALLOWED_MODEL_IDS: JSON.stringify(props.digitization.allowedModelIds),
      },
    });
    props.inputBucket.grantRead(this.prepareInput);
    props.outputBucket.grantWrite(this.prepareInput);

    this.dispatchSheet = make('DispatchSheet', 'dispatch_sheet', false, {
      description: 'Starts one AgentCore Runtime session per sheet and returns',
      environment: { AGENT_RUNTIME_ARN: props.runtime.agentRuntimeArn },
    });
    props.runtime.grantInvokeRuntime(this.dispatchSheet);

    this.mergeSheets = make('MergeSheets', 'merge_sheets', true, {
      description: 'Stitches sheet graphs into the plant graph and writes the execution summary',
      timeout: cdk.Duration.minutes(5),
      memorySize: 1024,
    });
    props.outputBucket.grantReadWrite(this.mergeSheets);

    // after the grants, so the suppressions reach the generated policies
    for (const fn of [this.prepareInput, this.dispatchSheet, this.mergeSheets]) {
      NagSuppressions.addResourceSuppressions(fn, [
        { id: 'AwsSolutions-IAM4', reason: 'AWS managed basic execution (and VPC access) policies for Lambda logging' },
        {
          id: 'AwsSolutions-IAM5',
          reason: 'CDK grant wildcards scoped to this stack: objects in its own buckets, their KMS keys, '
            + 'and the agent runtime\'s endpoints (<runtime ARN>/*)',
        },
      ], true);
    }
  }
}
