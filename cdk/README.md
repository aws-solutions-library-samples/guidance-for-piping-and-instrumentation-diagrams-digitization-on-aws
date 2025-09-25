# P&ID Processing CDK Stack

This CDK stack deploys a serverless pipeline for processing P&ID (Piping and Instrumentation Diagram) documents using AWS Lambda, SageMaker, Textract, and Step Functions.

## Architecture

The stack includes:
- **Storage**: S3 buckets with KMS encryption for input, processing, output, and temporary files
- **Processing**: Lambda functions for input validation, line detection, and graph generation
- **ML**: SageMaker endpoint for symbol detection
- **Orchestration**: Step Functions for pipeline coordination
- **Networking**: Optional VPC deployment with VPC endpoints

## VPC Configuration

### Overview

Lambda functions can be deployed in an existing VPC with private subnets and VPC endpoints for secure, internet-free operation. This provides:

- **Enhanced Security**: Complete isolation from the internet
- **Cost Optimization**: No NAT Gateway required (~$45/month savings)
- **Compliance**: Suitable for regulated environments
- **Performance**: Direct AWS backbone routing through VPC endpoints

### Configuration File

Create or update `config.json` in the CDK root directory:

```json
{
  "vpc": {
    "vpcId": "vpc-xxxxxxxxx",
    "subnetIds": ["subnet-xxxxx", "subnet-yyyyy"],
    "createVpcEndpoints": true
  },
  "endpoints": {
    "s3": true,
    "sagemaker": true,
    "textract": true,
    "logs": true
  },
  "model": {
    "s3Uri": "s3://your-bucket-name/models/symbol-detection/model.tar.gz"
  }
}
```

### Configuration Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `vpc.vpcId` | Your existing VPC ID | Yes (for VPC deployment) |
| `vpc.subnetIds` | Array of private subnet IDs where Lambda functions will be deployed | Yes (for VPC deployment) |
| `vpc.createVpcEndpoints` | Whether to create VPC endpoints for AWS services | No (default: true) |
| `endpoints.s3` | Create S3 Gateway endpoint (free) | No (default: true) |
| `endpoints.sagemaker` | Create SageMaker Runtime interface endpoint | No (default: true) |
| `endpoints.textract` | Create Textract interface endpoint | No (default: true) |
| `endpoints.logs` | Create CloudWatch Logs interface endpoint | No (default: true) |
| `model.s3Uri` | S3 URI of the model.tar.gz file for SageMaker | Yes |

### Deployment Steps

1. **Configure VPC settings**:
   ```bash
   # Copy the template and fill in your values
   cp config.json.template config.json
   # Edit config.json with your VPC ID, subnet IDs, and model S3 URI
   ```

2. **Deploy the stack**:
   ```bash
   cdk deploy
   ```

3. **Verify deployment**:
   - Check CloudFormation outputs for VPC configuration status and deployed region
   - Verify VPC endpoints are created in your VPC console
   - Test Lambda function execution

### VPC Requirements

- **VPC**: Existing VPC with DNS resolution and DNS hostnames enabled
- **Subnets**: Private subnets (no internet gateway route)
- **Security Groups**: Automatically created with least-privilege access
- **Route Tables**: Must have routes to VPC endpoints (automatically configured)

### VPC Endpoints Created

| Service | Type | Purpose | Cost |
|---------|------|---------|------|
| S3 | Gateway | S3 bucket access | Free |
| SageMaker Runtime | Interface | ML model inference | ~$7.30/month |
| Textract | Interface | Document text extraction | ~$7.30/month |
| CloudWatch Logs | Interface | Lambda logging | ~$7.30/month |

*Interface endpoint costs are per AZ per month in us-east-1*

### Security Groups

The stack creates security groups with minimal required access:

- **Lambda Security Group**: 
  - Outbound HTTPS (443) to VPC endpoints
  - No inbound rules
- **Endpoint Security Groups**: 
  - Inbound HTTPS (443) from Lambda security group only

### Troubleshooting

#### Lambda Functions Not Starting
- Verify subnet IDs are correct and in the same VPC
- Check that subnets have available IP addresses
- Ensure VPC has DNS resolution enabled

#### Service Access Issues
- Verify VPC endpoints are created and in "Available" state
- Check security group rules allow HTTPS traffic
- Confirm route tables include VPC endpoint routes

#### High Costs
- Monitor VPC endpoint usage in Cost Explorer
- Consider disabling unused endpoints in configuration
- Endpoints are charged per AZ - review AZ distribution

#### Region Mismatch
- Ensure your VPC is in the same region where you're deploying the stack
- VPC endpoints must be in the same region as the VPC
- Check CloudFormation outputs for the actual deployed region

### Deployment Without VPC

If no `config.json` file exists or VPC/subnet IDs are empty, Lambda functions deploy without VPC configuration and use internet gateway for AWS service access.

## Standard Deployment

### Prerequisites

- AWS CLI configured
- Node.js 18+ installed
- CDK CLI installed (`npm install -g aws-cdk`)

### Installation

```bash
# Install dependencies
npm install

# Build the project (required for shared files sync)
npm run build

# Bootstrap CDK (first time only)
cdk bootstrap

# Deploy the stack
cdk deploy
```

### Usage

1. **Upload P&ID files** to the input S3 bucket (supports JPG, PNG, PDF)
2. **Monitor processing** through Step Functions console
3. **Retrieve results** from the output S3 bucket

### ML Model Deployment

1. Train your YOLO/Faster R-CNN model for symbol detection
2. Upload model artifacts to S3 (e.g., `s3://your-bucket/models/symbol-detection/model.tar.gz`)
3. Update the `model.s3Uri` in `config.json` with your model's S3 URI
4. Redeploy the stack to update the SageMaker endpoint

### Configuration

The stack uses CDK context and configuration files:
- Region uses CDK defaults (can be set via CDK CLI or environment)
- Account is detected automatically
- Model S3 URI must be specified in config.json
- KMS encryption is enabled for all S3 buckets
- CloudWatch log retention is set to 1 week
- CDK Nag compliance is enforced

### Monitoring

- **CloudWatch Logs**: Lambda function logs with structured logging
- **CloudWatch Metrics**: Lambda duration, errors, and invocations
- **Step Functions**: Pipeline execution status and history
- **S3 Metrics**: Bucket usage and request metrics

### Cost Optimization

- Lambda functions use appropriate memory allocation
- S3 Intelligent Tiering for cost optimization
- VPC endpoints eliminate NAT Gateway costs
- Short log retention periods

### Security Features

- **Encryption**: KMS encryption for all data at rest
- **IAM**: Least-privilege custom policies (no managed policies)
- **VPC**: Optional private subnet deployment
- **CDK Nag**: Automated security compliance checking

### Clean Up

```bash
# Destroy all resources
cdk destroy

# Note: S3 buckets with data may need manual deletion
```

## Support

For issues or questions:
1. Check CloudWatch logs for Lambda errors
2. Review Step Function execution history
3. Verify CDK Nag compliance reports
4. Monitor VPC Flow Logs for networking issues
