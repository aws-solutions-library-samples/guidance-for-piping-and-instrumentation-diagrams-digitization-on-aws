"""
Coordinate transformation utilities for converting between processed and original image spaces.

This module provides functions to transform coordinates between different image spaces:
- Original image space (input image)
- Processed image space (after notes/frame removal)
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


def transform_coordinates_to_original(
    coordinates: List[Dict[str, Any]],
    transformation_metadata: Dict[str, Any],
    coordinate_type: str = "bounding_box"
) -> List[Dict[str, Any]]:
    """
    Transform coordinates from processed image space to original image space.
    
    Args:
        coordinates: List of coordinate objects to transform
        transformation_metadata: Metadata from notes processor containing transformation info
        coordinate_type: Type of coordinates ("bounding_box" for symbols, "line" for lines)
        
    Returns:
        List of transformed coordinates in original image space
    """
    
    try:
        logger.info(f"Transforming {len(coordinates)} {coordinate_type} coordinates to original space")
        
        # Extract transformation parameters
        frame_info = transformation_metadata.get('frame_info', {})
        manual_coordinates = transformation_metadata.get('manual_coordinates')
        notes_coordinates = transformation_metadata.get('notes_coordinates')
        processing_mode = transformation_metadata.get('processing_mode', 'auto')
        
        # Get image dimensions for validation
        original_dims = transformation_metadata.get('original_image_dimensions', {})
        processed_dims = transformation_metadata.get('processed_image_dimensions', {})
        
        logger.info(f"Processing mode: {processing_mode}")
        logger.info(f"Original dimensions: {original_dims}")
        logger.info(f"Processed dimensions: {processed_dims}")
        
        transformed_coordinates = []
        
        for coord in coordinates:
            if coordinate_type == "bounding_box":
                transformed_coord = _transform_bounding_box(
                    coord, frame_info, manual_coordinates, notes_coordinates, processing_mode
                )
            elif coordinate_type == "line":
                transformed_coord = _transform_line_coordinates(
                    coord, frame_info, manual_coordinates, notes_coordinates, processing_mode, transformation_metadata
                )
            else:
                logger.warning(f"Unknown coordinate type: {coordinate_type}")
                transformed_coord = coord.copy()
            
            transformed_coordinates.append(transformed_coord)
        
        logger.info(f"Successfully transformed {len(transformed_coordinates)} coordinates")
        return transformed_coordinates
        
    except Exception as e:
        logger.error(f"Error transforming coordinates: {str(e)}")
        # Return original coordinates on error
        return coordinates


def _transform_bounding_box(
    bbox: Dict[str, Any],
    frame_info: Dict[str, Any],
    manual_coordinates: Optional[Dict[str, Any]],
    notes_coordinates: Optional[Dict[str, Any]],
    processing_mode: str
) -> Dict[str, Any]:
    """
    Transform a bounding box from processed space to original space.
    
    Args:
        bbox: Bounding box with x1, y1, x2, y2 or x, y, width, height
        frame_info: Frame removal information
        manual_coordinates: Manual crop coordinates if used
        notes_coordinates: Auto-detected notes coordinates if used
        processing_mode: Processing mode (auto, manual, etc.)
        
    Returns:
        Transformed bounding box in original image space
    """
    
    transformed_bbox = bbox.copy()
    
    # Handle different bounding box formats
    if 'bbox' in bbox:
        # Symbol detection format
        inner_bbox = bbox['bbox'].copy()
        x1, y1 = inner_bbox.get('x1', 0), inner_bbox.get('y1', 0)
        x2, y2 = inner_bbox.get('x2', 0), inner_bbox.get('y2', 0)
    elif all(k in bbox for k in ['x', 'y', 'width', 'height']):
        # OCR format - convert to x1, y1, x2, y2
        x1, y1 = bbox['x'], bbox['y']
        x2, y2 = x1 + bbox['width'], y1 + bbox['height']
        inner_bbox = {'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2}
    else:
        logger.warning(f"Unknown bounding box format: {list(bbox.keys())}")
        return transformed_bbox
    
    # Apply transformations in reverse order of processing
    
    # 1. Manual coordinates transformation (if manual mode was used)
    if manual_coordinates and processing_mode in ["manual", "manual_failed"]:
        manual_x = manual_coordinates.get('x', 0)
        manual_y = manual_coordinates.get('y', 0)
        
        x1 += manual_x
        y1 += manual_y
        x2 += manual_x
        y2 += manual_y
        
        logger.debug(f"Applied manual offset: ({manual_x}, {manual_y})")
    
    # 2. Notes coordinates transformation (if auto notes removal was applied)
    elif notes_coordinates and processing_mode == "auto":
        # Notes are typically removed from the right side, no coordinate translation needed
        # The coordinates in processed space are already correct relative to the cropped image
        pass
    
    # 3. Frame removal transformation (add frame offset back)
    if frame_info.get('frame_removed', False):
        frame_bounds = frame_info.get('frame_bounds', {})
        frame_left = frame_bounds.get('left', 0)
        frame_top = frame_bounds.get('top', 0)
        
        x1 += frame_left
        y1 += frame_top
        x2 += frame_left
        y2 += frame_top
        
        logger.debug(f"Applied frame offset: ({frame_left}, {frame_top})")
    
    # Update the transformed coordinates
    if 'bbox' in bbox:
        # Symbol detection format
        transformed_bbox['bbox']['x1'] = int(x1)
        transformed_bbox['bbox']['y1'] = int(y1)
        transformed_bbox['bbox']['x2'] = int(x2)
        transformed_bbox['bbox']['y2'] = int(y2)
        # Also update width/height if present
        transformed_bbox['bbox']['width'] = int(x2 - x1)
        transformed_bbox['bbox']['height'] = int(y2 - y1)
    else:
        # Convert back to x, y, width, height format
        transformed_bbox['x'] = int(x1)
        transformed_bbox['y'] = int(y1)
        transformed_bbox['width'] = int(x2 - x1)
        transformed_bbox['height'] = int(y2 - y1)
    
    return transformed_bbox


def _transform_line_coordinates(
    line: Dict[str, Any],
    frame_info: Dict[str, Any],
    manual_coordinates: Optional[Dict[str, Any]],
    notes_coordinates: Optional[Dict[str, Any]],
    processing_mode: str,
    transformation_metadata: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Transform line coordinates from processed space to original space.
    
    Args:
        line: Line with startX, startY, endX, endY (normalized 0-1 coordinates)
        frame_info: Frame removal information
        manual_coordinates: Manual crop coordinates if used
        notes_coordinates: Auto-detected notes coordinates if used
        processing_mode: Processing mode (auto, manual, etc.)
        transformation_metadata: Full transformation metadata containing image dimensions
        
    Returns:
        Transformed line coordinates in original image space
    """
    
    transformed_line = line.copy()
    
    # Get processed and original image dimensions for coordinate scaling
    # Try multiple locations for image dimensions
    processed_dims = None
    original_dims = None
    
    if transformation_metadata:
        processed_dims = transformation_metadata.get('processed_image_dimensions')
        original_dims = transformation_metadata.get('original_image_dimensions')
    
    if not processed_dims or not original_dims:
        processed_dims = frame_info.get('processed_image_dimensions')
        original_dims = frame_info.get('original_image_dimensions')
    
    if not processed_dims or not original_dims:
        logger.warning("Missing image dimensions for line coordinate transformation")
        return transformed_line
    
    processed_width = processed_dims.get('width', 1)
    processed_height = processed_dims.get('height', 1)
    original_width = original_dims.get('width', 1)
    original_height = original_dims.get('height', 1)
    
    # Convert normalized coordinates to pixel coordinates in processed space
    start_x_pixel = line.get('startX', 0) * processed_width
    start_y_pixel = line.get('startY', 0) * processed_height
    end_x_pixel = line.get('endX', 0) * processed_width
    end_y_pixel = line.get('endY', 0) * processed_height
    
    # Apply transformations in reverse order of processing
    
    # 1. Manual coordinates transformation (if manual mode was used)
    if manual_coordinates and processing_mode in ["manual", "manual_failed"]:
        manual_x = manual_coordinates.get('x', 0)
        manual_y = manual_coordinates.get('y', 0)
        
        start_x_pixel += manual_x
        start_y_pixel += manual_y
        end_x_pixel += manual_x
        end_y_pixel += manual_y
        
        logger.debug(f"Applied manual offset to line: ({manual_x}, {manual_y})")
    
    # 2. Notes coordinates transformation (if auto notes removal was applied)
    elif notes_coordinates and processing_mode == "auto":
        # Notes are typically removed from the right side, no coordinate translation needed
        pass
    
    # 3. Frame removal transformation (add frame offset back)
    if frame_info.get('frame_removed', False):
        frame_bounds = frame_info.get('frame_bounds', {})
        frame_left = frame_bounds.get('left', 0)
        frame_top = frame_bounds.get('top', 0)
        
        start_x_pixel += frame_left
        start_y_pixel += frame_top
        end_x_pixel += frame_left
        end_y_pixel += frame_top
        
        logger.debug(f"Applied frame offset to line: ({frame_left}, {frame_top})")
    
    # Convert back to normalized coordinates in original image space
    transformed_line['startX'] = start_x_pixel / original_width
    transformed_line['startY'] = start_y_pixel / original_height
    transformed_line['endX'] = end_x_pixel / original_width
    transformed_line['endY'] = end_y_pixel / original_height
    
    # Ensure coordinates stay within valid range [0, 1]
    transformed_line['startX'] = max(0, min(1, transformed_line['startX']))
    transformed_line['startY'] = max(0, min(1, transformed_line['startY']))
    transformed_line['endX'] = max(0, min(1, transformed_line['endX']))
    transformed_line['endY'] = max(0, min(1, transformed_line['endY']))
    
    return transformed_line


