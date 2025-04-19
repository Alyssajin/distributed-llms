import os
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

# MongoDB configuration
MONGO_CONNECTION_STRING = os.getenv('MONGO_CONNECTION_STRING')
MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'ocr_service')
MONGO_COLLECTION_NAME = os.getenv('MONGO_COLLECTION_NAME', 'documents')

# Redis configuration
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD')

# Service configuration
PORT = int(os.getenv('PORT', 8000))

# Validate required environment variables
if not MONGO_CONNECTION_STRING:
    logger.warning("MONGO_CONNECTION_STRING is not set. Using default or will fail if MongoDB connection is required.")

# Log configuration (without sensitive information)
logger.info(f"Configuration loaded with MongoDB database: {MONGO_DB_NAME}")
logger.info(f"Redis host: {REDIS_HOST}, port: {REDIS_PORT}")
logger.info(f"Service will run on port: {PORT}")