# Troubleshooting Guide

This document provides solutions for common issues encountered with the P&ID Digitization Pipeline.

## Common Issues

### Step Functions Errors

#### JSONPath Errors
**Error**: `JSONPath '$.processing_config' could not be found`

**Cause**: Missing required input structure

**Solution**: Ensure your Step Functions input includes `processing_config`:
```json
{
  "image_key": "image.png",
  "input_bucket": "bucket-name",
  "processing_config": {}  // Add this even if empty
}
```

#### State Machine Execution Failed
**Error**: Step Functions execution shows failed state

**Solution**:
1. Check the execution graph in AWS Console
2. Click on the failed state to see error details
3. Check CloudWatch logs for the specific Lambda function
4. Look for validation or processing errors in the logs

### Configuration Issues

#### Configuration Validation Errors
**Error**: `Configuration validation failed for line_detection.threshold`

**Cause**: Invalid parameter type or value

**Solution**: Check parameter types and ranges:
```json
{
  "processing_config": {
    "line_detection": {
      "threshold": 3,        // Must be integer, not "3"
      "rho": 0.5,           // Must be float
      "max_line_gap": 120   // Must be positive integer
    }
  }
}
```

**Common validation errors:**
- `threshold` must be integer between 1-20
- `rho` must be float between 0.1-2.0
- `merge_distance_threshold` must be float between 0.001-0.1
- `manual_coordinates` must have integer x, y, width, height

#### Manual Coordinates Validation
**Error**: `Invalid coordinate values - must be integers`

**Solution**: Ensure all coordinate values are integers:
```json
{
  "manual_coordinates": {
    "x": 100,     // Integer, not 100.0
    "y": 50,      // Integer, not "50"
    "width": 800, // Integer
    "height": 600 // Integer
  }
}
```

**Error**: `Crop region exceeds image bounds`

**Solution**: Verify coordinates are within image dimensions:
```json
{
  "manual_coordinates": {
    "x": 100,
    "y": 50,
    "width": 800,  // x + width must be ≤ image width
    "height": 600  // y + height must be ≤ image height
  }
}
```

### Lambda Function Issues

#### Function Timeout
**Error**: Lambda function timeout after 15 minutes

**Solutions**:
1. **Reduce image size** before processing:
   ```bash
   # Resize image before upload
   convert large-image.png -resize 2000x2000\> smaller-image.png
   ```

2. **Use manual coordinates** to process smaller regions:
   ```json
   {
     "processing_config": {
       "notes_processing": {
         "manual_coordinates": {
           "x": 0, "y": 0, "width": 1000, "height": 1000
         }
       }
     }
   }
   ```

3. **Optimize parameters** for faster processing:
   ```json
   {
     "processing_config": {
       "line_detection": {
         "threshold": 6,      // Higher threshold = fewer detections
         "min_line_length": 20 // Longer minimum = fewer lines
       }
     }
   }
   ```

#### Memory Issues
**Error**: Lambda function out of memory

**Solutions**:
1. **Reduce image resolution** before processing
2. **Use Docker-based functions** which have higher memory limits
3. **Process images in smaller chunks** using manual coordinates

#### Import Errors
**Error**: `No module named 'config_helper'`

**Cause**: Shared files not synchronized

**Solution**:
```bash
cd cdk
node scripts/sync-shared-files.js
cdk deploy
```

### Line Detection Issues

#### Parallel Lines Merging Incorrectly
**Issue**: Two parallel lines being merged into a single diagonal line

**Cause**: `merge_distance_threshold` too high

**Solution**: Reduce merge distance threshold:
```json
{
  "processing_config": {
    "line_detection": {
      "postprocess_params": {
        "merge_distance_threshold": 0.008,  // Reduced from 0.02
        "angular_tolerance": 5.0             // More strict angle matching
      }
    }
  }
}
```

#### Missing Line Segments
**Issue**: Line segments missing or fragmented

