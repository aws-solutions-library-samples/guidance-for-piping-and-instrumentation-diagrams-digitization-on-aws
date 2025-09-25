import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import { Construct } from 'constructs';
import { NagSuppressions } from 'cdk-nag';

export interface LambdaRolesConstructProps {
  inputBucket: s3.Bucket;
  outputBucket: s3.Bucket;
  inputBucketKey: kms.Key;
  outputBucketKey: kms.Key;
  sagemakerInvokePolicy: iam.PolicyStatement;
  bdaProject: bedrock.CfnDataAutomationProject;
  // Optional VPC configuration
  vpcConfig?: {
    vpc: ec2.IVpc;
    vpcSubnets: ec2.SubnetSelection;
    securityGroups: ec2.SecurityGroup[];
  };
}

export interface LambdaRoles {
  inputValidatorRole: iam.Role;
  lineDetectionRole: iam.Role;
  graphGeneratorRole: iam.Role;
  graphVisualizationRole: iam.Role;
  symbolDetectionRole: iam.Role;
  textDetectionRole: iam.Role;
  notesProcessorRole: iam.Role;
}

export class LambdaRolesConstruct extends Construct {
  public readonly roles: LambdaRoles;

  constructor(scope: Construct, id: string, props: LambdaRolesConstructProps) {
    super(scope, id);

    // Get account and region from stack
    const account = cdk.Stack.of(this).account;
    const region = cdk.Stack.of(this).region;

    // Create common Lambda execution role base policy
    const lambdaBasePolicy = new iam.PolicyDocument({
      statements: [
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: [
            'logs:CreateLogGroup',
            'logs:CreateLogStream',
            'logs:PutLogEvents',
          ],
          resources: [
            `arn:aws:logs:${region}:${account}:log-group:/aws/lambda/*`,
          ],
        }),
      ],
    });

    // Add VPC permissions if VPC is configured
    const baseVpcPolicy = props.vpcConfig ? new iam.PolicyDocument({
      statements: [
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: [
            'ec2:CreateNetworkInterface',
            'ec2:DescribeNetworkInterfaces',
            'ec2:DeleteNetworkInterface',
            'ec2:AttachNetworkInterface',
            'ec2:DetachNetworkInterface',
          ],
          resources: ['*'],
        }),
      ],
    }) : undefined;

    // Create all IAM roles
    this.roles = {
      inputValidatorRole: this.createInputValidatorRole(lambdaBasePolicy, baseVpcPolicy, props),
      lineDetectionRole: this.createLineDetectionRole(lambdaBasePolicy, baseVpcPolicy, props),
      graphGeneratorRole: this.createGraphGeneratorRole(lambdaBasePolicy, baseVpcPolicy, props),
      graphVisualizationRole: this.createGraphVisualizationRole(lambdaBasePolicy, baseVpcPolicy, props),
      symbolDetectionRole: this.createSymbolDetectionRole(lambdaBasePolicy, baseVpcPolicy, props),
      textDetectionRole: this.createTextDetectionRole(lambdaBasePolicy, baseVpcPolicy, props, account),
      notesProcessorRole: this.createNotesProcessorRole(lambdaBasePolicy, baseVpcPolicy, props),
    };

    // Add CDK Nag suppressions for all Lambda roles
    this.addNagSuppressions();
  }

  private createInputValidatorRole(
    lambdaBasePolicy: iam.PolicyDocument,
    baseVpcPolicy: iam.PolicyDocument | undefined,
    props: LambdaRolesConstructProps
  ): iam.Role {
    const inputValidatorPolicies: { [key: string]: iam.PolicyDocument } = {
      BasePolicy: lambdaBasePolicy,
      S3Access: new iam.PolicyDocument({
        statements: [
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              's3:GetObject',
              's3:PutObject',
            ],
            resources: [
              `${props.inputBucket.bucketArn}/*`,
              `${props.outputBucket.bucketArn}/*`,
            ],
          }),
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              'kms:Decrypt',
              'kms:GenerateDataKey',
            ],
            resources: [
              props.inputBucketKey.keyArn,
              props.outputBucketKey.keyArn,
            ],
          }),
        ],
      }),
    };

    if (baseVpcPolicy) {
      inputValidatorPolicies.VpcAccess = baseVpcPolicy;
    }

    return new iam.Role(this, 'InputValidatorRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: 'IAM role for input validator Lambda function',
      inlinePolicies: inputValidatorPolicies,
    });
  }

  private createLineDetectionRole(
    lambdaBasePolicy: iam.PolicyDocument,
    baseVpcPolicy: iam.PolicyDocument | undefined,
    props: LambdaRolesConstructProps
  ): iam.Role {
    const lineDetectionPolicies: { [key: string]: iam.PolicyDocument } = {
      BasePolicy: lambdaBasePolicy,
      S3Access: new iam.PolicyDocument({
        statements: [
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              's3:ListBucket',
            ],
            resources: [
              props.inputBucket.bucketArn,
              props.outputBucket.bucketArn,
            ],
          }),
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              's3:GetObject',
            ],
            resources: [
              `${props.inputBucket.bucketArn}/*`,
              `${props.outputBucket.bucketArn}/*`,
            ],
          }),
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              's3:PutObject',
            ],
            resources: [
              `${props.outputBucket.bucketArn}/*`,
            ],
          }),
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              'kms:Decrypt',
            ],
            resources: [
              props.inputBucketKey.keyArn,
              props.outputBucketKey.keyArn,
            ],
          }),
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              'kms:GenerateDataKey',
            ],
            resources: [
              props.outputBucketKey.keyArn,
            ],
          }),
        ],
      }),
    };

    if (baseVpcPolicy) {
      lineDetectionPolicies.VpcAccess = baseVpcPolicy;
    }

    return new iam.Role(this, 'LineDetectionRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: 'IAM role for line detection Lambda function',
      inlinePolicies: lineDetectionPolicies,
    });
  }

  private createSymbolDetectionRole(
    lambdaBasePolicy: iam.PolicyDocument,
    baseVpcPolicy: iam.PolicyDocument | undefined,
    props: LambdaRolesConstructProps
  ): iam.Role {
    const symbolDetectionPolicies: { [key: string]: iam.PolicyDocument } = {
      BasePolicy: lambdaBasePolicy,
      S3Access: new iam.PolicyDocument({
        statements: [
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              's3:ListBucket',
            ],
            resources: [
              props.inputBucket.bucketArn,
              props.outputBucket.bucketArn,
            ],
          }),
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              's3:GetObject',
            ],
            resources: [
              `${props.inputBucket.bucketArn}/*`,
              `${props.outputBucket.bucketArn}/*`,
            ],
          }),
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              's3:PutObject',
            ],
            resources: [
              `${props.outputBucket.bucketArn}/*`,
            ],
          }),
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              'kms:Decrypt',
            ],
            resources: [
              props.inputBucketKey.keyArn,
              props.outputBucketKey.keyArn,
            ],
          }),
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              'kms:GenerateDataKey',
            ],
            resources: [
              props.outputBucketKey.keyArn,
            ],
          }),
        ],
      }),
      SageMakerAccess: new iam.PolicyDocument({
        statements: [props.sagemakerInvokePolicy],
      }),
    };

    if (baseVpcPolicy) {
      symbolDetectionPolicies.VpcAccess = baseVpcPolicy;
    }

    return new iam.Role(this, 'SymbolDetectionRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: 'IAM role for symbol detection Lambda function',
      inlinePolicies: symbolDetectionPolicies,
    });
  }

  private createGraphGeneratorRole(
    lambdaBasePolicy: iam.PolicyDocument,
    baseVpcPolicy: iam.PolicyDocument | undefined,
    props: LambdaRolesConstructProps
  ): iam.Role {
    const graphGeneratorPolicies: { [key: string]: iam.PolicyDocument } = {
      BasePolicy: lambdaBasePolicy,
      S3Access: new iam.PolicyDocument({
        statements: [
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              's3:GetObject',
              's3:PutObject',
            ],
            resources: [
              `${props.outputBucket.bucketArn}/*`,
            ],
          }),
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              'kms:Decrypt',
              'kms:GenerateDataKey',
            ],
            resources: [
              props.outputBucketKey.keyArn,
            ],
          }),
        ],
      }),
      SageMakerAccess: new iam.PolicyDocument({
        statements: [props.sagemakerInvokePolicy],
      }),
    };

    if (baseVpcPolicy) {
      graphGeneratorPolicies.VpcAccess = baseVpcPolicy;
    }

    return new iam.Role(this, 'GraphGeneratorRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: 'IAM role for graph generator Lambda function',
      inlinePolicies: graphGeneratorPolicies,
    });
  }

  private createGraphVisualizationRole(
    lambdaBasePolicy: iam.PolicyDocument,
    baseVpcPolicy: iam.PolicyDocument | undefined,
    props: LambdaRolesConstructProps
  ): iam.Role {
    const graphVisualizationPolicies: { [key: string]: iam.PolicyDocument } = {
      BasePolicy: lambdaBasePolicy,
      S3Access: new iam.PolicyDocument({
        statements: [
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              's3:ListBucket',
            ],
            resources: [
              props.inputBucket.bucketArn,
              props.outputBucket.bucketArn,
            ],
          }),
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              's3:GetObject',
            ],
            resources: [
              `${props.inputBucket.bucketArn}/*`,
              `${props.outputBucket.bucketArn}/*`,
            ],
          }),
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              's3:PutObject',
            ],
            resources: [
              `${props.outputBucket.bucketArn}/*`,
            ],
          }),
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              'kms:Decrypt',
            ],
            resources: [
              props.inputBucketKey.keyArn,
              props.outputBucketKey.keyArn,
            ],
          }),
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              'kms:GenerateDataKey',
            ],
            resources: [
              props.outputBucketKey.keyArn,
            ],
          }),
        ],
      }),
    };

    if (baseVpcPolicy) {
      graphVisualizationPolicies.VpcAccess = baseVpcPolicy;
    }

    return new iam.Role(this, 'GraphVisualizationRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: 'IAM role for graph visualization Lambda function',
      inlinePolicies: graphVisualizationPolicies,
    });
  }

  private createTextDetectionRole(
    lambdaBasePolicy: iam.PolicyDocument,
    baseVpcPolicy: iam.PolicyDocument | undefined,
    props: LambdaRolesConstructProps,
    account: string
  ): iam.Role {
    const region = cdk.Stack.of(this).region;

    const textDetectionPolicies: { [key: string]: iam.PolicyDocument } = {
      BasePolicy: lambdaBasePolicy,
      S3Access: new iam.PolicyDocument({
        statements: [
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              's3:ListBucket',
            ],
            resources: [
              props.outputBucket.bucketArn,
            ],
          }),
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              's3:GetObject',
            ],
            resources: [
              `${props.inputBucket.bucketArn}/*`,
              `${props.outputBucket.bucketArn}/*`,
            ],
          }),
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              's3:PutObject',
            ],
            resources: [
              `${props.outputBucket.bucketArn}/*`,
            ],
          }),
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              'kms:Decrypt',
            ],
            resources: [
              props.inputBucketKey.keyArn,
              props.outputBucketKey.keyArn,
            ],
          }),
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              'kms:GenerateDataKey',
            ],
            resources: [
              props.outputBucketKey.keyArn,
            ],
          }),
        ],
      }),
      BedrockDataAutomationAccess: new iam.PolicyDocument({
        statements: [
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              'bedrock:InvokeDataAutomationAsync',
              'bedrock:GetDataAutomationStatus',
              'bedrock:GetDataAutomationOutput'
            ],
            resources: [
              props.bdaProject.attrProjectArn,
              `arn:aws:bedrock:*:${account}:data-automation-profile/us.data-automation-v1`,
              `arn:aws:bedrock:${region}:${account}:data-automation-invocation/*`
            ],
          }),
        ],
      }),
    };

    if (baseVpcPolicy) {
      textDetectionPolicies.VpcAccess = baseVpcPolicy;
    }

    return new iam.Role(this, 'TextDetectionRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: 'IAM role for text detection Lambda function',
      inlinePolicies: textDetectionPolicies,
    });
  }

  private createNotesProcessorRole(
    lambdaBasePolicy: iam.PolicyDocument,
    baseVpcPolicy: iam.PolicyDocument | undefined,
    props: LambdaRolesConstructProps
  ): iam.Role {
    const notesProcessorPolicies: { [key: string]: iam.PolicyDocument } = {
      BasePolicy: lambdaBasePolicy,
      S3Access: new iam.PolicyDocument({
        statements: [
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              's3:ListBucket',
            ],
            resources: [
              props.inputBucket.bucketArn,
              props.outputBucket.bucketArn,
            ],
          }),
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              's3:GetObject',
            ],
            resources: [
              `${props.inputBucket.bucketArn}/*`,
              `${props.outputBucket.bucketArn}/*`,
            ],
          }),
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              's3:PutObject',
            ],
            resources: [
              `${props.outputBucket.bucketArn}/*`,
            ],
          }),
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              'kms:Decrypt',
            ],
            resources: [
              props.inputBucketKey.keyArn,
              props.outputBucketKey.keyArn,
            ],
          }),
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
              'kms:GenerateDataKey',
            ],
            resources: [
              props.outputBucketKey.keyArn,
            ],
          }),
        ],
      }),
    };

    if (baseVpcPolicy) {
      notesProcessorPolicies.VpcAccess = baseVpcPolicy;
    }

    return new iam.Role(this, 'NotesProcessorRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: 'IAM role for notes processor Lambda function',
      inlinePolicies: notesProcessorPolicies,
    });
  }

  private addNagSuppressions(): void {
    const roles = [
      this.roles.inputValidatorRole,
      this.roles.lineDetectionRole,
      this.roles.graphGeneratorRole,
      this.roles.graphVisualizationRole,
      this.roles.symbolDetectionRole,
      this.roles.textDetectionRole,
      this.roles.notesProcessorRole,
    ];

    roles.forEach(role => {
      const suppressions = [
        {
          id: 'AwsSolutions-IAM5',
          reason: 'Lambda functions require wildcard permissions for CloudWatch logs and VPC networking',
        },
      ];

      NagSuppressions.addResourceSuppressions(role, suppressions);
    });
  }
}
