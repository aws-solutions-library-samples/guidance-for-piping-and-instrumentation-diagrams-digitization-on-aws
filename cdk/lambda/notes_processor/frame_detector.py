import cv2
import numpy as np
from typing import Dict, Any, List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)

class FrameDetector:
    """
    Detects and removes frame lines from P&ID charts.
    Handles solid and dashed frames covering the entire perimeter.
    """
    
    def __init__(self):
        self.default_config = {
            'remove_frame': True,
            'frame_detection_sensitivity': 0.7,
            'min_frame_thickness': 2,
            'max_frame_thickness': 20,
            'edge_margin_ratio': 0.05,
            'safety_margin': 5,
            'min_line_length_ratio': 0.7,  # Minimum line length as ratio of edge
            'hough_threshold': 50,
            'hough_min_line_length': 100,
            'hough_max_line_gap': 20
        }
    
    def detect_and_remove_frame(self, image_data: bytes, config: Dict[str, Any] = None) -> Tuple[bytes, Dict[str, Any]]:
        """
        Main method to detect and remove frame from image.
        
        Args:
            image_data: Raw image bytes
            config: Configuration parameters
            
        Returns:
            Tuple of (processed_image_bytes, frame_analysis_info)
        """
        
        # Merge config with defaults
        frame_config = self.default_config.copy()
        if config:
            frame_config.update(config)
        
        if not frame_config.get('remove_frame', True):
            logger.info("Frame removal disabled")
            return image_data, {'frame_detected': False, 'frame_removed': False}
        
        # Convert bytes to OpenCV image
        nparr = np.frombuffer(image_data, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if image is None:
            raise ValueError("Could not decode image data")
        
        # Detect frame
        frame_info = self._detect_frame(image, frame_config)
        
        if not frame_info['frame_detected']:
            logger.info("No frame detected")
            return image_data, frame_info
        
        # Remove frame by cropping
        processed_image = self._remove_frame(image, frame_info, frame_config)
        
        # Convert back to bytes
        _, buffer = cv2.imencode('.png', processed_image)
        processed_bytes = buffer.tobytes()
        
        frame_info['frame_removed'] = True
        logger.info(f"Frame removed successfully. Original: {image.shape[:2]}, Processed: {processed_image.shape[:2]}")
        
        return processed_bytes, frame_info
    
    def _detect_frame(self, image: np.ndarray, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Detect frame lines around the perimeter of the image.
        """
        
        height, width = image.shape[:2]
        edge_margin = int(min(height, width) * config['edge_margin_ratio'])
        
        # Convert to grayscale for line detection
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Apply edge detection
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        
        # Detect lines using HoughLinesP
        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi/180,
            threshold=config['hough_threshold'],
            minLineLength=config['hough_min_line_length'],
            maxLineGap=config['hough_max_line_gap']
        )
        
        if lines is None:
            return {'frame_detected': False}
        
        # Analyze lines for frame patterns
        frame_bounds = self._analyze_frame_lines(lines, width, height, config)
        
        if frame_bounds:
            return {
                'frame_detected': True,
                'frame_bounds': frame_bounds,
                'total_lines': len(lines),
                'detection_method': 'hough_lines'
            }
        
        # Fallback: Check for consistent edge patterns
        edge_analysis = self._analyze_edge_patterns(gray, config)
        
        if edge_analysis['frame_detected']:
            return edge_analysis
        
        return {'frame_detected': False}
    
    def _analyze_frame_lines(self, lines: np.ndarray, width: int, height: int, config: Dict[str, Any]) -> Optional[Dict[str, int]]:
        """
        Analyze detected lines to identify frame boundaries.
        """
        
        # Separate lines by orientation and position
        horizontal_lines = []
        vertical_lines = []
        
        for line in lines:
            x1, y1, x2, y2 = line[0]
            
            # Calculate line properties
            length = np.sqrt((x2-x1)**2 + (y2-y1)**2)
            angle = np.arctan2(abs(y2-y1), abs(x2-x1)) * 180 / np.pi
            
            if angle < 30:  # More horizontal
                horizontal_lines.append({
                    'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
                    'length': length, 'y_avg': (y1+y2)/2
                })
            elif angle > 60:  # More vertical
                vertical_lines.append({
                    'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
                    'length': length, 'x_avg': (x1+x2)/2
                })
        
        # Find top and bottom horizontal lines
        top_lines = [l for l in horizontal_lines if l['y_avg'] < height * 0.2]
        bottom_lines = [l for l in horizontal_lines if l['y_avg'] > height * 0.8]
        
        # Find left and right vertical lines
        left_lines = [l for l in vertical_lines if l['x_avg'] < width * 0.2]
        right_lines = [l for l in vertical_lines if l['x_avg'] > width * 0.8]
        
        # Check if we have frame lines on all sides
        min_length_ratio = config['min_line_length_ratio']
        
        top_frame = self._find_best_frame_line(top_lines, width, min_length_ratio, 'horizontal')
        bottom_frame = self._find_best_frame_line(bottom_lines, width, min_length_ratio, 'horizontal')
        left_frame = self._find_best_frame_line(left_lines, height, min_length_ratio, 'vertical')
        right_frame = self._find_best_frame_line(right_lines, height, min_length_ratio, 'vertical')
        
        # We need at least 3 sides to consider it a frame
        frame_sides = sum([bool(top_frame), bool(bottom_frame), bool(left_frame), bool(right_frame)])
        
        if frame_sides >= 3:
            # Calculate frame bounds
            top_y = int(top_frame['y_avg']) if top_frame else 0
            bottom_y = int(bottom_frame['y_avg']) if bottom_frame else int(height)
            left_x = int(left_frame['x_avg']) if left_frame else 0
            right_x = int(right_frame['x_avg']) if right_frame else int(width)
            
            # Add safety margins
            safety = int(config['safety_margin'])
            
            return {
                'top': int(max(0, top_y + safety)),
                'bottom': int(min(int(height), bottom_y - safety)),
                'left': int(max(0, left_x + safety)),
                'right': int(min(int(width), right_x - safety))
            }
        
        return None
    
    def _find_best_frame_line(self, lines: List[Dict], dimension: int, min_ratio: float, orientation: str) -> Optional[Dict]:
        """
        Find the best frame line from a list of candidates.
        """
        
        if not lines:
            return None
        
        # Filter lines by minimum length
        min_length = dimension * min_ratio
        valid_lines = [l for l in lines if l['length'] >= min_length]
        
        if not valid_lines:
            return None
        
        # Return the longest line
        return max(valid_lines, key=lambda x: x['length'])
    
    def _analyze_edge_patterns(self, gray: np.ndarray, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fallback method: analyze edge patterns for consistent frame detection.
        """
        
        height, width = gray.shape
        edge_margin = int(min(height, width) * config['edge_margin_ratio'])
        
        # Sample edge regions
        top_edge = gray[:edge_margin, :]
        bottom_edge = gray[-edge_margin:, :]
        left_edge = gray[:, :edge_margin]
        right_edge = gray[:, -edge_margin:]
        
        # Look for consistent dark lines in edges
        frame_bounds = {}
        
        # Check top edge
        top_profile = np.mean(top_edge, axis=1)
        top_frame_y = self._find_edge_boundary(top_profile, 'top', config)
        if top_frame_y is not None:
            frame_bounds['top'] = top_frame_y + config['safety_margin']
        
        # Check bottom edge
        bottom_profile = np.mean(bottom_edge, axis=1)
        bottom_frame_y = self._find_edge_boundary(bottom_profile, 'bottom', config)
        if bottom_frame_y is not None:
            frame_bounds['bottom'] = height - edge_margin + bottom_frame_y - config['safety_margin']
        
        # Check left edge
        left_profile = np.mean(left_edge, axis=0)
        left_frame_x = self._find_edge_boundary(left_profile, 'left', config)
        if left_frame_x is not None:
            frame_bounds['left'] = left_frame_x + config['safety_margin']
        
        # Check right edge
        right_profile = np.mean(right_edge, axis=0)
        right_frame_x = self._find_edge_boundary(right_profile, 'right', config)
        if right_frame_x is not None:
            frame_bounds['right'] = width - edge_margin + right_frame_x - config['safety_margin']
        
        if len(frame_bounds) >= 2:  # At least 2 sides detected
            # Fill in missing bounds and ensure all values are Python integers
            if 'top' not in frame_bounds:
                frame_bounds['top'] = 0
            if 'bottom' not in frame_bounds:
                frame_bounds['bottom'] = int(height)
            if 'left' not in frame_bounds:
                frame_bounds['left'] = 0
            if 'right' not in frame_bounds:
                frame_bounds['right'] = int(width)
            
            # Convert all bounds to Python integers to ensure JSON serialization
            frame_bounds = {k: int(v) for k, v in frame_bounds.items()}
            
            return {
                'frame_detected': True,
                'frame_bounds': frame_bounds,
                'detection_method': 'edge_patterns'
            }
        
        return {'frame_detected': False}
    
    def _find_edge_boundary(self, profile: np.ndarray, edge_type: str, config: Dict[str, Any]) -> Optional[int]:
        """
        Find frame boundary in an edge profile.
        """
        
        # Look for significant intensity drops (dark lines)
        diff = np.diff(profile)
        
        if edge_type in ['top', 'left']:
            # Look for drops from light to dark
            candidates = np.where(diff < -20)[0]  # Threshold for significant drop
        else:
            # Look for rises from dark to light
            candidates = np.where(diff > 20)[0]
        
        if len(candidates) == 0:
            return None
        
        # Return the first significant boundary
        thickness_range = range(config['min_frame_thickness'], config['max_frame_thickness'])
        
        for candidate in candidates:
            if candidate in thickness_range:
                return candidate
        
        return candidates[0] if len(candidates) > 0 else None
    
    def _remove_frame(self, image: np.ndarray, frame_info: Dict[str, Any], config: Dict[str, Any]) -> np.ndarray:
        """
        Remove frame by cropping the image.
        """
        
        bounds = frame_info['frame_bounds']
        
        # Crop image to remove frame
        cropped = image[
            bounds['top']:bounds['bottom'],
            bounds['left']:bounds['right']
        ]
        
        return cropped
