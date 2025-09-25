import json
import boto3
import io
import logging
from typing import List, Dict
import numpy as np
from PIL import Image
import cv2
from line_detection import BoundingBox, LineSegment

# Set up logging
logger = logging.getLogger()

# Initialize AWS clients
s3_client = boto3.client("s3")


def save_debug_image(
    path_manager,
    image: np.ndarray,
    line_segments: List[LineSegment],
    symbol_boxes: List[BoundingBox],
    text_boxes: List[BoundingBox],
) -> None:
    """Save debug image with detected lines and bounding boxes to S3."""

    try:
        # Create debug image
        debug_image = image.copy()
        image_height, image_width = debug_image.shape[:2]

        # Draw symbol bounding boxes in red
        for box in symbol_boxes:
            cv2.rectangle(
                debug_image,
                (int(box.topX), int(box.topY)),
                (int(box.bottomX), int(box.bottomY)),
                (0, 0, 255),
                2,
            )

        # Draw text bounding boxes in blue
        for box in text_boxes:
            cv2.rectangle(
                debug_image,
                (box.topX, box.topY),
                (box.bottomX, box.bottomY),
                (255, 0, 0),
                2,
            )

        # Draw detected lines in green
        for line in line_segments:
            start_x = int(line.startX * image_width)
            start_y = int(line.startY * image_height)
            end_x = int(line.endX * image_width)
            end_y = int(line.endY * image_height)
            cv2.line(debug_image, (start_x, start_y), (end_x, end_y), (0, 255, 0), 2)

        # Convert to PIL and save to S3
        debug_pil = Image.fromarray(cv2.cvtColor(debug_image, cv2.COLOR_BGR2RGB))

        # Create debug key using ExecutionPathManager
        debug_key = f"{path_manager.get_line_detection_path()}/debug/11_final_processed.jpg"

        # Save to buffer
        buffer = io.BytesIO()
        debug_pil.save(buffer, format="JPEG", quality=85)
        buffer.seek(0)

        # Upload to S3
        s3_client.put_object(
            Bucket=path_manager.output_bucket,
            Key=debug_key,
            Body=buffer.getvalue(),
            ContentType="image/jpeg",
        )

        print(f"Debug image saved to s3://{path_manager.output_bucket}/{debug_key}")

    except Exception as e:
        print(f"Failed to save debug image: {str(e)}")


def save_preprocessed_image(path_manager, preprocessed_image: np.ndarray) -> None:
    """Save preprocessed image to S3 for debugging."""

    try:
        # Convert preprocessed binary image to RGB for saving
        # Binary image is 0 (black) and 255 (white), so we can save it directly
        debug_pil = Image.fromarray(preprocessed_image)

        # Use ExecutionPathManager for clean debug paths
        debug_key = f"{path_manager.get_line_detection_path()}/debug/06_after_thinning.png"

        # Save to buffer
        buffer = io.BytesIO()
        debug_pil.save(buffer, format="PNG")
        buffer.seek(0)

        # Upload to S3
        s3_client.put_object(
            Bucket=path_manager.output_bucket,
            Key=debug_key,
            Body=buffer.getvalue(),
            ContentType="image/png",
        )

        print(f"Preprocessed image saved to s3://{path_manager.output_bucket}/{debug_key}")

    except Exception as e:
        print(f"Failed to save preprocessed image: {str(e)}")


