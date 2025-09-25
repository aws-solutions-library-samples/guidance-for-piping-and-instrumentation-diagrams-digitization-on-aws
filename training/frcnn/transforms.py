"""
Custom PyTorch transforms for object detection tasks.

This module contains transforms that work with both images and their corresponding
target dictionaries (containing bounding boxes, labels, etc.).
"""

import torch
import torchvision.transforms as transforms
import torchvision.transforms.functional as F
from PIL import Image, ImageDraw
from typing import Dict, Tuple, Any, Union, List
import numpy as np
import random
import math
from scipy.ndimage import gaussian_filter


class FlattenLabels:
    """
    Custom PyTorch transform that converts a set of labels to a binary indicator.

    Args:
        None
    """

    def __call__(self, image: Image.Image, targets: Dict[str, Any]) -> Tuple[torch.Tensor, Dict[str, Any]]:
        targets['labels'] = [1 for _ in range(len(targets['labels']))]
        return image, targets


class ToTensorWithTargets:
    """
    Custom PyTorch transform that converts a PIL image to a tensor while keeping
    the targets dictionary unchanged.
    
    This transform is specifically designed for object detection tasks where you
    need to convert the image to a tensor but preserve the target dictionary
    containing bounding boxes, labels, and other metadata.
    
    Args:
        normalize_to_01: Whether to normalize the tensor to [0, 1] range (default: True)
        imagenet_normalize: Whether to apply ImageNet normalization (default: False)
        mean: Mean values for ImageNet normalization (default: ImageNet mean)
        std: Standard deviation values for ImageNet normalization (default: ImageNet std)
        
    Example:
        >>> # Basic tensor conversion with [0, 1] normalization
        >>> transform = ToTensorWithTargets()
        >>> 
        >>> # With ImageNet normalization
        >>> transform = ToTensorWithTargets(imagenet_normalize=True)
        >>> 
        >>> # Custom normalization values
        >>> transform = ToTensorWithTargets(
        ...     imagenet_normalize=True,
        ...     mean=(0.5, 0.5, 0.5),
        ...     std=(0.5, 0.5, 0.5)
        ... )
        >>> 
        >>> image = Image.open("image.jpg")
        >>> targets = {
        ...     'boxes': torch.tensor([[10, 20, 100, 200]]),
        ...     'labels': torch.tensor([1]),
        ...     'image_id': torch.tensor([0])
        ... }
        >>> tensor_image, targets = transform(image, targets)
        >>> print(tensor_image.shape)  # torch.Size([3, H, W])
        >>> print(targets)  # Original targets dict unchanged
    """
    
    def __init__(
        self, 
        normalize_to_01: bool = True,
        imagenet_normalize: bool = False,
        mean: Tuple[float, float, float] = (0.485, 0.456, 0.406),
        std: Tuple[float, float, float] = (0.229, 0.224, 0.225)
    ):
        self.normalize_to_01 = normalize_to_01
        self.imagenet_normalize = imagenet_normalize
        self.mean = mean
        self.std = std
        
        # Build transform pipeline
        if imagenet_normalize:
            self.transform = transforms.Compose([
                transforms.ToTensor(),
                transforms.Normalize(mean=mean, std=std)
            ])
        elif normalize_to_01:
            self.transform = transforms.ToTensor()
        else:
            # No normalization - keep [0, 255] range
            self.transform = None
    
    def __call__(self, image: Image.Image, targets: Dict[str, Any]) -> Tuple[torch.Tensor, Dict[str, Any]]:
        """
        Convert PIL image to tensor and return with unchanged targets.
        
        Args:
            image: PIL Image to convert
            targets: Dictionary containing target information (boxes, labels, etc.)
            
        Returns:
            Tuple of (tensor_image, targets) where tensor_image is the converted
            image and targets is the unchanged input dictionary
        """
        if not isinstance(image, Image.Image):
            raise TypeError(f"Expected PIL Image, got {type(image)}")
        
        if not isinstance(targets, dict):
            raise TypeError(f"Expected dict for targets, got {type(targets)}")
        
        # Convert PIL image to tensor
        if self.transform is not None:
            tensor_image = self.transform(image)
        else:
            # Convert to tensor without normalization (keeps [0, 255] range)
            tensor_image = torch.from_numpy(np.array(image)).permute(2, 0, 1).float()
        
        return tensor_image, targets
    
    def __repr__(self):
        return (f"{self.__class__.__name__}("
                f"normalize_to_01={self.normalize_to_01}, "
                f"imagenet_normalize={self.imagenet_normalize}, "
                f"mean={self.mean}, std={self.std})")


class ComposeWithTargets:
    """
    Compose multiple transforms that work with (image, targets) pairs.
    
    Similar to torchvision.transforms.Compose but designed for transforms
    that take both image and targets as input.
    
    Args:
        transforms: List of transforms to compose
        
    Example:
        >>> transform = ComposeWithTargets([
        ...     SomeCustomTransform(),
        ...     ToTensorWithTargets(),
        ...     AnotherCustomTransform()
        ... ])
        >>> result_image, result_targets = transform(image, targets)
    """
    
    def __init__(self, transforms):
        self.transforms = transforms
    
    def __call__(self, image: Image.Image, targets: Dict[str, Any]) -> Tuple[torch.Tensor, Dict[str, Any]]:
        """
        Apply all transforms in sequence.
        
        Args:
            image: Input PIL image
            targets: Input targets dictionary
            
        Returns:
            Tuple of (transformed_image, transformed_targets)
        """
        for transform in self.transforms:
            image, targets = transform(image, targets)
        return image, targets
    
    def __repr__(self):
        format_string = self.__class__.__name__ + '('
        for t in self.transforms:
            format_string += '\n'
            format_string += '    {0}'.format(t)
        format_string += '\n)'
        return format_string


class ImageOnlyTransform:
    """
    Wrapper to apply standard torchvision transforms to only the image,
    leaving targets unchanged.
    
    This allows you to use any standard torchvision transform in a pipeline
    that works with (image, targets) pairs.
    
    Args:
        transform: Any torchvision transform that works on images
        
    Example:
        >>> # Use standard torchvision transforms in object detection pipeline
        >>> transform = ComposeWithTargets([
        ...     ImageOnlyTransform(transforms.ColorJitter(brightness=0.2)),
        ...     ImageOnlyTransform(transforms.GaussianBlur(kernel_size=3)),
        ...     ToTensorWithTargets()
        ... ])
    """
    
    def __init__(self, transform):
        self.transform = transform
    
    def __call__(self, image: Image.Image, targets: Dict[str, Any]) -> Tuple[Union[Image.Image, torch.Tensor], Dict[str, Any]]:
        """
        Apply transform to image only, return with unchanged targets.
        
        Args:
            image: Input image
            targets: Input targets dictionary
            
        Returns:
            Tuple of (transformed_image, unchanged_targets)
        """
        transformed_image = self.transform(image)
        return transformed_image, targets
    
    def __repr__(self):
        return f"{self.__class__.__name__}({self.transform})"


