"""
Symbol-Aware Line Detection Module

This module provides functionality to detect and resolve line-symbol intersections
in P&ID diagrams. It prevents lines from appearing to pass through symbols by
splitting lines at symbol boundaries and creating proper connection points.
"""

import math
import os
from typing import List, Tuple, Optional, Dict, Any
import numpy as np

from line_detection import LineSegment, BoundingBox


class SymbolIntersectionResult:
    """Represents the result of a line-symbol intersection analysis."""
    
    def __init__(self, line_index: int, symbol_index: int, 
                 intersection_points: List[Tuple[float, float]], 
                 action: str = "split"):
        self.line_index = line_index
        self.symbol_index = symbol_index
        self.intersection_points = intersection_points
        self.action = action  # "split", "terminate", "skip"


class SymbolAwareLineDetector:
    """
    Detects and resolves line-symbol intersections in P&ID diagrams.
    
    This class provides methods to:
    1. Detect lines that pass through symbol bounding boxes
    2. Split those lines at symbol boundaries
    3. Create proper connection points at symbol edges
    """
    
    def __init__(self, symbol_boxes: List[BoundingBox], 
                 intersection_tolerance: Optional[int] = None,
                 enable_symbol_awareness: bool = True):
        """
        Initialize the symbol-aware line detector.
        
        Args:
            symbol_boxes: List of symbol bounding boxes
            intersection_tolerance: Distance tolerance for intersection detection (pixels)
            enable_symbol_awareness: Whether to enable symbol-aware processing
        """
        self.symbol_boxes = symbol_boxes
        self.enable_symbol_awareness = enable_symbol_awareness
        
        # Get tolerance from environment or use default
        self.intersection_tolerance = intersection_tolerance or int(
            os.environ.get('SYMBOL_INTERSECTION_TOLERANCE', '10')
        )
        
        # Additional padding around symbols for intersection detection
        self.symbol_padding = int(os.environ.get('SYMBOL_PADDING_PIXELS', '5'))
        
        print(f"SymbolAwareLineDetector initialized: "
              f"tolerance={self.intersection_tolerance}, "
              f"padding={self.symbol_padding}, "
              f"enabled={self.enable_symbol_awareness}")
    
    def detect_and_resolve_intersections(self, line_segments: List[LineSegment], 
                                       image_width: int, image_height: int) -> Tuple[List[LineSegment], List[Dict]]:
        """
        Main method: detect and resolve line-symbol intersections.
        
        Args:
            line_segments: List of detected line segments (normalized coordinates)
            image_width: Image width in pixels
            image_height: Image height in pixels
            
        Returns:
            Tuple of (processed_line_segments, intersection_metadata)
        """
        if not self.enable_symbol_awareness or not self.symbol_boxes:
            return line_segments, []
        
        print(f"Processing {len(line_segments)} line segments for symbol intersections")
        
        processed_lines = []
        intersection_metadata = []
        
        for line_idx, line in enumerate(line_segments):
            # Convert line to pixel coordinates for processing
            pixel_line = self._normalize_to_pixel_coords(line, image_width, image_height)
            
            # Check for intersections with all symbols
            intersecting_symbols = self._find_intersecting_symbols(pixel_line, image_width, image_height)
            
            if not intersecting_symbols:
                # No intersections, keep original line
                processed_lines.append(line)
            else:
                # Process intersections and split line
                split_result = self._split_line_at_intersections(
                    pixel_line, intersecting_symbols, image_width, image_height
                )
                
                # Convert back to normalized coordinates and add to results
                for split_line_pixels in split_result['segments']:
                    split_line_normalized = self._pixel_to_normalized_coords(
                        split_line_pixels, image_width, image_height
                    )
                    processed_lines.append(split_line_normalized)
                
                # Add metadata
                intersection_metadata.append({
                    'original_line_index': line_idx,
                    'intersecting_symbols': [s['symbol_idx'] for s in intersecting_symbols],
                    'action': 'split',
                    'resulting_segments': len(split_result['segments']),
                    'original_line': {
                        'startX': line.startX, 'startY': line.startY,
                        'endX': line.endX, 'endY': line.endY
                    }
                })
        
        print(f"Symbol-aware processing complete: {len(line_segments)} → {len(processed_lines)} segments")
        print(f"Found {len(intersection_metadata)} lines with symbol intersections")
        
        return processed_lines, intersection_metadata
    
    def _normalize_to_pixel_coords(self, line: LineSegment, width: int, height: int) -> Tuple[float, float, float, float]:
        """Convert normalized line coordinates to pixel coordinates."""
        return (
            line.startX * width,
            line.startY * height,
            line.endX * width,
            line.endY * height
        )
    
    def _pixel_to_normalized_coords(self, pixel_line: Tuple[float, float, float, float], 
                                  width: int, height: int) -> LineSegment:
        """Convert pixel coordinates back to normalized coordinates."""
        x1, y1, x2, y2 = pixel_line
        return LineSegment(
            startX=x1 / width,
            startY=y1 / height,
            endX=x2 / width,
            endY=y2 / height
        )
    
    def _find_intersecting_symbols(self, pixel_line: Tuple[float, float, float, float], 
                                 image_width: int, image_height: int) -> List[Dict]:
        """
        Find all symbols that intersect with the given line.
        
        Returns:
            List of dicts with 'symbol_idx', 'symbol_box', and 'intersection_points'
        """
        x1, y1, x2, y2 = pixel_line
        intersecting_symbols = []
        
        for symbol_idx, symbol_box in enumerate(self.symbol_boxes):
            # Add padding to symbol box for intersection detection
            padded_box = BoundingBox(
                x1=max(0, symbol_box.topX - self.symbol_padding),
                y1=max(0, symbol_box.topY - self.symbol_padding),
                x2=min(image_width, symbol_box.bottomX + self.symbol_padding),
                y2=min(image_height, symbol_box.bottomY + self.symbol_padding)
            )
            
            if self._line_intersects_rectangle(pixel_line, padded_box):
                # Find exact intersection points with the symbol boundary
                intersection_points = self._calculate_intersection_points(pixel_line, symbol_box)
                
                intersecting_symbols.append({
                    'symbol_idx': symbol_idx,
                    'symbol_box': symbol_box,
                    'padded_box': padded_box,
                    'intersection_points': intersection_points
                })
        
        return intersecting_symbols
    
    def _line_intersects_rectangle(self, line: Tuple[float, float, float, float], 
                                 rect: BoundingBox) -> bool:
        """
        Check if a line segment intersects with a rectangle.
        Uses the Cohen-Sutherland line clipping algorithm concept.
        """
        x1, y1, x2, y2 = line
        
        # Check if either endpoint is inside the rectangle
        if (rect.topX <= x1 <= rect.bottomX and rect.topY <= y1 <= rect.bottomY) or \
           (rect.topX <= x2 <= rect.bottomX and rect.topY <= y2 <= rect.bottomY):
            return True
        
        # Check intersection with each edge of the rectangle
        rect_edges = [
            (rect.topX, rect.topY, rect.bottomX, rect.topY),      # Top edge
            (rect.bottomX, rect.topY, rect.bottomX, rect.bottomY), # Right edge
            (rect.topX, rect.bottomY, rect.bottomX, rect.bottomY), # Bottom edge
            (rect.topX, rect.topY, rect.topX, rect.bottomY)       # Left edge
        ]
        
        for edge in rect_edges:
            if self._line_segments_intersect(line, edge):
                return True
        
        return False
    
    def _line_segments_intersect(self, line1: Tuple[float, float, float, float], 
                               line2: Tuple[float, float, float, float]) -> bool:
        """Check if two line segments intersect."""
        x1, y1, x2, y2 = line1
        x3, y3, x4, y4 = line2
        
        # Calculate the direction of the lines
        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        
        if abs(denom) < 1e-10:  # Lines are parallel
            return False
        
        # Calculate intersection point parameters
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom
        
        # Check if intersection point lies within both line segments
        return 0 <= t <= 1 and 0 <= u <= 1
    
    def _calculate_intersection_points(self, line: Tuple[float, float, float, float], 
                                     symbol_box: BoundingBox) -> List[Tuple[float, float]]:
        """Calculate the exact intersection points between a line and symbol boundary."""
        intersection_points = []
        
        # Define the four edges of the symbol box
        edges = [
            (symbol_box.topX, symbol_box.topY, symbol_box.bottomX, symbol_box.topY),      # Top
            (symbol_box.bottomX, symbol_box.topY, symbol_box.bottomX, symbol_box.bottomY), # Right
            (symbol_box.topX, symbol_box.bottomY, symbol_box.bottomX, symbol_box.bottomY), # Bottom
            (symbol_box.topX, symbol_box.topY, symbol_box.topX, symbol_box.bottomY)       # Left
        ]
        
        for edge in edges:
            intersection = self._calculate_line_intersection(line, edge)
            if intersection:
                intersection_points.append(intersection)
        
        return intersection_points
    
    def _calculate_line_intersection(self, line1: Tuple[float, float, float, float], 
                                   line2: Tuple[float, float, float, float]) -> Optional[Tuple[float, float]]:
        """Calculate the intersection point of two line segments."""
        x1, y1, x2, y2 = line1
        x3, y3, x4, y4 = line2
        
        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        
        if abs(denom) < 1e-10:
            return None
        
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom
        
        if 0 <= t <= 1 and 0 <= u <= 1:
            # Calculate intersection point
            ix = x1 + t * (x2 - x1)
            iy = y1 + t * (y2 - y1)
            return (ix, iy)
        
        return None
    
    def _split_line_at_intersections(self, pixel_line: Tuple[float, float, float, float], 
                                   intersecting_symbols: List[Dict], 
                                   image_width: int, image_height: int) -> Dict:
        """
        Split a line at symbol intersection points.
        
        Args:
            pixel_line: Line in pixel coordinates
            intersecting_symbols: List of intersecting symbol data
            image_width: Image width
            image_height: Image height
            
        Returns:
            Dict with 'segments' list of split line segments
        """
        x1, y1, x2, y2 = pixel_line
        
        # Collect all intersection points along the line
        split_points = [(x1, y1)]  # Start with line start point
        
        for symbol_data in intersecting_symbols:
            for point in symbol_data['intersection_points']:
                # Calculate distance along line for sorting
                px, py = point
                # Project point onto line to get parameter t
                line_vec = (x2 - x1, y2 - y1)
                line_len_sq = line_vec[0]**2 + line_vec[1]**2
                
                if line_len_sq > 0:
                    point_vec = (px - x1, py - y1)
                    t = (point_vec[0] * line_vec[0] + point_vec[1] * line_vec[1]) / line_len_sq
                    t = max(0, min(1, t))  # Clamp to [0, 1]
                    
                    split_points.append((px, py, t))
        
        split_points.append((x2, y2))  # End with line end point
        
        # Sort points by their position along the line
        split_points_with_t = []
        for i, point in enumerate(split_points):
            if len(point) == 2:  # Start/end points without t parameter
                if i == 0:
                    t = 0.0
                else:
                    t = 1.0
                split_points_with_t.append((point[0], point[1], t))
            else:
                split_points_with_t.append(point)
        
        split_points_with_t.sort(key=lambda p: p[2])
        
        # Create line segments between split points
        segments = []
        for i in range(len(split_points_with_t) - 1):
            start_point = split_points_with_t[i]
            end_point = split_points_with_t[i + 1]
            
            # Check if this segment is inside a symbol (should be skipped)
            seg_midpoint = (
                (start_point[0] + end_point[0]) / 2,
                (start_point[1] + end_point[1]) / 2
            )
            
            is_inside_symbol = False
            for symbol_data in intersecting_symbols:
                symbol_box = symbol_data['symbol_box']
                if (symbol_box.topX <= seg_midpoint[0] <= symbol_box.bottomX and
                    symbol_box.topY <= seg_midpoint[1] <= symbol_box.bottomY):
                    is_inside_symbol = True
                    break
            
            if not is_inside_symbol:
                # Only add segments that are outside symbols
                segment_length = math.sqrt(
                    (end_point[0] - start_point[0])**2 + 
                    (end_point[1] - start_point[1])**2
                )
                
                # Only add segments with meaningful length
                if segment_length > self.intersection_tolerance:
                    segments.append((start_point[0], start_point[1], end_point[0], end_point[1]))
        
        # If no valid segments, create connection points at symbol boundaries
        if not segments and intersecting_symbols:
            segments = self._create_symbol_connection_segments(pixel_line, intersecting_symbols)
        
        return {'segments': segments}
    
    def _create_symbol_connection_segments(self, pixel_line: Tuple[float, float, float, float], 
                                         intersecting_symbols: List[Dict]) -> List[Tuple[float, float, float, float]]:
        """Create short connection segments at symbol boundaries when line is completely inside symbols."""
        x1, y1, x2, y2 = pixel_line
        segments = []
        
        # Create short segments leading to symbol edges
        for symbol_data in intersecting_symbols:
            symbol_box = symbol_data['symbol_box']
            
            # Find the closest edge point
            center_x = (symbol_box.topX + symbol_box.bottomX) / 2
            center_y = (symbol_box.topY + symbol_box.bottomY) / 2
            
            # Create a short connection segment from line start to symbol edge
            edge_x = center_x
            edge_y = center_y
            
            # Adjust to actual edge
            if abs(x1 - center_x) > abs(y1 - center_y):
                edge_x = symbol_box.topX if x1 < center_x else symbol_box.bottomX
                edge_y = center_y
            else:
                edge_x = center_x
                edge_y = symbol_box.topY if y1 < center_y else symbol_box.bottomY
            
            connection_length = 5  # pixels
            dx = edge_x - x1
            dy = edge_y - y1
            length = math.sqrt(dx*dx + dy*dy)
            
            if length > 0:
                dx /= length
                dy /= length
                
                start_x = edge_x - dx * connection_length
                start_y = edge_y - dy * connection_length
                
                segments.append((start_x, start_y, edge_x, edge_y))
        
        return segments


