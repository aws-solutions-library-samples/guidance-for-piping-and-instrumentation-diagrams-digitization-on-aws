"""
Notes Section Detection and Removal Service for P&ID Charts.

This service detects and removes notes sections from P&ID charts before processing.
Notes sections typically contain guidelines, legends, and tables that should not
be processed as part of the main diagram.
"""

import cv2
import numpy as np
import logging
from PIL import Image
from io import BytesIO
from typing import Dict, Any, Tuple, Optional, List
from dataclasses import dataclass

logger = logging.getLogger()


@dataclass
class NotesRegion:
    """Information about detected notes region"""
    x: int
    y: int
    width: int
    height: int
    confidence: float
    method_used: str


class NotesSectionDetector:
    """Service for detecting and removing notes sections from P&ID charts"""
    
    def __init__(self, 
                 text_density_threshold: float = 0.15,
                 min_notes_width_ratio: float = 0.2,
                 max_notes_width_ratio: float = 0.4,
                 edge_detection_threshold: int = 50):
        """
        Initialize the notes section detector.
        
        Args:
            text_density_threshold: Minimum text density to consider a region as notes
            min_notes_width_ratio: Minimum width ratio for notes section (relative to image width)
            max_notes_width_ratio: Maximum width ratio for notes section (relative to image width)
            edge_detection_threshold: Threshold for edge detection
        """
        self.text_density_threshold = text_density_threshold
        self.min_notes_width_ratio = min_notes_width_ratio
        self.max_notes_width_ratio = max_notes_width_ratio
        self.edge_detection_threshold = edge_detection_threshold
    
    def detect_notes_section(self, image_data: bytes) -> Optional[NotesRegion]:
        """
        Detect notes section in P&ID chart using multiple methods.
        
        Args:
            image_data: Raw image data as bytes
            
        Returns:
            NotesRegion object if notes section is detected, None otherwise
        """
        try:
            # Convert to OpenCV format
            image = Image.open(BytesIO(image_data))
            cv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
            
            height, width = gray.shape
            logger.info(f"Analyzing image for notes section: {width}x{height}")
            
            # Try multiple detection methods
            methods = [
                self._detect_by_text_density,
                self._detect_by_border_detection,
                self._detect_by_layout_analysis,
                self._detect_by_keyword_matching
            ]
            
            best_region = None
            best_confidence = 0.0
            
            for method in methods:
                try:
                    region = method(cv_image, gray)
                    if region and region.confidence > best_confidence:
                        best_region = region
                        best_confidence = region.confidence
                        logger.info(f"Better region found using {region.method_used}: confidence={region.confidence:.3f}")
                except Exception as e:
                    logger.warning(f"Detection method failed: {str(e)}")
                    continue
            
            if best_region:
                logger.info(f"Notes section detected: {best_region.width}x{best_region.height} at ({best_region.x}, {best_region.y}) using {best_region.method_used}")
            else:
                logger.info("No notes section detected")
            
            return best_region
            
        except Exception as e:
            logger.error(f"Error detecting notes section: {str(e)}")
            return None
    
    def _detect_by_text_density(self, cv_image: np.ndarray, gray: np.ndarray) -> Optional[NotesRegion]:
        """Detect notes section by analyzing text density in different regions"""
        height, width = gray.shape
        
        # Divide image into vertical strips
        strip_width = width // 10
        max_density = 0.0
        best_region = None
        
        # Check right side of image (common location for notes)
        for start_x in range(width - int(width * self.max_notes_width_ratio), width - strip_width, strip_width):
            region_width = width - start_x
            
            # Skip if region is too small or too large
            width_ratio = region_width / width
            if width_ratio < self.min_notes_width_ratio or width_ratio > self.max_notes_width_ratio:
                continue
            
            # Extract region
            region = gray[0:height, start_x:width]
            
            # Calculate text density using edge detection
            edges = cv2.Canny(region, 50, 150)
            text_density = np.sum(edges > 0) / (region.shape[0] * region.shape[1])
            
            if text_density > max_density and text_density > self.text_density_threshold:
                max_density = text_density
                best_region = NotesRegion(
                    x=start_x,
                    y=0,
                    width=region_width,
                    height=height,
                    confidence=min(text_density * 2, 1.0),  # Normalize confidence
                    method_used="text_density"
                )
        
        return best_region
    
    def _detect_by_border_detection(self, cv_image: np.ndarray, gray: np.ndarray) -> Optional[NotesRegion]:
        """Detect notes section by finding rectangular borders"""
        height, width = gray.shape
        
        # Apply edge detection
        edges = cv2.Canny(gray, self.edge_detection_threshold, self.edge_detection_threshold * 2)
        
        # Find contours
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        best_region = None
        best_score = 0.0
        
        for contour in contours:
            # Approximate contour to polygon
            epsilon = 0.02 * cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, epsilon, True)
            
            # Check if it's roughly rectangular (4-8 vertices)
            if len(approx) < 4 or len(approx) > 8:
                continue
            
            # Get bounding rectangle
            x, y, w, h = cv2.boundingRect(contour)
            
            # Check if it's in the right area and size
            width_ratio = w / width
            height_ratio = h / height
            position_ratio = x / width
            
            # Notes section criteria: right side, reasonable size
            if (position_ratio > 0.6 and  # Right side of image
                width_ratio >= self.min_notes_width_ratio and 
                width_ratio <= self.max_notes_width_ratio and
                height_ratio > 0.3):  # Reasonable height
                
                # Calculate score based on rectangularity and position
                area_ratio = cv2.contourArea(contour) / (w * h)
                score = area_ratio * width_ratio * position_ratio
                
                if score > best_score:
                    best_score = score
                    best_region = NotesRegion(
                        x=x,
                        y=y,
                        width=w,
                        height=h,
                        confidence=min(score * 2, 1.0),
                        method_used="border_detection"
                    )
        
        return best_region
    
    def _detect_by_layout_analysis(self, cv_image: np.ndarray, gray: np.ndarray) -> Optional[NotesRegion]:
        """Detect notes section by analyzing layout patterns"""
        height, width = gray.shape
        
        # Look for consistent horizontal lines (typical in notes sections)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (width//20, 1))
        horizontal_lines = cv2.morphologyEx(gray, cv2.MORPH_OPEN, kernel)
        
        # Find regions with many horizontal lines
        right_third = width * 2 // 3
        right_region = horizontal_lines[0:height, right_third:width]
        
        # Count horizontal line pixels
        line_density = np.sum(right_region > 100) / (right_region.shape[0] * right_region.shape[1])
        
        if line_density > 0.02:  # Threshold for significant horizontal line content
            # Find the leftmost consistent vertical boundary in the right region
            col_sums = np.sum(right_region > 100, axis=0)
            
            # Find where horizontal lines start being consistent
            for i in range(len(col_sums) - 10):
                if np.mean(col_sums[i:i+10]) > height * 0.1:  # Consistent lines
                    notes_start_x = right_third + i
                    notes_width = width - notes_start_x
                    
                    width_ratio = notes_width / width
                    if (width_ratio >= self.min_notes_width_ratio and 
                        width_ratio <= self.max_notes_width_ratio):
                        
                        return NotesRegion(
                            x=notes_start_x,
                            y=0,
                            width=notes_width,
                            height=height,
                            confidence=min(line_density * 10, 1.0),
                            method_used="layout_analysis"
                        )
        
        return None
    
    def _detect_by_keyword_matching(self, cv_image: np.ndarray, gray: np.ndarray) -> Optional[NotesRegion]:
        """Detect notes section by looking for common keywords/patterns"""
        height, width = gray.shape
        
        try:
            import pytesseract
            
            # Extract text from right portion of image
            right_portion = gray[0:height, width*2//3:width]
            
            # Use OCR to extract text
            text = pytesseract.image_to_string(right_portion).upper()
            
            # Common keywords in P&ID notes sections
            notes_keywords = [
                'NOTES', 'NOTE', 'GENERAL NOTES', 'LEGEND', 'SYMBOLS',
                'ABBREVIATIONS', 'SPECIFICATIONS', 'STANDARDS',
                'REVISION', 'REV', 'DRAWING', 'PROCESS', 'FLOW',
                'ELEVATION', 'TEMPERATURE', 'PRESSURE'
            ]
            
            keyword_count = sum(1 for keyword in notes_keywords if keyword in text)
            
            if keyword_count >= 2:  # At least 2 keywords found
                notes_width = width - (width * 2 // 3)
                width_ratio = notes_width / width
                
                if (width_ratio >= self.min_notes_width_ratio and 
                    width_ratio <= self.max_notes_width_ratio):
                    
                    confidence = min(keyword_count / len(notes_keywords), 1.0)
                    
                    return NotesRegion(
                        x=width * 2 // 3,
                        y=0,
                        width=notes_width,
                        height=height,
                        confidence=confidence,
                        method_used="keyword_matching"
                    )
            
        except ImportError:
            logger.warning("pytesseract not available for keyword matching")
        except Exception as e:
            logger.warning(f"Keyword matching failed: {str(e)}")
        
        return None
    
    def remove_notes_section(self, image_data: bytes, notes_region: NotesRegion = None) -> bytes:
        """
        Remove notes section from image.
        
        Args:
            image_data: Raw image data as bytes
            notes_region: Optional specific region to remove. If None, auto-detect.
            
        Returns:
            Image data with notes section removed
        """
        try:
            # Auto-detect if region not provided
            if notes_region is None:
                notes_region = self.detect_notes_section(image_data)
                if notes_region is None:
                    logger.info("No notes section detected, returning original image")
                    return image_data
            
            # Load image
            image = Image.open(BytesIO(image_data))
            width, height = image.size
            
            # Calculate crop boundaries
            crop_width = notes_region.x
            
            # Ensure we don't crop too much
            if crop_width < width * 0.5:  # Don't crop more than half the image
                logger.warning(f"Notes region too large, limiting crop to preserve main diagram")
                crop_width = int(width * 0.7)
            
            # Crop image to remove notes section
            cropped_image = image.crop((0, 0, crop_width, height))
            
            # Convert back to bytes
            output_buffer = BytesIO()
            cropped_image.save(output_buffer, format='PNG')
            cropped_data = output_buffer.getvalue()
            
            logger.info(f"Notes section removed: original {width}x{height} -> cropped {crop_width}x{height}")
            
            return cropped_data
            
        except Exception as e:
            logger.error(f"Error removing notes section: {str(e)}")
            return image_data  # Return original image on error
    
    def analyze_image_layout(self, image_data: bytes) -> Dict[str, Any]:
        """
        Analyze image layout and provide detailed information about detected regions.
        
        Args:
            image_data: Raw image data as bytes
            
        Returns:
            Dictionary with layout analysis results
        """
        try:
            image = Image.open(BytesIO(image_data))
            width, height = image.size
            
            notes_region = self.detect_notes_section(image_data)
            
            analysis = {
                'original_size': {'width': width, 'height': height},
                'notes_section_detected': notes_region is not None,
                'main_diagram_area': {
                    'width': width,
                    'height': height,
                    'area_ratio': 1.0
                }
            }
            
            if notes_region:
                main_width = notes_region.x
                analysis['notes_section'] = {
                    'x': notes_region.x,
                    'y': notes_region.y,
                    'width': notes_region.width,
                    'height': notes_region.height,
                    'confidence': notes_region.confidence,
                    'method_used': notes_region.method_used,
                    'area_ratio': (notes_region.width * notes_region.height) / (width * height)
                }
                analysis['main_diagram_area'] = {
                    'width': main_width,
                    'height': height,
                    'area_ratio': (main_width * height) / (width * height)
                }
            
            return analysis
            
        except Exception as e:
            logger.error(f"Error analyzing image layout: {str(e)}")
            return {
                'error': str(e),
                'notes_section_detected': False
            }
