variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "distributed-api-gateway"
}

variable "environment" {
  description = "Environment (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "docker_image_tag" {
  description = "Docker image tag to deploy"
  type        = string
  default     = "latest"
}

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.medium"
}

variable "desired_gateway_count" {
  description = "Desired number of gateway tasks"
  type        = number
  default     = 2
}

variable "desired_worker_count" {
  description = "Desired number of worker tasks"
  type        = number
  default     = 2
}

variable "min_gateway_count" {
  description = "Minimum number of gateway tasks"
  type        = number
  default     = 1
}

variable "max_gateway_count" {
  description = "Maximum number of gateway tasks"
  type        = number
  default     = 10
}

variable "min_worker_count" {
  description = "Minimum number of worker tasks"
  type        = number
  default     = 1
}

variable "max_worker_count" {
  description = "Maximum number of worker tasks"
  type        = number
  default     = 10
}

variable "cpu_threshold" {
  description = "CPU utilization threshold for scaling"
  type        = number
  default     = 70
}

variable "memory_threshold" {
  description = "Memory utilization threshold for scaling"
  type        = number
  default     = 80
}

variable "kafka_broker_count" {
  description = "Number of MSK Kafka brokers"
  type        = number
  default     = 3
}

variable "kafka_volume_size" {
  description = "Kafka broker storage size in GB"
  type        = number
  default     = 100
}

variable "redis_auth_token" {
  description = "Redis AUTH token password"
  type        = string
  sensitive   = true
  default     = "change-me-in-production-use-ssm"
}