# Convenience functions for creating common transform pipelines

def create_training_transforms(
    normalize: bool = True,
    mean: Tuple[float, float, float] = (0.485, 0.456, 0.406),
    std: Tuple[float, float, float] = (0.229, 0.224, 0.225)
) -> ComposeWithTargets:
    """
    Create a standard training transform pipeline for object detection.
    
    Args:
        normalize: Whether to apply ImageNet normalization
        mean: Mean values for normalization
        std: Standard deviation values for normalization
        
    Returns:
        ComposeWithTargets transform pipeline
    """
    if normalize:
        return ComposeWithTargets([
            ToTensorWithTargets(imagenet_normalize=True, mean=mean, std=std)
        ])
    else:
        return ComposeWithTargets([
            ToTensorWithTargets(normalize_to_01=True)
        ])


def create_validation_transforms(
    normalize: bool = True,
    mean: Tuple[float, float, float] = (0.485, 0.456, 0.406),
    std: Tuple[float, float, float] = (0.229, 0.224, 0.225)
) -> ComposeWithTargets:
    """
    Create a standard validation transform pipeline for object detection.
    
    Args:
        normalize: Whether to apply ImageNet normalization
        mean: Mean values for normalization
        std: Standard deviation values for normalization
        
    Returns:
        ComposeWithTargets transform pipeline
    """
    # For validation, typically just convert to tensor and normalize
    return create_training_transforms(normalize=normalize, mean=mean, std=std)


def create_augmented_training_transforms(
    brightness: float = 0.2,
    contrast: float = 0.2,
    saturation: float = 0.2,
    hue: float = 0.1,
    rotation_degrees: List[float] = None,
    rotation_probabilities: List[float] = None,
    normalize: bool = True,
    mean: Tuple[float, float, float] = (0.485, 0.456, 0.406),
    std: Tuple[float, float, float] = (0.229, 0.224, 0.225)
) -> ComposeWithTargets:
    """
    Create an augmented training transform pipeline for object detection.
    
    This includes color jittering, optional rotation, and other augmentations.
    
    Args:
        brightness: Brightness jitter factor
        contrast: Contrast jitter factor
        saturation: Saturation jitter factor
        hue: Hue jitter factor
        rotation_degrees: List of rotation angles in degrees. If None, no rotation is applied.
        rotation_probabilities: List of probabilities for each rotation angle. 
                              Must have same length as rotation_degrees.
        normalize: Whether to apply ImageNet normalization
        mean: Mean values for normalization
        std: Standard deviation values for normalization
        
    Returns:
        ComposeWithTargets transform pipeline
    """
    transform_list = [
        ImageOnlyTransform(transforms.ColorJitter(
            brightness=brightness,
            contrast=contrast,
            saturation=saturation,
            hue=hue
        ))
    ]
    
    # Add rotation if specified
    if rotation_degrees is not None and rotation_probabilities is not None:
        transform_list.append(RandomRotationWithProbability(
            degrees=rotation_degrees,
            probabilities=rotation_probabilities
        ))
    
    if normalize:
        transform_list.append(ToTensorWithTargets(imagenet_normalize=True, mean=mean, std=std))
    else:
        transform_list.append(ToTensorWithTargets(normalize_to_01=True))
    
    return ComposeWithTargets(transform_list)


