"""
Line merging strategy classes for different phases of line processing.
"""

import logging
import networkx as nx
from typing import List, Dict
from models import GraphNodeType, Junction, JunctionType
from graph_service import GraphService
from line_geometry import merge_line_points, merge_geometric_continuation_points, merge_collinear_segments
from line_utils import (
    calculate_distance, calculate_line_length_from_points, is_point_on_line, 
    point_to_line_segment_distance, are_geometric_continuations, 
    can_form_single_straight_line, is_valid_l_shape_candidate
)

logger = logging.getLogger()


class AberrantLineMerger:
    """Phase 1: Merge collinear segments that were split due to detection aberrations"""
    
    def __init__(self, graph_service: GraphService, config: Dict):
        self.graph_service = graph_service
        self.config = config
    
    def merge_aberrant_lines(self):
        """Phase 1: Merge collinear segments that were split due to detection aberrations"""
        logger.info("Starting Phase 1: Aberrant line merging")
        
        # Find groups of connected lines for aberration merging
        line_groups = self._find_connected_line_groups()
        
        # Merge each group using aberration logic only
        for group in line_groups:
            if len(group) > 1:
                self._merge_aberrant_line_group(group)
        
        logger.info("Completed Phase 1: Aberrant line merging")
    
    def _find_connected_line_groups(self) -> List[List[str]]:
        """Find groups of lines that are connected to each other"""
        # Build a subgraph containing only line nodes
        line_subgraph = nx.Graph()
        
        # Add all line nodes to the subgraph
        for node_id, data in self.graph_service.graph.nodes(data=True):
            if data['node_type'] == GraphNodeType.LINE and not data.get('virtual', False):
                line_subgraph.add_node(node_id)
        
        # Add edges between lines that are connected
        for edge in self.graph_service.graph.edges():
            if edge[0] in line_subgraph and edge[1] in line_subgraph:
                line_subgraph.add_edge(edge[0], edge[1])
        
        # Find connected components in the line subgraph
        return list(nx.connected_components(line_subgraph))
    
    def _merge_aberrant_line_group(self, line_group: List[str]):
        """Phase 1: Merge collinear segments that were split due to detection aberrations"""
        # Collect all line data
        lines_data = []
        text_associations = []
        symbol_connections = set()
        
        for line_id in line_group:
            line_data = self.graph_service.get_node(line_id)
            lines_data.append({
                'id': line_id,
                'points': line_data['points'],
                'text': line_data.get('text_associated')
            })
            
            # Collect text associations
            if line_data.get('text_associated'):
                text_associations.append(line_data['text_associated'])
            
            # Collect symbol connections
            for neighbor in self.graph_service.get_neighbors(line_id):
                if neighbor.startswith('symbol-'):
                    symbol_connections.add(neighbor)
        
        # Check if lines can form a single straight line
        tolerance = self.config.get('line_aberration_tolerance', 5.0)
        if not can_form_single_straight_line(lines_data, tolerance):
            # Complex geometry detected - don't merge, preserve all lines
            logger.info(f"Aberrant phase: preserving all lines in group {line_group} due to complex geometry")
            return
        
        # Only merge truly collinear segments
        merged_points = self._merge_aberrant_line_points(lines_data)
        
        # Create new merged line node
        line_group_list = list(line_group)
        merged_line_id = f"line-aberrant-{line_group_list[0].replace('line-', '')}"
        
        # Add the merged line node
        self.graph_service.add_node(
            merged_line_id,
            GraphNodeType.LINE,
            points=merged_points,
            text_associated=' | '.join(text_associations) if text_associations else None,
            merged_from=line_group_list
        )
        
        # Transfer symbol connections to the merged line
        for symbol_id in symbol_connections:
            self.graph_service.add_edge(merged_line_id, symbol_id)
        
        # Remove original line nodes and their edges
        for line_id in line_group:
            self.graph_service.graph.remove_node(line_id)
    
    def _merge_aberrant_line_points(self, lines_data: List[Dict]) -> List[List[float]]:
        """Merge only collinear segments, preserve T-junctions and L-shapes for later processing"""
        if len(lines_data) == 1:
            return lines_data[0]['points']
        
        # Use config tolerance or default
        tolerance = self.config.get('line_aberration_tolerance', 5.0)
        
        # For aberrant merging, we need to be very conservative
        # Only merge lines that are truly collinear and form a continuous straight line
        
        # Check if all lines can form a single straight line
        if can_form_single_straight_line(lines_data, tolerance):
            return merge_collinear_segments(lines_data, tolerance)
        else:
            # Mixed orientations or complex geometry - don't merge in aberration phase
            # Return the longest line as a fallback
            longest_line = max(lines_data, key=lambda x: calculate_line_length_from_points(x['points']))
            logger.info(f"Aberrant phase: preserving longest line from group due to complex geometry")
            return longest_line['points']


