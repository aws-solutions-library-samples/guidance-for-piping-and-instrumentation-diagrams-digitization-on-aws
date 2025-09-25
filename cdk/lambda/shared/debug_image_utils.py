"""
Shared debug image utilities for P&ID processing pipeline.

Provides consistent debug image generation across symbol detection, text detection, and line detection components.
"""

import io
import logging
from typing import Dict, List, Any, Tuple, Optional
import boto3
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)
s3_client = boto3.client('s3')

# Standard color palette for consistent visualization across components
DEBUG_COLORS = {
    'symbol_high': '#00FF00',      # Green for high confidence symbols (>0.8)
    'symbol_medium': '#FFFF00',    # Yellow for medium confidence symbols (0.5-0.8)
    'symbol_low': '#FF0000',       # Red for low confidence symbols (<0.5)
    'symbol_box': '#FF0000',       # Red for symbol bounding boxes (line detection style)
    'text_box': '#0000FF',         # Blue for text bounding boxes
    'text_filtered': '#808080',    # Gray for filtered text
    'line_detected': '#00FF00',    # Green for detected lines
    'background': '#FFFFFF',       # White background for labels
    'text_color': '#000000',       # Black text for labels
    'border': '#000000'           # Black borders
}

def get_adaptive_font(image_width: int, image_height: int, base_size: int = 12) -> Optional[ImageFont.ImageFont]:
    """
    Get adaptive font size based on image dimensions with fallback options.
    
    Args:
        image_width: Image width in pixels
        image_height: Image height in pixels
        base_size: Base font size
        
    Returns:
        Font object or None if no font available
    """
    font_size = max(base_size, min(image_width, image_height) // 80)
    
    # Try different font paths for cross-platform compatibility
    font_paths = [
        "/System/Library/Fonts/Arial.ttf",  # macOS
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
        "arial.ttf"  # Windows
    ]
    
    for font_path in font_paths:
        try:
            return ImageFont.truetype(font_path, font_size)
        except (OSError, IOError):
            continue
    
    # Fallback to default font
    try:
        return ImageFont.load_default()
    except:
        return None

def draw_bounding_box(
    draw: ImageDraw.ImageDraw,
    bbox: Dict[str, float],
    color: str,
    thickness: int = 2,
    image_width: int = None,
    image_height: int = None
) -> None:
    """
    Draw a bounding box on the image.
    
    Args:
        draw: PIL ImageDraw object
        bbox: Bounding box dict with coordinates
        color: Color hex string
        thickness: Line thickness
        image_width: Image width for thickness scaling
        image_height: Image height for thickness scaling
    """
    # Extract coordinates from different bbox formats
    if 'x1' in bbox and 'y1' in bbox:
        # Format: {x1, y1, x2, y2}
        x1, y1, x2, y2 = bbox['x1'], bbox['y1'], bbox['x2'], bbox['y2']
    elif 'x' in bbox and 'y' in bbox:
        # Format: {x, y, width, height}
        x1, y1 = bbox['x'], bbox['y']
        x2, y2 = x1 + bbox['width'], y1 + bbox['height']
    elif 'left' in bbox and 'top' in bbox:
        # Format: {left, top, right, bottom} or {left, top, width, height}
        x1, y1 = bbox['left'], bbox['top']
        if 'right' in bbox and 'bottom' in bbox:
            x2, y2 = bbox['right'], bbox['bottom']
        else:
            x2, y2 = x1 + bbox['width'], y1 + bbox['height']
    elif isinstance(bbox, list) and len(bbox) >= 4:
        # Format: [x1, y1, x2, y2]
        x1, y1, x2, y2 = bbox[:4]
    else:
        logger.warning(f"Unknown bbox format: {bbox}")
        return
    
    # Scale thickness based on image size
    if image_width and image_height:
        thickness = max(thickness, min(image_width, image_height) // 500)
    
    # Draw multiple rectangles for thickness
    for offset in range(thickness):
        draw.rectangle([x1-offset, y1-offset, x2+offset, y2+offset], 
                      outline=color, fill=None)

def draw_text_label(
    draw: ImageDraw.ImageDraw,
    text: str,
    position: Tuple[int, int],
    font: Optional[ImageFont.ImageFont],
    background_color: str = DEBUG_COLORS['background'],
    text_color: str = DEBUG_COLORS['text_color'],
    padding: int = 2
) -> None:
    """
    Draw text label with background.
    
    Args:
        draw: PIL ImageDraw object
        text: Text to draw
        position: (x, y) position for text
        font: Font object
        background_color: Background color hex string
        text_color: Text color hex string
        padding: Padding around text
    """
    x, y = position
    
    # Get text dimensions
    if font:
        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
    else:
        # Estimate dimensions for default font
        text_width = len(text) * 6
        text_height = 11
    
    # Draw background rectangle
    draw.rectangle([x, y, x + text_width + padding * 2, y + text_height + padding * 2], 
                  fill=background_color, outline=DEBUG_COLORS['border'])
    
    # Draw text
    if font:
        draw.text((x + padding, y + padding), text, fill=text_color, font=font)
    else:
        draw.text((x + padding, y + padding), text, fill=text_color)

def add_image_summary(
    draw: ImageDraw.ImageDraw,
    summary_text: str,
    font: Optional[ImageFont.ImageFont],
    position: Tuple[int, int] = (10, 10)
) -> None:
    """
    Add summary statistics to image.
    
    Args:
        draw: PIL ImageDraw object
        summary_text: Summary text to display
        font: Font object
        position: (x, y) position for summary
    """
    draw_text_label(draw, summary_text, position, font, 
                   background_color=DEBUG_COLORS['background'],
                   text_color=DEBUG_COLORS['text_color'])

def save_debug_image_to_s3(
    image: Image.Image,
    bucket: str,
    s3_key: str,
    format: str = 'PNG',
    quality: int = 95
) -> None:
    """
    Save PIL Image to S3.
    
    Args:
        image: PIL Image object
        bucket: S3 bucket name
        s3_key: S3 key for the image
        format: Image format (PNG, JPEG)
        quality: JPEG quality (ignored for PNG)
    """
    try:
        # Convert image to bytes
        output_buffer = io.BytesIO()
        if format.upper() == 'JPEG':
            # Convert to RGB for JPEG if necessary
            if image.mode in ('RGBA', 'LA', 'P'):
                image = image.convert('RGB')
            image.save(output_buffer, format='JPEG', quality=quality)
            content_type = 'image/jpeg'
        else:
            image.save(output_buffer, format='PNG')
            content_type = 'image/png'
        
        output_buffer.seek(0)
        
        # Upload to S3
        s3_client.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=output_buffer.getvalue(),
            ContentType=content_type
        )
        
        logger.info(f"Debug image saved to s3://{bucket}/{s3_key}")
        
    except Exception as e:
        logger.error(f"Failed to save debug image to S3: {str(e)}")
        raise

def generate_symbol_debug_image(
    image_data: bytes,
    detections: List[Dict[str, Any]],
    path_manager,
    title: str = "Symbol Detection Debug"
) -> str:
    """
    Generate debug image for symbol detections using shared utilities (backward compatibility).
    
    Args:
        image_data: Original image data as bytes
        detections: List of detection results
        path_manager: ExecutionPathManager for S3 paths
        title: Title for the debug image
        
    Returns:
        S3 key where debug image is stored
    """
    result = generate_symbol_debug_image_pair(image_data, detections, path_manager, title)
    return result['labeled_key']


def generate_symbol_debug_image_pair(
    image_data: bytes,
    detections: List[Dict[str, Any]],
    path_manager,
    title: str = "Symbol Detection Debug"
) -> Dict[str, str]:
    """
    Generate both labeled and boxes-only debug images for symbol detections.
    
    Args:
        image_data: Original image data as bytes
        detections: List of detection results
        path_manager: ExecutionPathManager for S3 paths
        title: Title for the debug images
        
    Returns:
        Dict with keys 'labeled_key' and 'boxes_key' containing S3 keys
    """
    try:
        # Load the image
        base_image = Image.open(io.BytesIO(image_data))
        
        # Convert to RGB if necessary
        if base_image.mode != 'RGB':
            base_image = base_image.convert('RGB')
        
        # Get adaptive font
        font = get_adaptive_font(base_image.width, base_image.height)
        
        # Create copies for both versions
        labeled_image = base_image.copy()
        boxes_image = base_image.copy()
        
        labeled_draw = ImageDraw.Draw(labeled_image)
        boxes_draw = ImageDraw.Draw(boxes_image)
        
        # Draw bounding boxes for both images
        for i, detection in enumerate(detections):
            # Get confidence score
            confidence = detection.get('confidence', detection.get('score', 0.0))
            
            # Determine color based on confidence
            if confidence > 0.8:
                color = DEBUG_COLORS['symbol_high']
            elif confidence > 0.5:
                color = DEBUG_COLORS['symbol_medium']
            else:
                color = DEBUG_COLORS['symbol_low']
            
            bbox = detection.get('bbox', detection.get('bounding_box', {}))
            
            # Draw bounding box on both images
            draw_bounding_box(labeled_draw, bbox, color, thickness=2, 
                            image_width=labeled_image.width, image_height=labeled_image.height)
            draw_bounding_box(boxes_draw, bbox, color, thickness=2, 
                            image_width=boxes_image.width, image_height=boxes_image.height)
            
            # Only add labels to the labeled version
            class_name = detection.get('class_name', detection.get('class', f"Class{detection.get('class_id', 'Unknown')}"))
            label_text = f"{class_name}: {confidence:.2f}"
            
            # Position label above bounding box
            if 'x1' in bbox:
                label_x, label_y = int(bbox['x1']), max(0, int(bbox['y1']) - 25)
            elif 'x' in bbox:
                label_x, label_y = int(bbox['x']), max(0, int(bbox['y']) - 25)
            else:
                label_x, label_y = 10, 10 + i * 30  # Fallback positioning
            
            # Draw label only on labeled image
            draw_text_label(labeled_draw, label_text, (label_x, label_y), font, 
                          background_color=color, text_color=DEBUG_COLORS['text_color'])
        
        # Add summary to both images
        labeled_summary = f"{title}: {len(detections)} detections"
        boxes_summary = f"{title}: {len(detections)} detections (boxes only)"
        
        add_image_summary(labeled_draw, labeled_summary, font)
        add_image_summary(boxes_draw, boxes_summary, font)
        
        # Save both images to S3
        labeled_s3_key = path_manager.get_symbol_debug_image_labeled_s3_key()
        boxes_s3_key = path_manager.get_symbol_debug_image_boxes_s3_key()
        
        save_debug_image_to_s3(labeled_image, path_manager.output_bucket, labeled_s3_key)
        save_debug_image_to_s3(boxes_image, path_manager.output_bucket, boxes_s3_key)
        
        logger.info(f"Generated dual symbol debug images: labeled={labeled_s3_key}, boxes={boxes_s3_key}")
        
        return {
            'labeled_key': labeled_s3_key,
            'boxes_key': boxes_s3_key
        }
        
    except Exception as e:
        logger.error(f"Failed to generate symbol debug image pair: {str(e)}")
        raise

def generate_text_debug_image(
    image_data: bytes,
    text_elements: List[Dict[str, Any]],
    path_manager,
    filtering_stats: Optional[Dict[str, Any]] = None,
    title: str = "Text Detection Debug"
) -> str:
    """
    Generate debug image for text detections.
    
    Args:
        image_data: Original image data as bytes
        text_elements: List of text elements with bounding boxes
        path_manager: ExecutionPathManager for S3 paths
        filtering_stats: Optional filtering statistics
        title: Title for the debug image
        
    Returns:
        S3 key where debug image is stored
    """
    try:
        # Load the image
        image = Image.open(io.BytesIO(image_data))
        
        # Convert to RGB if necessary
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        # Create drawing context
        draw = ImageDraw.Draw(image)
        
        # Get adaptive font
        font = get_adaptive_font(image.width, image.height)
        
        # Draw bounding boxes and labels for each text element
        for i, element in enumerate(text_elements):
            text_content = element.get('text', '')
            bbox = element.get('bounding_box', {})
            
            # Draw bounding box in blue (consistent with line detection)
            draw_bounding_box(draw, bbox, DEBUG_COLORS['text_box'], 
                            thickness=2, image_width=image.width, image_height=image.height)
            
            # Prepare label text (truncate long text)
            display_text = text_content[:20] + "..." if len(text_content) > 20 else text_content
            label_text = f"Text: {display_text}"
            
            # Position label above bounding box
            if 'x' in bbox:
                label_x, label_y = int(bbox['x']), max(0, int(bbox['y']) - 25)
            elif 'left' in bbox:
                label_x, label_y = int(bbox['left']), max(0, int(bbox['top']) - 25)
            else:
                label_x, label_y = 10, 40 + i * 20  # Fallback positioning
            
            # Draw label
            draw_text_label(draw, label_text, (label_x, label_y), font, 
                          background_color=DEBUG_COLORS['background'], 
                          text_color=DEBUG_COLORS['text_color'])
        
        # Add summary with filtering info if available
        summary_lines = [f"{title}: {len(text_elements)} elements"]
        if filtering_stats:
            if filtering_stats.get('filtering_applied'):
                original_count = filtering_stats.get('original_count', 0)
                filtered_count = filtering_stats.get('filtered_count', 0)
                summary_lines.append(f"Filtered: {original_count} → {len(text_elements)} ({filtered_count} removed)")
        
        # Draw multi-line summary
        for i, line in enumerate(summary_lines):
            add_image_summary(draw, line, font, position=(10, 10 + i * 25))
        
        # Show filtering region if available
        if filtering_stats and filtering_stats.get('crop_region'):
            crop = filtering_stats['crop_region']
            crop_bbox = {
                'x': crop['x'], 'y': crop['y'], 
                'width': crop['width'], 'height': crop['height']
            }
            draw_bounding_box(draw, crop_bbox, '#FF00FF', thickness=3, 
                            image_width=image.width, image_height=image.height)
            
            # Add crop region label
            draw_text_label(draw, "Crop Region", (crop['x'], crop['y'] - 30), font,
                          background_color='#FF00FF', text_color=DEBUG_COLORS['text_color'])
        
        # Save to S3
        debug_s3_key = path_manager.get_text_debug_image_s3_key()
        save_debug_image_to_s3(image, path_manager.output_bucket, debug_s3_key)
        
        return debug_s3_key
        
    except Exception as e:
        logger.error(f"Failed to generate text debug image: {str(e)}")
        raise