class SymbolAwareLinePostProcessor:
    """
    Enhanced line post-processor that includes symbol-aware intersection handling.
    Extends the existing LinePostProcessor functionality.
    """
    
    def __init__(self, symbol_boxes: List[BoundingBox], base_processor=None, **kwargs):
        """
        Initialize with symbol boxes and optional base processor.
        
        Args:
            symbol_boxes: List of symbol bounding boxes
            base_processor: Optional existing LinePostProcessor instance
            **kwargs: Additional parameters for LinePostProcessor
        """
        self.symbol_boxes = symbol_boxes
        self.base_processor = base_processor
        
        # Initialize symbol-aware detector
        enable_symbol_awareness = os.environ.get('ENABLE_SYMBOL_AWARE_DETECTION', 'true').lower() == 'true'
        self.symbol_detector = SymbolAwareLineDetector(
            symbol_boxes=symbol_boxes,
            enable_symbol_awareness=enable_symbol_awareness
        )
        
        print(f"SymbolAwareLinePostProcessor initialized with {len(symbol_boxes)} symbols")
    
    def process_lines(self, line_segments: List[LineSegment], 
                     image_width: int, image_height: int) -> Tuple[List[LineSegment], List[Dict]]:
        """
        Process lines with symbol-aware intersection handling.
        
        Args:
            line_segments: List of detected line segments
            image_width: Image width in pixels
            image_height: Image height in pixels
            
        Returns:
            Tuple of (processed_lines, intersection_metadata)
        """
        print(f"Starting symbol-aware line processing: {len(line_segments)} input segments")
        
        # Step 1: Apply base post-processing if available
        if self.base_processor:
            processed_lines = self.base_processor.process_lines(line_segments, image_width, image_height)
            print(f"After base post-processing: {len(processed_lines)} segments")
        else:
            processed_lines = line_segments
        
        # Step 2: Apply symbol-aware intersection detection and resolution
        symbol_aware_lines, intersection_metadata = self.symbol_detector.detect_and_resolve_intersections(
            processed_lines, image_width, image_height
        )
        
        print(f"Final symbol-aware processing result: {len(symbol_aware_lines)} segments")
        
        return symbol_aware_lines, intersection_metadata
