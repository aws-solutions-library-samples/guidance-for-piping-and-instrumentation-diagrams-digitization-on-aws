import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import { NagSuppressions } from 'cdk-nag';

export interface EndpointFlags {
  /** bedrock-runtime: model calls from the agent */
  bedrockRuntime: boolean;
  /** bedrock-agentcore: DispatchSheet starting agent sessions */
  agentCore: boolean;
  /** states: the agent's task heartbeats and callbacks */
  stepFunctions: boolean;
  /** logs: CloudWatch Logs */
  logs: boolean;
  /** s3: gateway endpoint (data buckets, and the agent's code package at session start) */
  s3: boolean;
}

export interface NetworkingConstructProps {
  /** Existing VPC to use. When empty, the construct creates an isolated VPC with every endpoint. */
  vpcId?: string;
  subnetIds?: string[];
  routeTableIds?: string[];
  createVpcEndpoints: boolean;
  endpoints: EndpointFlags;
  /** CIDR of the created VPC. */
  cidr: string;
  /** AZ IDs (e.g. usw2-az1) of the created subnets; default: the first two AgentCore supports in the Region. */
  availabilityZoneIds?: string[];
}

/**
 * Availability Zone IDs where AgentCore Runtime supports VPC connectivity
 * (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html#agentcore-vpc-supported-azs).
 */
export const AGENTCORE_AZ_IDS: { [region: string]: string[] } = {
  'us-east-1': ['use1-az1', 'use1-az2', 'use1-az4'],
  'us-east-2': ['use2-az1', 'use2-az2', 'use2-az3'],
  'us-west-1': ['usw1-az1', 'usw1-az3'],
  'us-west-2': ['usw2-az1', 'usw2-az2', 'usw2-az3'],
  'ap-southeast-5': ['apse5-az1', 'apse5-az2', 'apse5-az3'],
  'ap-south-1': ['aps1-az1', 'aps1-az2', 'aps1-az3'],
  'ap-south-2': ['aps2-az1', 'aps2-az2', 'aps2-az3'],
  'ap-northeast-2': ['apne2-az1', 'apne2-az2', 'apne2-az3'],
  'ap-southeast-1': ['apse1-az1', 'apse1-az2', 'apse1-az3'],
  'ap-southeast-2': ['apse2-az1', 'apse2-az2', 'apse2-az3'],
  'ap-southeast-7': ['apse7-az1', 'apse7-az2', 'apse7-az3'],
  'ap-northeast-1': ['apne1-az1', 'apne1-az2', 'apne1-az4'],
  'ca-central-1': ['cac1-az1', 'cac1-az2', 'cac1-az4'],
  'eu-central-1': ['euc1-az1', 'euc1-az2', 'euc1-az3'],
  'eu-west-1': ['euw1-az1', 'euw1-az2', 'euw1-az3'],
  'eu-west-2': ['euw2-az1', 'euw2-az2', 'euw2-az3'],
  'eu-south-1': ['eus1-az1', 'eus1-az2', 'eus1-az3'],
  'eu-west-3': ['euw3-az1', 'euw3-az2', 'euw3-az3'],
  'eu-south-2': ['eus2-az1', 'eus2-az2', 'eus2-az3'],
  'eu-north-1': ['eun1-az1', 'eun1-az2', 'eun1-az3'],
  'sa-east-1': ['sae1-az1', 'sae1-az2', 'sae1-az3'],
};

/**
 * Network for the Lambdas and the AgentCore Runtime. By default a new VPC with private isolated
 * subnets (no internet gateway, no NAT): every AWS API is reached through VPC endpoints. Optionally
 * an existing VPC instead.
 */
export class NetworkingConstruct extends Construct {
  public readonly vpc: ec2.IVpc;
  public readonly subnets: ec2.ISubnet[];
  /** Security group of the Lambdas and the agent runtime. */
  public readonly workloadSecurityGroup: ec2.SecurityGroup;
  public readonly vpcEndpoints: { [key: string]: ec2.IVpcEndpoint } = {};
  public readonly created: boolean;

