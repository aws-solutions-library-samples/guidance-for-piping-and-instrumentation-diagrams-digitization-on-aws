"""
Geometric algorithms for line merging and point consolidation.
"""

import logging
from typing import List, Dict, Tuple
from line_utils import calculate_distance, calculate_line_length_from_points

logger = logging.getLogger()


def merge_line_points(lines_data: List[Dict]) -> List[List[float]]:
    """Consolidate collinear line segments while preserving L-shaped pipe connections"""
    if len(lines_data) == 1:
        return lines_data[0]['points']
    
    # Classify and group lines using tolerance-based grouping
    vertical_lines = []  # List of vertical line info
    horizontal_lines = []  # List of horizontal line info
    diagonal_lines = []  # Lines that are neither vertical nor horizontal
    tolerance = 5.0  # Tolerance for considering lines as collinear
    
    # First pass: classify lines by orientation
    for line_data in lines_data:
        points = line_data['points']
        start = points[0]
        end = points[-1]
        
        # Determine if line is vertical or horizontal
        dx = abs(end[0] - start[0])
        dy = abs(end[1] - start[1])
        
        if dx <= tolerance:
            # Vertical line
            avg_x = (start[0] + end[0]) / 2
            vertical_lines.append({
                'points': points,
                'avg_x': avg_x,
                'start_y': min(start[1], end[1]),
                'end_y': max(start[1], end[1]),
                'data': line_data
            })
        elif dy <= tolerance:
            # Horizontal line
            avg_y = (start[1] + end[1]) / 2
            horizontal_lines.append({
                'points': points,
                'avg_y': avg_y,
                'start_x': min(start[0], end[0]),
                'end_x': max(start[0], end[0]),
                'data': line_data
            })
        else:
            # Diagonal line - preserve as is
            diagonal_lines.append(line_data)
            logger.info(f"Preserving diagonal line {line_data['id']}: {points}")
    
    # Second pass: group lines by tolerance-based similarity
    vertical_groups = group_vertical_lines_by_tolerance(vertical_lines, tolerance)
    horizontal_groups = group_horizontal_lines_by_tolerance(horizontal_lines, tolerance)
    
    # Check if we have both vertical and horizontal groups (potential L-shape)
    if vertical_groups and horizontal_groups:
        logger.info(f"Detected potential L-shape: {len(vertical_groups)} vertical groups, {len(horizontal_groups)} horizontal groups")
        return create_l_shaped_line(vertical_groups, horizontal_groups)
    elif vertical_groups and not horizontal_groups:
        return consolidate_vertical_lines(vertical_groups)
    elif horizontal_groups and not vertical_groups:
        return consolidate_horizontal_lines(horizontal_groups)
    elif diagonal_lines:
        # If we only have diagonal lines, return the first one
        return diagonal_lines[0]['points']
    else:
        # Fallback to first line if no clear grouping
        return lines_data[0]['points']


def group_vertical_lines_by_tolerance(vertical_lines: List[Dict], tolerance: float) -> Dict:
    """Group vertical lines by X coordinate within tolerance"""
    if not vertical_lines:
        return {}
    
    groups = {}
    group_id = 0
    
    for line in vertical_lines:
        # Find existing group within tolerance
        assigned = False
        for gid, group_lines in groups.items():
            # Check if this line's X coordinate is within tolerance of group's average X
            group_avg_x = sum(l['avg_x'] for l in group_lines) / len(group_lines)
            
            if abs(line['avg_x'] - group_avg_x) <= tolerance:
                # Add to existing group
                groups[gid].append(line)
                assigned = True
                break
        
        if not assigned:
            # Create new group
            groups[group_id] = [line]
            group_id += 1
    
    # Convert to format expected by consolidation methods
    result_groups = {}
    for gid, group_lines in groups.items():
        # Use average X coordinate for the group
        avg_x = sum(l['avg_x'] for l in group_lines) / len(group_lines)
        result_groups[avg_x] = group_lines
        
    return result_groups


def group_horizontal_lines_by_tolerance(horizontal_lines: List[Dict], tolerance: float) -> Dict:
    """Group horizontal lines by Y coordinate within tolerance"""
    if not horizontal_lines:
        return {}
    
    groups = {}
    group_id = 0
    
    for line in horizontal_lines:
        # Find existing group within tolerance
        assigned = False
        for gid, group_lines in groups.items():
            # Check if this line's Y coordinate is within tolerance of group's average Y
            group_avg_y = sum(l['avg_y'] for l in group_lines) / len(group_lines)
            
            if abs(line['avg_y'] - group_avg_y) <= tolerance:
                # Add to existing group
                groups[gid].append(line)
                assigned = True
                break
        
        if not assigned:
            # Create new group
            groups[group_id] = [line]
            group_id += 1
    
    # Convert to format expected by consolidation methods
    result_groups = {}
    for gid, group_lines in groups.items():
        # Use average Y coordinate for the group
        avg_y = sum(l['avg_y'] for l in group_lines) / len(group_lines)
        result_groups[avg_y] = group_lines
        
    return result_groups


