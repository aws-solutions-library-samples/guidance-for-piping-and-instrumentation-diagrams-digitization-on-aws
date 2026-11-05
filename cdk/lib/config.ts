import * as fs from 'fs';
import * as path from 'path';
import { EndpointFlags } from './constructs/networking';

/** Per-execution digitizer settings; a StartExecution input can override any of them under "config". */
export interface DigitizationConfig {
  modelId: string;
  allowedModelIds: string[];
  /** "tiled": tiled detect then trace; "single": one call on the whole sheet. */
  detect: 'tiled' | 'single';
  /** modelId: run the review on another allowed model; null = same as modelId. */
  review: { enabled: boolean; maxViews: number; modelId: string | null };
  dashedAsPiping: boolean;
  pdf: { dpi: number; maxPages: number };
}

export interface StackConfig {
  /** Empty vpcId: the stack creates its own isolated VPC. Otherwise the existing VPC and subnets are used. */
  vpc: {
    vpcId: string;
    cidr: string;
    availabilityZoneIds: string[];
    subnetIds: string[];
    routeTableIds?: string[];
    createVpcEndpoints: boolean;
  };
  endpoints: EndpointFlags;
  digitization: DigitizationConfig;
  orchestration: {
    maxConcurrentSheets: number;
    sheetTimeoutMinutes: number;
    uploadTrigger: { enabled: boolean; prefix: string };
  };
  /** Connector for Spatial Data Management on AWS (docs/SDMA_CONNECTOR.md). */
  sdma: {
    enabled: boolean;
    /** SDMA content bucket the workflow reads drawings from. */
    contentBucketName: string;
    /** KMS key of the content bucket, if it uses SSE-KMS; empty otherwise. */
    contentBucketKmsKeyArn: string;
    /**
     * Execution roles of SDMA's ConnectorInvocationFunction, ConnectorInvocationAsyncFunction (they run the
     * connector) and ResourceOperationFunction (it test-assumes the role when the connector is created).
     */
    trustedRoleArns: string[];
  };
}

const DEFAULTS: StackConfig = JSON.parse(
  fs.readFileSync(path.join(__dirname, '..', 'config.json.template'), 'utf8'),
);

function merge<T>(base: T, over: any): T {
  if (over === undefined || over === null || typeof over !== 'object' || Array.isArray(over)) {
    return over === undefined ? base : over;
  }
  const out: any = { ...base };
  for (const [k, v] of Object.entries(over)) {
    out[k] = merge((base as any)?.[k], v);
  }
  return out;
}

/** cdk/config.json over the defaults in config.json.template; config.json is optional. */
export function loadConfig(): StackConfig {
  const file = path.join(__dirname, '..', 'config.json');
  const user = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : {};
  const cfg = merge(DEFAULTS, user);
  const d = cfg.digitization;
  if (!d.allowedModelIds.includes(d.modelId)) {
    throw new Error(`digitization.modelId ${d.modelId} must be one of digitization.allowedModelIds`);
  }
  if (d.review.modelId != null && !d.allowedModelIds.includes(d.review.modelId)) {
    throw new Error(`digitization.review.modelId ${d.review.modelId} must be null or one of digitization.allowedModelIds`);
  }
  if (cfg.orchestration.sheetTimeoutMinutes < 5 || cfg.orchestration.sheetTimeoutMinutes > 465) {
    throw new Error('orchestration.sheetTimeoutMinutes must be between 5 and 465 (AgentCore sessions last at most 8 hours)');
  }
  if (cfg.sdma.enabled && (!cfg.sdma.contentBucketName || !cfg.sdma.trustedRoleArns.length)) {
    throw new Error('sdma.enabled needs sdma.contentBucketName and sdma.trustedRoleArns (see docs/SDMA_CONNECTOR.md)');
  }
  return cfg;
}

/** The per-execution part of the config, as the PrepareInput Lambda receives it. */
export function digitizationDefaults(d: DigitizationConfig): Omit<DigitizationConfig, 'allowedModelIds'> {
  const { allowedModelIds, ...rest } = d;
  return rest;
}