  constructor(scope: Construct, id: string, props: NetworkingConstructProps) {
    super(scope, id);
    this.created = !props.vpcId;
    let endpoints = props.endpoints;
    let routeTableIds = props.routeTableIds;

    if (this.created) {
      ({ vpc: this.vpc, subnets: this.subnets } = this.createVpc(props));
      endpoints = { bedrockRuntime: true, agentCore: true, stepFunctions: true, logs: true, s3: true };
      routeTableIds = this.subnets.map((s) => s.routeTable.routeTableId);
    } else {
      if (!props.subnetIds || props.subnetIds.length === 0) {
        throw new Error('vpc.subnetIds is required with vpc.vpcId');
      }
      this.vpc = ec2.Vpc.fromLookup(this, 'ExistingVpc', { vpcId: props.vpcId! });
      this.subnets = props.subnetIds.map((subnetId, index) =>
        ec2.Subnet.fromSubnetAttributes(this, `ImportedSubnet${index}`, {
          subnetId,
          availabilityZone: cdk.Fn.select(index, cdk.Fn.getAzs()),
          routeTableId: props.routeTableIds?.[index] ?? cdk.Token.asString(cdk.Fn.ref('AWS::NoValue')),
        })
      );
    }

    this.workloadSecurityGroup = new ec2.SecurityGroup(this, 'WorkloadSecurityGroup', {
      vpc: this.vpc,
      description: 'P&ID digitization Lambdas and agent runtime',
      allowAllOutbound: false,
    });
    this.workloadSecurityGroup.addEgressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(443), 'HTTPS to AWS APIs through VPC endpoints');
    NagSuppressions.addResourceSuppressions(this.workloadSecurityGroup, [
      { id: 'AwsSolutions-EC23', reason: 'Egress only, HTTPS to AWS service endpoints; no ingress rules' },
    ]);

