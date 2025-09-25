#!/usr/bin/env python3
"""
Deploy dual models (Faster R-CNN + Siamese Network) to SageMaker
Reference images should be in PNG format and 224*224 size
"""

import boto3
import sagemaker
from sagemaker.pytorch import PyTorchModel
import os
import tarfile
from PIL import Image
import tarfile
import os

def create_model_tar(model_folder, inference_file="inference.py", siamese_file="siamese_lightning.py", png_folder = "png_references", output_path="model2.tar.gz"):
    """
    Create a tar.gz file with all model files from a folder and inference code
    """    
    import tarfile
    import cairosvg
    import os
    
    print(f"Creating model archive: {output_path}")
    
    with tarfile.open(output_path, "w:gz") as tar:
        # Add all files from model folder
        if os.path.exists(model_folder):
            for file_name in os.listdir(model_folder):
                file_path = os.path.join(model_folder, file_name)
                if os.path.isfile(file_path):
                    tar.add(file_path, arcname=file_name)
                    print(f"  Added: {file_path}")
        else:
            print(f"  Warning: Model folder {model_folder} not found")
        
        # Add inference code
        if os.path.exists(inference_file):
            tar.add(inference_file, arcname="code/inference.py")
            print(f"  Added: {inference_file}")
        else:
            print(f"  Warning: {inference_file} not found")

        # Add siamese_file
        if os.path.exists(siamese_file):
            tar.add(siamese_file, arcname="siamese_lightning.py")
            print(f"  Added: {siamese_file}")
        else:
            print(f"  Warning: {siamese_file} not found")

        print(os.listdir(png_folder))
        
        # Add PNG references folder
        if os.path.exists(png_folder):
            for file_name in os.listdir(png_folder):
                file_path = os.path.join(png_folder, file_name)
                if os.path.isfile(file_path) and file_name.endswith('.png'):
                    tar.add(file_path, arcname=f"references/{file_name}")
                    print(f"  Added: {file_path}")
            
        # Add requirements.txt
        if os.path.exists("requirements.txt"):
            tar.add("requirements.txt", arcname="code/requirements.txt")
            print(f"  Added: requirements.txt")
        else:
            print(f"  Warning: requirements.txt not found")
            
    print(f"Model archive created: {output_path}")
    return output_path

   
def deploy_to_sagemaker(model_tar_path, role_arn, instance_type="ml.g4dn.xlarge"):
    """Deploy the dual model to SageMaker"""
    
    print("Deploying to SageMaker...")
    
    # Initialize SageMaker session
    sagemaker_session = sagemaker.Session()

    
    # Upload model to S3
    model_uri = sagemaker_session.upload_data(
        path=model_tar_path,
        key_prefix="dual-model"
    )
    print(f"Model uploaded to: {model_uri}")
    
    # Create PyTorch model
    pytorch_model = PyTorchModel(
        model_data=model_uri,
        role=role_arn,
        entry_point="inference.py",
        framework_version="2.6",
        py_version="py312",
        name="dual-model-frcnn-siamese-401"
    )
    
    # Deploy the model
    predictor = pytorch_model.deploy(
        initial_instance_count=1,
        instance_type="ml.g4dn.2xlarge",
        endpoint_name="dual-model-endpoint-401",
    )
    
    print(f"Model deployed to endpoint: {predictor.endpoint_name}")
    return predictor

 def deploy(model_tar): 
    # Deploy to SageMaker
    try:
        role = sagemaker.get_execution_role()
        predictor = deploy_to_sagemaker(model_tar, role)
            
    except Exception as e:
        print(f"\n✗ Deployment failed: {e}")
    
    # Cleanup
    if os.path.exists(model_tar):
        os.remove(model_tar)
        print(f"Cleaned up: {model_tar}")

def main():
    model_tar = create_model_tar("./models")
    deploy(model_tar)
    
if __name__ == "__main__":
    main()
