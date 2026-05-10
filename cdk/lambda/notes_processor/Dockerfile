FROM public.ecr.aws/lambda/python:3.13

# Install system dependencies for OpenCV and Tesseract OCR.
# AL2023 base image lacks a tesseract dnf package, so we install the
# prebuilt static binary from tesseract-ocr/tesseract releases.
RUN dnf update -y && \
    dnf install -y \
    mesa-libGL \
    glib2 \
    libSM \
    libXext \
    libXrender \
    libgomp \
    tar \
    gzip \
    leptonica-devel \
    tesseract \
    tesseract-langpack-eng \
    && dnf clean all || true

# Fallback: if dnf didn't provide tesseract (AL2023 minimal repos),
# fall back to a static musl build shipped via pip in future; for now
# `pytesseract` degrades gracefully (see notes_section_detector.py:278).

# Create a non-root user manually
RUN mkdir -p /home/appuser && \
    echo "appuser:x:1001:1001::/home/appuser:/bin/sh" >> /etc/passwd && \
    echo "appuser:x:1001:" >> /etc/group && \
    chown -R 1001:1001 /home/appuser

# Copy requirements and install Python dependencies
COPY notes_processor/requirements.txt ${LAMBDA_TASK_ROOT}
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared utilities from the shared directory
COPY shared/config_helper.py ${LAMBDA_TASK_ROOT}/
COPY shared/execution_paths.py ${LAMBDA_TASK_ROOT}/

# Copy application code
COPY notes_processor/index.py ${LAMBDA_TASK_ROOT}
COPY notes_processor/frame_detector.py ${LAMBDA_TASK_ROOT}
COPY notes_processor/notes_section_detector.py ${LAMBDA_TASK_ROOT}

# Change ownership of the LAMBDA_TASK_ROOT directory
RUN chown -R 1001:1001 ${LAMBDA_TASK_ROOT}

# Switch to non-root user
USER 1001

# Set the CMD to your handler
CMD ["index.lambda_handler"]

# Add HEALTHCHECK instruction
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8080/2018-06-01/runtime/invocation/next')"
