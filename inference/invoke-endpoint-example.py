import boto3
import json
import base64
from PIL import Image
import io

def invoke_sagemaker_endpoint(endpoint_name, image_path, aws_region='us-east-1', 
                            score_threshold=0.5, n_closest=3):
    """
    Invoke SageMaker endpoint for symbol detection and classification
    
    Args:
        endpoint_name: Name of the SageMaker endpoint
        image_path: Path to the image file
        aws_region: AWS region where endpoint is deployed
        score_threshold: Minimum confidence for detections
        n_closest: Number of closest reference symbols to return
    
    Returns:
        Dictionary containing detection results with symbol classifications
    """
    # Initialize SageMaker runtime client
    runtime = boto3.client('sagemaker-runtime', region_name=aws_region)
    
    # Load and encode image
    with open(image_path, 'rb') as f:
        image_bytes = f.read()
    
    image_b64 = base64.b64encode(image_bytes).decode('utf-8')
    
    # Prepare payload
    payload = {
        'image': image_b64,
        'score_threshold': score_threshold,
        'n_closest': n_closest
    }
    
    # Invoke endpoint
    response = runtime.invoke_endpoint(
        EndpointName=endpoint_name,
        ContentType='application/json',
        Body=json.dumps(payload)
    )
    
    # Parse response
    result = json.loads(response['Body'].read().decode())
    return result

def invoke_local_inference(image_path, model_dir='./models'):
    """
    Run inference locally using the inference script
    
    Args:
        image_path: Path to the image file
        model_dir: Directory containing model files
    
    Returns:
        Dictionary containing detection results with symbol classifications
    """
    from inference import model_fn, input_fn, predict_fn, output_fn
    
    # Load models
    models = model_fn(model_dir)
    # Prepare input
    with open(image_path, 'rb') as f:
        image_bytes = f.read()
    
    image_b64 = base64.b64encode(image_bytes).decode('utf-8')
    
    payload = {
        'image': image_b64,
        'score_threshold': 0.5,
        'n_closest': 3
    }
    
    # Run inference pipeline
    input_data = input_fn(json.dumps(payload))
    prediction = predict_fn(input_data, models)
    result = output_fn(prediction)
    
    return json.loads(result)

def test_inference(image_path, endpoint_name=None):
    """
    Test inference either locally or via SageMaker endpoint
    """
    if endpoint_name:
        print(f"Testing SageMaker endpoint: {endpoint_name}")
        result = invoke_sagemaker_endpoint(endpoint_name, image_path)
    else:
        print("Testing local inference")
        result = invoke_local_inference(image_path)
    return result

def batch_inference(image_paths, endpoint_name, batch_size=5):
    """
    Run inference on multiple images
    
    Args:
        image_paths: List of image file paths
        endpoint_name: SageMaker endpoint name
        batch_size: Number of images to process at once
    
    Returns:
        Dictionary with results for each image
    """
    results = {}
    
    for i in range(0, len(image_paths), batch_size):
        batch_paths = image_paths[i:i+batch_size]
        
        for image_path in batch_paths:
            try:
                result = invoke_sagemaker_endpoint(endpoint_name, image_path)
                results[image_path] = result
                print(f"Processed {image_path}: {len(result)} detections")
            except Exception as e:
                print(f"Error processing {image_path}: {e}")
                results[image_path] = {"error": str(e)}
    
    return results

if __name__ == "__main__":
    # Example usage
    image_path = "./simple.png"  # Update with your image path
    
    # Test local inference
    result = test_inference(image_path)
    
    # To test SageMaker endpoint (uncomment and update endpoint name):
    #result = test_inference(image_path, endpoint_name="dual-model-endpoint-300")
    # For batch processing:
    # image_paths = ["./images/1.png", "./images/2.png"]
    # batch_results = batch_inference(image_paths, "your-endpoint-name")

import cv2
import numpy as np

def draw_detections_on_image(image_path, detections, output_path):
    """Draw detection boxes on original image"""
    # Load image
    image = cv2.imread(image_path)
    
    # Draw boxes directly
    for detection in detections["detections"]:
        bbox = detection['bbox']  # Assuming format: [x1, y1, x2, y2]
        x1, y1, x2, y2 = int(bbox.get('x1')), int(bbox.get('y1')), int(bbox.get('x2')), int(bbox.get('y2'))
        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
    
    # Save result
    cv2.imwrite(output_path, image)
    print(f"Saved visualization to {output_path}")

# Usage with your existing code:
if __name__ == "__main__":    
    image_path = "./simple.png"
    result = test_inference(image_path)
    draw_detections_on_image(image_path, result, "simple_before11.png")