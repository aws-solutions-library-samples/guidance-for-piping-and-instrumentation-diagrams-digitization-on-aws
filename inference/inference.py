import os
import subprocess
import sys
import logging
import json
import torch
import torchvision
from torchvision.models.detection.faster_rcnn import FastRCNNPredictor
import numpy as np
from PIL import Image
import io
import base64
from math import ceil
import itertools
import albumentations as A
import torch.nn.functional as F
from pathlib import Path
from siamese_lightning import SiameseLightningModule
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Optional

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
DEFAULT_TILE_SIZE = 1280


@dataclass
class TileInfo:
    """Information about a single tile"""

    x_offset: int
    y_offset: int
    width: int
    height: int
    tile_image: Image.Image


@dataclass
class Detection:
    """Detection result with original image coordinates"""

    class_id: int
    class_name: str
    confidence: float
    bbox: Dict[str, float]
    embedding_distance: float = 0.0


class TiledInference:
    """Optimized tiled inference for large images"""

    def __init__(
        self,
        rcnn_model,
        siamese_model,
        reference_embeddings,
        class_id_mapping,
        tile_size: int = DEFAULT_TILE_SIZE,
        overlap_ratio: float = 0.2,
    ):
        self.rcnn_model = rcnn_model
        self.siamese_model = siamese_model
        self.reference_embeddings = reference_embeddings
        self.class_id_mapping = class_id_mapping
        self.tile_size = tile_size
        self.overlap_ratio = overlap_ratio

    def needs_tiling(self, image_width: int, image_height: int) -> bool:
        """Check if image needs to be tiled"""
        return image_width > self.tile_size or image_height > self.tile_size

    def generate_tiles(self, image: np.ndarray) -> List[TileInfo]:
        """Generate image tiles with overlap"""
        height, width = image.shape[:2]

        if not self.needs_tiling(width, height):
            pil_image = Image.fromarray((image * 255).astype(np.uint8))
            return [TileInfo(0, 0, width, height, pil_image)]

        # Calculate overlap in pixels
        overlap_pixels = int(self.tile_size * self.overlap_ratio)
        effective_tile_size = self.tile_size - overlap_pixels

        tiles = []
        y = 0
        while y < height:
            x = 0
            while x < width:
                # Calculate actual tile dimensions
                actual_width = min(self.tile_size, width - x)
                actual_height = min(self.tile_size, height - y)

                # Extract tile
                tile_array = image[y : y + actual_height, x : x + actual_width]
                tile_image = Image.fromarray((tile_array * 255).astype(np.uint8))

                tiles.append(TileInfo(x, y, actual_width, actual_height, tile_image))

                # Move to next column
                if x + actual_width >= width:
                    break
                x += effective_tile_size

            # Move to next row
            if y + actual_height >= height:
                break
            y += effective_tile_size

        logger.info(f"Generated {len(tiles)} tiles for {width}x{height} image")
        return tiles

    def process_tiles(
        self, tiles: List[TileInfo], score_threshold: float, n_closest: int
    ) -> List[Detection]:
        """Process tiles and return detections"""
        all_detections = []

        for tile in tiles:
            # Convert PIL image back to numpy for processing
            tile_array = np.array(tile.tile_image).astype(np.float32) / 255.0

            # Get RCNN detections for this tile
            tile_detections = self._get_tile_detections(
                tile_array, tile, score_threshold, n_closest
            )
            all_detections.extend(tile_detections)

        return all_detections

    def _get_tile_detections(
        self,
        tile_array: np.ndarray,
        tile_info: TileInfo,
        score_threshold: float,
        n_closest: int,
    ) -> List[Detection]:
        """Get detections for a single tile"""
        # Prepare tensor for RCNN
        tile_tensor = torch.tensor(tile_array).transpose(2, 0).to(DEVICE)
        images = [tile_tensor]

        with torch.no_grad():
            output = self.rcnn_model(images)[0]

        detections = []
        for box, score in zip(output["boxes"], output["scores"]):
            if score > score_threshold:
                # Convert box coordinates to original image space
                box_cpu = box.cpu().numpy()
                original_box = [
                    box_cpu[0] + tile_info.y_offset,  # y1
                    box_cpu[1] + tile_info.x_offset,  # x1
                    box_cpu[2] + tile_info.y_offset,  # y2
                    box_cpu[3] + tile_info.x_offset,  # x2
                ]

                # Get symbol embedding and classification
                symbol_embedding = get_single_symbol_embedding(
                    tile_array, box_cpu, 224, self.siamese_model
                )
                closest_n = get_n_closest_embeddings_from_symbol(
                    self.reference_embeddings, symbol_embedding, n_closest
                )

                # Get the closest class
                closest_class_name = closest_n[0][0] if closest_n else "unknown"
                closest_distance = float(closest_n[0][1]) if closest_n else 1.0
                class_id = self.class_id_mapping.get(closest_class_name, 0)
                class_name = closest_class_name.replace(".png", "")

                detections.append(
                    Detection(
                        class_id=class_id,
                        class_name=class_name,
                        confidence=float(score),
                        bbox={
                            "x1": float(original_box[1]),
                            "y1": float(original_box[0]),
                            "x2": float(original_box[3]),
                            "y2": float(original_box[2]),
                            "width": float(original_box[3] - original_box[1]),
                            "height": float(original_box[2] - original_box[0]),
                        },
                        embedding_distance=closest_distance,
                    )
                )

        return detections


