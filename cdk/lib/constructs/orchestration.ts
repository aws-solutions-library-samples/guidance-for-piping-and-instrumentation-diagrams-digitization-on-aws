import * as cdk from 'aws-cdk-lib';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as sfn from 'aws-cdk-lib/aws-stepfunctions';
import * as tasks from 'aws-cdk-lib/aws-stepfunctions-tasks';
import { Construct } from 'constructs';
import { NagSuppressions } from 'cdk-nag';

export interface OrchestrationConstructProps {
  inputBucket: s3.IBucket;
  prepareInput: lambda.IFunction;
  dispatchSheet: lambda.IFunction;
  mergeSheets: lambda.IFunction;
  maxConcurrentSheets: number;
  sheetTimeout: cdk.Duration;
  heartbeatTimeout: cdk.Duration;
  uploadTrigger: { enabled: boolean; prefix: string };
}

/** Errors the agent reports that are worth another attempt on a fresh session. */
const RETRYABLE = [
  'States.HeartbeatTimeout', // the session died or hung
  'ThrottlingException', 'ModelThrottledException', 'ServiceUnavailableException',
  'ModelNotReadyException', 'ModelErrorException', 'InternalServerException',
];

const EXTENSIONS = ['pdf', 'png', 'jpg', 'jpeg', 'tif', 'tiff', 'webp'];

/**
 * PrepareInput -> Map over pages (DispatchSheet waits on the agent's task token) -> MergeSheets.
 * Started manually with {"bucket", "key", "config"?} or by an upload to the input bucket.
 */
export class OrchestrationConstruct extends Construct {
  public readonly stateMachine: sfn.StateMachine;