class RandomCropWithBBoxes:
    """
    Random crop transform that adjusts bounding boxes and labels accordingly.
    
    This transform takes an image, bounding boxes, and labels, performs a random crop,
    and adjusts the bounding boxes to the new coordinate system. Boxes that are
    completely outside the crop are removed, while boxes that are partially inside
    are kept and clipped to the crop boundaries.
    
    Args:
        size (int or tuple): Desired output size of the crop. If int, a square crop is made.
        padding (int or tuple, optional): Optional padding on each border of the image.
        pad_if_needed (bool): Pad the image if it's smaller than the desired size.
        fill (int or tuple): Pixel fill value for constant fill.
        padding_mode (str): Type of padding. Should be: constant, edge, reflect or symmetric.
    """
    
    def __init__(
        self,
        size: Union[int, Tuple[int, int]],
        padding: Union[int, Tuple[int, int, int, int]] = None,
        pad_if_needed: bool = False,
        fill: Union[int, Tuple[int, ...]] = 0,
        padding_mode: str = "constant"
    ):
        if isinstance(size, int):
            self.size = (size, size)
        else:
            self.size = size
            
        self.padding = padding
        self.pad_if_needed = pad_if_needed
        self.fill = fill
        self.padding_mode = padding_mode
    
    def __call__(self, image, targets):
        """
        Apply random crop to image and adjust bounding boxes and labels.
        
        Args:
            image (PIL Image or Tensor): Image to be cropped.
            targets (dict): A dictionary of bounding box targets
            
        Returns:
            tuple: (cropped_image, adjusted_targets)
        """
        #dict_keys(['boxes', 'labels', 'node_ids', 'image_id', 'area', 'iscrowd'])
        boxes = targets['boxes']
        labels = targets['labels']

        # Track padding offsets for bounding box adjustment
        pad_left = 0
        pad_top = 0

        if self.padding is not None:
            image = F.pad(image, self.padding, self.fill, self.padding_mode)
            # Update padding offsets based on padding format
            if isinstance(self.padding, int):
                pad_left = pad_top = self.padding
            elif len(self.padding) == 2:
                pad_left, pad_top = self.padding
            elif len(self.padding) == 4:
                pad_left, pad_top = self.padding[0], self.padding[1]
            
        # Pad the image if needed
        if self.pad_if_needed:
            img_width, img_height = F.get_image_size(image)
            if img_width < self.size[1]:
                padding_width = self.size[1] - img_width
                padding = [padding_width, 0]
                image = F.pad(image, padding, self.fill, self.padding_mode)
                pad_left += padding_width
            if img_height < self.size[0]:
                padding_height = self.size[0] - img_height
                padding = [0, padding_height]
                image = F.pad(image, padding, self.fill, self.padding_mode)
                pad_top += padding_height
        
        # Adjust bounding boxes for padding offset
        adjusted_boxes = boxes.clone()
        if pad_left > 0 or pad_top > 0:
            adjusted_boxes[:, 0] += pad_left  # x1
            adjusted_boxes[:, 1] += pad_top   # y1
            adjusted_boxes[:, 2] += pad_left  # x2
            adjusted_boxes[:, 3] += pad_top   # y2
        
        # Get image dimensions after padding
        img_width, img_height = F.get_image_size(image)
        
        # Get random crop parameters
        crop_height, crop_width = self.size
        
        if img_height < crop_height or img_width < crop_width:
            raise ValueError(f"Image size ({img_width}, {img_height}) is smaller than crop size {self.size}")
        
        # Random crop coordinates
        top = random.randint(0, img_height - crop_height)
        left = random.randint(0, img_width - crop_width)
        
        # Crop the image
        cropped_image = F.crop(image, top, left, crop_height, crop_width)
        
        # Adjust bounding boxes for cropping
        crop_box = torch.tensor([left, top, left + crop_width, top + crop_height], dtype=adjusted_boxes.dtype)
        final_boxes, valid_indices = self._adjust_boxes(adjusted_boxes, crop_box)
        
        # Filter labels and other target fields based on valid boxes
        filtered_labels = labels[valid_indices]
        
        # Create new targets dictionary with all relevant fields
        new_targets = {'boxes': final_boxes, 'labels': filtered_labels}
        
        # Copy over other target fields if they exist, filtering by valid_indices
        for key in targets:
            if key not in ['boxes', 'labels']:
                if key in ['node_ids', 'symbol_ids'] and isinstance(targets[key], list):
                    # Handle list-type node_ids
                    new_targets[key] = [targets[key][i] for i in range(len(targets[key])) if valid_indices[i]]
                elif hasattr(targets[key], '__getitem__') and len(targets[key]) == len(labels):
                    # Handle tensor-type fields that need filtering
                    new_targets[key] = targets[key][valid_indices]
                else:
                    # Handle scalar fields (like image_id)
                    new_targets[key] = targets[key]
        
        return cropped_image, new_targets

    
    def _adjust_boxes(self, boxes: torch.Tensor, crop_box: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Adjust bounding boxes to the cropped coordinate system.
        
        Args:
            boxes (Tensor): Original bounding boxes [x1, y1, x2, y2] with shape (N, 4).
            crop_box (Tensor): Crop region [x1, y1, x2, y2].
            
        Returns:
            tuple: (adjusted_boxes, valid_indices)
                - adjusted_boxes: Boxes adjusted to crop coordinates
                - valid_indices: Boolean mask indicating which boxes are valid
        """
        if len(boxes) == 0:
            return boxes, torch.tensor([], dtype=torch.bool)
        
        crop_x1, crop_y1, crop_x2, crop_y2 = crop_box
        
        # Clip boxes to crop region
        clipped_boxes = boxes.clone()
        clipped_boxes[:, 0] = torch.clamp(boxes[:, 0], crop_x1, crop_x2)  # x1
        clipped_boxes[:, 1] = torch.clamp(boxes[:, 1], crop_y1, crop_y2)  # y1
        clipped_boxes[:, 2] = torch.clamp(boxes[:, 2], crop_x1, crop_x2)  # x2
        clipped_boxes[:, 3] = torch.clamp(boxes[:, 3], crop_y1, crop_y2)  # y2
        
        # Check which boxes have valid area after clipping
        valid_width = clipped_boxes[:, 2] > clipped_boxes[:, 0]
        valid_height = clipped_boxes[:, 3] > clipped_boxes[:, 1]
        valid_indices = valid_width & valid_height
        
        # Adjust coordinates to crop coordinate system
        adjusted_boxes = clipped_boxes[valid_indices].clone()
        if len(adjusted_boxes) > 0:
            adjusted_boxes[:, 0] -= crop_x1  # x1
            adjusted_boxes[:, 1] -= crop_y1  # y1
            adjusted_boxes[:, 2] -= crop_x1  # x2
            adjusted_boxes[:, 3] -= crop_y1  # y2
        
        return adjusted_boxes, valid_indices
    
    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}(size={self.size}, "
                f"padding={self.padding}, pad_if_needed={self.pad_if_needed}, "
                f"fill={self.fill}, padding_mode={self.padding_mode})")


class XYXYToYXYX:
    """
    Convert bounding boxes from xyxy format to yxyx format.
    
    This transform takes bounding boxes in xyxy format [x1, y1, x2, y2] 
    (left, top, right, bottom) and converts them to yxyx format [y1, x1, y2, x2]
    (top, left, bottom, right).
    
    The image is passed through unchanged, and only the 'boxes' key in the
    targets dictionary is modified.
    
    Args:
        None
        
    Example:
        >>> transform = XYXYToYXYX()
        >>> image = Image.open("image.jpg")
        >>> targets = {
        ...     'boxes': torch.tensor([[10, 20, 100, 200]]),  # [x1, y1, x2, y2]
        ...     'labels': torch.tensor([1])
        ... }
        >>> image, targets = transform(image, targets)
        >>> print(targets['boxes'])  # tensor([[20, 10, 200, 100]]) -> [y1, x1, y2, x2]
    """
    
    def __call__(self, image: Union[Image.Image, torch.Tensor], targets: Dict[str, Any]) -> Tuple[Union[Image.Image, torch.Tensor], Dict[str, Any]]:
        """
        Convert bounding boxes from xyxy to yxyx format.
        
        Args:
            image: Input image (PIL Image or tensor) - passed through unchanged
            targets: Dictionary containing target information including 'boxes' key
            
        Returns:
            Tuple of (image, targets) where image is unchanged and targets
            contains boxes converted to yxyx format
        """
        if not isinstance(targets, dict):
            raise TypeError(f"Expected dict for targets, got {type(targets)}")
        
        if 'boxes' not in targets:
            raise KeyError("'boxes' key not found in targets dictionary")
        
        boxes = targets['boxes']
        
        if not isinstance(boxes, torch.Tensor):
            raise TypeError(f"Expected torch.Tensor for boxes, got {type(boxes)}")
        
        if len(boxes.shape) != 2 or boxes.shape[1] != 4:
            raise ValueError(f"Expected boxes to have shape (N, 4), got {boxes.shape}")
        
        # Convert from xyxy [x1, y1, x2, y2] to yxyx [y1, x1, y2, x2]
        converted_boxes = boxes.clone()
        converted_boxes[:, 0] = boxes[:, 1]  # y1 = original y1
        converted_boxes[:, 1] = boxes[:, 0]  # x1 = original x1
        converted_boxes[:, 2] = boxes[:, 3]  # y2 = original y2
        converted_boxes[:, 3] = boxes[:, 2]  # x2 = original x2
        
        # Create new targets dictionary with converted boxes
        new_targets = targets.copy()
        new_targets['boxes'] = converted_boxes
        
        return image, new_targets
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"


class RandomRotationWithProbability:
    """
    Random rotation transform that rotates images and adjusts bounding boxes accordingly.
    
    This transform takes a list of rotation degrees and their corresponding probabilities,
    randomly selects a rotation angle based on the probability distribution, rotates the
    image, and transforms the bounding boxes to match the new coordinate system.
    
    Args:
        degrees (List[float]): List of rotation angles in degrees (e.g., [0, 90, 180, 270])
        probabilities (List[float]): List of probabilities for each rotation angle.
                                   Must have the same length as degrees and sum to 1.0.
        min_box_area (float): Minimum area threshold for keeping bounding boxes after rotation.
                             Boxes with area smaller than this will be filtered out. Default: 100.0
        fill (Union[int, Tuple[int, ...]]): Pixel fill value for areas outside the rotated image.
                                          Default: 0 (black)
        
    Example:
        >>> # Equal probability for no rotation and 90-degree rotations
        >>> transform = RandomRotationWithProbability(
        ...     degrees=[0, 90, 180, 270],
        ...     probabilities=[0.4, 0.2, 0.2, 0.2]
        ... )
        >>> 
        >>> # Higher probability for no rotation
        >>> transform = RandomRotationWithProbability(
        ...     degrees=[0, 90, 180, 270],
        ...     probabilities=[0.7, 0.1, 0.1, 0.1]
        ... )
        >>> 
        >>> image = Image.open("image.jpg")
        >>> targets = {
        ...     'boxes': torch.tensor([[10, 20, 100, 200]]),
        ...     'labels': torch.tensor([1])
        ... }
        >>> rotated_image, rotated_targets = transform(image, targets)
    """
    
    def __init__(
        self,
        degrees: List[float],
        probabilities: List[float],
        min_box_area: float = 100.0,
        fill: Union[int, Tuple[int, ...]] = 0
    ):
        if len(degrees) != len(probabilities):
            raise ValueError(f"Length of degrees ({len(degrees)}) must match length of probabilities ({len(probabilities)})")
        
        if len(degrees) == 0:
            raise ValueError("At least one rotation degree must be provided")
        
        # Normalize probabilities to ensure they sum to 1.0
        prob_sum = sum(probabilities)
        if abs(prob_sum - 1.0) > 1e-6:
            print(f"Warning: Probabilities sum to {prob_sum:.6f}, normalizing to 1.0")
            probabilities = [p / prob_sum for p in probabilities]
        
        self.degrees = degrees
        self.probabilities = probabilities
        self.min_box_area = min_box_area
        self.fill = fill
        
        # Create numpy array for efficient sampling
        self.degrees_array = np.array(degrees)
        self.probabilities_array = np.array(probabilities)
    
    def __call__(self, image: Union[Image.Image, torch.Tensor], targets: Dict[str, Any]) -> Tuple[Union[Image.Image, torch.Tensor], Dict[str, Any]]:
        """
        Apply random rotation to image and adjust bounding boxes.
        
        Args:
            image: Input image (PIL Image or tensor)
            targets: Dictionary containing target information including 'boxes' key
            
        Returns:
            Tuple of (rotated_image, rotated_targets) where rotated_targets
            contains boxes adjusted to the rotated coordinate system
        """
        if not isinstance(targets, dict):
            raise TypeError(f"Expected dict for targets, got {type(targets)}")
        
        if 'boxes' not in targets:
            raise KeyError("'boxes' key not found in targets dictionary")
        
        boxes = targets['boxes']
        
        if not isinstance(boxes, torch.Tensor):
            raise TypeError(f"Expected torch.Tensor for boxes, got {type(boxes)}")
        
        # Randomly select rotation angle based on probabilities
        selected_angle = float(np.random.choice(self.degrees_array, p=self.probabilities_array))
        
        # If angle is 0, return unchanged
        if abs(selected_angle) < 1e-6:
            return image, targets
        
        # Get original image dimensions
        if isinstance(image, Image.Image):
            orig_width, orig_height = image.size
        else:
            # Assume tensor format is (C, H, W)
            orig_height, orig_width = image.shape[-2:]
        
        # Rotate the image with expansion to avoid cropping
        rotated_image = F.rotate(image, selected_angle, expand=True, fill=self.fill)
        
        # Get new image dimensions after rotation
        if isinstance(rotated_image, Image.Image):
            new_width, new_height = rotated_image.size
        else:
            new_height, new_width = rotated_image.shape[-2:]
        
        # Transform bounding boxes
        if len(boxes) > 0:
            transformed_boxes = self._rotate_boxes(
                boxes, selected_angle, orig_width, orig_height, new_width, new_height
            )
            
            # Filter out boxes that are too small or invalid
            valid_boxes, valid_indices = self._filter_valid_boxes(transformed_boxes)
        else:
            valid_boxes = boxes
            valid_indices = torch.tensor([], dtype=torch.bool)
        
        # Create new targets dictionary with transformed boxes
        new_targets = targets.copy()
        new_targets['boxes'] = valid_boxes
        
        # Filter other target fields based on valid indices
        if len(valid_indices) > 0 and len(boxes) > 0:
            if 'labels' in targets:
                original_labels = targets['labels']
                if isinstance(original_labels, list):
                    new_targets['labels'] = [original_labels[i] for i in range(len(original_labels)) if valid_indices[i]]
                else:
                    new_targets['labels'] = targets['labels'][valid_indices]
            if 'node_ids' in targets:
                original_node_ids = targets['node_ids']
                if isinstance(original_node_ids, list):
                    new_targets['node_ids'] = [original_node_ids[i] for i in range(len(original_node_ids)) if valid_indices[i]]
                else:
                    new_targets['node_ids'] = original_node_ids[valid_indices]
            if 'area' in targets:
                new_targets['area'] = self._calculate_box_areas(valid_boxes)
            if 'iscrowd' in targets:
                new_targets['iscrowd'] = targets['iscrowd'][valid_indices]
        elif len(boxes) > 0:
            # No valid boxes remain, create empty tensors
            if 'labels' in targets:
                new_targets['labels'] = torch.tensor([], dtype=targets['labels'].dtype)
            if 'node_ids' in targets:
                new_targets['node_ids'] = []
            if 'area' in targets:
                new_targets['area'] = torch.tensor([], dtype=torch.float32)
            if 'iscrowd' in targets:
                new_targets['iscrowd'] = torch.tensor([], dtype=targets['iscrowd'].dtype)
        
        return rotated_image, new_targets
    
    def _rotate_boxes(
        self, 
        boxes: torch.Tensor, 
        angle: float, 
        orig_width: int, 
        orig_height: int,
        new_width: int, 
        new_height: int
    ) -> torch.Tensor:
        """
        Rotate bounding boxes to match the rotated image coordinate system.
        
        Args:
            boxes: Original bounding boxes [x1, y1, x2, y2] with shape (N, 4)
            angle: Rotation angle in degrees
            orig_width: Original image width
            orig_height: Original image height
            new_width: New image width after rotation
            new_height: New image height after rotation
            
        Returns:
            Transformed bounding boxes in the rotated coordinate system
        """
        if len(boxes) == 0:
            return boxes
        
        # Convert angle to radians
        # Note: torchvision.transforms.functional.rotate uses clockwise rotation
        # So we need to negate the angle for our rotation matrix to match
        angle_rad = math.radians(-angle)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)
        
        # Original image center
        orig_cx = orig_width / 2.0
        orig_cy = orig_height / 2.0
        
        # New image center
        new_cx = new_width / 2.0
        new_cy = new_height / 2.0
        
        # Convert boxes to corner points
        # Each box [x1, y1, x2, y2] becomes 4 corner points
        x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
        
        # Four corners of each bounding box
        corners_x = torch.stack([x1, x2, x2, x1], dim=1)  # [N, 4]
        corners_y = torch.stack([y1, y1, y2, y2], dim=1)  # [N, 4]
        
        # Flatten to process all corners at once
        corners_x_flat = corners_x.flatten()  # [N*4]
        corners_y_flat = corners_y.flatten()  # [N*4]
        
        # Translate to origin (center of original image)
        corners_x_centered = corners_x_flat - orig_cx
        corners_y_centered = corners_y_flat - orig_cy
        
        # Apply rotation transformation
        rotated_x = corners_x_centered * cos_a - corners_y_centered * sin_a
        rotated_y = corners_x_centered * sin_a + corners_y_centered * cos_a
        
        # Translate to new image center
        final_x = rotated_x + new_cx
        final_y = rotated_y + new_cy
        
        # Reshape back to [N, 4] for each box's corners
        final_x = final_x.reshape(-1, 4)  # [N, 4]
        final_y = final_y.reshape(-1, 4)  # [N, 4]
        
        # Find axis-aligned bounding box for each set of rotated corners
        min_x = torch.min(final_x, dim=1)[0]  # [N]
        max_x = torch.max(final_x, dim=1)[0]  # [N]
        min_y = torch.min(final_y, dim=1)[0]  # [N]
        max_y = torch.max(final_y, dim=1)[0]  # [N]
        
        # Clamp to image boundaries
        min_x = torch.clamp(min_x, 0, new_width)
        max_x = torch.clamp(max_x, 0, new_width)
        min_y = torch.clamp(min_y, 0, new_height)
        max_y = torch.clamp(max_y, 0, new_height)
        
        # Stack to create new bounding boxes
        transformed_boxes = torch.stack([min_x, min_y, max_x, max_y], dim=1)
        
        return transformed_boxes
    
    def _filter_valid_boxes(self, boxes: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Filter out invalid bounding boxes (too small or malformed).
        
        Args:
            boxes: Bounding boxes to filter [x1, y1, x2, y2] with shape (N, 4)
            
        Returns:
            Tuple of (valid_boxes, valid_indices)
        """
        if len(boxes) == 0:
            return boxes, torch.tensor([], dtype=torch.bool)
        
        # Check for valid box dimensions
        width = boxes[:, 2] - boxes[:, 0]
        height = boxes[:, 3] - boxes[:, 1]
        
        # Valid boxes have positive width and height, and sufficient area
        valid_width = width > 0
        valid_height = height > 0
        valid_area = (width * height) >= self.min_box_area
        
        valid_indices = valid_width & valid_height & valid_area
        valid_boxes = boxes[valid_indices]
        
        return valid_boxes, valid_indices
    
    def _calculate_box_areas(self, boxes: torch.Tensor) -> torch.Tensor:
        """
        Calculate areas of bounding boxes.
        
        Args:
            boxes: Bounding boxes [x1, y1, x2, y2] with shape (N, 4)
            
        Returns:
            Areas of the boxes with shape (N,)
        """
        if len(boxes) == 0:
            return torch.tensor([], dtype=torch.float32)
        
        width = boxes[:, 2] - boxes[:, 0]
        height = boxes[:, 3] - boxes[:, 1]
        return width * height
    
    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}("
                f"degrees={self.degrees}, "
                f"probabilities={self.probabilities}, "
                f"min_box_area={self.min_box_area}, "
                f"fill={self.fill})")


