import os
import networkx as nx
from typing import Dict, List, Tuple, Optional, Union, Iterator, Any
import torch
from torch.utils.data import Dataset, IterableDataset
from PIL import Image
import torchvision.transforms as transforms
import numpy as np
import random
import json


class PIDGraphDataset(Dataset):
    """
    PyTorch Dataset for PID (Piping and Instrumentation Diagram) object detection.
    
    This dataset loads images and their corresponding GraphML annotation files,
    extracting bounding box information for object detection tasks.
    """
    
    def __init__(
        self, 
        data_dir: str, 
        transforms: Optional[Any] = None,
        image_ext: str = '.png',
        annotation_ext: str = '.graphml',
        labels: Optional[Union[str, List[str]]] = None
    ):
        """
        Initialize the PIDGraphDataset.
        
        Args:
            data_dir (str): Directory containing images and GraphML files
            transforms (Optional[Any]): Transforms to apply to both images and targets.
                                      Should be a transform that takes (image, targets) as input
                                      and returns (transformed_image, transformed_targets).
                                      Use transforms from transforms.py like ComposeWithTargets,
                                      ToTensorWithTargets, etc.
            image_ext (str): Image file extension (default: '.png')
            annotation_ext (str): Annotation file extension (default: '.graphml')
            labels (Optional[Union[str, List[str]]]): Specific labels to include. If None, 
                                                   includes all labels. Can be a single string 
                                                   or list of strings.
        """
        self.data_dir = data_dir
        self.transforms = transforms
        self.image_ext = image_ext
        self.annotation_ext = annotation_ext
        
        # Process labels filter
        if labels is None:
            self.filter_labels = None
        elif isinstance(labels, str):
            self.filter_labels = {labels}
        elif isinstance(labels, list):
            self.filter_labels = set(labels)
        else:
            raise ValueError("labels must be None, a string, or a list of strings")
        
        # Get all image files and their corresponding annotation files
        self.samples = self._get_samples()
        
        # Create label to index mapping
        self.label_to_idx = self._create_label_mapping()
        self.idx_to_label = {v: k for k, v in self.label_to_idx.items()}
        
    def _get_samples(self) -> List[Tuple[str, str]]:
        """
        Get all valid image-annotation pairs.
        
        Returns:
            List[Tuple[str, str]]: List of (image_path, annotation_path) tuples
        """
        samples = []
        
        # Get all files in the directory
        files = os.listdir(self.data_dir)
        
        # Find image files
        image_files = [f for f in files if f.endswith(self.image_ext)]
        
        for image_file in image_files:
            # Get corresponding annotation file
            base_name = os.path.splitext(image_file)[0]
            annotation_file = base_name + self.annotation_ext
            
            image_path = os.path.join(self.data_dir, image_file)
            annotation_path = os.path.join(self.data_dir, annotation_file)
            
            # Check if both files exist
            if os.path.exists(image_path) and os.path.exists(annotation_path):
                samples.append((image_path, annotation_path))
        
        return sorted(samples)
    
    def _create_label_mapping(self) -> Dict[str, int]:
        """
        Create a mapping from label names to indices by scanning all annotation files.
        
        Returns:
            Dict[str, int]: Mapping from label names to indices
        """
        labels = set()
        
        for _, annotation_path in self.samples:
            try:
                sample_labels = self._parse_graphml_labels(annotation_path)
                labels.update(sample_labels)
            except Exception as e:
                print(f"Warning: Could not parse {annotation_path}: {e}")
                continue
        
        # Sort labels for consistent ordering
        sorted_labels = sorted(list(labels))
        
        # Create mapping (0 is typically reserved for background in object detection)
        label_to_idx = {label: idx + 1 for idx, label in enumerate(sorted_labels)}
        
        return label_to_idx
    
    def _parse_graphml_labels(self, annotation_path: str) -> List[str]:
        """
        Parse GraphML file to extract unique labels using NetworkX.
        
        Args:
            annotation_path (str): Path to the GraphML annotation file
            
        Returns:
            List[str]: List of unique labels in the file
        """
        # Load GraphML file using NetworkX
        graph = nx.read_graphml(annotation_path)
        
        labels = []
        
        # Extract labels from all nodes
        for node_id, node_data in graph.nodes(data=True):
            label = node_data.get('label')  # NetworkX maps 'd0' to 'label'
            if label:
                labels.append(label)
        
        return list(set(labels))
    
    def _parse_graphml(self, annotation_path: str) -> Dict:
        """
        Parse GraphML file to extract bounding boxes and labels using NetworkX.
        
        Args:
            annotation_path (str): Path to the GraphML annotation file
            
        Returns:
            Dict: Dictionary containing boxes, labels, and other metadata
        """
        # Load GraphML file using NetworkX
        graph = nx.read_graphml(annotation_path)
        
        boxes = []
        labels = []
        node_ids = []
        
        # Extract data from all nodes
        for node_id, node_data in graph.nodes(data=True):
            # Initialize bounding box coordinates
            xmin = ymin = xmax = ymax = None
            label = None
            
            # Extract label (NetworkX maps 'd0' to 'label')
            label = node_data.get('label')
            
            # Extract bounding box coordinates
            # NetworkX maps d1-d8 to xmin, ymin, xmax, ymax, xmin_1, ymin_1, xmax_1, ymax_1
            xmin = self._safe_float(node_data.get('xmin'))
            ymin = self._safe_float(node_data.get('ymin'))
            xmax = self._safe_float(node_data.get('xmax'))
            ymax = self._safe_float(node_data.get('ymax'))
            
            # Try alternative attribute names if primary ones are None
            if xmin is None:
                xmin = self._safe_float(node_data.get('xmin_1'))
            if ymin is None:
                ymin = self._safe_float(node_data.get('ymin_1'))
            if xmax is None:
                xmax = self._safe_float(node_data.get('xmax_1'))
            if ymax is None:
                ymax = self._safe_float(node_data.get('ymax_1'))
            
            # Only add if we have valid bounding box and label
            if (xmin is not None and ymin is not None and 
                xmax is not None and ymax is not None and 
                label is not None and label in self.label_to_idx):
                
                # Apply label filtering if specified
                if self.filter_labels is not None and label not in self.filter_labels:
                    continue
                
                # Ensure valid bounding box (xmin < xmax, ymin < ymax)
                if xmin < xmax and ymin < ymax:
                    boxes.append([xmin, ymin, xmax, ymax])
                    labels.append(self.label_to_idx[label])
                    node_ids.append(node_id)
        
        return {
            'boxes': torch.tensor(boxes, dtype=torch.float32),
            'labels': torch.tensor(labels, dtype=torch.int64),
            'node_ids': node_ids
        }
    
    def _safe_float(self, value) -> Optional[float]:
        """
        Safely convert a value to float.
        
        Args:
            value: Value to convert
            
        Returns:
            Optional[float]: Float value or None if conversion fails
        """
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    
    def __len__(self) -> int:
        """Return the number of samples in the dataset."""
        return len(self.samples)
    
    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, Dict]:
        """
        Get a sample from the dataset.
        
        Args:
            idx (int): Index of the sample
            
        Returns:
            Tuple[torch.Tensor, Dict]: (image, target) where target contains
                                     boxes, labels, and other metadata
        """
        image_path, annotation_path = self.samples[idx]
        
        # Load image
        image = Image.open(image_path).convert('RGB')
        
        # Parse annotation
        target = self._parse_graphml(annotation_path)
        
        # Add image metadata
        target['image_id'] = torch.tensor([idx])
        target['area'] = (target['boxes'][:, 3] - target['boxes'][:, 1]) * \
                        (target['boxes'][:, 2] - target['boxes'][:, 0])
        target['iscrowd'] = torch.zeros((len(target['boxes']),), dtype=torch.int64)
        
        # Apply transforms that work with both image and target
        if self.transforms:
            image, target = self.transforms(image, target)
        
        return image, target
    
    def get_label_names(self) -> List[str]:
        """
        Get list of label names in order of their indices.
        
        Returns:
            List[str]: List of label names
        """
        return [self.idx_to_label[i] for i in sorted(self.idx_to_label.keys())]
    
    def get_num_classes(self) -> int:
        """
        Get the number of classes (including background).
        
        Returns:
            int: Number of classes
        """
        return len(self.label_to_idx) + 1  # +1 for background class
    
    def collate_fn(self, batch: List[Tuple[torch.Tensor, Dict]]) -> Tuple[List[torch.Tensor], List[Dict]]:
        """
        Custom collate function for DataLoader to handle variable number of objects.
        
        Args:
            batch: List of (image, target) tuples
            
        Returns:
            Tuple[List[torch.Tensor], List[Dict]]: Batched images and targets
        """
        images, targets = zip(*batch)
        return list(images), list(targets)