  constructor(scope: Construct, id: string, props: OrchestrationConstructProps) {
    super(scope, id);

    const prepare = new tasks.LambdaInvoke(this, 'PrepareInput', {
      lambdaFunction: props.prepareInput,
      comment: 'Validate the drawing, merge config, render PDF pages to PNG',
      payload: sfn.TaskInput.fromObject({
        'bucket.$': '$.bucket',
        'key.$': '$.key',
        'config.$': '$.config',
        executionName: sfn.JsonPath.stringAt('$$.Execution.Name'),
      }),
      payloadResponseOnly: true,
    });
    // "config" is optional in the execution input
    const defaults = new sfn.Pass(this, 'DefaultConfig', {
      parameters: { config: {} },
      resultPath: '$.defaults',
    });
    const withConfig = new sfn.Pass(this, 'MergeInput', {
      parameters: { 'merged.$': 'States.JsonMerge($.defaults, $, false)' },
      outputPath: '$.merged',
    });

    const dispatch = new tasks.LambdaInvoke(this, 'DigitizeSheet', {
      lambdaFunction: props.dispatchSheet,
      comment: 'Start an AgentCore session for the sheet; wait for its SendTaskSuccess',
      integrationPattern: sfn.IntegrationPattern.WAIT_FOR_TASK_TOKEN,
      payload: sfn.TaskInput.fromObject({
        taskToken: sfn.JsonPath.taskToken,
        execution: sfn.JsonPath.stringAt('$$.Execution.Id'),
        retryCount: sfn.JsonPath.numberAt('$$.State.RetryCount'),
        'bucket.$': '$.bucket',
        'page.$': '$.page',
        'config.$': '$.config',
      }),
      heartbeatTimeout: sfn.Timeout.duration(props.heartbeatTimeout),
      taskTimeout: sfn.Timeout.duration(props.sheetTimeout),
    });
    dispatch.addRetry({ errors: RETRYABLE, interval: cdk.Duration.minutes(1), backoffRate: 2, maxAttempts: 2 });
    const sheetFailed = new sfn.Pass(this, 'SheetFailed', {
      parameters: {
        status: 'FAILED',
        'sheetId.$': '$.page.sheetId',
        'outputPrefix.$': '$.page.outputPrefix',
        'error.$': '$.error.Error',
        'cause.$': '$.error.Cause',
      },
    });
    dispatch.addCatch(sheetFailed, { errors: ['States.ALL'], resultPath: '$.error' });

    const sheets = new sfn.Map(this, 'Sheets', {
      comment: 'One AgentCore session per sheet',
      itemsPath: '$.pages',
      maxConcurrency: props.maxConcurrentSheets,
      itemSelector: {
        'page.$': '$$.Map.Item.Value',
        'bucket.$': '$.bucket',
        'config.$': '$.config',
      },
      resultPath: '$.results',
    });
    sheets.itemProcessor(dispatch);

    const merge = new tasks.LambdaInvoke(this, 'MergeSheets', {
      lambdaFunction: props.mergeSheets,
      comment: 'Plant graph, DEXPI export and summary.json',
      payload: sfn.TaskInput.fromObject({
        'bucket.$': '$.bucket',
        'prefix.$': '$.prefix',
        'source.$': '$.source',
        'config.$': '$.config',
        'results.$': '$.results',
      }),
      payloadResponseOnly: true,
    });

    const done = new sfn.Choice(this, 'AllSheetsDone?')
      .when(sfn.Condition.stringEquals('$.status', 'SUCCEEDED'), new sfn.Succeed(this, 'Succeeded'))
      .otherwise(new sfn.Fail(this, 'SheetsFailed', {
        error: 'SheetsFailed',
        causePath: sfn.JsonPath.format('One or more sheets failed; see {}', sfn.JsonPath.stringAt('$.outputs.summary')),
      }));

    // The upload rule matches on prefix only (EventBridge limits wildcard patterns); uploads with
    // other extensions end here. Manual starts always go on, so PrepareInput can report a bad key.
    const exts = EXTENSIONS.flatMap((e) => [e, e.toUpperCase()]);
    const supported = new sfn.Choice(this, 'SupportedFile?')
      .when(sfn.Condition.or(
        sfn.Condition.isNotPresent('$.trigger'),
        ...exts.map((e) => sfn.Condition.stringMatches('$.key', `*.${e}`)),
      ), defaults)
      .otherwise(new sfn.Succeed(this, 'IgnoredUpload', { comment: 'Uploaded file is not a drawing' }));
    defaults.next(withConfig).next(prepare).next(sheets).next(merge).next(done);
    const definition = supported;

    const logGroup = new logs.LogGroup(this, 'Logs', {
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
    this.stateMachine = new sfn.StateMachine(this, 'StateMachine', {
      definitionBody: sfn.DefinitionBody.fromChainable(definition),
      timeout: cdk.Duration.hours(24),
      logs: { destination: logGroup, level: sfn.LogLevel.ALL },
      tracingEnabled: true,
    });
    NagSuppressions.addResourceSuppressions(this.stateMachine, [
      { id: 'AwsSolutions-IAM5', reason: 'Lambda invoke on function versions (:*) and X-Ray / log delivery' },
    ], true);

    if (props.uploadTrigger.enabled) {
      const rule = new events.Rule(this, 'UploadTrigger', {
        description: 'Start the digitization workflow when a drawing is uploaded to the input bucket',
        eventPattern: {
          source: ['aws.s3'],
          detailType: ['Object Created'],
          detail: {
            bucket: { name: [props.inputBucket.bucketName] },
            ...(props.uploadTrigger.prefix ? { object: { key: [{ prefix: props.uploadTrigger.prefix }] } } : {}),
          },
        },
      });
      rule.addTarget(new targets.SfnStateMachine(this.stateMachine, {
        input: events.RuleTargetInput.fromObject({
          bucket: events.EventField.fromPath('$.detail.bucket.name'),
          key: events.EventField.fromPath('$.detail.object.key'),
          trigger: 'upload',
        }),
      }));
    }

    new cdk.CfnOutput(this, 'StateMachineArn', {
      value: this.stateMachine.stateMachineArn,
      description: 'Digitization workflow (start with {"bucket": ..., "key": ..., "config": {...}})',
    });
  }
}
