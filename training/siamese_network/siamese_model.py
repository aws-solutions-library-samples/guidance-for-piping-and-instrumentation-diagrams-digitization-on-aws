"""
Siamese Network model for PID symbol classification using triplet loss.
The model outputs embeddings that can be compared using pairwise distances.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.models as models
from typing import Tuple, Optional
import math


class SiameseNetwork(nn.Module):
    """
    Siamese Network for PID symbol embedding generation.
    
    Uses a shared CNN backbone to generate embeddings for input images.
    The embeddings can be compared using distance metrics for similarity.
    """
    
    def __init__(self, 
                 embedding_dim: int = 128,
                 backbone: str = 'resnet18',
                 pretrained: bool = True,
                 dropout_rate: float = 0.5):
        """
        Initialize the Siamese Network.
        
        Args:
            embedding_dim: Dimension of the output embedding
            backbone: Backbone architecture ('resnet18', 'resnet34', 'resnet50', 'efficientnet_b0')
            pretrained: Whether to use pretrained weights
            dropout_rate: Dropout rate for regularization
        """
        super(SiameseNetwork, self).__init__()
        
        self.embedding_dim = embedding_dim
        self.backbone_name = backbone
        
        # Create backbone network
        self.backbone = self._create_backbone(backbone, pretrained)
        
        # Get the number of features from backbone
        backbone_features = self._get_backbone_features(backbone)
        
        # Embedding head
        self.embedding_head = nn.Sequential(
            nn.Linear(backbone_features, 512),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout_rate),
            nn.Linear(512, 256),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout_rate),
            nn.Linear(256, embedding_dim)
        )
        
        # Initialize weights
        self._initialize_weights()
    
    def _create_backbone(self, backbone: str, pretrained: bool) -> nn.Module:
        """Create the backbone network."""
        if backbone == 'resnet18':
            model = models.resnet18(pretrained=pretrained)
            # Remove the final classification layer
            model = nn.Sequential(*list(model.children())[:-1])
        elif backbone == 'resnet34':
            model = models.resnet34(pretrained=pretrained)
            model = nn.Sequential(*list(model.children())[:-1])
        elif backbone == 'resnet50':
            model = models.resnet50(pretrained=pretrained)
            model = nn.Sequential(*list(model.children())[:-1])
        elif backbone == 'efficientnet_b0':
            model = models.efficientnet_b0(pretrained=pretrained)
            # Remove classifier
            model.classifier = nn.Identity()
        else:
            raise ValueError(f"Unsupported backbone: {backbone}")
        
        return model
    
    def _get_backbone_features(self, backbone: str) -> int:
        """Get the number of output features from the backbone."""
        feature_dims = {
            'resnet18': 512,
            'resnet34': 512,
            'resnet50': 2048,
            'efficientnet_b0': 1280
        }
        return feature_dims[backbone]
    
    def _initialize_weights(self):
        """Initialize weights for the embedding head."""
        for m in self.embedding_head.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                if m.bias is not None:
                    nn.init.constant_(m.bias, 0)
    
    def forward_one(self, x: torch.Tensor) -> torch.Tensor:
        """
        Forward pass for a single image.
        
        Args:
            x: Input image tensor [batch_size, channels, height, width]
            
        Returns:
            Embedding tensor [batch_size, embedding_dim]
        """
        # Extract features using backbone
        features = self.backbone(x)
        
        # Flatten features
        if len(features.shape) > 2:
            features = features.view(features.size(0), -1)
        
        # Generate embedding
        embedding = self.embedding_head(features)
        
        # L2 normalize the embedding
        embedding = F.normalize(embedding, p=2, dim=1)
        
        return embedding
    
    def forward(self, anchor: torch.Tensor, positive: torch.Tensor, negative: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Forward pass for triplet inputs.
        
        Args:
            anchor: Anchor images [batch_size, channels, height, width]
            positive: Positive images [batch_size, channels, height, width]
            negative: Negative images [batch_size, channels, height, width]
            
        Returns:
            Tuple of (anchor_embedding, positive_embedding, negative_embedding)
        """
        anchor_embedding = self.forward_one(anchor)
        positive_embedding = self.forward_one(positive)
        negative_embedding = self.forward_one(negative)
        
        return anchor_embedding, positive_embedding, negative_embedding
    
    def get_embedding(self, x: torch.Tensor) -> torch.Tensor:
        """
        Get embedding for input images (inference mode).
        
        Args:
            x: Input images [batch_size, channels, height, width]
            
        Returns:
            Normalized embeddings [batch_size, embedding_dim]
        """
        return self.forward_one(x)


