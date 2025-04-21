import hashlib
import os
import time
import json
import logging
import boto3
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, File, Form, UploadFile, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from io import BytesIO
import shutil
import datetime
import redis
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import re
import pymongo
from pymongo import MongoClient
from bson.objectid import ObjectId



from magic_pdf.data.dataset import PymuDocDataset
from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze
from magic_pdf.config.enums import SupportedPdfParseMethod

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# MongoDB connection configuration (using environment variables for security)
MONGO_CONNECTION_STRING = os.environ.get('MONGO_CONNECTION_STRING', 'mongodb+srv://alyssajin2019:abkF0hz5gNi56d2c@dsllms-cluster.lgwixwu.mongodb.net/?retryWrites=true&w=majority&appName=dsllms-cluster')
MONGO_DB_NAME = os.environ.get('MONGO_DB_NAME', 'ocr_service')
MONGO_COLLECTION_NAME = os.environ.get('MONGO_COLLECTION_NAME', 'documents')

# Initialize MongoDB client at application startup
mongo_client = None
ocr_db = None
documents_collection = None

# Process pool for CPU-intensive tasks (like OCR)
process_executor = ProcessPoolExecutor(max_workers=os.cpu_count())
# Thread pool for I/O-bound tasks
thread_executor = ThreadPoolExecutor(max_workers=10)

# Output directory for files
output_dir = "output"
image_dir = os.path.join(output_dir, "images")

# Ensure directories exist
os.makedirs(output_dir, exist_ok=True)
os.makedirs(image_dir, exist_ok=True)

# Initialize Redis connection
redis_client = redis.Redis(
    host=os.environ.get('REDIS_HOST', 'localhost'),
    port=int(os.environ.get('REDIS_PORT', 6379)),
    password=os.environ.get('REDIS_PASSWORD', None),
    decode_responses=True  # Automatically decode bytes to strings
)

# Store document status
def update_document_status(document_id, status_data):
    """Store document processing status in Redis"""
    try:
        # Make sure document_id exists
        if document_id is None:
            logger.error("Cannot update status: document_id is None")
            return False
        # Only store hash mapping if hash exists
        if 'document_hash' in status_data and status_data['document_hash'] is not None:
            redis_client.setex(f"hash:{status_data['document_hash']}", 86400, document_id)
        
        # Convert dictionary to JSON string
        status_json = json.dumps(status_data)
        # Store in Redis with an expiration time (e.g., 24 hours = 86400 seconds)
        redis_client.setex(f"doc:{document_id}", 86400, status_json)
        
        logger.info(f"Updated status for document {document_id}: {status_data['status']}")
        return True
    except Exception as e:
        logger.error(f"Error updating document status in Redis: {str(e)}")
        return False

# Retrieve document status
def get_document_status(document_id):
    """Get document status from Redis"""
    try:
        status_json = redis_client.get(f"doc:{document_id}")
        if status_json:
            return json.loads(status_json)
        return None
    except Exception as e:
        logger.error(f"Error retrieving document status from Redis: {str(e)}")
        return None

def check_document_exists_by_id(document_id):
    """Check if a document exists using only its document_id"""
    try:
        key = f"doc:{document_id}"
        
        # Simply check if the key exists in Redis
        exists = redis_client.exists(key)
        
        return exists  # Returns True if document exists, False otherwise
    except Exception as e:
        logger.error(f"Error checking document existence in Redis: {str(e)}")
        return False

