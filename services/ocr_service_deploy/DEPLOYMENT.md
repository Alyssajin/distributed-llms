# OCR Service Deployment Guide

This guide provides step-by-step instructions for deploying the OCR service architecture, including the Redis EC2 instance, OCR service instances, Auto Scaling, and Load Balancer.

## Prerequisites

- AWS account with access to EC2, Auto Scaling, and Load Balancer services
- Familiarity with AWS Console
- SSH key pair for EC2 access
- MongoDB Atlas account with a configured cluster and connection string

## 1. Set Up the Redis EC2 Instance

### 1.1. Launch an EC2 Instance

1. Navigate to the EC2 dashboard in AWS Console
2. Click "Launch Instance"
3. Configure the instance:
   - Name: `redis-server`
   - AMI: Amazon Linux 2
   - Instance type: t2.medium (recommended for production) or t2.micro (for testing)
   - Key pair: Select your existing key pair
   - Network settings: 
     - Create a security group that allows inbound traffic on port 6379 from your OCR service security group
     - Allow SSH (port 22) from your IP address for administration

4. Launch the instance

### 1.2. Install and Configure Redis

1. Connect to your instance via SSH:
   ```bash
   ssh -i your-key.pem ec2-user@your-redis-instance-ip
   ```

2. Run the following commands to install and configure Docker:
   ```bash
   sudo yum update -y
   sudo yum install docker -y
   sudo systemctl start docker
   sudo systemctl enable docker
   sudo usermod -a -G docker ec2-user
   ```

3. Log out and log back in for group changes to take effect:
   ```bash
   exit
   ssh -i your-key.pem ec2-user@your-redis-instance-ip
   ```

4. Pull and run the Redis container:
   ```bash
   docker run -d --name redis-stack-server -p 6379:6379 redis/redis-stack-server:latest
   ```

5. Verify Redis is running:
   ```bash
   docker ps
   ```

6. Note the private IP address of your Redis instance:
   ```bash
   curl http://169.254.169.254/latest/meta-data/local-ipv4
   ```
   This IP will be needed for your OCR service configuration.

## 2. Set Up the OCR Service AMI

### 2.1. Launch a Temporary EC2 Instance

1. Navigate to the EC2 dashboard in AWS Console
2. Click "Launch Instance"
3. Configure the instance:
   - Name: `ocr-service-template`
   - AMI: Amazon Linux 2
   - Instance type: t2.medium (recommended for OCR processing)
   - Key pair: Select your existing key pair
   - Network settings: Allow SSH (port 22) from your IP and HTTP (port 8000)

4. Launch the instance

### 2.2. Install and Configure the OCR Service

1. Connect to your instance via SSH:
   ```bash
   ssh -i your-key.pem ec2-user@your-instance-ip
   ```

2. Run the following commands to install and configure Docker:
   ```bash
   sudo yum update -y
   sudo amazon-linux-extras install docker -y
   sudo yum install docker -y
   sudo systemctl start docker
   sudo systemctl enable docker
   sudo usermod -a -G docker ec2-user
   ```

3. Create necessary directories:
   ```bash
   mkdir -p /home/ec2-user/ocr-service/output
   ```

4. Create a `.env` file with environment variables:
   ```bash
   cd /home/ec2-user/ocr-service
   touch .env
   ```

5. Edit the `.env` file with your configuration:
   ```bash
   nano .env
   ```

   Add the following content (replace with your actual values):
   ```
   MONGO_CONNECTION_STRING=mongodb+srv://username:password@your-cluster.mongodb.net/?retryWrites=true&w=majority
   MONGO_DB_NAME=ocr_service
   MONGO_COLLECTION_NAME=documents
   REDIS_HOST=YOUR_REDIS_PRIVATE_IP
   REDIS_PORT=6379
   PORT=8000
   ```

6. Log out and log back in for group changes to take effect:
   ```bash
   exit
   ssh -i your-key.pem ec2-user@your-instance-ip
   ```

7. Test the Docker installation by running a simple container:
   ```bash
   newgrp docker
   docker run hello-world
   ```

8. Pull the OCR service Docker image:
   ```bash
   docker pull alyssajin/ocr-service:latest
   ```

9. Test run the OCR service:
   ```bash
   docker run -d \
     --name ocr-service \
     -p 8000:8000 \
     --env-file /home/ec2-user/ocr-service/.env \
     -v /home/ec2-user/ocr-service/output:/app/output \
     --restart always \
     alyssajin/ocr-service:latest
   ```

10. Verify the service is running:
    ```bash
    docker ps
    curl http://localhost:8000/health
    ```

11. Create a startup script to ensure the container starts on boot:
    ```bash
    cat > /home/ec2-user/start-ocr-service.sh << 'EOF'
    #!/bin/bash
    docker pull alyssajin/ocr-service:latest
    docker rm -f ocr-service 2>/dev/null || true
    docker run -d \
      --name ocr-service \
      -p 8000:8000 \
      --env-file /home/ec2-user/ocr-service/.env \
      -v /home/ec2-user/ocr-service/output:/app/output \
      --restart always \
      alyssajin/ocr-service:latest
    EOF
    
    chmod +x /home/ec2-user/start-ocr-service.sh
    ```

