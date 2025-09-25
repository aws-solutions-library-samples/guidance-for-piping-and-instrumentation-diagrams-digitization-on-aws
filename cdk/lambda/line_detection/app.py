import json
import os
import re
import traceback
from typing import Dict, Any, List
import logging

import boto3
import numpy as np

from line_detection import (
    BoundingBox,
    LineSegment,
    preprocess_image,
    detect_line_segments,
    clear_bounding_boxes,
    to_grayscale,
    to_binary,
    apply_thinning,
)
from line_postprocessing import LinePostProcessor
from symbol_aware_line_detection import SymbolAwareLinePostProcessor
from coordinate_transform import (
    transform_coordinates_to_original,
    transform_coordinates_to_processed,
    get_transformation_metadata_from_notes_processor,
    validate_transformation_result
)
from execution_paths import create_path_manager
from image_processing import (
    download_image_from_s3,
    convert_bounding_boxes,
    convert_bda_text_elements,
)
from debug_images import (
    save_debug_image,
    save_preprocessed_image,
    save_raw_hough_lines_image,
    save_before_thinning_image,
    save_raw_hough_lines_binary_image,
    save_raw_hough_lines_json,
    save_raw_hough_lines_indexed_image,
    save_original_with_bounding_boxes,
    save_after_symbol_clearing,
    save_after_text_clearing,
    save_after_grayscale,
    save_after_binary,
    save_lines_after_extension,
    save_lines_after_merging,
    save_lines_after_filtering,
    save_symbol_intersections,
)
from s3_operations import save_results_to_s3

# Set up logging
logger = logging.getLogger()
log_level = os.environ.get('LOG_LEVEL', 'INFO')
logger.setLevel(getattr(logging, log_level.upper()))

# Initialize AWS clients
s3_client = boto3.client("s3")

# Get environment variables
OUTPUT_BUCKET = os.environ.get('OUTPUT_BUCKET')