class SyntheticPIDDataset(Dataset):
    """
    PyTorch Dataset for synthetic PID (Piping and Instrumentation Diagram) object detection.
    
    This dataset loads images and their corresponding JSON annotation files,
    extracting bounding box information for object detection tasks.
    """
    
    def __init__(
        self, 
        data_dir: str, 
        transforms: Optional[Any] = None,
        image_ext: str = '.png',
        annotation_ext: str = '.json',
        labels: Optional[Union[str, List[str]]] = None
    ):
        """
        Initialize the SyntheticPIDDataset.
        
        Args:
            data_dir (str): Directory containing images and JSON files
            transforms (Optional[Any]): Transforms to apply to both images and targets.
                                      Should be a transform that takes (image, targets) as input
                                      and returns (transformed_image, transformed_targets).
                                      Use transforms from transforms.py like ComposeWithTargets,
                                      ToTensorWithTargets, etc.
            image_ext (str): Image file extension (default: '.png')
            annotation_ext (str): Annotation file extension (default: '.json')
            labels (Optional[Union[str, List[str]]]): Specific labels to include. If None, 
                                                   includes all labels. Can be a single string 
                                                   or list of strings.
        """
        self.data_dir = data_dir
        self.transforms = transforms
        self.image_ext = image_ext
        self.annotation_ext = annotation_ext
        
        # Process labels filter
        if labels is None:
            self.filter_labels = None
        elif isinstance(labels, str):
            self.filter_labels = {labels}
        elif isinstance(labels, list):
            self.filter_labels = set(labels)
        else:
            raise ValueError("labels must be None, a string, or a list of strings")
        
        # Get all image files and their corresponding annotation files
        self.samples = self._get_samples()
        
        # Create label to index mapping
        self.label_to_idx = self._create_label_mapping()
        self.idx_to_label = {v: k for k, v in self.label_to_idx.items()}
        
    def _get_samples(self) -> List[Tuple[str, str]]:
        """
        Get all valid image-annotation pairs.
        
        Returns:
            List[Tuple[str, str]]: List of (image_path, annotation_path) tuples
        """
        samples = []
        
        # Get all files in the directory
        files = os.listdir(self.data_dir)
        
        # Find image files
        image_files = [f for f in files if f.endswith(self.image_ext)]
        
        for image_file in image_files:
            # Get corresponding annotation file
            base_name = os.path.splitext(image_file)[0]
            annotation_file = base_name + self.annotation_ext
            
            image_path = os.path.join(self.data_dir, image_file)
            annotation_path = os.path.join(self.data_dir, annotation_file)
            
            # Check if both files exist
            if os.path.exists(image_path) and os.path.exists(annotation_path):
                samples.append((image_path, annotation_path))
        
        return sorted(samples)
    
    def _create_label_mapping(self) -> Dict[str, int]:
        """
        Create a mapping from label names to indices by scanning all annotation files.
        
        Returns:
            Dict[str, int]: Mapping from label names to indices
        """
        labels = set()
        
        for _, annotation_path in self.samples:
            try:
                sample_labels = self._parse_json_labels(annotation_path)
                labels.update(sample_labels)
            except Exception as e:
                print(f"Warning: Could not parse {annotation_path}: {e}")
                continue
        
        # Sort labels for consistent ordering
        sorted_labels = sorted(list(labels))
        
        # Create mapping (0 is typically reserved for background in object detection)
        label_to_idx = {label: idx + 1 for idx, label in enumerate(sorted_labels)}
        
        return label_to_idx
    
    def _parse_json_labels(self, annotation_path: str) -> List[str]:
        """
        Parse JSON file to extract unique labels.
        
        Args:
            annotation_path (str): Path to the JSON annotation file
            
        Returns:
            List[str]: List of unique labels in the file
        """
        with open(annotation_path, 'r') as f:
            data = json.load(f)
        
        labels = []
        
        # Extract labels from all symbols
        for symbol in data.get('symbols', []):
            label = symbol.get('label')
            if label:
                labels.append(label)
        
        return list(set(labels))
    
    def _parse_json(self, annotation_path: str, image_width: int, image_height: int) -> Dict:
        """
        Parse JSON file to extract bounding boxes and labels.
        
        Args:
            annotation_path (str): Path to the JSON annotation file
            image_width (int): Width of the corresponding image
            image_height (int): Height of the corresponding image
            
        Returns:
            Dict: Dictionary containing boxes, labels, and other metadata
        """
        with open(annotation_path, 'r') as f:
            data = json.load(f)
        
        # Validate image dimensions
        image_info = data.get('image_info', {})
        json_width = image_info.get('width')
        json_height = image_info.get('height')
        
        if json_width != image_width or json_height != image_height:
            print(f"Warning: Image dimensions mismatch in {annotation_path}")
            print(f"  JSON: {json_width}x{json_height}, Image: {image_width}x{image_height}")
        
        boxes = []
        labels = []
        node_ids = []
        
        # Extract data from all symbols
        for symbol in data.get('symbols', []):
            label = symbol.get('label')
            bbox = symbol.get('bbox')  # [x, y, width, height]
            node_id = symbol.get('label')
            
            # Only process if we have valid data
            if label and bbox and len(bbox) == 4:
                # Apply label filtering if specified
                if self.filter_labels is not None and label not in self.filter_labels:
                    continue
                
                # Skip if label is not in our mapping (shouldn't happen after _create_label_mapping)
                if label not in self.label_to_idx:
                    continue
                
                # Convert from [x, y, width, height] to [xmin, ymin, xmax, ymax]
                x, y, w, h = bbox
                xmin, ymin, xmax, ymax = x, y, x + w, y + h
                
                # Validate and clip bounding box coordinates
                xmin = max(0, min(xmin, image_width))
                ymin = max(0, min(ymin, image_height))
                xmax = max(0, min(xmax, image_width))
                ymax = max(0, min(ymax, image_height))
                
                # Ensure valid bounding box (xmin < xmax, ymin < ymax)
                if xmin < xmax and ymin < ymax:
                    boxes.append([xmin, ymin, xmax, ymax])
                    labels.append(self.label_to_idx[label])
                    node_ids.append(node_id)
        
        return {
            'boxes': torch.tensor(boxes, dtype=torch.float32),
            'labels': torch.tensor(labels, dtype=torch.int64),
            'node_ids': node_ids
        }
    
    def __len__(self) -> int:
        """Return the number of samples in the dataset."""
        return len(self.samples)
    
    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, Dict]:
        """
        Get a sample from the dataset.
        
        Args:
            idx (int): Index of the sample
            
        Returns:
            Tuple[torch.Tensor, Dict]: (image, target) where target contains
                                     boxes, labels, and other metadata
        """
        image_path, annotation_path = self.samples[idx]
        
        # Load image
        image = Image.open(image_path).convert('RGB')
        image_width, image_height = image.size
        
        # Parse annotation
        target = self._parse_json(annotation_path, image_width, image_height)
        
        # Add image metadata
        target['image_id'] = torch.tensor([idx])
        target['area'] = (target['boxes'][:, 3] - target['boxes'][:, 1]) * \
                        (target['boxes'][:, 2] - target['boxes'][:, 0])
        target['iscrowd'] = torch.zeros((len(target['boxes']),), dtype=torch.int64)
        
        # Apply transforms that work with both image and target
        if self.transforms:
            image, target = self.transforms(image, target)
        
        return image, target
    
    def get_label_names(self) -> List[str]:
        """
        Get list of label names in order of their indices.
        
        Returns:
            List[str]: List of label names
        """
        return [self.idx_to_label[i] for i in sorted(self.idx_to_label.keys())]
    
    def get_num_classes(self) -> int:
        """
        Get the number of classes (including background).
        
        Returns:
            int: Number of classes
        """
        return len(self.label_to_idx) + 1  # +1 for background class
    
    def collate_fn(self, batch: List[Tuple[torch.Tensor, Dict]]) -> Tuple[List[torch.Tensor], List[Dict]]:
        """
        Custom collate function for DataLoader to handle variable number of objects.
        
        Args:
            batch: List of (image, target) tuples
            
        Returns:
            Tuple[List[torch.Tensor], List[Dict]]: Batched images and targets
        """
        images, targets = zip(*batch)
        return list(images), list(targets)