12. Set up crontab to run the script on reboot:
    ```bash
    (crontab -l 2>/dev/null; echo "@reboot /home/ec2-user/start-ocr-service.sh") | crontab -
    ```

### 2.3. Create an AMI from the Instance

1. Stop the instance from the AWS Console
2. Right-click on the instance and select "Image and templates" > "Create image"
3. Configure the image:
   - Image name: `ocr-service-ami`
   - Image description: "AMI for OCR Service with Docker"
4. Create the image and note the AMI ID for use in the Auto Scaling Group

## 3. Set Up Auto Scaling

### 3.1. Create a Launch Template

1. Navigate to the EC2 dashboard > Launch Templates
2. Click "Create launch template"
3. Configure the template:
   - Name: `ocr-service-launch-template`
   - AMI: Select the AMI ID created in the previous step
   - Instance type: t2.medium
   - Key pair: Select your existing key pair
   - Security group: Allow inbound traffic on port 8000 from the load balancer security group
   - Advanced details:
     - IAM instance profile: If you have specific IAM roles for EC2
     - User data:
       ```bash
       #!/bin/bash
       /home/ec2-user/start-ocr-service.sh
       ```

4. Create the launch template

### 3.2. Create an Auto Scaling Group

1. Navigate to Auto Scaling Groups in the EC2 dashboard
2. Click "Create Auto Scaling group"
3. Configure the Auto Scaling group:
   - Name: `ocr-service-asg`
   - Launch template: Select the launch template created earlier
   - VPC and subnets: Select your VPC and at least two subnets in different Availability Zones
   - Load balancing: Select "Attach to an existing load balancer" (after creating the load balancer)
   - Group size:
     - Desired capacity: 3
     - Minimum capacity: 2
     - Maximum capacity: 10
   - Scaling policies:
     - Target tracking scaling policy
     - Metric type: Average CPU utilization
     - Target value: 70%
   - Add notifications if desired

4. Create Auto Scaling group

## 4. Set Up the Load Balancer

### 4.1. Create a Target Group

1. Navigate to Target Groups in the EC2 dashboard
2. Click "Create target group"
3. Configure the target group:
   - Target type: Instances
   - Name: `ocr-service-target-group`
   - Protocol: HTTP
   - Port: 8000
   - VPC: Select your VPC
   - Health check settings:
     - Protocol: HTTP
     - Path: /health
     - Advanced health check settings:
       - Port: traffic-port
       - Healthy threshold: 2
       - Unhealthy threshold: 3
       - Timeout: 5
       - Interval: 30
   - Register targets: Skip for now (Auto Scaling will register targets)

4. Create target group

### 4.2. Create an Application Load Balancer

1. Navigate to Load Balancers in the EC2 dashboard
2. Click "Create load balancer"
3. Choose "Application Load Balancer"
4. Configure the load balancer:
   - Name: `ocr-service-lb`
   - Scheme: Internet-facing
   - IP address type: IPv4
   - VPC: Select your VPC
   - Mappings: Select at least two Availability Zones and subnets
   - Security group: Create a new security group that allows HTTP (port 80) from anywhere
   - Listeners and routing:
     - HTTP on port 80, forward to the target group created earlier
   - Add a custom domain and SSL certificate if needed

5. Create load balancer
6. Note the DNS name of the load balancer (e.g., `dsllms-lb-2095661368.us-west-2.elb.amazonaws.com`)

### 4.3. Update Auto Scaling Group with Load Balancer

1. Return to your Auto Scaling group
2. Edit the Auto Scaling group
3. Under Load balancing, select "Attach to an existing load balancer"
4. Choose "Choose from your load balancer target groups"
5. Select the target group created earlier
6. Save changes

## 5. Verify Deployment

1. Wait for Auto Scaling to launch instances (check the Activity tab in the Auto Scaling group)
2. Verify instances are registered with the target group (check the Targets tab in the target group)
3. Test the load balancer endpoint:
   ```bash
   curl http://your-load-balancer-dns/health
   ```

4. Use Postman or another HTTP client to test uploading a PDF:
   ```
   POST http://your-load-balancer-dns/extract
   Form-data:
     - file: (select a PDF file)
     - document_id: test-document-1
   ```

## 6. Monitoring and Maintenance

### 6.1. Monitoring

- Set up CloudWatch Alarms for Auto Scaling group metrics
- Monitor target group health
- Check instance logs via SSH or CloudWatch Logs

### 6.2. Scaling Adjustments

- Modify Auto Scaling group settings as needed based on observed load
- Adjust target tracking values or add step scaling policies for more granular control

### 6.3. Updates

To update the OCR service:

1. Create a new instance from your existing AMI
2. Pull the latest Docker image and test
3. Create a new AMI
4. Update the launch template with the new AMI
5. Perform a rolling update of the Auto Scaling group