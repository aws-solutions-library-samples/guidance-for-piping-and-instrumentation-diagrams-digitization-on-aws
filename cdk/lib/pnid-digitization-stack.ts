import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import { Construct, IConstruct } from 'constructs';
import { NagSuppressions } from 'cdk-nag';
import * as fs from 'fs';
import * as path from 'path';

import { StorageConstruct } from './constructs/storage';
import { MLConstruct } from './constructs/ml';
import { ProcessingConstruct } from './constructs/lambda';
import { OrchestrationConstruct } from './constructs/orchestration';
import { NetworkingConstruct } from './constructs/networking';

// Interface for configuration
interface Config {
  vpc: {
    vpcId: string;
    subnetIds: string[];
    createVpcEndpoints: boolean;
  };
  endpoints: {
    s3: boolean;
    sagemaker: boolean;
    bedrock: boolean;
    logs: boolean;
  };
  model: {
    s3Uri: string;
  };
  
}

export class PNIDDigitizationStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // Read configuration (region is now handled by app.ts)
    const configPath = path.join(__dirname, '../config.json');
    let config: Config | null = null;

    if (fs.existsSync(configPath)) {
      try {
        const configContent = fs.readFileSync(configPath, 'utf8');
        const parsedConfig = JSON.parse(configContent) as Config;
        config = parsedConfig;
      } catch (error) {
        console.warn('Failed to parse configuration file. Using default configuration.', error);
      }
    }

    // Create storage infrastructure
    const storage = new StorageConstruct(this, 'Storage');

    // Check if model S3 URI is configured
    if (!config || !config.model || !config.model.s3Uri) {
      throw new Error('Model S3 URI is not configured. Please update config.json with the model.s3Uri property.');
    }

    // Create ML infrastructure for symbol detection
    const ml = new MLConstruct(this, 'ML', {
      modelS3Uri: config.model.s3Uri,
    });

    // Create Bedrock Data Automation Project directly in the main stack
    const bdaProject = new bedrock.CfnDataAutomationProject(this, 'TextDetection', {
      projectName: `${this.stackName}-text-detection-${this.account}`.toLowerCase(),
      projectDescription: 'Bedrock Data Automation project for P&ID text detection processing',
      standardOutputConfiguration: {
        document: {
          extraction: {
            boundingBox: {
              state: 'ENABLED',
            },
            granularity: {
              types: ["DOCUMENT",
                            "PAGE",
                            "ELEMENT",
                            "LINE",
                            "WORD"],
            },
      },
      "outputFormat": {
                    "textFormat": {
                        "types": [
                            "PLAIN_TEXT",
                            "MARKDOWN",
                            "HTML",
                            "CSV"
                        ]
                    },
                    "additionalFileFormat": {
                        "state": "ENABLED"
                    }
                }
        },
      },
      overrideConfiguration: {
    audio: {
      modalityProcessing: {
        state: 'DISABLED',
      },
    },
    document: {
      modalityProcessing: {
        state: 'ENABLED',
      },
      splitter: {
        state: 'ENABLED',
      },
    },
    image: {
      modalityProcessing: {
        state: 'ENABLED',
      },
    },
    modalityRouting: {
      jpeg: 'DOCUMENT',
      png: 'DOCUMENT',
    },
    video: {
      modalityProcessing: {
        state: 'DISABLED',
      },
    },
  },
    });

    let networking: NetworkingConstruct | undefined;

    // Create networking construct if VPC configuration is valid
    if (config && config.vpc.vpcId && config.vpc.subnetIds.length > 0) {
      networking = new NetworkingConstruct(this, 'Networking', {
        vpcId: config.vpc.vpcId,
        subnetIds: config.vpc.subnetIds,
        createVpcEndpoints: config.vpc.createVpcEndpoints,
        endpoints: config.endpoints,
        bedrockDataAutomationProjectArn: bdaProject.attrProjectArn,
      });

      // Add networking outputs
      networking.addOutputs();
    } else if (config) {
      console.warn('VPC configuration found but vpcId or subnetIds are empty. Lambda functions will not be deployed in VPC.');
    } else {
      console.info('No configuration file found. Lambda functions will not be deployed in VPC.');
    }

    // Create processing infrastructure with proper VPC configuration
    const processing = new ProcessingConstruct(this, 'Processing', {
      inputBucket: storage.inputBucket,
      outputBucket: storage.outputBucket,
      inputBucketKey: storage.inputBucketKey,
      outputBucketKey: storage.outputBucketKey,
      sagemakerInvokePolicy: ml.createLambdaInvokePolicy(),
      // Pass VPC configuration if available
      vpcConfig: networking ? networking.getVpcConfig() : undefined,
      // Pass the existing BDA project
      existingBdaProject: bdaProject,
    });

    // Create orchestration infrastructure (Step Functions)
    const orchestration = new OrchestrationConstruct(this, 'Orchestration', {
      inputValidator: processing.inputValidator,
      lineDetection: processing.lineDetection,
      graphGenerator: processing.graphGenerator,
      graphVisualization: processing.graphVisualization,
      symbolDetection: processing.symbolDetection,
      textDetection: processing.textDetection,
      notesProcessor: processing.notesProcessor,
      inputBucket: storage.inputBucket,
      outputBucket: storage.outputBucket,  // Add output bucket for CDK-provided values
    });

    // Add SAGEMAKER_ENDPOINT_NAME environment variable to input validator Lambda
    processing.inputValidator.addEnvironment(
      'SAGEMAKER_ENDPOINT_NAME',
      ml.endpoint.attrEndpointName
    );

    // Add SAGEMAKER_ENDPOINT_NAME environment variable to symbol detection Lambda
    processing.symbolDetection.addEnvironment(
      'SAGEMAKER_ENDPOINT_NAME',
      ml.endpoint.attrEndpointName
    );
  


    // Add CDK Nag suppressions for the stack level
    NagSuppressions.addStackSuppressions(this, [
      {
        id: 'AwsSolutions-S1',
        reason: 'S3 access logging would create circular dependency. Using CloudTrail for audit instead.',
      },
      {
        id: 'AwsSolutions-IAM4',
        reason: 'Using custom IAM policies instead of managed policies as per requirements',
      },
      {
        id: 'AwsSolutions-IAM5',
        reason: 'Some AWS services require wildcard permissions for proper operation (CloudWatch logs, Bedrock, SageMaker, VPC networking)',
      },
      {
        id: 'AwsSolutions-EC23',
        reason: 'Lambda security groups configured with least-privilege access for VPC endpoints',
      },
      {
        id: 'AwsSolutions-L1',
        reason: 'S3 BucketDeployment Lambda runtime is managed by CDK and automatically updated',
        appliesTo: ['Resource::*CDKBucketDeployment*'],
      },
      {
        id: 'Prototype Security Nag Pack-LambdaInsideVPC',
        reason: 'S3 BucketDeployment Lambda only runs during deployment and does not need VPC access',
        appliesTo: ['Resource::*CDKBucketDeployment*'],
      },
    ]);

    // Stack-level outputs
    new cdk.CfnOutput(this, 'PipelineInstructions', {
      value: `S3 automatic trigger is DISABLED. Manually trigger Step Functions to process P&ID images. Upload P&ID images (jpg, png, pdf) to s3://${storage.inputBucket.bucketName}. Results will be stored in s3://${storage.outputBucket.bucketName}`,
      description: 'Instructions for using the P&ID digitization pipeline',
    });

    new cdk.CfnOutput(this, 'ModelDeploymentInstructions', {
      value: `Model is deployed from ${config.model.s3Uri}. To update the model, upload a new model.tar.gz to S3 and update the model.s3Uri in config.json, then redeploy the stack`,
      description: 'Instructions for deploying trained ML models',
    });

    new cdk.CfnOutput(this, 'DeployedRegion', {
      value: this.region,
      description: 'AWS region where the stack is deployed',
    });

    new cdk.CfnOutput(this, 'VpcConfigurationStatus', {
      value: networking ? 'Lambda functions deployed in VPC with endpoints' : 'Lambda functions deployed without VPC',
      description: 'VPC configuration status for Lambda functions',
    });

    if (config && networking) {
      new cdk.CfnOutput(this, 'VpcConfigInstructions', {
        value: `Lambda functions are deployed in VPC ${config.vpc.vpcId} in region ${this.region} with VPC endpoints. No internet access required.`,
        description: 'VPC deployment information',
      });
    } else {
      new cdk.CfnOutput(this, 'VpcConfigInstructions', {
        value: 'To deploy Lambda functions in VPC, update config.json with your VPC ID and subnet IDs, then redeploy.',
        description: 'Instructions for VPC deployment',
      });
    }

    // Add an aspect to suppress CDK Nag warnings for all BucketDeployment Lambda functions
    cdk.Aspects.of(this).add({
      visit(node: IConstruct): void {
        if (node instanceof lambda.Function) {
          // Check if this is a BucketDeployment Lambda
          if (node.node.path.includes('Custom::CDKBucketDeployment')) {
            NagSuppressions.addResourceSuppressions(node, [
              {
                id: 'AwsSolutions-L1',
                reason: 'S3 BucketDeployment Lambda runtime is managed by CDK and automatically updated',
              },
              {
                id: 'Prototype Security Nag Pack-LambdaInsideVPC',
                reason: 'S3 BucketDeployment Lambda only runs during deployment and does not need VPC access',
              },
            ]);
          }
        }
      },
    });
  }
}
