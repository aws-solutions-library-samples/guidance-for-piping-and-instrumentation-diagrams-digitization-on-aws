import cv2
import numpy as np
import os
import json
from typing import Optional, List, Dict, Any
import logging
        
logger = logging.getLogger()

class BoundingBox:
    def __init__(self, x1: float = None, y1: float = None, x2: float = None, y2: float = None):
        # Use topX, topY, bottomX, bottomY naming convention
        self.topX, self.topY, self.bottomX, self.bottomY = x1, y1, x2, y2

class LineSegment:
    def __init__(self, startX: float, startY: float, endX: float, endY: float):
        self.startX = startX
        self.startY = startY
        self.endX = endX
        self.endY = endY

def to_grayscale(image: np.ndarray) -> np.ndarray:
    """Convert image to grayscale."""
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

def to_binary(image: np.ndarray) -> np.ndarray:
    """Convert grayscale image to binary using Otsu's method."""
    _, binary = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return binary

def clear_bounding_boxes(image: np.ndarray, bounding_boxes: List[BoundingBox]) -> np.ndarray:
    """Clear the given bounding boxes from the image."""
    # Determine background color based on image type
    if len(image.shape) == 3:  # Color image
        background_color = (255, 255, 255)  # White
    else:  # Grayscale
        background_color = 255  # White
    
    for bb in bounding_boxes:
        # topX,topY = top-left, bottomX,bottomY = bottom-right
        x1, y1, x2, y2 = int(bb.topX), int(bb.topY), int(bb.bottomX), int(bb.bottomY)
        
        # Use rectangle fill instead of polygon for simplicity
        cv2.rectangle(image, (x1, y1), (x2, y2), background_color, -1)
    
    return image

def draw_bounding_boxes(image: np.ndarray, bounding_boxes: List[BoundingBox], color=(0, 0, 255), thickness=2) -> np.ndarray:
    """Draw bounding boxes on the image."""
    output = image.copy()
    for bb in bounding_boxes:
        top_left = (int(bb.topX), int(bb.topY))
        bottom_right = (int(bb.bottomX), int(bb.bottomY))
        cv2.rectangle(output, top_left, bottom_right, color, thickness)
    return output

def apply_thinning(image: np.ndarray) -> np.ndarray:
    """Apply Zhang-Suen thinning algorithm."""
    thinning_type = cv2.ximgproc.THINNING_ZHANGSUEN
    return cv2.ximgproc.thinning(image, thinningType=thinning_type)

def preprocess_image(image: np.ndarray, 
                     symbol_bounding_boxes: List[BoundingBox] = None, 
                     text_bounding_boxes: List[BoundingBox] = None,
                     enable_thinning: bool = True) -> np.ndarray:
    """
    Preprocesses image for line detection.
    1. Clears symbol bounding boxes
    2. Clears text bounding boxes
    3. Converts to grayscale
    4. Binarizes
    5. Optionally applies thinning
    """
    # Create a copy to avoid modifying original
    processed = image.copy()
    
    # Clear bounding boxes if provided
    if symbol_bounding_boxes:
        processed = clear_bounding_boxes(processed, symbol_bounding_boxes)
    if text_bounding_boxes:
        processed = clear_bounding_boxes(processed, text_bounding_boxes)
    
    # Convert to grayscale
    processed = to_grayscale(processed)
    
    # Binarize
    processed = to_binary(processed)
    
    # Apply thinning if enabled
    if enable_thinning:
        processed = apply_thinning(processed)
    
    return processed

def is_within_bounding_box(bounding_box: Optional[BoundingBox], x1: int, y1: int, x2: int, y2: int) -> bool:
    """Check if line is within the given bounding box."""
    if bounding_box is None:
        return True
    
    # Check if both points are within the bounding box
    return (x1 >= bounding_box.topX and x1 <= bounding_box.bottomX and 
            y1 >= bounding_box.topY and y1 <= bounding_box.bottomY and
            x2 >= bounding_box.topX and x2 <= bounding_box.bottomX and
            y2 >= bounding_box.topY and y2 <= bounding_box.bottomY)

def detect_line_segments(preprocessed_image: np.ndarray,
                         image_height: int,
                         image_width: int,
                         bounding_box_inclusive: Optional[BoundingBox] = None,
                         max_line_gap: Optional[int] = None,
                         threshold: int = 5,
                         min_line_length: Optional[int] = 10,
                         rho: float = 0.2,
                         theta_param: float = 1080,
                         debug_raw_lines_callback=None) -> List[LineSegment]:
    """
    Detects line segments in the preprocessed image using Hough transform.
    
    Args:
        debug_raw_lines_callback: Optional callback function to save raw Hough lines
                                 Should accept (hough_results, image_width, image_height)
    """
    # Apply the Hough transform to detect lines
    hough_results = cv2.HoughLinesP(
        preprocessed_image, 
        rho=rho,
        theta=np.pi/theta_param,
        threshold=threshold,
        minLineLength=min_line_length,
        maxLineGap=max_line_gap
    )
    
    if hough_results is None:
        logger.warning("No lines detected!")
        return []
    
    # Call debug callback with raw Hough results if provided
    if debug_raw_lines_callback:
        debug_raw_lines_callback(hough_results, image_width, image_height)
    
    output_line_segments = []
    
    for line in hough_results:
        x1, y1, x2, y2 = line[0]
        
        # Sort start and end points for consistent direction
        # Horizontal lines: left to right
        if y1 == y2:
            if x1 > x2:
                x1, x2 = x2, x1
                y1, y2 = y2, y1
        # Vertical lines: top to bottom
        elif x1 == x2:
            if y1 > y2:
                x1, x2 = x2, x1
                y1, y2 = y2, y1
        # Angled lines: left to right
        else:
            if x1 > x2:
                x1, x2 = x2, x1
                y1, y2 = y2, y1
            elif x1 == x2 and y1 > y2:
                x1, x2 = x2, x1
                y1, y2 = y2, y1
        
        # Only include lines within the bounding box if specified
        if is_within_bounding_box(bounding_box_inclusive, x1, y1, x2, y2):
            # Add detected line and normalize coordinates
            output_line_segments.append(LineSegment(
                startX=x1/image_width,
                startY=y1/image_height,
                endX=x2/image_width,
                endY=y2/image_height
            ))
    
    return output_line_segments
