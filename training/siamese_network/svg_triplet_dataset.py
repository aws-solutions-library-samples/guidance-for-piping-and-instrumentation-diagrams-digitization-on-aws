import torch
from torch.utils.data import Dataset, DataLoader
import cairosvg
import numpy as np
from PIL import Image
import io
import os
import random
from collections import defaultdict
from typing import Optional, Tuple, Dict, List


class SVGTripletDataset(Dataset):
    """
    PyTorch Dataset for creating triplets of PID symbols for siamese network training.
    
    Creates triplets of (anchor, positive, negative) where:
    - anchor: random symbol from dataset
    - positive: same symbol (same file read again)
    - negative: different symbol from a different category
    """
    
    def __init__(self, 
                 svg_dir: str, 
                 image_size: Tuple[int, int] = (448, 448),
                 transform=None):
        """
        Initialize the SVG Triplet Dataset.
        
        Args:
            svg_dir: Directory containing SVG files
            image_size: Target image size (height, width)
            transform: Albumentations transform to apply to images
        """
        self.svg_dir = svg_dir
        self.image_size = image_size
        self.transform = transform
        
        # Load and organize SVG files
        self.svg_files = []
        self.category_mapping = defaultdict(list)
        self.categories = []
        
        self._load_svg_files()
        self._create_category_mapping()
    
    def _load_svg_files(self):
        """Load all SVG files from the directory."""
        for filename in os.listdir(self.svg_dir):
            if filename.endswith('.svg'):
                self.svg_files.append(filename)
        
        if not self.svg_files:
            raise ValueError(f"No SVG files found in {self.svg_dir}")
    
    def _create_category_mapping(self):
        """Create mapping from categories to SVG files."""
        for svg_file in self.svg_files:
            # Extract category from filename (everything before first underscore)
            if '_' in svg_file:
                category = svg_file.split('_')[0]
            else:
                category = 'uncategorized'
            
            self.category_mapping[category].append(svg_file)
        
        self.categories = list(self.category_mapping.keys())
        
        # Ensure we have at least 2 categories for negative sampling
        if len(self.categories) < 2:
            raise ValueError("Need at least 2 categories for negative sampling")
    
    def svg_to_numpy(self, svg_path: str) -> np.ndarray:
        """
        Convert SVG file to RGB numpy array.
        
        Args:
            svg_path: Path to SVG file
            
        Returns:
            RGB numpy array of shape (height, width, 3) with values in [0, 1]
        """
        try:
            # Convert SVG to PNG bytes
            png_bytes = cairosvg.svg2png(
                url=svg_path,
                output_width=self.image_size[1],
                output_height=self.image_size[0]
            )
            
            # Load PNG from bytes
            image = Image.open(io.BytesIO(png_bytes))
            
            # Convert to RGB (handle transparency by using white background)
            if image.mode != 'RGB':
                # Create white background
                rgb_image = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'RGBA':
                    rgb_image.paste(image, mask=image.split()[-1])  # Use alpha channel as mask
                else:
                    rgb_image.paste(image)
                image = rgb_image
            
            # Ensure correct size
            if image.size != (self.image_size[1], self.image_size[0]):
                image = image.resize((self.image_size[1], self.image_size[0]), Image.Resampling.LANCZOS)
            
            # Convert to numpy array and normalize to [0, 1]
            img_array = np.array(image, dtype=np.float32) / 255.0
            
            return img_array
            
        except Exception as e:
            raise RuntimeError(f"Failed to convert SVG {svg_path}: {str(e)}")
    
    def get_triplet_indices(self, anchor_idx: int) -> Tuple[int, int, int]:
        """
        Get indices for triplet (anchor, positive, negative).
        
        Args:
            anchor_idx: Index of anchor image
            
        Returns:
            Tuple of (anchor_idx, positive_idx, negative_idx)
        """
        anchor_file = self.svg_files[anchor_idx]
        anchor_category = anchor_file.split('_')[0] if '_' in anchor_file else 'uncategorized'
        
        # Positive is the same file
        positive_idx = anchor_idx
        
        # Negative must be from a different category
        other_categories = [cat for cat in self.categories if cat != anchor_category]
        negative_category = random.choice(other_categories)
        negative_file = random.choice(self.category_mapping[negative_category])
        negative_idx = self.svg_files.index(negative_file)
        
        return anchor_idx, positive_idx, negative_idx
    
    def __len__(self) -> int:
        """Return the number of samples in the dataset."""
        return len(self.svg_files)
    
    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Get a triplet of images.
        
        Args:
            idx: Index of the anchor image
            
        Returns:
            Tuple of (anchor, positive, negative) tensors, each of shape (3, H, W)
        """
        # Get triplet indices
        anchor_idx, positive_idx, negative_idx = self.get_triplet_indices(idx)
        
        # Load images
        anchor_path = os.path.join(self.svg_dir, self.svg_files[anchor_idx])
        positive_path = os.path.join(self.svg_dir, self.svg_files[positive_idx])
        negative_path = os.path.join(self.svg_dir, self.svg_files[negative_idx])
        
        # Convert SVGs to numpy arrays
        anchor_img = self.svg_to_numpy(anchor_path)
        positive_img = self.svg_to_numpy(positive_path)
        negative_img = self.svg_to_numpy(negative_path)
        
        # Apply transforms if provided
        if self.transform:
            anchor_img = self.transform(image=anchor_img)['image']
            positive_img = self.transform(image=positive_img)['image']
            negative_img = self.transform(image=negative_img)['image']
        
        # Convert to torch tensors and change from (H, W, C) to (C, H, W)
        anchor_tensor = torch.from_numpy(anchor_img).permute(2, 0, 1).float()
        positive_tensor = torch.from_numpy(positive_img).permute(2, 0, 1).float()
        negative_tensor = torch.from_numpy(negative_img).permute(2, 0, 1).float()
        
        return anchor_tensor, positive_tensor, negative_tensor


def create_dataloader(svg_dir: str, 
                     batch_size: int = 16, 
                     image_size: Tuple[int, int] = (448, 448),
                     transform=None,
                     shuffle: bool = True,
                     num_workers: int = 0) -> DataLoader:
    """
    Create a DataLoader for the SVG triplet dataset.
    
    Args:
        svg_dir: Directory containing SVG files
        batch_size: Batch size for training
        image_size: Target image size (height, width)
        transform: Albumentations transform to apply
        shuffle: Whether to shuffle the dataset
        num_workers: Number of worker processes for data loading
        
    Returns:
        DataLoader instance
    """
    dataset = SVGTripletDataset(svg_dir, image_size, transform)
    dataloader = DataLoader(
        dataset, 
        batch_size=batch_size, 
        shuffle=shuffle, 
        num_workers=num_workers,
        pin_memory=torch.cuda.is_available()
    )
    return dataloader


if __name__ == "__main__":
    # Example usage
    print("Testing SVG Triplet Dataset...")
    
    # Create dataset
    dataset = SVGTripletDataset('svgs/', image_size=(448, 448))
    
    # Test single sample
    anchor, positive, negative = dataset[0]
    print(f"Anchor shape: {anchor.shape}")
    print(f"Positive shape: {positive.shape}")
    print(f"Negative shape: {negative.shape}")
    print(f"Data type: {anchor.dtype}")
    print(f"Value range: [{anchor.min():.3f}, {anchor.max():.3f}]")
    
    # Test dataloader
    dataloader = create_dataloader('svgs/', batch_size=4)
    
    for batch_idx, (anchors, positives, negatives) in enumerate(dataloader):
        print(f"\nBatch {batch_idx}:")
        print(f"Anchors batch shape: {anchors.shape}")
        print(f"Positives batch shape: {positives.shape}")
        print(f"Negatives batch shape: {negatives.shape}")
        
        if batch_idx >= 2:  # Only test first few batches
            break
    
    print("\nDataset test completed successfully!")
