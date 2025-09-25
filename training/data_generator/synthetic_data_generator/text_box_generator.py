import random
import string
from typing import List, Tuple, Optional, Dict, Any
from PIL import Image, ImageDraw, ImageFont
import os


class TextBoxValidationError(Exception):
    """Custom exception for text box validation errors."""
    pass


class TextBoxGenerator:
    """Generates random text content for P&ID diagram text boxes."""
    
    def __init__(self, font_path: Optional[str] = None):
        """
        Initialize the TextBoxGenerator.
        
        Args:
            font_path: Optional path to custom font file. If None, uses system default.
        """
        self.font_path = font_path
        self._font_cache = {}
        
        # Technical terms commonly found in P&ID diagrams
        self.technical_terms = [
            "Process", "Flow", "Control", "System", "Unit", "Equipment", "Reactor",
            "Heat Exchanger", "Pump", "Valve", "Tank", "Vessel", "Column", "Tower",
            "Separator", "Filter", "Compressor", "Turbine", "Generator", "Motor",
            "Instrumentation", "Pipeline", "Stream", "Feed", "Product", "Recycle",
            "Bypass", "Emergency", "Safety", "Relief", "Pressure", "Temperature",
            "Level", "Flow Rate", "Density", "Viscosity", "Composition", "Quality"
        ]
        
        # Units commonly used in P&ID specifications
        self.units = [
            "kg/h", "m³/h", "L/min", "bar", "°C", "°F", "kPa", "MPa", "psi",
            "mm", "cm", "m", "in", "ft", "kW", "HP", "V", "A", "Hz", "rpm",
            "pH", "ppm", "wt%", "vol%", "mol%", "kg/m³", "g/L", "cP", "mPa·s"
        ]
        
        # Common P&ID labels and identifiers
        self.labels = [
            "TAG", "ID", "SIZE", "RATING", "MATERIAL", "SPEC", "SERVICE",
            "DESIGN", "OPERATING", "MAX", "MIN", "NORMAL", "ALARM", "TRIP",
            "INLET", "OUTLET", "SUPPLY", "RETURN", "DRAIN", "VENT", "SAMPLE"
        ]
        
        # Process-related words
        self.process_words = [
            "Primary", "Secondary", "Main", "Auxiliary", "Backup", "Standby",
            "Hot", "Cold", "High", "Low", "Medium", "Critical", "Non-Critical",
            "Continuous", "Batch", "Semi-Batch", "Forward", "Reverse", "Clean",
            "Dirty", "Fresh", "Recycled", "Waste", "Product", "Intermediate"
        ]
        
        # Common technical phrases
        self.phrases = [
            "Operating Conditions", "Design Parameters", "Process Specifications",
            "Equipment List", "Instrument Schedule", "Utility Requirements",
            "Safety Systems", "Control Philosophy", "Process Description",
            "Material Balance", "Energy Balance", "Equipment Sizing",
            "Piping Specifications", "Instrumentation Details"
        ]
    
    def generate_text_content(self, box_width: int, box_height: int, 
                            font_size: int = 12) -> List[str]:
        """
        Generate random text lines to fill the specified dimensions.
        
        Args:
            box_width: Width of text box in pixels
            box_height: Height of text box in pixels
            font_size: Font size to use for text
            
        Returns:
            List of text lines that fit within the specified dimensions
        """
        font = self._get_font(font_size)
        text_lines = []
        
        # Calculate approximate line height (font size + some padding)
        line_height = int(font_size * 1.2)
        max_lines = max(1, (box_height - 10) // line_height)  # 10px padding
        
        # Generate different types of content
        content_types = [
            self._generate_title_line,
            self._generate_specification_line,
            self._generate_parameter_line,
            self._generate_note_line,
            self._generate_equipment_line
        ]
        
        for i in range(max_lines):
            # Choose content type with some variety
            if i == 0:
                # First line is often a title
                line = self._generate_title_line()
            else:
                content_func = random.choice(content_types)
                line = content_func()
            
            # Ensure line fits within box width
            line = self._fit_text_to_width(line, box_width - 20, font)  # 20px padding
            
            if line:  # Only add non-empty lines
                text_lines.append(line)
        
        return text_lines
    
    def calculate_text_dimensions(self, text_lines: List[str], 
                                font_size: int) -> Tuple[int, int]:
        """
        Calculate required dimensions for given text content.
        
        Args:
            text_lines: List of text lines
            font_size: Font size used
            
        Returns:
            Tuple of (width, height) required for the text
        """
        if not text_lines:
            return (0, 0)
        
        font = self._get_font(font_size)
        
        # Calculate maximum width needed
        max_width = 0
        for line in text_lines:
            bbox = font.getbbox(line)
            line_width = bbox[2] - bbox[0]
            max_width = max(max_width, line_width)
        
        # Calculate total height
        line_height = int(font_size * 1.2)
        total_height = len(text_lines) * line_height
        
        # Add padding
        return (max_width + 20, total_height + 10)
    
    def get_random_technical_text(self) -> str:
        """Generate a single line of realistic technical text."""
        patterns = [
            lambda: f"{random.choice(self.technical_terms)} {random.choice(['System', 'Unit', 'Equipment'])}",
            lambda: f"{random.choice(self.process_words)} {random.choice(self.technical_terms)}",
            lambda: f"{random.choice(self.labels)}: {self._generate_alphanumeric_id()}",
            lambda: f"{random.choice(self.phrases)}",
            lambda: f"{random.choice(self.technical_terms)} - {random.choice(self.process_words)}"
        ]
        
        pattern = random.choice(patterns)
        return pattern()
    
    def _get_font(self, font_size: int) -> ImageFont.FreeTypeFont:
        """Get font object, using cache for performance."""
        cache_key = (self.font_path, font_size)
        
        if cache_key not in self._font_cache:
            try:
                if self.font_path and os.path.exists(self.font_path):
                    font = ImageFont.truetype(self.font_path, font_size)
                else:
                    # Try to use system default fonts
                    font = self._get_system_font(font_size)
            except (OSError, IOError):
                # Fallback to PIL default font
                font = ImageFont.load_default()
            
            self._font_cache[cache_key] = font
        
        return self._font_cache[cache_key]
    
    def _get_system_font(self, font_size: int) -> ImageFont.FreeTypeFont:
        """Try to load a system font."""
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
    
    def _generate_title_line(self) -> str:
        """Generate a title-style line."""
        patterns = [
            lambda: f"{random.choice(self.phrases)}",
            lambda: f"{random.choice(self.technical_terms)} {random.choice(['Diagram', 'Schematic', 'Layout'])}",
            lambda: f"Unit {random.randint(100, 999)} - {random.choice(self.technical_terms)}",
            lambda: f"{random.choice(self.process_words)} {random.choice(self.technical_terms)} System"
        ]
        return random.choice(patterns)()
    
    def _generate_specification_line(self) -> str:
        """Generate a specification-style line."""
        patterns = [
            lambda: f"{random.choice(self.labels)}: {self._generate_alphanumeric_id()}",
            lambda: f"Size: {random.randint(1, 48)} {random.choice(['in', 'mm', 'DN'])}",
            lambda: f"Rating: {random.choice(['150', '300', '600', '900', '1500'])} {random.choice(['lb', 'bar', 'psi'])}",
            lambda: f"Material: {random.choice(['CS', 'SS', '316L', 'Hastelloy', 'Inconel'])}",
            lambda: f"Service: {random.choice(self.process_words)} {random.choice(self.technical_terms)}"
        ]
        return random.choice(patterns)()
    
    def _generate_parameter_line(self) -> str:
        """Generate a parameter-style line."""
        value = round(random.uniform(0.1, 999.9), 1)
        unit = random.choice(self.units)
        parameter = random.choice(['Flow', 'Pressure', 'Temperature', 'Level', 'Density'])
        
        patterns = [
            lambda: f"{parameter}: {value} {unit}",
            lambda: f"Max {parameter}: {value} {unit}",
            lambda: f"Normal {parameter}: {value} {unit}",
            lambda: f"Design {parameter}: {value} {unit}"
        ]
        return random.choice(patterns)()
    
    def _generate_note_line(self) -> str:
        """Generate a note-style line."""
        patterns = [
            lambda: f"Note: {random.choice(['See', 'Refer to', 'Check'])} {random.choice(['drawing', 'specification', 'manual'])} {self._generate_alphanumeric_id()}",
            lambda: f"Typical for {random.choice(self.process_words).lower()} {random.choice(self.technical_terms).lower()}",
            lambda: f"As per {random.choice(['ASME', 'API', 'ANSI', 'ISO'])} {random.choice(['standard', 'specification'])}",
            lambda: f"See {random.choice(['P&ID', 'PFD', 'drawing'])} {self._generate_drawing_number()}"
        ]
        return random.choice(patterns)()
    
    def _generate_equipment_line(self) -> str:
        """Generate an equipment-style line."""
        equipment_id = f"{random.choice(['P', 'V', 'E', 'T', 'C', 'R'])}-{random.randint(100, 999)}"
        equipment_name = random.choice(self.technical_terms)
        
        patterns = [
            lambda: f"{equipment_id} {equipment_name}",
            lambda: f"{equipment_name} {equipment_id}",
            lambda: f"{equipment_id}: {random.choice(self.process_words)} {equipment_name}",
            lambda: f"Equipment: {equipment_id} ({equipment_name})"
        ]
        return random.choice(patterns)()
    
    def _generate_alphanumeric_id(self) -> str:
        """Generate a realistic alphanumeric identifier."""
        patterns = [
            lambda: f"{random.choice(string.ascii_uppercase)}{random.randint(100, 999)}",
            lambda: f"{random.choice(string.ascii_uppercase)}{random.choice(string.ascii_uppercase)}-{random.randint(10, 99)}",
            lambda: f"{random.randint(1000, 9999)}-{random.choice(string.ascii_uppercase)}",
            lambda: f"{random.choice(string.ascii_uppercase)}{random.choice(string.digits)}{random.choice(string.ascii_uppercase)}{random.choice(string.digits)}"
        ]
        return random.choice(patterns)()
    
    def _generate_drawing_number(self) -> str:
        """Generate a realistic drawing number."""
        return f"{random.randint(1000, 9999)}-{random.choice(string.ascii_uppercase)}-{random.randint(10, 99)}"
    
    def _fit_text_to_width(self, text: str, max_width: int, font: ImageFont.FreeTypeFont) -> str:
        """
        Truncate text to fit within specified width.
        
        Args:
            text: Original text
            max_width: Maximum width in pixels
            font: Font object for measurement
            
        Returns:
            Text that fits within the specified width
        """
        if not text:
            return text
        
        # Check if text already fits
        bbox = font.getbbox(text)
        text_width = bbox[2] - bbox[0]
        
        if text_width <= max_width:
            return text
        
        # Truncate text and add ellipsis
        ellipsis = "..."
        ellipsis_bbox = font.getbbox(ellipsis)
        ellipsis_width = ellipsis_bbox[2] - ellipsis_bbox[0]
        
        available_width = max_width - ellipsis_width
        
        # Binary search for the right length
        left, right = 0, len(text)
        best_length = 0
        
        while left <= right:
            mid = (left + right) // 2
            test_text = text[:mid]
            
            bbox = font.getbbox(test_text)
            test_width = bbox[2] - bbox[0]
            
            if test_width <= available_width:
                best_length = mid
                left = mid + 1
            else:
                right = mid - 1
        
        if best_length == 0:
            return ""
        
        return text[:best_length] + ellipsis
    
    @staticmethod
    def validate_text_box_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate and normalize text box configuration parameters.
        
        Args:
            config: Text box configuration dictionary or None
            
        Returns:
            Validated and normalized configuration dictionary
            
        Raises:
            TextBoxValidationError: If configuration is invalid
        """
        if config is None:
            return {}
        
        if not isinstance(config, dict):
            raise TextBoxValidationError(
                f"Text box configuration must be a dictionary, got {type(config).__name__}"
            )
        
        validated_config = {}
        
        # Validate position
        if 'position' in config:
            position = config['position']
            valid_positions = ['top', 'bottom', 'left', 'right']
            
            if not isinstance(position, str):
                raise TextBoxValidationError(
                    f"Text box position must be a string, got {type(position).__name__}"
                )
            
            if position not in valid_positions:
                raise TextBoxValidationError(
                    f"Text box position must be one of {valid_positions}, got '{position}'"
                )
            
            validated_config['position'] = position
        
        # Validate size_percent
        if 'size_percent' in config:
            size_percent = config['size_percent']
            
            if not isinstance(size_percent, (int, float)):
                raise TextBoxValidationError(
                    f"Text box size_percent must be a number, got {type(size_percent).__name__}"
                )
            
            if not (5.0 <= size_percent <= 50.0):
                raise TextBoxValidationError(
                    f"Text box size_percent must be between 5.0 and 50.0, got {size_percent}"
                )
            
            validated_config['size_percent'] = float(size_percent)
        
        # Validate font_size
        if 'font_size' in config:
            font_size = config['font_size']
            
            if not isinstance(font_size, int):
                raise TextBoxValidationError(
                    f"Text box font_size must be an integer, got {type(font_size).__name__}"
                )
            
            if not (8 <= font_size <= 72):
                raise TextBoxValidationError(
                    f"Text box font_size must be between 8 and 72, got {font_size}"
                )
            
            validated_config['font_size'] = font_size
        
        # Validate background_color
        if 'background_color' in config:
            bg_color = config['background_color']
            
            if not isinstance(bg_color, str):
                raise TextBoxValidationError(
                    f"Text box background_color must be a string, got {type(bg_color).__name__}"
                )
            
            # Basic color validation - accept common color names and hex codes
            valid_colors = [
                'white', 'black', 'red', 'green', 'blue', 'yellow', 'cyan', 'magenta',
                'gray', 'grey', 'lightgray', 'lightgrey', 'darkgray', 'darkgrey'
            ]
            
            if not (bg_color.lower() in valid_colors or TextBoxGenerator._is_valid_hex_color(bg_color)):
                raise TextBoxValidationError(
                    f"Text box background_color must be a valid color name or hex code, got '{bg_color}'"
                )
            
            validated_config['background_color'] = bg_color
        
        # Validate text_color
        if 'text_color' in config:
            text_color = config['text_color']
            
            if not isinstance(text_color, str):
                raise TextBoxValidationError(
                    f"Text box text_color must be a string, got {type(text_color).__name__}"
                )
            
            # Basic color validation - accept common color names and hex codes
            valid_colors = [
                'white', 'black', 'red', 'green', 'blue', 'yellow', 'cyan', 'magenta',
                'gray', 'grey', 'lightgray', 'lightgrey', 'darkgray', 'darkgrey'
            ]
            
            if not (text_color.lower() in valid_colors or TextBoxGenerator._is_valid_hex_color(text_color)):
                raise TextBoxValidationError(
                    f"Text box text_color must be a valid color name or hex code, got '{text_color}'"
                )
            
            validated_config['text_color'] = text_color
        
        # Check for unknown parameters
        known_params = {'position', 'size_percent', 'font_size', 'background_color', 'text_color'}
        unknown_params = set(config.keys()) - known_params
        
        if unknown_params:
            raise TextBoxValidationError(
                f"Unknown text box parameters: {sorted(unknown_params)}. "
                f"Valid parameters are: {sorted(known_params)}"
            )
        
        return validated_config
    
    @staticmethod
    def validate_multiple_text_boxes(configs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Validate multiple text box configurations and check for conflicts.
        
        Args:
            configs: List of text box configuration dictionaries
            
        Returns:
            List of validated configuration dictionaries
            
        Raises:
            TextBoxValidationError: If configurations are invalid or conflicting
        """
        if not isinstance(configs, list):
            raise TextBoxValidationError(
                f"Text box configurations must be a list, got {type(configs).__name__}"
            )
        
        if len(configs) == 0:
            return []
        
        validated_configs = []
        positions_used = set()
        
        for i, config in enumerate(configs):
            try:
                validated_config = TextBoxGenerator.validate_text_box_config(config)
                validated_configs.append(validated_config)
                
                # Check for position conflicts
                if 'position' in validated_config:
                    position = validated_config['position']
                    if position in positions_used:
                        available_positions = [p for p in ['top', 'bottom', 'left', 'right'] if p not in positions_used]
                        suggestion = f" Available positions: {available_positions}" if available_positions else ""
                        raise TextBoxValidationError(
                            f"Duplicate text box position '{position}' at index {i}. "
                            f"Each text box must have a unique position.{suggestion}"
                        )
                    positions_used.add(position)
                
            except TextBoxValidationError as e:
                raise TextBoxValidationError(f"Text box configuration at index {i}: {str(e)}")
        
        return validated_configs
    
    @staticmethod
    def get_default_config() -> Dict[str, Any]:
        """
        Get default text box configuration.
        
        Returns:
            Dictionary with default configuration values
        """
        return {
            'position': 'top',
            'size_percent': 15.0,
            'font_size': 12,
            'background_color': 'white',
            'text_color': 'black'
        }
    
    @staticmethod
    def merge_with_defaults(config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge user configuration with default values.
        
        Args:
            config: User-provided configuration dictionary
            
        Returns:
            Configuration dictionary with defaults applied for missing values
        """
        defaults = TextBoxGenerator.get_default_config()
        merged = defaults.copy()
        merged.update(config)
        return merged
    
    @staticmethod
    def _is_valid_hex_color(color: str) -> bool:
        """
        Check if a string is a valid hex color code.
        
        Args:
            color: Color string to validate
            
        Returns:
            True if valid hex color, False otherwise
        """
        if not color.startswith('#'):
            return False
        
        hex_part = color[1:]
        
        # Valid lengths are 3 (RGB) or 6 (RRGGBB)
        if len(hex_part) not in [3, 6]:
            return False
        
        # Check if all characters are valid hex digits
        try:
            int(hex_part, 16)
            return True
        except ValueError:
            return False
    
    @staticmethod
    def calculate_text_box_dimensions(canvas_width: int, canvas_height: int, 
                                    position: str, size_percent: float) -> Tuple[int, int, int, int]:
        """
        Calculate text box dimensions and position based on canvas size and configuration.
        
        Args:
            canvas_width: Width of the canvas in pixels
            canvas_height: Height of the canvas in pixels
            position: Text box position ('top', 'bottom', 'left', 'right')
            size_percent: Size as percentage of relevant dimension
            
        Returns:
            Tuple of (x, y, width, height) for the text box
            
        Raises:
            TextBoxValidationError: If parameters are invalid
        """
        if not isinstance(canvas_width, int) or canvas_width <= 0:
            raise TextBoxValidationError(
                f"Canvas width must be a positive integer, got {canvas_width}"
            )
        
        if not isinstance(canvas_height, int) or canvas_height <= 0:
            raise TextBoxValidationError(
                f"Canvas height must be a positive integer, got {canvas_height}"
            )
        
        valid_positions = ['top', 'bottom', 'left', 'right']
        if position not in valid_positions:
            raise TextBoxValidationError(
                f"Position must be one of {valid_positions}, got '{position}'"
            )
        
        if not (5.0 <= size_percent <= 50.0):
            raise TextBoxValidationError(
                f"Size percent must be between 5.0 and 50.0, got {size_percent}"
            )
        
        if position in ['top', 'bottom']:
            # Text box spans full width, height is percentage of canvas height
            box_width = canvas_width
            box_height = int(canvas_height * size_percent / 100.0)
            
            if position == 'top':
                x, y = 0, 0
            else:  # bottom
                x, y = 0, canvas_height - box_height
        
        else:  # left or right
            # Text box spans full height, width is percentage of canvas width
            box_width = int(canvas_width * size_percent / 100.0)
            box_height = canvas_height
            
            if position == 'left':
                x, y = 0, 0
            else:  # right
                x, y = canvas_width - box_width, 0
        
        return (x, y, box_width, box_height)
    
    @staticmethod
    def calculate_remaining_canvas_area(canvas_width: int, canvas_height: int,
                                      text_box_configs: List[Dict[str, Any]]) -> Tuple[int, int, int, int]:
        """
        Calculate the remaining canvas area available for symbols after text boxes are placed.
        
        Args:
            canvas_width: Width of the canvas in pixels
            canvas_height: Height of the canvas in pixels
            text_box_configs: List of validated text box configurations
            
        Returns:
            Tuple of (x, y, width, height) for the remaining area
            
        Raises:
            TextBoxValidationError: If text boxes leave insufficient space
        """
        if not text_box_configs:
            return (0, 0, canvas_width, canvas_height)
        
        # Start with full canvas
        remaining_x = 0
        remaining_y = 0
        remaining_width = canvas_width
        remaining_height = canvas_height
        
        # Apply each text box configuration
        for config in text_box_configs:
            position = config.get('position', 'top')
            size_percent = config.get('size_percent', 15.0)
            
            if position == 'top':
                box_height = int(canvas_height * size_percent / 100.0)
                remaining_y += box_height
                remaining_height -= box_height
            
            elif position == 'bottom':
                box_height = int(canvas_height * size_percent / 100.0)
                remaining_height -= box_height
            
            elif position == 'left':
                box_width = int(canvas_width * size_percent / 100.0)
                remaining_x += box_width
                remaining_width -= box_width
            
            elif position == 'right':
                box_width = int(canvas_width * size_percent / 100.0)
                remaining_width -= box_width
        
        # Validate that sufficient space remains
        min_width = 200
        min_height = 200
        
        if remaining_width < min_width or remaining_height < min_height:
            # Calculate total text box area percentage
            total_area_used = sum(config.get('size_percent', 15.0) for config in text_box_configs)
            
            # Provide helpful suggestions
            suggestions = []
            if total_area_used > 60:
                suggestions.append(f"reduce total text box size (currently {total_area_used:.1f}%)")
            if len(text_box_configs) > 2:
                suggestions.append("use fewer text boxes")
            if canvas_width < 800 or canvas_height < 600:
                suggestions.append("increase canvas resolution")
            
            suggestion_text = f" Try: {', '.join(suggestions)}." if suggestions else ""
            
            raise TextBoxValidationError(
                f"Text box configurations leave insufficient space for symbols. "
                f"Remaining area: {remaining_width}x{remaining_height}, "
                f"minimum required: {min_width}x{min_height}.{suggestion_text}"
            )
        
        return (remaining_x, remaining_y, remaining_width, remaining_height)
    
    @staticmethod
    def validate_text_box_with_canvas(config: Dict[str, Any], canvas_width: int, canvas_height: int) -> Dict[str, Any]:
        """
        Validate text box configuration against specific canvas dimensions.
        
        Args:
            config: Text box configuration dictionary
            canvas_width: Canvas width in pixels
            canvas_height: Canvas height in pixels
            
        Returns:
            Validated configuration dictionary
            
        Raises:
            TextBoxValidationError: If configuration is invalid for the given canvas
        """
        # First validate the basic configuration
        validated_config = TextBoxGenerator.validate_text_box_config(config)
        
        if not validated_config:
            return validated_config
        
        # Validate canvas dimensions
        if canvas_width <= 0 or canvas_height <= 0:
            raise TextBoxValidationError(
                f"Invalid canvas dimensions: {canvas_width}x{canvas_height}"
            )
        
        position = validated_config.get('position', 'top')
        size_percent = validated_config.get('size_percent', 15.0)
        
        # Calculate text box dimensions
        if position in ['top', 'bottom']:
            text_box_size = int(canvas_height * size_percent / 100.0)
            dimension_name = "height"
            canvas_dimension = canvas_height
        else:  # left or right
            text_box_size = int(canvas_width * size_percent / 100.0)
            dimension_name = "width"
            canvas_dimension = canvas_width
        
        # Check minimum text box size
        min_text_box_size = 50
        if text_box_size < min_text_box_size:
            min_percent = (min_text_box_size / canvas_dimension) * 100
            raise TextBoxValidationError(
                f"Text box {dimension_name} ({text_box_size}px) is too small for readable text. "
                f"Minimum size: {min_text_box_size}px ({min_percent:.1f}% of canvas {dimension_name}). "
                f"Try increasing size_percent to at least {min_percent:.1f}."
            )
        
        # Check if text box is too large relative to canvas
        max_reasonable_percent = 40.0
        if size_percent > max_reasonable_percent:
            remaining_percent = 100 - size_percent
            raise TextBoxValidationError(
                f"Text box size ({size_percent}%) leaves only {remaining_percent}% of canvas {dimension_name} for symbols. "
                f"Consider reducing size_percent to {max_reasonable_percent}% or less for better balance."
            )
        
        return validated_config
    
    @staticmethod
    def detect_text_box_conflicts(configs: List[Dict[str, Any]], canvas_width: int, canvas_height: int) -> List[str]:
        """
        Detect potential conflicts and issues with text box configurations.
        
        Args:
            configs: List of text box configuration dictionaries
            canvas_width: Canvas width in pixels
            canvas_height: Canvas height in pixels
            
        Returns:
            List of warning messages about potential issues
        """
        warnings = []
        
        if not configs:
            return warnings
        
        # Check for position conflicts (should be caught by validation, but double-check)
        positions = [config.get('position') for config in configs if 'position' in config]
        duplicate_positions = [pos for pos in set(positions) if positions.count(pos) > 1]
        
        if duplicate_positions:
            warnings.append(f"Duplicate text box positions detected: {duplicate_positions}")
        
        # Check total area usage
        total_horizontal_percent = sum(
            config.get('size_percent', 15.0) 
            for config in configs 
            if config.get('position') in ['left', 'right']
        )
        total_vertical_percent = sum(
            config.get('size_percent', 15.0) 
            for config in configs 
            if config.get('position') in ['top', 'bottom']
        )
        
        if total_horizontal_percent > 50:
            warnings.append(
                f"Left/right text boxes use {total_horizontal_percent:.1f}% of canvas width. "
                f"Consider reducing sizes for better symbol placement."
            )
        
        if total_vertical_percent > 50:
            warnings.append(
                f"Top/bottom text boxes use {total_vertical_percent:.1f}% of canvas height. "
                f"Consider reducing sizes for better symbol placement."
            )
        
        # Check for very small remaining area
        try:
            remaining_area = TextBoxGenerator.calculate_remaining_canvas_area(
                canvas_width, canvas_height, configs
            )
            remaining_x, remaining_y, remaining_width, remaining_height = remaining_area
            remaining_area_pixels = remaining_width * remaining_height
            total_canvas_area = canvas_width * canvas_height
            remaining_percent = (remaining_area_pixels / total_canvas_area) * 100
            
            if remaining_percent < 30:
                warnings.append(
                    f"Only {remaining_percent:.1f}% of canvas area remains for symbols. "
                    f"Consider reducing text box sizes for better symbol density."
                )
        except TextBoxValidationError:
            # This will be caught by the main validation, so just note it
            warnings.append("Text box configuration may leave insufficient space for symbols.")
        
        # Check for font size issues
        for i, config in enumerate(configs):
            font_size = config.get('font_size', 12)
            size_percent = config.get('size_percent', 15.0)
            position = config.get('position', 'top')
            
            if position in ['top', 'bottom']:
                text_box_height = int(canvas_height * size_percent / 100.0)
                if font_size > text_box_height / 3:
                    warnings.append(
                        f"Text box {i} font size ({font_size}px) may be too large for box height ({text_box_height}px). "
                        f"Consider reducing font_size or increasing size_percent."
                    )
            else:  # left or right
                text_box_width = int(canvas_width * size_percent / 100.0)
                if text_box_width < font_size * 10:  # Rough estimate for minimum readable width
                    warnings.append(
                        f"Text box {i} width ({text_box_width}px) may be too narrow for font size ({font_size}px). "
                        f"Consider increasing size_percent or reducing font_size."
                    )
        
        return warnings
    
    @staticmethod
    def suggest_text_box_improvements(config: Dict[str, Any], canvas_width: int, canvas_height: int) -> List[str]:
        """
        Provide suggestions for improving text box configuration.
        
        Args:
            config: Text box configuration dictionary
            canvas_width: Canvas width in pixels
            canvas_height: Canvas height in pixels
            
        Returns:
            List of improvement suggestions
        """
        suggestions = []
        
        if not config:
            return suggestions
        
        position = config.get('position', 'top')
        size_percent = config.get('size_percent', 15.0)
        font_size = config.get('font_size', 12)
        
        # Suggest optimal size ranges
        if position in ['top', 'bottom']:
            optimal_range = (10.0, 25.0)
            dimension = "height"
        else:
            optimal_range = (15.0, 30.0)
            dimension = "width"
        
        if size_percent < optimal_range[0]:
            suggestions.append(
                f"Consider increasing size_percent to at least {optimal_range[0]}% for better text readability"
            )
        elif size_percent > optimal_range[1]:
            suggestions.append(
                f"Consider reducing size_percent to {optimal_range[1]}% or less to preserve space for symbols"
            )
        
        # Font size suggestions
        if font_size < 10:
            suggestions.append("Consider increasing font_size to at least 10 for better readability")
        elif font_size > 18:
            suggestions.append("Consider reducing font_size to 18 or less to fit more text content")
        
        # Position-specific suggestions
        if position in ['left', 'right'] and canvas_width < 1200:
            suggestions.append(
                f"For narrow canvases ({canvas_width}px), consider using 'top' or 'bottom' position instead of '{position}'"
            )
        
        if position in ['top', 'bottom'] and canvas_height < 800:
            suggestions.append(
                f"For short canvases ({canvas_height}px), consider using 'left' or 'right' position instead of '{position}'"
            )
        
        return suggestions