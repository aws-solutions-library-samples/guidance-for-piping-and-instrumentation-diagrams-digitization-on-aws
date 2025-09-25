"""
PDF to PNG Converter
Converts multipage PDF files into individual PNG images for each page.
"""

import os
from pathlib import Path
from typing import List, Optional
from pdf2image import convert_from_path
from PIL import Image

Image.MAX_IMAGE_PIXELS = 10000000000

def pdf_to_png(
    pdf_path: str,
    output_dir: Optional[str] = None,
    dpi: int = 300,
    prefix: str = "page",
    image_format: str = "PNG"
) -> List[str]:
    """
    Convert a multipage PDF to individual PNG files.
    
    Args:
        pdf_path (str): Path to the input PDF file
        output_dir (str, optional): Directory to save PNG files. 
                                   If None, uses the same directory as the PDF
        dpi (int): Resolution for the output images (default: 300)
        prefix (str): Prefix for output filenames (default: "page")
        image_format (str): Image format for output files (default: "PNG")
    
    Returns:
        List[str]: List of paths to the created PNG files
    
    Raises:
        FileNotFoundError: If the PDF file doesn't exist
        Exception: If PDF conversion fails
    """
    
    # Validate input file
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    
    # Set output directory
    if output_dir is None:
        output_dir = pdf_path.parent
    else:
        output_dir = Path(output_dir)
    
    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Get base filename without extension
    base_name = pdf_path.stem
    
    try:
        # Convert PDF to images
        print(f"Converting PDF: {pdf_path}")
        pages = convert_from_path(
            pdf_path,
            dpi=dpi,
            fmt='ppm'  # Internal format for conversion
        )
        
        output_paths = []
        
        # Save each page as PNG
        for i, page in enumerate(pages, 1):
            # Create filename with zero-padded page numbers
            page_num = str(i).zfill(3)
            output_filename = f"{base_name}_{prefix}_{page_num}.{image_format.lower()}"
            output_path = output_dir / output_filename
            
            # Save the image
            page.save(output_path, image_format)
            output_paths.append(str(output_path))
            
            print(f"Saved: {output_path}")
        
        print(f"Successfully converted {len(pages)} pages from {pdf_path}")
        return output_paths
        
    except Exception as e:
        raise Exception(f"Failed to convert PDF to images: {str(e)}")


def batch_pdf_to_png(
    pdf_directory: str,
    output_dir: Optional[str] = None,
    dpi: int = 300,
    prefix: str = "page"
) -> dict:
    """
    Convert multiple PDF files in a directory to PNG files.
    
    Args:
        pdf_directory (str): Directory containing PDF files
        output_dir (str, optional): Directory to save PNG files
        dpi (int): Resolution for the output images
        prefix (str): Prefix for output filenames
    
    Returns:
        dict: Dictionary mapping PDF filenames to lists of output PNG paths
    """
    
    pdf_dir = Path(pdf_directory)
    if not pdf_dir.exists():
        raise FileNotFoundError(f"Directory not found: {pdf_dir}")
    
    # Find all PDF files
    pdf_files = list(pdf_dir.glob("*.pdf")) + list(pdf_dir.glob("*.PDF"))
    
    if not pdf_files:
        print(f"No PDF files found in {pdf_dir}")
        return {}
    
    results = {}
    
    for pdf_file in pdf_files:
        try:
            output_paths = pdf_to_png(
                str(pdf_file),
                output_dir=output_dir,
                dpi=dpi,
                prefix=prefix
            )
            results[pdf_file.name] = output_paths
        except Exception as e:
            print(f"Error processing {pdf_file}: {e}")
            results[pdf_file.name] = []
    
    return results


def main():
    """
    Example usage of the PDF to PNG converter.
    """
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python pdf_to_png_converter.py <pdf_path> [output_dir]")
        print("Example: python pdf_to_png_converter.py document.pdf ./output/")
        return
    
    pdf_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None
    
    try:
        output_files = pdf_to_png(pdf_path, output_dir)
        print(f"\nConversion complete! Created {len(output_files)} PNG files:")
        for file_path in output_files:
            print(f"  - {file_path}")
    
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