class RandomFlip:
    """
    Random flip transform that flips images horizontally or vertically and adjusts bounding boxes accordingly.
    
    This transform randomly applies horizontal or vertical flips to images and transforms the bounding boxes
    to match the new coordinate system. The flip direction and probability can be controlled.
    
    Args:
        flip_type (str): Type of flip to apply. Options are:
                        - 'horizontal': Only horizontal flips
                        - 'vertical': Only vertical flips  
                        - 'both': Randomly choose between horizontal and vertical flips
        p (float): Probability of applying the flip. Default: 0.5
        horizontal_prob (float): When flip_type='both', probability of horizontal flip vs vertical flip.
                               Default: 0.5 (equal probability)
        
    Example:
        >>> # Horizontal flip with 50% probability
        >>> transform = RandomFlip(flip_type='horizontal', p=0.5)
        >>> 
        >>> # Vertical flip with 30% probability
        >>> transform = RandomFlip(flip_type='vertical', p=0.3)
        >>> 
        >>> # Random horizontal or vertical flip with 70% probability
        >>> transform = RandomFlip(flip_type='both', p=0.7, horizontal_prob=0.6)
        >>> 
        >>> image = Image.open("image.jpg")
        >>> targets = {
        ...     'boxes': torch.tensor([[10, 20, 100, 200]]),
        ...     'labels': torch.tensor([1])
        ... }
        >>> flipped_image, flipped_targets = transform(image, targets)
    """
    
    def __init__(
        self,
        flip_type: str = 'horizontal',
        p: float = 0.5,
        horizontal_prob: float = 0.5
    ):
        if flip_type not in ['horizontal', 'vertical', 'both']:
            raise ValueError(f"flip_type must be 'horizontal', 'vertical', or 'both', got {flip_type}")
        
        if not 0 <= p <= 1:
            raise ValueError(f"Probability p must be between 0 and 1, got {p}")
        
        if not 0 <= horizontal_prob <= 1:
            raise ValueError(f"horizontal_prob must be between 0 and 1, got {horizontal_prob}")
        
        self.flip_type = flip_type
        self.p = p
        self.horizontal_prob = horizontal_prob
    
    def __call__(self, image: Union[Image.Image, torch.Tensor], targets: Dict[str, Any]) -> Tuple[Union[Image.Image, torch.Tensor], Dict[str, Any]]:
        """
        Apply random flip to image and adjust bounding boxes.
        
        Args:
            image: Input image (PIL Image or tensor)
            targets: Dictionary containing target information including 'boxes' key
            
        Returns:
            Tuple of (flipped_image, flipped_targets) where flipped_targets
            contains boxes adjusted to the flipped coordinate system
        """
        if not isinstance(targets, dict):
            raise TypeError(f"Expected dict for targets, got {type(targets)}")
        
        if 'boxes' not in targets:
            raise KeyError("'boxes' key not found in targets dictionary")
        
        boxes = targets['boxes']
        
        if not isinstance(boxes, torch.Tensor):
            raise TypeError(f"Expected torch.Tensor for boxes, got {type(boxes)}")
        
        # Decide whether to apply flip
        if random.random() > self.p:
            return image, targets
        
        # Determine flip direction
        if self.flip_type == 'horizontal':
            do_horizontal = True
        elif self.flip_type == 'vertical':
            do_horizontal = False
        else:  # flip_type == 'both'
            do_horizontal = random.random() < self.horizontal_prob
        
        # Get image dimensions
        if isinstance(image, Image.Image):
            img_width, img_height = image.size
        else:
            # Assume tensor format is (C, H, W)
            img_height, img_width = image.shape[-2:]
        
        # Apply flip to image
        if do_horizontal:
            flipped_image = F.hflip(image)
        else:
            flipped_image = F.vflip(image)
        
        # Transform bounding boxes
        if len(boxes) > 0:
            if do_horizontal:
                transformed_boxes = self._flip_boxes_horizontal(boxes, img_width)
            else:
                transformed_boxes = self._flip_boxes_vertical(boxes, img_height)
        else:
            transformed_boxes = boxes
        
        # Create new targets dictionary with transformed boxes
        new_targets = targets.copy()
        new_targets['boxes'] = transformed_boxes
        
        return flipped_image, new_targets
    
    def _flip_boxes_horizontal(self, boxes: torch.Tensor, img_width: int) -> torch.Tensor:
        """
        Flip bounding boxes horizontally.
        
        For horizontal flip, x-coordinates are transformed as: new_x = img_width - old_x
        The y-coordinates remain unchanged.
        
        Args:
            boxes: Original bounding boxes [x1, y1, x2, y2] with shape (N, 4)
            img_width: Width of the image
            
        Returns:
            Horizontally flipped bounding boxes
        """
        if len(boxes) == 0:
            return boxes
        
        flipped_boxes = boxes.clone()
        
        # For horizontal flip: new_x = img_width - old_x
        # We need to flip both x1 and x2, and ensure x1 < x2
        old_x1 = boxes[:, 0]
        old_x2 = boxes[:, 2]
        
        new_x1 = img_width - old_x2
        new_x2 = img_width - old_x1
        
        flipped_boxes[:, 0] = new_x1  # x1
        flipped_boxes[:, 2] = new_x2  # x2
        # y1 and y2 remain unchanged
        
        return flipped_boxes
    
    def _flip_boxes_vertical(self, boxes: torch.Tensor, img_height: int) -> torch.Tensor:
        """
        Flip bounding boxes vertically.
        
        For vertical flip, y-coordinates are transformed as: new_y = img_height - old_y
        The x-coordinates remain unchanged.
        
        Args:
            boxes: Original bounding boxes [x1, y1, x2, y2] with shape (N, 4)
            img_height: Height of the image
            
        Returns:
            Vertically flipped bounding boxes
        """
        if len(boxes) == 0:
            return boxes
        
        flipped_boxes = boxes.clone()
        
        # For vertical flip: new_y = img_height - old_y
        # We need to flip both y1 and y2, and ensure y1 < y2
        old_y1 = boxes[:, 1]
        old_y2 = boxes[:, 3]
        
        new_y1 = img_height - old_y2
        new_y2 = img_height - old_y1
        
        flipped_boxes[:, 1] = new_y1  # y1
        flipped_boxes[:, 3] = new_y2  # y2
        # x1 and x2 remain unchanged
        
        return flipped_boxes
    
    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}("
                f"flip_type='{self.flip_type}', "
                f"p={self.p}, "
                f"horizontal_prob={self.horizontal_prob})")


