import os
import time
import json
import logging
import uuid
import boto3
from fastapi import FastAPI, File, UploadFile, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from io import BytesIO
import shutil
import datetime

from magic_pdf.data.dataset import PymuDocDataset
from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze
from magic_pdf.config.enums import SupportedPdfParseMethod

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# AWS Configuration for DynamoDB only
region_name = "us-west-2"
dynamodb_table_name = "pdf_processing_results"

# Output directory for files
output_dir = "output"
image_dir = os.path.join(output_dir, "images")

# Ensure directories exist
os.makedirs(output_dir, exist_ok=True)
os.makedirs(image_dir, exist_ok=True)

# Initialize AWS clients for DynamoDB - using default credential provider chain
dynamodb_client = boto3.client(
    'dynamodb',
    region_name=region_name
)

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

# Initialize FastAPI app
app = FastAPI(title="PDF OCR Service", 
              description="API for processing PDF documents with OCR and text extraction")

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

def create_dynamodb_table_if_not_exists():
    """Create DynamoDB table if it doesn't exist."""
    try:
        # Check if table exists
        dynamodb_client.describe_table(TableName=dynamodb_table_name)
        logger.info(f"DynamoDB table {dynamodb_table_name} already exists")
    except dynamodb_client.exceptions.ResourceNotFoundException:
        logger.info(f"Creating DynamoDB table: {dynamodb_table_name}")
        
        # Create table with on-demand capacity
        response = dynamodb_client.create_table(
            TableName=dynamodb_table_name,
            KeySchema=[
                {'AttributeName': 'file_id', 'KeyType': 'HASH'},  # Partition key
                {'AttributeName': 'timestamp', 'KeyType': 'RANGE'}  # Sort key
            ],
            AttributeDefinitions=[
                {'AttributeName': 'file_id', 'AttributeType': 'S'},
                {'AttributeName': 'timestamp', 'AttributeType': 'N'}
            ],
            BillingMode='PAY_PER_REQUEST'  # Use on-demand capacity
        )
        
        # Wait for table creation to complete
        waiter = dynamodb_client.get_waiter('table_exists')
        waiter.wait(TableName=dynamodb_table_name)
        logger.info(f"DynamoDB table {dynamodb_table_name} created successfully")

def store_to_dynamodb(file_id, filename, status, content_data=None, error=None):
    """Store processing results or errors to DynamoDB."""
    try:
        timestamp = int(time.time())
        
        item = {
            'file_id': {'S': file_id},
            'timestamp': {'N': str(timestamp)},
            'filename': {'S': filename},
            'status': {'S': status}
        }
        
        if status == 'completed' and content_data:
            # Store markdown content
            if 'markdown' in content_data:
                item['markdown_content'] = {'S': content_data['markdown']}
            
            # Store structured content list
            if 'content_list' in content_data:
                item['content_list'] = {'S': json.dumps(content_data['content_list'])}
            
            # Store image file paths
            if 'images' in content_data:
                item['images'] = {'S': json.dumps(content_data['images'])}
                
            # Store output directory
            if 'output_dir' in content_data:
                item['output_dir'] = {'S': content_data['output_dir']}
        
        if status == 'failed' and error:
            item['error'] = {'S': str(error)}
        
        # Put item in DynamoDB
        dynamodb_client.put_item(
            TableName=dynamodb_table_name,
            Item=item
        )
        
        logger.info(f"Successfully stored {status} data in DynamoDB for {file_id}")
        return True
    
    except Exception as e:
        logger.error(f"Error storing data in DynamoDB: {str(e)}")
        return False

