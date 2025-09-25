import json
import os
import traceback
from datetime import datetime
from io import BytesIO
from typing import Dict, Any
import logging

import boto3
import numpy as np
from PIL import Image

from config_helper import get_lambda_config, store_results_in_s3
from execution_paths import create_path_manager
from frame_detector import FrameDetector
from notes_section_detector import NotesSectionDetector

# Set up logging
logger = logging.getLogger()
log_level = os.environ.get('LOG_LEVEL', 'INFO')
logger.setLevel(getattr(logging, log_level.upper()))

# Initialize AWS clients
s3_client = boto3.client('s3')

# Initialize detectors
notes_detector = NotesSectionDetector()
frame_detector = FrameDetector()

# Get environment variables
INPUT_BUCKET = os.environ.get('INPUT_BUCKET')
OUTPUT_BUCKET = os.environ.get('OUTPUT_BUCKET')


def make_json_serializable(obj):
    """
    Convert numpy types and other non-JSON-serializable types to JSON-serializable equivalents.
    """
    if isinstance(obj, dict):
        return {k: make_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_json_serializable(v) for v in obj]
    elif isinstance(obj, tuple):
        return tuple(make_json_serializable(v) for v in obj)
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif hasattr(obj, 'item'):  # numpy scalars
        return obj.item()
    else:
        return obj