class RandomLineNoise:
    """
    Random line noise transform that adds randomly placed black straight lines to images.
    
    This transform adds random black straight lines to images as a form of noise augmentation.
    The lines are drawn with configurable length, thickness, and density. The transform works
    with both PIL Images and tensors, and preserves the targets dictionary unchanged.
    
    Args:
        length_range (Tuple[int, int]): Range of line lengths in pixels (min_length, max_length).
                                       Default: (10, 100)
        thickness_range (Tuple[int, int]): Range of line thickness in pixels (min_thickness, max_thickness).
                                          Default: (1, 5)
        density (float): Density of lines to add. This represents the probability that each
                        potential line position will have a line drawn. Higher values = more lines.
                        Default: 0.01 (1% of potential positions get lines)
        p (float): Probability of applying the transform. Default: 0.5
        line_color (Union[int, Tuple[int, ...]]): Color of the lines. For grayscale images,
                                                 use int (0 for black). For RGB images, use
                                                 tuple (0, 0, 0) for black. Default: 0 (black)
        
    Example:
        >>> # Basic usage with default parameters
        >>> transform = RandomLineNoise()
        >>> 
        >>> # Custom line parameters
        >>> transform = RandomLineNoise(
        ...     length_range=(20, 150),
        ...     thickness_range=(2, 8),
        ...     density=0.02,
        ...     p=0.7
        ... )
        >>> 
        >>> # For RGB images with black lines
        >>> transform = RandomLineNoise(
        ...     length_range=(15, 80),
        ...     thickness_range=(1, 3),
        ...     density=0.015,
        ...     line_color=(0, 0, 0)
        ... )
        >>> 
        >>> image = Image.open("image.jpg")
        >>> targets = {
        ...     'boxes': torch.tensor([[10, 20, 100, 200]]),
        ...     'labels': torch.tensor([1])
        ... }
        >>> noisy_image, targets = transform(image, targets)
    """
    
    def __init__(
        self,
        length_range: Tuple[int, int] = (10, 100),
        thickness_range: Tuple[int, int] = (1, 5),
        density: float = 0.01,
        p: float = 0.5,
        line_color: Union[int, Tuple[int, ...]] = 0
    ):
        if not (0 < length_range[0] <= length_range[1]):
            raise ValueError(f"Invalid length_range: {length_range}. Must have 0 < min <= max")
        
        if not (0 < thickness_range[0] <= thickness_range[1]):
            raise ValueError(f"Invalid thickness_range: {thickness_range}. Must have 0 < min <= max")
        
        if not (0 <= density <= 1):
            raise ValueError(f"Density must be between 0 and 1, got {density}")
        
        if not (0 <= p <= 1):
            raise ValueError(f"Probability p must be between 0 and 1, got {p}")
        
        self.length_range = length_range
        self.thickness_range = thickness_range
        self.density = density
        self.p = p
        self.line_color = line_color
    
    def __call__(self, image: Union[Image.Image, torch.Tensor], targets: Dict[str, Any]) -> Tuple[Union[Image.Image, torch.Tensor], Dict[str, Any]]:
        """
        Apply random line noise to image while keeping targets unchanged.
        
        Args:
            image: Input image (PIL Image or tensor)
            targets: Dictionary containing target information (passed through unchanged)
            
        Returns:
            Tuple of (noisy_image, targets) where noisy_image has random lines added
            and targets is the unchanged input dictionary
        """
        if not isinstance(targets, dict):
            raise TypeError(f"Expected dict for targets, got {type(targets)}")
        
        # Decide whether to apply the transform
        if random.random() > self.p:
            return image, targets
        
        # Handle different image types
        if isinstance(image, torch.Tensor):
            # Convert tensor to PIL for drawing, then back to tensor
            was_tensor = True
            original_dtype = image.dtype
            
            # Convert tensor to PIL Image
            if image.dim() == 3:  # (C, H, W)
                # Ensure values are in [0, 255] range for PIL
                if image.max() <= 1.0:
                    # Assume normalized [0, 1] range
                    pil_image = F.to_pil_image((image * 255).byte())
                else:
                    # Assume [0, 255] range
                    pil_image = F.to_pil_image(image.byte())
            else:
                raise ValueError(f"Expected 3D tensor (C, H, W), got shape {image.shape}")
        else:
            was_tensor = False
            pil_image = image.copy()  # Work on a copy to avoid modifying original
        
        # Add line noise to PIL image
        noisy_pil_image = self._add_line_noise(pil_image)
        
        # Convert back to tensor if input was tensor
        if was_tensor:
            # Convert back to tensor with original properties
            noisy_image = F.to_tensor(noisy_pil_image)
            if original_dtype != torch.float32:
                noisy_image = noisy_image.to(original_dtype)
            # If original was normalized [0, 1], keep it that way
            if image.max() <= 1.0:
                noisy_image = noisy_image  # to_tensor already normalizes to [0, 1]
            else:
                # Scale back to [0, 255] range
                noisy_image = noisy_image * 255
        else:
            noisy_image = noisy_pil_image
        
        return noisy_image, targets
    
    def _add_line_noise(self, image: Image.Image) -> Image.Image:
        """
        Add random line noise to a PIL Image.
        
        Args:
            image: PIL Image to add noise to
            
        Returns:
            PIL Image with random lines added
        """
        # Create a copy to draw on
        noisy_image = image.copy()
        draw = ImageDraw.Draw(noisy_image)
        
        img_width, img_height = image.size
        
        # Calculate approximate number of lines based on density
        # Use image area and density to determine how many lines to potentially draw
        total_pixels = img_width * img_height
        potential_lines = int(total_pixels * self.density)
        
        # Generate random lines
        for _ in range(potential_lines):
            # Random line parameters
            length = random.randint(self.length_range[0], self.length_range[1])
            thickness = random.randint(self.thickness_range[0], self.thickness_range[1])
            
            # Random starting point
            start_x = random.randint(0, img_width - 1)
            start_y = random.randint(0, img_height - 1)
            
            # Random angle for line direction (0 to 2π)
            angle = random.uniform(0, 2 * math.pi)
            
            # Calculate end point based on angle and length
            end_x = start_x + int(length * math.cos(angle))
            end_y = start_y + int(length * math.sin(angle))
            
            # Clamp end point to image boundaries
            end_x = max(0, min(img_width - 1, end_x))
            end_y = max(0, min(img_height - 1, end_y))
            
            # Draw the line
            draw.line(
                [(start_x, start_y), (end_x, end_y)],
                fill=self.line_color,
                width=thickness
            )
        
        return noisy_image
    
    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}("
                f"length_range={self.length_range}, "
                f"thickness_range={self.thickness_range}, "
                f"density={self.density}, "
                f"p={self.p}, "
                f"line_color={self.line_color})")


