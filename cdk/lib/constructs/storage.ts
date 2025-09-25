import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';
import { NagSuppressions } from 'cdk-nag';

export class StorageConstruct extends Construct {
  public readonly inputBucket: s3.Bucket;
  public readonly outputBucket: s3.Bucket;
  
  public readonly inputBucketKey: kms.Key;
  public readonly outputBucketKey: kms.Key;

  constructor(scope: Construct, id: string) {
    super(scope, id);

    // Get account and region
    const account = cdk.Stack.of(this).account;
    const region = cdk.Stack.of(this).region;

    // Create KMS keys for each bucket
    this.inputBucketKey = new kms.Key(this, 'InputBucketKey', {
      description: 'KMS key for P&ID input bucket',
      enableKeyRotation: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    this.outputBucketKey = new kms.Key(this, 'OutputBucketKey', {
      description: 'KMS key for P&ID output bucket',
      enableKeyRotation: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Create S3 buckets with KMS encryption - let CDK auto-generate bucket names
    this.inputBucket = new s3.Bucket(this, 'InputBucket', {
      versioned: true,
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: this.inputBucketKey,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      serverAccessLogsPrefix: 'access-logs/',
      eventBridgeEnabled: true,
    });

    this.outputBucket = new s3.Bucket(this, 'OutputBucket', {
      versioned: true,
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: this.outputBucketKey,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      serverAccessLogsPrefix: 'access-logs/',
    });

    // Grant Bedrock Data Automation service permissions to read from input bucket
    this.inputBucket.addToResourcePolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      principals: [new iam.ServicePrincipal('bedrock.amazonaws.com')],
      actions: [
        's3:GetObject',
        's3:GetObjectVersion',
      ],
      resources: [`${this.inputBucket.bucketArn}/*`],
      conditions: {
        StringEquals: {
          'aws:SourceAccount': account,
        },
        StringLike: {
          'aws:SourceArn': `arn:aws:bedrock:${region}:${account}:data-automation-invocation/*`,
        },
      },
    }));

    // Grant Bedrock Data Automation service permissions to use the KMS keys
    this.inputBucketKey.grantDecrypt(new iam.ServicePrincipal('bedrock.amazonaws.com', {
      conditions: {
        StringEquals: {
          'aws:SourceAccount': account,
        },
        StringLike: {
          'aws:SourceArn': `arn:aws:bedrock:${region}:${account}:data-automation-invocation/*`,
        },
      },
    }));

    // Add CDK Nag suppressions for auto delete objects
    NagSuppressions.addResourceSuppressions(this.inputBucket, [
      {
        id: 'AwsSolutions-S1',
        reason: 'Access logging bucket would be circular dependency. Using CloudTrail for audit instead.',
      },
    ]);

    NagSuppressions.addResourceSuppressions(this.outputBucket, [
      {
        id: 'AwsSolutions-S1',
        reason: 'Access logging bucket would be circular dependency. Using CloudTrail for audit instead.',
      },
    ]);

    // Output bucket names for reference
    new cdk.CfnOutput(this, 'InputBucketName', {
      value: this.inputBucket.bucketName,
      description: 'Name of the P&ID input bucket',
    });

    new cdk.CfnOutput(this, 'OutputBucketName', {
      value: this.outputBucket.bucketName,
      description: 'Name of the P&ID output bucket',
    });
  }
}