def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Line detection Lambda handler.

    Processes P&ID images to detect line segments using the existing line detection algorithm.
    Removes symbols and text based on bounding boxes from previous pipeline steps.
    """

    try:
        logger.info(f"Line detection Lambda invoked with event: {json.dumps(event)}")

        # Extract parameters from event
        bucket = OUTPUT_BUCKET
        image_key = event.get("image_key") or event.get("key")

        # Initialize default values
        symbol_bounding_boxes = []
        text_bounding_boxes = []
        
        # Load bounding boxes from different event formats
        symbol_bounding_boxes, text_bounding_boxes = load_bounding_boxes_from_event(event, bucket)

        # Load configuration from S3 using config_helper
        config_s3_key = event.get("config_s3_key")
        
        if not config_s3_key:
            raise ValueError("Missing required parameter: config_s3_key")
            
        # Load full config from S3
        from config_helper import get_config_from_s3
        full_config = get_config_from_s3(bucket, config_s3_key)
        line_config = full_config.get("line_detection", {})

        logger.info(f"Using line detection configuration: {json.dumps(line_config, indent=2)}")

        # Extract configuration parameters
        config_params = extract_configuration_parameters(line_config)

        if not bucket or not image_key:
            raise ValueError("Missing required parameters: bucket and image_key")

        # Create execution path manager for consistent file organization
        path_manager = create_path_manager(event, context, bucket)

        # Process text bounding boxes format
        text_bounding_boxes = process_text_bounding_boxes(text_bounding_boxes, bucket)

        logger.info(f"Processing image: s3://{bucket}/{image_key}")
        logger.info(f"Symbol boxes: {len(symbol_bounding_boxes)}")
        logger.info(f"Text boxes: {len(text_bounding_boxes)}")

        # Transform input bounding boxes from original space to processed space for proper clearing
        symbol_bounding_boxes, text_bounding_boxes = transform_input_bounding_boxes(
            event, symbol_bounding_boxes, text_bounding_boxes
        )

        # Download image from S3
        image = download_image_from_s3(bucket, image_key)
        image_height, image_width = image.shape[:2]

        print(f"Image dimensions: {image_width}x{image_height}")

        # Convert bounding boxes to BoundingBox objects
        symbol_boxes = convert_bounding_boxes(symbol_bounding_boxes, image_width, image_height)
        text_boxes = convert_bda_text_elements(text_bounding_boxes, image_width, image_height)

        print(f"Converted {len(symbol_boxes)} symbol boxes and {len(text_boxes)} text boxes")

        # Perform step-by-step preprocessing with debug images
        processed_image = perform_preprocessing_pipeline(
            path_manager, image_key, image, symbol_boxes, text_boxes, config_params
        )

        # Detect line segments with debug callbacks
        line_segments = perform_line_detection(
            path_manager, processed_image, image, image_width, image_height, config_params
        )

        # Apply post-processing
        processed_line_segments, intersection_metadata = perform_line_postprocessing(
            path_manager, image, line_segments, symbol_boxes, config_params
        )

        # Convert LineSegment objects to JSON
        lines_json = convert_line_segments_to_json(processed_line_segments)

        # Transform line coordinates to original image space if available
        lines_json, processing_metadata = transform_line_coordinates_to_original(
            event, lines_json, symbol_boxes, text_boxes, intersection_metadata, image_width, image_height
        )

        # Save final debug image
        save_debug_image(path_manager, image, processed_line_segments, symbol_boxes, text_boxes)

        # Save large datasets to S3
        s3_results = save_results_to_s3(
            path_manager=path_manager,
            detected_lines=lines_json,
            symbol_intersections=intersection_metadata,
            processing_metadata=processing_metadata,
        )

        # Return minimal response with S3 references
        return {
            "statusCode": 200,
            "line_count": len(lines_json),
            "intersection_count": len(intersection_metadata),
            "s3_results": s3_results,
            "summary": {
                "image_dimensions": [image_width, image_height],
                "processing_successful": True,
            },
        }

    except Exception as e:
        print(f"Error in line detection: {str(e)}")
        traceback.print_exc()

        # Return minimal error response
        error_msg = str(e)[:500]  # Truncate very long error messages

        return {
            "statusCode": 500,
            "error": error_msg,
            "line_count": 0,
            "intersection_count": 0,
            "s3_results": {
                "error": f"Processing failed: {error_msg}",
                "bucket": bucket if "bucket" in locals() else "unknown",
                "timestamp": "error",
            },
            "summary": {"image_dimensions": [0, 0], "processing_successful": False},
        }


def load_bounding_boxes_from_event(event: Dict[str, Any], bucket: str) -> tuple:
    """Load bounding boxes from different event formats."""
    
    symbol_bounding_boxes = []
    text_bounding_boxes = []
    
    # Handle different event formats (priority order)
    # 1. New s3_refs format (current)
    if "s3_refs" in event:
        logger.info("Using s3_refs format for loading OCR and Symbol Detection results")
        s3_refs = event["s3_refs"]
        
        # Load text detection results
        text_detection_s3_key = s3_refs.get("text_detection_results_key")
        if text_detection_s3_key:
            logger.info(f"Loading text detection results from S3: {text_detection_s3_key}")
            try:
                response = s3_client.get_object(Bucket=bucket, Key=text_detection_s3_key)
                text_detection_data = json.loads(response["Body"].read().decode("utf-8"))
                text_bounding_boxes = text_detection_data.get("text_elements", [])
                logger.info(f"Loaded {len(text_bounding_boxes)} text elements from S3")
            except Exception as e:
                logger.error(f"Failed to load text detection results from S3: {str(e)}")
                text_bounding_boxes = []
        
        # Load Symbol Detection results
        symbol_s3_key = s3_refs.get("symbol_results_key")
        if symbol_s3_key:
            logger.info(f"Loading symbol detection results from S3: {symbol_s3_key}")
            try:
                response = s3_client.get_object(Bucket=bucket, Key=symbol_s3_key)
                symbol_data = json.loads(response["Body"].read().decode("utf-8"))
                symbol_bounding_boxes = symbol_data.get("detections", [])
                logger.info(f"Loaded {len(symbol_bounding_boxes)} detections from S3")
            except Exception as e:
                logger.error(f"Failed to load symbol results from S3: {str(e)}")
                symbol_bounding_boxes = []
    
    # 2. Parallel results format (previous)
    elif "parallel_results" in event:
        logger.info("Using parallel_results format for loading OCR and Symbol Detection results")
        parallel_results = event.get("parallel_results", [])
        
        if len(parallel_results) >= 2:
            # Extract text detection results from parallel_results[0]
            text_detection_result = parallel_results[0]
            if "s3_results" in text_detection_result:
                text_detection_s3_key = text_detection_result["s3_results"].get("text_detection_results_key")
                if text_detection_s3_key:
                    logger.info(f"Loading text detection results from S3: {text_detection_s3_key}")
                    try:
                        response = s3_client.get_object(Bucket=bucket, Key=text_detection_s3_key)
                        text_detection_data = json.loads(response["Body"].read().decode("utf-8"))
                        text_bounding_boxes = text_detection_data.get("text_elements", [])
                        logger.info(f"Loaded {len(text_bounding_boxes)} text elements from S3")
                    except Exception as e:
                        logger.error(f"Failed to load text detection results from S3: {str(e)}")
                        text_bounding_boxes = []
            
            # Extract Symbol Detection results from parallel_results[1] 
            symbol_result = parallel_results[1]
            if "s3_results" in symbol_result:
                symbol_s3_key = symbol_result["s3_results"].get("detections_key")
                if symbol_s3_key:
                    logger.info(f"Loading symbol detection results from S3: {symbol_s3_key}")
                    try:
                        response = s3_client.get_object(Bucket=bucket, Key=symbol_s3_key)
                        symbol_data = json.loads(response["Body"].read().decode("utf-8"))
                        symbol_bounding_boxes = symbol_data.get("detections", [])
                        logger.info(f"Loaded {len(symbol_bounding_boxes)} detections from S3")
                    except Exception as e:
                        logger.error(f"Failed to load symbol results from S3: {str(e)}")
                        symbol_bounding_boxes = []
    
    # 3. Legacy direct format (oldest, backward compatibility)
    else:
        logger.info("No s3_refs or parallel_results found, checking for legacy format...")
        
        # Legacy symbol detection results
        symbol_detection_results = event.get("symbol_detection_results", {})
        if symbol_detection_results.get("stored_in_s3"):
            s3_key = symbol_detection_results.get("detections_s3_key")
            if s3_key:
                logger.info(f"Loading symbol detection results from S3 (legacy): {s3_key}")
                response = s3_client.get_object(Bucket=bucket, Key=s3_key)
                stored_results = json.loads(response["Body"].read().decode("utf-8"))
                symbol_bounding_boxes = stored_results.get("detections", [])
        else:
            symbol_bounding_boxes = symbol_detection_results.get("detections", [])
        
        # Legacy text results
        text_bounding_boxes = event.get("text_bounding_boxes", [])
    
    return symbol_bounding_boxes, text_bounding_boxes


def extract_configuration_parameters(line_config: Dict[str, Any]) -> Dict[str, Any]:
    """Extract line detection parameters from validated config."""
    
    # Extract line detection parameters from validated config
    max_line_gap = line_config.get("max_line_gap", 120)
    threshold = line_config.get("threshold", 100)
    min_line_length = line_config.get("min_line_length", 30)
    rho = line_config.get("rho", 1.0)
    theta_param = line_config.get("theta_param", 180)
    enable_thinning = line_config.get("enable_thinning", True)

    # Extract post-processing parameters from validated config
    postprocess_params = line_config.get("postprocess_params", {})
    merge_distance_threshold = postprocess_params.get("merge_distance_threshold", 0.05)
    angular_tolerance = postprocess_params.get("angular_tolerance", 15.0)
    min_processed_line_length = postprocess_params.get("min_line_length", 20.0)
    extension_padding = postprocess_params.get("extension_padding", 0.02)
    enable_symbol_intersection = postprocess_params.get("enable_symbol_intersection", True)
    
    return {
        "max_line_gap": max_line_gap,
        "threshold": threshold,
        "min_line_length": min_line_length,
        "rho": rho,
        "theta_param": theta_param,
        "enable_thinning": enable_thinning,
        "merge_distance_threshold": merge_distance_threshold,
        "angular_tolerance": angular_tolerance,
        "min_processed_line_length": min_processed_line_length,
        "extension_padding": extension_padding,
        "enable_symbol_intersection": enable_symbol_intersection,
    }


def process_text_bounding_boxes(text_bounding_boxes: List, bucket: str) -> List:
    """Process text bounding boxes to handle different formats."""
    
    # Check if text_bounding_boxes is the full OCR result object
    if isinstance(text_bounding_boxes, dict):
        logger.debug(f"text_bounding_boxes is a dict with keys: {list(text_bounding_boxes.keys())}")

        # Check if this is the full OCR Lambda response with text_elements
        if "text_elements" in text_bounding_boxes:
            logger.info(f"Found text_elements in OCR results")
            text_bounding_boxes = text_bounding_boxes.get("text_elements", [])
        elif "bda_output_uri" in text_bounding_boxes:
            # Legacy format: OCR returns BDA output URI
            text_bounding_boxes = process_bda_output_uri(text_bounding_boxes, bucket)
        else:
            logger.warning(f"Unknown text_bounding_boxes format. Keys: {list(text_bounding_boxes.keys())}")
            text_bounding_boxes = []
    
    return text_bounding_boxes


def process_bda_output_uri(text_bounding_boxes: Dict, bucket: str) -> List:
    """Process BDA output URI to extract text elements."""
    
    try:
        # Parse S3 URI: s3://bucket/key/prefix/
        s3_uri = text_bounding_boxes["bda_output_uri"]
        match = re.match(r"s3://([^/]+)/(.+)", s3_uri)
        if match:
            bda_bucket = match.group(1)
            bda_prefix = match.group(2)

            # List objects in the BDA output directory
            logger.info(f"Fetching BDA results from {s3_uri}")
            objects = s3_client.list_objects_v2(Bucket=bda_bucket, Prefix=bda_prefix)

            # Find the JSON output file
            json_file = None
            for obj in objects.get("Contents", []):
                if obj["Key"].endswith(".json"):
                    json_file = obj["Key"]
                    break

            if json_file:
                logger.info(f"Found BDA JSON file: {json_file}")
                response = s3_client.get_object(Bucket=bda_bucket, Key=json_file)
                bda_results = json.loads(response["Body"].read().decode("utf-8"))

                # Extract text elements from BDA results
                extracted_text_boxes = []
                if "image" in bda_results and "text_words" in bda_results["image"]:
                    for word in bda_results["image"]["text_words"]:
                        if "locations" in word and word["locations"]:
                            location = word["locations"][0]
                            if "bounding_box" in location:
                                extracted_text_boxes.append({
                                    "text": word.get("text", ""),
                                    "locations": [location],
                                })
                return extracted_text_boxes
            else:
                logger.warning(f"No JSON file found in BDA output directory")
                return []
        else:
            logger.error(f"Invalid S3 URI format: {s3_uri}")
            return []
    except Exception as e:
        logger.error(f"Error fetching BDA results from S3: {str(e)}")
        return []


def transform_input_bounding_boxes(event: Dict, symbol_bounding_boxes: List, text_bounding_boxes: List) -> tuple:
    """Transform input bounding boxes from original space to processed space for proper clearing."""
    
    notes_processing_results = event.get('notes_processing_results')
    if notes_processing_results and (symbol_bounding_boxes or text_bounding_boxes):
        try:
            logger.info("Transforming input bounding boxes from original to processed space for clearing")
            
            # Extract transformation metadata from notes processor results
            transformation_metadata = get_transformation_metadata_from_notes_processor(notes_processing_results)
            
            # Transform symbol bounding boxes to processed space
            if symbol_bounding_boxes:
                logger.info(f"Transforming {len(symbol_bounding_boxes)} symbol boxes to processed space")
                processed_symbol_boxes = transform_coordinates_to_processed(
                    coordinates=symbol_bounding_boxes,
                    transformation_metadata=transformation_metadata,
                    coordinate_type="bounding_box"
                )
                symbol_bounding_boxes = processed_symbol_boxes
                logger.info(f"Symbol box transformation completed")

            # Transform text bounding boxes to processed space
            if text_bounding_boxes:
                logger.info(f"Transforming {len(text_bounding_boxes)} text boxes to processed space")
                processed_text_boxes = transform_coordinates_to_processed(
                    coordinates=text_bounding_boxes,
                    transformation_metadata=transformation_metadata,
                    coordinate_type="bounding_box"
                )
                text_bounding_boxes = processed_text_boxes
                logger.info(f"Text box transformation completed")
            
            logger.info("Input bounding box transformation to processed space completed successfully")
            
        except Exception as e:
            logger.warning(f"Input bounding box transformation failed, using original coordinates: {str(e)}")
    else:
        logger.debug("No notes processing results available or no bounding boxes to transform")
    
    return symbol_bounding_boxes, text_bounding_boxes


def perform_preprocessing_pipeline(path_manager, image_key: str, image: np.ndarray, 
                                 symbol_boxes: List[BoundingBox], text_boxes: List[BoundingBox], 
                                 config_params: Dict[str, Any]) -> np.ndarray:
    """Perform step-by-step preprocessing with debug images."""
    
    # Step 1: Save original image with bounding boxes
    save_original_with_bounding_boxes(path_manager, image_key, image, symbol_boxes, text_boxes)

    # Step 2: Clear symbol bounding boxes and save
    image_after_symbols = image.copy()
    if symbol_boxes:
        image_after_symbols = clear_bounding_boxes(image_after_symbols, symbol_boxes)
    save_after_symbol_clearing(path_manager, image_after_symbols)

    # Step 3: Clear text bounding boxes and save
    image_after_text = image_after_symbols.copy()
    if text_boxes:
        image_after_text = clear_bounding_boxes(image_after_text, text_boxes)
    save_after_text_clearing(path_manager, image_after_text)

    # Step 4: Convert to grayscale and save
    grayscale_image = to_grayscale(image_after_text)
    save_after_grayscale(path_manager, grayscale_image)

    # Step 5: Convert to binary and save
    binary_image = to_binary(grayscale_image)
    save_after_binary(path_manager, binary_image)

    # Step 6: Apply thinning if enabled and save
    if config_params["enable_thinning"]:
        processed_image = apply_thinning(binary_image)
    else:
        processed_image = binary_image

    # Save before-thinning and after-thinning images
    save_before_thinning_image(path_manager, binary_image)
    save_preprocessed_image(path_manager, processed_image)
    
    return processed_image


def perform_line_detection(path_manager, processed_image: np.ndarray, original_image: np.ndarray, 
                         image_width: int, image_height: int, config_params: Dict[str, Any]) -> List[LineSegment]:
    """Perform line detection with debug callbacks."""
    
    # Create callback for saving raw Hough lines
    def raw_lines_callback(hough_results, img_width, img_height):
        # Prepare Hough parameters for JSON output
        hough_params = {
            "rho": config_params["rho"],
            "theta_param": config_params["theta_param"],
            "threshold": config_params["threshold"],
            "min_line_length": config_params["min_line_length"],
            "max_line_gap": config_params["max_line_gap"],
            "enable_thinning": config_params["enable_thinning"],
        }

        # Save raw lines in various formats
        save_raw_hough_lines_image(path_manager, original_image, hough_results, img_width, img_height)
        save_raw_hough_lines_binary_image(path_manager, processed_image, hough_results, img_width, img_height)
        save_raw_hough_lines_json(path_manager, hough_results, img_width, img_height, hough_params)
        save_raw_hough_lines_indexed_image(path_manager, original_image, hough_results, img_width, img_height)

    # Detect line segments using existing algorithm with configurable parameters
    line_segments = detect_line_segments(
        processed_image,
        image_height=image_height,
        image_width=image_width,
        bounding_box_inclusive=None,  # Process entire image
        max_line_gap=config_params["max_line_gap"],
        threshold=config_params["threshold"],
        min_line_length=config_params["min_line_length"],
        rho=config_params["rho"],
        theta_param=config_params["theta_param"],
        debug_raw_lines_callback=raw_lines_callback,
    )

    print(f"Detected {len(line_segments)} line segments")
    return line_segments


def perform_line_postprocessing(path_manager, original_image: np.ndarray, line_segments: List[LineSegment], 
                              symbol_boxes: List[BoundingBox], config_params: Dict[str, Any]) -> tuple:
    """Apply post-processing to merge fragmented lines and handle symbol intersections."""
    
    # Apply symbol-aware post-processing
    base_postprocessor = LinePostProcessor(
        merge_distance_threshold=config_params["merge_distance_threshold"],
        angular_tolerance=config_params["angular_tolerance"],
        min_line_length=config_params["min_processed_line_length"],
        extension_padding=config_params["extension_padding"],
    )

    # Use symbol-aware post-processor with debug hooks
    symbol_aware_postprocessor = SymbolAwareLinePostProcessor(
        symbol_boxes=symbol_boxes, base_processor=base_postprocessor
    )

    image_height, image_width = original_image.shape[:2]

    # Apply base post-processing with intermediate saves
    if base_postprocessor:
        # Step 1: Extend lines
        extended_lines_pixel = base_postprocessor._denormalize_lines(line_segments, image_width, image_height)
        extended_lines_pixel = base_postprocessor._extend_lines(extended_lines_pixel)
        extended_lines = base_postprocessor._normalize_lines(extended_lines_pixel, image_width, image_height)
        save_lines_after_extension(path_manager, original_image, line_segments, extended_lines)

        # Step 2: Merge lines
        merged_lines_pixel = base_postprocessor._merge_connected_lines(extended_lines_pixel)
        merged_lines = base_postprocessor._normalize_lines(merged_lines_pixel, image_width, image_height)
        save_lines_after_merging(path_manager, original_image, extended_lines, merged_lines)

        # Step 3: Filter short lines
        filtered_lines_pixel = base_postprocessor._filter_short_lines(merged_lines_pixel, image_width, image_height)
        filtered_lines = base_postprocessor._normalize_lines(filtered_lines_pixel, image_width, image_height)
        save_lines_after_filtering(path_manager, original_image, merged_lines, filtered_lines)

        base_processed_lines = filtered_lines
    else:
        base_processed_lines = line_segments

    # Conditionally apply symbol-aware processing
    if config_params["enable_symbol_intersection"] and symbol_boxes:
        print(f"Applying symbol-aware processing with {len(symbol_boxes)} symbol boxes")

        # Apply symbol-aware processing
        processed_line_segments, intersection_metadata = symbol_aware_postprocessor.process_lines(
            base_processed_lines, image_width, image_height
        )

        # Save symbol intersection analysis
        save_symbol_intersections(path_manager, original_image, base_processed_lines, symbol_boxes, intersection_metadata)

        print(f"After symbol-aware post-processing: {len(processed_line_segments)} line segments")
    else:
        print(f"Skipping symbol-aware processing (enable_symbol_intersection={config_params['enable_symbol_intersection']}, symbol_boxes={len(symbol_boxes)})")

        # Skip symbol intersection processing - use base processed lines
        processed_line_segments = base_processed_lines
        intersection_metadata = []

        print(f"Using base post-processing results: {len(processed_line_segments)} line segments")

    return processed_line_segments, intersection_metadata


def convert_line_segments_to_json(line_segments: List[LineSegment]) -> List[Dict]:
    """Convert LineSegment objects to JSON format."""
    
    lines_json = []
    for line in line_segments:
        lines_json.append({
            "startX": line.startX,
            "startY": line.startY,
            "endX": line.endX,
            "endY": line.endY,
        })
    return lines_json


def transform_line_coordinates_to_original(event: Dict, lines_json: List[Dict], 
                                         symbol_boxes: List[BoundingBox], text_boxes: List[BoundingBox],
                                         intersection_metadata: List[Dict], 
                                         image_width: int, image_height: int) -> tuple:
    """Transform line coordinates to original image space if notes processing results are available."""
    
    coordinate_transformation_applied = False
    transformation_metadata = {}
    
    # Check if we have notes processing results for transformation
    notes_processing_results = event.get('notes_processing_results')
    if notes_processing_results:
        try:
            print("Applying coordinate transformation from processed to original space for line segments")
            
            # Extract transformation metadata from notes processor results
            transformation_metadata = get_transformation_metadata_from_notes_processor(notes_processing_results)
            
            # Transform line coordinates to original image space
            original_lines = transform_coordinates_to_original(
                coordinates=lines_json,
                transformation_metadata=transformation_metadata,
                coordinate_type="line"
            )
            
            # Validate transformation results
            validation_result = validate_transformation_result(
                original_coords=lines_json,
                transformed_coords=original_lines,
                transformation_metadata=transformation_metadata
            )
            
            # Update lines with transformed coordinates
            lines_json = original_lines
            coordinate_transformation_applied = True
            
            print(f"Line coordinate transformation completed: {validation_result['statistics']}")
            
            processing_metadata = {
                "image_dimensions": [image_width, image_height],
                "symbol_boxes_processed": len(symbol_boxes),
                "text_boxes_processed": len(text_boxes),
                "lines_with_symbol_intersections": len(intersection_metadata),
                "coordinate_transformation": {
                    'applied': True,
                    'validation': validation_result,
                    'metadata': transformation_metadata
                }
            }
            
        except Exception as e:
            print(f"Line coordinate transformation failed, using processed coordinates: {str(e)}")
            processing_metadata = {
                "image_dimensions": [image_width, image_height],
                "symbol_boxes_processed": len(symbol_boxes),
                "text_boxes_processed": len(text_boxes),
                "lines_with_symbol_intersections": len(intersection_metadata),
                "coordinate_transformation": {
                    'applied': False,
                    'error': str(e)
                }
            }
    else:
        print("No notes processing results available, using processed coordinates")
        processing_metadata = {
            "image_dimensions": [image_width, image_height],
            "symbol_boxes_processed": len(symbol_boxes),
            "text_boxes_processed": len(text_boxes),
            "lines_with_symbol_intersections": len(intersection_metadata),
            "coordinate_transformation": {
                'applied': False,
                'reason': 'No notes processing results available'
            }
        }
    
    return lines_json, processing_metadata
