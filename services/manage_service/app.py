"""
Purpose

Shows how to implement a REST API using AWS Chalice. This REST API processes PDF files
to extract text and structure using OCR and layout analysis techniques.
"""

import os
import json
import logging
import urllib.parse
import base64
import tempfile

import chalice
from chalice import CORSConfig

app = chalice.Chalice(app_name="pdf-extract-service")
app.debug = True  # Set this to False for production use.

# Configure CORS to allow requests from any origin
cors_config = CORSConfig(
    allow_origin="*",
    allow_headers=["Content-Type", "X-Amz-Date", "Authorization", "X-Api-Key"],
    max_age=600,
    expose_headers=["X-Special-Header"],
    allow_credentials=True
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# S3 configuration
BUCKET_NAME = os.environ.get("BUCKET_NAME", "my-bucket")
ACCESS_KEY = os.environ.get("AWS_ACCESS_KEY_ID", "test")
SECRET_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "test")
ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL", "https://localhost.localstack.cloud:4566")
OUTPUT_PREFIX = os.environ.get("S3_OUTPUT_PREFIX", "pdf-extract-output")
IMAGE_PREFIX = os.environ.get("S3_IMAGE_PREFIX", f"{OUTPUT_PREFIX}/images")

# Initialize S3 readers and writers
reader = S3DataReader(OUTPUT_PREFIX, BUCKET_NAME, ACCESS_KEY, SECRET_KEY, ENDPOINT_URL)
writer = S3DataWriter(OUTPUT_PREFIX, BUCKET_NAME, ACCESS_KEY, SECRET_KEY, ENDPOINT_URL)
image_writer = S3DataWriter(IMAGE_PREFIX, BUCKET_NAME, ACCESS_KEY, SECRET_KEY, ENDPOINT_URL)
md_writer = S3DataWriter(OUTPUT_PREFIX, BUCKET_NAME, ACCESS_KEY, SECRET_KEY, ENDPOINT_URL)


def verify_pdf_file(file_key=None, file_content=None):
    """
    Verifies that the file is a valid PDF. Unacceptable input raises a BadRequestError.

    :param file_key: The S3 key of the PDF file.
    :param file_content: The binary content of the PDF file.
    """
    if file_key is not None and not file_key.lower().endswith('.pdf'):
        raise chalice.BadRequestError(
            f"File must be a PDF. Got: {file_key}"
        )
    
    if file_content is not None:
        # Check if content starts with PDF signature %PDF
        if not file_content.startswith(b'%PDF'):
            raise chalice.BadRequestError(
                "Invalid PDF file. File does not start with %PDF signature."
            )


@app.route("/", methods=["GET"])
def index():
    """
    Returns information about the API.
    """
    return {
        "service": "PDF Extract Service",
        "endpoints": {
            "GET /": "API information",
            "GET /files": "List processed PDF files",
            "GET /files/{file_key}": "Get PDF processing results",
            "POST /files": "Process a new PDF file (from S3)",
            "POST /upload": "Upload and process a PDF file directly",
            "DELETE /files/{file_key}": "Delete PDF processing results"
        }
    }


@app.route("/files", methods=["GET"])
def list_files():
    """
    Lists all processed PDF files.
    
    :return: List of files in the output directory.
    """
    try:
        # List objects with the specified prefix
        s3_client = reader.s3_client
        response = s3_client.list_objects_v2(
            Bucket=BUCKET_NAME,
            Prefix=OUTPUT_PREFIX
        )
        
        files = []
        if 'Contents' in response:
            for obj in response['Contents']:
                if obj['Key'].endswith('.md') or obj['Key'].endswith('.json'):
                    files.append({
                        'key': obj['Key'],
                        'size': obj['Size'],
                        'last_modified': obj['LastModified'].isoformat()
                    })
        
        return {"files": files}
    except Exception as e:
        logger.error(f"Error listing files: {str(e)}")
        raise chalice.ChaliceViewError(f"Error listing files: {str(e)}")


@app.route("/files/{file_key}", methods=["GET"])
def get_file_results(file_key):
    """
    Gets the processing results for a specific PDF file.
    
    :param file_key: The key of the PDF file in S3.
    :return: The processing results.
    """
    file_key = urllib.parse.unquote(file_key)
    
    try:
        # Get the base name without extension
        name_without_suffix = os.path.basename(file_key).split(".")[0]
        
        # Try to get the markdown result
        md_key = f"{name_without_suffix}.md"
        md_content = None
        try:
            md_content = reader.read(f"{OUTPUT_PREFIX}/{md_key}").decode('utf-8')
        except Exception:
            logger.info(f"Markdown file not found: {md_key}")
        
        # Try to get the content list result
        content_list_key = f"{name_without_suffix}_content_list.json"
        content_list = None
        try:
            content_list_data = reader.read(f"{OUTPUT_PREFIX}/{content_list_key}")
            content_list = json.loads(content_list_data.decode('utf-8'))
        except Exception:
            logger.info(f"Content list file not found: {content_list_key}")
        
        # Try to get the middle JSON result
        middle_json_key = f"{name_without_suffix}_middle.json"
        middle_json = None
        try:
            middle_json_data = reader.read(f"{OUTPUT_PREFIX}/{middle_json_key}")
            middle_json = json.loads(middle_json_data.decode('utf-8'))
        except Exception:
            logger.info(f"Middle JSON file not found: {middle_json_key}")
        
        if md_content is None and content_list is None and middle_json is None:
            raise chalice.NotFoundError(f"No processing results found for {file_key}")
        
        result = {
            "file_key": file_key,
            "markdown": md_content,
            "content_list": content_list,
            "middle_json": middle_json
        }
        
        return result
    except chalice.NotFoundError:
        raise
    except Exception as e:
        logger.error(f"Error getting file results: {str(e)}")
        raise chalice.ChaliceViewError(f"Error getting file results: {str(e)}")


