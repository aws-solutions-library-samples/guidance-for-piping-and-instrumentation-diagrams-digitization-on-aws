import boto3
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)
s3 = boto3.client('s3')

def get_config_from_s3(bucket: str, config_key: str) -> Dict[str, Any]:
    """
    Read and parse configuration from S3.
    
    Args:
        bucket: S3 bucket name containing the configuration
        config_key: S3 key for the configuration file
        
    Returns:
        Dictionary containing the parsed configuration
        
    Raises:
        Exception: If configuration cannot be read or parsed
    """
    try:
        logger.info(f"Reading config from s3://{bucket}/{config_key}")
        response = s3.get_object(Bucket=bucket, Key=config_key)
        config = json.loads(response['Body'].read().decode('utf-8'))
        logger.info("Successfully loaded config from S3")
        return config
    except Exception as e:
        logger.error(f"Failed to read config from S3: {str(e)}")
        raise Exception(f"Config read error: {str(e)}")

def get_lambda_config(event: Dict[str, Any], config_section: str) -> Dict[str, Any]:
    """
    Get specific config section for a Lambda function.
    
    Args:
        event: Lambda event containing bucket and config_s3_key
        config_section: Name of the configuration section to retrieve
        
    Returns:
        Dictionary containing the requested configuration section
    """
    # Use output bucket for all configurations now
    bucket = event.get('output_bucket') or event.get('processing_bucket') or event.get('buckets', {}).get('output')
    config_key = event.get('config_s3_key')
    
    if not bucket or not config_key:
        raise Exception("Missing output_bucket or config_s3_key in event")
    
    full_config = get_config_from_s3(bucket, config_key)
    return full_config.get(config_section, {})

def read_s3_json(bucket: str, key: str) -> Dict[str, Any]:
    """
    Read JSON data from S3.
    
    Args:
        bucket: S3 bucket name
        key: S3 key for the JSON file
        
    Returns:
        Dictionary containing the parsed JSON data
        
    Raises:
        Exception: If JSON cannot be read or parsed
    """
    try:
        logger.info(f"Reading JSON from s3://{bucket}/{key}")
        response = s3.get_object(Bucket=bucket, Key=key)
        data = json.loads(response['Body'].read().decode('utf-8'))
        logger.info("Successfully loaded JSON from S3")
        return data
    except Exception as e:
        logger.error(f"Failed to read JSON from s3://{bucket}/{key}: {str(e)}")
        raise Exception(f"S3 JSON read error: {str(e)}")

def store_results_in_s3(bucket: str, key: str, data: Dict[str, Any]) -> str:
    """
    Store results data in S3 as JSON.
    
    Args:
        bucket: S3 bucket name
        key: S3 key for storing the data
        data: Dictionary to store as JSON
        
    Returns:
        The S3 key where data was stored
    """
    try:
        logger.info(f"Storing results to s3://{bucket}/{key}")
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(data, indent=2),
            ContentType="application/json"
        )
        logger.info("Successfully stored results in S3")
        return key
    except Exception as e:
        logger.error(f"Failed to store results in S3: {str(e)}")
        raise Exception(f"S3 storage error: {str(e)}")
