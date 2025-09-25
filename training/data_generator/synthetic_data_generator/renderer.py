import json
from typing import List, Dict, Tuple, Optional, Any
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import os


class Renderer:
    """Handles image rendering and JSON annotation export."""
    
    def __init__(self, canvas_width: int, canvas_height: int):
        self.canvas_width = canvas_width
        self.canvas_height = canvas_height
    
    def render_diagram(self, placed_symbols: List[Dict], connections: List[Dict], 
                      background_color: str = "white", line_thickness: int = 2,
                      text_boxes: Optional[List[Dict]] = None,
                      symbol_captions: Optional[List[Dict]] = None) -> Image.Image:
        """
        Render the complete P&ID diagram.
        
        Args:
            placed_symbols: List of placed symbols with position info
            connections: List of connections between symbols
            background_color: Background color for the canvas
            line_thickness: Thickness of connection lines in pixels
            text_boxes: Optional list of text box configurations to render
            symbol_captions: Optional list of symbol caption configurations to render
            
        Returns:
            PIL Image of the rendered diagram
        """
        # Create canvas
        canvas = Image.new('RGB', (self.canvas_width, self.canvas_height), background_color)
        draw = ImageDraw.Draw(canvas)
        
        # Draw text boxes first (so they appear as background)
        if text_boxes:
            self._draw_text_boxes(canvas, text_boxes)
        
        # Draw connections (so they appear behind symbols but over text boxes)
        self._draw_connections(draw, connections, line_thickness)
        
        # Draw symbols on top
        self._draw_symbols(canvas, placed_symbols)
        
        # Draw symbol captions last (so they appear on top)
        if symbol_captions:
            self._draw_symbol_captions(canvas, symbol_captions)
        
        return canvas
    
    def _draw_connections(self, draw: ImageDraw.Draw, connections: List[Dict], line_thickness: int = 2):
        """Draw connection lines between symbols."""
        line_color = "black"
        
        for connection in connections:
            path = connection['path']
            
            # Draw line segments
            for i in range(len(path) - 1):
                start_point = path[i]
                end_point = path[i + 1]
                draw.line([start_point, end_point], fill=line_color, width=line_thickness)
    
    def _draw_symbols(self, canvas: Image.Image, placed_symbols: List[Dict]):
        """Draw symbols on the canvas."""
        for symbol in placed_symbols:
            image = symbol['image']
            position = symbol['position']
            
            # Paste symbol image onto canvas
            # Handle transparency properly
            if image.mode == 'RGBA':
                canvas.paste(image, position, image)
            else:
                canvas.paste(image, position)
    
    def _draw_text_boxes(self, canvas: Image.Image, text_boxes: List[Dict]):
        """
        Draw text boxes on the canvas.
        
        Args:
            canvas: PIL Image canvas to draw on
            text_boxes: List of text box configurations with content
        """
        for text_box in text_boxes:
            self._draw_single_text_box(canvas, text_box)
    
    def _draw_single_text_box(self, canvas: Image.Image, text_box: Dict[str, Any]):
        """
        Draw a single text box on the canvas.
        
        Args:
            canvas: PIL Image canvas to draw on
            text_box: Text box configuration with content
        """
        # Extract text box properties
        bbox = text_box.get('bbox', (0, 0, 100, 100))
        text_lines = text_box.get('text_lines', [])
        font_size = text_box.get('font_size', 12)
        background_color = text_box.get('background_color', 'white')
        text_color = text_box.get('text_color', 'black')
        position = text_box.get('position', 'top')
        
        x, y, width, height = bbox
        
        # Create a drawing context
        draw = ImageDraw.Draw(canvas)
        
        # Draw background rectangle
        draw.rectangle([x, y, x + width, y + height], fill=background_color, outline='black', width=1)
        
        # Get font for text rendering
        font = self._get_font(font_size)
        
        # Draw text lines
        self._draw_text_lines(draw, text_lines, x, y, width, height, font, text_color, position)
    
    def _draw_text_lines(self, draw: ImageDraw.Draw, text_lines: List[str], 
                        box_x: int, box_y: int, box_width: int, box_height: int,
                        font: ImageFont.FreeTypeFont, text_color: str, position: str):
        """
        Draw text lines within a text box with proper alignment and spacing.
        
        Args:
            draw: ImageDraw object
            text_lines: List of text lines to draw
            box_x, box_y: Top-left corner of text box
            box_width, box_height: Dimensions of text box
            font: Font to use for text
            text_color: Color for text
            position: Text box position for alignment hints
        """
        if not text_lines:
            return
        
        # Calculate line height
        try:
            # Try to get font size from font object
            if hasattr(font, 'size'):
                line_height = int(font.size * 1.2)
            else:
                # Fallback: measure a sample text
                bbox = font.getbbox('Ay')
                line_height = int((bbox[3] - bbox[1]) * 1.2)
        except:
            # Final fallback
            line_height = 15
        
        # Calculate padding
        padding_x = 10
        padding_y = 8
        
        # Calculate available space for text
        available_width = box_width - (2 * padding_x)
        available_height = box_height - (2 * padding_y)
        
        # Calculate starting y position (center text vertically if possible)
        total_text_height = len(text_lines) * line_height
        if total_text_height < available_height:
            start_y = box_y + padding_y + (available_height - total_text_height) // 2
        else:
            start_y = box_y + padding_y
        
        # Draw each line
        for i, line in enumerate(text_lines):
            if not line.strip():
                continue
            
            line_y = start_y + (i * line_height)
            
            # Skip lines that would be outside the box
            if line_y + line_height > box_y + box_height - padding_y:
                break
            
            # Calculate x position based on alignment
            text_x = self._calculate_text_x_position(
                draw, line, font, box_x + padding_x, available_width, position
            )
            
            # Draw the text line
            draw.text((text_x, line_y), line, fill=text_color, font=font)
    
    def _calculate_text_x_position(self, draw: ImageDraw.Draw, text: str, 
                                  font: ImageFont.FreeTypeFont, start_x: int, 
                                  available_width: int, position: str) -> int:
        """
        Calculate x position for text based on alignment preferences.
        
        Args:
            draw: ImageDraw object
            text: Text to position
            font: Font being used
            start_x: Left edge of available text area
            available_width: Width available for text
            position: Text box position (affects alignment preference)
            
        Returns:
            X coordinate for text positioning
        """
        try:
            # Get text width
            bbox = font.getbbox(text)
            text_width = bbox[2] - bbox[0]
        except:
            # Fallback if font measurement fails
            text_width = len(text) * 8  # Rough estimate
        
        # If text is wider than available space, left-align
        if text_width >= available_width:
            return start_x
        
        # Choose alignment based on text box position and content
        # Title-like content (first line) gets centered, others left-aligned
        if self._looks_like_title(text):
            # Center align titles
            return start_x + (available_width - text_width) // 2
        else:
            # Left align other content
            return start_x
    
    def _looks_like_title(self, text: str) -> bool:
        """
        Determine if text looks like a title based on content patterns.
        
        Args:
            text: Text to analyze
            
        Returns:
            True if text appears to be a title
        """
        title_indicators = [
            'diagram', 'schematic', 'layout', 'system', 'unit', 'process',
            'flow', 'equipment', 'specifications', 'conditions', 'parameters'
        ]
        
        text_lower = text.lower()
        
        # Exclude lines that look like specifications (contain colons)
        if ':' in text:
            return False
        
        # Exclude very long lines (likely descriptions, not titles)
        if len(text) > 60:
            return False
        
        # Check for title indicators
        for indicator in title_indicators:
            if indicator in text_lower:
                return True
        
        # Check if text is short and doesn't contain technical patterns
        if len(text) < 30 and not any(char in text for char in [':', '=', '>', '<']):
            return True
        
        return False
    
    def _get_font(self, font_size: int) -> ImageFont.FreeTypeFont:
        """
        Get font object for text rendering.
        
        Args:
            font_size: Size of font to load
            
        Returns:
            Font object for rendering
        """
        try:
            # Try to use system fonts
            font = self._get_system_font(font_size)
            return font
        except (OSError, IOError):
            # Fallback to PIL default font
            return ImageFont.load_default()
    
    def _get_system_font(self, font_size: int) -> ImageFont.FreeTypeFont:
        """
        Try to load a system font.
        
        Args:
            font_size: Size of font to load
            
        Returns:
            System font object
        """
        # Common system font paths for different platforms
        font_paths = [
            # macOS
            "/System/Library/Fonts/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            # Windows
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/calibri.ttf",
            # Linux
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
        ]
        
        for font_path in font_paths:
            if os.path.exists(font_path):
                return ImageFont.truetype(font_path, font_size)
        
        # If no system font found, use default
        return ImageFont.load_default()
    
    def _draw_symbol_captions(self, canvas: Image.Image, symbol_captions: List[Dict]):
        """
        Draw symbol captions on the canvas.
        
        Args:
            canvas: PIL Image canvas to draw on
            symbol_captions: List of caption configurations with position and text
        """
        draw = ImageDraw.Draw(canvas)
        
        for caption in symbol_captions:
            text = caption.get('text', '')
            position = caption.get('position', (0, 0))
            font_size = caption.get('font_size', 10)
            color = caption.get('color', 'black')
            
            if not text or not position:
                continue
            
            # Get font for caption
            font = self._get_font(font_size)
            
            # Draw the caption text
            x, y = position
            draw.text((x, y), text, fill=color, font=font)
    
    def export_annotations(self, placed_symbols: List[Dict], connections: List[Dict], 
                          output_path: str, text_boxes: Optional[List[Dict]] = None,
                          symbol_captions: Optional[List[Dict]] = None):
        """
        Export symbol annotations to JSON file.
        
        Args:
            placed_symbols: List of placed symbols
            connections: List of connections
            output_path: Path to save JSON file
            text_boxes: Optional list of text box configurations
            symbol_captions: Optional list of symbol caption configurations
        """
        annotations = {
            "image_info": {
                "width": self.canvas_width,
                "height": self.canvas_height
            },
            "symbols": [],
            "connections": [],
            "text_boxes": [],
            "symbol_captions": []
        }
        
        # Add symbol annotations
        for i, symbol in enumerate(placed_symbols):
            bbox = symbol['bbox']
            symbol_annotation = {
                "id": i,
                "label": symbol['name'],
                "bbox": [bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1]],  # [x, y, width, height]
                "center": list(symbol['center']),
                "scale": symbol['scale'],
                "rotation": symbol.get('rotation', 0)  # Include rotation if available
            }
            annotations["symbols"].append(symbol_annotation)
        
        # Add connection annotations
        for connection in connections:
            connection_annotation = {
                "from": connection['from'],
                "to": connection['to'],
                "from_symbol": connection['from_symbol'],
                "to_symbol": connection['to_symbol'],
                "path": connection['path']
            }
            annotations["connections"].append(connection_annotation)
        
        # Add text box annotations
        if text_boxes:
            for text_box in text_boxes:
                bbox = text_box.get('bbox', (0, 0, 0, 0))
                text_box_annotation = {
                    "position": text_box.get('position', 'top'),
                    "bbox": list(bbox),  # [x, y, width, height]
                    "size_percent": text_box.get('size_percent', 15.0),
                    "text_lines": text_box.get('text_lines', []),
                    "font_size": text_box.get('font_size', 12),
                    "background_color": text_box.get('background_color', 'white'),
                    "text_color": text_box.get('text_color', 'black')
                }
                annotations["text_boxes"].append(text_box_annotation)
        
        # Add symbol caption annotations
        if symbol_captions:
            for caption in symbol_captions:
                caption_annotation = {
                    "symbol_id": caption.get('symbol_id', -1),
                    "symbol_name": caption.get('symbol_name', ''),
                    "text": caption.get('text', ''),
                    "position": list(caption.get('position', (0, 0))),  # [x, y]
                    "font_size": caption.get('font_size', 10),
                    "color": caption.get('color', 'black')
                }
                annotations["symbol_captions"].append(caption_annotation)
        
        # Save to JSON file
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(annotations, f, indent=2, ensure_ascii=False)
    
    def save_image(self, image: Image.Image, output_path: str):
        """Save rendered image to file."""
        # Ensure output directory exists
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save image
        image.save(output_path, 'PNG', optimize=True)
        print(f"Image saved to: {output_path}")
    
    def create_preview_image(self, placed_symbols: List[Dict], connections: List[Dict], 
                           scale: float = 0.25, text_boxes: Optional[List[Dict]] = None) -> Image.Image:
        """Create a smaller preview version of the diagram."""
        preview_width = int(self.canvas_width * scale)
        preview_height = int(self.canvas_height * scale)
        
        # Create temporary renderer for preview
        preview_renderer = Renderer(preview_width, preview_height)
        
        # Scale symbol positions and sizes
        scaled_symbols = []
        for symbol in placed_symbols:
            scaled_symbol = symbol.copy()
            
            # Scale position
            x, y = symbol['position']
            scaled_symbol['position'] = (int(x * scale), int(y * scale))
            
            # Scale bbox
            bbox = symbol['bbox']
            scaled_bbox = (
                int(bbox[0] * scale),
                int(bbox[1] * scale),
                int(bbox[2] * scale),
                int(bbox[3] * scale)
            )
            scaled_symbol['bbox'] = scaled_bbox
            
            # Scale center
            center = symbol['center']
            scaled_symbol['center'] = (int(center[0] * scale), int(center[1] * scale))
            
            # Scale image
            original_image = symbol['image']
            new_size = (int(original_image.width * scale), int(original_image.height * scale))
            scaled_symbol['image'] = original_image.resize(new_size, Image.Resampling.LANCZOS)
            
            scaled_symbols.append(scaled_symbol)
        
        # Scale connections
        scaled_connections = []
        for connection in connections:
            scaled_connection = connection.copy()
            scaled_path = [(int(x * scale), int(y * scale)) for x, y in connection['path']]
            scaled_connection['path'] = scaled_path
            scaled_connections.append(scaled_connection)
        
        # Scale text boxes if provided
        scaled_text_boxes = None
        if text_boxes:
            scaled_text_boxes = []
            for text_box in text_boxes:
                scaled_text_box = text_box.copy()
                
                # Scale bbox
                bbox = text_box.get('bbox', (0, 0, 0, 0))
                scaled_bbox = (
                    int(bbox[0] * scale),
                    int(bbox[1] * scale),
                    int(bbox[2] * scale),
                    int(bbox[3] * scale)
                )
                scaled_text_box['bbox'] = scaled_bbox
                
                # Scale font size
                font_size = text_box.get('font_size', 12)
                scaled_text_box['font_size'] = max(8, int(font_size * scale))
                
                scaled_text_boxes.append(scaled_text_box)
        
        return preview_renderer.render_diagram(scaled_symbols, scaled_connections, text_boxes=scaled_text_boxes)
