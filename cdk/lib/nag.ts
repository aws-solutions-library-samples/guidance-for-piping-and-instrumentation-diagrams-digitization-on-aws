import * as cdk from 'aws-cdk-lib';
import { IConstruct } from 'constructs';
import { NagSuppressions } from 'cdk-nag';

/** Findings on the Lambdas CDK adds for its own custom resources (bucket auto-delete and
 * notifications, default security group restriction). They run at deployment time only. */
export function suppressCdkHelperFindings(stack: cdk.Stack): void {
  NagSuppressions.addStackSuppressions(stack, [
    {
      id: 'AwsSolutions-IAM4',
      reason: 'CDK-managed custom resource handlers use the AWS managed Lambda basic execution policy',
      appliesTo: ['Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole'],
    },
    {
      id: 'AwsSolutions-L1',
      reason: 'CDK-managed singleton Lambdas (bucket auto-delete, notifications, default SG restriction) pick their own runtime',
    },
  ]);
  cdk.Aspects.of(stack).add({
    visit(node: IConstruct): void {
      if (node instanceof cdk.CfnResource && node.cfnResourceType === 'AWS::Lambda::Function'
        && !node.node.path.includes('/Functions/')) {
        NagSuppressions.addResourceSuppressions(node, [
          { id: 'Prototype Security Nag Pack-LambdaInsideVPC', reason: 'CDK custom resource Lambda, deployment time only' },
          { id: 'AwsSolutions-L1', reason: 'CDK custom resource Lambda runtime is managed by CDK' },
        ]);
      }
    },
  });
}
