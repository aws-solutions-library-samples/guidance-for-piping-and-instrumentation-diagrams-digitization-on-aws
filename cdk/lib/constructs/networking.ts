import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as kms from 'aws-cdk-lib/aws-kms';
import { Construct } from 'constructs';
import { NagSuppressions } from 'cdk-nag';

export interface NetworkingConstructProps {
  vpcId: string;
  subnetIds: string[];
  createVpcEndpoints: boolean;
  endpoints: {
    sagemaker: boolean;
    bedrock: boolean;
    logs: boolean;
  };
  bedrockDataAutomationProjectArn?: string;
}

export class NetworkingConstruct extends Construct {
  public readonly vpc: ec2.IVpc;
  public readonly subnets: ec2.ISubnet[];
  public readonly lambdaSecurityGroup: ec2.SecurityGroup;
  public readonly vpcEndpoints: { [key: string]: ec2.VpcEndpoint } = {};

  constructor(scope: Construct, id: string, props: NetworkingConstructProps) {
    super(scope, id);

    // Validate required props
    if (!props.vpcId) {
      throw new Error('VPC ID is required');
    }
    if (!props.subnetIds || props.subnetIds.length === 0) {
      throw new Error('At least one subnet ID is required');
    }

    // Import existing VPC
    this.vpc = ec2.Vpc.fromLookup(this, 'ExistingVpc', {
      vpcId: props.vpcId,
    });

    // Import existing subnets with route table acknowledgment
    this.subnets = props.subnetIds.map((subnetId, index) =>
      ec2.Subnet.fromSubnetAttributes(this, `ImportedSubnet${index}`, {
        subnetId: subnetId,
        availabilityZone: cdk.Fn.select(index, cdk.Fn.getAzs()),
        routeTableId: cdk.Token.asString(cdk.Fn.ref('AWS::NoValue')),
      })
    );

    // Create security group for Lambda functions
    this.lambdaSecurityGroup = new ec2.SecurityGroup(this, 'LambdaSecurityGroup', {
      vpc: this.vpc,
      description: 'Security group for Lambda functions in VPC',
      allowAllOutbound: false,
    });

    // Allow HTTPS outbound for VPC endpoints
    this.lambdaSecurityGroup.addEgressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(443),
      'Allow HTTPS outbound for VPC endpoints'
    );

    // Create KMS key for VPC endpoint encryption
    const vpcEndpointKey = new kms.Key(this, 'VpcEndpointKey', {
      description: 'KMS key for VPC endpoint encryption',
      enableKeyRotation: true,
    });

    // Create VPC endpoints if requested
    if (props.createVpcEndpoints) {
      this.createVpcEndpoints(props.endpoints, vpcEndpointKey, props.bedrockDataAutomationProjectArn);
    }

    // Add CDK Nag suppressions
    NagSuppressions.addResourceSuppressions(this.lambdaSecurityGroup, [
      {
        id: 'AwsSolutions-EC23',
        reason: 'Lambda security group requires 0.0.0.0/0 outbound for VPC endpoints',
      },
    ]);

