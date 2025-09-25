import json
import os
import re
import time
import traceback
from datetime import datetime
from typing import Dict, Any, List, Tuple
import logging
import io

import boto3
import cv2
import numpy as np
from PIL import Image

from config_helper import get_lambda_config, store_results_in_s3
from execution_paths import create_path_manager
from debug_image_utils import generate_text_debug_image

# Set up logging
logger = logging.getLogger()
log_level = os.environ.get('LOG_LEVEL', 'INFO')
logger.setLevel(getattr(logging, log_level.upper()))

# Initialize AWS clients
s3_client = boto3.client('s3')
bedrock_data_automation = boto3.client('bedrock-data-automation-runtime', region_name=os.environ.get('REGION'))
logger.info(f"Boto3 version: {boto3.__version__}")

# Get environment variables
BDA_PROJECT_ARN = os.environ.get('BDA_PROJECT_ARN')
INPUT_BUCKET = os.environ.get('INPUT_BUCKET')
OUTPUT_BUCKET = os.environ.get('OUTPUT_BUCKET')

def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Text detection Lambda function using Amazon Bedrock Data Automation for document analysis.
    
    Uses execution-based file organization and processes the original image,
    returning text elements with coordinates in original image space.
    """
    
    try:
        logger.info(f"Text detection Lambda invoked with event: {json.dumps(event)}")
        
        # Create execution path manager for organizing files
        path_manager = create_path_manager(event, context, OUTPUT_BUCKET)
        logger.info(f"Using execution ID: {path_manager.clean_execution_id}")
        
        # Extract parameters from event
        image_key = event.get('image_key')
        original_key = event.get('original_key')
        input_bucket = INPUT_BUCKET
        
        # Get processing configuration from S3
        processing_config = {}
        if 'config_s3_key' in event:
            try:
                full_config = get_lambda_config(event, 'notes_processing')  # Text detection needs notes_processing config for manual coordinates
                processing_config = {'notes_processing': full_config}
            except Exception as e:
                logger.warning(f"Failed to read config from S3, using defaults: {str(e)}")
        else:
            # Fallback for legacy support
            processing_config = event.get('processing_config', {})
        
        if not image_key:
            raise ValueError("Missing required parameter: image_key")
        
        if not input_bucket:
            raise ValueError("INPUT_BUCKET environment variable not set")
            
        if not OUTPUT_BUCKET:
            raise ValueError("OUTPUT_BUCKET environment variable not set")
        
        # Always use original image for BDA processing
        bda_bucket = input_bucket
        bda_image_key = original_key or image_key
        
        logger.info(f"Using image for BDA processing: s3://{bda_bucket}/{bda_image_key}")
        
        # Get manual coordinates for potential filtering
        notes_config = processing_config.get('notes_processing', {})
        manual_coordinates = notes_config.get('manual_coordinates', {})
        
        if manual_coordinates and manual_coordinates.get('width', 0) > 0:
            logger.info(f"Manual coordinates specified for filtering: {manual_coordinates}")
        
        # Invoke Bedrock Data Automation with execution-based output path
        bda_output_prefix = path_manager.get_bda_output_prefix()
        bda_response = invoke_bedrock_data_automation(
            input_bucket=bda_bucket,
            output_bucket=OUTPUT_BUCKET,
            image_key=bda_image_key,
            output_prefix=bda_output_prefix
        )
        
        # Wait for BDA processing to complete
        job_id = bda_response['invocationArn']
        final_status = wait_for_bda_completion(job_id)
        
        if final_status['status'] != 'Success':
            raise Exception(f"BDA processing failed: {final_status.get('message', 'Unknown error')}")
        
        # Get BDA output location
        output_location = final_status['outputConfiguration']
        bda_output_uri = output_location['s3Uri']
        
        logger.info(f"BDA processing complete. Output stored at: {bda_output_uri}")
        
        # Fetch and process BDA results (always in original image space)
        text_elements, image_dimensions = process_bda_results(bda_output_uri, bda_bucket, bda_image_key)
        
        # Filter text elements if manual coordinates are specified
        filtering_stats = {}
        if manual_coordinates and manual_coordinates.get('width', 0) > 0:
            text_elements, filtering_stats = filter_text_elements_by_region(
                text_elements, manual_coordinates, image_dimensions
            )
            logger.info(f"Text filtering applied: {filtering_stats}")
        
        # Store text detection results using execution-based path
        text_detection_s3_key = path_manager.get_text_detection_results_s3_key()
        
        text_detection_results = {
            'text_elements': text_elements,
            'image_dimensions': image_dimensions,
            'bda_output_uri': bda_output_uri,
            'bda_job_id': job_id,
            'source_bucket': bda_bucket,
            'source_key': bda_image_key,
            'execution_id': path_manager.execution_id,
            'timestamp': datetime.utcnow().isoformat(),
            'coordinate_processing': {
                'coordinates_in_original_space': True,
                'manual_coordinates': manual_coordinates if manual_coordinates.get('width', 0) > 0 else None,
                'filtering_applied': bool(filtering_stats),
                'filtering_stats': filtering_stats
            }
        }
        
        store_results_in_s3(OUTPUT_BUCKET, text_detection_s3_key, text_detection_results)
        
        # Generate debug image with detected text elements
        debug_image_generated = False
        debug_image_s3_key = None
        try:
            # Load original image data for debug visualization
            image_response = s3_client.get_object(Bucket=bda_bucket, Key=bda_image_key)
            image_data = image_response['Body'].read()
            
            # Generate debug image using shared utilities
            debug_image_s3_key = generate_text_debug_image(
                image_data=image_data,
                text_elements=text_elements,
                path_manager=path_manager,
                filtering_stats=filtering_stats if filtering_stats else None,
                title="Text Detection Debug"
            )
            debug_image_generated = True
            logger.info(f"Debug image generated successfully: s3://{OUTPUT_BUCKET}/{debug_image_s3_key}")
        except Exception as e:
            logger.warning(f"Debug image generation failed, continuing without debug image: {str(e)}")
            debug_image_generated = False
        
        # Return minimal response with S3 reference
        result = {
            'statusCode': 200,
            's3_results': {
                'bucket': OUTPUT_BUCKET,
                'text_detection_results_key': text_detection_s3_key
            },
            'summary': {
                'text_elements_count': len(text_elements),
                'bda_job_id': job_id,
                'execution_id': path_manager.clean_execution_id,
                'coordinates_in_original_space': True,
                'debug_image_generated': debug_image_generated
            }
        }
        
        # Add debug image key if generation was successful
        if debug_image_generated and debug_image_s3_key:
            result['s3_results']['debug_image_key'] = debug_image_s3_key
        
        logger.info(f"Text detection processing complete. Found {len(text_elements)} text elements in original coordinate space, stored in s3://{OUTPUT_BUCKET}/{text_detection_s3_key}")
        
        return result
        
    except Exception as e:
        logger.error(f"Error in text detection processing: {str(e)}")
        logger.error(traceback.format_exc())
        
        return {
            'statusCode': 500,
            'success': False,
            'error': str(e),
            'source_bucket': input_bucket,
            'source_key': event.get('image_key')
        }


def invoke_bedrock_data_automation(input_bucket: str, output_bucket: str, image_key: str, output_prefix: str) -> Dict[str, Any]:
    """
    Invoke Bedrock Data Automation for document processing.
    """
    # Get account ID from environment variable to avoid STS network calls
    account_id = os.environ.get('AWS_ACCOUNT_ID')
    if not account_id:
        raise ValueError("AWS_ACCOUNT_ID environment variable not set. This is required for BDA profile ARN construction.")
    
    # Get region from session (no network call required)
    current_region = boto3.Session().region_name
    
    logger.info(f"Using account: {account_id}, region: {current_region}")
    logger.info(f"BDA output will be stored at: s3://{output_bucket}/{output_prefix}/")
    
    try:
        response = bedrock_data_automation.invoke_data_automation_async(
            inputConfiguration={
                's3Uri': f"s3://{input_bucket}/{image_key}",
            },
            outputConfiguration={
                's3Uri': f"s3://{output_bucket}/{output_prefix}/"
            },
            dataAutomationConfiguration={
                'dataAutomationProjectArn': BDA_PROJECT_ARN,
            },
            dataAutomationProfileArn=f'arn:aws:bedrock:{current_region}:{account_id}:data-automation-profile/us.data-automation-v1'
        )
        
        logger.info(f"BDA invocation started with job ID: {response['invocationArn']}")
        return response
        
    except Exception as e:
        logger.error(f"Error invoking BDA: {str(e)}")
        raise


def wait_for_bda_completion(job_id: str, max_attempts: int = 60) -> Dict[str, Any]:
    """
    Wait for Bedrock Data Automation job to complete.
    """
    
    attempt = 0
    while attempt < max_attempts:
        try:
            response = bedrock_data_automation.get_data_automation_status(
                invocationArn=job_id
            )
            
            status = response['status']
            logger.info(f"BDA job {job_id} status: {status}")
            
            if status in ['Success', 'ServiceError', 'ClientError']:
                return response
            
            time.sleep(5)  # Wait 5 seconds before next check
            attempt += 1
            
        except Exception as e:
            logger.error(f"Error checking BDA status: {str(e)}")
            raise
    
    raise TimeoutError(f"BDA job {job_id} did not complete within timeout period")


def get_original_image_dimensions(bucket: str, key: str) -> Tuple[int, int]:
    """
    Get original image dimensions from S3 without downloading the full image.
    Uses PIL to read just the image headers for efficiency.
    
    Args:
        bucket: S3 bucket name containing the image
        key: S3 object key for the image
        
    Returns:
        Tuple of (width, height) in pixels
    """
    try:
        logger.info(f"Getting original image dimensions for s3://{bucket}/{key}")
        
        # Get the image object from S3
        response = s3_client.get_object(Bucket=bucket, Key=key)
        image_data = response['Body'].read()
        
        # Use PIL to read just the image headers for efficiency
        with Image.open(io.BytesIO(image_data)) as img:
            width, height = img.size
            
        logger.info(f"Original image dimensions: {width}x{height}")
        return width, height
        
    except Exception as e:
        logger.error(f"Error getting original image dimensions: {str(e)}")
        raise


def transform_bbox(left, top, box_width, box_height, width, height, corners):
    """
    Transform bounding box coordinates using perspective transform from metadata
    """
    
    # Convert box coordinates to normalized (0-1) space
    box_corners = np.array([
        [left, top],  # top-left
        [left + box_width, top],  # top-right
        [left + box_width, top + box_height],  # bottom-right
        [left, top + box_height]  # bottom-left
    ])

    # Create destination points for perspective transform
    dst_points = np.array([
        [0, 0],  # top-left
        [1, 0],  # top-right
        [1, 1],  # bottom-right
        [0, 1]   # bottom-left
    ], dtype=np.float32)

    # Calculate perspective transform matrix
    transform_matrix = cv2.getPerspectiveTransform(corners, dst_points)

    # Apply transformation to box corners
    transformed_corners = cv2.perspectiveTransform(
        box_corners.reshape(-1, 1, 2), 
        transform_matrix
    ).squeeze()

    # Get the new bounding box coordinates
    new_left = float(np.min(transformed_corners[:, 0]))
    new_top = float(np.min(transformed_corners[:, 1]))
    new_width = float(np.max(transformed_corners[:, 0]) - new_left)
    new_height = float(np.max(transformed_corners[:, 1]) - new_top)
    new_bounding_box = {
            'x': new_left * width,
            'y': new_top * height,
            'width': new_width * width,
            'height': new_height * height
        }
    
    return new_bounding_box

def make_rotated_patch(bbox, width, height, corners):
    
    # Extract normalized coordinates
    left = bbox['left']
    top = bbox['top']
    box_width = bbox['width']
    box_height = bbox['height']
    
    # Calculate center of the box
    center_x = left + box_width / 2
    center_y = top + box_height / 2
    
    # From center-based to corner-based
    left = center_x - box_width / 2
    top = center_y - box_height / 2
    
    # Use transform_bbox to create the transformed rectangle
    return transform_bbox(
        left=left,
        top=top,
        box_width=box_width,
        box_height=box_height,
        width=width, 
        height=height,
        corners=corners
    )
    
def process_bda_results(bda_output_uri: str, original_bucket: str, original_image_key: str) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Process BDA results to extract text elements with pixel coordinates.
    
    Args:
        bda_output_uri: S3 URI to the BDA output directory or job_metadata.json file
        original_bucket: S3 bucket containing the original image
        original_image_key: S3 key for the original image
        
    Returns:
        Tuple of (text_elements list, image_dimensions dict)
    """
    
    text_elements = []
    image_dimensions = None
    
    try:
        # Parse the job metadata S3 URI
        match = re.match(r's3://([^/]+)/(.+)', bda_output_uri)
        if not match:
            raise ValueError(f"Invalid S3 URI format: {bda_output_uri}")
        
        metadata_bucket = match.group(1)
        metadata_key = match.group(2)
        
        # Check if the URI already points to job_metadata.json
        if metadata_key.endswith('job_metadata.json'):
            # URI already points to the metadata file
            job_metadata_key = metadata_key
            logger.info(f"URI already points to job_metadata.json: s3://{metadata_bucket}/{job_metadata_key}")
        else:
            # URI points to a directory, list objects to find metadata
            # Ensure the key ends with a trailing slash for directory listing
            if not metadata_key.endswith('/'):
                metadata_key += '/'
            
            # List objects in the BDA output directory
            logger.info(f"Listing objects in s3://{metadata_bucket}/{metadata_key}")
            response = s3_client.list_objects_v2(
                Bucket=metadata_bucket,
                Prefix=metadata_key
            )
            
            # Find the job metadata file
            job_metadata_key = None
            for obj in response.get('Contents', []):
                if obj['Key'].endswith('job_metadata.json'):
                    job_metadata_key = obj['Key']
                    break
            
            if not job_metadata_key:
                raise ValueError(f"No job_metadata.json found in {bda_output_uri}")
        
        # Fetch the job metadata
        logger.info(f"Fetching job metadata from s3://{metadata_bucket}/{job_metadata_key}")
        response = s3_client.get_object(
            Bucket=metadata_bucket,
            Key=job_metadata_key
        )
        job_metadata = json.loads(response['Body'].read().decode('utf-8'))
        
        # Extract the standard output path from job metadata
        if 'output_metadata' not in job_metadata or not job_metadata['output_metadata']:
            logger.warning("No output_metadata found in job metadata")
            return text_elements, image_dimensions
        
        # Get the first asset's segment metadata
        asset_metadata = job_metadata['output_metadata'][0]
        if 'segment_metadata' not in asset_metadata or not asset_metadata['segment_metadata']:
            logger.warning("No segment_metadata found in asset metadata")
            return text_elements, image_dimensions
        
        # Get the standard output path
        standard_output_path = asset_metadata['segment_metadata'][0].get('standard_output_path')
        if not standard_output_path:
            logger.warning("No standard_output_path found in segment metadata")
            return text_elements, image_dimensions
        
        # Parse the standard output S3 URI
        match = re.match(r's3://([^/]+)/(.+)', standard_output_path)
        if not match:
            raise ValueError(f"Invalid standard output S3 URI format: {standard_output_path}")
        
        output_bucket = match.group(1)
        output_key = match.group(2)
        
        # Fetch the actual BDA results
        logger.info(f"Fetching BDA text detection results from s3://{output_bucket}/{output_key}")
        response = s3_client.get_object(
            Bucket=output_bucket,
            Key=output_key
        )
        standard_output = json.loads(response['Body'].read().decode('utf-8'))

        # Get original image dimensions instead of rectified dimensions
        image_width, image_height = get_original_image_dimensions(original_bucket, original_image_key)
        corners = np.array(standard_output["pages"][0]["asset_metadata"]["corners"], dtype=np.float32)
        
        image_dimensions = {
            'width': image_width,
            'height': image_height
        }
        logger.info(f"Image dimensions: {image_width}x{image_height}")
        
        for text_line in standard_output['text_lines']:
            bbox = text_line['locations'][0]['bounding_box']
            new_bounding_box = make_rotated_patch(bbox, image_width, image_height, corners)
            text_element = {'text': text_line['text'], 'bounding_box': new_bounding_box}
            text_elements.append(text_element)
        
        logger.info(f"Processed {len(text_elements)} text elements from BDA text detection results")
        
    except Exception as e:
        logger.error(f"Error processing BDA results: {str(e)}")
        logger.error(traceback.format_exc())
    
    return text_elements, image_dimensions


