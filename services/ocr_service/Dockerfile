FROM python:3.10

WORKDIR /app

# Install system dependencies for OpenCV
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6

# Copy your scripts
COPY download_models_hf.py .
COPY ocr_service.py .
COPY requirements.txt .

# Install dependencies
RUN pip install -r requirements.txt

# Download models
RUN python download_models_hf.py

# Run the OCR service
CMD ["python", "ocr_service.py"]