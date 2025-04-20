# PDF OCR Service

A FastAPI-based service for processing PDF documents with OCR and text extraction capabilities.

## Overview

This service provides an API for uploading and processing PDF documents. It uses the MagicPDF library along with various AI models to extract text content from PDFs. The service can handle both native text extraction and OCR for scanned documents.

## Features

- PDF document processing with automatic detection of parse method (OCR or text extraction)
- Asynchronous processing using process and thread pools for improved performance
- Document status tracking and retrieval
- MongoDB storage for processed document results
- Redis caching for fast status lookups
- Supporting AI models from Hugging Face for layout detection, OCR, etc.

## Prerequisites

- Python 3.8+
- MongoDB Atlas account
- Redis server
- Docker (optional, for containerized deployment)

## Installation

1. Clone the repository:
   ```
   git clone <repository-url>
   cd pdf-ocr-service
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Download required models:
   ```
   python download_models_hf.py
   ```

4. Create a `.env` file with the required environment variables (see Environment Variables section below)

## Environment Variables

Create a `.env` file in the root directory with the following variables:

```
# MongoDB Configuration
MONGO_CONNECTION_STRING=your_mongo_connection_string
MONGO_DB_NAME=ocr_service
MONGO_COLLECTION_NAME=documents

# Redis Configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=your_redis_password

# Service Configuration
PORT=8000
```

## Running the Service

### Local Development

```
uvicorn ocr_service:app --reload --port 8000
```

### Production

```
uvicorn ocr_service:app --host 0.0.0.0 --port 8000
```

### Docker

```
docker-compose up -d
```

## API Endpoints

- `POST /extract` - Upload a PDF file for processing
- `GET /check-status/{document_id}` - Check the processing status of a document
- `GET /result/{document_id}` - Get the processing result of a document

## Example Usage

```python
import requests

# Upload a PDF file
with open('document.pdf', 'rb') as f:
    files = {'file': f}
    data = {'document_id': 'my-document-1'}
    response = requests.post('http://localhost:8000/extract', files=files, data=data)
    print(response.json())

# Check status
response = requests.get('http://localhost:8000/check-status/my-document-1')
print(response.json())

# Get result
response = requests.get('http://localhost:8000/result/my-document-1')
print(response.json())
```

## Local Infrastructure Setup

For local development, you can use Docker to run MongoDB and Redis:

```bash
# Start LocalStack (for AWS services emulation if needed)
docker run -d --name localstack -p 4566:4566 -p 4510-4559:4510-4559 localstack/localstack

# Start Redis
docker run -d --name redis-stack-server -p 6379:6379 redis/redis-stack-server:latest
```

## Security Notes

- Never commit your `.env` file to version control
- Rotate MongoDB and Redis credentials regularly
- Use appropriate network security for production deployments

## License

[Your License]

docker run -d \
  --name ocr-service \
  -p 8000:8000 \
  --env-file /home/ec2-user/ocr-service/.env \
  -v /home/ec2-user/ocr-service/output:/app/output \
  --restart always \
  alyssajin/ocr-service:latest


  sudo yum update -y