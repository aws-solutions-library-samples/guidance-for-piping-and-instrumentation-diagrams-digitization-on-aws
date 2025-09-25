# API Reference

This document provides detailed technical reference for the P&ID Digitization Pipeline Lambda functions, data formats, and S3 organization.

## Lambda Functions

### InputValidator
**Function Name**: `InputValidator`  
**Runtime**: Python 3.13  
**Purpose**: Validates uploaded files and initializes processing configuration

#### Input
```json
{
  "image_key": "diagrams/pnid-001.png",
  "input_bucket": "my-input-bucket",
  "processing_config": {
    // Optional processing parameters
  }
}
```

#### Output
```json
{
  "statusCode": 200,
  "validated_image": {
    "key": "diagrams/pnid-001.png",
    "bucket": "my-input-bucket",
    "size": 2048576,
    "format": "PNG"
  },
  "processing_config": {
    // Validated and merged configuration
  },
  "execution_id": "exec-20250108-150426-abc123"
}
```

### NotesProcessor
**Function Name**: `NotesProcessor`  
**Runtime**: Python 3.13  
**Purpose**: Removes notes sections and frames from P&ID diagrams

#### Input
```json
{
  "image_key": "diagrams/pnid-001.png",
  "input_bucket": "my-input-bucket",
  "processing_config": {
    "notes_processing": {
      "manual_coordinates": {
        "x": 100, "y": 50, "width": 800, "height": 600
      },
      "remove_notes_section": true,
      "frame_config": {
        "remove_frame": true
      }
    }
  }
}
```

#### Output
```json
{
  "statusCode": 200,
  "processing_mode": "auto",
  "processed_key": "exec-20250108-150426-abc123/notes-processing/processed_image.png",
  "processed_bucket": "my-output-bucket",
  "original_image_dimensions": {"width": 1920, "height": 1080},
  "processed_image_dimensions": {"width": 1800, "height": 1000},
  "notes_coordinates": {
    "x": 1800, "y": 0, "width": 120, "height": 1080,
    "confidence": 0.95, "method_used": "automatic_detection"
  },
  "frame_info": {
    "frame_detected": true,
    "frame_removed": true,
    "frame_bounds": {"left": 10, "top": 10, "right": 10, "bottom": 10}
  }
}
```

### TextDetection
**Function Name**: `TextDetection`  
**Runtime**: Python 3.13  
**Purpose**: Extracts text elements using Amazon Bedrock Data Automation

#### Input
```json
{
  "image_key": "diagrams/pnid-001.png",
  "input_bucket": "my-input-bucket",
  "processing_config": {
    "text_detection": {
      "timeout_seconds": 300,
      "max_retries": 3
    }
  }
}
```

#### Output
```json
{
  "statusCode": 200,
  "s3_results": {
    "bucket": "my-output-bucket",
    "text_detection_results_key": "exec-20250108-150426-abc123/text-detection/text_detection_results.json",
    "debug_image_key": "exec-20250108-150426-abc123/text-detection/debug_image.png"
  },
  "summary": {
    "text_elements_count": 45,
    "bda_job_id": "bda-job-12345",
    "execution_id": "exec-20250108-150426-abc123",
    "coordinates_in_original_space": true,
    "debug_image_generated": true
  }
}
```

### SymbolDetection
**Function Name**: `SymbolDetection`  
**Runtime**: Python 3.13  
**Purpose**: Detects symbols using trained SageMaker model

#### Input
```json
{
  "image_key": "diagrams/pnid-001.png",
  "input_bucket": "my-input-bucket",
  "processing_config": {
    "symbol_detection": {
      "confidence_threshold": 0.9,
      "nms_threshold": 0.4
    }
  }
}
```