class GeometricContinuationMerger:
    """Phase 2: Merge lines that are geometric continuations of each other"""
    
    def __init__(self, graph_service: GraphService, config: Dict):
        self.graph_service = graph_service
        self.config = config
    
    def merge_geometric_continuations(self):
        """Phase 2: Merge lines that are geometric continuations of each other"""
        logger.info("Starting Phase 2: Geometric continuation merging")
        
        # Find line groups based on geometric proximity and collinearity
        continuation_groups = self._find_geometric_continuation_groups()
        
        # Merge each group
        for group in continuation_groups:
            if len(group) > 1:
                self._merge_geometric_continuation_group(group)
        
        logger.info("Completed Phase 2: Geometric continuation merging")
    
    def _find_geometric_continuation_groups(self) -> List[List[str]]:
        """Find groups of lines that are geometric continuations of each other"""
        tolerance = self.config.get('geometric_continuation_tolerance', 10.0)
        line_nodes = []
        
        # Collect all line nodes with their geometric data
        for node_id, data in self.graph_service.graph.nodes(data=True):
            if data['node_type'] == GraphNodeType.LINE and not data.get('virtual', False):
                points = data['points']
                if len(points) >= 2:
                    start = points[0]
                    end = points[-1]
                    
                    # Calculate line properties
                    dx = end[0] - start[0]
                    dy = end[1] - start[1]
                    length = (dx**2 + dy**2)**0.5
                    
                    if length > 0:
                        # Normalize direction
                        dir_x = dx / length
                        dir_y = dy / length
                        
                        line_nodes.append({
                            'id': node_id,
                            'start': start,
                            'end': end,
                            'length': length,
                            'dir_x': dir_x,
                            'dir_y': dir_y,
                            'horizontal': abs(dy) <= tolerance,
                            'vertical': abs(dx) <= tolerance
                        })
        
        # Find geometric continuation groups
        visited = set()
        groups = []
        
        for line_node in line_nodes:
            if line_node['id'] in visited:
                continue
                
            # Start a new group with this line
            group = [line_node['id']]
            visited.add(line_node['id'])
            
            # Find all lines that are geometric continuations
            self._find_continuation_lines(line_node, line_nodes, group, visited, tolerance)
            
            if len(group) > 1:
                groups.append(group)
                logger.info(f"Found geometric continuation group: {group}")
        
        return groups
    
    def _find_continuation_lines(self, base_line, all_lines, group, visited, tolerance):
        """Recursively find lines that continue from the base line"""
        for other_line in all_lines:
            if other_line['id'] in visited:
                continue
                
            # Check if this line is a geometric continuation of the base line
            if are_geometric_continuations(base_line, other_line, tolerance):
                group.append(other_line['id'])
                visited.add(other_line['id'])
                logger.info(f"Adding {other_line['id']} as continuation of {base_line['id']}")
                
                # Recursively find continuations of this line
                self._find_continuation_lines(other_line, all_lines, group, visited, tolerance)
    
    def _merge_geometric_continuation_group(self, line_group: List[str]):
        """Merge a group of geometric continuation lines"""
        # Collect all line data
        lines_data = []
        text_associations = []
        symbol_connections = set()
        
        for line_id in line_group:
            line_data = self.graph_service.get_node(line_id)
            lines_data.append({
                'id': line_id,
                'points': line_data['points'],
                'text': line_data.get('text_associated')
            })
            
            # Collect text associations
            if line_data.get('text_associated'):
                text_associations.append(line_data['text_associated'])
            
            # Collect symbol connections
            for neighbor in self.graph_service.get_neighbors(line_id):
                if neighbor.startswith('symbol-'):
                    symbol_connections.add(neighbor)
        
        # Create merged line points using geometric continuation logic
        merged_points = merge_geometric_continuation_points(lines_data, self.config)
        
        # Create new merged line node
        line_group_list = list(line_group)
        merged_line_id = f"line-geom-{line_group_list[0].replace('line-', '')}"
        
        # Add the merged line node
        self.graph_service.add_node(
            merged_line_id,
            GraphNodeType.LINE,
            points=merged_points,
            text_associated=' | '.join(text_associations) if text_associations else None,
            merged_from=line_group_list,
            merge_type='geometric_continuation'
        )
        
        # Transfer symbol connections to the merged line
        for symbol_id in symbol_connections:
            self.graph_service.add_edge(merged_line_id, symbol_id)
        
        # Remove original line nodes and their edges
        for line_id in line_group:
            self.graph_service.graph.remove_node(line_id)
        
        logger.info(f"Merged geometric continuation group {line_group} into {merged_line_id}")


