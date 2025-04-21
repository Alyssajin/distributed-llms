packer {
  required_plugins {
    amazon = {
      version = ">= 1.0.0"
      source  = "github.com/hashicorp/amazon"
    }
  }
}

# Source Configuration (Amazon EBS)
source "amazon-ebs" "redis" {
  region        = "us-west-2"
  instance_type = "t3.micro"
  ssh_username  = "ec2-user"
  ami_name      = "redis-docker-{{timestamp}}"

  source_ami_filter {
    filters = {
      name                = "amzn2-ami-hvm-2.0.*-x86_64-gp2"
      "virtualization-type" = "hvm"
      "root-device-type"    = "ebs"
    }
    owners      = ["amazon"]
    most_recent = true
  }

  tags = {
    Name = "redis-docker"
  }
}

# Build Block
build {
  sources = ["source.amazon-ebs.redis"]

  # Install Docker and run Redis
  provisioner "shell" {
    inline = [
      # Update system
      "sudo yum update -y",
      
      # Install and start Docker
      "sudo yum install docker -y",
      "sudo systemctl start docker",
      "sudo systemctl enable docker",
      "sudo usermod -a -G docker ec2-user",
      
      # Create startup script
      "echo '#!/bin/bash' > /home/ec2-user/start-redis.sh",
      "echo 'docker run -d --name redis-server -p 6379:6379 --restart always redis/redis-stack-server:latest' >> /home/ec2-user/start-redis.sh",
      "chmod +x /home/ec2-user/start-redis.sh",
      
      # Add to crontab to start on boot
      "(crontab -l 2>/dev/null; echo '@reboot /home/ec2-user/start-redis.sh') | crontab -",
      
      # Run Redis
      "/home/ec2-user/start-redis.sh"
    ]
  }
}