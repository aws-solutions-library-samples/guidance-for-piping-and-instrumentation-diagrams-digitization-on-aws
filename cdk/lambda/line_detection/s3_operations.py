import json
import boto3
import logging
from typing import List, Dict

# Set up logging
logger = logging.getLogger()

# Initialize AWS clients
s3_client = boto3.client("s3")


def save_results_to_s3(
    path_manager,
    detected_lines: List[Dict],
    symbol_intersections: List[Dict],
    processing_metadata: Dict,
) -> Dict[str, str]:
    """
    Save line detection results to S3 using ExecutionPathManager for clean paths.

    Returns dictionary with S3 keys for accessing the saved data.
    """

    try:
        # Use ExecutionPathManager for consistent file organization
        base_path = path_manager.get_line_detection_path()
        lines_key = f"{base_path}/detected_lines.json"
        intersections_key = f"{base_path}/symbol_intersections.json"
        metadata_key = f"{base_path}/processing_metadata.json"

        # Save detected lines
        lines_data = {
            "execution_id": path_manager.execution_id,
            "detected_lines": detected_lines,
            "line_count": len(detected_lines),
        }

        s3_client.put_object(
            Bucket=path_manager.output_bucket,
            Key=lines_key,
            Body=json.dumps(lines_data, indent=2).encode("utf-8"),
            ContentType="application/json",
        )

        print(f"Detected lines saved to s3://{path_manager.output_bucket}/{lines_key}")

        # Save symbol intersections
        intersections_data = {
            "execution_id": path_manager.execution_id,
            "symbol_intersections": symbol_intersections,
            "intersection_count": len(symbol_intersections),
        }

        s3_client.put_object(
            Bucket=path_manager.output_bucket,
            Key=intersections_key,
            Body=json.dumps(intersections_data, indent=2).encode("utf-8"),
            ContentType="application/json",
        )

        print(f"Symbol intersections saved to s3://{path_manager.output_bucket}/{intersections_key}")

        # Save processing metadata
        metadata_data = {
            "execution_id": path_manager.execution_id,
            "processing_metadata": processing_metadata,
        }

        s3_client.put_object(
            Bucket=path_manager.output_bucket,
            Key=metadata_key,
            Body=json.dumps(metadata_data, indent=2).encode("utf-8"),
            ContentType="application/json",
        )

        print(f"Processing metadata saved to s3://{path_manager.output_bucket}/{metadata_key}")

        # Return S3 references for Step Functions
        return {
            "lines_s3_key": lines_key,
            "intersections_s3_key": intersections_key,
            "metadata_s3_key": metadata_key,
            "bucket": path_manager.output_bucket,
            "execution_id": path_manager.execution_id,
        }

    except Exception as e:
        print(f"Error saving results to S3: {str(e)}")
        # Return minimal fallback data
        return {
            "error": f"Failed to save to S3: {str(e)}",
            "bucket": path_manager.output_bucket if "path_manager" in locals() else "unknown",
            "execution_id": path_manager.execution_id if "path_manager" in locals() else "unknown",
        }