def consolidate_vertical_lines(vertical_groups: Dict) -> List[List[float]]:
    """Consolidate vertical line groups into a single vertical line"""
    # Find the group with maximum total coverage
    best_group = None
    best_coverage = 0
    
    for x_coord, lines in vertical_groups.items():
        # Calculate total Y coverage for this group
        min_y = min(line['start_y'] for line in lines)
        max_y = max(line['end_y'] for line in lines)
        coverage = max_y - min_y
        
        if coverage > best_coverage:
            best_coverage = coverage
            best_group = (x_coord, lines)
    
    if not best_group:
        return []
    
    x_coord, lines = best_group
    
    # Find the full extent of all lines in this group
    min_y = min(line['start_y'] for line in lines)
    max_y = max(line['end_y'] for line in lines)
    
    # Create consolidated vertical line
    return [[x_coord, min_y], [x_coord, max_y]]


def consolidate_horizontal_lines(horizontal_groups: Dict) -> List[List[float]]:
    """Consolidate horizontal line groups into a single horizontal line"""
    # Find the group with maximum total coverage
    best_group = None
    best_coverage = 0
    
    for y_coord, lines in horizontal_groups.items():
        # Calculate total X coverage for this group
        min_x = min(line['start_x'] for line in lines)
        max_x = max(line['end_x'] for line in lines)
        coverage = max_x - min_x
        
        if coverage > best_coverage:
            best_coverage = coverage
            best_group = (y_coord, lines)
    
    if not best_group:
        return []
    
    y_coord, lines = best_group
    
    # Find the full extent of all lines in this group
    min_x = min(line['start_x'] for line in lines)
    max_x = max(line['end_x'] for line in lines)
    
    # Create consolidated horizontal line
    return [[min_x, y_coord], [max_x, y_coord]]


def create_l_shaped_line(vertical_groups: Dict, horizontal_groups: Dict) -> List[List[float]]:
    """Create an L-shaped line preserving both vertical and horizontal segments"""
    logger.info("Creating L-shaped line from vertical and horizontal groups")
    
    # Find the best vertical and horizontal segments to connect
    best_vertical = find_best_vertical_group(vertical_groups)
    best_horizontal = find_best_horizontal_group(horizontal_groups)
    
    if not best_vertical or not best_horizontal:
        logger.warning("Could not find suitable vertical or horizontal groups for L-shape")
        # Fallback to largest group
        if best_vertical:
            return consolidate_vertical_lines({best_vertical[0]: best_vertical[1]})
        elif best_horizontal:
            return consolidate_horizontal_lines({best_horizontal[0]: best_horizontal[1]})
        else:
            return []
    
    v_x_coord, v_lines = best_vertical
    h_y_coord, h_lines = best_horizontal
    
    # Get extents of each segment
    v_min_y = min(line['start_y'] for line in v_lines)
    v_max_y = max(line['end_y'] for line in v_lines)
    h_min_x = min(line['start_x'] for line in h_lines)
    h_max_x = max(line['end_x'] for line in h_lines)
    
    # Find the connection point where vertical and horizontal segments meet
    connection_point = [v_x_coord, h_y_coord]
    
    # Check if the connection point makes sense (segments should intersect or be close)
    tolerance = 10.0  # Allow some tolerance for connection
    
    # Check if vertical line overlaps with horizontal line's Y coordinate
    v_contains_h_y = (v_min_y - tolerance) <= h_y_coord <= (v_max_y + tolerance)
    # Check if horizontal line overlaps with vertical line's X coordinate  
    h_contains_v_x = (h_min_x - tolerance) <= v_x_coord <= (h_max_x + tolerance)
    
    if v_contains_h_y and h_contains_v_x:
        # Create L-shaped line with 3 points: vertical start -> connection -> horizontal end
        # Determine which ends are farthest from connection point
        
        # Vertical segment endpoints
        v_start = [v_x_coord, v_min_y]
        v_end = [v_x_coord, v_max_y]
        
        # Horizontal segment endpoints  
        h_start = [h_min_x, h_y_coord]
        h_end = [h_max_x, h_y_coord]
        
        # Calculate distances from connection point to each endpoint
        def distance_to_connection(point):
            return abs(point[0] - connection_point[0]) + abs(point[1] - connection_point[1])
        
        v_start_dist = distance_to_connection(v_start)
        v_end_dist = distance_to_connection(v_end)
        h_start_dist = distance_to_connection(h_start)
        h_end_dist = distance_to_connection(h_end)
        
        # Choose the farthest vertical endpoint
        v_far_point = v_start if v_start_dist > v_end_dist else v_end
        # Choose the farthest horizontal endpoint
        h_far_point = h_start if h_start_dist > h_end_dist else h_end
        
        # Create L-shaped path: vertical_far -> connection -> horizontal_far
        l_shaped_points = [v_far_point, connection_point, h_far_point]
        
        logger.info(f"Created L-shaped line: {l_shaped_points}")
        return l_shaped_points
    else:
        logger.warning(f"Vertical and horizontal segments don't form proper L-shape. V contains H_Y: {v_contains_h_y}, H contains V_X: {h_contains_v_x}")
        # Fallback to the longer segment
        v_length = v_max_y - v_min_y
        h_length = h_max_x - h_min_x
        
        if v_length > h_length:
            logger.info("Falling back to vertical segment")
            return [[v_x_coord, v_min_y], [v_x_coord, v_max_y]]
        else:
            logger.info("Falling back to horizontal segment")
            return [[h_min_x, h_y_coord], [h_max_x, h_y_coord]]