#### Output
```json
{
  "statusCode": 200,
  "s3_results": {
    "bucket": "my-output-bucket",
    "detections_key": "exec-20250108-150426-abc123/symbol-detection/detections.json",
    "debug_image_labeled_key": "exec-20250108-150426-abc123/symbol-detection/debug_image_labeled.png",
    "debug_image_boxes_key": "exec-20250108-150426-abc123/symbol-detection/debug_image_boxes.png",
    "debug_image_key": "exec-20250108-150426-abc123/symbol-detection/debug_image_labeled.png"
  },
  "summary": {
    "symbols_count": 23,
    "confidence_threshold": 0.9,
    "execution_id": "exec-20250108-150426-abc123",
    "debug_images_generated": true
  }
}
```

### LineDetection
**Function Name**: `LineDetection`  
**Runtime**: Python 3.13 (Docker)  
**Purpose**: Detects connecting lines using computer vision

#### Input
- Image location and bounding boxes from previous steps
- Line detection configuration parameters

#### Output
```json
{
  "statusCode": 200,
  "line_count": 156,
  "intersection_count": 23,
  "s3_results": {
    "bucket": "my-output-bucket",
    "lines_s3_key": "exec-20250108-150426-abc123/line-detection/lines.json"
  },
  "summary": {
    "image_dimensions": [1800, 1000],
    "processing_successful": true
  }
}
```

### GraphGenerator
**Function Name**: `GraphGenerator`  
**Runtime**: Python 3.13  
**Purpose**: Creates structured graph from detected elements

#### Input
- Combined results from all previous processing steps
- Graph generation configuration

#### Output
```json
{
  "statusCode": 200,
  "s3_results": {
    "bucket": "my-output-bucket",
    "graph_data_s3_key": "exec-20250108-150426-abc123/graph/graph_data.json",
    "dexpi_s3_key": "exec-20250108-150426-abc123/graph/dexpi_output.xml"
  },
  "graph_summary": {
    "text_elements_count": 45,
    "symbols_count": 23,
    "lines_count": 156,
    "total_nodes": 224,
    "total_edges": 312,
    "text_associations": 67,
    "component_filtering": {
      "filter_enabled": true,
      "components_removed": 3,
      "nodes_removed": 89
    }
  }
}
```

### GraphVisualization
**Function Name**: `GraphVisualization`  
**Runtime**: Python 3.13 (Docker)  
**Purpose**: Creates visualization outputs

#### Input
- Graph data from GraphGenerator
- Visualization configuration

#### Output
```json
{
  "statusCode": 200,
  "visualizations_generated": {
    "physical_layout": "exec-20250108-150426-abc123/visualization/physical_layout.png",
    "graph_representation": "exec-20250108-150426-abc123/visualization/graph_representation.png"
  },
  "message": "Successfully generated 2 visualizations",
  "success": true
}
```

## S3 File Organization

The system uses a 3-bucket architecture for organized data separation:

### Bucket Structure Overview
- **Input Bucket**: `${stackName}-input-${account}-${region}` - Original P&ID uploads
- **Output Bucket**: `${stackName}-output-${account}-${region}` - All processing results and execution data  
- **Model Artifacts Bucket**: `${stackName}-artifacts-${account}-${region}` - SageMaker model files

### Execution-Based File Organization
All processing results are organized by execution ID directly in the output bucket:

```
s3://input-bucket/
└── diagrams/
    ├── pnid-001.png                          # Original uploaded diagrams
    ├── pnid-002.jpg
    └── pnid-003.pdf

s3://output-bucket/
└── exec-20250108-150426-abc123/              # Step Functions execution ID
    ├── config/
    │   └── processing_config.json            # Validated processing configuration
    ├── input/
    │   └── pnid-001.png                      # Copy of input file for reference  
    ├── notes-processing/
    │   ├── processed_image.png               # Image after notes/frame removal
    │   └── notes_metadata.json              # Notes processing metadata
    ├── text-detection/
    │   ├── text_detection_results.json      # Text elements with coordinates
    │   └── bda_output/                       # Bedrock Data Automation outputs
    │       └── [BDA generated files]
    ├── symbol-detection/
    │   └── detections.json                   # Symbol detection results
    ├── line-detection/
    │   ├── lines.json                        # Line segments and intersections
    │   └── debug/                            # Debug images (if enabled)
    │       ├── 00_original_with_boxes.jpg
    │       ├── 01_after_symbol_clearing.jpg
    │       ├── 02_after_text_clearing.jpg
    │       ├── 03_after_grayscale.png
    │       ├── 04_after_binary.png
    │       ├── 05_before_thinning.png
    │       ├── 06_after_thinning.png
    │       ├── 06a_raw_hough_lines.jpg
    │       ├── 06b_raw_hough_lines_binary.jpg
    │       ├── 06c_raw_hough_lines_indexed.jpg
    │       ├── 06d_raw_hough_lines.json
    │       ├── 07_after_extension.jpg
    │       ├── 08_after_merging.jpg
    │       ├── 09_after_filtering.jpg
    │       ├── 10_symbol_intersections.jpg
    │       └── 11_final_processed.jpg
    ├── graph/
    │   ├── graph_data.json                   # Final graph structure
    │   └── dexpi_output.xml                  # DEXPI format output
    ├── visualization/
    │   ├── physical_layout.png               # Physical layout visualization
    │   └── graph_representation.png         # Graph network visualization
    └── execution_metadata.json              # Execution metadata and paths

s3://model-artifacts-bucket/
└── model.tar.gz                              # SageMaker model artifacts
```

## Data Formats

### Text Detection Results
```json
{
  "text_elements": [
    {
      "text": "P-101",
      "bounding_box": {
        "x": 245.3, "y": 156.7,
        "width": 45.2, "height": 18.5
      }
    }
  ],
  "image_dimensions": {"width": 1800, "height": 1000},
  "bda_output_uri": "s3://bucket/bda-output/job-12345/",
  "coordinate_processing": {
    "coordinates_in_original_space": true,
    "manual_coordinates": null,
    "filtering_applied": false
  }
}
```

### Symbol Detection Results
```json
{
  "detections": [
    {
      "bbox": [245.1, 156.3, 289.7, 198.9],
      "class_id": "pump",
      "class_name": "centrifugal_pump",
      "score": 0.95,
      "nearest_classes": ["pump.png", "centrifugal_pump.png"]
    }
  ],
  "processing_metadata": {
    "confidence_threshold": 0.9,
    "nms_threshold": 0.4,
    "model_version": "v2.1"
  }
}
```

### Line Detection Results
```json
{
  "detected_lines": [
    {
      "startX": 0.245, "startY": 0.178,
      "endX": 0.456, "endY": 0.178
    }
  ],
  "symbol_intersections": [
    {
      "line_id": "line-45",
      "symbol_id": "symbol-12",
      "intersection_type": "endpoint",
      "confidence": 0.87
    }
  ],
  "processing_metadata": {
    "coordinate_transformation": {
      "applied": true,
      "validation": {
        "statistics": {"avg_deviation": 2.3}
      }
    }
  }
}
```

### Graph Data Structure
```json
{
  "symbols": [
    {
      "id": "1",
      "type": "pump",
      "class_name": "centrifugal_pump",
      "bbox": [245, 156, 290, 199],
      "connections": ["line-45", "line-67"],
      "text_associated": "P-101"
    }
  ],
  "lines": [
    {
      "id": "45",
      "points": [[245, 178], [456, 178]],
      "text_associated": "4\" PIPE",
      "connections": ["symbol-1", "junction-3"]
    }
  ],
  "junctions": [
    {
      "id": "3",
      "point": [456, 178],
      "junction_type": "t_junction",
      "connected_lines": ["45", "67", "89"],
      "confidence": 0.92
    }
  ],
  "connections": [
    {"from": "symbol-1", "to": "line-45"},
    {"from": "line-45", "to": "junction-3"}
  ],
  "text_elements": [
    {
      "id": "text-12",
      "text": "P-101",
      "association_type": "symbol",
      "associated_with": "symbol-1",
      "original_bbox": {"x": 245, "y": 140, "width": 30, "height": 12}
    }
  ],
  "graph_stats": {
    "num_nodes": 224,
    "num_edges": 312,
    "num_components": 1,
    "num_junctions": 23
  }
}
```