def save_raw_hough_lines_image(
    path_manager,
    original_image: np.ndarray,
    hough_results,
    image_width: int,
    image_height: int,
) -> None:
    """Save raw Hough lines debug image to S3."""

    try:
        # Create debug image with raw Hough lines
        debug_image = original_image.copy()

        # Draw raw lines in red
        for line in hough_results:
            x1, y1, x2, y2 = line[0]
            cv2.line(debug_image, (x1, y1), (x2, y2), (0, 0, 255), 2)  # Red lines

        # Convert to PIL and save to S3
        debug_pil = Image.fromarray(cv2.cvtColor(debug_image, cv2.COLOR_BGR2RGB))

        # Use ExecutionPathManager for clean debug paths
        debug_key = f"{path_manager.get_line_detection_path()}/debug/06a_raw_hough_lines.jpg"

        # Save to buffer
        buffer = io.BytesIO()
        debug_pil.save(buffer, format="JPEG", quality=85)
        buffer.seek(0)

        # Upload to S3
        s3_client.put_object(
            Bucket=path_manager.output_bucket,
            Key=debug_key,
            Body=buffer.getvalue(),
            ContentType="image/jpeg",
        )

        print(f"Raw Hough lines image saved to s3://{path_manager.output_bucket}/{debug_key}")

    except Exception as e:
        print(f"Failed to save raw Hough lines image: {str(e)}")


def save_before_thinning_image(path_manager, before_thinning_image: np.ndarray) -> None:
    """Save before-thinning debug image to S3."""

    try:
        # Convert binary image for saving
        debug_pil = Image.fromarray(before_thinning_image)

        # Use ExecutionPathManager for clean debug paths
        debug_key = f"{path_manager.get_line_detection_path()}/debug/05_before_thinning.png"

        # Save to buffer
        buffer = io.BytesIO()
        debug_pil.save(buffer, format="PNG")
        buffer.seek(0)

        # Upload to S3
        s3_client.put_object(
            Bucket=path_manager.output_bucket,
            Key=debug_key,
            Body=buffer.getvalue(),
            ContentType="image/png",
        )

        print(f"Before-thinning image saved to s3://{path_manager.output_bucket}/{debug_key}")

    except Exception as e:
        print(f"Failed to save before-thinning image: {str(e)}")


def save_raw_hough_lines_binary_image(
    path_manager,
    binary_image: np.ndarray,
    hough_results,
    image_width: int,
    image_height: int,
) -> None:
    """Save raw Hough lines overlaid on binary preprocessed image to S3."""

    try:
        # Convert binary image to 3-channel for drawing colored lines
        # Binary image is single channel (0 or 255), convert to BGR
        if len(binary_image.shape) == 2:
            debug_image = cv2.cvtColor(binary_image, cv2.COLOR_GRAY2BGR)
        else:
            debug_image = binary_image.copy()

        # Draw raw lines in red on the binary image
        for line in hough_results:
            x1, y1, x2, y2 = line[0]
            cv2.line(debug_image, (x1, y1), (x2, y2), (0, 0, 255), 2)  # Red lines

        # Convert to PIL and save to S3
        debug_pil = Image.fromarray(cv2.cvtColor(debug_image, cv2.COLOR_BGR2RGB))

        # Use ExecutionPathManager for clean debug paths
        debug_key = f"{path_manager.get_line_detection_path()}/debug/06b_raw_hough_lines_binary.jpg"

        # Save to buffer
        buffer = io.BytesIO()
        debug_pil.save(buffer, format="JPEG", quality=85)
        buffer.seek(0)

        # Upload to S3
        s3_client.put_object(
            Bucket=path_manager.output_bucket,
            Key=debug_key,
            Body=buffer.getvalue(),
            ContentType="image/jpeg",
        )

        print(f"Raw Hough lines on binary image saved to s3://{path_manager.output_bucket}/{debug_key}")

    except Exception as e:
        print(f"Failed to save raw Hough lines binary image: {str(e)}")


