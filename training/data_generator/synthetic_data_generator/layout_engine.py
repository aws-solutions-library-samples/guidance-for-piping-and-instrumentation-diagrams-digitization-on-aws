import random
import math
from typing import List, Dict, Tuple, Optional
import numpy as np


class LayoutEngine:
    """Handles symbol placement and connection generation."""
    
    def __init__(self, canvas_width: int, canvas_height: int, margin: int = 50, 
                 text_box_areas: Optional[List[Dict]] = None):
        """
        Initialize LayoutEngine with optional text box areas to exclude from symbol placement.
        
        Args:
            canvas_width: Width of the canvas in pixels
            canvas_height: Height of the canvas in pixels
            margin: Margin around canvas edges in pixels
            text_box_areas: List of text box area dictionaries with format:
                           {'position': str, 'bbox': (x, y, width, height)}
        """
        self.canvas_width = canvas_width
        self.canvas_height = canvas_height
        self.margin = margin
        self.text_box_areas = text_box_areas or []
        self.placed_symbols = []
        self.connections = []
        
        # Validate text box areas and calculate available area
        self._validate_text_box_areas()
        self.available_area = self._calculate_available_area()
    
    def place_symbols(self, symbols_data: List[Dict]) -> List[Dict]:
        """
        Place symbols on canvas avoiding overlaps and text box areas.
        
        Args:
            symbols_data: List of dicts with 'name', 'image', 'scale' keys
            
        Returns:
            List of placed symbols with position and bbox info
        """
        self.placed_symbols = []
        
        # Validate that there's sufficient space for symbols
        self._validate_sufficient_space(symbols_data)
        
        # Try to place each symbol
        for symbol_data in symbols_data:
            image = symbol_data['image']
            symbol_width = image.width
            symbol_height = image.height
            
            # Try multiple placement attempts
            placed = False
            max_attempts = 100
            
            for attempt in range(max_attempts):
                # Random position within available area
                x, y = self._get_random_position_in_available_area(symbol_width, symbol_height)
                
                if x is None or y is None:
                    continue
                
                # Check for overlaps with existing symbols and text boxes
                bbox = (x, y, x + symbol_width, y + symbol_height)
                
                if not self._has_overlap(bbox) and not self._overlaps_text_box(bbox):
                    # Place the symbol
                    placed_symbol = {
                        'name': symbol_data['name'],
                        'image': image,
                        'position': (x, y),
                        'bbox': bbox,
                        'center': (x + symbol_width // 2, y + symbol_height // 2),
                        'scale': symbol_data['scale'],
                        'rotation': symbol_data.get('rotation', 0)
                    }
                    self.placed_symbols.append(placed_symbol)
                    placed = True
                    break
            
            if not placed:
                # Provide detailed warning with suggestions
                symbol_size = f"{symbol_data['image'].width}x{symbol_data['image'].height}"
                avail_x, avail_y, avail_width, avail_height = self.available_area
                
                suggestions = []
                if symbol_data['image'].width > avail_width * 0.3 or symbol_data['image'].height > avail_height * 0.3:
                    suggestions.append("reduce symbol scale")
                if len(self.placed_symbols) > avail_width * avail_height / 10000:
                    suggestions.append("reduce symbol count")
                if self.text_box_areas:
                    suggestions.append("reduce text box size")
                
                suggestion_text = f" Consider: {', '.join(suggestions)}." if suggestions else ""
                
                print(f"Warning: Could not place symbol '{symbol_data['name']}' ({symbol_size}) "
                      f"after {max_attempts} attempts in available area ({avail_width}x{avail_height}).{suggestion_text}")
        
        return self.placed_symbols
    
    def _has_overlap(self, bbox: Tuple[int, int, int, int], padding: int = 20) -> bool:
        """Check if bbox overlaps with any existing symbol (with padding)."""
        x1, y1, x2, y2 = bbox
        
        for symbol in self.placed_symbols:
            sx1, sy1, sx2, sy2 = symbol['bbox']
            
            # Add padding to existing symbol bbox
            sx1 -= padding
            sy1 -= padding
            sx2 += padding
            sy2 += padding
            
            # Check for overlap
            if not (x2 < sx1 or x1 > sx2 or y2 < sy1 or y1 > sy2):
                return True
        
        return False
    
    def generate_connections(self) -> List[Dict]:
        """
        Generate connections between symbols.
        Each symbol connects to exactly one other symbol.
        """
        self.connections = []
        
        if len(self.placed_symbols) < 2:
            return self.connections
        
        # Create pairs - each symbol connects to exactly one other
        symbols_copy = self.placed_symbols.copy()
        random.shuffle(symbols_copy)
        
        # Pair symbols
        pairs = []
        for i in range(0, len(symbols_copy) - 1, 2):
            pairs.append((symbols_copy[i], symbols_copy[i + 1]))
        
        # If odd number of symbols, connect the last one to a random existing pair
        if len(symbols_copy) % 2 == 1:
            last_symbol = symbols_copy[-1]
            random_symbol = random.choice(symbols_copy[:-1])
            pairs.append((last_symbol, random_symbol))
        
        # Generate connection paths for each pair
        for symbol1, symbol2 in pairs:
            path = self._generate_connection_path(symbol1, symbol2)
            connection = {
                'from': self.placed_symbols.index(symbol1),
                'to': self.placed_symbols.index(symbol2),
                'path': path,
                'from_symbol': symbol1['name'],
                'to_symbol': symbol2['name']
            }
            self.connections.append(connection)
        
        return self.connections
    
    def _generate_connection_path(self, symbol1: Dict, symbol2: Dict) -> List[Tuple[int, int]]:
        """
        Generate Manhattan-style connection path between two symbols.
        """
        center1 = symbol1['center']
        center2 = symbol2['center']
        
        x1, y1 = center1
        x2, y2 = center2
        
        # Simple Manhattan routing: horizontal then vertical
        if random.choice([True, False]):
            # Horizontal first, then vertical
            path = [
                (x1, y1),
                (x2, y1),
                (x2, y2)
            ]
        else:
            # Vertical first, then horizontal
            path = [
                (x1, y1),
                (x1, y2),
                (x2, y2)
            ]
        
        return path
    
    def get_connection_endpoints(self, symbol1: Dict, symbol2: Dict) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        """
        Calculate optimal connection points on symbol edges.
        """
        bbox1 = symbol1['bbox']
        bbox2 = symbol2['bbox']
        
        # Calculate centers
        center1 = symbol1['center']
        center2 = symbol2['center']
        
        # Determine which edges to connect
        # For simplicity, use centers for now
        return center1, center2
    
    def clear(self):
        """Clear all placed symbols and connections."""
        self.placed_symbols = []
        self.connections = []
    
    def _validate_text_box_areas(self):
        """Validate text box areas are within canvas bounds and don't overlap."""
        for i, text_box in enumerate(self.text_box_areas):
            bbox = text_box.get('bbox')
            if not bbox or len(bbox) != 4:
                raise ValueError(f"Text box {i} must have 'bbox' with format (x, y, width, height)")
            
            x, y, width, height = bbox
            
            # Check bounds
            if x < 0 or y < 0 or x + width > self.canvas_width or y + height > self.canvas_height:
                raise ValueError(f"Text box {i} bbox {bbox} is outside canvas bounds ({self.canvas_width}x{self.canvas_height})")
            
            # Check for overlaps with other text boxes
            for j, other_box in enumerate(self.text_box_areas[i+1:], i+1):
                other_bbox = other_box.get('bbox')
                if other_bbox and self._bboxes_overlap(bbox, other_bbox):
                    raise ValueError(f"Text box {i} overlaps with text box {j}")
    
    def _calculate_available_area(self) -> Tuple[int, int, int, int]:
        """
        Calculate the available area for symbol placement excluding margins and text boxes.
        
        Returns:
            Tuple of (x, y, width, height) representing the largest available rectangular area
        """
        # Start with full canvas minus margins
        available_x = self.margin
        available_y = self.margin
        available_width = self.canvas_width - 2 * self.margin
        available_height = self.canvas_height - 2 * self.margin
        
        # Reduce available area based on text box positions
        for text_box in self.text_box_areas:
            bbox = text_box.get('bbox')
            if not bbox:
                continue
                
            x, y, width, height = bbox
            position = text_box.get('position', '')
            
            # Adjust available area based on text box position
            if position == 'top':
                if y + height > available_y:
                    reduction = (y + height) - available_y
                    available_y += reduction
                    available_height -= reduction
            elif position == 'bottom':
                if y < available_y + available_height:
                    reduction = (available_y + available_height) - y
                    available_height -= reduction
            elif position == 'left':
                if x + width > available_x:
                    reduction = (x + width) - available_x
                    available_x += reduction
                    available_width -= reduction
            elif position == 'right':
                if x < available_x + available_width:
                    reduction = (available_x + available_width) - x
                    available_width -= reduction
        
        # Ensure positive dimensions
        available_width = max(0, available_width)
        available_height = max(0, available_height)
        
        return (available_x, available_y, available_width, available_height)
    
    def get_available_area(self) -> Tuple[int, int, int, int]:
        """
        Get the available area for symbol placement.
        
        Returns:
            Tuple of (x, y, width, height) of area available for symbols
        """
        return self.available_area
    
    def _get_random_position_in_available_area(self, symbol_width: int, symbol_height: int) -> Tuple[Optional[int], Optional[int]]:
        """
        Get a random position within the available area that can fit the symbol.
        
        Args:
            symbol_width: Width of the symbol to place
            symbol_height: Height of the symbol to place
            
        Returns:
            Tuple of (x, y) position or (None, None) if no space available
        """
        avail_x, avail_y, avail_width, avail_height = self.available_area
        
        # Check if symbol can fit in available area
        if symbol_width > avail_width or symbol_height > avail_height:
            return None, None
        
        # Generate random position within available area
        max_x = avail_x + avail_width - symbol_width
        max_y = avail_y + avail_height - symbol_height
        
        if max_x < avail_x or max_y < avail_y:
            return None, None
        
        x = random.randint(avail_x, max_x)
        y = random.randint(avail_y, max_y)
        
        return x, y
    
    def _overlaps_text_box(self, bbox: Tuple[int, int, int, int]) -> bool:
        """Check if bbox overlaps with any text box area."""
        for text_box in self.text_box_areas:
            text_bbox = text_box.get('bbox')
            if text_bbox and self._bboxes_overlap(bbox, text_bbox):
                return True
        return False
    
    def _bboxes_overlap(self, bbox1: Tuple[int, int, int, int], bbox2: Tuple[int, int, int, int]) -> bool:
        """Check if two bounding boxes overlap."""
        x1, y1, w1, h1 = bbox1
        x2, y2, w2, h2 = bbox2
        
        # Convert to (x1, y1, x2, y2) format for easier comparison
        x1_end, y1_end = x1 + w1, y1 + h1
        x2_end, y2_end = x2 + w2, y2 + h2
        
        # Check for no overlap (easier to negate)
        no_overlap = (x1_end <= x2 or x2_end <= x1 or y1_end <= y2 or y2_end <= y1)
        return not no_overlap
    
    def _validate_sufficient_space(self, symbols_data: List[Dict]):
        """
        Validate that there's sufficient space to place symbols.
        
        Args:
            symbols_data: List of symbol data to validate space for
            
        Raises:
            ValueError: If insufficient space is available
        """
        avail_x, avail_y, avail_width, avail_height = self.available_area
        available_area = avail_width * avail_height
        
        # Calculate minimum area needed (rough estimate)
        total_symbol_area = 0
        symbol_count = len(symbols_data)
        
        for symbol_data in symbols_data:
            image = symbol_data['image']
            symbol_area = image.width * image.height
            total_symbol_area += symbol_area
        
        # Add padding factor (symbols need space between them)
        padding_factor = 2.5  # Symbols need ~2.5x their area due to spacing requirements
        required_area = total_symbol_area * padding_factor
        
        if available_area < required_area:
            # Calculate area usage by text boxes for better error message
            canvas_area = self.canvas_width * self.canvas_height
            text_box_area = canvas_area - available_area - (2 * self.margin * (self.canvas_width + self.canvas_height - 2 * self.margin))
            text_box_percent = (text_box_area / canvas_area) * 100 if canvas_area > 0 else 0
            
            # Provide specific suggestions
            suggestions = []
            if text_box_percent > 30:
                suggestions.append(f"reduce text box size (currently using {text_box_percent:.1f}% of canvas)")
            if symbol_count > 10:
                max_symbols = int(available_area / (total_symbol_area / symbol_count * padding_factor))
                suggestions.append(f"reduce symbol count to {max_symbols} or fewer")
            if any(s['scale'] > 1.2 for s in symbols_data):
                suggestions.append("reduce symbol scale factors")
            
            suggestion_text = f" Try: {', '.join(suggestions)}." if suggestions else ""
            
            raise ValueError(
                f"Insufficient space for symbol placement. "
                f"Available area: {available_area:,} pixels, "
                f"Required area (with padding): {required_area:,.0f} pixels. "
                f"Available space: {avail_width}x{avail_height}.{suggestion_text}"
            )
        
        # Check if available area dimensions can fit largest symbol
        if symbols_data:
            max_width = max(symbol['image'].width for symbol in symbols_data)
            max_height = max(symbol['image'].height for symbol in symbols_data)
            largest_symbol = next(s['name'] for s in symbols_data if s['image'].width == max_width or s['image'].height == max_height)
            
            if max_width > avail_width or max_height > avail_height:
                # Provide specific suggestions for dimension issues
                suggestions = []
                if max_width > avail_width:
                    needed_width_percent = ((max_width - avail_width) / self.canvas_width) * 100
                    suggestions.append(f"reduce horizontal text box size by at least {needed_width_percent:.1f}%")
                if max_height > avail_height:
                    needed_height_percent = ((max_height - avail_height) / self.canvas_height) * 100
                    suggestions.append(f"reduce vertical text box size by at least {needed_height_percent:.1f}%")
                
                suggestions.append("reduce symbol scale factors")
                suggestion_text = f" Try: {', '.join(suggestions)}."
                
                raise ValueError(
                    f"Available area ({avail_width}x{avail_height}) is too small "
                    f"for largest symbol '{largest_symbol}' ({max_width}x{max_height}).{suggestion_text}"
                )