@app.route("/files", methods=["POST"])
def process_s3_file():
    """
    Processes a PDF file that is already in S3.
    
    Request JSON body should contain:
    {
        "file_key": "path/to/pdf/in/s3.pdf"
    }
    
    :return: The processing status and file identifier.
    """
    try:
        request_body = app.current_request.json_body
        
        if not request_body or "file_key" not in request_body:
            raise chalice.BadRequestError("Missing required parameter: file_key")
        
        file_key = request_body["file_key"]
        verify_pdf_file(file_key=file_key)
        
        # Construct the S3 URI
        s3_uri = f"s3://{BUCKET_NAME}/{file_key}"
        
        # Process the PDF file
        process_result = process_pdf(s3_uri)
        
        return {
            "status": "success",
            "message": "PDF processing completed successfully",
            "file_key": file_key,
            "result": process_result
        }
    except chalice.BadRequestError:
        raise
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}")
        raise chalice.ChaliceViewError(f"Error processing file: {str(e)}")


@app.route("/upload", methods=["POST"], content_types=["application/pdf", "multipart/form-data"])
def upload_and_process():
    """
    Uploads and processes a PDF file directly.
    
    The PDF can be uploaded either as raw binary data with content-type application/pdf
    or as a multipart form with a field named 'file'.
    
    :return: The processing status and file identifier.
    """
    try:
        content_type = app.current_request.headers.get('content-type', '')
        file_content = None
        file_name = None
        
        if content_type.startswith('application/pdf'):
            # Direct PDF upload
            file_content = app.current_request.raw_body
            file_name = app.current_request.headers.get('x-file-name', 'uploaded.pdf')
        elif content_type.startswith('multipart/form-data'):
            # Multipart form upload
            form_data = app.current_request.json_body
            if 'file' not in form_data:
                raise chalice.BadRequestError("Missing required field: file")
            
            file_data = form_data['file']
            if isinstance(file_data, dict) and 'content' in file_data and 'filename' in file_data:
                file_content = base64.b64decode(file_data['content'])
                file_name = file_data['filename']
            else:
                raise chalice.BadRequestError("Invalid file format in multipart form")
        else:
            raise chalice.BadRequestError(
                "Unsupported content-type. Use application/pdf or multipart/form-data"
            )
        
        if not file_content:
            raise chalice.BadRequestError("Empty file content")
        
        verify_pdf_file(file_content=file_content)
        
        # Save the file to S3
        file_key = f"uploads/{file_name}"
        s3_client = writer.s3_client
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=file_key,
            Body=file_content,
            ContentType='application/pdf'
        )
        
        # Construct the S3 URI
        s3_uri = f"s3://{BUCKET_NAME}/{file_key}"
        
        # Process the PDF file
        process_result = process_pdf(s3_uri)
        
        return {
            "status": "success",
            "message": "PDF uploaded and processed successfully",
            "file_key": file_key,
            "result": process_result
        }
    except chalice.BadRequestError:
        raise
    except Exception as e:
        logger.error(f"Error uploading and processing file: {str(e)}")
        raise chalice.ChaliceViewError(f"Error uploading and processing file: {str(e)}")


@app.route("/files/{file_key}", methods=["DELETE"])
def delete_file_results(file_key):
    """
    Deletes the processing results for a specific PDF file.
    
    :param file_key: The key of the PDF file in S3.
    :return: The deletion status.
    """
    file_key = urllib.parse.unquote(file_key)
    
    try:
        # Get the base name without extension
        name_without_suffix = os.path.basename(file_key).split(".")[0]
        
        # List of result files to delete
        result_keys = [
            f"{OUTPUT_PREFIX}/{name_without_suffix}.md",
            f"{OUTPUT_PREFIX}/{name_without_suffix}_content_list.json",
            f"{OUTPUT_PREFIX}/{name_without_suffix}_middle.json",
            f"{OUTPUT_PREFIX}/{name_without_suffix}_model.pdf",
            f"{OUTPUT_PREFIX}/{name_without_suffix}_layout.pdf",
            f"{OUTPUT_PREFIX}/{name_without_suffix}_spans.pdf"
        ]
        
        # Delete all result files
        s3_client = writer.s3_client
        deleted_files = []
        
        for key in result_keys:
            try:
                s3_client.delete_object(
                    Bucket=BUCKET_NAME,
                    Key=key
                )
                deleted_files.append(key)
            except Exception:
                logger.info(f"File not found or could not be deleted: {key}")
        
        # Delete image files
        try:
            response = s3_client.list_objects_v2(
                Bucket=BUCKET_NAME,
                Prefix=f"{IMAGE_PREFIX}/{name_without_suffix}"
            )
            
            if 'Contents' in response:
                for obj in response['Contents']:
                    s3_client.delete_object(
                        Bucket=BUCKET_NAME,
                        Key=obj['Key']
                    )
                    deleted_files.append(obj['Key'])
        except Exception as e:
            logger.info(f"Error deleting image files: {str(e)}")
        
        if not deleted_files:
            raise chalice.NotFoundError(f"No processing results found for {file_key}")
        
        return {
            "status": "success",
            "message": "Processing results deleted successfully",
            "deleted_files": deleted_files
        }
    except chalice.NotFoundError:
        raise
    except Exception as e:
        logger.error(f"Error deleting file results: {str(e)}")
        raise chalice.ChaliceViewError(f"Error deleting file results: {str(e)}")