class LShapeMerger:
    """Phase 3: Merge L-shaped lines based on L-junctions"""
    
    def __init__(self, graph_service: GraphService, config: Dict):
        self.graph_service = graph_service
        self.config = config
    
    def merge_l_shapes_with_protection(self, l_junctions: List[Junction], t_junctions: List[Junction]):
        """Phase 3: Merge L-shaped lines based on detected L-junctions"""
        logger.info("Starting Phase 3: L-junction-based line merging")
        logger.info(f"Processing {len(l_junctions)} L-junctions with {len(t_junctions)} T-junctions for protection")
        
        # Process each L-junction
        for l_junction in l_junctions:
            self._merge_lines_at_l_junction(l_junction, t_junctions)
        
        logger.info("Completed Phase 3: L-junction-based line merging")
    
    def _merge_lines_at_l_junction(self, l_junction: Junction, t_junctions: List[Junction]):
        """
        Merge two lines connected at an L-junction into a single L-shaped line
        
        Args:
            l_junction: L-junction object to process
            t_junctions: List of T-junctions that should prevent merging
        """
        junction_id = l_junction.id
        connected_lines = l_junction.connected_lines
        
        logger.info(f"Processing L-junction {junction_id} with connected lines: {connected_lines}")
        
        # L-junctions should have exactly 2 connected lines
        if len(connected_lines) != 2:
            logger.warning(f"L-junction {junction_id} has {len(connected_lines)} connected lines, expected 2")
            return
        
        line1_id, line2_id = connected_lines
        
        # Convert line IDs to graph node IDs (add 'line-' prefix if not present)
        line1_node_id = line1_id if line1_id.startswith('line-') else f'line-{line1_id}'
        line2_node_id = line2_id if line2_id.startswith('line-') else f'line-{line2_id}'
        
        # Check if these lines still exist in the graph (they might have been merged already)
        if not (self.graph_service.graph.has_node(line1_node_id) and self.graph_service.graph.has_node(line2_node_id)):
            logger.info(f"One or both lines {line1_node_id}, {line2_node_id} no longer exist - skipping")
            return
        
        # Check if merging these lines would interfere with T-junctions
        if self._would_interfere_with_t_junctions([line1_id, line2_id], t_junctions):
            logger.info(f"Skipping L-junction merge due to T-junction protection")
            return
        
        # Get line data
        line1_data = self.graph_service.get_node(line1_node_id)
        line2_data = self.graph_service.get_node(line2_node_id)
        
        # Collect data for merging
        lines_data = [
            {
                'id': line1_node_id,
                'points': line1_data['points'],
                'text': line1_data.get('text_associated')
            },
            {
                'id': line2_node_id,
                'points': line2_data['points'],
                'text': line2_data.get('text_associated')
            }
        ]
        
        # Collect text associations
        text_associations = []
        if line1_data.get('text_associated'):
            text_associations.append(line1_data['text_associated'])
        if line2_data.get('text_associated'):
            text_associations.append(line2_data['text_associated'])
        
        # Create L-shaped line points
        merged_points = merge_line_points(lines_data)
        
        # Create new merged line ID
        clean_line1_id = line1_id.replace('line-', '')
        clean_line2_id = line2_id.replace('line-', '')
        merged_line_id = f"line-l-junction-{clean_line1_id}-{clean_line2_id}"
        
        logger.info(f"Creating merged L-shaped line: {merged_line_id}")
        
        # Add the merged line node
        self.graph_service.add_node(
            merged_line_id,
            GraphNodeType.LINE,
            points=merged_points,
            text_associated=' | '.join(text_associations) if text_associations else None,
            merged_from=[line1_id, line2_id],
            merge_type='l_junction'
        )
        
        # Update all references in the graph to point to the new merged line
        # But be selective about symbol connections - only transfer if geometrically appropriate
        self._transfer_connections_selectively([line1_node_id, line2_node_id], merged_line_id, merged_points)
        
        # Remove the original lines and the L-junction
        self.graph_service.remove_nodes([line1_node_id, line2_node_id])
        
        logger.info(f"Successfully merged L-junction: {line1_node_id} + {line2_node_id} -> {merged_line_id}")
    
    def _would_interfere_with_t_junctions(self, line_ids: List[str], protection_junctions: List[Junction]) -> bool:
        """
        Check if merging these lines would interfere with existing T-junctions
        
        Args:
            line_ids: Lines that would be merged
            protection_junctions: T-junctions to protect
            
        Returns:
            True if merging would interfere with T-junctions
        """
        if not protection_junctions:
            return False
        
        logger.info(f"Checking T-junction interference for lines: {line_ids}")
        
        for junction in protection_junctions:
            if junction.junction_type == JunctionType.T_JUNCTION:
                junction_lines = set(junction.connected_lines)
                merge_lines = set(line_ids)
                
                # Only prevent merging if BOTH lines being merged are involved in the same T-junction
                # If only one line is involved, the merge can proceed and the T-junction 
                # will be maintained with the merged line
                overlap = junction_lines.intersection(merge_lines)
                if len(overlap) >= 2:
                    logger.info(f"T-junction {junction.id} involves multiple lines being merged ({overlap}) - preventing merge")
                    return True
                elif len(overlap) == 1:
                    logger.info(f"T-junction {junction.id} involves one line being merged ({overlap}) - merge allowed, T-junction will be preserved")
        
        return False
    
    def _transfer_connections_selectively(self, old_line_ids: List[str], new_line_id: str, new_line_points: List[List[float]]):
        """
        Transfer connections from old lines to new line, but be selective about symbol connections
        """
        from geometry import calculate_enhanced_line_to_bbox_distance
        from models import BoundingBox
        
        # First, update junction connected_lines (always transfer these)
        for node_id, data in self.graph_service.graph.nodes(data=True):
            if data.get('node_type') == GraphNodeType.JUNCTION:
                connected_lines = data.get('connected_lines', [])
                updated_lines = []
                
                for line_id in connected_lines:
                    if line_id in old_line_ids:
                        if new_line_id not in updated_lines:  # Avoid duplicates
                            updated_lines.append(new_line_id)
                    else:
                        updated_lines.append(line_id)
                
                data['connected_lines'] = updated_lines
        
        # Handle edge updates selectively
        edges_to_process = []
        
        for edge in list(self.graph_service.graph.edges(data=True)):
            node1, node2, edge_data = edge
            needs_update = False
            new_edge_nodes = [node1, node2]
            
            if node1 in old_line_ids:
                new_edge_nodes[0] = new_line_id
                needs_update = True
            if node2 in old_line_ids:
                new_edge_nodes[1] = new_line_id
                needs_update = True
            
            if needs_update:
                # Check if this involves a symbol connection
                is_symbol_connection = (node1.startswith('symbol-') or node2.startswith('symbol-'))
                
                if is_symbol_connection:
                    # For symbol connections, check if the symbol is geometrically close to the merged line
                    symbol_id = node1 if node1.startswith('symbol-') else node2
                    symbol_data = self.graph_service.get_node(symbol_id)
                    
                    # Convert bbox to BoundingBox object
                    bbox_data = symbol_data['bbox']
                    if hasattr(bbox_data, 'topX'):
                        # Already a BoundingBox object
                        symbol_bbox = bbox_data
                    else:
                        # It's a list [topX, topY, bottomX, bottomY]
                        symbol_bbox = BoundingBox(
                            topX=bbox_data[0],
                            topY=bbox_data[1],
                            bottomX=bbox_data[2],
                            bottomY=bbox_data[3]
                        )
                    
                    # Calculate distance from symbol to merged line
                    distance = calculate_enhanced_line_to_bbox_distance(new_line_points, symbol_bbox)
                    threshold = self.config.get("graph_distance_threshold_for_symbols", 60)
                    
                    logger.info(f"Checking symbol {symbol_id} connection to {new_line_id}: distance={distance:.2f}, threshold={threshold}")
                    
                    if distance <= threshold:
                        logger.info(f"Transferring symbol connection: {symbol_id} to {new_line_id} (distance: {distance:.2f} <= threshold: {threshold})")
                        edges_to_process.append({
                            'old_edge': (node1, node2),
                            'new_edge': tuple(new_edge_nodes),
                            'edge_data': edge_data
                        })
                    else:
                        logger.info(f"Skipping symbol connection: {symbol_id} to {new_line_id} (distance: {distance:.2f} > threshold: {threshold})")
                        # Just remove the old edge without adding a new one
                        edges_to_process.append({
                            'old_edge': (node1, node2),
                            'new_edge': None,
                            'edge_data': edge_data
                        })
                else:
                    # For non-symbol connections (lines, junctions), always transfer
                    edges_to_process.append({
                        'old_edge': (node1, node2),
                        'new_edge': tuple(new_edge_nodes),
                        'edge_data': edge_data
                    })
        
        # Apply edge updates
        for edge_info in edges_to_process:
            old_edge = edge_info['old_edge']
            new_edge = edge_info['new_edge']
            edge_data = edge_info['edge_data']
            
            # Remove old edge
            if self.graph_service.graph.has_edge(*old_edge):
                self.graph_service.graph.remove_edge(*old_edge)
            
            # Add new edge if specified and not a self-loop
            if new_edge is not None and new_edge[0] != new_edge[1] and not self.graph_service.graph.has_edge(*new_edge):
                self.graph_service.graph.add_edge(new_edge[0], new_edge[1], **edge_data)
    
    def _find_connected_line_groups(self) -> List[List[str]]:
        """Find groups of lines that are connected to each other"""
        # Build a subgraph containing only line nodes
        line_subgraph = nx.Graph()
        
        # Add all line nodes to the subgraph
        for node_id, data in self.graph_service.graph.nodes(data=True):
            if data['node_type'] == GraphNodeType.LINE and not data.get('virtual', False):
                line_subgraph.add_node(node_id)
        
        # Add edges between lines that are connected
        for edge in self.graph_service.graph.edges():
            if edge[0] in line_subgraph and edge[1] in line_subgraph:
                line_subgraph.add_edge(edge[0], edge[1])
        
        # Find connected components in the line subgraph
        return list(nx.connected_components(line_subgraph))
    
    def _merge_l_shaped_line_group(self, line_group: List[str], junctions: List[Junction]):
        """Phase 3: Merge L-shaped lines while avoiding T-junctions"""
        # Check if this group has a T-junction that prevents L-shape merging
        if self._has_t_junction_in_group(line_group, junctions):
            logger.info(f"Skipping L-shape merge for group {line_group} due to T-junction")
            return
        
        # Collect all line data
        lines_data = []
        text_associations = []
        symbol_connections = set()
        
        for line_id in line_group:
            line_data = self.graph_service.get_node(line_id)
            lines_data.append({
                'id': line_id,
                'points': line_data['points'],
                'text': line_data.get('text_associated')
            })
            
            # Collect text associations
            if line_data.get('text_associated'):
                text_associations.append(line_data['text_associated'])
            
            # Collect symbol connections
            for neighbor in self.graph_service.get_neighbors(line_id):
                if neighbor.startswith('symbol-'):
                    symbol_connections.add(neighbor)
        
        # Check if this is a valid L-shape candidate
        tolerance = self.config.get('line_aberration_tolerance', 5.0)
        if not is_valid_l_shape_candidate(lines_data, tolerance):
            logger.info(f"Group {line_group} is not a valid L-shape candidate")
            return
        
        # Create L-shaped line
        merged_points = merge_line_points(lines_data)
        
        # Create new merged line node
        line_group_list = list(line_group)
        merged_line_id = f"line-l-shape-{line_group_list[0].replace('line-', '')}"
        
        # Add the merged line node
        self.graph_service.add_node(
            merged_line_id,
            GraphNodeType.LINE,
            points=merged_points,
            text_associated=' | '.join(text_associations) if text_associations else None,
            merged_from=line_group_list
        )
        
        # Transfer symbol connections to the merged line
        for symbol_id in symbol_connections:
            self.graph_service.add_edge(merged_line_id, symbol_id)
        
        # Remove original line nodes and their edges
        for line_id in line_group:
            self.graph_service.graph.remove_node(line_id)
    
    def _has_t_junction_in_group(self, line_group: List[str], junctions: List[Junction]) -> bool:
        """Check if any T-junction exists between lines in this group"""
        if not junctions:
            return False
        
        logger.info(f"Checking T-junction protection for group: {line_group}")
        logger.info(f"Available junctions: {[f'{j.id}({j.junction_type.value})' for j in junctions]}")
        
        # Get line data for the group to check geometric overlap
        group_lines_data = []
        for line_id in line_group:
            line_data = self.graph_service.get_node(line_id)
            group_lines_data.append({
                'id': line_id,
                'points': line_data['points']
            })
        
        for junction in junctions:
            # Check both T-junctions and L-junctions that should be preserved
            if junction.junction_type in [JunctionType.T_JUNCTION, JunctionType.L_JUNCTION]:
                junction_point = junction.point
                logger.info(f"Checking {junction.junction_type.value} {junction.id} at {junction_point}")
                
                # Check if the T-junction point is geometrically close to any lines in our group
                tolerance = 15.0  # Tolerance for junction proximity
                lines_near_junction = 0
                
                for line_data in group_lines_data:
                    points = line_data['points']
                    
                    # Check if junction point is on or near this line
                    if is_point_on_line(junction_point, points, tolerance):
                        lines_near_junction += 1
                        logger.info(f"Junction {junction.id} is near line {line_data['id']}")
                
                # If 2 or more lines in the group are near this T-junction, prevent merging
                if lines_near_junction >= 2:
                    logger.info(f"T-junction {junction.id} affects {lines_near_junction} lines in group - preventing L-shape merge")
                    return True
                    
                # Additional check: if this group forms the exact geometry that would create this T-junction
                if self._group_would_create_t_junction(group_lines_data, junction_point, tolerance):
                    logger.info(f"Group would create T-junction at {junction_point} - preventing L-shape merge")
                    return True
        
        logger.info(f"No T-junction protection needed for group {line_group}")
        return False
    
    def _group_would_create_t_junction(self, group_lines_data, junction_point, tolerance):
        """Check if merging this group would eliminate a T-junction"""
        if len(group_lines_data) != 2:
            return False  # T-junctions typically involve 2 main lines
        
        line1_points = group_lines_data[0]['points']
        line2_points = group_lines_data[1]['points']
        
        # Check if both lines pass through or near the junction point
        line1_near_junction = is_point_on_line(junction_point, line1_points, tolerance)
        line2_near_junction = is_point_on_line(junction_point, line2_points, tolerance)
        
        if line1_near_junction and line2_near_junction:
            # Check if lines have different orientations (indicating T-junction)
            line1_start, line1_end = line1_points[0], line1_points[-1]
            line2_start, line2_end = line2_points[0], line2_points[-1]
            
            # Calculate orientations
            line1_dx = abs(line1_end[0] - line1_start[0])
            line1_dy = abs(line1_end[1] - line1_start[1])
            line2_dx = abs(line2_end[0] - line2_start[0])
            line2_dy = abs(line2_end[1] - line2_start[1])
            
            # Check if one is vertical and one is horizontal (classic T-junction)
            line1_vertical = line1_dx <= tolerance
            line1_horizontal = line1_dy <= tolerance
            line2_vertical = line2_dx <= tolerance
            line2_horizontal = line2_dy <= tolerance
            
            return (line1_vertical and line2_horizontal) or (line1_horizontal and line2_vertical)
        
        return False
