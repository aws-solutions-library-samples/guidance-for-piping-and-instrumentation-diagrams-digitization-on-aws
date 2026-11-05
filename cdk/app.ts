#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { loadConfig } from "./lib/config";
import { PNIDNetworkStack } from "./lib/network-stack";
import { PNIDDigitizationStack } from "./lib/pnid-digitization-stack";
import { PNIDSdmaStack } from "./lib/sdma-stack";
import { AwsSolutionsChecks } from "cdk-nag";
import { PrototypeSecurityNagPack } from "./lib/prototype-security";
import { stackDescription } from "./lib/solution";

const app = new cdk.App();

// Get environment details
// Region will be inferred from AWS profile or CDK_DEFAULT_REGION
const env: cdk.Environment = {
  account: process.env.CDK_DEFAULT_ACCOUNT || "<YOUR-AWS-ACCOUNT-ID>",
  region: process.env.CDK_DEFAULT_REGION || "us-east-1", // Change this to your desired region
};

// Validate that account is set
if (env.account === "<YOUR-AWS-ACCOUNT-ID>") {
  console.error(
    "ERROR: Please set your AWS account ID in app.ts or via CDK_DEFAULT_ACCOUNT environment variable"
  );
  console.error(
    "You can find your account ID by running: aws sts get-caller-identity"
  );
  process.exit(1);
}

// Two stacks: the network (deleted last, see lib/network-stack.ts) and the application
const stackName = process.env.CDK_STACK_NAME || "PNIDDigitization";
const config = loadConfig();
const network = new PNIDNetworkStack(app, `${stackName}-Network`, config, {
  env,
  // a supporting stack: its own id suffix, so one install is counted once (lib/solution.ts)
  description: stackDescription("network", "network"),
});
const digitization = new PNIDDigitizationStack(app, stackName, {
  env,
  description: stackDescription(),
  config,
  networking: network.networking,
});
// optional connector for Spatial Data Management on AWS (docs/SDMA_CONNECTOR.md)
if (config.sdma.enabled) {
  new PNIDSdmaStack(app, `${stackName}-Sdma`, {
    env,
    description: stackDescription("sdma", "sdma"),
    config,
    networking: network.networking,
    stateMachine: digitization.stateMachine,
    outputBucket: digitization.outputBucket,
  });
}

// Apply CDK Nag checks at the app level with verbose reporting
cdk.Aspects.of(app).add(
  new AwsSolutionsChecks({ verbose: true, reports: true })
);
cdk.Aspects.of(app).add(
  new PrototypeSecurityNagPack({ verbose: true, reports: true })
);

app.synth();
