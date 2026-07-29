variable "region" {
  type = string
}

variable "name_prefix" {
  type = string
}

variable "profile" {
  type    = string
  default = "economy"

  validation {
    condition     = contains(["economy", "parity"], var.profile)
    error_message = "profile must be economy or parity."
  }
}

variable "image_tag" {
  type    = string
  default = "replace-with-immutable-image-tag"
}

variable "subnet_ids" {
  type        = list(string)
  description = "Existing private subnets; networking is account-specific."
}

variable "security_group_ids" {
  type        = list(string)
  description = "Existing ECS security groups."
}

variable "vpc_id" {
  type        = string
  description = "VPC containing the ECS task and Application Load Balancer."
}

variable "load_balancer_subnet_ids" {
  type        = list(string)
  description = "At least two reachable subnets for the public Application Load Balancer."
}

variable "load_balancer_security_group_ids" {
  type        = list(string)
  description = "Security groups permitting intended client traffic to the Application Load Balancer."
}

variable "bedrock_model_arn" {
  type        = string
  description = "Exact Bedrock foundation or inference-profile ARN allowed to the task role."
}

variable "bedrock_model_id" {
  type        = string
  description = "Bedrock model ID passed to the application as AI_MODEL."
}

variable "bedrock_embedding_model_id" {
  type        = string
  default     = ""
  description = "Optional distinct Bedrock embedding model ID; embeddings are disabled when empty."
}

variable "bedrock_embedding_model_arn" {
  type        = string
  default     = ""
  description = "Optional exact embedding model ARN added to InvokeModel permissions."
}

variable "mongo_secret_arn" {
  type        = string
  description = "Secrets Manager ARN containing the Mongo URI string."
}

variable "github_token_secret_arn" {
  type        = string
  description = "Secrets Manager ARN containing the GitHub token string."
}

variable "acm_certificate_arn" {
  type        = string
  description = "ACM certificate ARN for the public HTTPS Application Load Balancer listener."
}

variable "api_hostname" {
  type        = string
  description = "Custom public API hostname covered by acm_certificate_arn."
}

variable "route53_zone_id" {
  type        = string
  description = "Route 53 hosted zone ID for api_hostname."
}

variable "tags" {
  type    = map(string)
  default = {}
}