def save_raw_hough_lines_json(
    path_manager,
    hough_results,
    image_width: int,
    image_height: int,
    hough_params: dict,
) -> None:
    """Save raw Hough lines data as sorted JSON to S3."""

    try:
        # Extract and sort raw lines from top-left to bottom-right by start point
        lines_data = []
        for line in hough_results:
            x1, y1, x2, y2 = line[0]
            lines_data.append(
                {"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2)}
            )

        # Sort lines by start point: Y coordinate first (top to bottom), then X coordinate (left to right)
        sorted_lines = sorted(lines_data, key=lambda line: (line["y1"], line["x1"]))

        # Add index to each line
        for i, line in enumerate(sorted_lines):
            line["index"] = i

        # Create JSON data structure
        json_data = {
            "metadata": {
                "image_width": image_width,
                "image_height": image_height,
                "total_raw_lines": len(sorted_lines),
                "sorting_method": "top_left_to_bottom_right_by_start_point",
                "hough_parameters": hough_params,
            },
            "raw_lines": sorted_lines,
        }

        # Use ExecutionPathManager for clean debug paths
        debug_key = f"{path_manager.get_line_detection_path()}/debug/06d_raw_hough_lines.json"

        # Convert to JSON and upload to S3
        json_str = json.dumps(json_data, indent=2)

        s3_client.put_object(
            Bucket=path_manager.output_bucket,
            Key=debug_key,
            Body=json_str.encode("utf-8"),
            ContentType="application/json",
        )

        print(
            f"Raw Hough lines JSON saved to s3://{path_manager.output_bucket}/{debug_key} ({len(sorted_lines)} lines)"
        )

    except Exception as e:
        print(f"Failed to save raw Hough lines JSON: {str(e)}")


def save_raw_hough_lines_indexed_image(
    path_manager,
    original_image: np.ndarray,
    hough_results,
    image_width: int,
    image_height: int,
) -> None:
    """Save raw Hough lines with index numbers overlaid on original image to S3."""

    try:
        # Create debug image with raw Hough lines
        debug_image = original_image.copy()

        # Extract and sort raw lines from top-left to bottom-right by start point (same as JSON)
        lines_data = []
        for line in hough_results:
            x1, y1, x2, y2 = line[0]
            lines_data.append(
                {"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2)}
            )

        # Sort lines by start point: Y coordinate first (top to bottom), then X coordinate (left to right)
        sorted_lines = sorted(lines_data, key=lambda line: (line["y1"], line["x1"]))

        # Calculate font scale based on image size for readability
        font_scale = max(0.4, min(1.2, image_width / 2000.0))
        thickness = max(1, int(font_scale * 2))

        # Draw sorted lines with index numbers
        for i, line_data in enumerate(sorted_lines):
            x1, y1, x2, y2 = (
                line_data["x1"],
                line_data["y1"],
                line_data["x2"],
                line_data["y2"],
            )

            # Draw the line in red
            cv2.line(debug_image, (x1, y1), (x2, y2), (0, 0, 255), 2)

            # Calculate midpoint for text placement
            mid_x = int((x1 + x2) / 2)
            mid_y = int((y1 + y2) / 2)

            # Draw index number with black outline for visibility
            text = str(i)

            # Get text size for positioning
            (text_width, text_height), baseline = cv2.getTextSize(
                text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness
            )

            # Adjust text position to center it
            text_x = mid_x - text_width // 2
            text_y = mid_y + text_height // 2

            # Draw black outline (shadow effect)
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx != 0 or dy != 0:
                        cv2.putText(
                            debug_image,
                            text,
                            (text_x + dx, text_y + dy),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            font_scale,
                            (0, 0, 0),
                            thickness + 1,
                        )

            # Draw white text on top
            cv2.putText(
                debug_image,
                text,
                (text_x, text_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                font_scale,
                (255, 255, 255),
                thickness,
            )

        # Convert to PIL and save to S3
        debug_pil = Image.fromarray(cv2.cvtColor(debug_image, cv2.COLOR_BGR2RGB))

        # Use ExecutionPathManager for clean debug paths
        debug_key = f"{path_manager.get_line_detection_path()}/debug/06c_raw_hough_lines_indexed.jpg"

        # Save to buffer
        buffer = io.BytesIO()
        debug_pil.save(buffer, format="JPEG", quality=85)
        buffer.seek(0)

        # Upload to S3
        s3_client.put_object(
            Bucket=path_manager.output_bucket,
            Key=debug_key,
            Body=buffer.getvalue(),
            ContentType="image/jpeg",
        )

        print(
            f"Indexed raw Hough lines image saved to s3://{path_manager.output_bucket}/{debug_key} ({len(sorted_lines)} lines)"
        )

    except Exception as e:
        print(f"Failed to save indexed raw Hough lines image: {str(e)}")


def save_original_with_bounding_boxes(
    path_manager,
    original_key: str,
    image: np.ndarray,
    symbol_boxes: List[BoundingBox],
    text_boxes: List[BoundingBox],
) -> None:
    """Save original image with all bounding boxes overlaid for debugging."""

    try:
        debug_image = image.copy()

        # Draw symbol bounding boxes in red
        for box in symbol_boxes:
            cv2.rectangle(
                debug_image,
                (int(box.topX), int(box.topY)),
                (int(box.bottomX), int(box.bottomY)),
                (0, 0, 255),
                2,
            )
            # Add label
            cv2.putText(
                debug_image,
                "S",
                (int(box.topX), int(box.topY) - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 0, 255),
                2,
            )

        # Draw text bounding boxes in blue
        for box in text_boxes:
            cv2.rectangle(
                debug_image,
                (int(box.topX), int(box.topY)),
                (int(box.bottomX), int(box.bottomY)),
                (255, 0, 0),
                2,
            )
            # Add label
            cv2.putText(
                debug_image,
                "T",
                (int(box.topX), int(box.topY) - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 0, 0),
                2,
            )

        # Convert to PIL and save
        debug_pil = Image.fromarray(cv2.cvtColor(debug_image, cv2.COLOR_BGR2RGB))

        # Use ExecutionPathManager for clean debug paths
        debug_key = f"{path_manager.get_line_detection_path()}/debug/00_original_with_boxes.jpg"

        buffer = io.BytesIO()
        debug_pil.save(buffer, format="JPEG", quality=85)
        buffer.seek(0)

        s3_client.put_object(
            Bucket=path_manager.output_bucket,
            Key=debug_key,
            Body=buffer.getvalue(),
            ContentType="image/jpeg",
        )

        print(f"Original with bounding boxes saved to s3://{path_manager.output_bucket}/{debug_key}")

    except Exception as e:
        print(f"Failed to save original with bounding boxes: {str(e)}")


def save_after_symbol_clearing(path_manager, image: np.ndarray) -> None:
    """Save image after symbol bounding boxes have been cleared."""

    try:
        debug_pil = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))

        # Use ExecutionPathManager for clean debug paths
        debug_key = f"{path_manager.get_line_detection_path()}/debug/01_after_symbol_clearing.jpg"

        buffer = io.BytesIO()
        debug_pil.save(buffer, format="JPEG", quality=85)
        buffer.seek(0)

        s3_client.put_object(
            Bucket=path_manager.output_bucket,
            Key=debug_key,
            Body=buffer.getvalue(),
            ContentType="image/jpeg",
        )

        print(f"After symbol clearing saved to s3://{path_manager.output_bucket}/{debug_key}")

    except Exception as e:
        print(f"Failed to save after symbol clearing: {str(e)}")


def save_after_text_clearing(path_manager, image: np.ndarray) -> None:
    """Save image after text bounding boxes have been cleared."""

    try:
        debug_pil = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))

        # Use ExecutionPathManager for clean debug paths
        debug_key = f"{path_manager.get_line_detection_path()}/debug/02_after_text_clearing.jpg"

        buffer = io.BytesIO()
        debug_pil.save(buffer, format="JPEG", quality=85)
        buffer.seek(0)

        s3_client.put_object(
            Bucket=path_manager.output_bucket,
            Key=debug_key,
            Body=buffer.getvalue(),
            ContentType="image/jpeg",
        )

        print(f"After text clearing saved to s3://{path_manager.output_bucket}/{debug_key}")

    except Exception as e:
        print(f"Failed to save after text clearing: {str(e)}")