def model_fn(model_dir):
    """Load both RCNN and Siamese models"""
    logger.info(f"Loading models from {model_dir}")
    logger.info(f"Directory contents: {os.listdir(model_dir)}")
    try:
        result = subprocess.run(["pip", "list"], capture_output=True, text=True)
        logger.info(f"Installed packages: {result.stdout}")
    except Exception as e:
        logger.error(f"Failed to list packages: {e}")

    # Check if files are in subdirectories
    for root, dirs, files in os.walk(model_dir):
        logger.info(f"Found in {root}: {files}")

    try:
        rcnn_path = os.path.join(model_dir, "frcnn_checkpoint_50000.pth")
        # Load checkpoint
        checkpoint = torch.load(rcnn_path, map_location=DEVICE)
        NUM_CLASSES = 2
        # Create the model architecture (you need to know what model was used)
        from torchvision.models.detection import fasterrcnn_resnet50_fpn

        rcnn_model = fasterrcnn_resnet50_fpn(pretrained=False, num_classes=NUM_CLASSES)

        # Load the weights from checkpoint
        if "model_state_dict" in checkpoint:
            rcnn_model.load_state_dict(checkpoint["model_state_dict"])
        elif "state_dict" in checkpoint:
            rcnn_model.load_state_dict(checkpoint["state_dict"])
        else:
            # Handle other possible keys
            logger.error(f"Unknown checkpoint format: {checkpoint.keys()}")

        # Now you can use the model
        rcnn_model.eval().to(DEVICE)

        # Load Siamese model
        siamese_path = os.path.join(model_dir, "last-v9.ckpt")
        logger.info(f"Loading Siamese model from {siamese_path}")
        siamese_model = SiameseLightningModule.load_from_checkpoint(
            siamese_path, map_location=DEVICE
        )
        siamese_model.eval().to(DEVICE)

        # Load reference embeddings (if they exist)
        reference_embeddings = {}
        references_dir = Path(model_dir) / "references"
        if references_dir.exists():
            logger.info(f"Loading reference embeddings from {references_dir}")
            reference_embeddings, class_id_mapping = get_reference_embeddings(
                references_dir, siamese_model
            )
        else:
            logger.warning("No reference embeddings directory found")
            reference_embeddings, class_id_mapping = {}, {}

        return {
            "rcnn": rcnn_model,
            "siamese": siamese_model,
            "reference_embeddings": reference_embeddings,
            "class_id_mapping": class_id_mapping,
        }
    except Exception as e:
        logger.error(f"Model loading failed: {e}")
        raise


