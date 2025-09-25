"""
Junction detection service for identifying T-junctions and other line intersections.
"""

import logging
import math
from typing import List, Optional, Tuple, Dict
import numpy as np
from models import Junction, JunctionType, LineSegment

logger = logging.getLogger()


class JunctionDetector:
    """Service for detecting T-junctions and other line intersections"""
    
    def __init__(self, config: Dict):
        if not config:
            raise ValueError("Config is required - should be provided from index.py")
        self.config = config
        self.junction_counter = 0  # Simple counter for junction IDs
    
    def detect_junctions(self, line_segments: List[LineSegment]) -> List[Junction]:
        """
        Detect all junctions from a list of line segments
        
        Args:
            line_segments: List of line segments to analyze
            
        Returns:
            List of detected junctions
        """
        if len(line_segments) < 2:
            return []
        
        logger.info(f"Starting junction detection on {len(line_segments)} line segments")
        
        # Step 1: Find all line-to-line intersections
        intersection_candidates = self._find_line_intersections(line_segments)
        logger.info(f"Found {len(intersection_candidates)} intersection candidates")
        
        # Step 2: Classify intersection types (T-junction, cross, etc.)
        junctions = []
        for candidate in intersection_candidates:
            junction = self._classify_intersection(candidate, line_segments)
            if junction:
                junctions.append(junction)
        
        logger.info(f"Classified {len(junctions)} junctions")
        
        # Step 3: Cluster nearby junctions
        clustered_junctions = self._cluster_junctions(junctions)
        logger.info(f"After clustering: {len(clustered_junctions)} final junctions")
        
        return clustered_junctions
    
    def _find_line_intersections(self, line_segments: List[LineSegment]) -> List[Dict]:
        """
        Find all intersection points between line segments
        
        Returns:
            List of intersection candidates with metadata
        """
        intersection_candidates = []
        
        for i, line1 in enumerate(line_segments):
            for j, line2 in enumerate(line_segments[i+1:], start=i+1):
                # Skip very short lines
                if (self._calculate_line_length(line1) < self.config["minimum_line_length"] or
                    self._calculate_line_length(line2) < self.config["minimum_line_length"]):
                    continue
                
                intersection = self._calculate_line_intersection(line1, line2)
                if intersection:
                    intersection_candidates.append({
                        'point': intersection,
                        'line1_id': line1.id,
                        'line2_id': line2.id,
                        'line1_index': i,
                        'line2_index': j
                    })
        
        return intersection_candidates
    
    def _calculate_line_intersection(self, line1: LineSegment, line2: LineSegment) -> Optional[Tuple[float, float]]:
        """
        Calculate intersection point between two line segments using parametric equations.
        Handles multi-segment lines (like L-shapes) by checking all segment pairs.
        
        Args:
            line1: First line segment
            line2: Second line segment
            
        Returns:
            Intersection point (x, y) or None if no intersection
        """
        # For multi-segment lines, check all segment combinations
        line1_segments = self._get_line_segments(line1)
        line2_segments = self._get_line_segments(line2)
        
        for seg1 in line1_segments:
            for seg2 in line2_segments:
                intersection = self._calculate_segment_intersection(seg1, seg2)
                if intersection:
                    return intersection
        
        return None
    
    def _get_line_segments(self, line: LineSegment) -> List[Tuple[np.ndarray, np.ndarray]]:
        """
        Break a line into its constituent segments
        
        Args:
            line: Line segment (may have multiple points for L-shapes)
            
        Returns:
            List of (start_point, end_point) tuples for each segment
        """
        segments = []
        for i in range(len(line.points) - 1):
            start = np.array(line.points[i])
            end = np.array(line.points[i + 1])
            segments.append((start, end))
        return segments
    
    def _calculate_segment_intersection(self, seg1: Tuple[np.ndarray, np.ndarray], 
                                     seg2: Tuple[np.ndarray, np.ndarray]) -> Optional[Tuple[float, float]]:
        """
        Calculate intersection between two line segments
        
        Args:
            seg1: (start_point, end_point) for first segment
            seg2: (start_point, end_point) for second segment
            
        Returns:
            Intersection point or None
        """
        p1, p2 = seg1
        p3, p4 = seg2
        
        # Line 1: P = p1 + t*(p2-p1)
        # Line 2: Q = p3 + s*(p4-p3)
        # Intersection when P = Q
        
        d1 = p2 - p1  # Direction vector of line 1
        d2 = p4 - p3  # Direction vector of line 2
        
        # Handle parallel lines
        cross_product = np.cross(d1, d2)
        if abs(cross_product) < 1e-10:  # Lines are parallel
            return None
        
        # Calculate intersection parameters
        diff = p3 - p1
        t = np.cross(diff, d2) / cross_product
        s = np.cross(diff, d1) / cross_product
        
        # Check if intersection is within both line segments (with tolerance)
        tolerance = 0.1  # Allow slight extension beyond endpoints
        if (-tolerance <= t <= 1 + tolerance) and (-tolerance <= s <= 1 + tolerance):
            intersection_point = p1 + t * d1
            return (float(intersection_point[0]), float(intersection_point[1]))
        
        return None
    
    def _classify_intersection(self, candidate: Dict, line_segments: List[LineSegment]) -> Optional[Junction]:
        """
        Classify an intersection candidate as a specific junction type
        
        Args:
            candidate: Intersection candidate with point and line information
            line_segments: All line segments for context
            
        Returns:
            Junction object or None if not a valid junction
        """
        point = candidate['point']
        line1 = line_segments[candidate['line1_index']]
        line2 = line_segments[candidate['line2_index']]
        
        # Check if these lines are collinear - if so, they shouldn't form a junction
        if self._are_lines_collinear(line1, line2, point):
            logger.info(f"Lines {line1.id} and {line2.id} are collinear at {point} - skipping junction")
            return None
        
        # Calculate distances from intersection to line endpoints
        line1_distances = self._calculate_endpoint_distances(point, line1)
        line2_distances = self._calculate_endpoint_distances(point, line2)
        
        threshold = self.config["t_junction_endpoint_threshold"]
        
        # Check if intersection is near an endpoint of either line
        line1_near_endpoint = min(line1_distances) < threshold
        line2_near_endpoint = min(line2_distances) < threshold
        
        # Determine junction type
        junction_type = JunctionType.UNKNOWN
        confidence = 0.5
        
        if line1_near_endpoint and line2_near_endpoint:
            # Both lines terminate - L junction
            junction_type = JunctionType.L_JUNCTION
            confidence = 0.8
        elif line1_near_endpoint != line2_near_endpoint:
            # Exactly one line terminates - T junction
            junction_type = JunctionType.T_JUNCTION
            confidence = 0.9
        else:
            # Neither line terminates at intersection - Cross junction
            junction_type = JunctionType.CROSS_JUNCTION
            confidence = 0.7
        
        # Validate with angle analysis
        if self._validate_junction_angles(point, line1, line2, junction_type):
            confidence = min(confidence + 0.1, 1.0)
        else:
            confidence = max(confidence - 0.2, 0.1)
        
        # Only create junction if confidence is high enough
        if confidence < 0.5:
            return None
        
        # Generate simple junction ID using counter
        self.junction_counter += 1
        junction_id = str(self.junction_counter)
        
        return Junction(
            id=junction_id,
            point=point,
            junction_type=junction_type,
            connected_lines=[line1.id, line2.id],
            confidence=confidence
        )
    
    def _calculate_endpoint_distances(self, point: Tuple[float, float], line: LineSegment) -> List[float]:
        """Calculate distances from point to line endpoints"""
        p = np.array(point)
        start = np.array(line.points[0])
        end = np.array(line.points[-1])
        
        start_dist = np.linalg.norm(p - start)
        end_dist = np.linalg.norm(p - end)
        
        return [start_dist, end_dist]
    
    def _validate_junction_angles(self, point: Tuple[float, float], line1: LineSegment, 
                                 line2: LineSegment, junction_type: JunctionType) -> bool:
        """
        Validate junction based on angle analysis
        
        Args:
            point: Junction point
            line1: First line
            line2: Second line
            junction_type: Proposed junction type
            
        Returns:
            True if angles support the junction type
        """
        # Calculate line directions
        dir1 = self._calculate_line_direction(line1, point)
        dir2 = self._calculate_line_direction(line2, point)
        
        if dir1 is None or dir2 is None:
            return False
        
        # Calculate angle between lines
        angle = self._calculate_angle_between_vectors(dir1, dir2)
        angle_degrees = math.degrees(angle)
        
        tolerance = self.config["junction_angle_tolerance"]
        
        # Angle validation based on junction type
        if junction_type == JunctionType.T_JUNCTION:
            # T-junctions should be roughly perpendicular (90 degrees ± tolerance)
            return abs(angle_degrees - 90) <= tolerance or abs(angle_degrees - 270) <= tolerance
        elif junction_type == JunctionType.L_JUNCTION:
            # L-junctions can have various angles
            return 45 <= angle_degrees <= 135 or 225 <= angle_degrees <= 315
        elif junction_type == JunctionType.CROSS_JUNCTION:
            # Cross-junctions should be roughly perpendicular
            return abs(angle_degrees - 90) <= tolerance or abs(angle_degrees - 270) <= tolerance
        
        return True  # Default to valid for unknown types
    
    def _calculate_line_direction(self, line: LineSegment, reference_point: Tuple[float, float]) -> Optional[np.ndarray]:
        """Calculate line direction vector relative to a reference point"""
        ref = np.array(reference_point)
        start = np.array(line.points[0])
        end = np.array(line.points[-1])
        
        # Choose direction that points away from the reference point
        start_dist = np.linalg.norm(ref - start)
        end_dist = np.linalg.norm(ref - end)
        
        if start_dist < end_dist:
            direction = end - start
        else:
            direction = start - end
        
        # Normalize direction vector
        norm = np.linalg.norm(direction)
        if norm < 1e-10:
            return None
        
        return direction / norm
    
    def _calculate_angle_between_vectors(self, v1: np.ndarray, v2: np.ndarray) -> float:
        """Calculate angle between two vectors in radians"""
        dot_product = np.dot(v1, v2)
        # Clamp to avoid numerical errors
        dot_product = np.clip(dot_product, -1.0, 1.0)
        return math.acos(dot_product)
    
    def _calculate_line_length(self, line: LineSegment) -> float:
        """Calculate total length of a line segment"""
        if len(line.points) < 2:
            return 0.0
        
        total_length = 0.0
        for i in range(len(line.points) - 1):
            p1 = np.array(line.points[i])
            p2 = np.array(line.points[i + 1])
            total_length += np.linalg.norm(p2 - p1)
        
        return total_length
    
    def _cluster_junctions(self, junctions: List[Junction]) -> List[Junction]:
        """
        Cluster nearby junctions to handle detection noise
        
        Args:
            junctions: List of detected junctions
            
        Returns:
            List of clustered junctions
        """
        if not junctions:
            return []
        
        clustered = []
        used_indices = set()
        radius = self.config["junction_clustering_radius"]
        
        for i, junction in enumerate(junctions):
            if i in used_indices:
                continue
            
            # Find all junctions within clustering radius
            cluster = [junction]
            cluster_indices = {i}
            
            for j, other_junction in enumerate(junctions[i+1:], start=i+1):
                if j in used_indices:
                    continue
                
                distance = self._calculate_distance(junction.point, other_junction.point)
                if distance <= radius:
                    cluster.append(other_junction)
                    cluster_indices.add(j)
            
            # Mark all junctions in this cluster as used
            used_indices.update(cluster_indices)
            
            # Create merged junction from cluster
            merged_junction = self._merge_junction_cluster(cluster)
            clustered.append(merged_junction)
        
        return clustered
    
    def _merge_junction_cluster(self, cluster: List[Junction]) -> Junction:
        """
        Merge a cluster of nearby junctions into a single junction
        
        Args:
            cluster: List of junctions to merge
            
        Returns:
            Merged junction
        """
        if len(cluster) == 1:
            return cluster[0]
        
        # Calculate centroid of cluster points
        points = [j.point for j in cluster]
        centroid_x = sum(p[0] for p in points) / len(points)
        centroid_y = sum(p[1] for p in points) / len(points)
        centroid = (centroid_x, centroid_y)
        
        # Collect all connected lines
        all_connected_lines = []
        for junction in cluster:
            all_connected_lines.extend(junction.connected_lines)
        
        # Remove duplicates while preserving order
        unique_lines = list(dict.fromkeys(all_connected_lines))
        
        # Determine junction type based on number of connected lines
        if len(unique_lines) == 2:
            junction_type = JunctionType.L_JUNCTION
        elif len(unique_lines) == 3:
            junction_type = JunctionType.T_JUNCTION
        elif len(unique_lines) >= 4:
            junction_type = JunctionType.CROSS_JUNCTION
        else:
            junction_type = JunctionType.UNKNOWN
        
        # Average confidence
        avg_confidence = sum(j.confidence for j in cluster) / len(cluster)
        
        # Create simple merged junction ID using counter
        self.junction_counter += 1
        merged_id = str(self.junction_counter)
        
        return Junction(
            id=merged_id,
            point=centroid,
            junction_type=junction_type,
            connected_lines=unique_lines,
            confidence=avg_confidence
        )
    
    def _are_lines_collinear(self, line1: LineSegment, line2: LineSegment, intersection_point: Tuple[float, float]) -> bool:
        """
        Check if two lines are collinear (same direction) at their intersection point
        
        Args:
            line1: First line segment
            line2: Second line segment
            intersection_point: Point where lines intersect
            
        Returns:
            True if lines are collinear and shouldn't form a junction
        """
        # For multi-segment lines (like L-shapes), find the relevant segments near the intersection
        line1_segment = self._find_segment_near_point(line1, intersection_point)
        line2_segment = self._find_segment_near_point(line2, intersection_point)
        
        if line1_segment is None or line2_segment is None:
            return False
        
        # Calculate direction vectors for the relevant segments
        dir1 = np.array(line1_segment[1]) - np.array(line1_segment[0])
        dir2 = np.array(line2_segment[1]) - np.array(line2_segment[0])
        
        # Normalize direction vectors
        norm1 = np.linalg.norm(dir1)
        norm2 = np.linalg.norm(dir2)
        
        if norm1 < 1e-10 or norm2 < 1e-10:
            return False  # Can't determine direction
        
        dir1_normalized = dir1 / norm1
        dir2_normalized = dir2 / norm2
        
        # Check if directions are parallel (same or opposite)
        dot_product = np.dot(dir1_normalized, dir2_normalized)
        
        # Lines are collinear if dot product is close to 1 (same direction) or -1 (opposite direction)
        angle_threshold = 0.1  # ~5.7 degrees tolerance
        is_parallel = abs(abs(dot_product) - 1.0) < angle_threshold
        
        if is_parallel:
            logger.info(f"Lines {line1.id} and {line2.id} are collinear at intersection (dot product: {dot_product:.3f})")
            return True
        
        return False
    
    def _find_segment_near_point(self, line: LineSegment, point: Tuple[float, float]) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
        """
        Find the line segment that's closest to the given point
        
        Args:
            line: Line segment (may have multiple points for L-shapes)
            point: Point to find nearest segment for
            
        Returns:
            Tuple of (start_point, end_point) for the nearest segment, or None
        """
        if len(line.points) < 2:
            return None
        
        point_array = np.array(point)
        min_distance = float('inf')
        best_segment = None
        
        # Check each segment of the line
        for i in range(len(line.points) - 1):
            seg_start = line.points[i]
            seg_end = line.points[i + 1]
            
            # Calculate distance from point to this segment
            distance = self._point_to_segment_distance(point, seg_start, seg_end)
            
            if distance < min_distance:
                min_distance = distance
                best_segment = (seg_start, seg_end)
        
        return best_segment
    
    def _point_to_segment_distance(self, point: Tuple[float, float], 
                                   seg_start: Tuple[float, float], 
                                   seg_end: Tuple[float, float]) -> float:
        """Calculate distance from point to line segment"""
        p = np.array(point)
        a = np.array(seg_start)
        b = np.array(seg_end)
        
        # Vector from a to b
        ab = b - a
        # Vector from a to p
        ap = p - a
        
        # Project ap onto ab
        ab_length_sq = np.dot(ab, ab)
        if ab_length_sq == 0:
            return np.linalg.norm(ap)
        
        t = max(0, min(1, np.dot(ap, ab) / ab_length_sq))
        projection = a + t * ab
        
        return np.linalg.norm(p - projection)
    
    def _calculate_distance(self, point1: Tuple[float, float], point2: Tuple[float, float]) -> float:
        """Calculate Euclidean distance between two points"""
        p1 = np.array(point1)
        p2 = np.array(point2)
        return np.linalg.norm(p2 - p1)
