"""
Geometric calculation functions for P&ID graph processing.
"""

from typing import List
import numpy as np
from models import BoundingBox


def calculate_line_to_bbox_distance(line_points: List[List[float]], bbox: BoundingBox) -> float:
    """Calculate minimum distance from line to bounding box"""
    min_distance = float('inf')
    bbox_center = bbox.center()
    
    # Calculate distance from each line segment to bbox center
    for i in range(len(line_points) - 1):
        p1 = np.array(line_points[i])
        p2 = np.array(line_points[i + 1])
        center = np.array(bbox_center)
        
        # Distance from point to line segment
        distance = point_to_line_segment_distance(center, p1, p2)
        min_distance = min(min_distance, distance)
    
    return min_distance


def calculate_line_to_line_distance(line1_points: List[List[float]], 
                                   line2_points: List[List[float]]) -> float:
    """Calculate minimum distance between two lines"""
    min_distance = float('inf')
    
    # Check distance between all segment pairs
    for i in range(len(line1_points) - 1):
        for j in range(len(line2_points) - 1):
            p1 = np.array(line1_points[i])
            p2 = np.array(line1_points[i + 1])
            p3 = np.array(line2_points[j])
            p4 = np.array(line2_points[j + 1])
            
            distance = line_segment_distance(p1, p2, p3, p4)
            min_distance = min(min_distance, distance)
    
    return min_distance


def calculate_bbox_distance(bbox1: BoundingBox, bbox2: BoundingBox) -> float:
    """Calculate distance between two bounding boxes"""
    center1 = np.array(bbox1.center())
    center2 = np.array(bbox2.center())
    return np.linalg.norm(center1 - center2)


def calculate_bbox_edge_distance(bbox1: BoundingBox, bbox2: BoundingBox) -> float:
    """Calculate minimum edge-to-edge distance between two bounding boxes"""
    # If bounding boxes overlap, distance is 0
    if (bbox1.topX <= bbox2.bottomX and bbox1.bottomX >= bbox2.topX and
        bbox1.topY <= bbox2.bottomY and bbox1.bottomY >= bbox2.topY):
        return 0.0
    
    # Calculate horizontal and vertical distances
    horizontal_distance = 0.0
    vertical_distance = 0.0
    
    # Horizontal distance
    if bbox1.bottomX < bbox2.topX:
        horizontal_distance = bbox2.topX - bbox1.bottomX
    elif bbox2.bottomX < bbox1.topX:
        horizontal_distance = bbox1.topX - bbox2.bottomX
    
    # Vertical distance
    if bbox1.bottomY < bbox2.topY:
        vertical_distance = bbox2.topY - bbox1.bottomY
    elif bbox2.bottomY < bbox1.topY:
        vertical_distance = bbox1.topY - bbox2.bottomY
    
    # Return Euclidean distance
    return np.sqrt(horizontal_distance**2 + vertical_distance**2)


def point_to_line_segment_distance(point: np.ndarray, p1: np.ndarray, p2: np.ndarray) -> float:
    """Calculate distance from point to line segment"""
    line_vec = p2 - p1
    point_vec = point - p1
    line_len = np.linalg.norm(line_vec)
    
    if line_len == 0:
        return np.linalg.norm(point_vec)
    
    line_unitvec = line_vec / line_len
    proj_length = np.dot(point_vec, line_unitvec)
    
    if proj_length < 0.0:
        return np.linalg.norm(point_vec)
    elif proj_length > line_len:
        return np.linalg.norm(point - p2)
    else:
        return np.linalg.norm(point_vec - proj_length * line_unitvec)


def line_segment_distance(p1: np.ndarray, p2: np.ndarray, 
                          p3: np.ndarray, p4: np.ndarray) -> float:
    """Calculate minimum distance between two line segments"""
    distances = [
        point_to_line_segment_distance(p1, p3, p4),
        point_to_line_segment_distance(p2, p3, p4),
        point_to_line_segment_distance(p3, p1, p2),
        point_to_line_segment_distance(p4, p1, p2)
    ]
    return min(distances)


def calculate_line_to_bbox_edge_distance(line_points: List[List[float]], bbox: BoundingBox) -> float:
    """
    Calculate minimum distance from line to bounding box edges (not just center).
    This provides more accurate proximity detection for symbol-line connections.
    """
    min_distance = float('inf')
    
    # Define bbox edges as line segments
    bbox_edges = [
        # Top edge
        [[bbox.topX, bbox.topY], [bbox.bottomX, bbox.topY]],
        # Right edge  
        [[bbox.bottomX, bbox.topY], [bbox.bottomX, bbox.bottomY]],
        # Bottom edge
        [[bbox.bottomX, bbox.bottomY], [bbox.topX, bbox.bottomY]],
        # Left edge
        [[bbox.topX, bbox.bottomY], [bbox.topX, bbox.topY]]
    ]
    
    # Test distance from each line segment to each bbox edge
    for i in range(len(line_points) - 1):
        line_seg = [line_points[i], line_points[i + 1]]
        
        for bbox_edge in bbox_edges:
            # Distance between two line segments
            p1 = np.array(line_seg[0])
            p2 = np.array(line_seg[1])
            p3 = np.array(bbox_edge[0])
            p4 = np.array(bbox_edge[1])
            
            # Calculate minimum distance between line segments
            distances = [
                point_to_line_segment_distance(p1, p3, p4),
                point_to_line_segment_distance(p2, p3, p4),
                point_to_line_segment_distance(p3, p1, p2),
                point_to_line_segment_distance(p4, p1, p2)
            ]
            
            segment_distance = min(distances)
            min_distance = min(min_distance, segment_distance)
    
    return min_distance


def calculate_enhanced_line_to_bbox_distance(line_points: List[List[float]], bbox: BoundingBox) -> float:
    """
    Enhanced distance calculation that uses the minimum of center-based and edge-based methods.
    This ensures the most accurate symbol-line connection detection.
    """
    center_distance = calculate_line_to_bbox_distance(line_points, bbox)
    edge_distance = calculate_line_to_bbox_edge_distance(line_points, bbox)
    
    return min(center_distance, edge_distance)


def calculate_line_length(points: List[List[float]]) -> float:
    """Calculate total length of a line from its points"""
    total_length = 0.0
    for i in range(len(points) - 1):
        p1 = np.array(points[i])
        p2 = np.array(points[i + 1])
        total_length += np.linalg.norm(p2 - p1)
    return total_length
