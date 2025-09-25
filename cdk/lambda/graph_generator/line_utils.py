"""
Utility functions for line processing operations.
"""

import numpy as np
from typing import List, Tuple


def calculate_distance(point1: List[float], point2: List[float]) -> float:
    """Calculate Euclidean distance between two points"""
    return np.linalg.norm(np.array(point1) - np.array(point2))


def calculate_line_length_from_points(points: List[List[float]]) -> float:
    """Calculate total length of a line from its points"""
    if len(points) < 2:
        return 0.0
    
    total_length = 0.0
    for i in range(len(points) - 1):
        p1 = points[i]
        p2 = points[i + 1]
        total_length += ((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)**0.5
    
    return total_length


def is_point_on_line(point: List[float], line_points: List[List[float]], tolerance: float) -> bool:
    """Check if a point is on or near a line segment"""
    if len(line_points) < 2:
        return False
        
    # For multi-segment lines, check each segment
    for i in range(len(line_points) - 1):
        start = line_points[i]
        end = line_points[i + 1]
        
        # Calculate distance from point to line segment
        distance = point_to_line_segment_distance(point, start, end)
        if distance <= tolerance:
            return True
    
    return False


def point_to_line_segment_distance(point: List[float], line_start: List[float], line_end: List[float]) -> float:
    """Calculate minimum distance from a point to a line segment"""
    # Vector from line_start to line_end
    line_vec = [line_end[0] - line_start[0], line_end[1] - line_start[1]]
    # Vector from line_start to point
    point_vec = [point[0] - line_start[0], point[1] - line_start[1]]
    
    line_len_sq = line_vec[0]**2 + line_vec[1]**2
    if line_len_sq == 0:
        # Line is a point
        return ((point[0] - line_start[0])**2 + (point[1] - line_start[1])**2)**0.5
    
    # Project point onto line
    t = max(0, min(1, (point_vec[0]*line_vec[0] + point_vec[1]*line_vec[1]) / line_len_sq))
    
    # Find closest point on line segment
    closest = [line_start[0] + t*line_vec[0], line_start[1] + t*line_vec[1]]
    
    # Return distance
    return ((point[0] - closest[0])**2 + (point[1] - closest[1])**2)**0.5


def are_geometric_continuations(line1: dict, line2: dict, tolerance: float) -> bool:
    """Check if two lines are geometric continuations of each other"""
    # Must have the same orientation (both horizontal or both vertical)
    if line1['horizontal'] and line2['horizontal']:
        # Both horizontal - check if they're on the same Y level and adjacent/overlapping
        y1_avg = (line1['start'][1] + line1['end'][1]) / 2
        y2_avg = (line2['start'][1] + line2['end'][1]) / 2
        
        if abs(y1_avg - y2_avg) > tolerance:
            return False
        
        # Check if they're adjacent or overlapping in X direction
        line1_min_x = min(line1['start'][0], line1['end'][0])
        line1_max_x = max(line1['start'][0], line1['end'][0])
        line2_min_x = min(line2['start'][0], line2['end'][0])
        line2_max_x = max(line2['start'][0], line2['end'][0])
        
        # Check for adjacency or overlap
        gap = min(abs(line1_max_x - line2_min_x), abs(line2_max_x - line1_min_x))
        overlap = max(0, min(line1_max_x, line2_max_x) - max(line1_min_x, line2_min_x))
        
        # Allow for small gaps or require overlap
        return gap <= tolerance or overlap > 0
        
    elif line1['vertical'] and line2['vertical']:
        # Both vertical - check if they're on the same X level and adjacent/overlapping
        x1_avg = (line1['start'][0] + line1['end'][0]) / 2
        x2_avg = (line2['start'][0] + line2['end'][0]) / 2
        
        if abs(x1_avg - x2_avg) > tolerance:
            return False
        
        # Check if they're adjacent or overlapping in Y direction
        line1_min_y = min(line1['start'][1], line1['end'][1])
        line1_max_y = max(line1['start'][1], line1['end'][1])
        line2_min_y = min(line2['start'][1], line2['end'][1])
        line2_max_y = max(line2['start'][1], line2['end'][1])
        
        # Check for adjacency or overlap
        gap = min(abs(line1_max_y - line2_min_y), abs(line2_max_y - line1_min_y))
        overlap = max(0, min(line1_max_y, line2_max_y) - max(line1_min_y, line2_min_y))
        
        # Allow for small gaps or require overlap
        return gap <= tolerance or overlap > 0
    
    else:
        # Different orientations or diagonal lines
        # Check if they're collinear with similar direction
        dot_product = abs(line1['dir_x'] * line2['dir_x'] + line1['dir_y'] * line2['dir_y'])
        if dot_product < 0.95:  # Not parallel enough
            return False
        
        # Check if endpoints are close (indicating continuation)
        distances = [
            calculate_distance(line1['start'], line2['start']),
            calculate_distance(line1['start'], line2['end']),
            calculate_distance(line1['end'], line2['start']),
            calculate_distance(line1['end'], line2['end'])
        ]
        
        min_distance = min(distances)
        return min_distance <= tolerance


def can_form_single_straight_line(lines_data: List[dict], tolerance: float) -> bool:
    """Check if all lines can form a single continuous straight line"""
    if len(lines_data) < 2:
        return True
    
    # Collect all unique points
    all_points = []
    for line_data in lines_data:
        for point in line_data['points']:
            # Check if point already exists (within tolerance)
            exists = False
            for existing_point in all_points:
                if (abs(point[0] - existing_point[0]) <= tolerance and 
                    abs(point[1] - existing_point[1]) <= tolerance):
                    exists = True
                    break
            if not exists:
                all_points.append(point)
    
    # If we have more than 2 unique points, it's not a simple straight line
    if len(all_points) > 2:
        return False
    
    # Check if all line segments have the same orientation
    first_line = lines_data[0]['points']
    first_start, first_end = first_line[0], first_line[-1]
    first_dx = first_end[0] - first_start[0]
    first_dy = first_end[1] - first_start[1]
    
    # Normalize the direction vector
    first_length = (first_dx**2 + first_dy**2)**0.5
    if first_length < tolerance:
        return False  # Too short to determine direction
    
    first_dir_x = first_dx / first_length
    first_dir_y = first_dy / first_length
    
    # Check all other lines have the same direction
    for line_data in lines_data[1:]:
        points = line_data['points']
        start, end = points[0], points[-1]
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        
        length = (dx**2 + dy**2)**0.5
        if length < tolerance:
            continue  # Skip very short lines
        
        dir_x = dx / length
        dir_y = dy / length
        
        # Check if directions are parallel (same or opposite)
        dot_product = abs(first_dir_x * dir_x + first_dir_y * dir_y)
        if dot_product < 0.95:  # Allow for small angle differences
            return False
    
    return True


def is_valid_l_shape_candidate(lines_data: List[dict], tolerance: float) -> bool:
    """Check if the line group is a valid candidate for L-shape merging"""
    if len(lines_data) != 2:
        return False  # L-shape should have exactly 2 segments
    
    line1_points = lines_data[0]['points']
    line2_points = lines_data[1]['points']
    
    line1_start = line1_points[0]
    line1_end = line1_points[-1]
    line2_start = line2_points[0]
    line2_end = line2_points[-1]
    
    # Check orientations
    line1_dx = abs(line1_end[0] - line1_start[0])
    line1_dy = abs(line1_end[1] - line1_start[1])
    line2_dx = abs(line2_end[0] - line2_start[0])
    line2_dy = abs(line2_end[1] - line2_start[1])
    
    # One should be vertical, one horizontal
    line1_vertical = line1_dx <= tolerance
    line1_horizontal = line1_dy <= tolerance
    line2_vertical = line2_dx <= tolerance
    line2_horizontal = line2_dy <= tolerance
    
    return (line1_vertical and line2_horizontal) or (line1_horizontal and line2_vertical)
