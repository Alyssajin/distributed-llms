packer {
  required_plugins {
    amazon = {
      version = ">= 1.0.0"
      source  = "github.com/hashicorp/amazon"
    }
  }
}

# ------------------------------------------------------------------------------
# Source Configuration (Amazon EBS)
# ------------------------------------------------------------------------------
source "amazon-ebs" "ocr_with_cloudwatch" {
  region  = "us-west-2"

  # We'll use a filter to pick the latest Amazon Linux 2 AMI
  source_ami_filter {
    filters = {
      name                = "amzn2-ami-hvm-2.0.*-x86_64-gp2"
      "virtualization-type" = "hvm"
      "root-device-type"    = "ebs"
    }
    owners      = ["amazon"]
    most_recent = true
  }

  instance_type    = "t2.large"
  ssh_username     = "ec2-user"
  ami_name         = "ocr-with-cloudwatch-{{timestamp}}"
  ami_description  = "Pre-baked AMI with OCR service, Docker and CloudWatch agent"

  tags = {
    Name = "ocr-with-cloudwatch"
  }
}

# ------------------------------------------------------------------------------
# Build Block: Provisioners
# ------------------------------------------------------------------------------
build {
  name    = "build-ocr-with-cloudwatch"
  sources = [
    "source.amazon-ebs.ocr_with_cloudwatch"
  ]

  # ----------------------------------------------------------------------------
  # First shell provisioner: install dependencies, clone, build
  # ----------------------------------------------------------------------------
  provisioner "shell" {
    # Comments in HCL are placed outside the array
    inline = [
      # 0) (Optional) Kill background yum so it doesn't lock:
      "sudo pkill -9 yum || true",
      "sudo rm -f /var/run/yum.pid || true",

      # 1) Now run yum update
      "sudo yum update -y",

      # 2) Install Docker
      "sudo yum install docker -y",
      "sudo systemctl start docker",
      "sudo systemctl enable docker",
      "sudo usermod -a -G docker ec2-user",

      # 3) Setup environment
      "mkdir -p /home/ec2-user/ocr-service/output",
      "cd /home/ec2-user",
      "touch .env",
      "echo 'MONGO_CONNECTION_STRING=mongodb+srv://username:password@your-cluster.mongodb.net/?retryWrites=true&w=majority' > /home/ec2-user/.env",
      "echo 'MONGO_DB_NAME=ocr_service' >> /home/ec2-user/.env",
      "echo 'MONGO_COLLECTION_NAME=documents' >> /home/ec2-user/.env",
      "echo 'REDIS_HOST=YOUR_REDIS_PRIVATE_IP' >> /home/ec2-user/.env",
      "echo 'REDIS_PORT=6379' >> /home/ec2-user/.env",
      "echo 'PORT=8000' >> /home/ec2-user/.env",

      # 4) Pull the OCR service Docker image:
      "sudo docker pull alyssajin/ocr-service:latest"
    ]
  }

  # ----------------------------------------------------------------------------
  # File provisioner: upload CloudWatch agent config
  # ----------------------------------------------------------------------------
  provisioner "file" {
    source      = "cloudwatch-agent-config.json"
    destination = "/tmp/cloudwatch-agent-config.json"
  }

  # ----------------------------------------------------------------------------
  # Second shell provisioner: configure CloudWatch Agent + systemd service
  # ----------------------------------------------------------------------------
  provisioner "shell" {
    inline = [
      # 5) Install CloudWatch agent
      "sudo yum install -y amazon-cloudwatch-agent",
      
      # 6) Move config and set up the agent to start at boot
      "sudo cp /tmp/cloudwatch-agent-config.json /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json",
      "sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a stop",
      "sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a start -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json -m ec2",

      # 7) Create a startup script for the OCR service
      "cat > /home/ec2-user/start-ocr-service.sh << 'EOF'
#!/bin/bash
docker pull alyssajin/ocr-service:latest
docker rm -f ocr-service 2>/dev/null || true
docker run -d \\\\
  --name ocr-service \\\\
  -p 8000:8000 \\\\
  --env-file /home/ec2-user/.env \\\\
  -v /home/ec2-user/ocr-service/output:/app/output \\\\
  --restart always \\\\
  alyssajin/ocr-service:latest
EOF",
      "chmod +x /home/ec2-user/start-ocr-service.sh",
      
      # 8) Add crontab entry to run the script at reboot
      "(crontab -l 2>/dev/null; echo '@reboot /home/ec2-user/start-ocr-service.sh') | crontab -",
      
      # 9) Start the service for the first time
      "/home/ec2-user/start-ocr-service.sh",
      
      # 10) Verify the service is running
      "sleep 10",
      "docker ps | grep ocr-service || echo 'WARNING: OCR service did not start properly'"
    ]
  }
}