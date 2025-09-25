import random
from typing import Tuple, List, Optional, Dict, Any
from pathlib import Path
from symbol_manager import SymbolManager
from layout_engine import LayoutEngine
from renderer import Renderer
from text_box_generator import TextBoxGenerator, TextBoxValidationError


class PnidGenerator:
    """Main class for generating synthetic P&ID diagrams."""
    
    def __init__(self, symbol_directory: str = "./symbols/"):
        """
        Initialize the P&ID generator.
        
        Args:
            symbol_directory: Path to directory containing symbol files (SVG, PNG, JPEG)
        """
        self.symbol_manager = SymbolManager(symbol_directory)
        self.text_box_generator = TextBoxGenerator()
        print(f"Loaded {len(self.symbol_manager.get_all_symbols())} symbols")
    
    def generate(self, 
                symbol_count_range: Tuple[int, int] = (5, 15),
                symbol_size_range: Tuple[float, float] = (0.7, 1.5),
                output_resolution: Tuple[int, int] = (1920, 1080),
                output_prefix: str = "synthetic_pnid",
                output_directory: str = "./output/",
                line_thickness: int = 2,
                enable_rotation: bool = True,
                with_replacement: bool = False,
                seed: Optional[int] = None,
                text_box_config: Optional[Dict[str, Any]] = None,
                captions: float = 0.0) -> Tuple[str, str]:
        """
        Generate a synthetic P&ID diagram.
        
        Args:
            symbol_count_range: (min, max) number of symbols to include
            symbol_size_range: (min, max) scaling factors for symbols
            output_resolution: (width, height) of output image in pixels
            output_prefix: Base name for output files
            output_directory: Directory to save output files
            line_thickness: Thickness of connection lines in pixels
            enable_rotation: Whether to randomly rotate symbols by 90/180/270 degrees
            with_replacement: If True, allows duplicate symbols; if False, each symbol appears at most once
            seed: Random seed for reproducible results
            text_box_config: Optional text box configuration dict with keys:
                           'position': 'top'|'bottom'|'left'|'right'
                           'size_percent': float (5.0-50.0)
                           'font_size': int (8-72, default 12)
                           'background_color': str (default 'white')
                           'text_color': str (default 'black')
            captions: Proportion of symbols (0.0-1.0) that should have text captions
            
        Returns:
            Tuple of (image_path, json_path) for generated files
        """
        if seed is not None:
            random.seed(seed)
        
        # Validate captions parameter
        if not isinstance(captions, (int, float)):
            raise ValueError(f"captions must be a number between 0.0 and 1.0, got {type(captions).__name__}")
        if not (0.0 <= captions <= 1.0):
            raise ValueError(f"captions must be between 0.0 and 1.0, got {captions}")
        
        # Setup output paths
        output_dir = Path(output_directory)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        image_path = output_dir / f"{output_prefix}.png"
        json_path = output_dir / f"{output_prefix}.json"
        
        print(f"Generating P&ID diagram...")
        print(f"- Symbol count range: {symbol_count_range}")
        print(f"- Symbol size range: {symbol_size_range}")
        print(f"- Output resolution: {output_resolution}")
        
        # Process text box configuration
        text_boxes = []
        text_box_areas = []
        
        if text_box_config is not None:
            try:
                canvas_width, canvas_height = output_resolution
                
                # Validate text box configuration against canvas dimensions
                validated_config = TextBoxGenerator.validate_text_box_with_canvas(
                    text_box_config, canvas_width, canvas_height
                )
                
                if validated_config:  # Only process if config is not empty
                    # Check for potential issues and provide warnings
                    warnings = TextBoxGenerator.detect_text_box_conflicts(
                        [validated_config], canvas_width, canvas_height
                    )
                    
                    for warning in warnings:
                        print(f"Warning: {warning}")
                    
                    # Get improvement suggestions
                    suggestions = TextBoxGenerator.suggest_text_box_improvements(
                        validated_config, canvas_width, canvas_height
                    )
                    
                    for suggestion in suggestions:
                        print(f"Suggestion: {suggestion}")
                    
                    # Merge with defaults
                    full_config = TextBoxGenerator.merge_with_defaults(validated_config)
                    
                    # Calculate text box dimensions
                    position = full_config['position']
                    size_percent = full_config['size_percent']
                    
                    bbox = TextBoxGenerator.calculate_text_box_dimensions(
                        canvas_width, canvas_height, position, size_percent
                    )
                    
                    # Generate text content
                    x, y, box_width, box_height = bbox
                    font_size = full_config['font_size']
                    text_lines = self.text_box_generator.generate_text_content(
                        box_width, box_height, font_size
                    )
                    
                    # Create text box data structure
                    text_box = {
                        'position': position,
                        'bbox': bbox,
                        'size_percent': size_percent,
                        'text_lines': text_lines,
                        'font_size': font_size,
                        'background_color': full_config['background_color'],
                        'text_color': full_config['text_color']
                    }
                    
                    text_boxes.append(text_box)
                    text_box_areas.append({
                        'position': position,
                        'bbox': bbox
                    })
                    
                    print(f"- Text box: {position} position, {size_percent}% size")
                    
            except TextBoxValidationError as e:
                # Provide helpful error message with context
                error_msg = f"Invalid text box configuration: {e}"
                
                # Add canvas context to error message
                if "canvas" not in str(e).lower():
                    error_msg += f" (Canvas: {canvas_width}x{canvas_height})"
                
                raise ValueError(error_msg)
        
        # Step 1: Select random symbols
        symbol_count = random.randint(*symbol_count_range)
        selected_symbols = self.symbol_manager.get_random_symbols(symbol_count, with_replacement=with_replacement)
        print(f"Selected {len(selected_symbols)} symbols")
        
        # Step 2: Render symbols with random scaling and rotation
        symbols_data = []
        for symbol_name in selected_symbols:
            scale = random.uniform(*symbol_size_range)
            
            # Random rotation if enabled
            rotation = 0
            if enable_rotation:
                rotation = random.choice([0, 90, 180, 270])
            
            try:
                image = self.symbol_manager.render_symbol(symbol_name, scale=scale, rotation=rotation)
                symbols_data.append({
                    'name': symbol_name,
                    'image': image,
                    'scale': scale,
                    'rotation': rotation
                })
                rotation_str = f", rotation: {rotation}°" if rotation != 0 else ""
                print(f"  - {symbol_name} (scale: {scale:.2f}{rotation_str})")
            except Exception as e:
                print(f"  - Failed to render {symbol_name}: {e}")
        
        if not symbols_data:
            raise ValueError("No symbols could be rendered")
        
        # Step 3: Layout symbols on canvas (accounting for text box areas)
        layout_engine = LayoutEngine(*output_resolution, text_box_areas=text_box_areas)
        placed_symbols = layout_engine.place_symbols(symbols_data)
        print(f"Successfully placed {len(placed_symbols)} symbols")
        
        # Step 4: Generate captions for symbols
        symbol_captions = []
        if captions > 0.0:
            symbol_captions = self._generate_symbol_captions(placed_symbols, captions, output_resolution)
            print(f"Generated {len(symbol_captions)} symbol captions")
        
        # Step 5: Generate connections
        connections = layout_engine.generate_connections()
        print(f"Generated {len(connections)} connections")
        
        # Step 6: Render final diagram (including text boxes and captions)
        renderer = Renderer(*output_resolution)
        final_image = renderer.render_diagram(placed_symbols, connections, 
                                            line_thickness=line_thickness, text_boxes=text_boxes,
                                            symbol_captions=symbol_captions)
        
        # Step 7: Save outputs
        renderer.save_image(final_image, str(image_path))
        renderer.export_annotations(placed_symbols, connections, str(json_path), 
                                   text_boxes=text_boxes, symbol_captions=symbol_captions)
        
        print(f"Generated files:")
        print(f"  - Image: {image_path}")
        print(f"  - Annotations: {json_path}")
        
        return str(image_path), str(json_path)
    
    def generate_batch(self,
                      count: int,
                      symbol_count_range: Tuple[int, int] = (5, 15),
                      symbol_size_range: Tuple[float, float] = (0.7, 1.5),
                      output_resolution: Tuple[int, int] = (1920, 1080),
                      output_directory: str = "./output/",
                      base_prefix: str = "synthetic_pnid",
                      line_thickness: int = 2,
                      enable_rotation: bool = True,
                      with_replacement: bool = False,
                      text_box_config: Optional[Dict[str, Any]] = None,
                      captions: float = 0.0) -> List[Tuple[str, str]]:
        """
        Generate multiple P&ID diagrams.
        
        Args:
            count: Number of diagrams to generate
            symbol_count_range: (min, max) number of symbols to include
            symbol_size_range: (min, max) scaling factors for symbols
            output_resolution: (width, height) of output image in pixels
            output_directory: Directory to save output files
            base_prefix: Base name for output files (will be numbered)
            line_thickness: Thickness of connection lines in pixels
            enable_rotation: Whether to randomly rotate symbols by 90/180/270 degrees
            with_replacement: If True, allows duplicate symbols; if False, each symbol appears at most once
            text_box_config: Optional text box configuration applied to all generated diagrams
            captions: Proportion of symbols (0.0-1.0) that should have text captions
            
        Returns:
            List of (image_path, json_path) tuples for generated files
        """
        results = []
        
        print(f"Generating {count} P&ID diagrams...")
        
        for i in range(count):
            prefix = f"{base_prefix}_{i+1:03d}"
            try:
                image_path, json_path = self.generate(
                    symbol_count_range=symbol_count_range,
                    symbol_size_range=symbol_size_range,
                    output_resolution=output_resolution,
                    output_prefix=prefix,
                    output_directory=output_directory,
                    line_thickness=line_thickness,
                    enable_rotation=enable_rotation,
                    with_replacement=with_replacement,
                    text_box_config=text_box_config,
                    captions=captions
                )
                results.append((image_path, json_path))
                print(f"Generated {i+1}/{count}: {prefix}")
            except Exception as e:
                print(f"Failed to generate {prefix}: {e}")
        
        print(f"Successfully generated {len(results)}/{count} diagrams")
        return results
    
    def list_available_symbols(self) -> List[str]:
        """Get list of all available symbol names."""
        return list(self.symbol_manager.get_all_symbols().keys())
    
    def get_symbol_categories(self) -> dict:
        """Get symbols organized by category."""
        symbols = self.symbol_manager.get_all_symbols()
        categories = {}
        
        for name, info in symbols.items():
            category = info['category']
            if category not in categories:
                categories[category] = []
            categories[category].append(name)
        
        return categories
    
    def _generate_symbol_captions(self, placed_symbols: List[Dict], caption_proportion: float, 
                                 canvas_size: Tuple[int, int]) -> List[Dict]:
        """
        Generate captions for a proportion of placed symbols.
        
        Args:
            placed_symbols: List of placed symbol dictionaries
            caption_proportion: Proportion (0.0-1.0) of symbols to caption
            canvas_size: (width, height) of canvas for positioning
            
        Returns:
            List of caption dictionaries with position and text info
        """
        if caption_proportion <= 0.0 or not placed_symbols:
            return []
        
        # Determine how many symbols should have captions
        num_captions = max(1, int(len(placed_symbols) * caption_proportion))
        
        # Randomly select symbols to caption
        symbols_to_caption = random.sample(placed_symbols, min(num_captions, len(placed_symbols)))
        
        captions = []
        canvas_width, canvas_height = canvas_size
        
        for symbol in symbols_to_caption:
            # Generate caption text
            caption_text = self._generate_caption_text(symbol)
            
            # Calculate caption position (next to symbol, avoiding overlaps)
            caption_position = self._calculate_caption_position(
                symbol, caption_text, canvas_width, canvas_height, placed_symbols, captions
            )
            
            if caption_position:  # Only add if position was found
                caption = {
                    'symbol_id': placed_symbols.index(symbol),
                    'symbol_name': symbol['name'],
                    'text': caption_text,
                    'position': caption_position,
                    'font_size': 10,  # Small font for captions
                    'color': 'black'
                }
                captions.append(caption)
        
        return captions
    
    def _generate_caption_text(self, symbol: Dict) -> str:
        """
        Generate realistic caption text for a symbol.
        
        Args:
            symbol: Symbol dictionary with name and other info
            
        Returns:
            Caption text string
        """
        symbol_name = symbol['name']
        
        # Common P&ID caption patterns
        caption_patterns = [
            # Equipment tags
            lambda: f"{self._get_equipment_prefix(symbol_name)}-{random.randint(100, 999)}",
            # Service descriptions
            lambda: f"{random.choice(['Hot', 'Cold', 'Steam', 'Water', 'Air', 'Gas'])} {symbol_name.title()}",
            # Size specifications
            lambda: f"{random.randint(1, 24)}\" {symbol_name.title()}",
            # Pressure ratings
            lambda: f"{symbol_name.title()} {random.choice(['150#', '300#', '600#', '900#'])}",
            # Simple identifiers
            lambda: f"{symbol_name.upper()}-{random.randint(1, 99)}",
            # Process identifiers
            lambda: f"{random.choice(['P', 'S', 'R', 'T'])}-{random.randint(100, 999)}"
        ]
        
        # Choose a random pattern
        pattern = random.choice(caption_patterns)
        return pattern()
    
    def _get_equipment_prefix(self, symbol_name: str) -> str:
        """Get appropriate equipment prefix based on symbol name."""
        prefixes = {
            'pump': 'P',
            'valve': 'V', 
            'tank': 'T',
            'vessel': 'V',
            'heat': 'E',
            'exchanger': 'E',
            'reactor': 'R',
            'column': 'C',
            'tower': 'T',
            'compressor': 'K',
            'turbine': 'G',
            'motor': 'M',
            'instrument': 'I',
            'control': 'C'
        }
        
        symbol_lower = symbol_name.lower()
        for key, prefix in prefixes.items():
            if key in symbol_lower:
                return prefix
        
        # Default prefix
        return 'E'
    
    def _calculate_caption_position(self, symbol: Dict, caption_text: str, 
                                   canvas_width: int, canvas_height: int,
                                   all_symbols: List[Dict], existing_captions: List[Dict]) -> Optional[Tuple[int, int]]:
        """
        Calculate optimal position for caption near symbol.
        
        Args:
            symbol: Symbol dictionary with bbox info
            caption_text: Text to be displayed
            canvas_width: Canvas width
            canvas_height: Canvas height
            all_symbols: All placed symbols (for collision detection)
            existing_captions: Already placed captions (for collision detection)
            
        Returns:
            (x, y) position for caption, or None if no good position found
        """
        symbol_bbox = symbol['bbox']
        sx1, sy1, sx2, sy2 = symbol_bbox
        
        # Estimate caption dimensions (rough approximation)
        char_width = 6  # Approximate character width for font size 10
        char_height = 12  # Approximate character height for font size 10
        caption_width = len(caption_text) * char_width
        caption_height = char_height
        
        # Define potential positions around the symbol (in order of preference)
        margin = 5  # Small margin between symbol and caption
        
        potential_positions = [
            # Right of symbol
            (sx2 + margin, sy1 + (sy2 - sy1) // 2 - caption_height // 2),
            # Left of symbol  
            (sx1 - caption_width - margin, sy1 + (sy2 - sy1) // 2 - caption_height // 2),
            # Below symbol
            (sx1 + (sx2 - sx1) // 2 - caption_width // 2, sy2 + margin),
            # Above symbol
            (sx1 + (sx2 - sx1) // 2 - caption_width // 2, sy1 - caption_height - margin),
            # Bottom-right corner
            (sx2 + margin, sy2 - caption_height),
            # Top-right corner
            (sx2 + margin, sy1),
            # Bottom-left corner
            (sx1 - caption_width - margin, sy2 - caption_height),
            # Top-left corner
            (sx1 - caption_width - margin, sy1)
        ]
        
        # Try each position and check for collisions
        for x, y in potential_positions:
            # Check if caption would be within canvas bounds
            if (x < 0 or y < 0 or 
                x + caption_width > canvas_width or 
                y + caption_height > canvas_height):
                continue
            
            caption_bbox = (x, y, x + caption_width, y + caption_height)
            
            # Check for collisions with symbols
            if self._caption_collides_with_symbols(caption_bbox, all_symbols):
                continue
            
            # Check for collisions with existing captions
            if self._caption_collides_with_captions(caption_bbox, existing_captions):
                continue
            
            # This position works
            return (x, y)
        
        # No good position found
        return None
    
    def _caption_collides_with_symbols(self, caption_bbox: Tuple[int, int, int, int], 
                                      symbols: List[Dict]) -> bool:
        """Check if caption bbox collides with any symbol."""
        cx1, cy1, cx2, cy2 = caption_bbox
        
        for symbol in symbols:
            sx1, sy1, sx2, sy2 = symbol['bbox']
            
            # Check for overlap
            if not (cx2 < sx1 or cx1 > sx2 or cy2 < sy1 or cy1 > sy2):
                return True
        
        return False
    
    def _caption_collides_with_captions(self, caption_bbox: Tuple[int, int, int, int],
                                       existing_captions: List[Dict]) -> bool:
        """Check if caption bbox collides with existing captions."""
        cx1, cy1, cx2, cy2 = caption_bbox
        
        for existing_caption in existing_captions:
            ex, ey = existing_caption['position']
            # Estimate existing caption size
            existing_text = existing_caption['text']
            char_width = 6
            char_height = 12
            ex2 = ex + len(existing_text) * char_width
            ey2 = ey + char_height
            
            # Check for overlap
            if not (cx2 < ex or cx1 > ex2 or cy2 < ey or cy1 > ey2):
                return True
        
        return False


if __name__ == "__main__":
    # Example usage
    generator = PnidGenerator()
    
    # Generate a single diagram with text box
    text_box_config = {
        'position': 'top',
        'size_percent': 15.0,
        'font_size': 14,
        'background_color': 'lightgray'
    }
    
    image_path, json_path = generator.generate(
        symbol_count_range=(8, 12),
        symbol_size_range=(0.8, 1.2),
        output_resolution=(1600, 1200),
        output_prefix="example_pnid",
        text_box_config=text_box_config,
        captions=0.5  # Add captions to 50% of symbols
    )
    
    print(f"\nExample diagram generated:")
    print(f"Image: {image_path}")
    print(f"Annotations: {json_path}")
    
    # Generate a diagram without text box (backward compatibility)
    image_path2, json_path2 = generator.generate(
        symbol_count_range=(6, 10),
        output_prefix="example_pnid_no_textbox",
        captions=0.3  # Add captions to 30% of symbols
    )
    
    print(f"\nExample diagram without text box generated:")
    print(f"Image: {image_path2}")
    print(f"Annotations: {json_path2}")
