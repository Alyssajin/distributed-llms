import os
import time
import json
import logging
import sys
import boto3

from magic_pdf.data.data_reader_writer import S3DataReader, S3DataWriter
from magic_pdf.data.dataset import PymuDocDataset
from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze
from magic_pdf.config.enums import SupportedPdfParseMethod

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# S3 Configuration
bucket_name = "my-bucket"  # replace with real bucket name
ak = "test"  # replace with real s3 access key
sk = "test"  # replace with real s3 secret key
endpoint_url = "https://localhost.localstack.cloud:4566"  # replace with real s3 endpoint_url

# Output directories
output_prefix = "output/"  # where to store results
failed_prefix = "failed/"  # where to move failed files

# Local directories
local_image_dir = "output/images"
local_md_dir = "output"
image_dir = str(os.path.basename(local_image_dir))

# Ensure local directories exist
os.makedirs(local_image_dir, exist_ok=True)
os.makedirs(local_md_dir, exist_ok=True)

# Initialize S3 clients
reader = S3DataReader('', bucket_name, ak, sk, endpoint_url)  # Base reader without prefix
writer = S3DataWriter(output_prefix, bucket_name, ak, sk, endpoint_url)
image_writer = S3DataWriter(f"{output_prefix}images", bucket_name, ak, sk, endpoint_url)
md_writer = S3DataWriter(output_prefix, bucket_name, ak, sk, endpoint_url)

def move_file(source_key, dest_prefix):
    """Move a file from source_key to destination prefix."""
    try:
        import boto3
        s3_client = boto3.client(
            's3',
            endpoint_url=endpoint_url,
            aws_access_key_id=ak,
            aws_secret_access_key=sk,
            region_name='us-east-1'
        )
        
        filename = os.path.basename(source_key)
        dest_key = f"{dest_prefix}{filename}"
        
        # Copy the object
        s3_client.copy_object(
            Bucket=bucket_name,
            CopySource={'Bucket': bucket_name, 'Key': source_key},
            Key=dest_key
        )
        
        # Delete the original
        s3_client.delete_object(Bucket=bucket_name, Key=source_key)
        
        return dest_key
    except Exception as e:
        logger.error(f"Error moving file {source_key}: {str(e)}")
        return None

def process_file(file_key):
    """Process a single PDF file from S3."""
    logger.info(f"Processing file: {file_key}")
    
    try:
        # Full S3 path for reading
        s3_path = f"s3://{bucket_name}/{file_key}"
        
        # Get filename without extension for output naming
        name_without_suffix = os.path.basename(file_key).split(".")[0]
        
        # Read PDF bytes
        pdf_bytes = reader.read(s3_path)
        
        # Create Dataset Instance
        ds = PymuDocDataset(pdf_bytes)
        
        # Determine processing method and apply it
        if ds.classify() == SupportedPdfParseMethod.OCR:
            logger.info(f"Using OCR mode for {name_without_suffix}")
            infer_result = ds.apply(doc_analyze, ocr=True)
            pipe_result = infer_result.pipe_ocr_mode(image_writer)
        else:
            logger.info(f"Using text extraction mode for {name_without_suffix}")
            infer_result = ds.apply(doc_analyze, ocr=False)
            pipe_result = infer_result.pipe_txt_mode(image_writer)
        
        # Dump and upload markdown
        pipe_result.dump_md(md_writer, f"{name_without_suffix}.md", image_dir)
        
        # Dump and upload content list
        pipe_result.dump_content_list(md_writer, f"{name_without_suffix}_content_list.json", image_dir)
        
        # Write status file to indicate completion
        status = {
            "status": "completed",
            "timestamp": time.time(),
            "file": file_key,
            "outputs": {
                "markdown": f"{output_prefix}{name_without_suffix}.md",
                "content_list": f"{output_prefix}{name_without_suffix}_content_list.json"
            }
        }
        
        md_writer.write(f"{name_without_suffix}_status.json", json.dumps(status, indent=2).encode('utf-8'))
        
        # Move original file to output directory (optional)
        move_file(file_key, output_prefix)
        
        logger.info(f"Successfully processed {name_without_suffix}")
        return True
        
    except Exception as e:
        logger.error(f"Error processing {file_key}: {str(e)}")
        try:
            # Move to failed folder
            move_file(file_key, failed_prefix)
            
            # Write error status
            error_status = {
                "status": "failed",
                "timestamp": time.time(),
                "file": file_key,
                "error": str(e)
            }
            
            name_without_suffix = os.path.basename(file_key).split(".")[0]
            md_writer.write(
                f"{name_without_suffix}_error.json", 
                json.dumps(error_status, indent=2).encode('utf-8')
            )
        except Exception as inner_e:
            logger.error(f"Error handling failure for {file_key}: {str(inner_e)}")
        
        return False

def main():
    """
    Main function that continuously processes files from an SQS queue.
    
    This script will keep running indefinitely, waiting for messages
    from SQS that contain file keys to process.
    """
    logger.info("Starting OCR service in continuous mode")
    
    # Initialize SQS client
    sqs = boto3.client(
        'sqs',
        region_name='us-east-1',  # Replace with your region
        aws_access_key_id=ak,
        aws_secret_access_key=sk
    )
    
    # URL of your SQS queue
    queue_url = 'https://sqs.us-east-1.amazonaws.com/123456789012/pdf-processing-queue'  # Replace with your queue URL
    
    # Continuously poll for messages
    while True:
        try:
            # Receive message from SQS queue
            response = sqs.receive_message(
                QueueUrl=queue_url,
                AttributeNames=['All'],
                MaxNumberOfMessages=1,
                MessageAttributeNames=['All'],
                VisibilityTimeout=600,  # 10 minutes to process the file
                WaitTimeSeconds=20  # Long polling to reduce costs
            )
            
            # Check if we got a message
            if 'Messages' in response:
                for message in response['Messages']:
                    receipt_handle = message['ReceiptHandle']
                    
                    try:
                        # Parse message body
                        message_body = json.loads(message['Body'])
                        file_key = message_body.get('file_key')
                        
                        if file_key:
                            logger.info(f"Processing file: {file_key}")
                            success = process_file(file_key)
                            
                            if success:
                                logger.info(f"Successfully processed file: {file_key}")
                                # Delete message from queue after successful processing
                                sqs.delete_message(
                                    QueueUrl=queue_url,
                                    ReceiptHandle=receipt_handle
                                )
                            else:
                                logger.error(f"Failed to process file: {file_key}")
                                # Don't delete the message, let it become visible again
                        else:
                            logger.error("Received message without file_key")
                            # Delete invalid messages to avoid reprocessing
                            sqs.delete_message(
                                QueueUrl=queue_url,
                                ReceiptHandle=receipt_handle
                            )
                    except Exception as e:
                        logger.error(f"Error processing message: {str(e)}")
            else:
                # No messages, wait a bit to avoid excessive polling
                logger.debug("No messages available, waiting...")
                time.sleep(5)
                
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt, exiting")
            break
        except Exception as e:
            logger.error(f"Error in main loop: {str(e)}")
            # Wait before trying again to avoid rapid failures
            time.sleep(5)
            
if __name__ == "__main__":
    main()