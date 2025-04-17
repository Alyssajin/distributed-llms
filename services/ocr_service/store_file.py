import boto3

# Create a boto3 client for S3 with LocalStack endpoint
s3_client = boto3.client(
    's3',
    endpoint_url='https://localhost.localstack.cloud:4566',
    aws_access_key_id='test',  # Any value works for LocalStack
    aws_secret_access_key='test',  # Any value works for LocalStack
    region_name='us-east-1'
)

# Create a bucket
s3_client.create_bucket(Bucket='my-bucket')

# Upload a file
s3_client.upload_file(
    'test1.pdf',  # Local file path
    'my-bucket',               # Bucket name
    'test1.pdf'                 # S3 object key (name)
)

# List objects in the bucket
response = s3_client.list_objects_v2(Bucket='my-bucket')
for obj in response.get('Contents', []):
    print(obj['Key'])