    NagSuppressions.addResourceSuppressions(vpcEndpointKey, [
      {
        id: 'AwsSolutions-KMS5',
        reason: 'VPC endpoint KMS key uses default key policy with appropriate restrictions',
      },
    ]);
  }

  private createVpcEndpoints(
    endpoints: NetworkingConstructProps['endpoints'],
    kmsKey: kms.Key,
    bedrockDataAutomationProjectArn?: string
  ): void {
    const region = cdk.Stack.of(this).region;
    const account = cdk.Stack.of(this).account;


    // SageMaker Runtime Interface Endpoint
    if (endpoints.sagemaker) {
      const sagemakerEndpoint = new ec2.InterfaceVpcEndpoint(this, 'SageMakerEndpoint', {
        vpc: this.vpc,
        service: ec2.InterfaceVpcEndpointAwsService.SAGEMAKER_RUNTIME,
        subnets: { subnets: this.subnets },
        securityGroups: [this.createEndpointSecurityGroup('SageMaker')],
        privateDnsEnabled: true,
      });

      sagemakerEndpoint.addToPolicy(new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        principals: [new iam.AnyPrincipal()],
        actions: [
          'sagemaker:InvokeEndpoint',
          'sagemaker:InvokeEndpointAsync',
        ],
        resources: [`arn:aws:sagemaker:${region}:${account}:endpoint/*`],
      }));

      this.vpcEndpoints['sagemaker'] = sagemakerEndpoint;
    }

    // Bedrock Interface Endpoint
    if (endpoints.bedrock) {
      if (!bedrockDataAutomationProjectArn) {
        throw new Error('Bedrock Data Automation Project ARN is required when creating Bedrock VPC endpoints');
      }

      const bedrockEndpoint = new ec2.InterfaceVpcEndpoint(this, 'BedrockEndpoint', {
        vpc: this.vpc,
        service: ec2.InterfaceVpcEndpointAwsService.BEDROCK_DATA_AUTOMATION_RUNTIME,
        subnets: { subnets: this.subnets },
        securityGroups: [this.createEndpointSecurityGroup('Bedrock')],
        privateDnsEnabled: true,
      });

      // Policy for starting data automation jobs
      bedrockEndpoint.addToPolicy(new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        principals: [new iam.AnyPrincipal()],
        actions: [
          'bedrock:InvokeDataAutomationAsync',
        ],
        resources: [
          // Data Automation projects
          bedrockDataAutomationProjectArn,
          // Data Automation profiles
          `arn:aws:bedrock:us-east-1:${account}:data-automation-profile/us.data-automation-v1`,
          `arn:aws:bedrock:us-east-2:${account}:data-automation-profile/us.data-automation-v1`,
          `arn:aws:bedrock:us-west-1:${account}:data-automation-profile/us.data-automation-v1`,
          `arn:aws:bedrock:us-west-2:${account}:data-automation-profile/us.data-automation-v1`,
        ],
      }));

      // Policy for checking job status and retrieving output
      bedrockEndpoint.addToPolicy(new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        principals: [new iam.AnyPrincipal()],
        actions: [
          'bedrock:GetDataAutomationStatus',
          'bedrock:GetDataAutomationOutput',
        ],
        resources: [
          // Data Automation invocations
          `arn:aws:bedrock:${region}:${account}:data-automation-invocation/*`,
        ],
      }));

      this.vpcEndpoints['bedrock'] = bedrockEndpoint;
    }

    // CloudWatch Logs Interface Endpoint
    if (endpoints.logs) {
      const logsEndpoint = new ec2.InterfaceVpcEndpoint(this, 'LogsEndpoint', {
        vpc: this.vpc,
        service: ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
        subnets: { subnets: this.subnets },
        securityGroups: [this.createEndpointSecurityGroup('CloudWatchLogs')],
        privateDnsEnabled: true,
      });

      logsEndpoint.addToPolicy(new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        principals: [new iam.AnyPrincipal()],
        actions: [
          'logs:CreateLogGroup',
          'logs:CreateLogStream',
          'logs:PutLogEvents',
        ],
        resources: [`arn:aws:logs:${region}:${account}:*`],
      }));

      this.vpcEndpoints['logs'] = logsEndpoint;
    }
  }

  private createEndpointSecurityGroup(serviceName: string): ec2.SecurityGroup {
    const sg = new ec2.SecurityGroup(this, `${serviceName}EndpointSG`, {
      vpc: this.vpc,
      description: `Security group for ${serviceName} VPC endpoint`,
      allowAllOutbound: false,
    });

    // Allow inbound HTTPS from Lambda security group
    sg.addIngressRule(
      this.lambdaSecurityGroup,
      ec2.Port.tcp(443),
      `Allow HTTPS from Lambda functions to ${serviceName} endpoint`
    );

    // Add CDK Nag suppressions
    NagSuppressions.addResourceSuppressions(sg, [
      {
        id: 'AwsSolutions-EC23',
        reason: `${serviceName} endpoint security group has specific ingress rules from Lambda security group`,
      },
    ]);

    return sg;
  }

  // Helper method to get VPC configuration for Lambda functions
  public getVpcConfig(): {
    vpc: ec2.IVpc;
    vpcSubnets: ec2.SubnetSelection;
    securityGroups: ec2.SecurityGroup[];
  } {
    return {
      vpc: this.vpc,
      vpcSubnets: { subnets: this.subnets },
      securityGroups: [this.lambdaSecurityGroup],
    };
  }

  // Output important information
  public addOutputs(): void {
    new cdk.CfnOutput(this, 'VpcId', {
      value: this.vpc.vpcId,
      description: 'VPC ID used for Lambda functions',
    });

    new cdk.CfnOutput(this, 'SubnetIds', {
      value: this.subnets.map(subnet => subnet.subnetId).join(','),
      description: 'Subnet IDs used for Lambda functions',
    });

    new cdk.CfnOutput(this, 'LambdaSecurityGroupId', {
      value: this.lambdaSecurityGroup.securityGroupId,
      description: 'Security group ID for Lambda functions',
    });

    if (Object.keys(this.vpcEndpoints).length > 0) {
      new cdk.CfnOutput(this, 'VpcEndpoints', {
        value: Object.keys(this.vpcEndpoints).join(','),
        description: 'Created VPC endpoints',
      });
    }
  }
}
