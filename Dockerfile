# Use python-slim for a smaller footprint
FROM python:3.11-slim

# Install system dependencies for OCR (Tesseract) and Image Processing (OpenCV/RemBG)
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-amh \
    tesseract-ocr-eng \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Set up a non-root user (Hugging Face requirement)
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:${PATH}"

WORKDIR /app

# Copy and install requirements
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Copy all code, fonts, and templates
COPY --chown=user . .

# Create directories with proper permissions
RUN mkdir -p input output fonts templates

# Pre-warm the rembg model
RUN python -c "from rembg import remove; import numpy as np; from PIL import Image; remove(np.zeros((10,10,3), dtype=np.uint8))"

# Hugging Face Spaces usually listen on port 7860, 
# but since we are using Polling, we don't strictly need it.
# We include it to prevent the "Health Check" from failing.
EXPOSE 7860

CMD ["python", "bot.py"]