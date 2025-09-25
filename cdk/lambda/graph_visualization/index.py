import json
import logging
import os
import traceback
from typing import Dict, Any

import boto3

from execution_paths import create_path_manager
from visualization import GraphVisualizer

logger = logging.getLogger()
log_level = os.environ.get('LOG_LEVEL', 'INFO')
logger.setLevel(getattr(logging, log_level.upper()))

s3 = boto3.client('s3')

# Get environment variables
OUTPUT_BUCKET = os.environ.get('OUTPUT_BUCKET')

def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Graph Visualization Lambda function.
    
    Takes graph data from S3 and generates two separate PNG visualizations:
    1. Physical layout visualization
    2. Graph representation visualization
    """
    
    try:
        logger.info(f"Graph visualization Lambda invoked with event: {json.dumps(event)}")
        
        # Extract parameters from event
        graph_data_s3_key = event.get('graph_data_s3_key')
        image_key = event.get('image_key')
        
        # Extract optional notes information from notes processor (for physical layout)
        notes_coordinates = event.get('notes_coordinates')
        
        if not all([graph_data_s3_key, OUTPUT_BUCKET, image_key]):
            raise ValueError("Missing required parameters: graph_data_s3_key, OUTPUT_BUCKET, image_key")
        
        # Create execution path manager for consistent file organization
        path_manager = create_path_manager(event, context, OUTPUT_BUCKET)
        
        logger.info(f"Generating visualizations for graph data: {graph_data_s3_key}")
        if notes_coordinates:
            logger.info(f"Notes cutting area information provided: {notes_coordinates}")
        
        # Download graph data from S3
        graph_data = download_graph_data_from_s3(OUTPUT_BUCKET, graph_data_s3_key)
        
        # Generate all visualizations
        visualizer = GraphVisualizer()
        visualizations = visualizer.create_all_visualizations(graph_data, notes_info=notes_coordinates)
        
        if not visualizations:
            logger.warning("No visualizations could be generated")
            return {
                'statusCode': 200,
                'visualizations_generated': {},
                'message': 'No visualizations could be generated',
                'success': False
            }
        
        # Save all visualizations to S3
        output_keys = {}
        for viz_type, viz_bytes in visualizations.items():
            if viz_bytes:
                output_key = save_individual_visualization_to_s3(path_manager, image_key, viz_type, viz_bytes)
                output_keys[viz_type] = output_key
                logger.info(f"Successfully saved {viz_type} visualization to: {output_key}")
        
        logger.info(f"Generated {len(output_keys)} visualizations: {list(output_keys.keys())}")
        
        return {
            'statusCode': 200,
            'visualizations_generated': output_keys,
            'message': f'Successfully generated {len(output_keys)} visualizations',
            'success': True
        }
        
    except Exception as e:
        logger.error(f"Error in graph visualization: {str(e)}")
        logger.error(traceback.format_exc())
        
        return {
            'statusCode': 500,
            'error': str(e),
            'visualizations_generated': {},
            'success': False
        }


def download_graph_data_from_s3(bucket: str, key: str) -> Dict[str, Any]:
    """
    Download graph data JSON from S3.
    """
    try:
        logger.info(f"Downloading graph data from s3://{bucket}/{key}")
        
        response = s3.get_object(Bucket=bucket, Key=key)
        graph_data = json.loads(response['Body'].read().decode('utf-8'))
        
        logger.info(f"Successfully downloaded graph data with {len(graph_data.get('symbols', []))} symbols, "
                   f"{len(graph_data.get('lines', []))} lines")
        
        return graph_data
        
    except Exception as e:
        logger.error(f"Error downloading graph data from S3: {str(e)}")
        raise




def save_individual_visualization_to_s3(path_manager, image_key: str, viz_type: str, visualization_bytes: bytes) -> str:
    """
    Save individual visualization PNG to S3 output bucket using execution-based paths.
    """
    try:
        # Use ExecutionPathManager for consistent S3 key
        viz_key = f"{path_manager.get_visualization_path()}/{viz_type}.png"
        
        # Upload to S3
        s3.put_object(
            Bucket=path_manager.output_bucket,
            Key=viz_key,
            Body=visualization_bytes,
            ContentType='image/png'
        )
        
        logger.info(f"Saved {viz_type} visualization to s3://{path_manager.output_bucket}/{viz_key}")
        return viz_key
        
    except Exception as e:
        logger.error(f"Error saving {viz_type} visualization to S3: {str(e)}")
        raise