class RandomGaussianBlobs:
    """
    Random Gaussian blobs transform that adds random blobs of Gaussian distortion to images.
    
    This transform creates random circular regions with Gaussian blur distortion
    to simulate various image artifacts, degradation effects, or local distortions.
    The blobs are applied as localized Gaussian blur with smooth falloff at the edges.
    
    Args:
        blob_count_range (Tuple[int, int]): Range of number of blobs to add (min_count, max_count).
                                           Default: (1, 5)
        size_range (Tuple[int, int]): Range of blob sizes in pixels (min_radius, max_radius).
                                     Default: (10, 50)
        intensity_range (Tuple[float, float]): Range of distortion intensity (min_sigma, max_sigma).
                                              Higher values create more blur. Default: (0.5, 2.0)
        p (float): Probability of applying the transform. Default: 0.5
        
    Example:
        >>> # Basic usage with default parameters
        >>> transform = RandomGaussianBlobs()
        >>> 
        >>> # Custom blob parameters for stronger distortion
        >>> transform = RandomGaussianBlobs(
        ...     blob_count_range=(2, 8),
        ...     size_range=(20, 80),
        ...     intensity_range=(1.0, 3.0),
        ...     p=0.7
        ... )
        >>> 
        >>> # Subtle distortion with small blobs
        >>> transform = RandomGaussianBlobs(
        ...     blob_count_range=(1, 3),
        ...     size_range=(5, 25),
        ...     intensity_range=(0.3, 1.0),
        ...     p=0.3
        ... )
        >>> 
        >>> image = Image.open("image.jpg")
        >>> targets = {
        ...     'boxes': torch.tensor([[10, 20, 100, 200]]),
        ...     'labels': torch.tensor([1])
        ... }
        >>> distorted_image, targets = transform(image, targets)
    """
    
    def __init__(
        self,
        blob_count_range: Tuple[int, int] = (1, 5),
        size_range: Tuple[int, int] = (10, 50),
        intensity_range: Tuple[float, float] = (0.5, 2.0),
        p: float = 0.5
    ):
        if not (0 < blob_count_range[0] <= blob_count_range[1]):
            raise ValueError(f"Invalid blob_count_range: {blob_count_range}. Must have 0 < min <= max")
        
        if not (0 < size_range[0] <= size_range[1]):
            raise ValueError(f"Invalid size_range: {size_range}. Must have 0 < min <= max")
        
        if not (0 < intensity_range[0] <= intensity_range[1]):
            raise ValueError(f"Invalid intensity_range: {intensity_range}. Must have 0 < min <= max")
        
        if not (0 <= p <= 1):
            raise ValueError(f"Probability p must be between 0 and 1, got {p}")
        
        self.blob_count_range = blob_count_range
        self.size_range = size_range
        self.intensity_range = intensity_range
        self.p = p
    
    def __call__(self, image: Union[Image.Image, torch.Tensor], targets: Dict[str, Any]) -> Tuple[Union[Image.Image, torch.Tensor], Dict[str, Any]]:
        """
        Apply random Gaussian blob distortion to image while keeping targets unchanged.
        
        Args:
            image: Input image (PIL Image or tensor)
            targets: Dictionary containing target information (passed through unchanged)
            
        Returns:
            Tuple of (distorted_image, targets) where distorted_image has random
            Gaussian blobs applied and targets is the unchanged input dictionary
        """
        if not isinstance(targets, dict):
            raise TypeError(f"Expected dict for targets, got {type(targets)}")
        
        # Decide whether to apply the transform
        if random.random() > self.p:
            return image, targets
        
        # Handle different image types
        if isinstance(image, torch.Tensor):
            # Convert tensor to numpy for processing, then back to tensor
            was_tensor = True
            original_dtype = image.dtype
            
            # Convert tensor to numpy array
            if image.dim() == 3:  # (C, H, W)
                # Convert to (H, W, C) format for processing
                img_array = image.permute(1, 2, 0).numpy()
                if image.max() <= 1.0:
                    # Assume normalized [0, 1] range, scale to [0, 255]
                    img_array = (img_array * 255).astype(np.uint8)
                else:
                    # Assume [0, 255] range
                    img_array = img_array.astype(np.uint8)
            else:
                raise ValueError(f"Expected 3D tensor (C, H, W), got shape {image.shape}")
        else:
            was_tensor = False
            img_array = np.array(image)
        
        # Apply Gaussian blob distortion
        distorted_array = self._add_gaussian_blobs(img_array)
        
        # Convert back to original format
        if was_tensor:
            # Convert back to tensor with original properties
            if len(distorted_array.shape) == 3:
                # Convert from (H, W, C) back to (C, H, W)
                distorted_image = torch.from_numpy(distorted_array).permute(2, 0, 1).float()
            else:
                # Grayscale case
                distorted_image = torch.from_numpy(distorted_array).unsqueeze(0).float()
            
            # Restore original data type and range
            if original_dtype != torch.float32:
                distorted_image = distorted_image.to(original_dtype)
            
            # If original was normalized [0, 1], normalize back
            if image.max() <= 1.0:
                distorted_image = distorted_image / 255.0
        else:
            distorted_image = Image.fromarray(distorted_array)
        
        return distorted_image, targets
    
    def _add_gaussian_blobs(self, img_array: np.ndarray) -> np.ndarray:
        """
        Add random Gaussian blob distortions to a numpy image array.
        
        Args:
            img_array: Numpy array representing the image (H, W) or (H, W, C)
            
        Returns:
            Numpy array with Gaussian blobs applied
        """
        # Ensure we have the right shape and work with float for processing
        if len(img_array.shape) == 2:
            # Grayscale image
            height, width = img_array.shape
            channels = 1
            working_array = img_array.astype(np.float32)
        else:
            # Color image
            height, width, channels = img_array.shape
            working_array = img_array.astype(np.float32)
        
        # Generate random number of blobs
        num_blobs = random.randint(*self.blob_count_range)
        
        for _ in range(num_blobs):
            # Random blob parameters
            center_x = random.randint(0, width - 1)
            center_y = random.randint(0, height - 1)
            radius = random.randint(*self.size_range)
            intensity = random.uniform(*self.intensity_range)
            
            # Create a region around the blob for processing
            # Expand the region to ensure smooth blending
            padding = max(10, int(radius * 0.5))
            y_min = max(0, center_y - radius - padding)
            y_max = min(height, center_y + radius + padding)
            x_min = max(0, center_x - radius - padding)
            x_max = min(width, center_x + radius + padding)
            
            if y_max <= y_min or x_max <= x_min:
                continue  # Skip if region is invalid
            
            # Extract the region to process
            if channels == 1:
                region = working_array[y_min:y_max, x_min:x_max].copy()
                original_region = region.copy()
            else:
                region = working_array[y_min:y_max, x_min:x_max, :].copy()
                original_region = region.copy()
            
            # Apply Gaussian blur to the region
            if channels == 1:
                blurred_region = gaussian_filter(region, sigma=intensity)
            else:
                blurred_region = np.zeros_like(region)
                for c in range(channels):
                    blurred_region[:, :, c] = gaussian_filter(region[:, :, c], sigma=intensity)
            
            # Create a smooth circular mask for blending
            region_height, region_width = region.shape[:2]
            local_center_x = center_x - x_min
            local_center_y = center_y - y_min
            
            # Create coordinate grids
            y_coords, x_coords = np.ogrid[:region_height, :region_width]
            
            # Calculate distances from the blob center
            distances = np.sqrt((x_coords - local_center_x) ** 2 + (y_coords - local_center_y) ** 2)
            
            # Create smooth circular mask with falloff
            # Use a smooth transition from 1.0 (full effect) to 0.0 (no effect)
            mask = np.clip(1.0 - (distances / radius), 0, 1)
            
            # Apply smooth falloff using a cosine function for even smoother blending
            mask = 0.5 * (1 + np.cos(np.pi * (1 - mask)))
            mask = np.where(distances <= radius, mask, 0)
            
            # Apply the mask to blend original and blurred regions
            if channels == 1:
                blended_region = mask * blurred_region + (1 - mask) * original_region
            else:
                # Expand mask to match color channels
                mask_expanded = np.expand_dims(mask, axis=2)
                blended_region = mask_expanded * blurred_region + (1 - mask_expanded) * original_region
            
            # Put the blended region back into the working array
            if channels == 1:
                working_array[y_min:y_max, x_min:x_max] = blended_region
            else:
                working_array[y_min:y_max, x_min:x_max, :] = blended_region
        
        # Convert back to uint8 and return
        result = np.clip(working_array, 0, 255).astype(np.uint8)
        return result
    
    def __repr__(self) -> str:
        return (f"{self.__class__.__name__}("
                f"blob_count_range={self.blob_count_range}, "
                f"size_range={self.size_range}, "
                f"intensity_range={self.intensity_range}, "
                f"p={self.p})")
