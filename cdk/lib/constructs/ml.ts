import * as cdk from 'aws-cdk-lib';
import * as sagemaker from 'aws-cdk-lib/aws-sagemaker';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as kms from 'aws-cdk-lib/aws-kms';
import { Construct } from 'constructs';
import { NagSuppressions } from 'cdk-nag';

export interface MLConstructProps {
  modelS3Uri: string;
}

export class MLConstruct extends Construct {
  public readonly sagemakerRole: iam.Role;
  public readonly model: sagemaker.CfnModel;
  public readonly endpointConfig: sagemaker.CfnEndpointConfig;
  public readonly endpoint: sagemaker.CfnEndpoint;

  constructor(scope: Construct, id: string, props: MLConstructProps) {
    super(scope, id);

    // Get account and region from stack
    const account = cdk.Stack.of(this).account;
    const region = cdk.Stack.of(this).region;

    // Extract bucket and key from the S3 URI
    const s3UriParts = props.modelS3Uri.replace('s3://', '').split('/');
    const modelBucket = s3UriParts[0];
    const modelKey = s3UriParts.slice(1).join('/');

    // Create SageMaker execution role
    this.sagemakerRole = new iam.Role(this, 'SageMakerExecutionRole', {
      assumedBy: new iam.ServicePrincipal('sagemaker.amazonaws.com'),
      description: 'IAM role for SageMaker symbol detection endpoint',
      inlinePolicies: {
        ModelArtifactsAccess: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: [
                's3:GetObject',
                's3:ListBucket',
              ],
              resources: [
                `arn:aws:s3:::${modelBucket}`,
                `arn:aws:s3:::${modelBucket}/*`,
              ],
            }),
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: [
                'kms:Decrypt',
                'kms:DescribeKey',
              ],
              resources: ['*'],
              conditions: {
                StringEquals: {
                  'kms:ViaService': [
                    `s3.${region}.amazonaws.com`,
                  ],
                },
              },
            }),
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: [
                'logs:CreateLogGroup',
                'logs:CreateLogStream',
                'logs:PutLogEvents',
              ],
              resources: [
                `arn:aws:logs:${region}:${account}:log-group:/aws/sagemaker/*`,
              ],
            }),
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: [
                'ecr:GetAuthorizationToken',
              ],
              resources: ['*'],
            }),
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: [
                'ecr:BatchCheckLayerAvailability',
                'ecr:GetDownloadUrlForLayer',
                'ecr:BatchGetImage',
              ],
              resources: [
                `arn:aws:ecr:${region}:763104351884:repository/*`,
              ],
            }),
          ],
        }),
      },
    });

    // Add CDK Nag suppressions for the SageMaker role
    NagSuppressions.addResourceSuppressions(this.sagemakerRole, [
      {
        id: 'AwsSolutions-IAM5',
        reason: 'SageMaker requires wildcard permissions for: ' +
                '1) CloudWatch logs for log group creation, ' +
                '2) S3 model artifacts access within the bucket, ' +
                '3) KMS decrypt operations via S3 service, ' +
                '4) ECR GetAuthorizationToken which is an account-level permission, ' +
                '5) ECR repository access for AWS-managed deep learning containers',
      },
    ]);

    // SageMaker Model - will use model from the provided S3 URI
    this.model = new sagemaker.CfnModel(this, 'SymbolDetectionModel', {
      executionRoleArn: this.sagemakerRole.roleArn,
      primaryContainer: {
        image: `763104351884.dkr.ecr.${region}.amazonaws.com/pytorch-inference:2.6.0-gpu-py312-cu124-ubuntu22.04-sagemaker`,
        modelDataUrl: props.modelS3Uri,
      },
      // modelName: `symbol-detection-model-${cdk.Stack.of(this).stackName}`.toLowerCase(),
    });

    // SageMaker Endpoint Configuration
    this.endpointConfig = new sagemaker.CfnEndpointConfig(this, 'SymbolDetectionEndpointConfig', {
      productionVariants: [
        {
          variantName: 'primary',
          modelName: this.model.attrModelName,
          initialInstanceCount: 1,
          instanceType: 'ml.g4dn.2xlarge',
          initialVariantWeight: 1,
        },
      ],
      // endpointConfigName: `symbol-detection-config-${cdk.Stack.of(this).stackName}`.toLowerCase(),
    });

    // SageMaker Endpoint - let CDK auto-generate endpoint name
    this.endpoint = new sagemaker.CfnEndpoint(this, 'SymbolDetectionEndpoint', {
      endpointConfigName: this.endpointConfig.attrEndpointConfigName,
    });

    // Set dependencies
    this.endpointConfig.addDependency(this.model);
    this.endpoint.addDependency(this.endpointConfig);

    // Output the endpoint name
    new cdk.CfnOutput(this, 'SageMakerEndpointName', {
      value: this.endpoint.attrEndpointName,
      description: 'Name of the SageMaker endpoint for symbol detection',
    });

    new cdk.CfnOutput(this, 'SageMakerRoleArn', {
      value: this.sagemakerRole.roleArn,
      description: 'ARN of the SageMaker execution role',
    });
  }

  public createLambdaInvokePolicy(): iam.PolicyStatement {
    /**
     * Creates an IAM policy statement for Lambda functions to invoke the SageMaker endpoint.
     */
    return new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'sagemaker:InvokeEndpoint',
      ],
      resources: [
        `arn:aws:sagemaker:${cdk.Stack.of(this).region}:${cdk.Stack.of(this).account}:endpoint/${this.endpoint.attrEndpointName}`,
      ],
    });
  }
}