def get_transformation_metadata_from_notes_processor(notes_processor_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract transformation metadata from notes processor result for coordinate transformation.
    
    Args:
        notes_processor_result: Result from notes processor Lambda
        
    Returns:
        Dictionary containing transformation metadata
    """
    
    try:
        payload = notes_processor_result.get('Payload', notes_processor_result)
        
        return {
            'frame_info': payload.get('frame_info', {}),
            'manual_coordinates': payload.get('coordinates_used'),
            'notes_coordinates': payload.get('notes_coordinates'),
            'processing_mode': payload.get('processing_mode', 'auto'),
            'original_image_dimensions': payload.get('original_image_dimensions', {}),
            'processed_image_dimensions': payload.get('processed_image_dimensions', {}),
        }
        
    except Exception as e:
        logger.error(f"Error extracting transformation metadata: {str(e)}")
        return {}


def transform_coordinates_to_processed(
    coordinates: List[Dict[str, Any]],
    transformation_metadata: Dict[str, Any],
    coordinate_type: str = "bounding_box"
) -> List[Dict[str, Any]]:
    """
    Transform coordinates from original image space to processed image space.
    This is the reverse of transform_coordinates_to_original.
    
    Args:
        coordinates: List of coordinate objects to transform (in original space)
        transformation_metadata: Metadata from notes processor containing transformation info
        coordinate_type: Type of coordinates ("bounding_box" for symbols/text, "line" for lines)
        
    Returns:
        List of transformed coordinates in processed image space
    """
    
    try:
        logger.info(f"Transforming {len(coordinates)} {coordinate_type} coordinates to processed space")
        
        # Extract transformation parameters
        frame_info = transformation_metadata.get('frame_info', {})
        manual_coordinates = transformation_metadata.get('manual_coordinates')
        notes_coordinates = transformation_metadata.get('notes_coordinates')
        processing_mode = transformation_metadata.get('processing_mode', 'auto')
        
        # Get image dimensions for validation
        original_dims = transformation_metadata.get('original_image_dimensions', {})
        processed_dims = transformation_metadata.get('processed_image_dimensions', {})
        
        logger.info(f"Processing mode: {processing_mode}")
        logger.info(f"Original dimensions: {original_dims}")
        logger.info(f"Processed dimensions: {processed_dims}")
        
        # Check if transformation is actually needed
        frame_removed = frame_info.get('frame_removed', False)
        dimensions_changed = (
            original_dims.get('width') != processed_dims.get('width') or 
            original_dims.get('height') != processed_dims.get('height')
        )
        has_manual_coords = manual_coordinates is not None and processing_mode in ["manual", "manual_failed"]
        has_notes_coords = notes_coordinates is not None and processing_mode == "auto"
        
        if not (frame_removed or dimensions_changed or has_manual_coords or has_notes_coords):
            logger.info("No coordinate transformation needed - image dimensions and processing parameters unchanged")
            return coordinates
        
        logger.info(f"Applying transformation: frame_removed={frame_removed}, dimensions_changed={dimensions_changed}, "
                   f"has_manual_coords={has_manual_coords}, has_notes_coords={has_notes_coords}")
        
        transformed_coordinates = []
        
        for coord in coordinates:
            if coordinate_type == "bounding_box":
                transformed_coord = _transform_bounding_box_to_processed(
                    coord, frame_info, manual_coordinates, notes_coordinates, processing_mode
                )
            elif coordinate_type == "line":
                transformed_coord = _transform_line_coordinates_to_processed(
                    coord, frame_info, manual_coordinates, notes_coordinates, processing_mode
                )
            else:
                logger.warning(f"Unknown coordinate type: {coordinate_type}")
                transformed_coord = coord.copy()
            
            transformed_coordinates.append(transformed_coord)
        
        logger.info(f"Successfully transformed {len(transformed_coordinates)} coordinates to processed space")
        return transformed_coordinates
        
    except Exception as e:
        logger.error(f"Error transforming coordinates to processed space: {str(e)}")
        # Return original coordinates on error
        return coordinates


def _transform_bounding_box_to_processed(
    bbox: Dict[str, Any],
    frame_info: Dict[str, Any],
    manual_coordinates: Optional[Dict[str, Any]],
    notes_coordinates: Optional[Dict[str, Any]],
    processing_mode: str
) -> Dict[str, Any]:
    """
    Transform a bounding box from original space to processed space.
    This is the reverse of _transform_bounding_box.
    """
    
    transformed_bbox = bbox.copy()
    
    # Handle different bounding box formats
    if 'bbox' in bbox:
        # Symbol detection format: {'bbox': {'x1': ..., 'y1': ..., 'x2': ..., 'y2': ...}}
        inner_bbox = bbox['bbox'].copy()
        x1, y1 = inner_bbox.get('x1', 0), inner_bbox.get('y1', 0)
        x2, y2 = inner_bbox.get('x2', 0), inner_bbox.get('y2', 0)
    elif 'bounding_box' in bbox:
        # OCR format: {'text': '...', 'bounding_box': {'x': ..., 'y': ..., 'width': ..., 'height': ...}}
        inner_bbox = bbox['bounding_box'].copy()
        x1, y1 = inner_bbox.get('x', 0), inner_bbox.get('y', 0)
        width, height = inner_bbox.get('width', 0), inner_bbox.get('height', 0)
        x2, y2 = x1 + width, y1 + height
    elif all(k in bbox for k in ['x', 'y', 'width', 'height']):
        # Direct format: {'x': ..., 'y': ..., 'width': ..., 'height': ...}
        x1, y1 = bbox['x'], bbox['y']
        x2, y2 = x1 + bbox['width'], y1 + bbox['height']
        inner_bbox = {'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2}
    else:
        logger.warning(f"Unknown bounding box format: {list(bbox.keys())}")
        return transformed_bbox
    
    # Apply reverse transformations in forward order of processing
    
    # 1. Frame removal transformation (subtract frame offset)
    if frame_info.get('frame_removed', False):
        frame_bounds = frame_info.get('frame_bounds', {})
        frame_left = frame_bounds.get('left', 0)
        frame_top = frame_bounds.get('top', 0)
        
        x1 -= frame_left
        y1 -= frame_top
        x2 -= frame_left
        y2 -= frame_top
        
        logger.debug(f"Applied reverse frame offset: (-{frame_left}, -{frame_top})")
    
    # 2. Notes coordinates transformation (if auto notes removal was applied)
    if notes_coordinates and processing_mode == "auto":
        # Notes removal typically crops from right side, coordinates may need adjustment
        # For most cases, no transformation needed since notes are removed from right
        pass
    
    # 3. Manual coordinates transformation (if manual mode was used)
    elif manual_coordinates and processing_mode in ["manual", "manual_failed"]:
        manual_x = manual_coordinates.get('x', 0)
        manual_y = manual_coordinates.get('y', 0)
        
        x1 -= manual_x
        y1 -= manual_y
        x2 -= manual_x
        y2 -= manual_y
        
        logger.debug(f"Applied reverse manual offset: (-{manual_x}, -{manual_y})")
    
    # Update the transformed coordinates
    if 'bbox' in bbox:
        # Symbol detection format
        transformed_bbox['bbox']['x1'] = int(max(0, x1))
        transformed_bbox['bbox']['y1'] = int(max(0, y1))
        transformed_bbox['bbox']['x2'] = int(x2)
        transformed_bbox['bbox']['y2'] = int(y2)
        # Also update width/height if present
        transformed_bbox['bbox']['width'] = int(max(0, x2 - x1))
        transformed_bbox['bbox']['height'] = int(max(0, y2 - y1))
    elif 'bounding_box' in bbox:
        # OCR format - update nested bounding_box structure
        transformed_bbox['bounding_box']['x'] = int(max(0, x1))
        transformed_bbox['bounding_box']['y'] = int(max(0, y1))
        transformed_bbox['bounding_box']['width'] = int(max(0, x2 - x1))
        transformed_bbox['bounding_box']['height'] = int(max(0, y2 - y1))
    else:
        # Direct format - update top-level keys
        transformed_bbox['x'] = int(max(0, x1))
        transformed_bbox['y'] = int(max(0, y1))
        transformed_bbox['width'] = int(max(0, x2 - x1))
        transformed_bbox['height'] = int(max(0, y2 - y1))
    
    return transformed_bbox


def _transform_line_coordinates_to_processed(
    line: Dict[str, Any],
    frame_info: Dict[str, Any],
    manual_coordinates: Optional[Dict[str, Any]],
    notes_coordinates: Optional[Dict[str, Any]],
    processing_mode: str
) -> Dict[str, Any]:
    """
    Transform line coordinates from original space to processed space.
    This is the reverse of _transform_line_coordinates.
    """
    
    transformed_line = line.copy()
    
    # Get processed and original image dimensions for coordinate scaling
    processed_dims = frame_info.get('processed_image_dimensions')
    original_dims = frame_info.get('original_image_dimensions')
    
    if not processed_dims or not original_dims:
        logger.warning("Missing image dimensions for reverse line coordinate transformation")
        return transformed_line
    
    processed_width = processed_dims.get('width', 1)
    processed_height = processed_dims.get('height', 1)
    original_width = original_dims.get('width', 1)
    original_height = original_dims.get('height', 1)
    
    # Convert normalized coordinates to pixel coordinates in original space
    start_x_pixel = line.get('startX', 0) * original_width
    start_y_pixel = line.get('startY', 0) * original_height
    end_x_pixel = line.get('endX', 0) * original_width
    end_y_pixel = line.get('endY', 0) * original_height
    
    # Apply reverse transformations in forward order of processing
    
    # 1. Frame removal transformation (subtract frame offset)
    if frame_info.get('frame_removed', False):
        frame_bounds = frame_info.get('frame_bounds', {})
        frame_left = frame_bounds.get('left', 0)
        frame_top = frame_bounds.get('top', 0)
        
        start_x_pixel -= frame_left
        start_y_pixel -= frame_top
        end_x_pixel -= frame_left
        end_y_pixel -= frame_top
        
        logger.debug(f"Applied reverse frame offset to line: (-{frame_left}, -{frame_top})")
    
    # 2. Notes coordinates transformation (if auto notes removal was applied)
    if notes_coordinates and processing_mode == "auto":
        # Notes removal, coordinates may need adjustment
        pass
    
    # 3. Manual coordinates transformation (if manual mode was used)  
    elif manual_coordinates and processing_mode in ["manual", "manual_failed"]:
        manual_x = manual_coordinates.get('x', 0)
        manual_y = manual_coordinates.get('y', 0)
        
        start_x_pixel -= manual_x
        start_y_pixel -= manual_y
        end_x_pixel -= manual_x
        end_y_pixel -= manual_y
        
        logger.debug(f"Applied reverse manual offset to line: (-{manual_x}, -{manual_y})")
    
    # Convert back to normalized coordinates in processed image space
    transformed_line['startX'] = start_x_pixel / processed_width
    transformed_line['startY'] = start_y_pixel / processed_height
    transformed_line['endX'] = end_x_pixel / processed_width
    transformed_line['endY'] = end_y_pixel / processed_height
    
    # Ensure coordinates stay within valid range [0, 1]
    transformed_line['startX'] = max(0, min(1, transformed_line['startX']))
    transformed_line['startY'] = max(0, min(1, transformed_line['startY']))
    transformed_line['endX'] = max(0, min(1, transformed_line['endX']))
    transformed_line['endY'] = max(0, min(1, transformed_line['endY']))
    
    return transformed_line


def validate_transformation_result(
    original_coords: List[Dict[str, Any]],
    transformed_coords: List[Dict[str, Any]],
    transformation_metadata: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Validate the results of coordinate transformation.
    
    Args:
        original_coords: Original coordinates before transformation
        transformed_coords: Coordinates after transformation
        transformation_metadata: Transformation metadata used
        
    Returns:
        Validation results with statistics and warnings
    """
    
    validation_results = {
        'success': True,
        'warnings': [],
        'statistics': {
            'original_count': len(original_coords),
            'transformed_count': len(transformed_coords),
            'coordinate_changes': 0,
        }
    }
    
    try:
        # Check if counts match
        if len(original_coords) != len(transformed_coords):
            validation_results['warnings'].append(
                f"Coordinate count mismatch: {len(original_coords)} -> {len(transformed_coords)}"
            )
        
        # Count how many coordinates actually changed
        changes = 0
        for orig, trans in zip(original_coords, transformed_coords):
            if orig != trans:
                changes += 1
        
        validation_results['statistics']['coordinate_changes'] = changes
        
        # Check if transformation was actually needed
        processing_mode = transformation_metadata.get('processing_mode', 'auto')
        if processing_mode in ['manual', 'manual_failed'] or transformation_metadata.get('frame_info', {}).get('frame_removed'):
            if changes == 0:
                validation_results['warnings'].append(
                    "Expected coordinate changes but none were applied"
                )
        
        logger.info(f"Transformation validation: {changes} coordinates changed out of {len(original_coords)}")
        
    except Exception as e:
        logger.error(f"Error validating transformation: {str(e)}")
        validation_results['success'] = False
        validation_results['warnings'].append(f"Validation error: {str(e)}")
    
    return validation_results
