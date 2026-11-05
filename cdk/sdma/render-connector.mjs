#!/usr/bin/env node
// Prints the SDMA connector configuration for a deployed <stack>-Sdma stack, filled in from its outputs.
// Usage (from cdk/): node sdma/render-connector.mjs [<stack name, default PNIDDigitization>] > pnid-connector.json
// Uses the AWS CLI with the current credentials and Region (AWS_REGION / AWS_DEFAULT_REGION / profile).
import { execFileSync } from 'child_process';
import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const base = process.argv[2] || process.env.CDK_STACK_NAME || 'PNIDDigitization';
const stack = base.endsWith('-Sdma') ? base : `${base}-Sdma`;
const described = JSON.parse(execFileSync('aws', ['cloudformation', 'describe-stacks', '--stack-name', stack, '--output', 'json'],
  { encoding: 'utf8' }));
const outputs = Object.fromEntries((described.Stacks[0].Outputs || []).map((o) => [o.OutputKey, o.OutputValue]));
// the Region is the fourth field of the stack ARN
const values = { ...outputs, Region: described.Stacks[0].StackId.split(':')[3] };

const template = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'connector.template.json'), 'utf8');
const rendered = template.replace(/\{\{(\w+)\}\}/g, (_, key) => {
  if (!(key in values)) {
    throw new Error(`stack ${stack} has no output ${key}; is it deployed with sdma.enabled?`);
  }
  return values[key];
});
process.stdout.write(rendered);