def find_best_vertical_group(vertical_groups: Dict):
    """Find the best vertical group based on coverage"""
    best_group = None
    best_coverage = 0
    
    for x_coord, lines in vertical_groups.items():
        min_y = min(line['start_y'] for line in lines)
        max_y = max(line['end_y'] for line in lines)
        coverage = max_y - min_y
        
        if coverage > best_coverage:
            best_coverage = coverage
            best_group = (x_coord, lines)
    
    return best_group


def find_best_horizontal_group(horizontal_groups: Dict):
    """Find the best horizontal group based on coverage"""
    best_group = None
    best_coverage = 0
    
    for y_coord, lines in horizontal_groups.items():
        min_x = min(line['start_x'] for line in lines)
        max_x = max(line['end_x'] for line in lines)
        coverage = max_x - min_x
        
        if coverage > best_coverage:
            best_coverage = coverage
            best_group = (y_coord, lines)
    
    return best_group


def merge_geometric_continuation_points(lines_data: List[Dict], config: Dict) -> List[List[float]]:
    """Merge geometric continuation lines into optimal line segments"""
    if len(lines_data) == 1:
        return lines_data[0]['points']
    
    tolerance = config.get('geometric_continuation_tolerance', 10.0)
    
    # Classify lines by orientation
    horizontal_lines = []
    vertical_lines = []
    diagonal_lines = []
    
    for line_data in lines_data:
        points = line_data['points']
        start = points[0]
        end = points[-1]
        dx = abs(end[0] - start[0])
        dy = abs(end[1] - start[1])
        
        if dx <= tolerance:
            # Vertical line
            vertical_lines.append({
                'start': start,
                'end': end,
                'min_y': min(start[1], end[1]),
                'max_y': max(start[1], end[1]),
                'avg_x': (start[0] + end[0]) / 2
            })
        elif dy <= tolerance:
            # Horizontal line
            horizontal_lines.append({
                'start': start,
                'end': end,
                'min_x': min(start[0], end[0]),
                'max_x': max(start[0], end[0]),
                'avg_y': (start[1] + end[1]) / 2
            })
        else:
            # Diagonal line
            diagonal_lines.append(line_data)
    
    # Merge based on dominant orientation
    if horizontal_lines and len(horizontal_lines) >= len(vertical_lines) and len(horizontal_lines) >= len(diagonal_lines):
        # Merge horizontal lines
        avg_y = sum(line['avg_y'] for line in horizontal_lines) / len(horizontal_lines)
        min_x = min(line['min_x'] for line in horizontal_lines)
        max_x = max(line['max_x'] for line in horizontal_lines)
        return [[min_x, avg_y], [max_x, avg_y]]
        
    elif vertical_lines and len(vertical_lines) >= len(horizontal_lines) and len(vertical_lines) >= len(diagonal_lines):
        # Merge vertical lines
        avg_x = sum(line['avg_x'] for line in vertical_lines) / len(vertical_lines)
        min_y = min(line['min_y'] for line in vertical_lines)
        max_y = max(line['max_y'] for line in vertical_lines)
        return [[avg_x, min_y], [avg_x, max_y]]
        
    else:
        # Mixed or diagonal - find the line with maximum extent
        max_length = 0
        best_line = lines_data[0]
        
        for line_data in lines_data:
            length = calculate_line_length_from_points(line_data['points'])
            if length > max_length:
                max_length = length
                best_line = line_data
        
        return best_line['points']


def merge_collinear_segments(lines_data: List[Dict], tolerance: float) -> List[List[float]]:
    """Merge truly collinear line segments into a single line"""
    # Collect all points
    all_points = []
    for line_data in lines_data:
        all_points.extend(line_data['points'])
    
    # Find the two points that are farthest apart
    max_distance = 0
    start_point = None
    end_point = None
    
    for i, point1 in enumerate(all_points):
        for j, point2 in enumerate(all_points[i+1:], start=i+1):
            distance = ((point2[0] - point1[0])**2 + (point2[1] - point1[1])**2)**0.5
            if distance > max_distance:
                max_distance = distance
                start_point = point1
                end_point = point2
    
    if start_point and end_point:
        return [start_point, end_point]
    else:
        # Fallback to first line
        return lines_data[0]['points']
