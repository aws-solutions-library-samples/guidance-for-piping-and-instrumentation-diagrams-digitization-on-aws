import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { PythonFunction } from '@aws-cdk/aws-lambda-python-alpha';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import { Construct } from 'constructs';
import { NagSuppressions } from 'cdk-nag';
import { LambdaRolesConstruct } from './lambda-roles';

export interface ProcessingConstructProps {
  inputBucket: s3.Bucket;
  outputBucket: s3.Bucket;
  inputBucketKey: kms.Key;
  outputBucketKey: kms.Key;
  sagemakerInvokePolicy: iam.PolicyStatement;
  // Optional VPC configuration
  vpcConfig?: {
    vpc: ec2.IVpc;
    vpcSubnets: ec2.SubnetSelection;
    securityGroups: ec2.SecurityGroup[];
  };
  // Optional existing BDA project
  existingBdaProject?: bedrock.CfnDataAutomationProject;
}

export class ProcessingConstruct extends Construct {
  public readonly inputValidatorRole: iam.Role;
  public readonly lineDetectionRole: iam.Role;
  public readonly graphGeneratorRole: iam.Role;
  public readonly graphVisualizationRole: iam.Role;
  public readonly symbolDetectionRole: iam.Role;
  public readonly textDetectionRole: iam.Role;
  public readonly notesProcessorRole: iam.Role;
  public readonly inputValidator: lambda.Function;
  public readonly lineDetection: lambda.DockerImageFunction;
  public readonly graphGenerator: lambda.Function;
  public readonly graphVisualization: lambda.DockerImageFunction;
  public readonly symbolDetection: lambda.Function;
  public readonly textDetection: lambda.DockerImageFunction;
  public readonly notesProcessor: lambda.DockerImageFunction;
  public readonly bdaProject: bedrock.CfnDataAutomationProject;


