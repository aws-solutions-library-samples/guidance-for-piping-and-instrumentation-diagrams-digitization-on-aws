"""
Graph service for managing the NetworkX graph structure.
"""

from typing import List, Dict, Any
import networkx as nx
from models import GraphNodeType, Junction, JunctionType


class GraphService:
    """Service for managing the graph structure"""
    
    def __init__(self):
        self.graph = nx.Graph()
        
    def add_node(self, node_id: str, node_type: GraphNodeType, **kwargs):
        """Add a node to the graph"""
        self.graph.add_node(node_id, node_type=node_type, **kwargs)
        
    def add_edge(self, node_id_1: str, node_id_2: str, **kwargs):
        """Add an edge to the graph"""
        self.graph.add_edge(node_id_1, node_id_2, **kwargs)
        
    def get_node(self, node_id: str):
        """Get node data"""
        return self.graph.nodes[node_id]
        
    def get_degree(self, node_id: str) -> int:
        """Get degree of a node"""
        return self.graph.degree(node_id)
        
    def get_neighbors(self, node_id: str) -> List[str]:
        """Get neighbors of a node"""
        return list(self.graph.neighbors(node_id))
        
    def get_connected_components(self) -> List[List[str]]:
        """Get all connected components in the graph"""
        return list(nx.connected_components(self.graph))
    
    def add_junction_node(self, junction: Junction):
        """Add a junction node to the graph"""
        junction_id = f"junction-{junction.id}"
        self.add_node(
            junction_id,
            GraphNodeType.JUNCTION,
            point=junction.point,
            junction_type=junction.junction_type,
            connected_lines=junction.connected_lines,
            confidence=junction.confidence
        )
        return junction_id
    
    def connect_lines_through_junction(self, junction: Junction):
        """Connect lines through a junction node"""
        junction_id = f"junction-{junction.id}"
        
        # Connect each line to the junction
        for line_id in junction.connected_lines:
            line_node_id = f"line-{line_id}"
            if self.graph.has_node(line_node_id):
                self.add_edge(line_node_id, junction_id, junction_connection=True)
    
    def get_junction_nodes(self) -> Dict[str, Dict[str, Any]]:
        """Get all junction nodes from the graph"""
        junctions = {}
        for node_id, data in self.graph.nodes(data=True):
            if data.get('node_type') == GraphNodeType.JUNCTION:
                junctions[node_id] = data
        return junctions
    
    def get_nodes_by_type(self, node_type: GraphNodeType) -> Dict[str, Dict[str, Any]]:
        """Get all nodes of a specific type"""
        nodes = {}
        for node_id, data in self.graph.nodes(data=True):
            if data.get('node_type') == node_type:
                nodes[node_id] = data
        return nodes
    
    def replace_node_references(self, old_node_ids: List[str], new_node_id: str):
        """
        Replace all references to old nodes with the new node throughout the graph
        
        Args:
            old_node_ids: List of old node IDs to replace
            new_node_id: New node ID to replace them with
        """
        # Update junction connected_lines
        for node_id, data in self.graph.nodes(data=True):
            if data.get('node_type') == GraphNodeType.JUNCTION:
                connected_lines = data.get('connected_lines', [])
                updated_lines = []
                
                for line_id in connected_lines:
                    if line_id in old_node_ids:
                        if new_node_id not in updated_lines:  # Avoid duplicates
                            updated_lines.append(new_node_id)
                    else:
                        updated_lines.append(line_id)
                
                data['connected_lines'] = updated_lines
        
        # Update edges - replace connections to old nodes with connections to new node
        edges_to_process = []
        
        for edge in list(self.graph.edges(data=True)):
            node1, node2, edge_data = edge
            needs_update = False
            new_edge_nodes = [node1, node2]
            
            if node1 in old_node_ids:
                new_edge_nodes[0] = new_node_id
                needs_update = True
            if node2 in old_node_ids:
                new_edge_nodes[1] = new_node_id
                needs_update = True
            
            if needs_update:
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
            if self.graph.has_edge(*old_edge):
                self.graph.remove_edge(*old_edge)
            
            # Add new edge if it's not a self-loop and doesn't already exist
            if new_edge[0] != new_edge[1] and not self.graph.has_edge(*new_edge):
                self.graph.add_edge(new_edge[0], new_edge[1], **edge_data)
    
    def get_l_junctions(self) -> List[Dict[str, Any]]:
        """Get all L-junction nodes from the graph"""
        l_junctions = []
        for node_id, data in self.graph.nodes(data=True):
            if (data.get('node_type') == GraphNodeType.JUNCTION and 
                data.get('junction_type') == JunctionType.L_JUNCTION):
                l_junctions.append({
                    'id': node_id,
                    'data': data
                })
        return l_junctions
    
    def remove_nodes(self, node_ids: List[str]):
        """Remove multiple nodes from the graph"""
        for node_id in node_ids:
            if self.graph.has_node(node_id):
                self.graph.remove_node(node_id)
