import * as cdk from 'aws-cdk-lib';
import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';
import { NagSuppressions } from 'cdk-nag';
import * as path from 'path';
import { pythonBundle } from '../bundling';
import { userAgentEnvironment } from '../solution';

export interface DigitizerAgentProps {
  outputBucket: s3.IBucket;
  allowedModelIds: string[];
  /** Upper bound on one sheet; the session's maximum lifetime is set a little above it. */
  sheetTimeout: cdk.Duration;
  heartbeatSeconds: number;
  vpcConfig?: { vpc: ec2.IVpc; vpcSubnets: ec2.SubnetSelection; securityGroups: ec2.ISecurityGroup[] };
}

/** Bedrock model and inference-profile ARNs an inference profile id (or plain model id) can route to. */
export function modelArns(modelId: string, region: string, account: string): string[] {
  const [prefix, ...rest] = modelId.split('.');
  const geo = ['us', 'eu', 'apac', 'jp', 'au', 'ca', 'global'];
  if (!geo.includes(prefix)) {
    return [`arn:aws:bedrock:${region}::foundation-model/${modelId}`];
  }
  const base = rest.join('.');
  return [
    `arn:aws:bedrock:${region}:${account}:inference-profile/${modelId}`,
    // a cross-Region profile routes to the model in any Region of its geography; global ones have no Region
    `arn:aws:bedrock:*::foundation-model/${base}`,
    ...(prefix === 'global' ? [`arn:aws:bedrock:::foundation-model/${base}`] : []),
  ];
}

/** AgentCore Runtime hosting the per-sheet digitizer (cdk/agent/main.py), deployed as a zip (no container). */
export class DigitizerAgent extends Construct {
  public readonly runtime: agentcore.Runtime;

  constructor(scope: Construct, id: string, props: DigitizerAgentProps) {
    super(scope, id);
    const stack = cdk.Stack.of(this);

    const bundle = pythonBundle({ sourceDir: path.join(__dirname, '..', '..', 'agent'), includePidtwin: true });
    const maxLifetime = cdk.Duration.minutes(Math.min(props.sheetTimeout.toMinutes() + 15, 480));

    this.runtime = new agentcore.Runtime(this, 'Runtime', {
      runtimeName: `${stack.stackName.replace(/[^A-Za-z0-9]/g, '')}_digitizer`.slice(0, 48),
      description: 'Digitizes one P&ID sheet per session: detect, trace, review agent, plant graph',
      agentRuntimeArtifact: agentcore.AgentRuntimeArtifact.fromCodeAsset({
        path: bundle.path,
        ...bundle.options,
        runtime: agentcore.AgentCoreRuntime.PYTHON_3_13,
        entrypoint: ['main.py'],
      }),
      networkConfiguration: props.vpcConfig
        ? agentcore.RuntimeNetworkConfiguration.usingVpc(this, {
          vpc: props.vpcConfig.vpc,
          vpcSubnets: props.vpcConfig.vpcSubnets,
          securityGroups: props.vpcConfig.securityGroups,
        })
        : agentcore.RuntimeNetworkConfiguration.usingPublicNetwork(),
      lifecycleConfiguration: {
        idleRuntimeSessionTimeout: cdk.Duration.minutes(15),
        maxLifetime,
      },
      environmentVariables: {
        OUTPUT_BUCKET: props.outputBucket.bucketName,
        ALLOWED_MODEL_IDS: JSON.stringify(props.allowedModelIds),
        HEARTBEAT_SECONDS: String(props.heartbeatSeconds),
        LOG_LEVEL: 'INFO',
        ...userAgentEnvironment(),
      },
    });

    props.outputBucket.grantReadWrite(this.runtime.role);
    this.runtime.role.addToPrincipalPolicy(new iam.PolicyStatement({
      sid: 'InvokeAllowedModels',
      actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
      resources: [...new Set(props.allowedModelIds.flatMap((m) => modelArns(m, stack.region, stack.account)))],
    }));
    this.runtime.role.addToPrincipalPolicy(new iam.PolicyStatement({
      sid: 'StepFunctionsCallback',
      actions: ['states:SendTaskSuccess', 'states:SendTaskFailure', 'states:SendTaskHeartbeat'],
      resources: ['*'], // these actions do not support resource-level permissions
    }));

    NagSuppressions.addResourceSuppressions(this.runtime.role, [
      {
        id: 'AwsSolutions-IAM5',
        reason: 'Wildcards: AgentCore log groups and streams, X-Ray, CloudWatch metrics (namespace-conditioned), '
          + 'the output bucket objects, foundation models in every Region of a cross-Region inference profile, '
          + 'and Step Functions task callbacks, which have no resource-level permissions',
      },
    ], true);

    new cdk.CfnOutput(this, 'AgentRuntimeArn', {
      value: this.runtime.agentRuntimeArn,
      description: 'AgentCore Runtime that digitizes one sheet per session',
    });
  }
}