### DEXPI Output Format
The pipeline generates DEXPI-compliant XML output for integration with engineering software:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<PlantModel xmlns="http://www.dexpi.org/2017/dexpi">
  <PlantInformation>
    <Identification>pnid-001</Identification>
    <CreationDateTime>2025-01-08T15:04:26Z</CreationDateTime>
  </PlantInformation>
  <PlantStructure>
    <Equipment id="P-101" componentType="Pump">
      <Position x="245" y="156"/>
      <PipingConnections>
        <Connection id="conn-1" to="line-45"/>
      </PipingConnections>
    </Equipment>
    <PipingNetworkSegment id="line-45" 
                          startPosition="245,178" 
                          endPosition="456,178"/>
  </PlantStructure>
</PlantModel>
```

## Execution Path Management

### ExecutionPathManager
The system uses consistent execution-based paths for all file operations:

```python
from execution_paths import create_path_manager

# Create path manager
path_manager = create_path_manager(event, context, output_bucket)

# Generate consistent S3 keys
processed_image_key = path_manager.get_processed_image_s3_key()
# Returns: "exec-20250108-150426-abc123/notes-processing/processed_image.png"

text_results_key = path_manager.get_text_detection_results_s3_key()
# Returns: "exec-20250108-150426-abc123/text-detection/text_detection_results.json"

graph_data_key = path_manager.get_graph_data_s3_key()
# Returns: "exec-20250108-150426-abc123/graph/graph_data.json"
```

### Path Structure Methods
- `get_execution_prefix()` - Base execution directory
- `get_processed_image_s3_key()` - Processed image location
- `get_text_detection_results_s3_key()` - Text detection results
- `get_line_detection_results_s3_key()` - Line detection results
- `get_graph_data_s3_key()` - Graph data location
- `get_dexpi_s3_key()` - DEXPI output location
- `get_visualization_path()` - Visualization directory

## Error Responses

### Standard Error Format
All Lambda functions return consistent error responses:

```json
{
  "statusCode": 500,
  "success": false,
  "error": "Configuration validation failed: threshold must be integer",
  "source_bucket": "my-input-bucket",
  "source_key": "diagrams/pnid-001.png",
  "execution_id": "exec-20250108-150426-abc123",
  "timestamp": "2025-01-08T15:04:26.123Z"
}
```

### Common Error Types

#### Validation Errors (400)
- Invalid configuration parameters
- Missing required fields
- Invalid coordinate values

#### Processing Errors (500)
- Image processing failures
- Model inference errors
- S3 access issues

#### Timeout Errors (504)
- Long-running operations exceed timeout
- Bedrock Data Automation timeout
- SageMaker endpoint timeout

## Integration Examples

### Step Functions Integration
```json
{
  "Comment": "P&ID Processing Pipeline",
  "StartAt": "InputValidator",
  "States": {
    "InputValidator": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:region:account:function:InputValidator",
      "ResultPath": "$.validation_result",
      "Next": "NotesProcessor"
    },
    "NotesProcessor": {
      "Type": "Task", 
      "Resource": "arn:aws:lambda:region:account:function:NotesProcessor",
      "ResultPath": "$.notes_processing_results",
      "Next": "ParallelProcessing"
    }
  }
}
```

### Direct Lambda Invocation
```python
import boto3

lambda_client = boto3.client('lambda')

# Invoke InputValidator
response = lambda_client.invoke(
    FunctionName='InputValidator',
    Payload=json.dumps({
        "image_key": "diagrams/pnid-001.png",
        "input_bucket": "my-input-bucket",
        "processing_config": {}
    })
)

result = json.loads(response['Payload'].read())
```

### S3 Event Integration
```python
# Example S3 event trigger (if enabled)
{
  "Records": [
    {
      "eventVersion": "2.1",
      "eventSource": "aws:s3",
      "eventName": "ObjectCreated:Put",
      "s3": {
        "bucket": {"name": "my-input-bucket"},
        "object": {"key": "diagrams/pnid-001.png"}
      }
    }
  ]
}
```

For deployment and infrastructure details, see the main [README.md](../README.md).
For troubleshooting specific API issues, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