async def process_pdf(pdf_bytes, filename):
    """Process a PDF and store results in DynamoDB."""
    try:
        # Generate a unique ID for this PDF
        file_id = str(uuid.uuid4())
        logger.info(f"Processing PDF: {filename} (ID: {file_id})")
        
        # Create Dataset Instance
        ds = PymuDocDataset(pdf_bytes)
        
        # Determine processing method and apply it
        if ds.classify() == SupportedPdfParseMethod.OCR:
            logger.info(f"Using OCR mode for {filename}")
            infer_result = ds.apply(doc_analyze, ocr=True)
            pipe_result = infer_result.pipe_ocr_mode(local_image_writer)
        else:
            logger.info(f"Using text extraction mode for {filename}")
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
        
        # Create a results directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        
        # Save the final JSON results
        results_json = {
            'file_id': file_id,
            'filename': filename,
            'combined_text': combined_text.strip(),
            'status': 'completed',
            'processed_at': datetime.datetime.now().isoformat()
        }
        
        # Save the JSON file with the file_id as the name
        results_path = os.path.join(output_dir, f"{file_id}.json")
        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(results_json, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Successfully processed PDF: {filename}. Results saved to {results_path}")
        
        # Return only the essential information
        return {
            'file_id': file_id,
            'status': 'completed',
            'results_path': results_path,
            'text_length': len(combined_text)
        }
        
    except Exception as e:
        logger.error(f"Error processing PDF {filename}: {str(e)}")
        
        # Create a JSON with error information
        error_json = {
            'file_id': str(uuid.uuid4()),
            'filename': filename,
            'status': 'failed',
            'error': str(e),
            'processed_at': datetime.datetime.now().isoformat()
        }
        
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        
        # Save the error information
        error_path = os.path.join(output_dir, f"error_{error_json['file_id']}.json")
        with open(error_path, "w", encoding="utf-8") as f:
            json.dump(error_json, f, ensure_ascii=False, indent=2)
        
        # Re-raise the exception
        raise

@app.on_event("startup")
async def startup_event():
    """Initialize resources on startup."""
    try:
        # Create DynamoDB table if it doesn't exist
        # create_dynamodb_table_if_not_exists()
        logger.info("Service started successfully")
    except Exception as e:
        logger.error(f"Error during startup: {str(e)}")

@app.post("/process-pdf/")
async def upload_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """
    Upload a PDF file for processing
    
    This endpoint accepts a PDF file upload and processes it using OCR or text extraction.
    The processing happens asynchronously in the background.
    
    - **file**: The PDF file to process
    
    Returns:
        JSON with file_id and status information
    """
    try:
        # Validate file type
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Only PDF files are accepted")
        
        # Generate a unique ID for tracking
        file_id = str(uuid.uuid4())
        
        # Create a temporary file to store the uploaded PDF
        temp_file_path = os.path.join(output_dir, f"{file_id}_{file.filename}")
        
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Read the PDF content
        with open(temp_file_path, "rb") as f:
            pdf_bytes = f.read()
            logger.info(f"Read {len(pdf_bytes)} bytes from {file.filename}")
        
        # Add the processing task to background tasks
        background_tasks.add_task(process_pdf, pdf_bytes, file.filename)
        
        # Return initial response with tracking ID
        return JSONResponse(
            content={
                "message": "PDF uploaded successfully and processing has begun",
                "file_id": file_id,
                "filename": file.filename,
                "status": "processing"
            },
            status_code=202
        )
    
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error handling PDF upload: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing PDF: {str(e)}")

@app.get("/status/{file_id}")
async def get_processing_status(file_id: str):
    """
    Get the processing status of a PDF file
    
    - **file_id**: The ID of the file to check
    
    Returns:
        JSON with the processing status and result details
    """
    try:
        # Query DynamoDB for the file
        response = dynamodb_client.query(
            TableName=dynamodb_table_name,
            KeyConditionExpression='file_id = :file_id',
            ExpressionAttributeValues={
                ':file_id': {'S': file_id}
            },
            ScanIndexForward=False,  # Get most recent first
            Limit=1
        )
        
        if 'Items' in response and len(response['Items']) > 0:
            item = response['Items'][0]
            status = item.get('status', {}).get('S', 'unknown')
            
            result = {
                'file_id': file_id,
                'status': status,
                'timestamp': int(item.get('timestamp', {}).get('N', 0))
            }
            
            if 'filename' in item:
                result['filename'] = item['filename']['S']
            
            if status == 'completed':
                if 'markdown_content' in item:
                    # Return a truncated version of the markdown
                    markdown = item['markdown_content']['S']
                    result['markdown_preview'] = markdown[:500] + '...' if len(markdown) > 500 else markdown
                
                if 'output_dir' in item:
                    result['output_dir'] = item['output_dir']['S']
            
            elif status == 'failed' and 'error' in item:
                result['error'] = item['error']['S']
            
            return JSONResponse(content=result)
        else:
            return JSONResponse(
                content={'error': f'No processing record found for file ID: {file_id}'},
                status_code=404
            )
    
    except Exception as e:
        logger.error(f"Error retrieving status for {file_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving status: {str(e)}")

if __name__ == "__main__":
    # Run the FastAPI app with Uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)