import os
import json
from pathlib import Path
from typing import List, Dict, Tuple
import cairosvg
from PIL import Image
import io


class SymbolManager:
    """Manages loading and processing of symbol files (SVG, PNG, JPEG)."""
    
    def __init__(self, symbol_directory: str = "./symbols/"):
        self.symbol_directory = Path(symbol_directory)
        self.symbols = {}
        self.supported_extensions = {'.svg', '.png', '.jpg', '.jpeg'}
        self._load_symbols()
    
    def _load_symbols(self):
        """Load all symbol files (SVG, PNG, JPEG) and create symbol catalog."""
        if not self.symbol_directory.exists():
            raise FileNotFoundError(f"Symbol directory not found: {self.symbol_directory}")
        
        # Find all supported symbol files
        symbol_files = []
        for ext in self.supported_extensions:
            symbol_files.extend(self.symbol_directory.glob(f"*{ext}"))
        
        print(f"Found {len(symbol_files)} symbol files")
        
        for symbol_file in symbol_files:
            symbol_name = self._extract_symbol_name(symbol_file.name)
            file_type = self._get_file_type(symbol_file.suffix.lower())
            
            self.symbols[symbol_name] = {
                'path': symbol_file,
                'category': self._extract_category(symbol_file.name),
                'filename': symbol_file.name,
                'type': file_type
            }
    
    def _extract_symbol_name(self, filename: str) -> str:
        """Extract clean symbol name from filename."""
        # Remove file extension
        name = Path(filename).stem
        
        # Split on underscore and take the part after the first underscore
        # This removes the category prefix
        parts = name.split('_', 1)
        if len(parts) > 1:
            return parts[1].strip()
        return name.strip()
    
    def _extract_category(self, filename: str) -> str:
        """Extract category from filename."""
        name = Path(filename).stem
        parts = name.split('_', 1)
        return parts[0] if len(parts) > 1 else "Unknown"
    
    def _get_file_type(self, extension: str) -> str:
        """Determine file type from extension."""
        if extension == '.svg':
            return 'svg'
        elif extension in ['.png', '.jpg', '.jpeg']:
            return 'image'
        else:
            return 'unknown'
    
    def get_all_symbols(self) -> Dict[str, Dict]:
        """Get all available symbols."""
        return self.symbols
    
    def get_random_symbols(self, count: int, with_replacement: bool = False) -> List[str]:
        """Get a random selection of symbol names.
        
        Args:
            count: Number of symbols to select
            with_replacement: If True, allows duplicate symbols; if False, each symbol can only be selected once
            
        Returns:
            List of selected symbol names
        """
        import random
        symbol_names = list(self.symbols.keys())
        
        if with_replacement:
            # Allow duplicates - use random.choices
            return random.choices(symbol_names, k=count)
        else:
            # No duplicates - use random.sample (existing behavior)
            return random.sample(symbol_names, min(count, len(symbol_names)))
    
    def render_symbol(self, symbol_name: str, scale: float = 1.0, target_size: Tuple[int, int] = None, rotation: int = 0) -> Image.Image:
        """Render symbol to PIL Image with optional scaling and rotation."""
        if symbol_name not in self.symbols:
            raise ValueError(f"Symbol not found: {symbol_name}")
        
        symbol_info = self.symbols[symbol_name]
        symbol_path = symbol_info['path']
        file_type = symbol_info['type']
        
        # Load image based on file type
        if file_type == 'svg':
            image = self._render_svg(symbol_path)
        elif file_type == 'image':
            image = self._render_image(symbol_path)
        else:
            raise ValueError(f"Unsupported file type: {file_type}")
        
        # Convert to RGBA if not already
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        
        # Apply scaling
        if scale != 1.0 or target_size is not None:
            if target_size:
                image = image.resize(target_size, Image.Resampling.LANCZOS)
            else:
                new_size = (int(image.width * scale), int(image.height * scale))
                image = image.resize(new_size, Image.Resampling.LANCZOS)
        
        # Apply rotation
        if rotation != 0:
            # Validate rotation angle
            if rotation not in [0, 90, 180, 270]:
                raise ValueError(f"Rotation must be 0, 90, 180, or 270 degrees, got {rotation}")
            
            # Rotate the image
            image = image.rotate(-rotation, expand=True)  # Negative for clockwise rotation
        
        return image
    
    def _render_svg(self, svg_path: Path) -> Image.Image:
        """Render SVG file to PIL Image."""
        # Read SVG content
        with open(svg_path, 'r', encoding='utf-8') as f:
            svg_content = f.read()
        
        # Convert SVG to PNG bytes
        png_bytes = cairosvg.svg2png(bytestring=svg_content.encode('utf-8'))
        
        # Load as PIL Image
        return Image.open(io.BytesIO(png_bytes))
    
    def _render_image(self, image_path: Path) -> Image.Image:
        """Load image file as PIL Image."""
        return Image.open(image_path)
    
    def get_symbol_info(self, symbol_name: str) -> Dict:
        """Get information about a specific symbol."""
        if symbol_name not in self.symbols:
            raise ValueError(f"Symbol not found: {symbol_name}")
        return self.symbols[symbol_name]
