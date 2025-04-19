#!/bin/bash

# Script to set up Redis on EC2

# Update system
sudo yum update -y

# Install Docker
sudo amazon-linux-extras install docker -y
sudo service docker start
sudo systemctl enable docker
sudo usermod -a -G docker ec2-user

# Create directories for Redis data
mkdir -p ~/redis/data

# Run Redis container
sudo docker run -d \
  --name redis \
  -p 6379:6379 \
  -v ~/redis/data:/data \
  --restart always \
  redis:7-alpine redis-server --appendonly yes

echo "Redis setup complete. The server is running on port 6379."
echo "Make note of this server's private IP to use in your OCR service .env file."
hostname -I | awk '{print $1}'