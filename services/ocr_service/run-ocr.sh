# Script to build and run OCR service Docker container

cd ~/ocr-service

# Build Docker image
docker build -t ocr-service .

# Run container with environment variables from .env file
docker run -d \
  --name ocr-service \
  -p 8000:8000 \
  --env-file .env \
  -v ~/ocr-service/output:/app/output \
  --restart always \
  ocr-service

echo "OCR service is running on port 8000"