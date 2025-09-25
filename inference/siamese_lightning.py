import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.models as models
import lightning.pytorch as pl
from lightning.pytorch.callbacks import ModelCheckpoint, EarlyStopping, LearningRateMonitor
from lightning.pytorch.loggers import TensorBoardLogger
import torchmetrics
from typing import Tuple, Optional, Dict, Any, List
import math
import numpy as np
from sklearn.metrics import accuracy_score, roc_auc_score


class SiameseLightningModule(pl.LightningModule):
    """
    PyTorch Lightning module for Siamese Network training on P&ID symbol matching.
    
    This module encapsulates the model architecture, training logic, validation,
    and optimization in a clean Lightning format.
    
    Args:
        backbone: Type of backbone architecture ('resnet18', 'resnet50', 'efficientnet_b0', 'custom')
        embedding_dim: Dimension of the output embedding vector
        pretrained: Whether to use pretrained weights for backbone
        dropout_rate: Dropout rate for regularization
        loss_type: Type of loss function ('contrastive', 'triplet', 'arcface')
        margin: Margin for loss functions
        learning_rate: Learning rate for optimizer
        weight_decay: Weight decay for optimizer
        distance_threshold: Threshold for binary classification during validation
        num_classes: Number of classes (required for ArcFace loss)
    """
    
    def __init__(
        self,
        backbone: str = 'resnet18',
        embedding_dim: int = 128,
        pretrained: bool = True,
        dropout_rate: float = 0.5,
        loss_type: str = 'contrastive',
        margin: float = 1.0,
        learning_rate: float = 1e-3,
        weight_decay: float = 1e-4,
        distance_threshold: float = 0.5,
        num_classes: Optional[int] = None,
        **kwargs
    ):
        super().__init__()
        self.save_hyperparameters()
        
        # Store hyperparameters
        self.backbone_name = backbone
        self.embedding_dim = embedding_dim
        self.dropout_rate = dropout_rate
        self.loss_type = loss_type
        self.margin = margin
        self.learning_rate = learning_rate
        self.weight_decay = weight_decay
        self.distance_threshold = distance_threshold
        self.num_classes = num_classes
        
        # Build the network
        self._build_network(backbone, embedding_dim, pretrained, dropout_rate)
        
        # Initialize loss function
        self._init_loss_function()
        
        # Initialize metrics
        self._init_metrics()
        
        # Store validation outputs for epoch-end calculations
        self.validation_step_outputs = []
    
    def _build_network(self, backbone: str, embedding_dim: int, pretrained: bool, dropout_rate: float):
        """Build the backbone network and embedding head."""
        
        # Create the backbone network
        if backbone == 'resnet18':
            self.backbone = models.resnet18(weights='IMAGENET1K_V1' if pretrained else None)
            backbone_output_dim = self.backbone.fc.in_features
            self.backbone.fc = nn.Identity()  # Remove final classification layer
            
        elif backbone == 'resnet50':
            self.backbone = models.resnet50(weights='IMAGENET1K_V1' if pretrained else None)
            backbone_output_dim = self.backbone.fc.in_features
            self.backbone.fc = nn.Identity()
            
        elif backbone == 'efficientnet_b0':
            self.backbone = models.efficientnet_b0(weights='IMAGENET1K_V1' if pretrained else None)
            backbone_output_dim = self.backbone.classifier[1].in_features
            self.backbone.classifier = nn.Identity()
            
        elif backbone == 'custom':
            self.backbone = self._create_custom_backbone()
            backbone_output_dim = 512
            
        else:
            raise ValueError(f"Unsupported backbone: {backbone}")
        
        # Create the embedding head
        self.embedding_head = nn.Sequential(
            nn.Linear(backbone_output_dim, 512),
            nn.BatchNorm1d(512),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout_rate),
            nn.Linear(512, 256),
            nn.BatchNorm1d(256),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout_rate),
            nn.Linear(256, embedding_dim)
        )
        
        # Initialize weights
        self._initialize_weights()
    
    def _create_custom_backbone(self) -> nn.Module:
        """Create a custom CNN backbone optimized for P&ID symbols."""
        return nn.Sequential(
            # First block
            nn.Conv2d(3, 64, kernel_size=7, stride=2, padding=3),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=3, stride=2, padding=1),
            
            # Second block
            nn.Conv2d(64, 128, kernel_size=3, stride=1, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.Conv2d(128, 128, kernel_size=3, stride=1, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=2, stride=2),
            
            # Third block
            nn.Conv2d(128, 256, kernel_size=3, stride=1, padding=1),
            nn.BatchNorm2d(256),
            nn.ReLU(inplace=True),
            nn.Conv2d(256, 256, kernel_size=3, stride=1, padding=1),
            nn.BatchNorm2d(256),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(kernel_size=2, stride=2),
            
            # Fourth block
            nn.Conv2d(256, 512, kernel_size=3, stride=1, padding=1),
            nn.BatchNorm2d(512),
            nn.ReLU(inplace=True),
            nn.Conv2d(512, 512, kernel_size=3, stride=1, padding=1),
            nn.BatchNorm2d(512),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((1, 1)),
            nn.Flatten()
        )
    
    def _initialize_weights(self):
        """Initialize network weights."""
        for m in self.embedding_head.modules():
            if isinstance(m, nn.Linear):
                nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
                if m.bias is not None:
                    nn.init.constant_(m.bias, 0)
            elif isinstance(m, nn.BatchNorm1d):
                nn.init.constant_(m.weight, 1)
                nn.init.constant_(m.bias, 0)
    
    def _init_loss_function(self):
        """Initialize the loss function based on loss_type."""
        if self.loss_type == 'contrastive':
            self.criterion = ContrastiveLoss(margin=self.margin)
        elif self.loss_type == 'triplet':
            self.criterion = TripletLoss(margin=self.margin)
        elif self.loss_type == 'arcface':
            if self.num_classes is None:
                raise ValueError("num_classes required for ArcFace loss")
            self.criterion = ArcFaceLoss(
                in_features=self.embedding_dim,
                out_features=self.num_classes,
                margin=self.margin
            )
        else:
            raise ValueError(f"Unsupported loss type: {self.loss_type}")
    
    def _init_metrics(self):
        """Initialize metrics for tracking."""
        # We'll compute custom metrics in validation_epoch_end
        pass
    
    def forward_once(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass through one branch of the siamese network."""
        # Extract features using backbone
        features = self.backbone(x)
        
        # Get embedding
        embedding = self.embedding_head(features)
        
        # L2 normalize the embedding
        embedding = F.normalize(embedding, p=2, dim=1)
        
        return embedding
    
    def forward(self, x1: torch.Tensor, x2: Optional[torch.Tensor] = None) -> torch.Tensor:
        """
        Forward pass through the siamese network.
        
        Args:
            x1: First input tensor or single input for embedding
            x2: Second input tensor (optional)
            
        Returns:
            If x2 is provided: tuple of (embedding1, embedding2)
            If x2 is None: single embedding for x1
        """
        if x2 is not None:
            embedding1 = self.forward_once(x1)
            embedding2 = self.forward_once(x2)
            return embedding1, embedding2
        else:
            return self.forward_once(x1)
    
    def training_step(self, batch, batch_idx):
        """Training step."""
        if self.loss_type == 'contrastive':
            img1 = batch['image1']
            img2 = batch['image2']
            labels = batch['label'].float()
            
            emb1, emb2 = self(img1, img2)
            loss = self.criterion(emb1, emb2, labels)
            
            # Log metrics
            self.log('train_loss', loss, on_step=True, on_epoch=True, prog_bar=True)
            
        elif self.loss_type == 'triplet':
            anchor = batch['anchor']
            positive = batch['positive']
            negative = batch['negative']
            
            emb_anchor = self(anchor)
            emb_positive = self(positive)
            emb_negative = self(negative)
            
            loss = self.criterion(emb_anchor, emb_positive, emb_negative)
            
            self.log('train_loss', loss, on_step=True, on_epoch=True, prog_bar=True)
        
        elif self.loss_type == 'arcface':
            images = batch['image']
            labels = batch['category_id']
            
            embeddings = self(images)
            loss = self.criterion(embeddings, labels)
            
            self.log('train_loss', loss, on_step=True, on_epoch=True, prog_bar=True)
        
        return loss
    
    def validation_step(self, batch, batch_idx):
        """Validation step."""
        if self.loss_type == 'contrastive':
            img1 = batch['image1']
            img2 = batch['image2']
            labels = batch['label'].float()
            
            emb1, emb2 = self(img1, img2)
            loss = self.criterion(emb1, emb2, labels)
            
            # Calculate distances for accuracy computation
            distances = F.pairwise_distance(emb1, emb2)
            
            # Store outputs for epoch-end calculations
            self.validation_step_outputs.append({
                'loss': loss,
                'distances': distances.detach().cpu(),
                'labels': labels.detach().cpu()
            })
            
        elif self.loss_type == 'triplet':
            anchor = batch['anchor']
            positive = batch['positive']
            negative = batch['negative']
            
            emb_anchor = self(anchor)
            emb_positive = self(positive)
            emb_negative = self(negative)
            
            loss = self.criterion(emb_anchor, emb_positive, emb_negative)
            
            # Calculate distances
            pos_distances = F.pairwise_distance(emb_anchor, emb_positive)
            neg_distances = F.pairwise_distance(emb_anchor, emb_negative)
            
            # Store for epoch-end calculations
            self.validation_step_outputs.append({
                'loss': loss,
                'pos_distances': pos_distances.detach().cpu(),
                'neg_distances': neg_distances.detach().cpu()
            })
        
        elif self.loss_type == 'arcface':
            images = batch['image']
            labels = batch['category_id']
            
            embeddings = self(images)
            loss = self.criterion(embeddings, labels)
            
            self.validation_step_outputs.append({
                'loss': loss
            })
        
        return {'val_loss': loss}
    
    def on_validation_epoch_end(self):
        """Compute metrics at the end of validation epoch."""
        if not self.validation_step_outputs:
            return
        
        # Calculate average loss
        avg_loss = torch.stack([x['loss'] for x in self.validation_step_outputs]).mean()
        self.log('val_loss', avg_loss, prog_bar=True)
        
        if self.loss_type == 'contrastive':
            # Concatenate all distances and labels
            all_distances = torch.cat([x['distances'] for x in self.validation_step_outputs])
            all_labels = torch.cat([x['labels'] for x in self.validation_step_outputs])
            
            # Calculate accuracy
            predictions = (all_distances < self.distance_threshold).float()
            accuracy = (predictions == all_labels).float().mean()
            
            # Calculate AUC
            try:
                auc = roc_auc_score(all_labels.numpy(), -all_distances.numpy())
            except:
                auc = 0.0
            
            # Log metrics
            self.log('val_accuracy', accuracy, prog_bar=True)
            self.log('val_auc', auc, prog_bar=True)
            self.log('val_mean_pos_distance', all_distances[all_labels == 1].mean())
            self.log('val_mean_neg_distance', all_distances[all_labels == 0].mean())
            
        elif self.loss_type == 'triplet':
            # Concatenate distances
            all_pos_distances = torch.cat([x['pos_distances'] for x in self.validation_step_outputs])
            all_neg_distances = torch.cat([x['neg_distances'] for x in self.validation_step_outputs])
            
            # Calculate accuracy (positive distances < threshold, negative distances > threshold)
            pos_correct = (all_pos_distances < self.distance_threshold).float().mean()
            neg_correct = (all_neg_distances > self.distance_threshold).float().mean()
            accuracy = (pos_correct + neg_correct) / 2
            
            self.log('val_accuracy', accuracy, prog_bar=True)
            self.log('val_mean_pos_distance', all_pos_distances.mean())
            self.log('val_mean_neg_distance', all_neg_distances.mean())
        
        # Clear outputs
        self.validation_step_outputs.clear()
    
    def configure_optimizers(self):
        """Configure optimizers and learning rate schedulers."""
        optimizer = torch.optim.Adam(
            self.parameters(),
            lr=self.learning_rate,
            weight_decay=self.weight_decay
        )
        
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer,
            mode='min',
            factor=0.5,
            patience=10,
            verbose=True
        )
        
        return {
            'optimizer': optimizer,
            'lr_scheduler': {
                'scheduler': scheduler,
                'monitor': 'val_loss',
                'frequency': 1
            }
        }
    
    def get_embedding(self, x: torch.Tensor) -> torch.Tensor:
        """Get embedding for a single input (useful for inference)."""
        return self(x)


class ContrastiveLoss(nn.Module):
    """Contrastive Loss for Siamese Networks."""
    
    def __init__(self, margin: float = 2.0):
        super(ContrastiveLoss, self).__init__()
        self.margin = margin

    def forward(self, embedding1: torch.Tensor, embedding2: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
        '''
        euclidean_distance = F.pairwise_distance(embedding1, embedding2, keepdim=True)

        loss_contrastive = torch.mean(
            labels * torch.pow(euclidean_distance, 2) +
            (1 - labels) * torch.pow(torch.clamp(self.margin - euclidean_distance, min=0.0), 2)
        )
        '''
        euclidean_distance = F.pairwise_distance(embedding1, embedding2)
        pos = (1-labels) * torch.pow(euclidean_distance, 2)
        neg = (labels) * torch.pow(torch.clamp(self.margin - euclidean_distance, min=0.0), 2)
        loss_contrastive = torch.mean( pos + neg )
        return loss_contrastive


class TripletLoss(nn.Module):
    """Triplet Loss for Siamese Networks."""
    
    def __init__(self, margin: float = 0.1):
        super(TripletLoss, self).__init__()
        self.margin = margin
    
    def forward(self, anchor: torch.Tensor, positive: torch.Tensor, negative: torch.Tensor) -> torch.Tensor:
        #positive_distance = F.pairwise_distance(anchor, positive, keepdim=True)
        #negative_distance = F.pairwise_distance(anchor, negative, keepdim=True)
        positive_distance = (anchor - positive).pow(2).sum(1)  # .pow(.5)
        negative_distance = (anchor - negative).pow(2).sum(1)  # .pow(.5)
        loss_triplet = torch.mean(
            torch.clamp(positive_distance - negative_distance + self.margin, min=0.0)
        )
        
        return loss_triplet


class ArcFaceLoss(nn.Module):
    """ArcFace Loss for enhanced discriminative learning."""
    
    def __init__(self, in_features: int, out_features: int, margin: float = 0.5, scale: float = 64.0):
        super(ArcFaceLoss, self).__init__()
        self.in_features = in_features
        self.out_features = out_features
        self.margin = margin
        self.scale = scale
        
        self.weight = nn.Parameter(torch.FloatTensor(out_features, in_features))
        nn.init.xavier_uniform_(self.weight)
        
        self.cos_m = math.cos(margin)
        self.sin_m = math.sin(margin)
        self.th = math.cos(math.pi - margin)
        self.mm = math.sin(math.pi - margin) * margin
    
    def forward(self, embeddings: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
        embeddings = F.normalize(embeddings, p=2, dim=1)
        weight = F.normalize(self.weight, p=2, dim=1)
        
        cosine = F.linear(embeddings, weight)
        sine = torch.sqrt(1.0 - torch.pow(cosine, 2))
        
        phi = cosine * self.cos_m - sine * self.sin_m
        phi = torch.where(cosine > self.th, phi, cosine - self.mm)
        
        one_hot = torch.zeros(cosine.size(), device=embeddings.device)
        one_hot.scatter_(1, labels.view(-1, 1).long(), 1)
        
        output = (one_hot * phi) + ((1.0 - one_hot) * cosine)
        output *= self.scale
        
        return F.cross_entropy(output, labels)


def create_callbacks(save_dir: str, monitor: str = 'val_loss', patience: int = 20):
    """Create standard callbacks for training."""
    callbacks = [
        # Model checkpointing
        ModelCheckpoint(
            dirpath=save_dir,
            filename='best-{epoch:02d}-{val_loss:.4f}',
            monitor=monitor,
            mode='min',
            save_top_k=1,
            save_last=True,
            verbose=True
        ),
        
        # Early stopping
        EarlyStopping(
            monitor=monitor,
            mode='min',
            patience=patience,
            verbose=True
        ),
        
        # Learning rate monitoring
        LearningRateMonitor(logging_interval='epoch')
    ]
    
    return callbacks


def create_logger(save_dir: str, name: str = 'siamese_network'):
    """Create TensorBoard logger."""
    logger = TensorBoardLogger(
        save_dir=save_dir,
        name=name,
        default_hp_metric=False
    )
    return logger


# Test the model
if __name__ == "__main__":
    # Test model creation
    print("Testing Siamese Lightning Module...")
    
    model = SiameseLightningModule(
        backbone='resnet18',
        embedding_dim=128,
        loss_type='contrastive',
        learning_rate=1e-3
    )
    
    print(f"Model created with {sum(p.numel() for p in model.parameters()):,} parameters")
    
    # Test forward pass
    batch_size = 4
    x1 = torch.randn(batch_size, 3, 224, 224)
    x2 = torch.randn(batch_size, 3, 224, 224)
    
    with torch.no_grad():
        # Test paired forward
        emb1, emb2 = model(x1, x2)
        print(f"Paired embedding shapes: {emb1.shape}, {emb2.shape}")
        
        # Test single forward
        single_emb = model(x1)
        print(f"Single embedding shape: {single_emb.shape}")
    
    # Test loss computation
    labels = torch.randint(0, 2, (batch_size,)).float()
    loss = model.criterion(emb1, emb2, labels)
    print(f"Contrastive loss: {loss.item():.4f}")
    
    print("All tests passed!")