class TripletLoss(nn.Module):
    """
    Triplet Loss for training the Siamese Network.
    
    Loss = max(0, margin + d(anchor, positive) - d(anchor, negative))
    where d is the distance function (typically L2 distance).
    """
    
    def __init__(self, margin: float = 1.0, distance_function: str = 'euclidean'):
        """
        Initialize Triplet Loss.
        
        Args:
            margin: Margin for triplet loss
            distance_function: Distance function ('euclidean' or 'cosine')
        """
        super(TripletLoss, self).__init__()
        self.margin = margin
        self.distance_function = distance_function
    
    def forward(self, anchor: torch.Tensor, positive: torch.Tensor, negative: torch.Tensor) -> torch.Tensor:
        """
        Compute triplet loss.
        
        Args:
            anchor: Anchor embeddings [batch_size, embedding_dim]
            positive: Positive embeddings [batch_size, embedding_dim]
            negative: Negative embeddings [batch_size, embedding_dim]
            
        Returns:
            Triplet loss value
        """
        if self.distance_function == 'euclidean':
            # Euclidean distance
            pos_dist = F.pairwise_distance(anchor, positive, p=2)
            neg_dist = F.pairwise_distance(anchor, negative, p=2)
        elif self.distance_function == 'cosine':
            # Cosine distance (1 - cosine similarity)
            pos_dist = 1 - F.cosine_similarity(anchor, positive)
            neg_dist = 1 - F.cosine_similarity(anchor, negative)
        else:
            raise ValueError(f"Unsupported distance function: {self.distance_function}")
        
        # Triplet loss
        loss = F.relu(self.margin + pos_dist - neg_dist)
        
        return loss.mean()


class ContrastiveLoss(nn.Module):
    """
    Contrastive Loss as an alternative to Triplet Loss.
    Can be used for pairwise training.
    """
    
    def __init__(self, margin: float = 1.0):
        """
        Initialize Contrastive Loss.
        
        Args:
            margin: Margin for contrastive loss
        """
        super(ContrastiveLoss, self).__init__()
        self.margin = margin
    
    def forward(self, embedding1: torch.Tensor, embedding2: torch.Tensor, label: torch.Tensor) -> torch.Tensor:
        """
        Compute contrastive loss.
        
        Args:
            embedding1: First set of embeddings [batch_size, embedding_dim]
            embedding2: Second set of embeddings [batch_size, embedding_dim]
            label: Labels (1 for same class, 0 for different class) [batch_size]
            
        Returns:
            Contrastive loss value
        """
        distance = F.pairwise_distance(embedding1, embedding2, p=2)
        
        # Loss for same class pairs
        pos_loss = label * torch.pow(distance, 2)
        
        # Loss for different class pairs
        neg_loss = (1 - label) * torch.pow(F.relu(self.margin - distance), 2)
        
        loss = pos_loss + neg_loss
        return loss.mean()


def compute_distance(embedding1: torch.Tensor, embedding2: torch.Tensor, distance_type: str = 'euclidean') -> torch.Tensor:
    """
    Compute distance between embeddings.
    
    Args:
        embedding1: First embedding [batch_size, embedding_dim] or [embedding_dim]
        embedding2: Second embedding [batch_size, embedding_dim] or [embedding_dim]
        distance_type: Type of distance ('euclidean', 'cosine', 'manhattan')
        
    Returns:
        Distance values
    """
    if distance_type == 'euclidean':
        return F.pairwise_distance(embedding1, embedding2, p=2)
    elif distance_type == 'cosine':
        return 1 - F.cosine_similarity(embedding1, embedding2)
    elif distance_type == 'manhattan':
        return F.pairwise_distance(embedding1, embedding2, p=1)
    else:
        raise ValueError(f"Unsupported distance type: {distance_type}")


def create_siamese_model(embedding_dim: int = 128, 
                        backbone: str = 'resnet18', 
                        pretrained: bool = True,
                        dropout_rate: float = 0.5) -> SiameseNetwork:
    """
    Factory function to create a Siamese Network model.
    
    Args:
        embedding_dim: Dimension of output embeddings
        backbone: Backbone architecture
        pretrained: Whether to use pretrained weights
        dropout_rate: Dropout rate for regularization
        
    Returns:
        SiameseNetwork model
    """
    return SiameseNetwork(
        embedding_dim=embedding_dim,
        backbone=backbone,
        pretrained=pretrained,
        dropout_rate=dropout_rate
    )


if __name__ == "__main__":
    # Test the model
    print("Testing Siamese Network...")
    
    # Create model
    model = create_siamese_model(embedding_dim=128, backbone='resnet18')
    print(f"Model created with {sum(p.numel() for p in model.parameters())} parameters")
    
    # Test with dummy data
    batch_size = 4
    channels, height, width = 3, 448, 448
    
    anchor = torch.randn(batch_size, channels, height, width)
    positive = torch.randn(batch_size, channels, height, width)
    negative = torch.randn(batch_size, channels, height, width)
    
    print(f"Input shapes: {anchor.shape}")
    
    # Forward pass
    model.eval()
    with torch.no_grad():
        anchor_emb, positive_emb, negative_emb = model(anchor, positive, negative)
    
    print(f"Embedding shapes: {anchor_emb.shape}")
    print(f"Embedding range: [{anchor_emb.min():.3f}, {anchor_emb.max():.3f}]")
    
    # Test loss
    criterion = TripletLoss(margin=1.0)
    loss = criterion(anchor_emb, positive_emb, negative_emb)
    print(f"Triplet loss: {loss.item():.4f}")
    
    # Test distance computation
    pos_dist = compute_distance(anchor_emb, positive_emb, 'euclidean')
    neg_dist = compute_distance(anchor_emb, negative_emb, 'euclidean')
    
    print(f"Positive distances: {pos_dist.mean():.4f} ± {pos_dist.std():.4f}")
    print(f"Negative distances: {neg_dist.mean():.4f} ± {neg_dist.std():.4f}")
    
    print("✓ Model test completed successfully!")
