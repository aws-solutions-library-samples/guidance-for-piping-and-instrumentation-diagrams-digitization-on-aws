# Configuration Guide

This document provides detailed information about configuring the P&ID Digitization Pipeline parameters.

## Configuration Overview

This document focuses on **Processing Configuration** - the algorithm parameters and thresholds used during P&ID processing.

For **Infrastructure Configuration** (`cdk/config.json`) setup including VPC, endpoints, and model deployment, see the [Basic Deployment](../README.md#basic-deployment) section in the main README.

The pipeline uses two configuration levels:
1. **Infrastructure Configuration** (`cdk/config.json`) - AWS resource deployment settings (see main README)
2. **Processing Configuration** - Algorithm parameters passed in execution input (covered in this guide)

## Processing Configuration

### Default Configuration Location
`cdk/lambda/input_validator/default_config.json` - Contains all default parameters

### Configuration Structure

#### Notes Processing
Controls diagram preprocessing and cleanup:

```json
{
  "notes_processing": {
    "manual_coordinates": {
      "x": 0,
      "y": 0,
      "width": -1,
      "height": -1
    },
    "remove_notes_section": true,
    "frame_config": {
      "remove_frame": true,
      "frame_detection_sensitivity": 0.7,
      "min_frame_thickness": 2,
      "max_frame_thickness": 20
    }
  }
}
```

**Parameters:**
- **`manual_coordinates`**: Manual crop region (width/height = -1 means no cropping)
- **`remove_notes_section`**: Automatically detect and remove notes sections
- **`frame_config.remove_frame`**: Automatically detect and remove diagram frames
- **`frame_detection_sensitivity`**: Frame detection sensitivity (0.0-1.0)
- **`min_frame_thickness`**: Minimum frame line thickness in pixels
- **`max_frame_thickness`**: Maximum frame line thickness in pixels

#### Line Detection
Controls line detection and post-processing:

```json
{
  "line_detection": {
    "max_line_gap": 100,
    "threshold": 3,
    "min_line_length": 8,
    "rho": 0.5,
    "theta_param": 180,
    "enable_thinning": true,
    "postprocess_params": {
      "merge_distance_threshold": 0.02,
      "angular_tolerance": 15.0,
      "min_line_length": 0.0001,
      "extension_padding": 0.01,
      "enable_symbol_intersection": true
    }
  }
}
```

**Core Parameters:**
- **`max_line_gap`**: Maximum gap between line segments that will be connected
- **`threshold`**: Minimum intersections in Hough space to detect a line
- **`min_line_length`**: Minimum line length in pixels
- **`rho`**: Distance resolution for Hough transform
- **`theta_param`**: Angle divisions for Hough transform
- **`enable_thinning`**: Apply morphological thinning to thick lines

**Post-Processing Parameters:**
- **`merge_distance_threshold`**: **CRITICAL** - Max distance for line merging (as fraction of image size)
- **`angular_tolerance`**: Max angle difference for line merging (degrees)
- **`extension_padding`**: Line endpoint extension for better merging
- **`enable_symbol_intersection`**: Enable symbol-aware line processing

#### Graph Generation
Controls graph structure creation:

```json
{
  "graph_generation": {
    "distance_threshold_symbols": 60,
    "distance_threshold_text": 30,
    "distance_threshold_lines": 20,
    "junction_detection_tolerance": 10.0,
    "component_filter": {
      "enabled": false,
      "min_component_size": 3,
      "max_symbol_density_for_removal": 0.1
    }
  }
}
```

**Distance Thresholds:**
- **`distance_threshold_symbols`**: Max distance for symbol-line connections
- **`distance_threshold_text`**: Max distance for text-line associations
- **`distance_threshold_lines`**: Max distance for line-line connections

**Junction Detection:**
- **`junction_detection_tolerance`**: Junction point detection tolerance
- **`t_junction_endpoint_threshold`**: T-junction endpoint detection threshold
- **`junction_clustering_radius`**: Radius for clustering nearby junctions

**Component Filtering:**
- **`enabled`**: Enable automatic removal of frame/notes components
- **`min_component_size`**: Minimum component size to keep
- **`max_symbol_density_for_removal`**: Max symbol density for component removal

## Parameter Tuning Guidelines

### Line Detection Tuning

#### For High-Quality Diagrams
```json
{
  "line_detection": {
    "threshold": 5,
    "max_line_gap": 80,
    "min_line_length": 15,
    "postprocess_params": {
      "merge_distance_threshold": 0.015,
      "angular_tolerance": 10.0
    }
  }
}
```

#### For Poor Quality/Hand-Drawn Diagrams
```json
{
  "line_detection": {
    "threshold": 2,
    "max_line_gap": 200,
    "min_line_length": 5,
    "postprocess_params": {
      "merge_distance_threshold": 0.035,
      "angular_tolerance": 20.0,
      "extension_padding": 0.02
    }
  }
}
```

#### To Prevent Parallel Line Merging
```json
{
  "line_detection": {
    "postprocess_params": {
      "merge_distance_threshold": 0.008,
      "angular_tolerance": 5.0,
      "extension_padding": 0.005
    }
  }
}
```

### Manual Coordinates

#### When to Use
- Complex layouts with unusual notes placement
- High-precision requirements for specific regions
- Quality control for critical diagrams
- Troubleshooting automatic detection issues

#### Format
```json
{
  "manual_coordinates": {
    "x": 150,      // Start 150px from left
    "y": 100,      // Start 100px from top  
    "width": 1200, // 1200px wide
    "height": 800  // 800px tall
  }
}
```

#### Behavior
- **Width/Height > 0**: Crops to specified region
- **Width/Height ≤ 0**: Passes image through unchanged
- **Invalid coordinates**: Returns error with validation message

### Component Filtering

#### Conservative (Keep More Components)
```json
{
  "component_filter": {
    "enabled": true,
    "min_component_size": 2,
    "max_symbol_density_for_removal": 0.05,
    "extreme_symbol_density_threshold": 0.02
  }
}
```

#### Aggressive (Remove More Components)
```json
{
  "component_filter": {
    "enabled": true,
    "min_component_size": 5,
    "max_symbol_density_for_removal": 0.15,
    "extreme_symbol_density_threshold": 0.08
  }
}
```

## Usage Examples

### Basic Processing
```json
{
  "image_key": "diagram.png",
  "input_bucket": "my-bucket"
}
```

### Custom Line Detection
```json
{
  "image_key": "complex-diagram.png",
  "input_bucket": "my-bucket",
  "processing_config": {
    "line_detection": {
      "threshold": 5,
      "merge_distance_threshold": 0.015
    }
  }
}
```

### Manual Coordinates with Custom Parameters
```json
{
  "image_key": "diagram-with-notes.png",
  "input_bucket": "my-bucket",
  "processing_config": {
    "notes_processing": {
      "manual_coordinates": {
        "x": 100,
        "y": 50,
        "width": 800,
        "height": 600
      }
    },
    "line_detection": {
      "threshold": 3,
      "max_line_gap": 120
    },
    "graph_generation": {
      "component_filter": {
        "enabled": false
      }
    }
  }
}
```

### Disable All Automatic Processing
```json
{
  "processing_config": {
    "notes_processing": {
      "remove_notes_section": false,
      "frame_config": {
        "remove_frame": false
      }
    },
    "graph_generation": {
      "component_filter": {
        "enabled": false
      }
    }
  }
}
```

## Validation Rules

The configuration system enforces these validation rules:

### Type Validation
- **Integers**: `threshold`, `max_line_gap`, `min_line_length`
- **Floats**: `rho`, `merge_distance_threshold`, `angular_tolerance`
- **Booleans**: `enable_thinning`, `remove_notes_section`
- **Objects**: `manual_coordinates`, `frame_config`

### Range Validation
- **`threshold`**: 1-20 (integer)
- **`max_line_gap`**: 1-1000 (integer)
- **`merge_distance_threshold`**: 0.001-0.1 (float)
- **`angular_tolerance`**: 1.0-45.0 (degrees)
- **`distance_threshold_symbols`**: 10-200 (pixels)

### Required Fields
- Manual coordinates must have `x`, `y`, `width`, `height` if specified
- Frame config must have boolean `remove_frame` if specified
- Component filter must have boolean `enabled` if specified

## Best Practices

### Configuration Management
1. **Start with defaults** and modify incrementally
2. **Test parameter changes** on sample images first
3. **Document custom configurations** for reproducibility
4. **Use version control** for configuration files

### Parameter Tuning Process
1. **Identify the issue** (missing lines, false positives, etc.)
2. **Choose relevant parameters** based on the issue type
3. **Make small adjustments** (10-20% changes)
4. **Test thoroughly** with multiple images
5. **Document the changes** and reasoning

### Performance Optimization
- **Higher thresholds** = faster processing, fewer detections
- **Lower merge tolerances** = more precise but slower processing
- **Disabled features** = faster processing but less functionality
- **Manual coordinates** = faster processing on smaller regions

## Troubleshooting Configuration Issues

### Validation Errors
```
Error: Configuration validation failed for line_detection.threshold: 
Value 0 is below minimum allowed value of 1
```
**Solution**: Check parameter types and ranges in validation rules

### Parameter Not Taking Effect
1. Verify parameter is in correct configuration section
2. Check for typos in parameter names
3. Ensure configuration is passed in execution input
4. Check Lambda logs for configuration loading messages

### Performance Issues
1. Reduce image resolution before processing
2. Use manual coordinates for smaller processing regions
3. Increase thresholds to reduce detection sensitivity
4. Disable expensive features like component filtering

For more troubleshooting guidance, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