    if (this.created || props.createVpcEndpoints) {
      this.createVpcEndpoints(endpoints, routeTableIds);
    }
  }

  private createVpc(props: NetworkingConstructProps): { vpc: ec2.Vpc; subnets: ec2.ISubnet[] } {
    const region = cdk.Stack.of(this).region;
    const azIds = props.availabilityZoneIds?.length ? props.availabilityZoneIds : AGENTCORE_AZ_IDS[region]?.slice(0, 2);
    if (!azIds || azIds.length === 0) {
      throw new Error(`No AgentCore-supported Availability Zones known for ${region}; set vpc.availabilityZoneIds`);
    }
    const vpc = new ec2.Vpc(this, 'Vpc', {
      ipAddresses: ec2.IpAddresses.cidr(props.cidr),
      natGateways: 0,
      subnetConfiguration: [],
      restrictDefaultSecurityGroup: true,
    });
    const flowLogs = new logs.LogGroup(this, 'FlowLogs', {
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
    vpc.addFlowLog('FlowLog', { destination: ec2.FlowLogDestination.toCloudWatchLogs(flowLogs) });
    NagSuppressions.addResourceSuppressions(vpc, ['batch', 'bedrock-agent-runtime', 'dynamodb'].map((svc) => ({
      id: `Prototype Security Nag Pack-VPC Endpoint for ${svc}`,
      reason: `The workload does not call ${svc}; the VPC has endpoints for every service it uses`,
    })));

    // Subnets are placed by AZ ID, not name: AgentCore supports specific zone IDs, and names map
    // to different IDs in every account.
    const [base, mask] = props.cidr.split('/');
    const octets = base.split('.').map(Number);
    const subnets = azIds.map((azId, i) => {
      const subnet = new ec2.PrivateSubnet(this, `Isolated${i + 1}`, {
        vpcId: vpc.vpcId,
        availabilityZone: azId,
        cidrBlock: `${octets[0]}.${octets[1]}.${octets[2] + i * 16}.0/20`,
        mapPublicIpOnLaunch: false,
      });
      const cfn = subnet.node.defaultChild as ec2.CfnSubnet;
      cfn.addPropertyDeletionOverride('AvailabilityZone');
      cfn.addPropertyOverride('AvailabilityZoneId', azId);
      return subnet;
    });
    if (Number(mask) > 18) {
      throw new Error('vpc.cidr must be /18 or larger (subnets are /20 each)');
    }
    return { vpc, subnets };
  }

  private createVpcEndpoints(flags: EndpointFlags, routeTableIds: string[] | undefined): void {
    const region = cdk.Stack.of(this).region;
    const account = cdk.Stack.of(this).account;

    const iface = (name: string, service: ec2.InterfaceVpcEndpointAwsService, statements: iam.PolicyStatement[]) => {
      const ep = new ec2.InterfaceVpcEndpoint(this, `${name}Endpoint`, {
        vpc: this.vpc,
        service,
        subnets: { subnets: this.subnets },
        securityGroups: [this.createEndpointSecurityGroup(name)],
        privateDnsEnabled: true,
      });
      statements.forEach((s) => ep.addToPolicy(s));
      this.vpcEndpoints[name] = ep;
    };
    const allow = (actions: string[], resources: string[], conditions?: { [k: string]: any }) =>
      new iam.PolicyStatement({ effect: iam.Effect.ALLOW, principals: [new iam.AnyPrincipal()], actions, resources, conditions });

    if (flags.bedrockRuntime) {
      iface('BedrockRuntime', ec2.InterfaceVpcEndpointAwsService.BEDROCK_RUNTIME, [
        allow(['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'], [
          `arn:aws:bedrock:${region}:${account}:inference-profile/*`,
          'arn:aws:bedrock:*::foundation-model/*',
        ]),
      ]);
    }
    if (flags.agentCore) {
      iface('AgentCore', ec2.InterfaceVpcEndpointAwsService.BEDROCK_AGENTCORE, [
        allow(['bedrock-agentcore:InvokeAgentRuntime'], [`arn:aws:bedrock-agentcore:${region}:${account}:runtime/*`]),
      ]);
    }
    if (flags.stepFunctions) {
      iface('StepFunctions', ec2.InterfaceVpcEndpointAwsService.STEP_FUNCTIONS, [
        allow(['states:SendTaskSuccess', 'states:SendTaskFailure', 'states:SendTaskHeartbeat'], ['*']),
      ]);
    }
    if (flags.logs) {
      iface('CloudWatchLogs', ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS, [
        allow(['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents', 'logs:DescribeLogStreams'],
          [`arn:aws:logs:${region}:${account}:*`]),
      ]);
    }
    if (flags.s3) {
      if (!routeTableIds || routeTableIds.length !== this.subnets.length) {
        throw new Error('endpoints.s3 needs vpc.routeTableIds (one per subnet) for the S3 gateway endpoint');
      }
      const s3ep = new ec2.GatewayVpcEndpoint(this, 'S3Endpoint', {
        vpc: this.vpc,
        service: ec2.GatewayVpcEndpointAwsService.S3,
        subnets: [{ subnets: this.subnets }],
      });
      // buckets of this account only (the data buckets live in the application stack, which depends on this one)
      s3ep.addToPolicy(allow(['s3:GetObject', 's3:PutObject', 's3:AbortMultipartUpload', 's3:ListBucket', 's3:GetBucketLocation'],
        ['*'], { StringEquals: { 'aws:ResourceAccount': account } }));
      // AgentCore keeps zip-deployed agent code in service-owned buckets and fetches it through the VPC
      s3ep.addToPolicy(allow(['s3:GetObject'], [`arn:aws:s3:::acr-code-*-${region}-an`, `arn:aws:s3:::acr-code-*-${region}-an/*`],
        { StringEquals: { 'aws:PrincipalServiceName': 'bedrock-agentcore.amazonaws.com' } }));
      this.vpcEndpoints['S3'] = s3ep;
    }
  }

  private createEndpointSecurityGroup(serviceName: string): ec2.SecurityGroup {
    const sg = new ec2.SecurityGroup(this, `${serviceName}EndpointSG`, {
      vpc: this.vpc,
      description: `Security group for ${serviceName} VPC endpoint`,
      allowAllOutbound: false,
    });
    sg.addIngressRule(this.workloadSecurityGroup, ec2.Port.tcp(443), `HTTPS from the workload to ${serviceName}`);
    NagSuppressions.addResourceSuppressions(sg, [
      { id: 'AwsSolutions-EC23', reason: `${serviceName} endpoint security group only admits the workload security group` },
    ]);
    return sg;
  }

  /** VPC settings for the Lambdas and the agent runtime. */
  public getVpcConfig(): { vpc: ec2.IVpc; vpcSubnets: ec2.SubnetSelection; securityGroups: ec2.SecurityGroup[] } {
    return { vpc: this.vpc, vpcSubnets: { subnets: this.subnets }, securityGroups: [this.workloadSecurityGroup] };
  }

  public addOutputs(): void {
    new cdk.CfnOutput(this, 'VpcId', { value: this.vpc.vpcId, description: 'VPC of the Lambdas and the agent runtime' });
    new cdk.CfnOutput(this, 'SubnetIds', {
      value: this.subnets.map((s) => s.subnetId).join(','),
      description: 'Subnets of the Lambdas and the agent runtime',
    });
    new cdk.CfnOutput(this, 'WorkloadSecurityGroupId', {
      value: this.workloadSecurityGroup.securityGroupId,
      description: 'Security group of the Lambdas and the agent runtime',
    });
    new cdk.CfnOutput(this, 'VpcEndpoints', {
      value: Object.keys(this.vpcEndpoints).join(',') || 'none',
      description: 'VPC endpoints created by the stack',
    });
  }
}