def save_after_grayscale(path_manager, image: np.ndarray) -> None:
    """Save grayscale image."""

    try:
        debug_pil = Image.fromarray(image, mode="L")

        # Use ExecutionPathManager for clean debug paths
        debug_key = f"{path_manager.get_line_detection_path()}/debug/03_after_grayscale.png"

        buffer = io.BytesIO()
        debug_pil.save(buffer, format="PNG")
        buffer.seek(0)

        s3_client.put_object(
            Bucket=path_manager.output_bucket,
            Key=debug_key,
            Body=buffer.getvalue(),
            ContentType="image/png",
        )

        print(f"After grayscale saved to s3://{path_manager.output_bucket}/{debug_key}")

    except Exception as e:
        print(f"Failed to save after grayscale: {str(e)}")


def save_after_binary(path_manager, image: np.ndarray) -> None:
    """Save binary image (before thinning)."""

    try:
        debug_pil = Image.fromarray(image, mode="L")

        # Use ExecutionPathManager for clean debug paths
        debug_key = f"{path_manager.get_line_detection_path()}/debug/04_after_binary.png"

        buffer = io.BytesIO()
        debug_pil.save(buffer, format="PNG")
        buffer.seek(0)

        s3_client.put_object(
            Bucket=path_manager.output_bucket,
            Key=debug_key,
            Body=buffer.getvalue(),
            ContentType="image/png",
        )

        print(f"After binary saved to s3://{path_manager.output_bucket}/{debug_key}")

    except Exception as e:
        print(f"Failed to save after binary: {str(e)}")


