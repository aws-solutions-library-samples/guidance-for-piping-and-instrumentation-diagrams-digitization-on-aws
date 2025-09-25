"""
Execution-based path generation utility for P&ID processing pipeline.

Provides standardized path generation for organizing files by Step Functions execution ID.
"""

import os
from typing import Dict, Any, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class ExecutionPathManager:
    """Manages execution-based file paths for the P&ID processing pipeline."""
    
    def __init__(self, execution_id: str, output_bucket: str):
        """
        Initialize path manager with execution context.
        
        Args:
            execution_id: Step Functions execution ID (from context or event)
            output_bucket: S3 bucket for all processing outputs
        """
        self.execution_id = execution_id
        self.output_bucket = output_bucket
        
        # Clean execution ID for use in paths (remove ARN parts if present)
        if ':' in execution_id:
            # Extract just the execution name from ARN
            self.clean_execution_id = execution_id.split(':')[-1]
        else:
            self.clean_execution_id = execution_id
            
        logger.info(f"Initialized ExecutionPathManager for execution: {self.clean_execution_id}")
    
    def get_base_path(self) -> str:
        """Get the base execution path."""
        return f"{self.clean_execution_id}"
    
    def get_config_path(self) -> str:
        """Get path for configuration files."""
        return f"{self.get_base_path()}/config"
    
    def get_input_path(self) -> str:
        """Get path for input files (copied from input bucket)."""
        return f"{self.get_base_path()}/input"
    
    def get_notes_processing_path(self) -> str:
        """Get path for notes processing outputs."""
        return f"{self.get_base_path()}/notes-processing"
    
    def get_text_detection_path(self) -> str:
        """Get path for text detection (OCR) outputs."""
        return f"{self.get_base_path()}/text-detection"
    
    def get_symbol_detection_path(self) -> str:
        """Get path for symbol detection outputs."""
        return f"{self.get_base_path()}/symbol-detection"
    
    def get_line_detection_path(self) -> str:
        """Get path for line detection outputs."""
        return f"{self.get_base_path()}/line-detection"
    
    def get_graph_generation_path(self) -> str:
        """Get path for graph generation outputs."""
        return f"{self.get_base_path()}/graph"
    
    def get_visualization_path(self) -> str:
        """Get path for visualization outputs."""
        return f"{self.get_base_path()}/visualization"
    
    def get_config_s3_key(self) -> str:
        """Get S3 key for the main processing configuration."""
        return f"{self.get_config_path()}/processing_config.json"
    
    def get_input_copy_s3_key(self, original_filename: str) -> str:
        """Get S3 key for input file copy."""
        return f"{self.get_input_path()}/{original_filename}"
    
    def get_processed_image_s3_key(self) -> str:
        """Get S3 key for processed image (after notes removal)."""
        return f"{self.get_notes_processing_path()}/processed_image.png"
    
    def get_notes_metadata_s3_key(self) -> str:
        """Get S3 key for notes processing metadata."""
        return f"{self.get_notes_processing_path()}/notes_metadata.json"
    
    def get_text_detection_results_s3_key(self) -> str:
        """Get S3 key for text detection results."""
        return f"{self.get_text_detection_path()}/text_detection_results.json"
    
    def get_bda_output_prefix(self) -> str:
        """Get S3 prefix for BDA outputs."""
        return f"{self.get_text_detection_path()}/bda_output"
    
    def get_symbol_results_s3_key(self) -> str:
        """Get S3 key for symbol detection results."""
        return f"{self.get_symbol_detection_path()}/detections.json"
    
    def get_symbol_debug_image_labeled_s3_key(self) -> str:
        """Get S3 key for symbol detection debug image with labels."""
        return f"{self.get_symbol_detection_path()}/debug_image_labeled.png"
    
    def get_symbol_debug_image_boxes_s3_key(self) -> str:
        """Get S3 key for symbol detection debug image with boxes only."""
        return f"{self.get_symbol_detection_path()}/debug_image_boxes.png"
    
    def get_symbol_debug_image_s3_key(self) -> str:
        """Get S3 key for symbol detection debug image (backward compatibility)."""
        return self.get_symbol_debug_image_labeled_s3_key()
    
    def get_text_debug_image_s3_key(self) -> str:
        """Get S3 key for text detection debug image."""
        return f"{self.get_text_detection_path()}/debug_image.png"
    
    def get_line_results_s3_key(self) -> str:
        """Get S3 key for line detection results."""
        return f"{self.get_line_detection_path()}/lines.json"
    
    def get_line_debug_prefix(self) -> str:
        """Get S3 prefix for line detection debug images."""
        return f"{self.get_line_detection_path()}/debug_images"
    
    def get_graph_data_s3_key(self) -> str:
        """Get S3 key for graph data JSON."""
        return f"{self.get_graph_generation_path()}/graph_data.json"
    
    def get_dexpi_s3_key(self) -> str:
        """Get S3 key for DEXPI XML output."""
        return f"{self.get_graph_generation_path()}/dexpi_output.xml"
    
    def get_visualization_s3_key(self) -> str:
        """Get S3 key for final visualization."""
        return f"{self.get_visualization_path()}/final_visualization.png"
    
    def get_execution_metadata_s3_key(self) -> str:
        """Get S3 key for execution metadata."""
        return f"{self.get_base_path()}/execution_metadata.json"
    
    def create_execution_metadata(self, image_key: str, stage: str, additional_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Create execution metadata object.
        
        Args:
            image_key: Original image key
            stage: Current processing stage
            additional_data: Additional metadata to include
            
        Returns:
            Metadata dictionary
        """
        metadata = {
            'execution_id': self.execution_id,
            'clean_execution_id': self.clean_execution_id,
            'output_bucket': self.output_bucket,
            'original_image_key': image_key,
            'current_stage': stage,
            'timestamp': datetime.utcnow().isoformat(),
            'paths': {
                'config': self.get_config_path(),
                'input': self.get_input_path(),
                'notes_processing': self.get_notes_processing_path(),
                'text_detection': self.get_text_detection_path(),
                'symbol_detection': self.get_symbol_detection_path(),
                'line_detection': self.get_line_detection_path(),
                'graph_generation': self.get_graph_generation_path(),
                'visualization': self.get_visualization_path()
            }
        }
        
        if additional_data:
            metadata.update(additional_data)
            
        return metadata

def get_execution_id_from_context(context) -> str:
    """
    Extract execution ID from Lambda context.
    
    Args:
        context: Lambda context object
        
    Returns:
        Execution ID string (fallback only - should not be used when Step Functions provides execution_id in event)
    """
    try:
        # DO NOT use Lambda request ID as it's unique per invocation
        # Instead generate a consistent fallback ID
        logger.warning("Generating fallback execution ID - Step Functions execution ID should be passed in event")
        timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
        return f"fallback-exec-{timestamp}"
    except Exception as e:
        logger.warning(f"Could not generate fallback execution ID: {e}")
        # Generate simple fallback ID
        timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
        return f"fallback-exec-{timestamp}"

def get_execution_id_from_event(event: Dict[str, Any]) -> Optional[str]:
    """
    Extract execution ID from event if available.
    
    Args:
        event: Lambda event object
        
    Returns:
        Execution ID if found in event, None otherwise
    """
    try:
        # Check if execution_id is directly in event
        if 'execution_id' in event:
            return event['execution_id']
        
        # Check if it's in Step Functions context
        if '_execution_id' in event:
            return event['_execution_id']
            
        return None
    except Exception as e:
        logger.warning(f"Could not extract execution ID from event: {e}")
        return None

def create_path_manager(event: Dict[str, Any], context, output_bucket: str) -> ExecutionPathManager:
    """
    Create ExecutionPathManager from Lambda event and context.
    
    Args:
        event: Lambda event
        context: Lambda context
        output_bucket: S3 output bucket name
        
    Returns:
        Configured ExecutionPathManager
    """
    # Try to get execution ID from event first, then context
    execution_id = get_execution_id_from_event(event)
    if not execution_id:
        execution_id = get_execution_id_from_context(context)
    
    return ExecutionPathManager(execution_id, output_bucket)
