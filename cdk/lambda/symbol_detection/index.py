import json
import boto3
import base64
import os
import logging
from typing import Dict, Any, List
from datetime import datetime
from config_helper import get_config_from_s3
from coordinate_transform import (
    transform_coordinates_to_original,
    get_transformation_metadata_from_notes_processor,
    validate_transformation_result
)
from execution_paths import create_path_manager
from debug_image_utils import generate_symbol_debug_image_pair

logger = logging.getLogger()
log_level = os.environ.get('LOG_LEVEL', 'INFO')
logger.setLevel(getattr(logging, log_level.upper()))

# Initialize clients
sagemaker_runtime = boto3.client('sagemaker-runtime')
s3_client = boto3.client('s3')

# Get endpoint name from environment variable
ENDPOINT_NAME = os.environ.get('SAGEMAKER_ENDPOINT_NAME')
INPUT_BUCKET = os.environ.get('INPUT_BUCKET')
OUTPUT_BUCKET = os.environ.get('OUTPUT_BUCKET')

if not ENDPOINT_NAME:
    raise ValueError("SAGEMAKER_ENDPOINT_NAME environment variable is not set")

if not OUTPUT_BUCKET:
    raise ValueError("OUTPUT_BUCKET environment variable is not set")


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda function to invoke SageMaker endpoint for P&ID symbol detection.
    
    Expected input format from Step Functions:
    {
        "image_key": "1.jpg",
        "config_s3_key": "config/image_123_config.json",
        "processing_bucket": "bucket-name",
        ...
    }
    
    Returns:
    {
        "statusCode": 200,
        "s3_results": {
            "bucket": "processing-bucket",
            "detections_key": "symbols/image_123_symbols.json"
        },
        "summary": {
            "symbols_count": 97,
            "processing_time": "20250730_002236"
        }
    }
    """
    try:
        logger.info(f"Symbol Detection Lambda started")
        logger.info(f"Received event: {json.dumps(event, default=str)}")
        
        # Create execution path manager for consistent file organization
        path_manager = create_path_manager(event, context, OUTPUT_BUCKET)
        
        # Load configuration from S3
        config = get_config_from_s3(
            bucket=OUTPUT_BUCKET,
            config_key=event['config_s3_key']
        )
        
        # Get image information
        image_key = event['image_key']
        
        # Load image data - priority order:
        # 1. s3_image_uri (direct S3 URI, usually processed image)
        # 2. notes_processing_results (legacy format)
        # 3. input_bucket + image_key (original image)
        
        used_processed_image = False
        
        if 's3_image_uri' in event:
            # Direct S3 URI provided (preferred method)
            s3_image_uri = event['s3_image_uri']
            image_data = load_image_from_s3(s3_image_uri)
            used_processed_image = 'processed' in s3_image_uri or 'notes_removed' in s3_image_uri
            logger.info(f"Loaded image from provided S3 URI: {s3_image_uri}")
        elif 'notes_processing_results' in event:
            # Legacy format - check notes processing results
            notes_results = event['notes_processing_results']
            if isinstance(notes_results, dict) and 'Payload' in notes_results:
                payload = notes_results['Payload']
                if payload.get('statusCode') == 200 and payload.get('processed_key'):
                    processed_key = payload['processed_key']
                    image_data = load_image_from_s3_key(OUTPUT_BUCKET, processed_key)
                    used_processed_image = True
                    logger.info(f"Loaded processed image from notes results: s3://{OUTPUT_BUCKET}/{processed_key}")
                else:
                    # Fall back to original image
                    image_data = load_image_from_s3_key(INPUT_BUCKET, image_key)
                    logger.info(f"Loaded original image: s3://{INPUT_BUCKET}/{image_key}")
            else:
                # Fall back to original image
                image_data = load_image_from_s3_key(INPUT_BUCKET, image_key)
                logger.info(f"Loaded original image: s3://{INPUT_BUCKET}/{image_key}")
        else:
            # Fall back to original image from input bucket
            if not INPUT_BUCKET:
                raise ValueError("No image source available: missing s3_image_uri, notes_processing_results, or INPUT_BUCKET environment variable")
            image_data = load_image_from_s3_key(INPUT_BUCKET, image_key)
            logger.info(f"Loaded original image: s3://{INPUT_BUCKET}/{image_key}")
        
        # Get processing parameters from config
        score_threshold = config.get('symbol_detection', {}).get('score_threshold', 0.9)
        n_closest = config.get('symbol_detection', {}).get('n_closest', 3)
        
        logger.info(f"Processing image through SageMaker endpoint with score_threshold={score_threshold}, n_closest={n_closest}")
        
        # Process image through SageMaker
        start_time = datetime.now()
        detection_result = process_image(
            image_data=image_data,
            score_threshold=score_threshold,
            n_closest=n_closest
        )
        processing_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        logger.info(f"Detection completed: {detection_result['num_detections']} symbols detected")
        
        # Filter results if specified in config
        filter_classes = config.get('symbol_detection', {}).get('filter_classes')
        if filter_classes:
            detection_result = filter_detections_by_class(detection_result, filter_classes)
            logger.info(f"Filtered to {detection_result['num_detections']} symbols")
        
        # Transform coordinates to original image space if we used processed image
        coordinate_transformation_applied = False
        if used_processed_image and 'notes_processing_results' in event:
            try:
                logger.info("Applying coordinate transformation from processed to original space")
                
                # Extract transformation metadata from notes processor results
                transformation_metadata = get_transformation_metadata_from_notes_processor(
                    event['notes_processing_results']
                )
                
                # Transform symbol coordinates to original image space
                original_detections = transform_coordinates_to_original(
                    coordinates=detection_result.get('detections', []),
                    transformation_metadata=transformation_metadata,
                    coordinate_type="bounding_box"
                )
                
                # Validate transformation results
                validation_result = validate_transformation_result(
                    original_coords=detection_result.get('detections', []),
                    transformed_coords=original_detections,
                    transformation_metadata=transformation_metadata
                )
                
                # Update detection result with transformed coordinates
                detection_result['detections'] = original_detections
                detection_result['coordinate_transformation'] = {
                    'applied': True,
                    'validation': validation_result,
                    'metadata': transformation_metadata
                }
                coordinate_transformation_applied = True
                
                logger.info(f"Coordinate transformation completed: {validation_result['statistics']}")
                
            except Exception as e:
                logger.warning(f"Coordinate transformation failed, using processed coordinates: {str(e)}")
                detection_result['coordinate_transformation'] = {
                    'applied': False,
                    'error': str(e)
                }
        else:
            detection_result['coordinate_transformation'] = {
                'applied': False,
                'reason': 'No processed image or notes processing results available'
            }
        
        # Store results in S3 using execution-based path (now with transformed coordinates)
        results_s3_key = store_symbol_results_in_s3(
            detection_result, 
            path_manager
        )
        
        # Generate dual debug images (labeled and boxes-only) using shared utilities
        debug_images_generated = False
        debug_image_keys = {}
        try:
            debug_image_keys = generate_symbol_debug_image_pair(
                image_data=image_data,
                detections=detection_result.get('detections', []),
                path_manager=path_manager,
                title="Symbol Detection Debug"
            )
            debug_images_generated = True
            logger.info(f"Debug images generated successfully: labeled={debug_image_keys['labeled_key']}, boxes={debug_image_keys['boxes_key']}")
        except Exception as e:
            logger.warning(f"Debug images generation failed, continuing without debug images: {str(e)}")
            debug_images_generated = False
        
        # Prepare response with optional debug images
        response = {
            'statusCode': 200,
            's3_results': {
                'bucket': OUTPUT_BUCKET,
                'detections_key': results_s3_key
            },
            'summary': {
                'symbols_count': detection_result['num_detections'],
                'processing_time': processing_time,
                'score_threshold': score_threshold,
                'used_processed_image': used_processed_image,
                'debug_images_generated': debug_images_generated
            }
        }
        
        # Add debug image keys if generation was successful
        if debug_images_generated and debug_image_keys:
            response['s3_results']['debug_image_labeled_key'] = debug_image_keys['labeled_key']
            response['s3_results']['debug_image_boxes_key'] = debug_image_keys['boxes_key']
            # Backward compatibility
            response['s3_results']['debug_image_key'] = debug_image_keys['labeled_key']
        
        return response
        
    except Exception as e:
        logger.error(f"Error in Symbol Detection Lambda: {str(e)}", exc_info=True)
        
        return {
            'statusCode': 500,
            'error': f'Symbol detection failed: {str(e)}'
        }


def process_image(image_data: bytes, score_threshold: float = 0.5,
                  n_closest: int = 3) -> Dict[str, Any]:
    """
    Process an image through the SageMaker endpoint.
    
    Args:
        image_data: Raw image data as bytes
        confidence_threshold: Detection confidence threshold
        nms_threshold: Non-maximum suppression threshold
        
    Returns:
        Detection results in standard format
    """
    # Prepare payload for SageMaker
    payload = {
        'image': base64.b64encode(image_data).decode('utf-8'),
        'score_threshold': score_threshold,
        'n_closest': n_closest
    }
    
    logger.info(f"Invoking SageMaker endpoint: {ENDPOINT_NAME}")
    
    # Invoke SageMaker endpoint with timeout
    try:
        response = sagemaker_runtime.invoke_endpoint(
            EndpointName=ENDPOINT_NAME,
            ContentType='application/json',
            Accept='application/json',
            Body=json.dumps(payload)
        )
    except Exception as e:
        logger.error(f"SageMaker endpoint invocation failed: {str(e)}")
        raise
    
    # Parse response
    result = json.loads(response['Body'].read().decode())
    
    # Add num_detections field if missing (for backward compatibility)
    if 'detections' in result and 'num_detections' not in result:
        result['num_detections'] = len(result['detections'])
    
    return result


def load_image_from_s3(s3_uri: str) -> bytes:
    """
    Load image data from S3 URI.
    
    Args:
        s3_uri: S3 URI in format s3://bucket/key
        
    Returns:
        Image data as bytes
    """
    s3 = boto3.client('s3')
    
    # Parse S3 URI
    if not s3_uri.startswith('s3://'):
        raise ValueError(f"Invalid S3 URI format: {s3_uri}")
    
    parts = s3_uri[5:].split('/', 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid S3 URI format: {s3_uri}")
    
    bucket, key = parts
    
    # Download image from S3
    response = s3.get_object(Bucket=bucket, Key=key)
    return response['Body'].read()


def load_image_from_s3_key(bucket: str, key: str) -> bytes:
    """
    Load image data from S3 using bucket and key.
    
    Args:
        bucket: S3 bucket name
        key: S3 object key
        
    Returns:
        Image data as bytes
    """
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        return response['Body'].read()
    except Exception as e:
        logger.error(f"Failed to load image from s3://{bucket}/{key}: {str(e)}")
        raise


def store_symbol_results_in_s3(detection_result: Dict[str, Any], path_manager) -> str:
    """
    Store symbol detection results in S3 using execution-based path.
    
    Args:
        detection_result: Detection results from SageMaker
        path_manager: ExecutionPathManager for consistent file organization
        
    Returns:
        S3 key where results are stored
    """
    try:
        # Use ExecutionPathManager for consistent S3 key
        s3_key = path_manager.get_symbol_results_s3_key()
        
        # Store results in S3
        s3_client.put_object(
            Bucket=path_manager.output_bucket,
            Key=s3_key,
            Body=json.dumps(detection_result, indent=2),
            ContentType='application/json'
        )
        
        logger.info(f"Stored symbol detection results in S3: s3://{path_manager.output_bucket}/{s3_key}")
        return s3_key
        
    except Exception as e:
        logger.error(f"Failed to store symbol results in S3: {str(e)}")
        raise


def filter_detections_by_class(result: Dict[str, Any], filter_classes: List[int]) -> Dict[str, Any]:
    """
    Filter detections to only include specified classes.
    
    Args:
        result: Detection results from SageMaker
        filter_classes: List of class IDs to keep
        
    Returns:
        Filtered detection results
    """
    filtered_detections = []
    
    for detection in result['detections']:
        if detection['class_id'] in filter_classes:
            filtered_detections.append(detection)
    
    result['detections'] = filtered_detections
    result['num_detections'] = len(filtered_detections)
    
    return result
