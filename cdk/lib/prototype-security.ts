// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { App, CfnResource, Stack } from "aws-cdk-lib";
import { IConstruct } from "constructs";
import {
  NagPack,
  NagPackProps,
  NagMessageLevel,
  rules,
  NagRuleCompliance,
  NagRuleResult,
  NagRules,
} from "cdk-nag";
import { CfnVPC, CfnVPCEndpoint } from "aws-cdk-lib/aws-ec2";
import { CfnBucket } from "aws-cdk-lib/aws-s3";
import { CfnGuardrail } from "aws-cdk-lib/aws-bedrock";
import { CfnNotebookInstance } from "aws-cdk-lib/aws-sagemaker";

export class PrototypeSecurityNagPack extends NagPack {
  constructor(props?: NagPackProps) {
    super(props);
    this.packName = "Prototype Security Nag Pack";
  }
  public visit(node: IConstruct): void {
    if (node instanceof App) {
      this.bedrockGuardrailsExists(node);
    } else if (node instanceof CfnResource) {
      this.lambdaInVpc(node);
      [
        "s3",
        "dynamodb",
        "bedrock",
        "bedrock-agent",
        "bedrock-runtime",
        "bedrock-agent-runtime",
        "batch",
      ].forEach((serviceName) => this.serviceVpcEndpoint(node, serviceName));
      this.s3CMK(node);
      this.bedrockGuardrailsSensitiveInformation(node);
      this.notebookNoRootAccess(node);
    }
  }
  lambdaInVpc = (node: CfnResource) => {
    this.applyRule({
      info: "Lambda function is not VPC enabled.",
      explanation:
        "Resources that reside within an Amazon VPC have an extra layer of security when compared to resources that use public endpoints.",
      level: NagMessageLevel.ERROR,
      node,
      rule: rules.lambda.LambdaInsideVPC,
    });
  };
  serviceVpcEndpoint = (node: CfnResource, serviceName: string) => {
    this.applyRule({
      info: `VPC does not have an endpoint for ${serviceName}.`,
      explanation: "Protect your data using Amazon VPC and AWS Private link.",
      level: NagMessageLevel.WARN,
      node,
      ruleSuffixOverride: `VPC Endpoint for ${serviceName}`,
      rule: (node: CfnResource): NagRuleResult => {
        if (node instanceof CfnVPC) {
          //check if the vpc has a vpc endpoint for this service
          for (const child of Stack.of(node).node.findAll()) {
            if (
              child instanceof CfnVPCEndpoint &&
              child.serviceName?.indexOf(serviceName) !== -1
            ) {
              return NagRuleCompliance.COMPLIANT;
            }
          }
          return NagRuleCompliance.NON_COMPLIANT;
        } else {
          return NagRuleCompliance.NOT_APPLICABLE;
        }
      },
    });
  };
  s3CMK = (node: CfnResource) => {
    this.applyRule({
      info: "S3 bucket does not use AWS KMS Customer Managed Key.",
      explanation:
        "Customer managed keys provide customers full control including lifecycle management, and access control.",
      level: NagMessageLevel.ERROR,
      node,
      ruleSuffixOverride: "CMK for S3 buckets",
      rule: (node: CfnResource): NagRuleResult => {
        if (node instanceof CfnBucket) {
          if (node.bucketEncryption === undefined) {
            return NagRuleCompliance.NON_COMPLIANT;
          }
          const encryption = Stack.of(node).resolve(node.bucketEncryption);
          if (encryption.serverSideEncryptionConfiguration === undefined) {
            return NagRuleCompliance.NON_COMPLIANT;
          }
          const sse = Stack.of(node).resolve(
            encryption.serverSideEncryptionConfiguration
          );
          for (const rule of sse) {
            const defaultEncryption = Stack.of(node).resolve(
              rule.serverSideEncryptionByDefault
            );
            if (defaultEncryption === undefined) {
              return NagRuleCompliance.NON_COMPLIANT;
            }
            let key: any
            try {
              key = NagRules.resolveIfPrimitive(
                node,
                defaultEncryption.kmsMasterKeyId
              );
            } catch (error) {
              try {
                key = NagRules.resolveResourceFromIntrinsic(node, defaultEncryption.kmsMasterKeyId)
              } catch (error) {
                console.error("[PrototypeSecurityPack]", "Unable to resolve KMS key id to verify S3 encryption configuration")
              }
            }
            if (key === undefined) {
              return NagRuleCompliance.NON_COMPLIANT;
            }
          }
          return NagRuleCompliance.COMPLIANT;
        } else {
          return NagRuleCompliance.NOT_APPLICABLE;
        }
      },
    });
  };
  bedrockGuardrailsExists = (node: App | Stack) => {
    //find the first CfnResource node to apply the annotations on
    const resourceNode = node.node
      .findAll()
      .find((node) => node instanceof CfnResource);
    if (resourceNode) {
      this.applyRule({
        info: "Missing Bedrock Guardrails.",
        explanation:
          "Create guardrails to safeguard your generative AI applications.",
        level: NagMessageLevel.WARN,
        node: resourceNode,
        ruleSuffixOverride: "Bedrock Guardrails Exists",
        rule: (_node: CfnResource): NagRuleResult => {
          //get all resources under the app or stack to check for CfnGuardrail presence of
          if (
            node.node.findAll().some((node) => node instanceof CfnGuardrail)
          ) {
            return NagRuleCompliance.COMPLIANT;
          }
          return NagRuleCompliance.NON_COMPLIANT;
        },
      });
    }
  };
  bedrockGuardrailsSensitiveInformation = (node: CfnResource) => {
    this.applyRule({
      info: "Missing Bedrock Guardrails sensitive information policy configuration.",
      explanation:
        "Create guardrails to block sensitive information and to implement safeguards for your generative AI applications.",
      level: NagMessageLevel.ERROR,
      node,
      ruleSuffixOverride: "Bedrock Guardrails Sensitive Information",
      rule: (node: CfnResource): NagRuleResult => {
        //check if CfnGuardrail has Sensitive information config
        if (node instanceof CfnGuardrail) {
          const config = Stack.of(node).resolve(
            node.sensitiveInformationPolicyConfig
          );
          if (config === undefined) {
            return NagRuleCompliance.NON_COMPLIANT;
          }
          const piiConfig = Stack.of(node).resolve(config.piiEntitiesConfig);
          if (piiConfig === undefined) {
            return NagRuleCompliance.NON_COMPLIANT;
          }
          return NagRuleCompliance.COMPLIANT;
        } else {
          return NagRuleCompliance.NOT_APPLICABLE;
        }
      },
    });
  };
  notebookNoRootAccess = (node: CfnResource) => {
    this.applyRule({
      info: "Root access on notebook.",
      explanation: "Disable root access on notebook.",
      level: NagMessageLevel.ERROR,
      node,
      ruleSuffixOverride: "Noteboook Root access",
      rule: (node: CfnResource): NagRuleResult => {
        if (node instanceof CfnNotebookInstance) {
          const rootAccess = NagRules.resolveIfPrimitive(node, node.rootAccess);
          if (rootAccess === "Disabled") {
            return NagRuleCompliance.COMPLIANT;
          }
          return NagRuleCompliance.NON_COMPLIANT;
        } else {
          return NagRuleCompliance.NOT_APPLICABLE;
        }
      },
    });
  };
}
