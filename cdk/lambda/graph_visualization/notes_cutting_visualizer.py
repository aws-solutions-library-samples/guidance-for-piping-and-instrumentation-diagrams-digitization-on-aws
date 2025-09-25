import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
from PIL import Image
from typing import Dict, Any, Optional
import io


class NotesCuttingVisualizer:
    """Create visualizations showing the notes cutting area on the original image"""
    
    def __init__(self):
        self.overlay_color = 'red'
        self.overlay_alpha = 0.3
        self.border_color = 'darkred'
        self.text_color = 'white'
        self.text_bg_color = 'red'
    
    def create_notes_cutting_visualization(self, original_image_bytes: bytes, 
                                         notes_info: Dict[str, Any],
                                         original_dimensions: Optional[Dict[str, int]] = None) -> Optional[bytes]:
        """
        Create visualization showing the original image with notes cutting area overlay
        
        Args:
            original_image_bytes: Original image data as bytes
            notes_info: Notes coordinates and metadata from notes processor
            original_dimensions: Original image dimensions (width, height) before processing
            
        Returns:
            PNG image as bytes showing original image with cutting area highlighted
        """
        try:
            if not notes_info or notes_info.get('x') is None:
                # Create a simple message image if no notes info
                return self._create_no_notes_image()
            
            # Log coordinate space information for debugging
            coordinate_space = notes_info.get('coordinate_space', 'unknown')
            print(f"Notes coordinates coordinate space: {coordinate_space}")
            if coordinate_space == 'original_image':
                print("Using frame-adjusted coordinates for original image space")
            
            # Always load and display the actual original image
            image = Image.open(io.BytesIO(original_image_bytes))
            
            # Convert to RGB if necessary
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            # Use original dimensions if provided, otherwise get from actual image
            if original_dimensions and original_dimensions.get('width') and original_dimensions.get('height'):
                canvas_width = original_dimensions['width']
                canvas_height = original_dimensions['height']
                title = f"Original Image Dimensions: {canvas_width} × {canvas_height} - Notes Cutting Area"
            else:
                canvas_width, canvas_height = image.size
                title = f"Image Dimensions: {canvas_width} × {canvas_height} - Notes Cutting Area"
            
            # Create matplotlib figure with appropriate aspect ratio
            aspect_ratio = canvas_width / canvas_height
            if aspect_ratio > 1:
                fig_width = 16
                fig_height = 16 / aspect_ratio
            else:
                fig_width = 12 * aspect_ratio
                fig_height = 12
            
            fig, ax = plt.subplots(1, 1, figsize=(fig_width, fig_height))
            
            # Display the actual original image
            ax.imshow(image)
            
            # Set coordinate system limits to match the expected dimensions
            ax.set_xlim(0, canvas_width)
            ax.set_ylim(canvas_height, 0)  # Invert Y axis to match image coordinates
            
            # Extract notes coordinates
            x = notes_info.get('x', 0)
            y = notes_info.get('y', 0)
            width = notes_info.get('width', 0)
            height = notes_info.get('height', 0)
            confidence = notes_info.get('confidence', 0)
            method_used = notes_info.get('method_used', 'unknown')
            
            # Draw cutting area overlay
            self._draw_cutting_overlay(ax, x, y, width, height, confidence, method_used)
            
            # Set title and formatting
            ax.set_title(title, fontsize=16, fontweight='bold')
            ax.set_xlabel('X Coordinate')
            ax.set_ylabel('Y Coordinate')
            ax.grid(True, alpha=0.3)
            
            # Adjust layout
            plt.tight_layout()
            
            # Convert to bytes
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', 
                       facecolor='white', edgecolor='none')
            buf.seek(0)
            image_bytes = buf.read()
            plt.close()
            
            return image_bytes
            
        except Exception as e:
            print(f"Error creating notes cutting visualization: {str(e)}")
            # Return a fallback error image
            return self._create_error_image(str(e))
    
    def _draw_cutting_overlay(self, ax, x: float, y: float, width: float, height: float,
                             confidence: float, method_used: str):
        """Draw the cutting area overlay with annotations"""
        
        # Draw semi-transparent overlay rectangle
        cutting_rect = patches.Rectangle(
            (x, y),
            width,
            height,
            linewidth=3,
            edgecolor=self.border_color,
            facecolor=self.overlay_color,
            alpha=self.overlay_alpha,
            linestyle='--',
            zorder=10
        )
        ax.add_patch(cutting_rect)
        
        # Draw solid border for clarity
        border_rect = patches.Rectangle(
            (x, y),
            width,
            height,
            linewidth=2,
            edgecolor=self.border_color,
            facecolor='none',
            linestyle='-',
            zorder=11
        )
        ax.add_patch(border_rect)
        
        # Add corner markers
        corner_size = min(width, height) * 0.02
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
                facecolor=self.border_color,
                edgecolor=self.border_color,
                linewidth=1,
                zorder=12
            )
            ax.add_patch(corner_marker)
        
        # Add main label in center
        label_x = x + width / 2
        label_y = y + height / 2
        
        main_label = f"NOTES SECTION\n(TO BE REMOVED)"
        ax.text(label_x, label_y, 
               main_label,
               ha='center', va='center', fontsize=14,
               bbox=dict(boxstyle="round,pad=0.8", 
                        facecolor=self.text_bg_color, 
                        edgecolor='white',
                        alpha=0.9,
                        linewidth=2),
               color=self.text_color,
               fontweight='bold',
               zorder=15)
        
        # Add detailed info box in top-left corner of cutting area
        info_x = x + 10
        info_y = y + 30
        
        info_text = f"Confidence: {confidence:.2f}\nMethod: {method_used}\nSize: {int(width)}×{int(height)}"
        
        ax.text(info_x, info_y, 
               info_text,
               ha='left', va='top', fontsize=10,
               bbox=dict(boxstyle="round,pad=0.5", 
                        facecolor='white', 
                        edgecolor=self.border_color,
                        alpha=0.95,
                        linewidth=1),
               color=self.border_color,
               fontweight='normal',
               zorder=15)
        
        # Add coordinate labels
        coord_text = f"Origin: ({int(x)}, {int(y)})"
        ax.text(x, y - 15, 
               coord_text,
               ha='left', va='bottom', fontsize=9,
               bbox=dict(boxstyle="round,pad=0.3", 
                        facecolor='yellow', 
                        edgecolor=self.border_color,
                        alpha=0.9),
               color='black',
               fontweight='bold',
               zorder=15)
        
        # Add dimension arrows and labels
        self._add_dimension_annotations(ax, x, y, width, height)
    
    def _add_dimension_annotations(self, ax, x: float, y: float, width: float, height: float):
        """Add dimension arrows and labels"""
        
        # Width dimension (top)
        arrow_y = y - 30
        ax.annotate('', xy=(x + width, arrow_y), xytext=(x, arrow_y),
                   arrowprops=dict(arrowstyle='<->', color=self.border_color, lw=2))
        ax.text(x + width/2, arrow_y - 10, f'Width: {int(width)}px', 
               ha='center', va='top', fontsize=9, fontweight='bold',
               bbox=dict(boxstyle="round,pad=0.2", facecolor='white', alpha=0.8))
        
        # Height dimension (left)
        arrow_x = x - 30
        ax.annotate('', xy=(arrow_x, y + height), xytext=(arrow_x, y),
                   arrowprops=dict(arrowstyle='<->', color=self.border_color, lw=2))
        ax.text(arrow_x - 10, y + height/2, f'Height: {int(height)}px', 
               ha='right', va='center', fontsize=9, fontweight='bold', rotation=90,
               bbox=dict(boxstyle="round,pad=0.2", facecolor='white', alpha=0.8))
    
    def _create_no_notes_image(self) -> bytes:
        """Create a placeholder image when no notes information is available"""
        fig, ax = plt.subplots(1, 1, figsize=(12, 8))
        
        ax.text(0.5, 0.5, 'No Notes Section Detected\n\nOriginal image processed without notes removal', 
               ha='center', va='center', fontsize=16,
               bbox=dict(boxstyle="round,pad=1", facecolor='lightblue', alpha=0.8),
               transform=ax.transAxes)
        
        ax.set_title("Notes Cutting Area Analysis", fontsize=18, fontweight='bold')
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        
        plt.tight_layout()
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        image_bytes = buf.read()
        plt.close()
        
        return image_bytes
    
    def _create_error_image(self, error_message: str) -> bytes:
        """Create an error image when visualization fails"""
        fig, ax = plt.subplots(1, 1, figsize=(12, 8))
        
        ax.text(0.5, 0.5, f'Error Creating Notes Cutting Visualization\n\n{error_message}', 
               ha='center', va='center', fontsize=14,
               bbox=dict(boxstyle="round,pad=1", facecolor='lightcoral', alpha=0.8),
               transform=ax.transAxes)
        
        ax.set_title("Notes Cutting Area Analysis - Error", fontsize=18, fontweight='bold')
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        
        plt.tight_layout()
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        image_bytes = buf.read()
        plt.close()
        
        return image_bytes
