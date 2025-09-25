import boto3
import os
import json
import logging
from typing import Dict, Any
from config_validator import ConfigValidator
from config_helper import store_results_in_s3
from execution_paths import create_path_manager

# Set up logging
logger = logging.getLogger()
log_level = os.environ.get('LOG_LEVEL', 'INFO')
logger.setLevel(getattr(logging, log_level.upper()))

# Initialize AWS clients
s3_client = boto3.client('s3')

# Initialize config validator
config_validator = ConfigValidator()

# Environment variables
INPUT_BUCKET = os.environ.get('INPUT_BUCKET')
OUTPUT_BUCKET = os.environ.get('OUTPUT_BUCKET')
SAGEMAKER_ENDPOINT_NAME = os.environ.get('SAGEMAKER_ENDPOINT_NAME')

def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Input validator Lambda function.
    
    Validates uploaded P&ID files when invoked by Step Functions.
    Uses execution-based file organization for all processing artifacts.
    """
    
    try:
        # Extract S3 information from the event
        bucket_name = None
        object_key = None
        manual_coordinates = None
        
        if 'input_bucket' in event and 'image_key' in event:
            bucket_name = event['input_bucket']
            object_key = event['image_key']
            manual_coordinates = event.get('manual_coordinates')
        elif 'image_key' in event:
            bucket_name = INPUT_BUCKET
            object_key = event['image_key']
            manual_coordinates = event.get('manual_coordinates')
        else:
            raise ValueError("Unable to extract S3 bucket and key from event")
        
        logger.info(f"Validating file: bucket={bucket_name}, key={object_key}")
        if manual_coordinates:
            logger.info(f"Manual coordinates provided: {manual_coordinates}")
        
        # Create execution path manager for organizing files
        path_manager = create_path_manager(event, context, OUTPUT_BUCKET)
        logger.info(f"Using execution ID: {path_manager.clean_execution_id}")
        
        # Validate the file
        validation_result = validate_file(bucket_name, object_key)
        
        if not validation_result['valid']:
            raise ValueError(f"File validation failed: {validation_result['error']}")
        
        # Validate and merge processing configuration with defaults
        user_processing_config = event.get('processing_config', {})
        validated_processing_config = validate_processing_config(user_processing_config)
        
        # Store validated configuration using execution-based path
        config_s3_key = path_manager.get_config_s3_key()
        store_results_in_s3(OUTPUT_BUCKET, config_s3_key, validated_processing_config)
        logger.info(f"Stored validated config in S3: s3://{OUTPUT_BUCKET}/{config_s3_key}")
        
        # Copy input file to execution directory for reference
        input_filename = os.path.basename(object_key)
        input_copy_s3_key = path_manager.get_input_copy_s3_key(input_filename)
        copy_file_to_execution_location(bucket_name, object_key, OUTPUT_BUCKET, input_copy_s3_key)
        logger.info(f"Copied input file to execution location: s3://{OUTPUT_BUCKET}/{input_copy_s3_key}")
        
        # Create and store execution metadata
        execution_metadata = path_manager.create_execution_metadata(
            image_key=object_key,
            stage='input_validation',
            additional_data={
                'file_metadata': validation_result['metadata'],
                'manual_coordinates': manual_coordinates,
                'sagemaker_endpoint_name': SAGEMAKER_ENDPOINT_NAME,
                'input_bucket': bucket_name,
                'original_key': object_key
            }
        )
        metadata_s3_key = path_manager.get_execution_metadata_s3_key()
        store_results_in_s3(OUTPUT_BUCKET, metadata_s3_key, execution_metadata)
        
        # Build minimal response with execution-based paths
        response = {
            'statusCode': 200,
            'execution_id': path_manager.execution_id,
            'image_key': object_key,
            'original_key': object_key,
            'input_bucket': bucket_name,
            'output_bucket': OUTPUT_BUCKET,
            'config_s3_key': config_s3_key,
            'input_copy_s3_key': input_copy_s3_key,
            'execution_metadata_s3_key': metadata_s3_key,
            'sagemaker_endpoint_name': SAGEMAKER_ENDPOINT_NAME,
            'file_metadata': validation_result['metadata']
        }
        
        # Include manual coordinates if provided (legacy support)
        if manual_coordinates:
            response['manual_coordinates'] = manual_coordinates
            logger.info(f"Passing through manual coordinates: {manual_coordinates}")
        
        return response
            
    except Exception as e:
        logger.error(f"Error in input validator: {str(e)}")
        return {
            'statusCode': 500,
            'error': str(e)
        }

def validate_file(bucket_name: str, object_key: str) -> Dict[str, Any]:
    """
    Validate the uploaded file.
    
    Checks:
    - File exists and is accessible
    - File size is reasonable (< 50MB)
    - File type is supported (jpg, png, pdf)
    """
    
    try:
        # Get object metadata
        response = s3_client.head_object(Bucket=bucket_name, Key=object_key)
        
        file_size = response['ContentLength']
        last_modified = response['LastModified']
        content_type = response.get('ContentType', '')
        
        logger.info(f"File info: size={file_size}, type={content_type}")
        
        # Check file size (50MB limit)
        if file_size > 50 * 1024 * 1024:
            return {
                'valid': False,
                'error': f'File too large: {file_size} bytes (max 50MB)'
            }
        
        # Check file type
        file_extension = object_key.lower().split('.')[-1]
        supported_extensions = ['jpg', 'jpeg', 'png', 'pdf']
        
        if file_extension not in supported_extensions:
            return {
                'valid': False,
                'error': f'Unsupported file type: {file_extension}'
            }
        
        return {
            'valid': True,
            'metadata': {
                'file_size': file_size,
                'content_type': content_type,
                'last_modified': last_modified.isoformat(),
                'file_extension': file_extension
            }
        }
        
    except Exception as e:
        return {
            'valid': False,
            'error': f'Error accessing file: {str(e)}'
        }

def copy_file_to_execution_location(source_bucket: str, source_key: str, target_bucket: str, target_key: str) -> None:
    """Copy file from source location to execution-based location."""
    
    logger.info(f"Copying s3://{source_bucket}/{source_key} to s3://{target_bucket}/{target_key}")
    
    # Copy object
    copy_source = {
        'Bucket': source_bucket,
        'Key': source_key
    }
    
    s3_client.copy_object(
        CopySource=copy_source,
        Bucket=target_bucket,
        Key=target_key
    )

def validate_processing_config(user_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate and merge user processing configuration with defaults.
    This centralizes all configuration validation in one place.
    
    Args:
        user_config: User-provided processing configuration overrides
        
    Returns:
        Complete validated configuration with all stages (notes_processing, line_detection, etc.)
    """
    
    # Load default configuration for all stages
    default_config = config_validator.load_default_config()
    
    # List of processing stages to validate
    stages = ['notes_processing', 'line_detection', 'graph_generation', 'text_detection', 'symbol_detection', 'graph_visualization']
    
    validated_config = {}
    
    # Validate each stage
    for stage in stages:
        try:
            # Get user overrides for this stage (if any)
            stage_overrides = user_config.get(stage, {})
            
            # Get validated config for this stage
            validated_stage_config = config_validator.get_merged_config(stage, stage_overrides)
            validated_config[stage] = validated_stage_config
            
            logger.info(f"Validated {stage} config: {len(stage_overrides)} overrides applied")
            
        except Exception as e:
            logger.error(f"Error validating {stage} config: {str(e)}")
            # Use defaults for this stage if validation fails
            validated_config[stage] = default_config.get(stage, {})
    
    return validated_config
