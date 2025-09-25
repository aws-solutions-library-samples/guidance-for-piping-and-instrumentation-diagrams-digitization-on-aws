from pid2graph_utils.dataset import PIDGraphDataset, SyntheticPIDDataset, MixedIterableDataset
from pid2graph_utils.transforms import (RandomCropWithBBoxes, 
                                        ToTensorWithTargets, 
                                        ComposeWithTargets, 
                                        XYXYToYXYX,
                                        RandomRotationWithProbability,
                                        RandomFlip,
                                        RandomLineNoise,
                                        RandomGaussianBlobs,
                                        FlattenLabels)
from pid2graph_utils.utils import draw_boxes_torch, draw_boxes, save_checkpoint

from torchvision.models.detection.faster_rcnn import FastRCNNPredictor
import torchvision
import torch.optim as optim
from torch.utils.data import DataLoader
import torch
from torchvision.transforms.v2 import ConvertBoundingBoxFormat

import matplotlib.pyplot as plt
import matplotlib.patches as patches

from tqdm import tqdm
from statistics import mean

import warnings

from pathlib import Path

# Ignore all warnings globally
warnings.filterwarnings("ignore")

open_100_data_dir = './data/PID2Graph/Complete/PID2Graph OPEN100/'
PID_data_dir = './data/PID2Graph/Complete/Dataset PID'
pid2_graph_synthetic_data_dir = './data/PID2Graph/Complete/PID2Graph Synthetic'
synthetic_data_dir = './data/output'

labels = ['arrow',
 'general',
 'inlet/outlet',
 'instrumentation',
 'pump',
 'tank',
 'valve',]

rcwb = RandomCropWithBBoxes(size=1280, pad_if_needed=True, fill=255)
flatten = FlattenLabels()
rotate = RandomRotationWithProbability([0, 90, 180, 270], [0.25, 0.25, 0.25, 0.25])
flip = RandomFlip(flip_type='both') 
lines = RandomLineNoise(length_range=(5,50), thickness_range=(1,1), density=0.0002)
blobs = RandomGaussianBlobs(blob_count_range=(5, 25), size_range=(5, 100), 
                            intensity_range=(5.0, 25.0), p=0.5)
to_tensor = ToTensorWithTargets(imagenet_normalize=False)
transforms = ComposeWithTargets([rcwb, flatten, rotate, flip, lines, blobs, to_tensor])

open_100_ds = PIDGraphDataset(data_dir=open_100_data_dir, labels=labels, transforms=transforms)
pid_ds = PIDGraphDataset(data_dir=PID_data_dir, labels=labels, transforms=transforms)
pid2_graph_synthetic_ds = PIDGraphDataset(data_dir=pid2_graph_synthetic_data_dir, labels=labels, 
                                          image_ext='.jpg', transforms=transforms)
synthetic_ds = SyntheticPIDDataset(data_dir=synthetic_data_dir, transforms=transforms)

interleaved_dataset = MixedIterableDataset([open_100_ds, pid_ds, pid2_graph_synthetic_ds, synthetic_ds], [.25, .05, .05, .65])

def tuple_collater(batch): 
    return tuple(zip(*batch))

pid_dataloader = DataLoader(interleaved_dataset, 
                            batch_size=8,
                            collate_fn=tuple_collater, 
                            num_workers=8,
                            prefetch_factor=8,
                            )

pid_dataloader_iterable = iter(pid_dataloader)

model = torchvision.models.detection.fasterrcnn_resnet50_fpn(pretrained=True, pretrained_backbone=True)

num_classes = 2
in_features = model.roi_heads.box_predictor.cls_score.in_features
model.roi_heads.box_predictor = FastRCNNPredictor(in_features, num_classes)

total_steps = 50000
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
optimizer = optim.AdamW(model.parameters(), lr = 1e-6, weight_decay=1e-3)
scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, total_steps)

model.to(device)
_ = model.train()

itr = 1
total_loss = []
pbar = tqdm(pid_dataloader, total=total_steps)
for images, targets in pbar:
    images = list(image.to(device) for image, target in zip(images, targets) if len(target['boxes'])>0)
    targets = [{k: torch.tensor(v).to(device) for k, v in t.items() if  k in ['boxes', 'labels']} for t in targets if len(t['boxes'])>0]
    loss_dict = model(images, targets)   ##Return the loss
    losses = sum(loss for loss in loss_dict.values())
    total_loss.append(float(losses.cpu().detach().numpy()))
    optimizer.zero_grad()
    losses.backward()
    optimizer.step()
    scheduler.step()
    pbar.set_description("Loss: {0:.5f}".format(mean(total_loss[-50:])))
    itr += 1
    if itr%10000==0:
        print("Saving Checkpoint")
        save_checkpoint('frcnn_checkpoint', itr, model, optimizer, losses)