def filter_text_elements_by_region(
    text_elements: List[Dict[str, Any]], 
    manual_coordinates: Dict[str, Any], 
    image_dimensions: Dict[str, int]
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Filter text elements that fall outside the manual crop region.
    Keeps coordinates in original image space (no translation).
    
    Args:
        text_elements: List of text elements with bounding boxes in original image coordinates
        manual_coordinates: Manual crop coordinates {x, y, width, height}
        image_dimensions: Original image dimensions {width, height}
        
    Returns:
        Tuple of (filtered_text_elements, filtering_stats)
    """
    
    try:
        # Extract crop region boundaries
        crop_x = int(manual_coordinates['x'])
        crop_y = int(manual_coordinates['y'])
        crop_width = int(manual_coordinates['width'])
        crop_height = int(manual_coordinates['height'])
        
        crop_right = crop_x + crop_width
        crop_bottom = crop_y + crop_height
        
        logger.info(f"Filtering text elements for crop region: ({crop_x}, {crop_y}) to ({crop_right}, {crop_bottom})")
        logger.info(f"Coordinates will remain in original image space (no translation)")
        
        filtered_elements = []
        original_count = len(text_elements)
        kept_count = 0
        filtered_count = 0
        
        for element in text_elements:
            bbox = element.get('bounding_box', {})
            
            # Get text bounding box coordinates
            text_x = bbox.get('x', 0)
            text_y = bbox.get('y', 0)
            text_width = bbox.get('width', 0)
            text_height = bbox.get('height', 0)
            
            # Calculate text bounding box boundaries
            text_right = text_x + text_width
            text_bottom = text_y + text_height
            
            # Check if text overlaps with crop region
            overlaps = (
                text_x < crop_right and  # Text left edge is before crop right edge
                text_right > crop_x and  # Text right edge is after crop left edge
                text_y < crop_bottom and  # Text top edge is before crop bottom edge
                text_bottom > crop_y     # Text bottom edge is after crop top edge
            )
            
            if overlaps:
                # Keep this text element with original coordinates (no translation)
                filtered_element = element.copy()
                filtered_elements.append(filtered_element)
                kept_count += 1
                
                if kept_count <= 5:  # Log first few for debugging
                    logger.info(f"Text '{element.get('text', '')[:20]}...' kept in original space: "
                              f"({text_x:.1f}, {text_y:.1f})")
            else:
                filtered_count += 1
                if filtered_count <= 5:  # Log first few filtered for debugging
                    logger.info(f"Text '{element.get('text', '')[:20]}...' filtered out: "
                              f"({text_x:.1f}, {text_y:.1f}) outside crop region")
        
        # Calculate statistics
        filtering_stats = {
            'original_count': original_count,
            'kept_count': kept_count,
            'filtered_count': filtered_count,
            'crop_region': {
                'x': crop_x,
                'y': crop_y,
                'width': crop_width,
                'height': crop_height
            },
            'coordinates_in_original_space': True,
            'coordinate_translation_applied': False
        }
        
        logger.info(f"Text filtering complete: {original_count} -> {kept_count} elements (filtered {filtered_count})")
        logger.info(f"All coordinates remain in original image space")
        
        return filtered_elements, filtering_stats
        
    except Exception as e:
        logger.error(f"Error filtering text elements: {str(e)}")
        logger.error(traceback.format_exc())
        
        # Return original elements and error stats on failure
        return text_elements, {
            'original_count': len(text_elements),
            'kept_count': len(text_elements),
            'filtered_count': 0,
            'error': str(e),
            'coordinates_in_original_space': True,
            'coordinate_translation_applied': False
        }
