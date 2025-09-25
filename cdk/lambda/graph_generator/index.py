import json
import logging
import os
import traceback
from typing import Dict, Any, List, Tuple

import boto3

from config_helper import get_lambda_config, read_s3_json, store_results_in_s3
from dexpi_converter import convert_to_dexpi
from document_processor import DocumentProcessor
from execution_paths import create_path_manager

logger = logging.getLogger()
log_level = os.environ.get('LOG_LEVEL', 'INFO')
logger.setLevel(getattr(logging, log_level.upper()))

s3 = boto3.client("s3")

# Get OUTPUT_BUCKET from environment variable
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET")


def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Graph generator Lambda function.

    Combines results from Bedrock Data Automation text detection, SageMaker symbol detection, and line detection
    to create a comprehensive P&ID graph representation and visualization.
    """

    try:
        logger.info(f"Graph generator Lambda invoked with event: {json.dumps(event)}")

        # Extract parameters from event
        image_key = event.get("image_key")
        output_format = event.get("output_format", "dexpi")
        
        # Create execution path manager for consistent file organization
        path_manager = create_path_manager(event, context, OUTPUT_BUCKET)

        # Get processing configuration from S3
        try:
            config = get_lambda_config(event, 'graph_generation')
        except Exception as e:
            logger.error(f"Failed to read config from S3: {str(e)}")
            raise ValueError(f"Could not read configuration: {str(e)}")

        # Read text detection results from S3
        s3_refs = event.get("s3_refs", {})
        text_detection_results_key = s3_refs.get("text_detection_results_key")
        symbol_results_key = s3_refs.get("symbol_results_key")
        line_results_key = s3_refs.get("line_results_key")

        if not text_detection_results_key:
            raise ValueError("Missing required S3 reference: text_detection_results_key")

        # Read data from S3
        try:
            text_detection_results = read_s3_json(OUTPUT_BUCKET, text_detection_results_key)
            logger.info(f"Loaded text detection results from s3://{OUTPUT_BUCKET}/{text_detection_results_key}")
        except Exception as e:
            logger.error(f"Failed to read text detection results from S3: {str(e)}")
            raise ValueError(f"Could not read text detection results: {str(e)}")

        # Read symbol detection results from S3 (if available)
        symbol_detection_results = {}
        if symbol_results_key:
            try:
                symbol_detection_results = read_s3_json(OUTPUT_BUCKET, symbol_results_key)
                logger.info(f"Loaded symbol results from s3://{OUTPUT_BUCKET}/{symbol_results_key}")
            except Exception as e:
                logger.warning(f"Failed to read symbol results from S3: {str(e)}")

        # Handle line detection results (already in S3-based format)
        line_detection_results = event.get("line_detection_results", {})

        # Debug logging
        logger.info(f"Text detection results type: {type(text_detection_results)}")
        logger.info(
            f"Text detection results keys: {list(text_detection_results.keys()) if isinstance(text_detection_results, dict) else 'Not a dict'}"
        )
        logger.info(len(symbol_detection_results))

        # Use OUTPUT_BUCKET from environment variable
        if not OUTPUT_BUCKET:
            raise ValueError("OUTPUT_BUCKET environment variable not set")

        if not all([OUTPUT_BUCKET, image_key]):
            raise ValueError(
                "Missing required parameters: OUTPUT_BUCKET, image_key"
            )

        logger.info(
            f"Generating graph for image: {image_key} with output format: {output_format}"
        )

        # Process text detection results to get text elements and image dimensions
        text_elements, text_detection_image_dimensions, original_text_elements = (
            process_text_detection_results(text_detection_results)
        )

        # Use original image dimensions if available (since line detection transforms to original space)
        # Otherwise use processed dimensions, then fall back to text detection dimensions
        processed_image_dimensions = event.get("processed_image_dimensions")
        original_image_dimensions = event.get("original_image_dimensions")

        if original_image_dimensions:
            image_dimensions = original_image_dimensions
            logger.info(f"Using original image dimensions: {image_dimensions}")
            logger.info(f"Processed image dimensions: {processed_image_dimensions}")
        elif processed_image_dimensions:
            image_dimensions = processed_image_dimensions
            logger.info(f"Using processed image dimensions (fallback): {image_dimensions}")
        else:
            image_dimensions = text_detection_image_dimensions
            logger.info(f"Using text detection image dimensions (final fallback): {image_dimensions}")

        # Process symbols and lines using the correct reference dimensions
        symbols = process_symbol_detection_results(
            symbol_detection_results, image_dimensions
        )
        lines = process_line_detection_results(line_detection_results, image_dimensions)

        logger.info(
            f"Processed: {len(text_elements)} text elements, {len(symbols)} symbols, {len(lines)} lines"
        )

        # Use validated configuration from input validator
        logger.info(f"Using configuration: {json.dumps(config, indent=2)}")

        # Transform config format to match DocumentProcessor expectations
        transformed_config = transform_config_for_document_processor(config)

        # Use the improved DocumentProcessor
        processor = DocumentProcessor(transformed_config)
        graph_data = processor.process_document(
            image_key, symbols, lines, text_elements, original_text_elements
        )

        # Generate DEXPI output
        dexpi_xml = convert_to_dexpi(graph_data, image_key, image_dimensions)

        # Save results to output bucket using execution-based paths
        output_keys = save_graph_to_s3(path_manager, graph_data, dexpi_xml)

        # Count text associations
        text_associations = sum(
            1 for line in graph_data.get("lines", []) if line.get("text_associated")
        )

        # Get component filtering info from graph data
        component_filtering = graph_data.get("component_filtering", {})

        # Return minimal response with S3 references
        return {
            "statusCode": 200,
            "s3_results": {
                "bucket": path_manager.output_bucket,
                "graph_data_s3_key": output_keys["graph_data_s3_key"],
                "dexpi_s3_key": output_keys["dexpi_s3_key"]
            },
            "graph_summary": {
                "text_elements_count": len(text_elements),
                "symbols_count": len(symbols),
                "lines_count": len(lines),
                "total_nodes": graph_data.get("graph_stats", {}).get("num_nodes", 0),
                "total_edges": graph_data.get("graph_stats", {}).get("num_edges", 0),
                "text_associations": text_associations,
                "component_filtering": component_filtering,
            },
            "processing_complete": True,
        }

    except Exception as e:
        logger.error(f"Error in graph generator: {str(e)}")
        logger.error(traceback.format_exc())

        return {"statusCode": 500, "error": str(e), "processing_complete": False}


def process_text_detection_results(
    text_detection_results: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, int], List[Dict[str, Any]]]:
    """
    Process text detection results to extract text elements and image dimensions.
    Returns both processed text elements (for graph processing) and original text elements (for final output).
    """
    text_elements = []
    original_text_elements = []
    image_dimensions = {"width": 0, "height": 0}

    if not text_detection_results:
        logger.warning("No text detection results provided")
        return text_elements, image_dimensions, original_text_elements

    # Extract image dimensions from text detection results
    if "image_dimensions" in text_detection_results:
        image_dimensions = text_detection_results["image_dimensions"]
        logger.info(f"Found image dimensions: {image_dimensions}")

    # Extract text elements from text detection results
    if "text_elements" in text_detection_results:
        for idx, element in enumerate(text_detection_results["text_elements"]):
            bbox = element.get("bounding_box", {})
            if bbox and "text" in element:
                # Create processed text element for graph processing (x1, y1, x2, y2 format)
                text_element = {
                    "id": f"text-{idx}",
                    "text": element["text"],
                    "bbox": [
                        bbox.get("x", 0),
                        bbox.get("y", 0),
                        bbox.get("x", 0) + bbox.get("width", 0),
                        bbox.get("y", 0) + bbox.get("height", 0),
                    ],
                    "confidence": element.get("confidence", 0.0),
                }
                text_elements.append(text_element)

                # Create original text element for final output (x, y, width, height format)
                original_text_element = {
                    "id": f"text-{idx}",
                    "text": element["text"],
                    "original_bbox": {
                        "x": bbox.get("x", 0),
                        "y": bbox.get("y", 0),
                        "width": bbox.get("width", 0),
                        "height": bbox.get("height", 0),
                    },
                    "normalized_bbox": {
                        "x": bbox.get("x", 0),
                        "y": bbox.get("y", 0),
                        "width": bbox.get("width", 0),
                        "height": bbox.get("height", 0),
                    },
                    "confidence": element.get("confidence", 0.0),
                }
                original_text_elements.append(original_text_element)

    logger.info(f"Extracted {len(text_elements)} text elements from text detection results")
    return text_elements, image_dimensions, original_text_elements


def process_symbol_detection_results(
    symbol_results: Dict[str, Any], image_dimensions: Dict[str, int]
) -> List[Dict[str, Any]]:
    """
    Process symbol detection results and convert to our format.
    Handles both direct results and S3-stored results.
    """
    symbols = []

    if not symbol_results:
        logger.warning("No symbol detection results provided")
        return symbols

    logger.info(f"Symbol detection results type: {type(symbol_results)}")
    logger.info(
        f"Symbol detection results keys: {list(symbol_results.keys()) if isinstance(symbol_results, dict) else 'Not a dict'}"
    )

    # Handle S3-stored results
    if symbol_results.get("stored_in_s3"):
        s3_key = symbol_results.get("detections_s3_key")
        if s3_key:
            logger.info(f"Loading symbol detection results from S3: {s3_key}")
            try:
                # Use output bucket for all processing data
                if not OUTPUT_BUCKET:
                    logger.error("OUTPUT_BUCKET environment variable not set")
                    return symbols

                response = s3.get_object(Bucket=OUTPUT_BUCKET, Key=s3_key)
                stored_results = json.loads(response["Body"].read().decode("utf-8"))
                detections = stored_results.get("detections", [])
                logger.info(f"Loaded {len(detections)} detections from S3")
            except Exception as e:
                logger.error(
                    f"Failed to load symbol detection results from S3: {str(e)}"
                )
                return symbols
        else:
            logger.error("No S3 key provided for stored detections")
            return symbols
    else:
        # Handle direct results
        if "body" in symbol_results and "detections" in symbol_results["body"]:
            detections = symbol_results["body"]["detections"]
        elif "detections" in symbol_results:
            detections = symbol_results["detections"]
        else:
            logger.warning("No detections found in symbol results")
            return symbols

    # Process each detection
    for idx, detection in enumerate(detections):
        bbox = detection.get("bbox")
        if bbox:
            # Get class name from nearest_classes (first one)
            symbol_type = "unknown"
            if "nearest_classes" in detection and detection["nearest_classes"]:
                symbol_type = detection["nearest_classes"][0].replace(".png", "")

            processed_symbol = {
                "id": str(idx),
                "type": str(detection.get("class_id", "unknown")),
                "class_name": detection.get("class_name", "unknown"),
                "bbox": bbox,
                "score": detection.get("score", 0.9),
            }
            symbols.append(processed_symbol)
    return symbols


def process_line_detection_results(
    line_results: Dict[str, Any], image_dimensions: Dict[str, int]
) -> List[Dict[str, Any]]:
    """
    Process line detection results and convert to our format.
    Uses S3-based data passing to handle large line datasets.
    """
    lines = []

    if not line_results:
        logger.error("No line detection results provided")
        return lines

    logger.debug(f"Line results: {line_results}")

    # Expect S3-based format only
    if not ('Payload' in line_results and 's3_results' in line_results['Payload']):
        logger.error("Expected S3-based line detection results but found different format")
        return lines
    
    s3_results = line_results['Payload']['s3_results']
    lines_s3_key = s3_results.get("lines_s3_key")
    bucket = s3_results.get("bucket")

    if not lines_s3_key or not bucket:
        logger.error(
            "Missing required S3 keys (lines_s3_key or bucket) in line detection results"
        )
        return lines

    logger.info(f"Reading line detection results from S3: s3://{bucket}/{lines_s3_key}")

    try:
        # Fetch detected lines from S3
        response = s3.get_object(Bucket=bucket, Key=lines_s3_key)
        lines_data = json.loads(response["Body"].read().decode("utf-8"))
        detected_lines = lines_data.get("detected_lines", [])
        logger.info(f"Successfully loaded {len(detected_lines)} lines from S3")
    except Exception as e:
        logger.error(f"Failed to load line detection results from S3: {str(e)}")
        return lines

    # Process each line
    width = image_dimensions.get("width", 1280)
    height = image_dimensions.get("height", 1280)

    for idx, line in enumerate(detected_lines):
        # Convert normalized coordinates to pixel coordinates
        # Lines are in format: startX, startY, endX, endY (normalized 0-1)
        if all(k in line for k in ["startX", "startY", "endX", "endY"]):
            processed_line = {
                "id": str(idx),
                "points": [
                    [line["startX"] * width, line["startY"] * height],
                    [line["endX"] * width, line["endY"] * height],
                ],
            }
            lines.append(processed_line)

    logger.info(f"Processed {len(lines)} lines")
    return lines


def transform_config_for_document_processor(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform configuration from new format to DocumentProcessor expected format.

    Args:
        config: Configuration in new standardized format

    Returns:
        Configuration in DocumentProcessor expected format
    """
    # Map new config format to DocumentProcessor expected format
    transformed = {
        # Graph processing parameters
        "graph_distance_threshold_for_symbols": config.get(
            "distance_threshold_symbols", 60
        ),
        "graph_distance_threshold_for_text": config.get("distance_threshold_text", 30),
        "graph_distance_threshold_for_lines": config.get(
            "distance_threshold_lines", 20
        ),
        "graph_line_buffer": config.get("line_buffer", 5),
        "graph_symbol_to_symbol_distance_threshold": config.get(
            "symbol_distance_threshold", 100
        ),
        "graph_symbol_to_symbol_overlap_region_threshold": config.get(
            "symbol_overlap_threshold", 0.3
        ),
        "graph_symbol_text_association_threshold": config.get(
            "symbol_text_association_threshold", 80
        ),
        "graph_symbol_text_fallback_threshold": config.get(
            "symbol_text_fallback_threshold", 120
        ),
        # Junction detection parameters
        "junction_detection_tolerance": config.get(
            "junction_detection_tolerance", 10.0
        ),
        "t_junction_endpoint_threshold": config.get(
            "t_junction_endpoint_threshold", 15.0
        ),
        "junction_clustering_radius": config.get("junction_clustering_radius", 20.0),
        "junction_angle_tolerance": config.get("junction_angle_tolerance", 15.0),
        "minimum_line_length": config.get("minimum_line_length", 5.0),
        "intersection_snap_distance": config.get("intersection_snap_distance", 5.0),
        # Line processing parameters
        "line_aberration_tolerance": config.get("line_aberration_tolerance", 5.0),
        "junction_proximity_threshold": config.get(
            "junction_proximity_threshold", 10.0
        ),
        "max_merge_iterations": config.get("max_merge_iterations", 5),
        "geometric_continuation_tolerance": config.get(
            "geometric_continuation_tolerance", 20.0
        ),
    }

    # Component filtering parameters (nested in new format)
    component_filter = config.get("component_filter", {})
    transformed.update(
        {
            "component_filter_enabled": component_filter.get("enabled", True),
            "min_component_size": component_filter.get("min_component_size", 3),
            "max_line_density": component_filter.get("max_line_density", 0.9),
            "min_symbol_density": component_filter.get("min_symbol_density", 0.1),
            "max_notes_component_size": component_filter.get(
                "max_notes_component_size", 15
            ),
            "frame_aspect_ratio_threshold": component_filter.get(
                "frame_aspect_ratio_threshold", 0.1
            ),
            "max_symbol_density_for_removal": component_filter.get(
                "max_symbol_density_for_removal", 0.1
            ),
            "extreme_symbol_density_threshold": component_filter.get(
                "extreme_symbol_density_threshold", 0.05
            ),
        }
    )

    return transformed


def save_graph_to_s3(
    path_manager, graph_data: Dict[str, Any], dexpi_xml: str
) -> Dict[str, str]:
    """
    Save graph results to S3 using execution-based paths.
    """
    output_keys = {}

    # Use ExecutionPathManager for consistent S3 keys
    graph_key = path_manager.get_graph_data_s3_key()
    dexpi_key = path_manager.get_dexpi_s3_key()

    # Save graph JSON for visualization lambda
    s3.put_object(
        Bucket=path_manager.output_bucket,
        Key=graph_key,
        Body=json.dumps(graph_data, indent=2),
        ContentType="application/json",
    )
    output_keys["graph_data_s3_key"] = graph_key  # For visualization lambda
    logger.info(f"Saved graph data to s3://{path_manager.output_bucket}/{graph_key}")

    # Save DEXPI XML
    s3.put_object(
        Bucket=path_manager.output_bucket,
        Key=dexpi_key,
        Body=dexpi_xml,
        ContentType="application/xml",
    )
    output_keys["dexpi_s3_key"] = dexpi_key
    logger.info(f"Saved DEXPI output to s3://{path_manager.output_bucket}/{dexpi_key}")

    return output_keys