**Cause**: Detection parameters too restrictive

**Solution**: Adjust core detection parameters:
```json
{
  "processing_config": {
    "line_detection": {
      "threshold": 2,         // Lower threshold = more detections
      "max_line_gap": 150,    // Larger gap = more connections
      "min_line_length": 5,   // Shorter minimum = more lines
      "postprocess_params": {
        "extension_padding": 0.02  // More extension for connections
      }
    }
  }
}
```

#### Too Many False Positive Lines
**Issue**: Detecting noise or artifacts as lines

**Cause**: Detection too sensitive

**Solution**: Make detection more selective:
```json
{
  "processing_config": {
    "line_detection": {
      "threshold": 6,         // Higher threshold = more selective
      "min_line_length": 20   // Longer minimum = less noise
    }
  }
}
```

#### Lines Disappearing After Thinning
**Issue**: Thin lines disappear during preprocessing

**Cause**: Thinning removes already-thin lines

**Solution**: Disable thinning for thin lines:
```json
{
  "processing_config": {
    "line_detection": {
      "enable_thinning": false
    }
  }
}
```

### Text Detection Issues

#### Bedrock Data Automation Timeout
**Error**: `BDA job did not complete within timeout period`

**Solution**: Increase timeout and retries:
```json
{
  "processing_config": {
    "text_detection": {
      "timeout_seconds": 600,  // Increased to 10 minutes
      "max_retries": 5
    }
  }
}
```

#### Missing Text Elements
**Issue**: Text not being detected in specific regions

**Cause**: Text outside processed region or low quality

**Solutions**:
1. **Verify image quality** - text should be clearly readable
2. **Check manual coordinates** - ensure text region is included
3. **Use original image** - avoid over-preprocessing before text detection

### Symbol Detection Issues

#### SageMaker Endpoint Errors
**Error**: `EndpointNotFound` or `ModelNotFound`

**Cause**: SageMaker endpoint not deployed or model URI incorrect

**Solution**:
1. Check model URI in `cdk/config.json`:
   ```json
   {
     "model": {
       "s3Uri": "s3://your-bucket/path/to/model.tar.gz"
     }
   }
   ```

2. Verify endpoint is deployed:
   ```bash
   aws sagemaker list-endpoints
   ```

3. Redeploy if necessary:
   ```bash
   cdk deploy
   ```

#### Low Symbol Detection Confidence
**Issue**: Symbols not being detected or low confidence scores

**Solution**: Adjust confidence threshold:
```json
{
  "processing_config": {
    "symbol_detection": {
      "confidence_threshold": 0.7,  // Reduced from 0.9
      "nms_threshold": 0.5
    }
  }
}
```

### Graph Generation Issues

#### Component Filtering Removing Valid Elements
**Issue**: Important symbols or lines being filtered out

**Cause**: Component filtering too aggressive

**Solution**: Disable or adjust component filtering:
```json
{
  "processing_config": {
    "graph_generation": {
      "component_filter": {
        "enabled": false  // Disable completely
      }
    }
  }
}
```

Or make filtering more conservative:
```json
{
  "processing_config": {
    "graph_generation": {
      "component_filter": {
        "enabled": true,
        "min_component_size": 2,                    // Keep smaller components
        "max_symbol_density_for_removal": 0.05     // Lower removal threshold
      }
    }
  }
}
```

#### Missing Connections Between Elements
**Issue**: Symbols and lines not connecting properly

**Cause**: Distance thresholds too restrictive

**Solution**: Increase distance thresholds:
```json
{
  "processing_config": {
    "graph_generation": {
      "distance_threshold_symbols": 80,  // Increased from 60
      "distance_threshold_text": 40,     // Increased from 30
      "distance_threshold_lines": 30     // Increased from 20
    }
  }
}
```

### S3 and Access Issues

#### S3 Access Denied
**Error**: `AccessDenied` when accessing S3 buckets

