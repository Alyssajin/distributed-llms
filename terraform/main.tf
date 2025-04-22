############
# Provider
############
provider "aws" {
  region = "us-west-2" # or any preferred region
  # If Cloud9 is already set up with an IAM role that allows provisioning,
  # you likely don't need explicit access/secret keys. 
  # Otherwise, you can specify or set environment variables.
  # access_key = "<YOUR-ACCESS-KEY>"
  # secret_key = "<YOUR-SECRET-KEY>"
}

############
# Variables
############

variable "ami_ocr_id" {
  type    = string
  default = "ami-08e4e35cccc6189f4" # Change to your AMI ID
}

variable "ami_redis_id" {
  type    = string
  default = "ami-0c55b159cbfafe1f0" # Change to your AMI ID
}

############
# VPC & Subnet
############
resource "aws_vpc" "ocr_vpc" {
  cidr_block = "10.0.0.0/16"
  tags = {
    Name = "ocr-vpc"
  }
}

resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.ocr_vpc.id
  tags = {
    Name = "ocr-igw"
  }
}

# Subnet A (us-west-2a)
resource "aws_subnet" "ocr_subnet_a" {
  vpc_id                  = aws_vpc.ocr_vpc.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = "us-west-2a"
  map_public_ip_on_launch = true
  tags = {
    Name = "ocr-subnet-a"
  }
}

resource "aws_route_table_association" "assoc_a" {
  subnet_id      = aws_subnet.ocr_subnet_a.id
  route_table_id = aws_route_table.ocr_route_table.id
}

# Subnet B (us-west-2b)
resource "aws_subnet" "ocr_subnet_b" {
  vpc_id                  = aws_vpc.ocr_vpc.id
  cidr_block              = "10.0.2.0/24"
  availability_zone       = "us-west-2b"
  map_public_ip_on_launch = true
  tags = {
    Name = "ocr-subnet-b"
  }
}

resource "aws_route_table_association" "assoc_b" {
  subnet_id      = aws_subnet.ocr_subnet_b.id
  route_table_id = aws_route_table.ocr_route_table.id
}

resource "aws_route_table" "ocr_route_table" {
  vpc_id = aws_vpc.ocr_vpc.id
  tags = {
    Name = "ocr-rt"
  }
}

resource "aws_route" "ocr_route" {
  route_table_id         = aws_route_table.ocr_route_table.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.igw.id
}

############
# Security Groups
############
# For the EC2 instances that will run the OCR server
resource "aws_security_group" "ec2_ocr_sg" {
  name        = "ec2-ocr-sg"
  description = "Allow inbound traffic from ALB and SSH"
  vpc_id      = aws_vpc.ocr_vpc.id

  # Allow inbound HTTP from ALB (or all for quick testing).
  ingress {
    description = "HTTP from ALB"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] # Ideally, we would restrict to the ALB SG.
  }

  # Allow inbound SSH for debugging
  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Allow public traffic on 80 to reach ALB
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Outbound to anywhere
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "ec2-ocr-sg"
  }
}

resource "aws_security_group" "ec2_redis_sg" {
  name        = "ec2-redis-sg"
  description = "Allow inbound traffic from OCR and SSH"
  vpc_id      = aws_vpc.ocr_vpc.id

  # Allow inbound Redis from OCR servers
  ingress {
    description     = "Redis from OCR servers"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ec2_ocr_sg.id]
  }

  # Allow inbound SSH for debugging
  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  
  # Outbound to anywhere
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "ec2-redis-sg"
  }
}

############
# ALB
############
resource "aws_lb" "ocr_alb" {
  name               = "ocr-alb"
  load_balancer_type = "application"
  # Provide subnets in at least two AZs
  subnets = [
    aws_subnet.ocr_subnet_a.id,
    aws_subnet.ocr_subnet_b.id
  ]
  security_groups = [aws_security_group.ec2_ocr_sg.id] # For inbound rules, or a separate ALB SG
  ip_address_type = "ipv4"

  tags = {
    Name = "ocr-alb"
  }
}

resource "aws_lb_target_group" "ocr_tg" {
  name        = "ocr-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.ocr_vpc.id
  target_type = "instance"
  health_check {
    port                = "traffic-port"
    protocol            = "HTTP"
    path                = "/health" # health checks
    matcher             = "200-399"
    healthy_threshold   = 2
    unhealthy_threshold = 2
    timeout             = 5
    interval            = 30
  }

  tags = {
    Name = "ocr-tg"
  }
}

resource "aws_lb_listener" "ocr_http_listener" {
  load_balancer_arn = aws_lb.ocr_alb.arn
  port              = "8000"
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.ocr_tg.arn
  }

  tags = {
    Name = "ocr-alb-listener"
  }
}

############
# EC2 Auto Scaling Setup
############

# User data script for OCR service
locals {
  ocr_userdata = <<-EOF
    #!/bin/bash
    # Configure environment variables for OCR service
    cat > /home/ec2-user/.env << EOT
    MONGO_CONNECTION_STRING=mongodb+srv://username:password@your-cluster.mongodb.net/?retryWrites=true&w=majority
    MONGO_DB_NAME=ocr_service
    MONGO_COLLECTION_NAME=documents
    REDIS_HOST=${aws_instance.redis_instance.private_ip}
    REDIS_PORT=6379
    PORT=8000
    EOT

    # Restart OCR service to apply new environment
    /home/ec2-user/start-ocr-service.sh
    EOF
}

resource "aws_launch_template" "ocr_lt" {
  name_prefix   = "ocr-lt-"
  image_id      = var.ami_ocr_id 
  instance_type = "t2.large"

  user_data = base64encode(local.ocr_userdata)

  vpc_security_group_ids = [aws_security_group.ec2_ocr_sg.id]

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name = "ocr-ec2"
    }
  }
}

resource "aws_autoscaling_group" "ocr_asg" {
  name             = "ocr-asg"
  max_size         = 3
  min_size         = 1
  desired_capacity = 2
  launch_template {
    id      = aws_launch_template.ocr_lt.id
    version = "$Latest"
  }
  vpc_zone_identifier = [
    aws_subnet.ocr_subnet_a.id,
    aws_subnet.ocr_subnet_b.id
  ]

  target_group_arns = [aws_lb_target_group.ocr_tg.arn]

  tag {
    key                 = "Name"
    value               = "ocr-ec2"
    propagate_at_launch = true
  }

  lifecycle {
    create_before_destroy = true
  }
}

############
# EC2 Instance for Redis
############
resource "aws_instance" "redis_instance" {
    ami             = var.ami_redis_id
    instance_type   = "t2.micro"
    subnet_id       = aws_subnet.ocr_subnet_a.id
    security_groups = [aws_security_group.ec2_redis_sg.id]
    
    tags = {
        Name = "redis-instance"
    }
}

############
# Outputs
############
output "alb_dns_name" {
  description = "DNS name of the ALB"
  value       = aws_lb.ocr_alb.dns_name
}

output "redis_public_ip" {
  description = "Public IP of the Redis instance"
  value       = aws_instance.redis_instance.public_ip
}