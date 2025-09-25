import json
import boto3
import io
import logging
from typing import List, Dict
import numpy as np
from PIL import Image
import cv2
from line_detection import BoundingBox

# Set up logging
logger = logging.getLogger()

# Initialize AWS clients
s3_client = boto3.client("s3")


def download_image_from_s3(bucket: str, key: str) -> np.ndarray:
    """Download image from S3 and convert to OpenCV format."""

    print(f"Downloading image from s3://{bucket}/{key}")

    # Download image
    response = s3_client.get_object(Bucket=bucket, Key=key)
    image_data = response["Body"].read()

    # Convert to PIL Image
    pil_image = Image.open(io.BytesIO(image_data))

    # Convert to RGB if needed
    if pil_image.mode != "RGB":
        pil_image = pil_image.convert("RGB")

    # Convert to OpenCV format (BGR)
    opencv_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)

    return opencv_image


def convert_bounding_boxes(
    bounding_boxes: List[Dict], image_width: int, image_height: int
) -> List[BoundingBox]:
    """Convert symbol detection bounding boxes to BoundingBox objects.

    Assumes bounding boxes are already in pixel coordinates from symbol detection.
    """

    converted_boxes = []

    for box in bounding_boxes:
        # Handle different possible formats from SageMaker
        if "bbox" in box:
            bbox = box["bbox"]
            # Symbol detection output: {x1, y1, x2, y2, width, height} in pixels
            top_x = int(bbox.get("x1", 0))
            top_y = int(bbox.get("y1", 0))
            bottom_x = int(bbox.get("x2", 0))
            bottom_y = int(bbox.get("y2", 0))

        else:
            print(f"Unknown bounding box format: {box}")
            continue

        # Add padding to ensure complete clearing (2 pixels on each side)
        padding = 2
        top_x = max(0, top_x - padding)
        top_y = max(0, top_y - padding)
        bottom_x = min(image_width, bottom_x + padding)
        bottom_y = min(image_height, bottom_y + padding)

        converted_boxes.append(BoundingBox(top_x, top_y, bottom_x, bottom_y))

        if len(converted_boxes) <= 5:  # Log first few for debugging
            print(
                f"Converted symbol box: ({top_x}, {top_y}) - ({bottom_x}, {bottom_y})"
            )

    return converted_boxes


def convert_bda_text_elements(
    text_elements: List[Dict], image_width: int, image_height: int
) -> List[BoundingBox]:
    """Convert BDA text elements to BoundingBox objects.

    Expects text elements with bounding boxes already in pixel coordinates from OCR lambda.
    """

    converted_boxes = []

    for element in text_elements:
        # New format from OCR lambda: bounding_box with x, y, width, height in pixels
        if "bounding_box" in element:
            bbox = element.get("bounding_box", {})

            # OCR lambda now provides pixel coordinates
            x = bbox.get("x", 0)
            y = bbox.get("y", 0)
            width = bbox.get("width", 0)
            height = bbox.get("height", 0)

            top_x = int(x)
            top_y = int(y)
            bottom_x = int(x + width)
            bottom_y = int(y + height)

        # Legacy format: Handle BDA format with locations array (normalized coordinates)
        elif "locations" in element:
            locations = element.get("locations", [])
            if locations and len(locations) > 0:
                # Get the first location
                location = locations[0]
                bbox = location.get("bounding_box", {})

                # Legacy BDA format provides normalized coordinates (0-1)
                left = bbox.get("left", 0)
                top = bbox.get("top", 0)
                width = bbox.get("width", 0)
                height = bbox.get("height", 0)

                # Convert to pixel coordinates
                top_x = int(left * image_width)
                top_y = int(top * image_height)
                bottom_x = int((left + width) * image_width)
                bottom_y = int((top + height) * image_height)
            else:
                continue
        else:
            # Skip elements without valid bounding box data
            continue

        # Add padding to ensure complete clearing (2 pixels on each side)
        padding = 2
        top_x = max(0, top_x - padding)
        top_y = max(0, top_y - padding)
        bottom_x = min(image_width, bottom_x + padding)
        bottom_y = min(image_height, bottom_y + padding)

        converted_boxes.append(BoundingBox(top_x, top_y, bottom_x, bottom_y))

        if len(converted_boxes) <= 5:  # Log first few for debugging
            print(f"Converted text box: ({top_x}, {top_y}) - ({bottom_x}, {bottom_y})")

    return converted_boxes
