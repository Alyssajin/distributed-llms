#!/bin/bash

# Script to set up OCR service on EC2

# Update system
sudo yum update -y

# Install Docker
sudo amazon-linux-extras install docker -y
sudo service docker start
sudo systemctl enable docker
sudo usermod -a -G docker ec2-user

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/download/1.29.2/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Create app directory
mkdir -p ~/ocr-service
cd ~/ocr-service

# Copy files from your local machine to this directory (manually or through scp)
# You should copy:
# - ocr_service.py
# - config.py
# - download_models_hf.py
# - requirements.txt
# - Dockerfile
# - .env (with updated Redis host)

echo "OCR service setup complete. Now copy your application files to this server."