# Custom file writer for local storage
class LocalFileWriter:
    def __init__(self, base_dir):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)
    
    def write(self, path, data):
        """Write data to a local file"""
        full_path = os.path.join(self.base_dir, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        with open(full_path, 'wb') as f:
            f.write(data)
        
        return full_path

# Define the lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup code (runs before application starts) ---
    global mongo_client, ocr_db, documents_collection, redis_client
    
    try:
        # Initialize MongoDB connection
        mongo_client = MongoClient(
                        MONGO_CONNECTION_STRING,
                        tls=True,
                        tlsAllowInvalidCertificates=True )
        # Test the connection
        mongo_client.admin.command('ping')
        logger.info("Connected to MongoDB Atlas successfully")
        
        # Access database and collection
        ocr_db = mongo_client[MONGO_DB_NAME]
        documents_collection = ocr_db[MONGO_COLLECTION_NAME]
        
        # Create indexes for better performance
        documents_collection.create_index("document_id", unique=True)
        documents_collection.create_index("document_hash")
        documents_collection.create_index("status")
        documents_collection.create_index("processed_at")
        
        # Initialize Redis connection
        redis_client = redis.Redis(
            host=os.environ.get('REDIS_HOST', 'localhost'),
            port=int(os.environ.get('REDIS_PORT', 6379)),
            password=os.environ.get('REDIS_PASSWORD', None),
            decode_responses=True
        )
        
        logger.info("Service started successfully with process pool size: %d", process_executor._max_workers)
        logger.info("Thread pool size: %d", thread_executor._max_workers)
    except Exception as e:
        logger.error(f"Error during startup: {str(e)}")
    
    yield  # This is where the application runs
    
    # --- Shutdown code (runs after application stops) ---
    try:
        # Close MongoDB connection
        if mongo_client:
            mongo_client.close()
            logger.info("MongoDB connection closed")
            
        # Shutdown process and thread pools
        process_executor.shutdown(wait=False)
        thread_executor.shutdown(wait=False)
        logger.info("Service shut down successfully")
    except Exception as e:
        logger.error(f"Error during shutdown: {str(e)}")

# Initialize FastAPI app with the lifespan handler
app = FastAPI(
    title="PDF OCR Service", 
    description="API for processing PDF documents with OCR and text extraction",
    lifespan=lifespan  # Connect the lifespan context manager
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Initialize local file writer
local_image_writer = LocalFileWriter(image_dir)

# Synchronous function to process PDF - runs in a separate process
def process_pdf_sync(pdf_bytes, document_id, document_hash=None):
    """
    Process a PDF file synchronously.
    This function runs in a separate process to utilize multiprocessing.
    """
    try:
        logger.info(f"Processing PDF ID: {document_id}")
        
        # Create Dataset Instance
        ds = PymuDocDataset(pdf_bytes)
        
        # Determine processing method and apply it
        if ds.classify() == SupportedPdfParseMethod.OCR:
            logger.info(f"Using OCR mode for {document_id}")
            infer_result = ds.apply(doc_analyze, ocr=True)
            pipe_result = infer_result.pipe_ocr_mode(local_image_writer)
        else:
            logger.info(f"Using text extraction mode for {document_id}")
            infer_result = ds.apply(doc_analyze, ocr=False)
            pipe_result = infer_result.pipe_txt_mode(local_image_writer)
        
        # Get markdown content
        markdown_content = pipe_result.get_markdown(os.path.basename(image_dir))
        
        # Get content list
        content_list = pipe_result.get_content_list(os.path.basename(image_dir))
        
        # Combine all text from content_list into a single body
        combined_text = ""
        
        # Extract text from the content list and combine it
        if isinstance(content_list, list):
            for item in content_list:
                if isinstance(item, dict) and 'text' in item:
                    combined_text += item['text'] + "\n\n"
                elif isinstance(item, str):
                    combined_text += item + "\n\n"
        
        # If no text was extracted from content_list, use markdown content instead
        if not combined_text.strip() and markdown_content:
            # Remove markdown formatting for clean text
            combined_text = re.sub(r'#+ ', '', markdown_content)  # Remove headers
            combined_text = re.sub(r'\*\*|\*|__|\||---|___', '', combined_text)  # Remove formatting
        
        return {
            'status': 'completed',
            'result': combined_text.strip(),
        }
        
    except Exception as e:
        logger.error(f"Error in process_pdf_sync for {document_id}: {str(e)}")
        return {
            'status': 'failed',
            'error': str(e)
        }

async def process_pdf_async(pdf_bytes, document_id, document_hash=None):
    """
    Asynchronous wrapper to run PDF processing in a separate process.
    This function is called from FastAPI endpoints.
    """
    try:
        # Update status to processing
        update_document_status(document_id, {
            'status': 'processing',
            'document_hash': document_hash,
            'started_at': datetime.datetime.now().isoformat()
        })
        
        # Use the running event loop
        loop = asyncio.get_running_loop()
        
        # Run the CPU-intensive processing in the process pool
        result = await loop.run_in_executor(
            process_executor,
            process_pdf_sync,
            pdf_bytes, document_id, document_hash
        )
        
        # Handle the result
        if result['status'] == 'completed':
            
            # Save the results asynchronously using thread pool
            await loop.run_in_executor(
                thread_executor,
                save_results,
                document_id, result
            )
            
            # Update the status in Redis
            update_document_status(document_id, {
                'status': 'completed',
                'document_hash': document_hash,
                'result': result['result'],
                'completed_at': datetime.datetime.now().isoformat()
            })
            
            return {
                'status': 'completed',
                'result': result['result']
            }
        else:
            # Handle error case
            update_document_status(document_id, {
                'status': 'failed',
                'document_hash': document_hash,
                'error': result['error'],
                'completed_at': datetime.datetime.now().isoformat()
            })
            
            # Save error information
            await loop.run_in_executor(
                thread_executor,
                save_error,
                document_id, result['error']
            )
            
            return {
                'status': 'failed',
                'error': result['error']
            }
            
    except Exception as e:
        logger.error(f"Error in process_pdf_async for {document_id}: {str(e)}")
        
        # Update status to failed
        update_document_status(document_id, {
            'status': 'failed',
            'document_hash': document_hash,
            'error': str(e),
            'completed_at': datetime.datetime.now().isoformat()
        })
        
        return {
            'status': 'failed',
            'error': str(e)
        }

def save_results(document_id, result):
    """Save successful processing results to MongoDB"""
    try:
        # Only proceed if status is completed
        if result['status'] != 'completed':
            logger.info(f"Not saving to MongoDB - processing not completed for {document_id}")
            return False
            
        # Get the Redis status first for additional information
        status_json = redis_client.get(f"doc:{document_id}")
        status_data = {}
        if status_json:
            try:
                status_data = json.loads(status_json)
            except:
                logger.warning(f"Could not parse Redis status for {document_id}")
        
        # Create MongoDB document
        mongo_doc = {
            'document_id': document_id,
            'combined_text': result['result'],
            'status': 'completed',
            'processed_at': datetime.datetime.now(),
            'word_count': len(result['result'].split()),
            'character_count': len(result['result'])
        }
        
        # Insert or update document in MongoDB
        documents_collection.update_one(
            {"document_id": document_id},
            {"$set": mongo_doc},
            upsert=True
        )
        
        # Update Redis with completion status and a preview
        # This keeps status checks fast but doesn't duplicate all data
        update_document_status(document_id, {
            'status': 'completed',
            'result_preview': result['result'][:500] + '...' if len(result['result']) > 500 else result['result'],
            'completed_at': datetime.datetime.now().isoformat()
        })
            
        logger.info(f"Successfully processed and saved document {document_id} to MongoDB Atlas")
        return True
    except Exception as e:
        logger.error(f"Error saving results for {document_id} to MongoDB: {str(e)}")
        return False

def save_error(document_id, error_message):
    """Save error information to a file (runs in thread pool)"""
    try:
        # Create a JSON with error information
        error_json = {
            'document_id': document_id,
            'status': 'failed',
            'error': error_message,
            'processed_at': datetime.datetime.now().isoformat()
        }
        
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        
        # Save the error information
        error_path = os.path.join(output_dir, f"error_{document_id}.json")
        with open(error_path, "w", encoding="utf-8") as f:
            json.dump(error_json, f, ensure_ascii=False, indent=2)
            
        logger.info(f"Saved error information for {document_id}")
        return True
    except Exception as e:
        logger.error(f"Error saving error information for {document_id}: {str(e)}")
        return False

@app.post("/extract")
async def upload_pdf(file: UploadFile = File(...), document_id: str = Form(...) ):
    """
    Upload a PDF file for processing
    
    This endpoint accepts a PDF file upload and processes it using OCR or text extraction.
    The processing happens asynchronously using process pools.
    
    - **file**: The PDF file to process
    - **document_id**: Optional ID for the document (will be generated if not provided)
    
    Returns:
        JSON with document_id and status information
    """
    try:
        logger.info(f"Received file: {document_id}")
        # Validate file type
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Only PDF files are accepted")
        
        # Generate document_id if not provided
        if not document_id:
            return HTTPException(status_code=400, detail="document_id is required")

        # Read file into memory for hashing
        file_bytes = await file.read()
        document_hash = hashlib.sha256(file_bytes).hexdigest()
        
        # Check if this file is already being processed
        if check_document_exists_by_id(document_id):
            # Get current status
            status_data = get_document_status(document_id)
            if status_data:
                return {
                    "status": status_data['status'],
                    # "message": f"Document with ID {document_id} already exists",
                    # "document_id": document_id
                }
    
        # Initialize status in Redis
        update_document_status(document_id, {
            'status': 'queued',
            'document_hash': document_hash,
            'filename': file.filename,
            'started_at': datetime.datetime.now().isoformat()
        })
        
        # Start the processing in background (don't await the result)
        asyncio.create_task(process_pdf_async(file_bytes, document_id, document_hash))
        
        # Return initial response with tracking ID
        return {
            "status": "ok",
        }
    
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error handling PDF upload: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing PDF: {str(e)}")
    
@app.get("/check-status/{document_id}")
async def check_processing_status(document_id: str):
    """
    Quick check if processing is complete
    
    - **document_id**: The ID of the file to check
    
    Returns:
        Simple status: "processing" or "ok" or "error"
    """
    try:
        status_data = get_document_status(document_id)
        if status_data:
            status = status_data['status']
            if status == 'completed':
                return {"status": "completed"}
            elif status == 'failed':
                return {"status": "error"}
            else:
                return {"status": "processing"}
        else:
            return JSONResponse(
                content={'status': 'unknown', 'error': f'No record found for document ID: {document_id}'},
                status_code=404
            )
    
    except Exception as e:
        logger.error(f"Error checking status for {document_id}: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.get("/result/{document_id}")
async def get_processing_result(document_id: str):
    try:
        # First check Redis for status (fast lookup)
        status_json = redis_client.get(f"doc:{document_id}")
        status_data = None
        
        if status_json:
            try:
                status_data = json.loads(status_json)
            except:
                logger.warning(f"Could not parse Redis status for {document_id}")
        
        # For in-progress documents, return status from Redis
        if status_data and status_data.get('status') != 'completed':
            return JSONResponse(
                content={
                    'document_id': document_id,
                    'status': status_data.get('status', 'unknown'),
                    'message': f"Document processing status: {status_data.get('status', 'unknown')}"
                }
            )
        
        # For completed documents, get the result from MongoDB
        loop = asyncio.get_running_loop()
        mongo_doc = await loop.run_in_executor(
            thread_executor,
            lambda: documents_collection.find_one({"document_id": document_id})
        )
        
        if mongo_doc:
            # Create a completely new dictionary with just the text field
            result = {
                "document_id": document_id,
                "text": mongo_doc.get('combined_text', ''),
                "status": "completed"
            }
            
            # Return a clean dictionary without any datetime objects
            return JSONResponse(content=result)
        else:
            # Not found in either database
            return JSONResponse(
                content={'error': f'No record found for document ID: {document_id}'},
                status_code=404
            )
    
    except Exception as e:
        logger.error(f"Error retrieving result for {document_id}: {str(e)}")
        # Print the full exception trace for debugging
        import traceback
        logger.error(traceback.format_exc())
        return JSONResponse(
            content={'error': f'Error retrieving result: {str(e)}'},
            status_code=500
        )

@app.get("/health")
async def health_check():
    """
    Health check endpoint for load balancers and monitoring systems.
    Checks connectivity to Redis and MongoDB.
    """
    status = {
        "status": "healthy",
        "version": "1.0.0",
        "timestamp": datetime.datetime.now().isoformat(),
        "dependencies": {
            "redis": "unknown",
            "mongodb": "unknown"
        }
    }
    
    # Check Redis connectivity
    try:
        redis_ping = redis_client.ping()
        status["dependencies"]["redis"] = "healthy" if redis_ping else "degraded"
    except Exception as e:
        logger.error(f"Redis health check failed: {str(e)}")
        status["dependencies"]["redis"] = "unhealthy"
    
    # Check MongoDB connectivity
    try:
        # Run in thread pool for async operation
        loop = asyncio.get_running_loop()
        mongo_result = await loop.run_in_executor(
            thread_executor, 
            lambda: mongo_client.admin.command('ping')
        )
        status["dependencies"]["mongodb"] = "healthy" if mongo_result.get('ok') == 1 else "degraded"
    except Exception as e:
        logger.error(f"MongoDB health check failed: {str(e)}")
        status["dependencies"]["mongodb"] = "unhealthy"
    
    # Set overall status based on dependencies
    if all(v == "healthy" for v in status["dependencies"].values()):
        status["status"] = "healthy"
    elif any(v == "unhealthy" for v in status["dependencies"].values()):
        status["status"] = "unhealthy"
        return JSONResponse(content=status, status_code=503)  # Service Unavailable
    else:
        status["status"] = "degraded"
    
    return status
    
if __name__ == "__main__":
    # Run the FastAPI app with Uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)