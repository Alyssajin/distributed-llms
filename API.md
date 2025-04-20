# OCR Service API Documentation

This document provides detailed information about the REST API endpoints available in the OCR Service.

## Base URL

All API endpoints are accessible at:

```
http://dsllms-lb-2095661368.us-west-2.elb.amazonaws.com
```

## Endpoints

### 1. Upload PDF for Processing

Uploads a PDF file and starts the OCR processing.

**Endpoint:** `/extract`  
**Method:** `POST`  
**Content-Type:** `multipart/form-data`

**Request Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| file | File | Yes | PDF file to process (must be a valid PDF) |
| document_id | String | Yes | Unique identifier for the document |

**Success Response:**
- **Status Code:** 200 OK
- **Content:**
```json
{
  "status": "ok"
}
```

**Error Responses:**
- **Status Code:** 400 Bad Request
  - **Content:** `{"detail": "Only PDF files are accepted"}`
  - Occurs when the uploaded file is not a PDF

- **Status Code:** 400 Bad Request
  - **Content:** `{"detail": "document_id is required"}`
  - Occurs when no document_id is provided

- **Status Code:** 500 Internal Server Error
  - **Content:** `{"detail": "Error processing PDF: [error message]"}`
  - Occurs when the service encounters an error during processing

**Notes:**
- The document processing happens asynchronously
- Use the `/check-status/{document_id}` endpoint to monitor processing status
- If a document with the same ID already exists, the service will return the current status of that document

**Example Request:**
```bash
curl -X POST \
  http://dsllms-lb-2095661368.us-west-2.elb.amazonaws.com/extract \
  -H 'Content-Type: multipart/form-data' \
  -F 'file=@/path/to/document.pdf' \
  -F 'document_id=doc123'
```

**Example Response:**
```json
{
  "status": "ok"
}
```

### 2. Check Processing Status

Checks the current processing status of a document.

**Endpoint:** `/check-status/{document_id}`  
**Method:** `GET`

**URL Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| document_id | String | Yes | The ID of the document to check |

**Success Responses:**
- **Status Code:** 200 OK
- **Content:**
```json
{
  "status": "processing"
}
```
OR
```json
{
  "status": "completed"
}
```
OR
```json
{
  "status": "error"
}
```

**Error Response:**
- **Status Code:** 404 Not Found
  - **Content:** `{"status": "unknown", "error": "No record found for document ID: [document_id]"}`
  - Occurs when the document ID does not exist

**Notes:**
- The status will be one of:
  - `processing`: Document is being processed
  - `completed`: Document processing is complete
  - `error`: An error occurred during processing

**Example Request:**
```bash
curl -X GET \
  http://dsllms-lb-2095661368.us-west-2.elb.amazonaws.com/check-status/doc123
```

**Example Response:**
```json
{
  "status": "processing"
}
```

### 3. Get Processing Results

Retrieves the text extracted from a processed document.

**Endpoint:** `/result/{document_id}`  
**Method:** `GET`

**URL Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| document_id | String | Yes | The ID of the document to retrieve |

**Success Response (Completed):**
- **Status Code:** 200 OK
- **Content:**
```json
{
  "document_id": "doc123",
  "text": "This is the full extracted text content from the PDF document...",
  "status": "completed"
}
```

**Success Response (In Progress):**
- **Status Code:** 200 OK
- **Content:**
```json
{
  "document_id": "doc123",
  "status": "processing",
  "message": "Document processing status: processing"
}
```

**Error Responses:**
- **Status Code:** 404 Not Found
  - **Content:** `{"error": "No record found for document ID: [document_id]"}`
  - Occurs when the document ID does not exist

- **Status Code:** 500 Internal Server Error
  - **Content:** `{"error": "Error retrieving result: [error message]"}`
  - Occurs when the service encounters an error retrieving the result

**Notes:**
- If processing is complete, the full extracted text is returned
- If processing is still in progress, only the status is returned
- The extracted text is stored in MongoDB for persistence

**Example Request:**
```bash
curl -X GET \
  http://dsllms-lb-2095661368.us-west-2.elb.amazonaws.com/result/doc123
```

**Example Response (Completed):**
```json
{
  "document_id": "doc123",
  "text": "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Nullam auctor, nisl eget ultricies lacinia, nisl nisl aliquet nisl, eget ultricies lacinia nisl nisl aliquet nisl.",
  "status": "completed"
}
```

### 4. Health Check

Checks the health status of the OCR service and its dependencies.

**Endpoint:** `/health`  
**Method:** `GET`

**Success Response:**
- **Status Code:** 200 OK
- **Content:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2025-04-19T15:30:45.123456",
  "dependencies": {
    "redis": "healthy",
    "mongodb": "healthy"
  }
}
```

**Other Responses:**
- **Status Code:** 200 OK (Degraded)
  - **Content:**
```json
{
  "status": "degraded",
  "version": "1.0.0",
  "timestamp": "2025-04-19T15:30:45.123456",
  "dependencies": {
    "redis": "healthy",
    "mongodb": "degraded"
  }
}
```

- **Status Code:** 503 Service Unavailable
  - **Content:**
```json
{
  "status": "unhealthy",
  "version": "1.0.0",
  "timestamp": "2025-04-19T15:30:45.123456",
  "dependencies": {
    "redis": "unhealthy",
    "mongodb": "healthy"
  }
}
```

**Notes:**
- The health check verifies connectivity to both Redis and MongoDB
- The overall status will be:
  - `healthy`: All dependencies are functioning properly
  - `degraded`: Some dependencies have issues but the service can still function
  - `unhealthy`: Critical dependencies are not functioning

**Example Request:**
```bash
curl -X GET \
  http://dsllms-lb-2095661368.us-west-2.elb.amazonaws.com/health
```

**Example Response:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2025-04-19T15:30:45.123456",
  "dependencies": {
    "redis": "healthy",
    "mongodb": "healthy"
  }
}
```

## Error Handling

The OCR Service uses the following HTTP status codes:

| Status Code | Description |
|-------------|-------------|
| 200 | Successful request |
| 400 | Bad Request - client error (invalid parameters) |
| 404 | Not Found - resource does not exist |
| 500 | Internal Server Error - something went wrong on the server |
| 503 | Service Unavailable - dependencies are unhealthy |

## Typical Usage Flow

1. **Upload a PDF:**
   - Send a POST request to `/extract` with the PDF file and a unique document_id

2. **Poll for completion:**
   - Periodically send GET requests to `/check-status/{document_id}` until the status is either "completed" or "error"

3. **Retrieve results:**
   - Once the status is "completed", send a GET request to `/result/{document_id}` to get the extracted text

## Notes on Rate Limiting and Performance

- The service uses an auto-scaling infrastructure to handle varying loads
- Processing time depends on the PDF size, complexity, and whether OCR is needed
- Consider implementing a reasonable polling interval (5-10 seconds) when checking status
- For large batch processing, stagger your uploads to avoid overwhelming the service