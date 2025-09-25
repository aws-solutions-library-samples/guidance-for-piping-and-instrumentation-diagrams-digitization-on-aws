import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
import numpy as np
import matplotlib.pyplot as plt
from tqdm import tqdm
import os
import json
from datetime import datetime
from typing import Dict, List, Tuple

from svg_triplet_dataset import SVGTripletDataset, create_dataloader
from siamese_model import SiameseNetwork, TripletLoss, create_siamese_model, compute_distance
from transforms import RandomLinesTransform
import albumentations as A
from statistics import mean

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

config = {
    'batch_size': 64,
    'backbone': 'resnet50',
    'embedding_dim': 128,
    'learning_rate': 1e-4,
    'margin': 1.0,
}

def save_checkpoint(filename, step, model, optimizer, loss):
    checkpoint = {
        'step': step,
        'model_state_dict': model.state_dict(),
        'optimizer_state_dict': optimizer.state_dict(),
        'loss': loss,
    }
    torch.save(checkpoint, f'{filename}_{step}.pth')

rotate = A.Rotate(limit=360)
flip = A.HorizontalFlip(p=0.5)
bright = A.RandomBrightnessContrast()
noise = A.GaussNoise()
downscale = A.Downscale(scale_range=(0.25, 1.0))
lines = RandomLinesTransform(p=0.5)

transforms = A.Compose([rotate, flip, bright, noise, downscale, lines])

dataset = SVGTripletDataset('./svgs/', image_size=(224, 224), transform=transforms)
dataset_size = len(dataset)

train_loader = DataLoader(
        dataset, 
        batch_size=config['batch_size'], 
        shuffle=True, 
        num_workers=0,
        pin_memory=torch.cuda.is_available()
    )

model = create_siamese_model(
        embedding_dim=config['embedding_dim'],
        backbone=config['backbone'],
        pretrained=True
    )

criterion = triplet_loss = nn.TripletMarginLoss(margin=config['margin'], p=2, eps=1e-7)
optimizer = optim.Adam(model.parameters(), lr=config['learning_rate'], weight_decay=1e-4)
scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=2500)

_ = model.to(device)

_ = model.train()
losses = []
num_batches = 0
epochs = 500

for epoch in range(epochs):
    for batch_idx, (anchors, positives, negatives) in enumerate(train_loader):
        anchors = anchors.to(device)
        positives = positives.to(device)
        negatives = negatives.to(device)
    
        optimizer.zero_grad()
        anchor_emb, positive_emb, negative_emb = model(anchors, positives, negatives)
        loss = criterion(anchor_emb, positive_emb, negative_emb)
    
        loss.backward()
        optimizer.step()
        scheduler.step()
    
        losses.append(float(loss.detach().cpu().numpy()))
        num_batches += 1
    print(f"Epoch: {epoch}, Loss: {mean(losses[-50:])}")

save_checkpoint('siamese_model', num_batches, model, optimizer, mean(losses[-50:]))
