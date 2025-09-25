"""
Line post-processing utilities for improving line detection.
Includes line merging, extension, and connection detection.
"""
import numpy as np
from typing import List, Tuple, Optional
from shapely.geometry import LineString, Point
from shapely.ops import unary_union
import math

from line_detection import LineSegment


class LinePostProcessor:
    """Post-processes detected line segments to merge fragmented lines."""
    
    def __init__(
        self,
        merge_distance_threshold: float = 0.02,  # 2% of image dimension
        angular_tolerance: float = 15.0,  # degrees
        min_line_length: float = 0.01,  # 1% of image dimension
        extension_padding: float = 0.01  # 1% extension padding
    ):
        self.merge_distance_threshold = merge_distance_threshold
        self.angular_tolerance = angular_tolerance
        self.min_line_length = min_line_length
        self.extension_padding = extension_padding
    
    def process_lines(
        self,
        line_segments: List[LineSegment],
        image_width: int,
        image_height: int
    ) -> List[LineSegment]:
        """
        Main processing pipeline for line segments.
        
        Args:
            line_segments: List of detected line segments
            image_width: Image width in pixels
            image_height: Image height in pixels
            
        Returns:
            List of processed line segments
        """
        if not line_segments:
            return []
        
        # Convert normalized coordinates to pixel coordinates for processing
        pixel_lines = self._denormalize_lines(line_segments, image_width, image_height)
        
        # Step 1: Extend lines
        extended_lines = self._extend_lines(pixel_lines)
        
        # Step 2: Find and merge connected lines
        merged_lines = self._merge_connected_lines(extended_lines)
        
        # Step 3: Filter out very short segments
        filtered_lines = self._filter_short_lines(merged_lines, image_width, image_height)
        
        # Convert back to normalized coordinates
        return self._normalize_lines(filtered_lines, image_width, image_height)
    
    def _denormalize_lines(
        self,
        lines: List[LineSegment],
        width: int,
        height: int
    ) -> List[Tuple[float, float, float, float]]:
        """Convert normalized line coordinates to pixel coordinates."""
        return [
            (
                line.startX * width,
                line.startY * height,
                line.endX * width,
                line.endY * height
            )
            for line in lines
        ]
    
    def _normalize_lines(
        self,
        lines: List[Tuple[float, float, float, float]],
        width: int,
        height: int
    ) -> List[LineSegment]:
        """Convert pixel coordinates back to normalized coordinates."""
        return [
            LineSegment(
                startX=x1 / width,
                startY=y1 / height,
                endX=x2 / width,
                endY=y2 / height
            )
            for x1, y1, x2, y2 in lines
        ]
    
    def _extend_lines(
        self,
        lines: List[Tuple[float, float, float, float]]
    ) -> List[Tuple[float, float, float, float]]:
        """Extend lines by a small amount to help with connection detection."""
        extended = []
        
        for x1, y1, x2, y2 in lines:
            # Calculate line direction
            dx = x2 - x1
            dy = y2 - y1
            length = math.sqrt(dx**2 + dy**2)
            
            if length > 0:
                # Normalize direction
                dx /= length
                dy /= length
                
                # Extend both ends
                extend_amount = length * self.extension_padding
                new_x1 = x1 - dx * extend_amount
                new_y1 = y1 - dy * extend_amount
                new_x2 = x2 + dx * extend_amount
                new_y2 = y2 + dy * extend_amount
                
                extended.append((new_x1, new_y1, new_x2, new_y2))
            else:
                extended.append((x1, y1, x2, y2))
        
        return extended
    
    def _merge_connected_lines(
        self,
        lines: List[Tuple[float, float, float, float]]
    ) -> List[Tuple[float, float, float, float]]:
        """Merge lines that are collinear and close to each other."""
        if not lines:
            return []
        
        # Convert to LineString objects
        line_strings = [LineString([(x1, y1), (x2, y2)]) for x1, y1, x2, y2 in lines]
        
        merged = []
        used = set()
        
        for i, line1 in enumerate(line_strings):
            if i in used:
                continue
            
            # Start a group with this line
            group = [i]
            
            # Find all lines that should be merged with this one
            for j, line2 in enumerate(line_strings):
                if j <= i or j in used:
                    continue
                
                if self._should_merge_lines(line1, line2, lines[i], lines[j]):
                    group.append(j)
                    used.add(j)
            
            # Merge the group
            if len(group) > 1:
                merged_line = self._merge_line_group([lines[idx] for idx in group])
                merged.append(merged_line)
            else:
                merged.append(lines[i])
            
            used.add(i)
        
        return merged
    
    def _should_merge_lines(
        self,
        line1: LineString,
        line2: LineString,
        coords1: Tuple[float, float, float, float],
        coords2: Tuple[float, float, float, float]
    ) -> bool:
        """Check if two lines should be merged based on distance and angle."""
        # Check distance between endpoints
        x1_1, y1_1, x2_1, y2_1 = coords1
        x1_2, y1_2, x2_2, y2_2 = coords2
        
        # Calculate minimum distance between endpoints
        distances = [
            math.sqrt((x2_1 - x1_2)**2 + (y2_1 - y1_2)**2),
            math.sqrt((x2_1 - x2_2)**2 + (y2_1 - y2_2)**2),
            math.sqrt((x1_1 - x1_2)**2 + (y1_1 - y1_2)**2),
            math.sqrt((x1_1 - x2_2)**2 + (y1_1 - y2_2)**2)
        ]
        
        min_distance = min(distances)
        
        # Get image dimension for threshold scaling
        avg_coord = (abs(x2_1) + abs(y2_1) + abs(x1_1) + abs(y1_1)) / 4
        threshold = avg_coord * self.merge_distance_threshold
        
        if min_distance > threshold:
            return False
        
        # Check angle between lines
        angle1 = math.atan2(y2_1 - y1_1, x2_1 - x1_1)
        angle2 = math.atan2(y2_2 - y1_2, x2_2 - x1_2)
        
        angle_diff = abs(angle1 - angle2) * 180 / math.pi
        angle_diff = min(angle_diff, 180 - angle_diff)  # Handle angle wrap-around
        
        return angle_diff < self.angular_tolerance
    
    def _merge_line_group(
        self,
        lines: List[Tuple[float, float, float, float]]
    ) -> Tuple[float, float, float, float]:
        """Merge a group of lines into a single line."""
        # Collect all endpoints
        points = []
        for x1, y1, x2, y2 in lines:
            points.extend([(x1, y1), (x2, y2)])
        
        # Find the two points that are farthest apart
        max_dist = 0
        best_pair = (points[0], points[1])
        
        for i in range(len(points)):
            for j in range(i + 1, len(points)):
                dist = math.sqrt((points[i][0] - points[j][0])**2 + 
                               (points[i][1] - points[j][1])**2)
                if dist > max_dist:
                    max_dist = dist
                    best_pair = (points[i], points[j])
        
        return (best_pair[0][0], best_pair[0][1], best_pair[1][0], best_pair[1][1])
    
    def _filter_short_lines(
        self,
        lines: List[Tuple[float, float, float, float]],
        width: int,
        height: int
    ) -> List[Tuple[float, float, float, float]]:
        """Filter out very short line segments."""
        min_length = self.min_line_length * max(width, height)
        
        filtered = []
        for x1, y1, x2, y2 in lines:
            length = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
            if length >= min_length:
                filtered.append((x1, y1, x2, y2))
        
        return filtered


