# OCR Service Infrastructure

This repository contains infrastructure as code (IaC) for deploying a scalable OCR (Optical Character Recognition) service with Redis caching on AWS.

## Architecture Overview

The infrastructure consists of:

- **OCR Service**: Containerized application running on EC2 instances within an Auto Scaling Group
- **Redis**: In-memory database used for caching, running on a separate EC2 instance
- **Load Balancer**: Application Load Balancer distributing traffic to OCR service instances
- **Monitoring**: CloudWatch for logs and metrics collection

![Architecture Diagram](architecture_diagram.png)

## Prerequisites

Install [Packer](https://developer.hashicorp.com/packer/tutorials/docker-get-started/get-started-install-cli) on Amazon Linux

Install [Terraform](https://aws-quickstart.github.io/workshop-terraform-modules/40_setup_cloud9_ide/42_install_terraform_c9.html) 


## Infrastructure Components

### 1. AMI Creation (Packer)

Two custom AMIs are used in this architecture:

#### OCR Service AMI (`ami_ocr.pkr.hcl`)

The OCR Service AMI contains:
- Docker runtime
- Pre-pulled OCR service Docker image
- CloudWatch agent for monitoring
- Service startup scripts
- Default configuration

```bash
packer init ami_ocr.pkr.hcl
packer build ami_ocr.pkr.hcl
```

#### Redis AMI (`ami_redis.pkr.hcl`)

The Redis AMI contains:
- Docker runtime
- Redis server running in Docker
- CloudWatch agent for monitoring

```bash
packer init ami_redis.pkr.hcl
packer build ami_redis.pkr.hcl
```

### 2. Infrastructure Deployment (Terraform)

The Terraform configuration (`main.tf`) deploys:
- VPC with public subnets across two availability zones
- Security groups for OCR service and Redis
- Application Load Balancer with health checks
- Auto Scaling Group for OCR service instances
- Redis EC2 instance
- CloudWatch alarms and monitoring

```bash
terraform init
terraform apply
```

## Configuration

### Environment Variables

The OCR service uses the following environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| MONGO_CONNECTION_STRING | MongoDB connection string | mongodb+srv://username:password@your-cluster.mongodb.net/?retryWrites=true&w=majority |
| MONGO_DB_NAME | MongoDB database name | ocr_service |
| MONGO_COLLECTION_NAME | MongoDB collection name | documents |
| REDIS_HOST | Redis hostname/IP | Dynamically set by Terraform |
| REDIS_PORT | Redis port | 6379 |
| PORT | OCR service port | 8000 |

### CloudWatch Monitoring

The CloudWatch agent is configured to collect:
- System metrics (CPU, memory, disk)
- Application logs
- Docker container logs

## Usage

### Deploying the Infrastructure

1. Build the AMIs:
   ```bash
   packer build ami_ocr.pkr.hcl
   packer build ami_redis.pkr.hcl
   ```

2. Update the AMI IDs in `main.tf`:
   ```hcl
   variable "ami_ocr_id" {
     type    = string
     default = "ami-xxxxxxxxxxxxxxxxx" # Update with your OCR AMI ID
   }

   variable "ami_redis_id" {
     type    = string
     default = "ami-xxxxxxxxxxxxxxxxx" # Update with your Redis AMI ID
   }
   ```

3. Deploy with Terraform:
   ```bash
   terraform init
   terraform apply
   ```

4. After deployment, the OCR service will be accessible via the ALB DNS name:
   ```bash
   terraform output alb_dns_name
   ```

### API Endpoints

The OCR service exposes the following endpoints:

- `POST /extract` - Upload a PDF for OCR processing
- `GET /check-status/{document_id}` - Check processing status
- `GET /result/{document_id}` - Get processing results
- `GET /health` - Health check endpoint

Example usage:
```bash
# Upload a PDF for processing
curl -X POST -F "file=@document.pdf" -F "document_id=doc123" http://<alb_dns_name>/extract

# Check status
curl http://<alb_dns_name>/check-status/doc123

# Get results
curl http://<alb_dns_name>/result/doc123
```

## Security Considerations

- The OCR instances pull MongoDB credentials from environment variables
- Redis is only accessible from the OCR service instances
- SSH access is restricted by security groups
- All data is stored within the VPC

## Maintenance

### Scaling

The Auto Scaling Group is configured with:
- Minimum: 1 instance
- Maximum: 3 instances
- Desired: 2 instances

Adjust these values in `main.tf` based on your workload requirements.

### Updates

To update the OCR service:

1. Update the Docker image
2. Rebuild the AMI
3. Update the AMI ID in Terraform
4. Apply the changes

## Troubleshooting

### Common Issues

1. **OCR Service Not Starting**: Check Docker logs on the instance
   ```bash
   ssh ec2-user@<instance-ip>
   docker logs ocr-service
   ```

2. **Redis Connection Issues**: Verify Redis is running and security groups are configured correctly
   ```bash
   ssh ec2-user@<redis-ip>
   docker ps | grep redis
   ```

3. **CloudWatch Metrics Missing**: Ensure the CloudWatch agent is running
   ```bash
   sudo systemctl status amazon-cloudwatch-agent
   ```

## License

This project is licensed under the MIT License - see the LICENSE file for details.