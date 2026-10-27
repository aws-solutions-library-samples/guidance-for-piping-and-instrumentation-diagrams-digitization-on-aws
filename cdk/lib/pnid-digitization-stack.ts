import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { NagSuppressions } from 'cdk-nag';

import { StackConfig } from './config';
import { DigitizerAgent } from './constructs/agent';
import { FunctionsConstruct } from './constructs/functions';
import { NetworkingConstruct } from './constructs/networking';
import { suppressCdkHelperFindings } from './nag';
import { OrchestrationConstruct } from './constructs/orchestration';
import { StorageConstruct } from './constructs/storage';

const HEARTBEAT_SECONDS = 60;

export interface PNIDDigitizationStackProps extends cdk.StackProps {
  config: StackConfig;
  /** From the network stack (PNIDNetworkStack). */
  networking: NetworkingConstruct;
}

/** Buckets, agent runtime, Lambdas and workflow. The network lives in PNIDNetworkStack. */
export class PNIDDigitizationStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: PNIDDigitizationStackProps) {
    super(scope, id, props);

    const { config, networking } = props;
    const storage = new StorageConstruct(this, 'Storage');

    const vpcConfig = networking.getVpcConfig();

    const sheetTimeout = cdk.Duration.minutes(config.orchestration.sheetTimeoutMinutes);
    const agent = new DigitizerAgent(this, 'Digitizer', {
      outputBucket: storage.outputBucket,
      allowedModelIds: config.digitization.allowedModelIds,
      sheetTimeout,
      heartbeatSeconds: HEARTBEAT_SECONDS,
      vpcConfig,
    });

    const functions = new FunctionsConstruct(this, 'Functions', {
      inputBucket: storage.inputBucket,
      outputBucket: storage.outputBucket,
      runtime: agent.runtime,
      digitization: config.digitization,
      vpcConfig,
    });

    const orchestration = new OrchestrationConstruct(this, 'Orchestration', {
      inputBucket: storage.inputBucket,
      prepareInput: functions.prepareInput,
      dispatchSheet: functions.dispatchSheet,
      mergeSheets: functions.mergeSheets,
      maxConcurrentSheets: config.orchestration.maxConcurrentSheets,
      sheetTimeout,
      heartbeatTimeout: cdk.Duration.seconds(HEARTBEAT_SECONDS * 5),
      uploadTrigger: config.orchestration.uploadTrigger,
    });

    NagSuppressions.addStackSuppressions(this, [
      {
        id: 'AwsSolutions-S1',
        reason: 'Server access logs go to an access-logs/ prefix in each bucket (a separate log bucket is left to the deployer)',
      },
    ]);

    const trigger = config.orchestration.uploadTrigger;
    new cdk.CfnOutput(this, 'Usage', {
      value: (trigger.enabled
        ? `Upload a P&ID (PDF or image) to s3://${storage.inputBucket.bucketName}/${trigger.prefix} to start, or start `
        : 'Start ')
        + `${orchestration.stateMachine.stateMachineName} with {"bucket": "${storage.inputBucket.bucketName}", "key": "<key>"}. `
        + `Results: s3://${storage.outputBucket.bucketName}/<execution name>/`,
      description: 'How to run the P&ID digitization workflow',
    });
    new cdk.CfnOutput(this, 'DefaultModel', {
      value: config.digitization.modelId,
      description: 'Bedrock model used unless an execution sets config.modelId',
    });
    new cdk.CfnOutput(this, 'VpcConfigurationStatus', {
      value: networking.created
        ? 'Lambdas and agent runtime in a stack-created isolated VPC (no internet access; VPC endpoints only)'
        : `Lambdas and agent runtime in VPC ${config.vpc.vpcId}`,
      description: 'Network placement of the workload',
    });

    suppressCdkHelperFindings(this);
  }
}
