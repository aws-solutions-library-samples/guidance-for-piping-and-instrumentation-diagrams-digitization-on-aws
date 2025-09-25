import networkx as nx
import numpy as np
from typing import Dict, Any
import math


class GraphRepresentationVisualizer:
    """Create graph representation visualizations using NetworkX"""
    
    def __init__(self, colors: Dict[str, str], config: Dict[str, Any]):
        self.colors = colors
        self.config = config
    
    def draw_graph(self, ax, graph_data: Dict[str, Any], params: Dict[str, Any] = None):
        """
        Draw the graph representation using NetworkX with dynamic parameters
        
        Args:
            ax: matplotlib axis
            graph_data: Graph data containing symbols, lines, junctions, connections
            params: Dynamic visualization parameters
        """
        if params is None:
            # Fallback to default parameters
            params = {
                'fonts': {'title': 16, 'label': 8, 'small': 6},
                'elements': {'line_width': 2, 'marker_size': 3000, 'junction_size_scale': 1.0},
                'layout_algorithm': 'spring',
                'show_detailed_labels': True
            }
        
        ax.set_title("Graph Representation", fontsize=params['fonts']['title'])
        
        # Create NetworkX graph
        G = nx.Graph()
        
        # First, collect all node IDs from connections to ensure we have everything
        all_node_ids = set()
        for connection in graph_data.get('connections', []):
            all_node_ids.add(connection['from'])
            all_node_ids.add(connection['to'])
        
        # Add nodes and colors
        node_colors = []
        node_labels = {}
        
        # Add symbol nodes
        for symbol in graph_data.get('symbols', []):
            node_id = f"symbol-{symbol['id']}"
            if node_id in all_node_ids:
                G.add_node(node_id)
                node_colors.append(self.colors['symbol'])
                
                # Create label with text association if present
                label = f"{symbol['type']}\n{symbol['id']}"
                if symbol.get('text_associated'):
                    label += f"\n'{symbol['text_associated']}'"
                node_labels[node_id] = label
        
        # Add line nodes
        for line in graph_data.get('lines', []):
            node_id = f"line-{line['id']}"
            if node_id in all_node_ids:
                G.add_node(node_id)
                node_colors.append(self.colors['line'])
                label = f"Line {line['id']}"
                if line.get('text_associated'):
                    label += f"\n'{line['text_associated']}'"
                node_labels[node_id] = label
        
        # Add junction nodes
        for junction in graph_data.get('junctions', []):
            node_id = f"junction-{junction['id']}"
            if node_id in all_node_ids:
                G.add_node(node_id)
                
                # Choose color based on junction type
                junction_type = junction.get('junction_type', 'unknown')
                if junction_type == 't_junction':
                    color = self.colors['t_junction']
                elif junction_type == 'cross_junction':
                    color = self.colors['cross_junction']
                elif junction_type == 'l_junction':
                    color = self.colors['l_junction']
                else:
                    color = self.colors['junction']
                
                node_colors.append(color)
                
                # Create junction label
                label = f"{junction_type.upper()}\nJ-{junction['id']}"
                if junction.get('confidence'):
                    label += f"\nConf: {junction['confidence']:.2f}"
                node_labels[node_id] = label
        
        # Handle any remaining nodes that weren't in the expected categories
        for node_id in all_node_ids:
            if not G.has_node(node_id):
                G.add_node(node_id)
                # Default color for unknown node types
                if node_id.startswith('line-virtual'):
                    node_colors.append(self.colors['virtual_line'])
                    node_labels[node_id] = f"Virtual\n{node_id}"
                else:
                    node_colors.append(self.colors['connection'])
                    node_labels[node_id] = node_id
                print(f"Warning: Unknown node type: {node_id}")
        
        # Add edges
        for connection in graph_data.get('connections', []):
            G.add_edge(connection['from'], connection['to'])
        
        # Layout the graph using optimal algorithm
        pos = self._get_optimal_layout(G, params['layout_algorithm'])
        
        # Calculate dynamic node size based on graph complexity
        base_node_size = params['elements']['marker_size'] * 30  # Convert to graph node size scale
        node_size = max(1000, min(base_node_size, 5000))  # Clamp between reasonable bounds
        
        # Draw nodes with dynamic sizing
        nx.draw_networkx_nodes(G, pos, 
                              node_color=node_colors,
                              node_size=node_size,
                              alpha=0.8,
                              ax=ax)
        
        # Draw edges with dynamic width
        nx.draw_networkx_edges(G, pos,
                              edge_color=self.colors['connection'],
                              width=params['elements']['line_width'],
                              alpha=0.6,
                              ax=ax)
        
        # Draw labels with dynamic font size, but only if detailed labels are enabled
        if params['show_detailed_labels']:
            nx.draw_networkx_labels(G, pos,
                                   labels=node_labels,
                                   font_size=params['fonts']['small'],
                                   font_weight='bold',
                                   ax=ax)
        else:
            # For high density, show simplified labels
            simplified_labels = {}
            for node_id, full_label in node_labels.items():
                # Take only the first line of the label
                simplified_labels[node_id] = full_label.split('\n')[0]
            nx.draw_networkx_labels(G, pos,
                                   labels=simplified_labels,
                                   font_size=max(params['fonts']['small'] - 1, 6),
                                   font_weight='bold',
                                   ax=ax)
        
        # Add statistics
        stats = graph_data.get('graph_stats', {})
        stats_text = f"Nodes: {stats.get('num_nodes', 0)}\n"
        stats_text += f"Edges: {stats.get('num_edges', 0)}\n"
        stats_text += f"Components: {stats.get('num_components', 0)}"
        
        ax.text(0.02, 0.98, stats_text,
                transform=ax.transAxes,
                verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
        
        ax.axis('off')
    
    def _get_optimal_layout(self, G: nx.Graph, algorithm: str = 'spring') -> Dict:
        """
        Get optimal layout for the graph based on the specified algorithm
        """
        try:
            if algorithm == 'kamada_kawai' and len(G.nodes()) > 2:
                return nx.kamada_kawai_layout(G, scale=2)
            elif algorithm == 'circular':
                return nx.circular_layout(G, scale=2)
            elif algorithm == 'shell' and len(G.nodes()) > 10:
                return nx.shell_layout(G, scale=2)
            else:
                # Default spring layout with adaptive parameters
                k = max(1, 3 / math.sqrt(len(G.nodes()))) if len(G.nodes()) > 1 else 1
                iterations = min(50, max(20, len(G.nodes()) * 2))
                return nx.spring_layout(G, k=k, iterations=iterations, scale=2)
        except:
            # Fallback to spring layout
            return nx.spring_layout(G, k=2, iterations=50, scale=2)
    
    def create_simple_visualization(self, graph_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a simple dictionary representation for visualization
        This can be used for web-based visualization libraries
        """
        nodes = []
        edges = []
        
        # Add symbol nodes
        for symbol in graph_data.get('symbols', []):
            nodes.append({
                'id': f"symbol-{symbol['id']}",
                'label': symbol['type'],
                'type': 'symbol',
                'x': (symbol['bbox'][0] + symbol['bbox'][2]) / 2,
                'y': (symbol['bbox'][1] + symbol['bbox'][3]) / 2,
                'data': symbol
            })
        
        # Add line nodes
        for line in graph_data.get('lines', []):
            points = line['points']
            center_x = sum(p[0] for p in points) / len(points)
            center_y = sum(p[1] for p in points) / len(points)
            
            nodes.append({
                'id': f"line-{line['id']}",
                'label': f"Line {line['id']}",
                'type': 'line',
                'x': center_x,
                'y': center_y,
                'text_associated': line.get('text_associated'),
                'data': line
            })
        
        # Add edges
        for connection in graph_data.get('connections', []):
            edges.append({
                'source': connection['from'],
                'target': connection['to']
            })
        
        return {
            'nodes': nodes,
            'edges': edges,
            'statistics': graph_data.get('graph_stats', {})
        }