def create_transforms(train: bool = True) -> transforms.Compose:
    """
    Create standard transforms for the dataset.
    
    Args:
        train (bool): Whether to create transforms for training or validation
        
    Returns:
        transforms.Compose: Composed transforms
    """
    if train:
        return transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], 
                               std=[0.229, 0.224, 0.225])
        ])
    else:
        return transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], 
                               std=[0.229, 0.224, 0.225])
        ])


class MixedIterableDataset(IterableDataset):
    """
    An iterable dataset that randomly samples from multiple map-style datasets
    based on specified probabilities.
    
    This dataset is useful for combining multiple datasets with different sampling
    weights, such as balancing datasets of different sizes or emphasizing certain
    data sources during training.
    
    Args:
        datasets: List of PyTorch map-style datasets
        probabilities: List of probabilities for sampling from each dataset.
                      Must sum to 1.0 and have the same length as datasets.
        seed: Random seed for reproducibility (optional)
        infinite: If True, the dataset will cycle infinitely. If False, it will
                 stop after one epoch through all datasets (default: True)
        epoch_size: Number of samples per epoch. If None, uses the sum of all
                   dataset lengths (only used when infinite=False)
    
    Example:
        >>> dataset1 = MyDataset1()  # 1000 samples
        >>> dataset2 = MyDataset2()  # 500 samples  
        >>> dataset3 = MyDataset3()  # 200 samples
        >>> 
        >>> # Sample with equal probability from each dataset
        >>> mixed_dataset = MixedIterableDataset(
        ...     datasets=[dataset1, dataset2, dataset3],
        ...     probabilities=[0.33, 0.33, 0.34]
        ... )
        >>> 
        >>> # Or weight by dataset size
        >>> total_size = len(dataset1) + len(dataset2) + len(dataset3)
        >>> mixed_dataset = MixedIterableDataset(
        ...     datasets=[dataset1, dataset2, dataset3],
        ...     probabilities=[len(d)/total_size for d in [dataset1, dataset2, dataset3]]
        ... )
    """
    
    def __init__(
        self,
        datasets: List[Dataset],
        probabilities: List[float],
        seed: Optional[int] = None,
        infinite: bool = True,
        epoch_size: Optional[int] = None
    ):
        super().__init__()
        
        # Validation
        if len(datasets) == 0:
            raise ValueError("At least one dataset must be provided")
        
        if len(datasets) != len(probabilities):
            raise ValueError(
                f"Number of datasets ({len(datasets)}) must match "
                f"number of probabilities ({len(probabilities)})"
            )
        
        if not all(isinstance(ds, Dataset) for ds in datasets):
            raise ValueError("All datasets must be map-style datasets (inherit from Dataset)")
        
        if not all(len(ds) > 0 for ds in datasets):
            raise ValueError("All datasets must be non-empty")
        
        # Normalize probabilities to ensure they sum to 1.0
        prob_sum = sum(probabilities)
        if abs(prob_sum - 1.0) > 1e-6:
            print(f"Warning: Probabilities sum to {prob_sum}, normalizing to 1.0")
            probabilities = [p / prob_sum for p in probabilities]
        
        self.datasets = datasets
        self.probabilities = probabilities
        self.seed = seed
        self.infinite = infinite
        
        # Calculate dataset sizes
        self.dataset_sizes = [len(ds) for ds in datasets]
        self.total_size = sum(self.dataset_sizes)
        
        # Set epoch size
        if epoch_size is None:
            self.epoch_size = self.total_size
        else:
            self.epoch_size = epoch_size
        
        # Create cumulative probabilities for efficient sampling
        self.cumulative_probs = np.cumsum(probabilities)
        
        # Initialize random state
        self._rng = np.random.RandomState(seed)
        
    def __iter__(self) -> Iterator[Any]:
        """
        Create an iterator that yields samples from the mixed datasets.
        
        Returns:
            Iterator yielding samples from the constituent datasets
        """
        # Create per-worker random state to avoid issues with multiprocessing
        worker_info = torch.utils.data.get_worker_info()
        if worker_info is not None:
            # In multiprocessing mode, create unique seed for each worker
            worker_seed = self.seed + worker_info.id if self.seed is not None else worker_info.id
            rng = np.random.RandomState(worker_seed)
        else:
            # Single process mode
            rng = self._rng
        
        # Create dataset iterators with shuffled indices
        dataset_iterators = []
        for i, dataset in enumerate(self.datasets):
            indices = list(range(len(dataset)))
            rng.shuffle(indices)
            dataset_iterators.append(iter(indices))
        
        samples_yielded = 0
        
        while True:
            # Choose which dataset to sample from
            rand_val = rng.random()
            dataset_idx = np.searchsorted(self.cumulative_probs, rand_val)
            
            # Ensure we don't go out of bounds due to floating point precision
            dataset_idx = min(dataset_idx, len(self.datasets) - 1)
            
            try:
                # Get next index from the chosen dataset
                sample_idx = next(dataset_iterators[dataset_idx])
                
                # Yield the sample
                yield self.datasets[dataset_idx][sample_idx]
                samples_yielded += 1
                
            except StopIteration:
                # Dataset iterator is exhausted, create a new one
                indices = list(range(len(self.datasets[dataset_idx])))
                rng.shuffle(indices)
                dataset_iterators[dataset_idx] = iter(indices)
                
                # Try again with the new iterator
                sample_idx = next(dataset_iterators[dataset_idx])
                yield self.datasets[dataset_idx][sample_idx]
                samples_yielded += 1
            
            # Check if we should stop (only for finite mode)
            if not self.infinite and samples_yielded >= self.epoch_size:
                break

    def __len__(self) -> int:
        """
        Return the length of the dataset.
        
        For infinite datasets, this returns the epoch size.
        For finite datasets, this returns the total size of all constituent datasets.
        """
        if self.infinite:
            return self.epoch_size
        else:
            return self.total_size

    def get_dataset_info(self) -> dict:
        """
        Get information about the constituent datasets.
        
        Returns:
            Dictionary containing dataset information
        """
        return {
            'num_datasets': len(self.datasets),
            'dataset_sizes': self.dataset_sizes,
            'total_size': self.total_size,
            'probabilities': self.probabilities,
            'epoch_size': self.epoch_size,
            'infinite': self.infinite
        }

    def set_epoch_size(self, epoch_size: int):
        """
        Set the epoch size for the dataset.
        
        Args:
            epoch_size: Number of samples per epoch
        """
        self.epoch_size = epoch_size

    def get_expected_samples_per_dataset(self, num_samples: Optional[int] = None) -> List[int]:
        """
        Calculate expected number of samples from each dataset.
        
        Args:
            num_samples: Total number of samples to consider. If None, uses epoch_size.
            
        Returns:
            List of expected sample counts for each dataset
        """
        if num_samples is None:
            num_samples = self.epoch_size
        
        return [int(prob * num_samples) for prob in self.probabilities]


