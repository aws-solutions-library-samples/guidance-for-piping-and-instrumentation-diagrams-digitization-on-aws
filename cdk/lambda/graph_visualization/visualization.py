import matplotlib.pyplot as plt
import numpy as np
from typing import Dict, Any, List, Tuple
import io
import math
import logging
import os

# Set up logging
logger = logging.getLogger()

from physical_layout import PhysicalLayoutVisualizer
from graph_representation import GraphRepresentationVisualizer


class GraphVisualizer:
    """Create visualizations of P&ID graphs using separate layout and graph visualizers"""
    
    def __init__(self):
        self.colors = {
            'symbol': '#FF6B6B',
            'line': '#4ECDC4',
            'text': '#45B7D1',
            'virtual_line': '#95E1D3',
            'connection': '#F7B731',
            'junction': '#E74C3C',
            't_junction': '#C0392B',
            'cross_junction': '#8E44AD',
            'l_junction': '#27AE60'
        }
        
        # Configuration for different visualization modes
        self.config = {
            'min_figure_size': (15, 8),
            'max_figure_size': (40, 30),
            'base_dpi': 150,
            'high_density_dpi': 200,
            'density_threshold': 0.01,  # elements per unit area
            'min_font_size': 6,
            'max_font_size': 14,
            'min_padding': 50,
            'max_padding': 200,
            # Label sizing configuration
            'label_config': {
                'min_font_size': 4,
                'max_font_size': 8,
                'symbol_font_scale': 0.8,  # Scale font based on symbol size
                'line_font_scale': 0.4,    # Scale font based on line length (more conservative)
                'max_text_width_ratio': 0.9,  # Max text width as ratio of element size
                'text_truncate_length': 15,   # Max characters before truncation (more aggressive)
                'min_element_size_for_label': 20,  # Min element size to show labels (higher threshold)
                'offset_scale_factor': 0.2,   # Scale offset based on element size (more conservative)
                'min_line_label_offset': 15,  # Minimum offset for line labels
                'max_line_label_offset': 60,  # Maximum offset for line labels
                'symbol_collision_buffer': 10  # Buffer around symbols to avoid collisions
            }
        }
        
        # Initialize separate visualizers
        self.physical_layout_visualizer = PhysicalLayoutVisualizer(self.colors, self.config)
        self.graph_representation_visualizer = GraphRepresentationVisualizer(self.colors, self.config)
    
    def _analyze_content_density(self, graph_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze content density to determine appropriate visualization parameters
        Returns analysis results including density metrics and suggested parameters
        """
        # Calculate content bounds
        min_x, min_y = float('inf'), float('inf')
        max_x, max_y = float('-inf'), float('-inf')
        
        # Count elements
        num_symbols = len(graph_data.get('symbols', []))
        num_lines = len(graph_data.get('lines', []))
        num_junctions = len(graph_data.get('junctions', []))
        num_connections = len(graph_data.get('connections', []))
        total_elements = num_symbols + num_lines + num_junctions
        
        # Update bounds from all elements
        for symbol in graph_data.get('symbols', []):
            bbox = symbol['bbox']
            min_x = min(min_x, bbox[0])
            min_y = min(min_y, bbox[1])
            max_x = max(max_x, bbox[2])
            max_y = max(max_y, bbox[3])
        
        for line in graph_data.get('lines', []):
            for point in line['points']:
                min_x = min(min_x, point[0])
                min_y = min(min_y, point[1])
                max_x = max(max_x, point[0])
                max_y = max(max_y, point[1])
        
        for junction in graph_data.get('junctions', []):
            point = junction['point']
            min_x = min(min_x, point[0])
            min_y = min(min_y, point[1])
            max_x = max(max_x, point[0])
            max_y = max(max_y, point[1])
        
        # Calculate area and density - handle empty data
        if min_x != float('inf') and total_elements > 0:
            content_width = max_x - min_x
            content_height = max_y - min_y
            content_area = content_width * content_height
            density = total_elements / content_area if content_area > 0 else 0
        else:
            # Default bounds for empty data
            min_x, min_y, max_x, max_y = 0, 0, 1000, 1000
            content_width = content_height = 1000
            content_area = 1000000
            density = 0
        
        # Calculate complexity metrics
        has_text_labels = any(s.get('text_associated') for s in graph_data.get('symbols', [])) or \
                         any(l.get('text_associated') for l in graph_data.get('lines', []))
        
        complexity_score = (
            num_symbols * 1.0 +
            num_lines * 0.8 +
            num_junctions * 1.2 +
            num_connections * 0.5 +
            (50 if has_text_labels else 0)
        )
        
        return {
            'bounds': {'min_x': min_x, 'min_y': min_y, 'max_x': max_x, 'max_y': max_y},
            'dimensions': {'width': content_width, 'height': content_height, 'area': content_area},
            'counts': {'symbols': num_symbols, 'lines': num_lines, 'junctions': num_junctions, 'connections': num_connections, 'total': total_elements},
            'density': density,
            'complexity_score': complexity_score,
            'has_text_labels': has_text_labels,
            'is_high_density': density > self.config['density_threshold']
        }
    
    def _calculate_dynamic_parameters(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate dynamic visualization parameters based on content analysis
        Returns parameters for figure size, fonts, padding, etc.
        """
        bounds = analysis['bounds']
        dimensions = analysis['dimensions']
        complexity = analysis['complexity_score']
        is_high_density = analysis['is_high_density']
        
        # Calculate aspect ratio
        if dimensions['width'] > 0 and dimensions['height'] > 0:
            aspect_ratio = dimensions['width'] / dimensions['height']
        else:
            aspect_ratio = 1.6  # Default aspect ratio
        
        # Calculate base figure size based on content dimensions and complexity
        base_width = max(self.config['min_figure_size'][0], min(dimensions['width'] / 100, self.config['max_figure_size'][0]))
        base_height = max(self.config['min_figure_size'][1], min(dimensions['height'] / 100, self.config['max_figure_size'][1]))
        
        # Scale based on complexity
        complexity_factor = min(1.0 + (complexity / 500), 2.0)  # Scale up to 2x for very complex diagrams
        
        figure_width = min(base_width * complexity_factor, self.config['max_figure_size'][0])
        figure_height = min(base_height * complexity_factor, self.config['max_figure_size'][1])
        
        # Adjust for high density content
        if is_high_density:
            figure_width *= 1.3
            figure_height *= 1.3
        
        # Calculate padding based on figure size and density
        if is_high_density:
            padding = max(self.config['min_padding'], min(dimensions['width'] * 0.05, self.config['max_padding']))
        else:
            padding = self.config['min_padding']
        
        # Calculate font sizes based on figure size
        font_scale = min(figure_width / 20, figure_height / 15)
        title_font_size = max(self.config['min_font_size'] + 4, min(16 * font_scale, self.config['max_font_size'] + 4))
        label_font_size = max(self.config['min_font_size'], min(10 * font_scale, self.config['max_font_size']))
        small_font_size = max(self.config['min_font_size'] - 1, min(8 * font_scale, self.config['max_font_size'] - 2))
        
        # Calculate element sizes
        line_width = 2 if not is_high_density else 1.5
        marker_size = 100 if not is_high_density else 80
        junction_size_scale = 1.0 if not is_high_density else 0.8
        
        # Calculate DPI based on density
        dpi = self.config['high_density_dpi'] if is_high_density else self.config['base_dpi']
        
        # Determine optimal layout algorithm for graph representation
        layout_algorithm = 'spring'  # Default
        if analysis['counts']['total'] > 50:
            layout_algorithm = 'kamada_kawai'
        elif analysis['counts']['total'] > 100:
            layout_algorithm = 'circular'
        
        return {
            'figure_size': (figure_width, figure_height),
            'padding': padding,
            'dpi': dpi,
            'fonts': {
                'title': title_font_size,
                'label': label_font_size,
                'small': small_font_size
            },
            'elements': {
                'line_width': line_width,
                'marker_size': marker_size,
                'junction_size_scale': junction_size_scale
            },
            'layout_algorithm': layout_algorithm,
            'show_detailed_labels': not is_high_density or analysis['counts']['total'] < 30
        }
    
        
    def create_visualization(self, graph_data: Dict[str, Any], notes_info: Dict[str, Any] = None) -> bytes:
        """
        Create a visualization of the graph with dynamic sizing and adaptive parameters
        
        Args:
            graph_data: Graph data containing symbols, lines, junctions, connections
            notes_info: Optional notes cutting area information from notes processor
            
        Returns:
            PNG image as bytes
        """
        try:
            # Analyze content density and calculate dynamic parameters
            analysis = self._analyze_content_density(graph_data)
            params = self._calculate_dynamic_parameters(analysis)
            
            # Log analysis for debugging
            logger.info(f"Content analysis: {analysis['counts']['total']} elements, "
                  f"density: {analysis['density']:.6f}, "
                  f"high_density: {analysis['is_high_density']}")
            logger.info(f"Dynamic params: figure_size={params['figure_size']}, "
                  f"padding={params['padding']}, "
                  f"layout_algorithm={params['layout_algorithm']}")
            
            if notes_info:
                logger.info(f"Notes cutting area info provided: {notes_info}")
            
            # Create figure with dynamic size
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=params['figure_size'])
            
            # Draw physical layout with dynamic parameters and notes info
            self.physical_layout_visualizer.draw_layout(ax1, graph_data, params, notes_info)
            
            # Draw graph representation with dynamic parameters
            self.graph_representation_visualizer.draw_graph(ax2, graph_data, params)
            
            # Adjust layout with extra spacing for high density content
            if analysis['is_high_density']:
                plt.tight_layout(pad=3.0)
            else:
                plt.tight_layout(pad=2.0)
            
            # Convert to bytes with dynamic DPI
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=params['dpi'], bbox_inches='tight', 
                       facecolor='white', edgecolor='none')
            buf.seek(0)
            image_bytes = buf.read()
            plt.close()
            
            return image_bytes
            
        except Exception as e:
            logger.error(f"Error creating visualization: {str(e)}")
            # Fallback to simple visualization
            try:
                fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(20, 10))
                self.physical_layout_visualizer.draw_layout(ax1, graph_data, notes_info=notes_info)
                self.graph_representation_visualizer.draw_graph(ax2, graph_data)
                plt.tight_layout()
                
                buf = io.BytesIO()
                plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
                buf.seek(0)
                image_bytes = buf.read()
                plt.close()
                
                return image_bytes
            except:
                return None
    
    def create_physical_layout_visualization(self, graph_data: Dict[str, Any], notes_info: Dict[str, Any] = None) -> bytes:
        """
        Create a visualization of only the physical layout
        
        Args:
            graph_data: Graph data containing symbols, lines, junctions, connections
            notes_info: Optional notes cutting area information from notes processor
            
        Returns:
            PNG image as bytes showing only the physical layout
        """
        try:
            logger.info(f"Starting physical layout visualization creation")
            logger.debug(f"Graph data keys: {list(graph_data.keys())}")
            logger.info(f"Symbols: {len(graph_data.get('symbols', []))}, Lines: {len(graph_data.get('lines', []))}, Junctions: {len(graph_data.get('junctions', []))}")
            
            # Check if we have any data to visualize
            total_elements = len(graph_data.get('symbols', [])) + len(graph_data.get('lines', [])) + len(graph_data.get('junctions', []))
            if total_elements == 0:
                logger.warning("No elements to visualize - skipping physical layout visualization")
                return None
            
            # Analyze content density and calculate dynamic parameters
            analysis = self._analyze_content_density(graph_data)
            params = self._calculate_dynamic_parameters(analysis)
            
            logger.info(f"Creating physical layout visualization with {analysis['counts']['total']} elements")
            logger.debug(f"Figure size: {params['figure_size']}, DPI: {params['dpi']}")
            
            # Create single figure for physical layout
            fig, ax = plt.subplots(1, 1, figsize=params['figure_size'])
            logger.debug(f"Created matplotlib figure")
            
            # Draw physical layout with dynamic parameters and notes info
            logger.debug(f"Calling physical_layout_visualizer.draw_layout")
            self.physical_layout_visualizer.draw_layout(ax, graph_data, params, notes_info)
            logger.debug(f"Completed draw_layout call")
            
            # Adjust layout
            plt.tight_layout(pad=2.0)
            
            # Convert to bytes with dynamic DPI
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=params['dpi'], bbox_inches='tight', 
                       facecolor='white', edgecolor='none')
            buf.seek(0)
            image_bytes = buf.read()
            plt.close()
            
            logger.info(f"Successfully created physical layout visualization ({len(image_bytes)} bytes)")
            return image_bytes
            
        except Exception as e:
            logger.error(f"Error creating physical layout visualization: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            # Fallback to simple visualization
            try:
                logger.info(f"Attempting fallback visualization")
                fig, ax = plt.subplots(1, 1, figsize=(16, 12))
                self.physical_layout_visualizer.draw_layout(ax, graph_data, notes_info=notes_info)
                plt.tight_layout()
                
                buf = io.BytesIO()
                plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
                buf.seek(0)
                image_bytes = buf.read()
                plt.close()
                
                logger.info(f"Fallback visualization successful ({len(image_bytes)} bytes)")
                return image_bytes
            except Exception as fallback_e:
                logger.error(f"Fallback visualization also failed: {str(fallback_e)}")
                return None
    
    def create_graph_representation_visualization(self, graph_data: Dict[str, Any]) -> bytes:
        """
        Create a visualization of only the graph representation
        
        Args:
            graph_data: Graph data containing symbols, lines, junctions, connections
            
        Returns:
            PNG image as bytes showing only the graph representation
        """
        try:
            # Analyze content density and calculate dynamic parameters
            analysis = self._analyze_content_density(graph_data)
            params = self._calculate_dynamic_parameters(analysis)
            
            logger.info(f"Creating graph representation visualization with {analysis['counts']['total']} elements")
            
            # Create single figure for graph representation
            fig, ax = plt.subplots(1, 1, figsize=params['figure_size'])
            
            # Draw graph representation with dynamic parameters
            self.graph_representation_visualizer.draw_graph(ax, graph_data, params)
            
            # Adjust layout
            plt.tight_layout(pad=2.0)
            
            # Convert to bytes with dynamic DPI
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=params['dpi'], bbox_inches='tight', 
                       facecolor='white', edgecolor='none')
            buf.seek(0)
            image_bytes = buf.read()
            plt.close()
            
            return image_bytes
            
        except Exception as e:
            logger.error(f"Error creating graph representation visualization: {str(e)}")
            # Fallback to simple visualization
            try:
                fig, ax = plt.subplots(1, 1, figsize=(16, 12))
                self.graph_representation_visualizer.draw_graph(ax, graph_data)
                plt.tight_layout()
                
                buf = io.BytesIO()
                plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
                buf.seek(0)
                image_bytes = buf.read()
                plt.close()
                
                return image_bytes
            except:
                return None
    
    
    def create_all_visualizations(self, graph_data: Dict[str, Any], original_image_bytes: bytes = None,
                                 notes_info: Dict[str, Any] = None, original_dimensions: Dict[str, int] = None) -> Dict[str, bytes]:
        """
        Create all three visualizations
        
        Args:
            graph_data: Graph data containing symbols, lines, junctions, connections
            original_image_bytes: Original image data as bytes for notes cutting visualization
            notes_info: Optional notes cutting area information from notes processor
            original_dimensions: Original image dimensions (width, height) before processing
            
        Returns:
            Dictionary with all visualization images as bytes
        """
        visualizations = {}
        
        # Create physical layout visualization
        physical_layout = self.create_physical_layout_visualization(graph_data, notes_info)
        if physical_layout:
            visualizations['physical_layout'] = physical_layout
        
        # Create graph representation visualization
        graph_representation = self.create_graph_representation_visualization(graph_data)
        if graph_representation:
            visualizations['graph_representation'] = graph_representation
        
        # Notes cutting visualization removed per user request
        
        return visualizations
    
    
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
