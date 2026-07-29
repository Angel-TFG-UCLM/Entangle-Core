output "ecr_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "api_service_name" {
  value = module.runtime.service_name
}

output "cloudfront_domain_name" {
  value = aws_cloudfront_distribution.visualizer.domain_name
}

output "visualizer_bucket" {
  value = aws_s3_bucket.visualizer.bucket
}

output "api_endpoint" {
  value = "https://${var.api_hostname}"
}