**Solutions**:
1. **Check bucket policies** and IAM permissions
2. **Verify VPC endpoints** are configured if using VPC
3. **Check KMS key permissions** for encrypted buckets

#### Files Not Found in Expected Locations
**Issue**: Processing results not found in S3

**Cause**: Execution-based file organization

**Solution**: Files are organized by execution ID:
```
s3://bucket/executions/exec-20250108-150426-abc123/
├── processed/image_processed.png
├── text_detection_results.json
├── graph_data.json
└── visualizations/physical_layout.png
```

Use the execution ID from Lambda responses to locate files.

### Performance Optimization

#### Slow Processing Times
**Issue**: Pipeline takes very long to process images

**Solutions**:
1. **Reduce image size**:
   ```bash
   # Resize before upload
   convert input.png -resize 1920x1920\> optimized.png
   ```

2. **Use manual coordinates** for targeted processing:
   ```json
   {
     "processing_config": {
       "notes_processing": {
         "manual_coordinates": {
           "x": 100, "y": 100, "width": 800, "height": 600
         }
       }
     }
   }
   ```

3. **Optimize parameters**:
   ```json
   {
     "processing_config": {
       "line_detection": {
         "threshold": 5,                    // Higher = faster
         "enable_thinning": false,          // Skip if not needed
         "postprocess_params": {
           "enable_symbol_intersection": false  // Disable if not needed
         }
       },
       "graph_generation": {
         "component_filter": {
           "enabled": false                 // Skip filtering
         }
       }
     }
   }
   ```

## Debugging Steps

### 1. Check CloudWatch Logs
```bash
# List log groups
aws logs describe-log-groups --log-group-name-prefix "/aws/lambda/pnid"

# Get recent log events
aws logs filter-log-events \
  --log-group-name "/aws/lambda/InputValidator" \
  --start-time $(date -d '1 hour ago' +%s)000
```

### 2. Test Individual Lambda Functions
```bash
# Test InputValidator
aws lambda invoke \
  --function-name InputValidator \
  --payload '{"image_key":"test.png","input_bucket":"bucket","processing_config":{}}' \
  response.json

cat response.json
```

### 3. Validate Configuration Locally
```python
# Test configuration validation
import json
from cdk.lambda.input_validator.config_validator import ConfigValidator

validator = ConfigValidator()
config = {
  "line_detection": {
    "threshold": 5,
    "max_line_gap": 150
  }
}

try:
  validated = validator.get_validated_config('line_detection', config)
  print("Valid configuration:", validated)
except Exception as e:
  print("Validation error:", str(e))
```

### 4. Monitor Step Functions Execution
1. Go to AWS Console → Step Functions
2. Find your state machine
3. Click on execution to see execution graph
4. Check each step for errors or timeouts
5. Review input/output for each step

### 5. Check S3 File Organization
```bash
# List files in execution directory
aws s3 ls s3://your-output-bucket/executions/exec-20250108-150426-abc123/ --recursive

# Download specific result for inspection
aws s3 cp s3://your-output-bucket/executions/exec-20250108-150426-abc123/graph_data.json ./
```

## Getting Help

### Error Reporting
When reporting issues, include:
1. **Complete error message** from CloudWatch logs
2. **Input configuration** used (sanitized)
3. **Image characteristics** (size, format, complexity)
4. **Expected vs actual behavior**
5. **AWS region and deployment details**

### Log Analysis
Key log patterns to look for:
- `Configuration validation failed` - Parameter issues
- `Error in [function] processing` - Processing failures
- `Timeout` - Performance issues
- `Access denied` - Permission problems
- `File not found` - S3 path issues

### Performance Profiling
Monitor these CloudWatch metrics:
- **Duration** - Function execution time
- **Memory utilization** - Peak memory usage
- **Error rate** - Failed invocations
- **Throttles** - Concurrent execution limits

For additional support, check the main [README.md](../README.md) or create an issue in the project repository.
