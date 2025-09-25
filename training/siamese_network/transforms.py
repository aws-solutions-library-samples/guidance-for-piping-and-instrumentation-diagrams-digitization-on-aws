"""
Albumentations transforms for SVG triplet dataset.
Contains various data augmentation transforms optimized for PID symbols.
"""

import albumentations as A
from albumentations.pytorch import ToTensorV2
import numpy as np
import cv2
import random

class RandomLinesTransform(A.ImageOnlyTransform):
    """
    Custom Albumentations transform that draws random black lines across the image.
    """
    
    def __init__(self, 
                 num_lines_range=(1, 5), 
                 thickness_range=(1, 3), 
                 p=1.0):
        """
        Initialize the random lines transform.
        
        Args:
            num_lines_range (tuple): Range for number of lines to draw (min, max)
            thickness_range (tuple): Range for line thickness (min, max)
            p (float): Probability of applying the transform
        """
        super(RandomLinesTransform, self).__init__(p)
        self.num_lines_range = num_lines_range
        self.thickness_range = thickness_range
    
    def apply(self, img, **params):
        """
        Apply the transform to the image.
        
        Args:
            img: Input image as numpy array
            
        Returns:
            Image with random black lines drawn on it
        """
        # Make a copy to avoid modifying the original
        img_with_lines = img.copy()
        
        # Get image dimensions
        height, width = img.shape[:2]
        
        # Randomly select number of lines
        num_lines = random.randint(self.num_lines_range[0], self.num_lines_range[1])
        
        for _ in range(num_lines):
            # Randomly select line thickness
            thickness = random.randint(self.thickness_range[0], self.thickness_range[1])
            
            # Randomly select line endpoints
            x1 = random.randint(0, width - 1)
            y1 = random.randint(0, height - 1)
            x2 = random.randint(0, width - 1)
            y2 = random.randint(0, height - 1)
            
            # Draw black line
            cv2.line(img_with_lines, (x1, y1), (x2, y2), (0, 0, 0), thickness)
        
        return img_with_lines
    
    def get_transform_init_args_names(self):
        return ("num_lines_range", "thickness_range")
