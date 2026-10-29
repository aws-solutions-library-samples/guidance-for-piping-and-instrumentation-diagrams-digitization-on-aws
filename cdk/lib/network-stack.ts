import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';

import { StackConfig } from './config';
import { NetworkingConstruct } from './constructs/networking';
import { suppressCdkHelperFindings } from './nag';

/**
 * VPC, subnets, workload security group and VPC endpoints, in a stack of their own.
 *
 * AgentCore can keep the runtime's network interfaces in the subnets for up to 8 hours after the
 * runtime is deleted. Keeping the network out of the application stack means a failed deploy or a
 * `cdk destroy` of the application never waits on them; this stack is removed last, once they are gone.
 */
export class PNIDNetworkStack extends cdk.Stack {
  public readonly networking: NetworkingConstruct;

  constructor(scope: Construct, id: string, config: StackConfig, props?: cdk.StackProps) {
    super(scope, id, props);
    this.networking = new NetworkingConstruct(this, 'Networking', {
      vpcId: config.vpc.vpcId || undefined,
      subnetIds: config.vpc.subnetIds,
      routeTableIds: config.vpc.routeTableIds?.length ? config.vpc.routeTableIds : undefined,
      createVpcEndpoints: config.vpc.createVpcEndpoints,
      endpoints: config.endpoints,
      cidr: config.vpc.cidr,
      availabilityZoneIds: config.vpc.availabilityZoneIds,
    });
    this.networking.addOutputs();
    suppressCdkHelperFindings(this);
  }
}