def save_lines_after_extension(
    path_manager,
    original_image: np.ndarray,
    original_lines: List[LineSegment],
    extended_lines: List[LineSegment],
) -> None:
    """Save comparison of lines before and after extension."""

    try:
        debug_image = original_image.copy()
        image_height, image_width = debug_image.shape[:2]

        # Draw original lines in blue
        for line in original_lines:
            start_x = int(line.startX * image_width)
            start_y = int(line.startY * image_height)
            end_x = int(line.endX * image_width)
            end_y = int(line.endY * image_height)
            cv2.line(
                debug_image, (start_x, start_y), (end_x, end_y), (255, 0, 0), 2
            )  # Blue

        # Draw extended lines in green (thinner)
        for line in extended_lines:
            start_x = int(line.startX * image_width)
            start_y = int(line.startY * image_height)
            end_x = int(line.endX * image_width)
            end_y = int(line.endY * image_height)
            cv2.line(
                debug_image, (start_x, start_y), (end_x, end_y), (0, 255, 0), 1
            )  # Green

        # Add legend
        cv2.putText(
            debug_image,
            "Blue: Original",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 0, 0),
            2,
        )
        cv2.putText(
            debug_image,
            "Green: Extended",
            (10, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
        )

        debug_pil = Image.fromarray(cv2.cvtColor(debug_image, cv2.COLOR_BGR2RGB))

        # Use ExecutionPathManager for clean debug paths
        debug_key = f"{path_manager.get_line_detection_path()}/debug/07_after_extension.jpg"

        buffer = io.BytesIO()
        debug_pil.save(buffer, format="JPEG", quality=85)
        buffer.seek(0)

        s3_client.put_object(
            Bucket=path_manager.output_bucket,
            Key=debug_key,
            Body=buffer.getvalue(),
            ContentType="image/jpeg",
        )

        print(f"Lines after extension saved to s3://{path_manager.output_bucket}/{debug_key}")

    except Exception as e:
        print(f"Failed to save lines after extension: {str(e)}")


def save_lines_after_merging(
    path_manager,
    original_image: np.ndarray,
    before_merge: List[LineSegment],
    after_merge: List[LineSegment],
) -> None:
    """Save comparison of lines before and after merging."""

    try:
        debug_image = original_image.copy()
        image_height, image_width = debug_image.shape[:2]

        # Draw before-merge lines in red (thinner)
        for line in before_merge:
            start_x = int(line.startX * image_width)
            start_y = int(line.startY * image_height)
            end_x = int(line.endX * image_width)
            end_y = int(line.endY * image_height)
            cv2.line(
                debug_image, (start_x, start_y), (end_x, end_y), (0, 0, 255), 1
            )  # Red

        # Draw after-merge lines in green (thicker)
        for line in after_merge:
            start_x = int(line.startX * image_width)
            start_y = int(line.startY * image_height)
            end_x = int(line.endX * image_width)
            end_y = int(line.endY * image_height)
            cv2.line(
                debug_image, (start_x, start_y), (end_x, end_y), (0, 255, 0), 3
            )  # Green

        # Add legend and stats
        cv2.putText(
            debug_image,
            "Red: Before merge",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255),
            2,
        )
        cv2.putText(
            debug_image,
            "Green: After merge",
            (10, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
        )
        cv2.putText(
            debug_image,
            f"{len(before_merge)} -> {len(after_merge)} lines",
            (10, 90),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )

        debug_pil = Image.fromarray(cv2.cvtColor(debug_image, cv2.COLOR_BGR2RGB))

        # Use ExecutionPathManager for clean debug paths
        debug_key = f"{path_manager.get_line_detection_path()}/debug/08_after_merging.jpg"

        buffer = io.BytesIO()
        debug_pil.save(buffer, format="JPEG", quality=85)
        buffer.seek(0)

        s3_client.put_object(
            Bucket=path_manager.output_bucket,
            Key=debug_key,
            Body=buffer.getvalue(),
            ContentType="image/jpeg",
        )

        print(f"Lines after merging saved to s3://{path_manager.output_bucket}/{debug_key}")

    except Exception as e:
        print(f"Failed to save lines after merging: {str(e)}")


def save_lines_after_filtering(
    path_manager,
    original_image: np.ndarray,
    before_filter: List[LineSegment],
    after_filter: List[LineSegment],
) -> None:
    """Save comparison of lines before and after short-line filtering."""

    try:
        debug_image = original_image.copy()
        image_height, image_width = debug_image.shape[:2]

        # Find lines that were removed
        removed_lines = []
        kept_lines = []

        # Simple approach: assume lines that are very similar are kept
        for before_line in before_filter:
            is_kept = False
            for after_line in after_filter:
                if (
                    abs(before_line.startX - after_line.startX) < 0.001
                    and abs(before_line.startY - after_line.startY) < 0.001
                    and abs(before_line.endX - after_line.endX) < 0.001
                    and abs(before_line.endY - after_line.endY) < 0.001
                ):
                    is_kept = True
                    break

            if is_kept:
                kept_lines.append(before_line)
            else:
                removed_lines.append(before_line)

        # Draw removed lines in red
        for line in removed_lines:
            start_x = int(line.startX * image_width)
            start_y = int(line.startY * image_height)
            end_x = int(line.endX * image_width)
            end_y = int(line.endY * image_height)
            cv2.line(
                debug_image, (start_x, start_y), (end_x, end_y), (0, 0, 255), 2
            )  # Red

        # Draw kept lines in green
        for line in kept_lines:
            start_x = int(line.startX * image_width)
            start_y = int(line.startY * image_height)
            end_x = int(line.endX * image_width)
            end_y = int(line.endY * image_height)
            cv2.line(
                debug_image, (start_x, start_y), (end_x, end_y), (0, 255, 0), 2
            )  # Green

        # Add legend
        cv2.putText(
            debug_image,
            "Red: Filtered out",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255),
            2,
        )
        cv2.putText(
            debug_image,
            "Green: Kept",
            (10, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
        )
        cv2.putText(
            debug_image,
            f"{len(before_filter)} -> {len(after_filter)} lines",
            (10, 90),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )

        debug_pil = Image.fromarray(cv2.cvtColor(debug_image, cv2.COLOR_BGR2RGB))

        # Use ExecutionPathManager for clean debug paths
        debug_key = f"{path_manager.get_line_detection_path()}/debug/09_after_filtering.jpg"

        buffer = io.BytesIO()
        debug_pil.save(buffer, format="JPEG", quality=85)
        buffer.seek(0)

        s3_client.put_object(
            Bucket=path_manager.output_bucket,
            Key=debug_key,
            Body=buffer.getvalue(),
            ContentType="image/jpeg",
        )

        print(f"Lines after filtering saved to s3://{path_manager.output_bucket}/{debug_key}")

    except Exception as e:
        print(f"Failed to save lines after filtering: {str(e)}")


def save_symbol_intersections(
    path_manager,
    original_image: np.ndarray,
    lines: List[LineSegment],
    symbol_boxes: List[BoundingBox],
    intersection_metadata: List[Dict],
) -> None:
    """Save image showing lines with symbol intersections highlighted."""

    try:
        debug_image = original_image.copy()
        image_height, image_width = debug_image.shape[:2]

        # Draw all symbol boxes in blue
        for box in symbol_boxes:
            cv2.rectangle(
                debug_image,
                (int(box.topX), int(box.topY)),
                (int(box.bottomX), int(box.bottomY)),
                (255, 0, 0),
                2,
            )

        # Draw all lines first in gray
        for line in lines:
            start_x = int(line.startX * image_width)
            start_y = int(line.startY * image_height)
            end_x = int(line.endX * image_width)
            end_y = int(line.endY * image_height)
            cv2.line(
                debug_image, (start_x, start_y), (end_x, end_y), (128, 128, 128), 1
            )

        # Highlight lines with intersections in bright colors
        colors = [
            (0, 255, 255),
            (255, 0, 255),
            (0, 255, 0),
            (255, 255, 0),
        ]  # Cyan, Magenta, Green, Yellow

        for i, metadata in enumerate(intersection_metadata):
            color = colors[i % len(colors)]
            original_line = metadata.get("original_line", {})

            if original_line:
                start_x = int(original_line["startX"] * image_width)
                start_y = int(original_line["startY"] * image_height)
                end_x = int(original_line["endX"] * image_width)
                end_y = int(original_line["endY"] * image_height)
                cv2.line(debug_image, (start_x, start_y), (end_x, end_y), color, 3)

                # Add intersection indicator
                mid_x = (start_x + end_x) // 2
                mid_y = (start_y + end_y) // 2
                cv2.circle(debug_image, (mid_x, mid_y), 8, color, -1)
                cv2.putText(
                    debug_image,
                    str(i),
                    (mid_x - 5, mid_y + 5),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 0, 0),
                    1,
                )

        # Add legend
        cv2.putText(
            debug_image,
            f"{len(intersection_metadata)} intersecting lines",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )

        debug_pil = Image.fromarray(cv2.cvtColor(debug_image, cv2.COLOR_BGR2RGB))

        # Use ExecutionPathManager for clean debug paths
        debug_key = f"{path_manager.get_line_detection_path()}/debug/10_symbol_intersections.jpg"

        buffer = io.BytesIO()
        debug_pil.save(buffer, format="JPEG", quality=85)
        buffer.seek(0)

        s3_client.put_object(
            Bucket=path_manager.output_bucket,
            Key=debug_key,
            Body=buffer.getvalue(),
            ContentType="image/jpeg",
        )

        print(f"Symbol intersections saved to s3://{path_manager.output_bucket}/{debug_key}")

    except Exception as e:
        print(f"Failed to save symbol intersections: {str(e)}")