def make_grid(image, patch_size=1280):
    """Generate grid positions for tiled inference"""
    height, width = image.shape[0:2]
    width_segs = ceil(width / (patch_size / 2))
    width_step_size = width // width_segs
    width_pos = np.arange(0, width - patch_size // 2, step=width_step_size)
    height_segs = ceil(height / (patch_size / 2))
    height_step_size = height // height_segs
    height_pos = np.arange(0, height - patch_size // 2, step=height_step_size)

    grid = list(itertools.product(height_pos, width_pos))
    return grid


def get_crop_predictions(image, grid, model, patch_size=1280):
    """Get predictions from image crops"""
    model.eval()
    detections = []

    for pos in grid:
        if image.dtype == np.uint8:
            image = image.astype("float32") / 255.0

        cropped_image = A.Compose(
            [
                A.Crop(
                    x_min=pos[1],
                    y_min=pos[0],
                    x_max=pos[1] + patch_size,
                    y_max=pos[0] + patch_size,
                    pad_if_needed=True,
                    fill=255,
                )
            ]
        )(image=image)["image"]

        cropped_image_tensor = torch.tensor(cropped_image).transpose(2, 0)
        images = [cropped_image_tensor.to(DEVICE)]

        with torch.no_grad():
            output = model(images)[0]

        output = {i: j.detach().cpu().numpy() for i, j in output.items()}
        output["boxes"][:, 0] = np.round(output["boxes"][:, 0] + pos[0])
        output["boxes"][:, 1] = np.round(output["boxes"][:, 1] + pos[1])
        output["boxes"][:, 2] = np.round(output["boxes"][:, 2] + pos[0])
        output["boxes"][:, 3] = np.round(output["boxes"][:, 3] + pos[1])
        detections.append(output)

    boxes = np.concatenate([i["boxes"] for i in detections])
    scores = np.concatenate([i["scores"] for i in detections])
    return {"boxes": boxes, "scores": scores}


def get_reference_embeddings(output_dir, siamese_model):
    """Get embeddings for reference symbols"""
    siamese_model.eval()
    references_image_paths = list(output_dir.glob("*.png"))
    references_embeddings = {}
    class_id_mapping = {}  # Map class names to indices

    for i, path in enumerate(references_image_paths):
        img = Image.open(path).convert("RGB")
        img_array = np.array(img).astype(np.float32) / 255.0
        img_tensor = torch.tensor(img_array).transpose(2, 0).unsqueeze(0).to(DEVICE)

        with torch.no_grad():
            embedding = siamese_model.forward_once(img_tensor).detach().cpu().clone()
        logger.info(
            f"Reference {i}: {path.name} -> embedding sum: {embedding.sum().item()}"
        )
        print(f"Reference {i}: {path.name} -> embedding sum: {embedding.sum().item()}")

        references_embeddings[path.name] = embedding
        class_id_mapping[path.name] = i  # Store index as class_id

    return references_embeddings, class_id_mapping


def get_single_symbol_embedding(image, detection, target_size, siamese_model):
    """Get embedding for a single detected symbol"""
    crop = A.Crop(
        x_min=int(detection[1]),
        y_min=int(detection[0]),
        x_max=int(detection[3]),
        y_max=int(detection[2]),
        pad_if_needed=True,
        fill=255,
    )
    resize = A.LongestMaxSize(target_size, pad_if_needed=True)
    pad = A.PadIfNeeded(
        min_height=target_size,
        min_width=target_size,
        border_mode=0,
        fill=(1.0, 1.0, 1.0),
    )

    single_symbol = A.Compose([crop, resize, pad])(image=image)["image"]

    if single_symbol.dtype == np.uint8:
        single_symbol = single_symbol.astype(np.float32) / 255.0

    tensor_symbol = torch.tensor(single_symbol, dtype=torch.float32).transpose(2, 0)
    tensor_symbol = tensor_symbol.unsqueeze(dim=0).to(DEVICE)

    # Ensure model is in eval mode
    siamese_model.eval()

    # Clear any cached gradients and reset model state
    siamese_model.zero_grad()
    torch.cuda.empty_cache() if torch.cuda.is_available() else None

    with torch.no_grad():
        symbol_embedding = (
            siamese_model.forward_once(tensor_symbol).detach().cpu().clone()
        )

    return symbol_embedding


def get_n_closest_embeddings_from_symbol(references_embeddings, symbol_embedding, n):
    """Find n closest reference symbols"""
    reference_distances = {}
    for ref, emb in references_embeddings.items():
        reference_distances[ref] = F.pairwise_distance(
            symbol_embedding[0], emb[0]
        ).numpy()

    sorted_items = sorted(reference_distances.items(), key=lambda item: item[1])
    closest_n = list(sorted_items)[:n]
    return closest_n


def input_fn(request_body, content_type="application/json"):
    """Parse input data"""
    if content_type == "application/json":
        input_data = json.loads(request_body)

        image_data = base64.b64decode(input_data["image"])
        image = Image.open(io.BytesIO(image_data)).convert("RGB")
        return {
            "image": np.array(image),
            "score_threshold": input_data.get("score_threshold", 0.9),
            "n_closest": input_data.get("n_closest", 3),
        }

    raise ValueError(f"Unsupported content type: {content_type}")


def calculate_iou(bbox1, bbox2):
    """Calculate Intersection over Union (IoU)"""
    x1 = max(bbox1["x1"], bbox2["x1"])
    y1 = max(bbox1["y1"], bbox2["y1"])
    x2 = min(bbox1["x2"], bbox2["x2"])
    y2 = min(bbox1["y2"], bbox2["y2"])

    if x2 <= x1 or y2 <= y1:
        return 0.0

    intersection = (x2 - x1) * (y2 - y1)
    area1 = (bbox1["x2"] - bbox1["x1"]) * (bbox1["y2"] - bbox1["y1"])
    area2 = (bbox2["x2"] - bbox2["x1"]) * (bbox2["y2"] - bbox2["y1"])
    union = area1 + area2 - intersection

    return intersection / union if union > 0 else 0.0


def remove_duplicates(detections, iou_threshold=0.3):
    """Remove duplicate detections using class-agnostic NMS"""
    if not detections:
        return []

    # Sort by confidence (descending)
    sorted_detections = sorted(detections, key=lambda x: x["confidence"], reverse=True)

    keep = []
    while sorted_detections:
        current = sorted_detections.pop(0)
        keep.append(current)

        # Remove overlapping detections
        remaining = []
        for detection in sorted_detections:
            iou = calculate_iou(current["bbox"], detection["bbox"])
            if iou < iou_threshold:
                remaining.append(detection)

        sorted_detections = remaining

    logger.info(f"Deduplication: {len(detections)} -> {len(keep)} detections")
    return keep


def predict_fn(input_data, models):
    """Run inference pipeline using TiledInference"""
    image = input_data["image"]
    score_threshold = input_data["score_threshold"]
    n_closest = input_data["n_closest"]

    rcnn_model = models["rcnn"]
    siamese_model = models["siamese"]
    reference_embeddings = models["reference_embeddings"]
    class_id_mapping = models["class_id_mapping"]

    # Return empty if models not loaded
    if rcnn_model is None:
        return {
            "detections": [],
            "num_detections": 0,
            "message": "No RCNN model loaded",
        }

    # Convert image to float32 if needed
    if image.dtype == np.uint8:
        image = image.astype("float32") / 255.0

    # Create tiled inference processor
    tiled_processor = TiledInference(
        rcnn_model=rcnn_model,
        siamese_model=siamese_model,
        reference_embeddings=reference_embeddings,
        class_id_mapping=class_id_mapping,
        tile_size=DEFAULT_TILE_SIZE,
        overlap_ratio=0.2,
    )

    # Generate tiles and process
    tiles = tiled_processor.generate_tiles(image)
    all_detections = tiled_processor.process_tiles(tiles, score_threshold, n_closest)

    # Convert Detection objects to dict format
    detection_list = []
    for det in all_detections:
        detection_list.append(
            {
                "class_id": det.class_id,
                "class_name": det.class_name,
                "confidence": det.confidence,
                "bbox": det.bbox,
                "embedding_distance": det.embedding_distance,
            }
        )

    # Remove duplicates
    detection_list = remove_duplicates(detection_list, iou_threshold=0.3)
    return {"detections": detection_list}


def output_fn(prediction, content_type="application/json"):
    """Format output"""
    if content_type == "application/json":
        return json.dumps(prediction)

    raise ValueError(f"Unsupported content type: {content_type}")
