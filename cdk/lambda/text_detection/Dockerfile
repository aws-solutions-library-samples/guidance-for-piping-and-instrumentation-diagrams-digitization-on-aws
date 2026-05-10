FROM public.ecr.aws/lambda/python:3.13

# Install system dependencies for OpenCV
RUN dnf update -y && \
    dnf install -y \
    mesa-libGL \
    glib2 \
    libSM \
    libXext \
    libXrender \
    libgomp \
    && dnf clean all

# Create a non-root user manually
RUN mkdir -p /home/appuser && \
    echo "appuser:x:1001:1001::/home/appuser:/bin/sh" >> /etc/passwd && \
    echo "appuser:x:1001:" >> /etc/group && \
    chown -R 1001:1001 /home/appuser

# Copy requirements and install Python dependencies
COPY text_detection/requirements.txt ${LAMBDA_TASK_ROOT}
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared utilities from the shared directory
COPY shared/config_helper.py ${LAMBDA_TASK_ROOT}/
COPY shared/execution_paths.py ${LAMBDA_TASK_ROOT}/
COPY shared/debug_image_utils.py ${LAMBDA_TASK_ROOT}/

# Copy application code
COPY text_detection/index.py ${LAMBDA_TASK_ROOT}

# Change ownership of the LAMBDA_TASK_ROOT directory
RUN chown -R 1001:1001 ${LAMBDA_TASK_ROOT}

# Switch to non-root user
USER 1001

# Set the CMD to your handler
CMD ["index.lambda_handler"]

# Add HEALTHCHECK instruction
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8080/2018-06-01/runtime/invocation/next')"