def process_pdf(pdf_file_name):
    """
    Processes a PDF file and returns the results.
    
    :param pdf_file_name: The S3 URI of the PDF file.
    :return: A dictionary with the processing results.
    """
    # Get the base name without extension
    name_without_suffix = os.path.basename(pdf_file_name).split(".")[0]
    
    # Create local directories for output
    local_image_dir = "output/images"
    local_md_dir = "output"
    os.makedirs(local_image_dir, exist_ok=True)
    os.makedirs(local_md_dir, exist_ok=True)
    
    # Get image directory name
    image_dir = os.path.basename(local_image_dir)
    
    # Read PDF bytes
    pdf_bytes = reader.read(pdf_file_name)
    
    # Create dataset instance
    ds = PymuDocDataset(pdf_bytes)
    
    # Determine processing method and apply
    if ds.classify() == SupportedPdfParseMethod.OCR:
        # OCR mode
        infer_result = ds.apply(doc_analyze, ocr=True)
        pipe_result = infer_result.pipe_ocr_mode(image_writer)
    else:
        # Text mode
        infer_result = ds.apply(doc_analyze, ocr=False)
        pipe_result = infer_result.pipe_txt_mode(image_writer)
    
    # Draw model result on each page
    model_output_path = os.path.join(local_md_dir, f"{name_without_suffix}_model.pdf")
    infer_result.draw_model(model_output_path)
    
    # Get model inference result
    model_inference_result = infer_result.get_infer_res()
    
    # Draw layout result on each page
    layout_output_path = os.path.join(local_md_dir, f"{name_without_suffix}_layout.pdf")
    pipe_result.draw_layout(layout_output_path)
    
    # Draw spans result on each page
    spans_output_path = os.path.join(local_md_dir, f"{name_without_suffix}_spans.pdf")
    pipe_result.draw_span(spans_output_path)
    
    # Dump markdown
    md_filename = f"{name_without_suffix}.md"
    pipe_result.dump_md(md_writer, md_filename, image_dir)
    
    # Dump content list
    content_list_filename = f"{name_without_suffix}_content_list.json"
    pipe_result.dump_content_list(md_writer, content_list_filename, image_dir)
    
    # Get markdown content
    md_content = pipe_result.get_markdown(image_dir)
    
    # Get content list content
    content_list_content = pipe_result.get_content_list(image_dir)
    
    # Get middle json
    middle_json_content = pipe_result.get_middle_json()
    
    # Dump middle json
    middle_json_filename = f"{name_without_suffix}_middle.json"
    pipe_result.dump_middle_json(md_writer, middle_json_filename)
    
    # Upload the local files to S3
    for filename in [f"{name_without_suffix}_model.pdf", f"{name_without_suffix}_layout.pdf", f"{name_without_suffix}_spans.pdf"]:
        local_path = os.path.join(local_md_dir, filename)
        if os.path.exists(local_path):
            with open(local_path, 'rb') as f:
                writer.s3_client.put_object(
                    Bucket=BUCKET_NAME,
                    Key=f"{OUTPUT_PREFIX}/{filename}",
                    Body=f.read(),
                    ContentType='application/pdf'
                )
    
    # Return processing results
    return {
        "markdown_url": f"s3://{BUCKET_NAME}/{OUTPUT_PREFIX}/{md_filename}",
        "content_list_url": f"s3://{BUCKET_NAME}/{OUTPUT_PREFIX}/{content_list_filename}",
        "middle_json_url": f"s3://{BUCKET_NAME}/{OUTPUT_PREFIX}/{middle_json_filename}",
        "model_pdf_url": f"s3://{BUCKET_NAME}/{OUTPUT_PREFIX}/{name_without_suffix}_model.pdf",
        "layout_pdf_url": f"s3://{BUCKET_NAME}/{OUTPUT_PREFIX}/{name_without_suffix}_layout.pdf",
        "spans_pdf_url": f"s3://{BUCKET_NAME}/{OUTPUT_PREFIX}/{name_without_suffix}_spans.pdf"
    }