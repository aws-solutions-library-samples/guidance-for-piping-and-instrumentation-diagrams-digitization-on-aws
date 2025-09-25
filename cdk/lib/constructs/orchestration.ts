import * as cdk from 'aws-cdk-lib';
import * as sfn from 'aws-cdk-lib/aws-stepfunctions';
import * as tasks from 'aws-cdk-lib/aws-stepfunctions-tasks';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import { NagSuppressions } from 'cdk-nag';

export interface OrchestrationConstructProps {
  inputValidator: lambda.Function;
  lineDetection: lambda.DockerImageFunction;
  graphGenerator: lambda.Function;
  graphVisualization: lambda.DockerImageFunction;
  symbolDetection: lambda.Function;
  textDetection: lambda.Function;
  notesProcessor: lambda.Function;
  inputBucket: s3.Bucket;
  outputBucket: s3.Bucket;  // Add output bucket to props
}

export class OrchestrationConstruct extends Construct {
  public readonly sfnRole: iam.Role;
  public readonly sfnLogGroup: logs.LogGroup;
  public readonly stateMachine: sfn.StateMachine;

  constructor(scope: Construct, id: string, props: OrchestrationConstructProps) {
    super(scope, id);

    // Get account and region from stack
    const account = cdk.Stack.of(this).account;
    const region = cdk.Stack.of(this).region;

    // Create Step Functions execution role
    this.sfnRole = new iam.Role(this, 'StepFunctionsRole', {
      assumedBy: new iam.ServicePrincipal('states.amazonaws.com'),
      description: 'IAM role for Step Functions state machine',
      inlinePolicies: {
        LambdaInvoke: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: [
                'lambda:InvokeFunction',
              ],
              resources: [
                props.inputValidator.functionArn,
                props.lineDetection.functionArn,
                props.graphGenerator.functionArn,
                props.graphVisualization.functionArn,
                props.symbolDetection.functionArn,
                props.textDetection.functionArn,
                props.notesProcessor.functionArn,
              ],
            }),
          ],
        }),
        LoggingAccess: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: [
                'logs:CreateLogGroup',
                'logs:CreateLogStream',
                'logs:PutLogEvents',
                'logs:CreateLogDelivery',
                'logs:GetLogDelivery',
                'logs:UpdateLogDelivery',
                'logs:DeleteLogDelivery',
                'logs:ListLogDeliveries',
                'logs:PutResourcePolicy',
                'logs:DescribeResourcePolicies',
                'logs:DescribeLogGroups',
              ],
              resources: [
                `arn:aws:logs:${region}:${account}:*`,
              ],
            }),
          ],
        }),
      },
    });

    // Add CDK Nag suppressions for Step Functions role
    NagSuppressions.addResourceSuppressions(this.sfnRole, [
      {
        id: 'AwsSolutions-IAM5',
        reason: 'Step Functions requires wildcard permissions for CloudWatch logs',
      },
    ]);

    // Create CloudWatch Log Group for Step Functions - let CDK auto-generate log group name
    this.sfnLogGroup = new logs.LogGroup(this, 'StepFunctionsLogGroup', {
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Define Step Functions tasks
    const inputValidationTask = new tasks.LambdaInvoke(this, 'InputValidationTask', {
      lambdaFunction: props.inputValidator,
      payload: sfn.TaskInput.fromObject({
        execution_id: sfn.JsonPath.stringAt('$$.Execution.Name'),  // Pass Step Functions execution ID
        // Pass through user input parameters
        image_key: sfn.JsonPath.stringAt('$.image_key'),
        input_bucket: sfn.JsonPath.stringAt('$.input_bucket'),
        processing_config: sfn.JsonPath.objectAt('$.processing_config'),  // Contains all config including manual_coordinates
        // Inject CDK-provided infrastructure values
        output_bucket: props.outputBucket.bucketName,  // Use CDK-known output bucket name
      }),
      outputPath: '$.Payload',
    });

    // Notes processor task - removes notes section and frame, creates clean image
    // Uses S3-stored configuration (which includes any manual coordinates merged by input validator)
    // Config is stored in output bucket by input validator
    const notesProcessorTask = new tasks.LambdaInvoke(this, 'NotesProcessorTask', {
      lambdaFunction: props.notesProcessor,
      payload: sfn.TaskInput.fromObject({
        execution_id: sfn.JsonPath.stringAt('$$.Execution.Name'),  // Pass Step Functions execution ID
        image_key: sfn.JsonPath.stringAt('$.image_key'),
        input_bucket: sfn.JsonPath.stringAt('$.input_bucket'),  // Read original image from input bucket
        processing_bucket: sfn.JsonPath.stringAt('$.output_bucket'),
        config_s3_key: sfn.JsonPath.stringAt('$.config_s3_key'),
        config_bucket: sfn.JsonPath.stringAt('$.output_bucket'),  // Read config from output bucket
      }),
      resultPath: '$.notes_processing_results',
    });

    // Text Detection task using Lambda function (synchronous) - uses processed image if available
    // Uses S3-stored configuration and stores results in S3
    const textDetectionTask = new tasks.LambdaInvoke(this, 'TextDetectionTask', {
      lambdaFunction: props.textDetection,
      payload: sfn.TaskInput.fromObject({
        execution_id: sfn.JsonPath.stringAt('$$.Execution.Name'),  // Pass Step Functions execution ID
        image_key: sfn.JsonPath.stringAt('$.notes_processing_results.Payload.processed_key'),
        bucket: sfn.JsonPath.stringAt('$.notes_processing_results.Payload.processed_bucket'),
        original_key: sfn.JsonPath.stringAt('$.original_key'),
        input_bucket: sfn.JsonPath.stringAt('$.input_bucket'),
        processing_bucket: sfn.JsonPath.stringAt('$.output_bucket'),
        config_s3_key: sfn.JsonPath.stringAt('$.config_s3_key'),
      }),
      outputPath: '$.Payload',
    });

    // Symbol detection task using Lambda function - uses processed image
    // Uses S3-stored configuration
    const symbolDetectionTask = new tasks.LambdaInvoke(this, 'SymbolDetectionTask', {
      lambdaFunction: props.symbolDetection,
      payload: sfn.TaskInput.fromObject({
        execution_id: sfn.JsonPath.stringAt('$$.Execution.Name'),  // Pass Step Functions execution ID
        s3_image_uri: sfn.JsonPath.format(
          's3://{}/{}',
          sfn.JsonPath.stringAt('$.notes_processing_results.Payload.processed_bucket'),
          sfn.JsonPath.stringAt('$.notes_processing_results.Payload.processed_key')
        ),
        processing_bucket: sfn.JsonPath.stringAt('$.output_bucket'),
        image_key: sfn.JsonPath.stringAt('$.image_key'),
        config_s3_key: sfn.JsonPath.stringAt('$.config_s3_key'),
        n_closest: 3,
        // Pass notes processing results for coordinate transformation
        notes_processing_results: sfn.JsonPath.objectAt('$.notes_processing_results'),
      }),
      outputPath: '$.Payload',
    });

    // Line detection task - uses S3 references for text detection and symbol detection results
    const lineDetectionTask = new tasks.LambdaInvoke(this, 'LineDetectionTask', {
      lambdaFunction: props.lineDetection,
      payload: sfn.TaskInput.fromObject({
        execution_id: sfn.JsonPath.stringAt('$$.Execution.Name'),  // Pass Step Functions execution ID
        bucket: sfn.JsonPath.stringAt('$.notes_processing_results.Payload.processed_bucket'),
        key: sfn.JsonPath.stringAt('$.notes_processing_results.Payload.processed_key'),
        config_s3_key: sfn.JsonPath.stringAt('$.config_s3_key'),
        s3_refs: {
          text_detection_results_key: sfn.JsonPath.stringAt('$.parallel_results[0].s3_results.text_detection_results_key'),
          symbol_results_key: sfn.JsonPath.stringAt('$.parallel_results[1].s3_results.detections_key'),
        },
        // Pass notes processing results for coordinate transformation
        notes_processing_results: sfn.JsonPath.objectAt('$.notes_processing_results'),
      }),
      resultPath: '$.line_detection_results',
    });

    // Graph generation task - uses S3 references for all inputs
    const graphGenerationTask = new tasks.LambdaInvoke(this, 'GraphGenerationTask', {
      lambdaFunction: props.graphGenerator,
      payload: sfn.TaskInput.fromObject({
        execution_id: sfn.JsonPath.stringAt('$$.Execution.Name'),  // Pass Step Functions execution ID
        processing_bucket: sfn.JsonPath.stringAt('$.output_bucket'),
        image_key: sfn.JsonPath.stringAt('$.image_key'),
        config_s3_key: sfn.JsonPath.stringAt('$.config_s3_key'),
        s3_refs: {
          text_detection_results_key: sfn.JsonPath.stringAt('$.parallel_results[0].s3_results.text_detection_results_key'),
          symbol_results_key: sfn.JsonPath.stringAt('$.parallel_results[1].s3_results.detections_key'),
          line_results_key: sfn.JsonPath.stringAt('$.line_detection_results.Payload.s3_results.lines_s3_key'),
        },
        line_detection_results: sfn.JsonPath.objectAt('$.line_detection_results'),
        // Pass processed image dimensions from notes processor for correct coordinate space handling
        processed_image_dimensions: sfn.JsonPath.objectAt('$.notes_processing_results.Payload.processed_image_dimensions'),
        original_image_dimensions: sfn.JsonPath.objectAt('$.notes_processing_results.Payload.original_image_dimensions'),
      }),
      resultPath: '$.graph_results',
    });

    // Graph visualization task - uses S3 references
    const graphVisualizationTask = new tasks.LambdaInvoke(this, 'GraphVisualizationTask', {
      lambdaFunction: props.graphVisualization,
      payload: sfn.TaskInput.fromObject({
        execution_id: sfn.JsonPath.stringAt('$$.Execution.Name'),  // Pass Step Functions execution ID
        graph_data_s3_key: sfn.JsonPath.stringAt('$.graph_results.Payload.s3_results.graph_data_s3_key'),
        processing_bucket: sfn.JsonPath.stringAt('$.output_bucket'),      // Read graph JSON from output bucket
        output_bucket: sfn.JsonPath.stringAt('$.output_bucket'),          // Save visualization PNG to output bucket
        image_key: sfn.JsonPath.stringAt('$.image_key'),
        config_s3_key: sfn.JsonPath.stringAt('$.config_s3_key'),
        // Add parameters for notes cutting visualization
        source_bucket: sfn.JsonPath.stringAt('$.input_bucket'),           // Original image bucket
        source_key: sfn.JsonPath.stringAt('$.original_key'),              // Original image key
        notes_coordinates: sfn.JsonPath.stringAt('$.notes_processing_results.Payload.frame_adjusted_notes_coordinates'),
        original_image_dimensions: sfn.JsonPath.stringAt('$.notes_processing_results.Payload.original_image_dimensions'),
      }),
      resultPath: '$.visualization_results',
    });

    // Success state
    const successState = new sfn.Succeed(this, 'ProcessingComplete', {
      comment: 'P&ID processing completed successfully',
    });

    // Failure state  
    const failureState = new sfn.Fail(this, 'ProcessingFailed', {
      comment: 'P&ID processing failed',
    });

    // Parallel processing - happens after notes processing
    // Results are stored in S3 automatically, no merging needed
    const parallelProcessing = new sfn.Parallel(this, 'ParallelProcessing', {
      comment: 'Run text detection and symbol detection in parallel on processed images',
      resultPath: '$.parallel_results',
    })
      .branch(textDetectionTask)
      .branch(symbolDetectionTask);

    // Define the simplified state machine workflow - no merge/parse states needed
    const processingChain = notesProcessorTask
      .next(parallelProcessing)
      .next(lineDetectionTask)
      .next(graphGenerationTask)
      .next(graphVisualizationTask)
      .next(successState);

    const tryProcessing = new sfn.Parallel(this, 'TryProcessing')
      .branch(processingChain)
      .addCatch(failureState, {
        errors: ['States.ALL'],
      });

    const definition = inputValidationTask.next(tryProcessing);

    // Create the Step Functions state machine - let CDK auto-generate state machine name
    this.stateMachine = new sfn.StateMachine(this, 'PNIDProcessingStateMachine', {
      definitionBody: sfn.DefinitionBody.fromChainable(definition),
      role: this.sfnRole,
      logs: {
        destination: this.sfnLogGroup,
        level: sfn.LogLevel.ALL,
      },
      tracingEnabled: true,
    });

    // Output the state machine ARN
    new cdk.CfnOutput(this, 'StateMachineArn', {
      value: this.stateMachine.stateMachineArn,
      description: 'ARN of the Step Functions state machine',
    });

    new cdk.CfnOutput(this, 'StateMachineName', {
      value: this.stateMachine.stateMachineName,
      description: 'Name of the Step Functions state machine',
    });
  }
}
