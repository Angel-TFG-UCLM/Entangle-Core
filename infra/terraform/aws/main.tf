terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

locals {
  name              = "${var.name_prefix}-${var.profile}"
  tags              = merge(var.tags, { Project = "entangle", Profile = var.profile })
  economy           = var.profile == "economy"
  alb_name          = "ent-${substr(md5(local.name), 0, 12)}"
  target_group_name = "ent-api-${substr(md5("${local.name}-api"), 0, 12)}"
}

resource "aws_ecr_repository" "api" {
  name                 = "${local.name}/api"
  image_tag_mutability = "IMMUTABLE"
  tags                 = local.tags

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/entangle/${local.name}/api"
  retention_in_days = local.economy ? 14 : 30
  tags              = local.tags
}

resource "aws_ecs_cluster" "this" {
  name = "entangle-${local.name}"
  tags = local.tags

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

data "aws_iam_policy_document" "ecs_task_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task_execution" {
  name               = "entangle-${local.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "task" {
  name               = "entangle-${local.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
  tags               = local.tags
}

data "aws_iam_policy_document" "task_bedrock" {
  statement {
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = compact([var.bedrock_model_arn, var.bedrock_embedding_model_arn])
  }

}

data "aws_iam_policy_document" "task_runtime_secrets" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.mongo_secret_arn, var.github_token_secret_arn]
  }
}

resource "aws_iam_role_policy" "task_runtime_secrets" {
  name   = "read-runtime-secrets"
  role   = aws_iam_role.task_execution.id
  policy = data.aws_iam_policy_document.task_runtime_secrets.json
}

resource "aws_iam_role_policy" "task_bedrock" {
  name   = "invoke-selected-bedrock-model"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task_bedrock.json
}

resource "aws_lb" "api" {
  name               = local.alb_name
  internal           = false
  load_balancer_type = "application"
  security_groups    = var.load_balancer_security_group_ids
  subnets            = var.load_balancer_subnet_ids
  tags               = local.tags
}

resource "aws_lb_target_group" "api" {
  name        = local.target_group_name
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id
  tags        = local.tags

  health_check {
    path = "/api/v1/health/ready"
  }
}

resource "aws_lb_listener" "api" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "api_https" {
  load_balancer_arn = aws_lb.api.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = var.acm_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

}

resource "aws_route53_record" "api" {
  zone_id = var.route53_zone_id
  name    = var.api_hostname
  type    = "A"

  alias {
    name                   = aws_lb.api.dns_name
    zone_id                = aws_lb.api.zone_id
    evaluate_target_health = true
  }
}

module "runtime" {
  source                  = "./modules/runtime"
  name                    = local.name
  cluster_arn             = aws_ecs_cluster.this.arn
  execution_role_arn      = aws_iam_role.task_execution.arn
  task_role_arn           = aws_iam_role.task.arn
  image                   = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
  subnet_ids              = var.subnet_ids
  security_group_ids      = var.security_group_ids
  log_group               = aws_cloudwatch_log_group.api.name
  target_group_arn        = aws_lb_target_group.api.arn
  desired_count           = 1
  mongo_secret_arn        = var.mongo_secret_arn
  github_token_secret_arn = var.github_token_secret_arn
  ai_model                = var.bedrock_model_id
  embedding_model         = var.bedrock_embedding_model_id
  frontend_url            = "https://${aws_cloudfront_distribution.visualizer.domain_name}"
}

resource "aws_s3_bucket" "visualizer" {
  bucket_prefix = "entangle-${local.name}-"
  tags          = local.tags
}

resource "aws_s3_bucket_public_access_block" "visualizer" {
  bucket                  = aws_s3_bucket.visualizer.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_cloudfront_origin_access_control" "visualizer" {
  name                              = "entangle-${local.name}"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "visualizer" {
  enabled             = true
  default_root_object = "index.html"
  tags                = local.tags

  origin {
    domain_name              = aws_s3_bucket.visualizer.bucket_regional_domain_name
    origin_id                = "visualizer"
    origin_access_control_id = aws_cloudfront_origin_access_control.visualizer.id
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "visualizer"
    viewer_protocol_policy = "redirect-to-https"

    forwarded_values {
      query_string = false

      cookies {
        forward = "none"
      }
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

data "aws_iam_policy_document" "visualizer_oac" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.visualizer.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.visualizer.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "visualizer_oac" {
  bucket = aws_s3_bucket.visualizer.id
  policy = data.aws_iam_policy_document.visualizer_oac.json
}

# Bedrock and runtime credentials are supplied by least-privilege IAM plus Secrets Manager.
