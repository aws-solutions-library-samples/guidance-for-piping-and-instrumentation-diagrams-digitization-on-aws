#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { PNIDDigitizationStack } from './lib/pnid-digitization-stack';
import { AwsSolutionsChecks } from 'cdk-nag';
import { PrototypeSecurityNagPack } from './lib/prototype-security';

const app = new cdk.App();

// Get environment details
// Region will be inferred from AWS profile or CDK_DEFAULT_REGION
const env: cdk.Environment = {
  account: process.env.CDK_DEFAULT_ACCOUNT || '<YOUR-AWS-ACCOUNT-ID>',
  region: process.env.CDK_DEFAULT_REGION || 'us-east-1'  // Change this to your desired region
};

// Validate that account is set
if (env.account === '<YOUR-AWS-ACCOUNT-ID>') {
  console.error('ERROR: Please set your AWS account ID in app.ts or via CDK_DEFAULT_ACCOUNT environment variable');
  console.error('You can find your account ID by running: aws sts get-caller-identity');
  process.exit(1);
}

// Create the main digitization stack with flexible naming
const stackName = process.env.CDK_STACK_NAME || 'PNIDDigitization';
new PNIDDigitizationStack(app, stackName, {
  env,
  description: 'P&ID Digitization Pipeline with ML Symbol Detection and Line Detection',
});

// Apply CDK Nag checks at the app level with verbose reporting
cdk.Aspects.of(app).add(new AwsSolutionsChecks({ verbose: true, reports: true }));
cdk.Aspects.of(app).add(new PrototypeSecurityNagPack({ verbose: true, reports: true }));

app.synth();