def connect_lines_with_gaps(
    line_segments: List[LineSegment],
    gap_threshold: float = 0.05,  # 5% of image dimension
    angle_tolerance: float = 30.0  # degrees
) -> List[Tuple[int, int]]:
    """
    Find pairs of line indices that should be connected across gaps.
    
    Returns:
        List of tuples (line_index1, line_index2) indicating connections
    """
    connections = []
    
    for i, line1 in enumerate(line_segments):
        for j, line2 in enumerate(line_segments):
            if j <= i:
                continue
            
            # Check if lines are roughly aligned
            angle1 = math.atan2(line1.endY - line1.startY, line1.endX - line1.startX)
            angle2 = math.atan2(line2.endY - line2.startY, line2.endX - line2.startX)
            
            angle_diff = abs(angle1 - angle2) * 180 / math.pi
            angle_diff = min(angle_diff, 180 - angle_diff)
            
            if angle_diff > angle_tolerance:
                continue
            
            # Check gap distance
            gaps = [
                math.sqrt((line1.endX - line2.startX)**2 + (line1.endY - line2.startY)**2),
                math.sqrt((line1.endX - line2.endX)**2 + (line1.endY - line2.endY)**2),
                math.sqrt((line1.startX - line2.startX)**2 + (line1.startY - line2.startY)**2),
                math.sqrt((line1.startX - line2.endX)**2 + (line1.startY - line2.endY)**2)
            ]
            
            min_gap = min(gaps)
            if min_gap < gap_threshold:
                connections.append((i, j))
    
    return connections


def detect_corner_connections(
    line_segments: List[LineSegment],
    corner_threshold: float = 0.03,  # 3% of image dimension
    angle_tolerance: Tuple[float, float] = (75.0, 105.0)  # 90 +/- 15 degrees
) -> List[Tuple[int, int, str]]:
    """
    Detect lines that form corners (elbows) and should be connected.
    
    Returns:
        List of tuples (line_index1, line_index2, connection_type) 
        where connection_type is 'corner' or 'straight'
    """
    connections = []
    
    for i, line1 in enumerate(line_segments):
        for j, line2 in enumerate(line_segments):
            if j <= i:
                continue
            
            # Calculate angles
            angle1 = math.atan2(line1.endY - line1.startY, line1.endX - line1.startX)
            angle2 = math.atan2(line2.endY - line2.startY, line2.endX - line2.startX)
            
            angle_diff = abs(angle1 - angle2) * 180 / math.pi
            angle_diff = min(angle_diff, 180 - angle_diff)
            
            # Check all endpoint combinations
            endpoints = [
                ((line1.endX, line1.endY), (line2.startX, line2.startY)),
                ((line1.endX, line1.endY), (line2.endX, line2.endY)),
                ((line1.startX, line1.startY), (line2.startX, line2.startY)),
                ((line1.startX, line1.startY), (line2.endX, line2.endY))
            ]
            
            for (x1, y1), (x2, y2) in endpoints:
                distance = math.sqrt((x1 - x2)**2 + (y1 - y2)**2)
                
                if distance < corner_threshold:
                    # Check if it's a corner (90 degrees +/- tolerance)
                    if angle_tolerance[0] <= angle_diff <= angle_tolerance[1]:
                        connections.append((i, j, 'corner'))
                    elif angle_diff < 30.0:  # Straight connection
                        connections.append((i, j, 'straight'))
                    break
    
    return connections