class WeightedMixedIterableDataset(MixedIterableDataset):
    """
    A convenience class that automatically calculates probabilities based on dataset weights.
    
    Args:
        datasets: List of PyTorch map-style datasets
        weights: List of weights for each dataset. Will be normalized to probabilities.
        **kwargs: Additional arguments passed to MixedIterableDataset
    
    Example:
        >>> dataset1 = MyDataset1()  # Want this to be sampled 3x more often
        >>> dataset2 = MyDataset2()  # Normal sampling
        >>> dataset3 = MyDataset3()  # Want this to be sampled 2x more often
        >>> 
        >>> mixed_dataset = WeightedMixedIterableDataset(
        ...     datasets=[dataset1, dataset2, dataset3],
        ...     weights=[3.0, 1.0, 2.0]  # Will be normalized to [0.5, 0.167, 0.333]
        ... )
    """

    def __init__(
        self,
        datasets: List[Dataset],
        weights: List[float],
        **kwargs
    ):
        # Normalize weights to probabilities
        weight_sum = sum(weights)
        probabilities = [w / weight_sum for w in weights]
        
        super().__init__(datasets, probabilities, **kwargs)
        self.weights = weights


class BalancedMixedIterableDataset(MixedIterableDataset):
    """
    A convenience class that automatically balances datasets by giving equal probability
    to each dataset regardless of their sizes.
    
    Args:
        datasets: List of PyTorch map-style datasets
        **kwargs: Additional arguments passed to MixedIterableDataset
    
    Example:
        >>> dataset1 = MyDataset1()  # 10000 samples
        >>> dataset2 = MyDataset2()  # 100 samples
        >>> dataset3 = MyDataset3()  # 50 samples
        >>> 
        >>> # Each dataset will be sampled with equal probability (0.333 each)
        >>> mixed_dataset = BalancedMixedIterableDataset(
        ...     datasets=[dataset1, dataset2, dataset3]
        ... )
    """
    
    def __init__(
        self,
        datasets: List[Dataset],
        **kwargs
    ):
        # Equal probability for each dataset
        num_datasets = len(datasets)
        probabilities = [1.0 / num_datasets] * num_datasets
        
        super().__init__(datasets, probabilities, **kwargs)


def create_size_weighted_probabilities(datasets: List[Dataset]) -> List[float]:
    """
    Create probabilities proportional to dataset sizes.
    
    Args:
        datasets: List of datasets
        
    Returns:
        List of probabilities proportional to dataset sizes
    """
    sizes = [len(ds) for ds in datasets]
    total_size = sum(sizes)
    return [size / total_size for size in sizes]


def create_inverse_size_weighted_probabilities(datasets: List[Dataset]) -> List[float]:
    """
    Create probabilities inversely proportional to dataset sizes.
    This gives smaller datasets higher probability to balance representation.
    
    Args:
        datasets: List of datasets
        
    Returns:
        List of probabilities inversely proportional to dataset sizes
    """
    sizes = [len(ds) for ds in datasets]
    inverse_sizes = [1.0 / size for size in sizes]
    total_inverse = sum(inverse_sizes)
    return [inv_size / total_inverse for inv_size in inverse_sizes]
