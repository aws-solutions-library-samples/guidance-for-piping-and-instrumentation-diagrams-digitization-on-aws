import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
from typing import Dict, Any, List, Tuple
import math


class PhysicalLayoutVisualizer:
    """Create physical layout visualizations of P&ID graphs"""
    
    def __init__(self, colors: Dict[str, str], config: Dict[str, Any]):
        self.colors = colors
        self.config = config
    
    def draw_layout(self, ax, graph_data: Dict[str, Any], params: Dict[str, Any] = None, 
                   notes_info: Dict[str, Any] = None):
        """
        Draw the physical layout of symbols, lines, and text with dynamic parameters
        
        Args:
            ax: matplotlib axis
            graph_data: Graph data containing symbols, lines, junctions
            params: Dynamic visualization parameters
            notes_info: Optional notes cutting area information from notes processor
        """
        if params is None:
            # Fallback to default parameters
            params = {
                'fonts': {'title': 16, 'label': 10, 'small': 8},
                'elements': {'line_width': 2, 'marker_size': 100, 'junction_size_scale': 1.0},
                'padding': 50,
                'show_detailed_labels': True
            }
        
        ax.set_title("Physical Layout with Text Associations", fontsize=params['fonts']['title'])
        
        # Find bounds
        min_x, min_y, max_x, max_y = self._calculate_bounds(graph_data)
        
        # Set axis limits with dynamic padding
        padding = params['padding']
        ax.set_xlim(min_x - padding, max_x + padding)
        ax.set_ylim(min_y - padding, max_y + padding)
        ax.invert_yaxis()  # Invert Y axis for image coordinates
        
        # Draw notes cutting area overlay first (so it appears behind other elements)
        if notes_info:
            self._draw_notes_overlay(ax, notes_info)
        
        # Draw symbols
        self._draw_symbols(ax, graph_data, params)
        
        # Draw lines with perpendicular text labels
        self._draw_lines(ax, graph_data, params, min_x, max_x, min_y, max_y)
        
        # Draw junctions
        self._draw_junctions(ax, graph_data, params)
        
        ax.set_aspect('equal')
        ax.grid(True, alpha=0.3)
        ax.set_xlabel('X Coordinate')
        ax.set_ylabel('Y Coordinate')
    
    def _calculate_bounds(self, graph_data: Dict[str, Any]) -> Tuple[float, float, float, float]:
        """Calculate the bounds of all elements in the graph data"""
        min_x, min_y = float('inf'), float('inf')
        max_x, max_y = float('-inf'), float('-inf')
        
        # Update bounds from symbols
        for symbol in graph_data.get('symbols', []):
            bbox = symbol['bbox']
            min_x = min(min_x, bbox[0])
            min_y = min(min_y, bbox[1])
            max_x = max(max_x, bbox[2])
            max_y = max(max_y, bbox[3])
        
        # Update bounds from lines
        for line in graph_data.get('lines', []):
            for point in line['points']:
                min_x = min(min_x, point[0])
                min_y = min(min_y, point[1])
                max_x = max(max_x, point[0])
                max_y = max(max_y, point[1])
        
        # Update bounds from junctions
        for junction in graph_data.get('junctions', []):
            point = junction['point']
            min_x = min(min_x, point[0])
            min_y = min(min_y, point[1])
            max_x = max(max_x, point[0])
            max_y = max(max_y, point[1])
        
        return min_x, min_y, max_x, max_y
    
    def _draw_notes_overlay(self, ax, notes_info: Dict[str, Any]):
        """
        Draw overlay showing the area that was cut by the notes processor
        
        Args:
            ax: matplotlib axis
            notes_info: Notes coordinates and metadata from notes processor
        """
        if not notes_info or notes_info.get('x') is None:
            return
        
        x = notes_info.get('x', 0)
        y = notes_info.get('y', 0)
        width = notes_info.get('width', 0)
        height = notes_info.get('height', 0)
        confidence = notes_info.get('confidence', 0)
        method_used = notes_info.get('method_used', 'unknown')
        
        # Draw semi-transparent red rectangle showing the cut area
        notes_rect = patches.Rectangle(
            (x, y),
            width,
            height,
            linewidth=3,
            edgecolor='red',
            facecolor='red',
            alpha=0.15,
            linestyle='--',
            zorder=1  # Behind other elements
        )
        ax.add_patch(notes_rect)
        
        # Add border with more visible edge
        border_rect = patches.Rectangle(
            (x, y),
            width,
            height,
            linewidth=2,
            edgecolor='darkred',
            facecolor='none',
            linestyle='-',
            zorder=2
        )
        ax.add_patch(border_rect)
        
        # Add label showing what was removed
        label_x = x + width / 2
        label_y = y + height / 2
        
        label_text = f"Notes Section (Removed)\nConfidence: {confidence:.2f}\nMethod: {method_used}"
        
        ax.text(label_x, label_y, 
               label_text,
               ha='center', va='center', fontsize=10,
               bbox=dict(boxstyle="round,pad=0.5", 
                        facecolor='white', 
                        edgecolor='red',
                        alpha=0.9,
                        linewidth=2),
               color='darkred',
               fontweight='bold',
               zorder=20)  # High z-order to appear above everything
        
        # Add corner markers to clearly show the bounds
        corner_size = min(width, height) * 0.05
        corners = [
            (x, y),  # top-left
            (x + width, y),  # top-right
            (x, y + height),  # bottom-left
            (x + width, y + height)  # bottom-right
        ]
        
        for corner_x, corner_y in corners:
            corner_marker = patches.Rectangle(
                (corner_x - corner_size/2, corner_y - corner_size/2),
                corner_size,
                corner_size,
                facecolor='red',
                edgecolor='darkred',
                linewidth=1,
                zorder=21
            )
            ax.add_patch(corner_marker)
    
    def _draw_symbols(self, ax, graph_data: Dict[str, Any], params: Dict[str, Any]):
        """Draw symbols with text associations"""
        for symbol in graph_data.get('symbols', []):
            bbox = symbol['bbox']
            rect = patches.Rectangle(
                (bbox[0], bbox[1]),
                bbox[2] - bbox[0],
                bbox[3] - bbox[1],
                linewidth=2,
                edgecolor=self.colors['symbol'],
                facecolor='none',
                alpha=0.8
            )
            ax.add_patch(rect)
            
            center_x = (bbox[0] + bbox[2]) / 2
            center_y = (bbox[1] + bbox[3]) / 2
            
            # Add symbol text association if present with adaptive sizing
            if symbol.get('text_associated') and params['show_detailed_labels']:
                # Calculate element size and adaptive font parameters
                element_size = self._calculate_element_size(symbol, 'symbol')
                text = symbol['text_associated']
                
                # Only show label if element is large enough
                if element_size >= self.config['label_config']['min_element_size_for_label']:
                    # Calculate adaptive font size
                    font_size = self._calculate_adaptive_font_size(
                        element_size, len(text), self.config['label_config']['symbol_font_scale']
                    )
                    
                    # Calculate available width for text (90% of symbol width)
                    symbol_width = bbox[2] - bbox[0]
                    max_text_width = symbol_width * self.config['label_config']['max_text_width_ratio']
                    
                    # Fit text to bounds
                    fitted_text = self._fit_text_to_bounds(text, max_text_width, font_size)
                    
                    ax.text(center_x, center_y, 
                           fitted_text,
                           ha='center', va='center', fontsize=font_size,
                           bbox=dict(boxstyle="round,pad=0.3", 
                                    facecolor=self.colors['text'], 
                                    alpha=0.8),
                           color='white', fontweight='bold')
    
    def _draw_lines(self, ax, graph_data: Dict[str, Any], params: Dict[str, Any],
                   min_x: float, max_x: float, min_y: float, max_y: float):
        """Draw lines with perpendicular text labels"""
        for line in graph_data.get('lines', []):
            points = line['points']
            points_array = np.array(points)
            
            # Draw line with dynamic width
            ax.plot(points_array[:, 0], points_array[:, 1], 
                   color=self.colors['line'], 
                   linewidth=params['elements']['line_width'], 
                   alpha=0.7)
            
            # Draw line endpoints with dynamic size
            endpoint_size = max(20, int(params['elements']['marker_size'] * 0.3))
            ax.scatter(points_array[0, 0], points_array[0, 1], 
                      color=self.colors['line'], s=endpoint_size, zorder=5)
            ax.scatter(points_array[-1, 0], points_array[-1, 1], 
                      color=self.colors['line'], s=endpoint_size, zorder=5)
            
            # Find the longest segment for label placement
            longest_segment = self._find_longest_segment(points)
            
            if longest_segment and line.get('text_associated'):
                start_point, end_point, length = longest_segment
                
                # Calculate element size for adaptive sizing
                element_size = self._calculate_element_size(line, 'line')
                text = line['text_associated']
                
                # Only show label if line is long enough
                if element_size >= self.config['label_config']['min_element_size_for_label']:
                    # Calculate adaptive font size
                    font_size = self._calculate_adaptive_font_size(
                        element_size, len(text), self.config['label_config']['line_font_scale']
                    )
                    
                    # Calculate available width for text (based on line length but more conservative)
                    max_text_width = min(length * 0.6, 150)  # More conservative: 60% of line length or 150px
                    
                    # Fit text to bounds
                    fitted_text = self._fit_text_to_bounds(text, max_text_width, font_size)
                    
                    # Estimate text dimensions for collision detection
                    text_width = len(fitted_text) * font_size * 0.6  # Rough estimate
                    text_height = font_size * 1.2  # Account for padding
                    
                    # Find optimal position that avoids symbol collisions
                    symbols = graph_data.get('symbols', [])
                    optimal_label_x, optimal_label_y = self._find_optimal_line_label_position(
                        start_point, end_point, text_width, text_height, symbols,
                        min_x, max_x, min_y, max_y
                    )
                    
                    # Draw label with collision-aware positioning
                    ax.text(optimal_label_x, optimal_label_y, 
                        fitted_text,
                        ha='center', va='center', fontsize=font_size,
                        rotation=0,  # Keep text horizontal for better readability
                        bbox=dict(boxstyle="round,pad=0.2",  # Smaller padding
                                    facecolor=self.colors['text'], 
                                    alpha=0.85,  # Slightly more transparent
                                    edgecolor='white',
                                    linewidth=1),
                        color='white',
                        fontweight='bold',
                        zorder=10)  # Ensure label appears above lines
    
    def _draw_junctions(self, ax, graph_data: Dict[str, Any], params: Dict[str, Any]):
        """Draw junctions with appropriate markers and colors"""
        for junction in graph_data.get('junctions', []):
            point = junction['point']
            junction_type = junction['junction_type']
            
            # Choose color based on junction type with dynamic sizing
            base_size = int(params['elements']['marker_size'] * params['elements']['junction_size_scale'])
            if junction_type == 't_junction':
                color = self.colors['t_junction']
                marker = '^'  # Triangle for T-junction
                size = max(100, int(base_size * 1.5))
            elif junction_type == 'cross_junction':
                color = self.colors['cross_junction']
                marker = 'X'  # X for cross junction
                size = max(80, int(base_size * 1.2))
            elif junction_type == 'l_junction':
                color = self.colors['l_junction']
                marker = 's'  # Square for L-junction
                size = max(60, base_size)
            else:
                color = self.colors['junction']
                marker = 'o'  # Circle for unknown junction
                size = max(60, base_size)
            
            # Draw junction point with dynamic sizing
            ax.scatter(point[0], point[1], 
                      color=color, 
                      marker=marker, 
                      s=size, 
                      alpha=0.9, 
                      edgecolors='white', 
                      linewidths=max(1, int(params['elements']['line_width'])),
                      zorder=15)  # High z-order to appear above lines
    
    def _find_longest_segment(self, points: List[List[float]]) -> Tuple[Tuple[float, float], Tuple[float, float], float]:
        """
        Find the longest segment in a multi-point line
        Returns: (start_point, end_point, length) of the longest segment
        """
        if len(points) < 2:
            return None
        
        longest_segment = None
        max_length = 0
        
        for i in range(len(points) - 1):
            start = points[i]
            end = points[i + 1]
            
            # Calculate segment length
            length = math.sqrt((end[0] - start[0])**2 + (end[1] - start[1])**2)
            
            if length > max_length:
                max_length = length
                longest_segment = (tuple(start), tuple(end), length)
        
        return longest_segment
    
    def _calculate_adaptive_font_size(self, element_size: float, text_length: int, 
                                    scale_factor: float = 0.8) -> int:
        """
        Calculate adaptive font size based on element dimensions and text length
        """
        label_config = self.config['label_config']
        
        # Base font size calculated from element size
        base_font_size = max(element_size * scale_factor / 10, label_config['min_font_size'])
        
        # Adjust based on text length - longer text gets smaller font
        length_adjustment = max(0.5, 1.0 - (text_length / 30.0))
        adjusted_font_size = base_font_size * length_adjustment
        
        # Clamp to min/max bounds
        return max(label_config['min_font_size'], 
                  min(adjusted_font_size, label_config['max_font_size']))
    
    def _fit_text_to_bounds(self, text: str, max_width: float, font_size: int) -> str:
        """
        Truncate or wrap text to fit within bounds
        """
        # Simple character-based truncation (could be improved with actual text measurement)
        # Rough estimate: each character is about 0.6 * font_size pixels wide
        char_width = font_size * 0.6
        max_chars = int(max_width / char_width)
        
        if len(text) <= max_chars:
            return text
        elif max_chars <= 3:
            return "..."
        else:
            return text[:max_chars-3] + "..."
    
    def _calculate_element_size(self, element: Dict[str, Any], element_type: str) -> float:
        """
        Calculate characteristic size of an element for label scaling
        """
        if element_type == 'symbol':
            bbox = element['bbox']
            width = bbox[2] - bbox[0]
            height = bbox[3] - bbox[1]
            return min(width, height)  # Use smaller dimension for conservative sizing
        elif element_type == 'line':
            points = element['points']
            if len(points) < 2:
                return 50  # Default size for single-point lines
            
            # Calculate total line length
            total_length = 0
            for i in range(len(points) - 1):
                dx = points[i+1][0] - points[i][0]
                dy = points[i+1][1] - points[i][1]
                total_length += math.sqrt(dx**2 + dy**2)
            return total_length
        else:
            return 50  # Default size
    
    def _check_symbol_collision(self, label_x: float, label_y: float, 
                               text_width: float, text_height: float,
                               symbols: List[Dict[str, Any]]) -> bool:
        """
        Check if a label position would collide with any symbols
        Returns True if collision detected, False otherwise
        """
        label_config = self.config['label_config']
        buffer = label_config['symbol_collision_buffer']
        
        # Create label bounding box with buffer
        label_bbox = {
            'x1': label_x - text_width/2 - buffer,
            'y1': label_y - text_height/2 - buffer,
            'x2': label_x + text_width/2 + buffer,
            'y2': label_y + text_height/2 + buffer
        }
        
        # Check collision with each symbol
        for symbol in symbols:
            symbol_bbox = symbol['bbox']
            
            # Check if rectangles overlap
            if (label_bbox['x1'] < symbol_bbox[2] and label_bbox['x2'] > symbol_bbox[0] and
                label_bbox['y1'] < symbol_bbox[3] and label_bbox['y2'] > symbol_bbox[1]):
                return True
        
        return False
    
    def _find_optimal_line_label_position(self, start_point: Tuple[float, float], 
                                         end_point: Tuple[float, float],
                                         text_width: float, text_height: float,
                                         symbols: List[Dict[str, Any]],
                                         min_x: float, max_x: float, 
                                         min_y: float, max_y: float) -> Tuple[float, float]:
        """
        Find optimal position for line label that avoids symbol collisions
        """
        label_config = self.config['label_config']
        min_offset = label_config['min_line_label_offset']
        max_offset = label_config['max_line_label_offset']
        
        # Try different offset distances and both sides of the line
        offsets_to_try = [min_offset, (min_offset + max_offset) / 2, max_offset]
        
        for offset in offsets_to_try:
            # Try both sides of the perpendicular
            for side_multiplier in [1, -1]:
                # Calculate perpendicular position
                mid_x = (start_point[0] + end_point[0]) / 2
                mid_y = (start_point[1] + end_point[1]) / 2
                
                dx = end_point[0] - start_point[0]
                dy = end_point[1] - start_point[1]
                line_length = math.sqrt(dx**2 + dy**2)
                
                if line_length > 0:
                    dx_norm = dx / line_length
                    dy_norm = dy / line_length
                    
                    # Calculate perpendicular vector
                    perp_x = -dy_norm * side_multiplier
                    perp_y = dx_norm * side_multiplier
                    
                    label_x = mid_x + perp_x * offset
                    label_y = mid_y + perp_y * offset
                    
                    # Check if position is within bounds
                    padding = 30
                    if (label_x >= min_x + padding and label_x <= max_x - padding and
                        label_y >= min_y + padding and label_y <= max_y - padding):
                        
                        # Check for symbol collisions
                        if not self._check_symbol_collision(label_x, label_y, text_width, text_height, symbols):
                            return (label_x, label_y)
        
        # Fallback: return position with maximum offset on first side
        mid_x = (start_point[0] + end_point[0]) / 2
        mid_y = (start_point[1] + end_point[1]) / 2
        dx = end_point[0] - start_point[0]
        dy = end_point[1] - start_point[1]
        line_length = math.sqrt(dx**2 + dy**2)
        
        if line_length > 0:
            dx_norm = dx / line_length
            dy_norm = dy / line_length
            perp_x = -dy_norm
            perp_y = dx_norm
            label_x = mid_x + perp_x * max_offset
            label_y = mid_y + perp_y * max_offset
        else:
            label_x, label_y = mid_x, mid_y
            
        return (label_x, label_y)