  constructor(scope: Construct, id: string, props: ProcessingConstructProps) {
    super(scope, id);

    // Get account and region from stack
    const account = cdk.Stack.of(this).account;
    const region = cdk.Stack.of(this).region;

    // Use existing BDA project if provided, otherwise create a new one
    this.bdaProject = props.existingBdaProject! 

    // Create all Lambda IAM roles using dedicated construct
    const lambdaRoles = new LambdaRolesConstruct(this, 'LambdaRoles', {
      inputBucket: props.inputBucket,
      outputBucket: props.outputBucket,
      inputBucketKey: props.inputBucketKey,
      outputBucketKey: props.outputBucketKey,
      sagemakerInvokePolicy: props.sagemakerInvokePolicy,
      bdaProject: this.bdaProject,
      vpcConfig: props.vpcConfig,
    });

    // Expose roles for backwards compatibility
    this.inputValidatorRole = lambdaRoles.roles.inputValidatorRole;
    this.lineDetectionRole = lambdaRoles.roles.lineDetectionRole;
    this.graphGeneratorRole = lambdaRoles.roles.graphGeneratorRole;
    this.graphVisualizationRole = lambdaRoles.roles.graphVisualizationRole;
    this.symbolDetectionRole = lambdaRoles.roles.symbolDetectionRole;
    this.textDetectionRole = lambdaRoles.roles.textDetectionRole;
    this.notesProcessorRole = lambdaRoles.roles.notesProcessorRole;

    // Prepare common Lambda configuration
    const commonLambdaConfig = props.vpcConfig ? {
      vpc: props.vpcConfig.vpc,
      vpcSubnets: props.vpcConfig.vpcSubnets,
      securityGroups: props.vpcConfig.securityGroups,
    } : {};

    // Shared file mapping - defines which shared files each lambda function needs
    const sharedFileMapping: { [key: string]: string[] } = {
      'input_validator': ['config_helper.py'],
      'text_detection': ['config_helper.py'], 
      'graph_generator': ['config_helper.py', 'coordinate_transform.py'],
      'symbol_detection': ['config_helper.py', 'coordinate_transform.py'],
      'notes_processor': ['config_helper.py'],
    };

    // Helper method to create Python Lambda (shared files are copied by sync script)
    const createPythonLambdaWithShared = (id: string, entry: string, sharedFiles: string[], lambdaProps: any) => {
      return new PythonFunction(this, id, {
        entry,
        runtime: lambda.Runtime.PYTHON_3_13,
        // Shared files are now copied by the sync-shared-files.js script
        // No bundling hooks needed - files are already in the lambda directories
        ...lambdaProps,
      });
    };

    // Input Validator Lambda Function
    this.inputValidator = createPythonLambdaWithShared('InputValidator', 'lambda/input_validator', sharedFileMapping['input_validator'], {
      index: 'index.py',
      handler: 'lambda_handler',
      role: this.inputValidatorRole,
      timeout: cdk.Duration.minutes(5),
      memorySize: 512,
      environment: {
        INPUT_BUCKET: props.inputBucket.bucketName,
        OUTPUT_BUCKET: props.outputBucket.bucketName,
        LOG_LEVEL: 'INFO',
      },
      logRetention: logs.RetentionDays.ONE_WEEK,
      ...commonLambdaConfig,
    });

    // Line Detection Lambda Function (Container-based for OpenCV)
    this.lineDetection = new lambda.DockerImageFunction(this, 'LineDetection', {
      code: lambda.DockerImageCode.fromImageAsset('lambda', {
        // Use parent lambda directory as build context to access shared files
        file: 'line_detection/Dockerfile',
        // Explicitly specify x86_64 platform to ensure compatibility with Lambda
        platform: cdk.aws_ecr_assets.Platform.LINUX_AMD64,
      }),
      role: this.lineDetectionRole,
      timeout: cdk.Duration.minutes(15),
      memorySize: 10240, // More memory for image processing
      environment: {
        OUTPUT_BUCKET: props.outputBucket.bucketName,
        LOG_LEVEL: 'INFO',
      },
      logRetention: logs.RetentionDays.ONE_WEEK,
      ...commonLambdaConfig,
    });

    // Graph Generator Lambda Function
    this.graphGenerator = createPythonLambdaWithShared('GraphGenerator', 'lambda/graph_generator', sharedFileMapping['graph_generator'], {
      index: 'index.py',
      handler: 'lambda_handler',
      role: this.graphGeneratorRole,
      timeout: cdk.Duration.minutes(15),
      memorySize: 10240,
      environment: {
        OUTPUT_BUCKET: props.outputBucket.bucketName,
        LOG_LEVEL: 'INFO',
      },
      logRetention: logs.RetentionDays.ONE_WEEK,
      ...commonLambdaConfig,
    });

    // Graph Visualization Lambda Function (Container-based for heavy libraries)
    this.graphVisualization = new lambda.DockerImageFunction(this, 'GraphVisualization', {
      code: lambda.DockerImageCode.fromImageAsset('lambda', {
        // Use parent lambda directory as build context to access shared files
        file: 'graph_visualization/Dockerfile',
        // Explicitly specify x86_64 platform to ensure compatibility with Lambda
        platform: cdk.aws_ecr_assets.Platform.LINUX_AMD64,
      }),
      role: this.graphVisualizationRole,
      timeout: cdk.Duration.minutes(5),
      memorySize: 2048, // Higher memory for heavy libraries (matplotlib, scipy)
      environment: {
        OUTPUT_BUCKET: props.outputBucket.bucketName,
        LOG_LEVEL: 'INFO',
      },
      logRetention: logs.RetentionDays.ONE_WEEK,
      ...commonLambdaConfig,
    });

    // Symbol Detection Lambda Function
    this.symbolDetection = createPythonLambdaWithShared('SymbolDetection', 'lambda/symbol_detection', sharedFileMapping['symbol_detection'], {
      index: 'index.py',
      handler: 'lambda_handler',
      role: this.symbolDetectionRole,
      timeout: cdk.Duration.minutes(15),
      memorySize: 2048,
      environment: {
        OUTPUT_BUCKET: props.outputBucket.bucketName,
        LOG_LEVEL: 'INFO',
        // SageMaker endpoint will be set during deployment
        // SAGEMAKER_ENDPOINT_NAME: 'set-during-deployment'
      },
      logRetention: logs.RetentionDays.ONE_WEEK,
      ...commonLambdaConfig,
    });

    // Text Detection Lambda Function (Container-based for OpenCV on Python 3.13)
    // Python zip would exceed the 250MB unzipped limit, so we use a container image.
    this.textDetection = new lambda.DockerImageFunction(this, 'TextDetection', {
      code: lambda.DockerImageCode.fromImageAsset('lambda', {
        file: 'text_detection/Dockerfile',
        platform: cdk.aws_ecr_assets.Platform.LINUX_AMD64,
      }),
      role: this.textDetectionRole,
      timeout: cdk.Duration.minutes(5),
      memorySize: 1024,
      environment: {
        INPUT_BUCKET: props.inputBucket.bucketName,
        OUTPUT_BUCKET: props.outputBucket.bucketName,
        BDA_PROJECT_ARN: this.bdaProject.attrProjectArn,
        AWS_ACCOUNT_ID: account,
        LOG_LEVEL: 'INFO',
      },
      logRetention: logs.RetentionDays.ONE_WEEK,
      ...commonLambdaConfig,
    });

    // Notes Processor Lambda Function (Container-based for OpenCV + pytesseract on Python 3.13)
    this.notesProcessor = new lambda.DockerImageFunction(this, 'NotesProcessor', {
      code: lambda.DockerImageCode.fromImageAsset('lambda', {
        file: 'notes_processor/Dockerfile',
        platform: cdk.aws_ecr_assets.Platform.LINUX_AMD64,
      }),
      role: this.notesProcessorRole,
      timeout: cdk.Duration.minutes(10),
      memorySize: 2048, // Higher memory for image processing
      environment: {
        INPUT_BUCKET: props.inputBucket.bucketName,
        OUTPUT_BUCKET: props.outputBucket.bucketName,
        LOG_LEVEL: 'INFO',
      },
      logRetention: logs.RetentionDays.ONE_WEEK,
      ...commonLambdaConfig,
    });

    // Add CDK Nag suppressions for Lambda functions when not in VPC
    if (!props.vpcConfig) {
      const lambdaVpcSuppressions = [
        {
          id: 'Prototype Security Nag Pack-LambdaInsideVPC',
          reason: 'Lambda functions can be optionally deployed in VPC. Configure config.json to enable VPC deployment for enhanced security.',
        },
      ];

      NagSuppressions.addResourceSuppressions(this.inputValidator, lambdaVpcSuppressions);
      NagSuppressions.addResourceSuppressions(this.lineDetection, lambdaVpcSuppressions);
      NagSuppressions.addResourceSuppressions(this.graphGenerator, lambdaVpcSuppressions);
      NagSuppressions.addResourceSuppressions(this.graphVisualization, lambdaVpcSuppressions);
      NagSuppressions.addResourceSuppressions(this.symbolDetection, lambdaVpcSuppressions);
      NagSuppressions.addResourceSuppressions(this.textDetection, lambdaVpcSuppressions);
      NagSuppressions.addResourceSuppressions(this.notesProcessor, lambdaVpcSuppressions);
    }

    // Output Lambda function ARNs
    new cdk.CfnOutput(this, 'InputValidatorArn', {
      value: this.inputValidator.functionArn,
      description: 'ARN of the input validator Lambda function',
    });

    new cdk.CfnOutput(this, 'LineDetectionArn', {
      value: this.lineDetection.functionArn,
      description: 'ARN of the line detection Lambda function',
    });

    new cdk.CfnOutput(this, 'GraphGeneratorArn', {
      value: this.graphGenerator.functionArn,
      description: 'ARN of the graph generator Lambda function',
    });

    new cdk.CfnOutput(this, 'GraphVisualizationArn', {
      value: this.graphVisualization.functionArn,
      description: 'ARN of the graph visualization Lambda function',
    });

    new cdk.CfnOutput(this, 'SymbolDetectionArn', {
      value: this.symbolDetection.functionArn,
      description: 'ARN of the symbol detection Lambda function',
    });

    new cdk.CfnOutput(this, 'TextDetectionArn', {
      value: this.textDetection.functionArn,
      description: 'ARN of the text detection Lambda function',
    });

    new cdk.CfnOutput(this, 'NotesProcessorArn', {
      value: this.notesProcessor.functionArn,
      description: 'ARN of the notes processor Lambda function',
    });
  }
}