def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Notes Processor Lambda function.
    
    Uses execution-based file organization for processing P&ID charts.
    Detects and removes notes sections, saves processed image to S3.
    """
    
    try:
        logger.info(f"Notes Processor Lambda invoked with event: {json.dumps(event)}")
        
        # Create execution path manager for organizing files
        path_manager = create_path_manager(event, context, OUTPUT_BUCKET)
        logger.info(f"Using execution ID: {path_manager.clean_execution_id}")
        
        # Extract parameters from event
        image_key = event.get('image_key')
        input_bucket = INPUT_BUCKET
        
        # Get processing configuration from S3 using the new config helper
        processing_config = {}
        if 'config_s3_key' in event:
            try:
                config = get_lambda_config(event, 'notes_processing')
                logger.info(f"Loaded configuration from S3")
            except Exception as e:
                logger.warning(f"Failed to read config from S3, using defaults: {str(e)}")
                config = {}
        else:
            # Fallback for legacy support
            processing_config = event.get('processing_config', {})
            config = processing_config.get('notes_processing', {})
            logger.info("Using configuration from event (legacy mode)")
        
        logger.info(f"Using notes processing configuration: {json.dumps(config, indent=2)}")
        
        # Extract manual coordinates from config
        manual_coordinates = config.get('manual_coordinates', {})
        
        # Check if manual coordinates are provided (non-zero values)
        has_manual_coords = (manual_coordinates.get('width', 0) >= 0 and 
                           manual_coordinates.get('height', 0) >= 0)
        
        if has_manual_coords:
            # Manual mode: disable auto-processing
            remove_notes_section = False
            remove_frame = False
            processing_mode = "manual"
            logger.info("Manual coordinates provided - disabling auto-processing")
            logger.info(f"Manual coordinates: {manual_coordinates}")
        else:
            # Auto mode: use configuration
            remove_notes_section = config.get('remove_notes_section', True)
            frame_config = config.get('frame_config', {})
            remove_frame = frame_config.get('remove_frame', True)
            processing_mode = "auto"
            # Set manual_coordinates to None for clarity
            manual_coordinates = None
        
        if not image_key:
            raise ValueError("Missing required parameter: image_key")
        
        if not input_bucket:
            raise ValueError("INPUT_BUCKET environment variable not set")
        
        logger.info(f"Processing image: s3://{input_bucket}/{image_key}")
        logger.info(f"Processing mode: {processing_mode}")
        logger.info(f"Remove notes section: {remove_notes_section}")
        logger.info(f"Remove frame: {remove_frame}")
        
        # Download original image from S3
        original_image_data = download_image_from_s3(input_bucket, image_key)
        current_image_data = original_image_data
        
        # Capture original image dimensions
        original_dimensions = get_image_dimensions(original_image_data)
        logger.info(f"Original image dimensions: {original_dimensions['width']}x{original_dimensions['height']}")
        
        # Step 1: Frame removal (if enabled)
        frame_info = {'frame_detected': False, 'frame_removed': False}
        if remove_frame:
            logger.info("Processing frame removal")
            current_image_data, frame_info = frame_detector.detect_and_remove_frame(
                current_image_data, frame_config
            )
            logger.info(f"Frame processing complete. Detected: {frame_info.get('frame_detected', False)}, Removed: {frame_info.get('frame_removed', False)}")
        
        # Step 2: Notes section analysis and removal (only in auto mode)
        layout_analysis = notes_detector.analyze_image_layout(current_image_data)
        
        notes_coordinates = None
        coordinates_used = None
        manual_processing_applied = False
        
        if remove_notes_section and layout_analysis.get('notes_section_detected', False):
            logger.info("Notes section detected, removing from processed image")
            
            # Get notes section information (in frame-removed space)
            notes_section = layout_analysis.get('notes_section')
            notes_coordinates = {
                'x': notes_section.get('x'),
                'y': notes_section.get('y'),
                'width': notes_section.get('width'),
                'height': notes_section.get('height'),
                'confidence': notes_section.get('confidence'),
                'method_used': notes_section.get('method_used')
            }
            
            # Remove notes section from current image
            current_image_data = notes_detector.remove_notes_section(current_image_data)
        
        # Step 3: Manual coordinates processing (if provided)
        if manual_coordinates:
            logger.info("Processing manual coordinates")
            
            # Get current image dimensions for validation
            current_dimensions = get_image_dimensions(current_image_data)
            
            # Validate coordinates
            validation_result = validate_coordinates(manual_coordinates, current_dimensions)
            
            if validation_result['valid']:
                logger.info(f"Manual coordinates are valid, applying crop: {manual_coordinates}")
                
                # Apply manual crop
                current_image_data = apply_manual_crop(current_image_data, manual_coordinates)
                manual_processing_applied = True
                
                coordinates_used = {
                    'x': manual_coordinates['x'],
                    'y': manual_coordinates['y'],
                    'width': manual_coordinates['width'],
                    'height': manual_coordinates['height'],
                    'method_used': 'manual_coordinates',
                    'validation_status': 'valid'
                }
                
                logger.info("Manual crop applied successfully")
                
            else:
                logger.error(f"Invalid manual coordinates: {validation_result['error']}")
                logger.error("Returning original image without processing")
                
                coordinates_used = {
                    'x': manual_coordinates.get('x', 0),
                    'y': manual_coordinates.get('y', 0),
                    'width': manual_coordinates.get('width', 0),
                    'height': manual_coordinates.get('height', 0),
                    'method_used': 'manual_coordinates',
                    'validation_status': 'invalid',
                    'error': validation_result['error']
                }
                
                # Update processing mode to indicate failure
                processing_mode = "manual_failed"
        
        # Upload processed image using execution-based path
        processed_image_s3_key = path_manager.get_processed_image_s3_key()
        upload_processed_image_to_execution_location(
            current_image_data, processed_image_s3_key, OUTPUT_BUCKET
        )
        logger.info(f"Processed image uploaded: s3://{OUTPUT_BUCKET}/{processed_image_s3_key}")
        
        # Store notes processing metadata using execution-based path
        notes_metadata_s3_key = path_manager.get_notes_metadata_s3_key()
        notes_metadata = {
            'processing_mode': processing_mode,
            'original_image_dimensions': original_dimensions,
            'notes_coordinates': notes_coordinates,
            'coordinates_used': coordinates_used,
            'layout_analysis': layout_analysis,
            'frame_info': frame_info,
            'manual_processing_applied': manual_processing_applied,
            'execution_id': path_manager.execution_id,
            'timestamp': datetime.utcnow().isoformat()
        }
        store_results_in_s3(OUTPUT_BUCKET, notes_metadata_s3_key, notes_metadata)
        
        # Calculate frame-adjusted notes coordinates for visualization
        frame_adjusted_notes_coordinates = None
        if notes_coordinates and frame_info.get('frame_removed', False):
            frame_bounds = frame_info.get('frame_bounds', {})
            if frame_bounds:
                frame_adjusted_notes_coordinates = {
                    'x': notes_coordinates['x'] + frame_bounds.get('left', 0),
                    'y': notes_coordinates['y'] + frame_bounds.get('top', 0),
                    'width': notes_coordinates['width'],
                    'height': notes_coordinates['height'],
                    'confidence': notes_coordinates['confidence'],
                    'method_used': notes_coordinates['method_used'],
                    'coordinate_space': 'original_image'
                }
                logger.info(f"Frame-adjusted notes coordinates: x={frame_adjusted_notes_coordinates['x']}, y={frame_adjusted_notes_coordinates['y']}")
        
        # Calculate processed image dimensions
        processed_dimensions = calculate_processed_image_dimensions(
            original_dimensions, 
            manual_coordinates, 
            manual_processing_applied, 
            notes_coordinates, 
            frame_info
        )
        logger.info(f"Processed image dimensions: {processed_dimensions['width']}x{processed_dimensions['height']}")
        
        # Build response with execution-based paths
        result = {
            'statusCode': 200,
            'success': True,
            'processing_mode': processing_mode,
            'source_bucket': input_bucket,
            'source_key': image_key,
            'processed_bucket': OUTPUT_BUCKET,
            'processed_key': processed_image_s3_key,
            'notes_metadata_s3_key': notes_metadata_s3_key,
            'original_image_dimensions': original_dimensions,
            'processed_image_dimensions': processed_dimensions,
            'notes_coordinates': notes_coordinates,
            'coordinates_used': coordinates_used,
            'frame_adjusted_notes_coordinates': frame_adjusted_notes_coordinates,
            'layout_analysis': layout_analysis,
            'frame_info': frame_info,
            'notes_cutting_disabled': processing_mode in ["manual", "manual_failed"],
            'frame_removal_disabled': processing_mode in ["manual", "manual_failed"],
            'manual_processing_applied': manual_processing_applied,
            'execution_id': path_manager.execution_id
        }
        
        logger.info(f"Notes processing complete. Notes detected: {layout_analysis.get('notes_section_detected', False)}")
        
        # Ensure all numpy types are converted to JSON-serializable types
        return make_json_serializable(result)
        
    except Exception as e:
        logger.error(f"Error in notes processing: {str(e)}")
        logger.error(traceback.format_exc())
        
        return {
            'statusCode': 500,
            'success': False,
            'error': str(e),
            'source_bucket': input_bucket,
            'source_key': event.get('image_key')
        }


def get_image_dimensions(image_data: bytes) -> Dict[str, int]:
    """Get image dimensions from image bytes."""
    try:
        # Open image from bytes
        image = Image.open(BytesIO(image_data))
        width, height = image.size
        
        return {
            'width': width,
            'height': height
        }
    except Exception as e:
        logger.error(f"Error getting image dimensions: {str(e)}")
        # Return default dimensions on error
        return {
            'width': 0,
            'height': 0
        }


def download_image_from_s3(bucket: str, key: str) -> bytes:
    """Download image from S3 and return as bytes."""
    try:
        logger.info(f"Downloading image from s3://{bucket}/{key}")
        response = s3_client.get_object(Bucket=bucket, Key=key)
        return response['Body'].read()
    except Exception as e:
        logger.error(f"Error downloading image from S3: {str(e)}")
        raise


def validate_coordinates(coords: Dict[str, Any], image_dims: Dict[str, int]) -> Dict[str, Any]:
    """
    Validate that coordinates are within image bounds and have required fields.
    
    Args:
        coords: Dictionary containing x, y, width, height
        image_dims: Dictionary containing image width and height
        
    Returns:
        Dictionary with validation result and error message if invalid
    """
    required_keys = ['x', 'y', 'width', 'height']
    
    # Check for required keys
    missing_keys = [k for k in required_keys if k not in coords]
    if missing_keys:
        return {
            'valid': False,
            'error': f"Missing required coordinate fields: {missing_keys}"
        }
    
    try:
        # Convert to integers and validate types
        x = int(coords['x'])
        y = int(coords['y'])
        w = int(coords['width'])
        h = int(coords['height'])
    except (ValueError, TypeError) as e:
        return {
            'valid': False,
            'error': f"Invalid coordinate values - must be integers: {str(e)}"
        }
    
    img_w, img_h = image_dims['width'], image_dims['height']
    
    # Check bounds for x,y coordinates
    if x < 0 or y < 0:
        return {
            'valid': False,
            'error': f"Coordinates must be non-negative: x={x}, y={y}"
        }
    
    # Note: Width and height <= 0 are allowed and will result in image passthrough
    
    # Only check bounds if width and height are positive (normal cropping case)
    if w > 0 and h > 0:
        if x >= img_w or y >= img_h:
            return {
                'valid': False,
                'error': f"Start coordinates exceed image bounds: x={x}, y={y}, image_size={img_w}x{img_h}"
            }
        
        if x + w > img_w or y + h > img_h:
            return {
                'valid': False,
                'error': f"Crop region exceeds image bounds: region=({x},{y},{w},{h}), image_size={img_w}x{img_h}"
            }
    
    return {'valid': True}


def apply_manual_crop(image_data: bytes, coordinates: Dict[str, Any]) -> bytes:
    """
    Crop image to keep only the specified region.
    
    Args:
        image_data: Raw image data as bytes
        coordinates: Dictionary with x, y, width, height
        
    Returns:
        Cropped image data as bytes
    """
    try:
        # Load image
        image = Image.open(BytesIO(image_data))
        
        # Extract coordinates
        x = int(coordinates['x'])
        y = int(coordinates['y'])
        w = int(coordinates['width'])
        h = int(coordinates['height'])
        
        if w > 0 and h > 0:
            # Crop image to keep only the specified region
            # PIL crop uses (left, top, right, bottom) format
            cropped_image = image.crop((x, y, x + w, y + h))
        else:
            logger.info(f'Width or height <= 0 (w={w}, h={h}), passing image through unchanged')
            cropped_image = image
        
        # Convert back to bytes
        output_buffer = BytesIO()
        cropped_image.save(output_buffer, format='PNG')
        cropped_data = output_buffer.getvalue()
        
        logger.info(f"Manual crop applied: original {image.size} -> cropped {cropped_image.size}")
        
        return cropped_data
        
    except Exception as e:
        logger.error(f"Error applying manual crop: {str(e)}")
        raise


def upload_processed_image_to_execution_location(image_data: bytes, s3_key: str, bucket: str) -> None:
    """Upload processed image to execution-based S3 location."""
    try:
        # Upload processed image
        s3_client.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=image_data,
            ContentType='image/png'
        )
        
        logger.info(f"Processed image uploaded to s3://{bucket}/{s3_key}")
        
    except Exception as e:
        logger.error(f"Error uploading processed image: {str(e)}")
        raise

def upload_processed_image_to_s3(image_data: bytes, original_key: str, bucket: str, 
                                  frame_removed: bool = False, notes_removed: bool = False,
                                  manual_cropped: bool = False) -> str:
    """Upload processed image to S3 and return the new key."""
    try:
        # Create processed image key with descriptive suffix
        base_name = os.path.splitext(os.path.basename(original_key))[0]
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        
        # Build suffix based on what was processed
        suffixes = []
        if frame_removed:
            suffixes.append("frame_removed")
        if notes_removed:
            suffixes.append("notes_removed")
        
        suffix = "_".join(suffixes) if suffixes else "processed"
        processed_key = f"processed/{base_name}_{suffix}_{timestamp}.png"
        
        # Upload processed image
        s3_client.put_object(
            Bucket=bucket,
            Key=processed_key,
            Body=image_data,
            ContentType='image/png'
        )
        
        logger.info(f"Processed image uploaded to s3://{bucket}/{processed_key}")
        return processed_key
        
    except Exception as e:
        logger.error(f"Error uploading processed image: {str(e)}")
        # Return original key on error
        return original_key


def calculate_processed_image_dimensions(
    original_dimensions: Dict[str, int], 
    manual_coordinates: Dict[str, Any], 
    manual_processing_applied: bool, 
    notes_coordinates: Dict[str, Any], 
    frame_info: Dict[str, Any]
) -> Dict[str, int]:
    """
    Calculate the dimensions of the processed image based on what processing was applied.
    
    Args:
        original_dimensions: Original image dimensions {width, height}
        manual_coordinates: Manual crop coordinates (if provided)
        manual_processing_applied: Whether manual processing was successfully applied
        notes_coordinates: Auto-detected notes coordinates (if any)
        frame_info: Frame processing information
        
    Returns:
        Processed image dimensions {width, height}
    """
    
    current_width = original_dimensions['width']
    current_height = original_dimensions['height']
    
    # Apply frame removal dimension changes
    if frame_info.get('frame_removed', False) and 'frame_bounds' in frame_info:
        frame_bounds = frame_info['frame_bounds']
        # After frame removal, dimensions are reduced by frame bounds
        current_width = current_width - frame_bounds.get('left', 0) - frame_bounds.get('right', 0)
        current_height = current_height - frame_bounds.get('top', 0) - frame_bounds.get('bottom', 0)
        logger.info(f"After frame removal: {current_width}x{current_height}")
    
    # Apply manual crop dimension changes
    if manual_processing_applied and manual_coordinates:
        # Manual crop defines the final dimensions directly
        crop_width = int(manual_coordinates.get('width', 0))
        crop_height = int(manual_coordinates.get('height', 0))
        
        if crop_width > 0 and crop_height > 0:
            current_width = crop_width
            current_height = crop_height
            logger.info(f"After manual crop: {current_width}x{current_height}")
    
    # Apply auto notes removal dimension changes (if no manual processing)
    elif notes_coordinates and not manual_processing_applied:
        # Auto notes removal typically crops from the right side
        notes_x = notes_coordinates.get('x', 0)
        if notes_x > 0:
            current_width = notes_x  # Width is reduced to notes start position
            logger.info(f"After auto notes removal: {current_width}x{current_height}")
    
    return {
        'width': current_width,
        'height': current_height
    }
