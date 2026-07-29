variable "name" { type = string }
variable "cluster_arn" { type = string }
variable "execution_role_arn" { type = string }
variable "task_role_arn" { type = string }
variable "image" { type = string }
variable "subnet_ids" { type = list(string) }
variable "security_group_ids" { type = list(string) }
variable "log_group" { type = string }
variable "target_group_arn" { type = string }
variable "desired_count" { type = number }
variable "mongo_secret_arn" { type = string }
variable "github_token_secret_arn" { type = string }
variable "ai_model" { type = string }
variable "embedding_model" { type = string }
variable "frontend_url" { type = string }

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = var.image
      essential = true
      portMappings = [
        { containerPort = 8000 }
      ]
      environment = [
        { name = "ENVIRONMENT", value = "production" },
        { name = "ENTANGLE_DATA_MODE", value = "live" },
        { name = "ENTANGLE_DATABASE_PROVIDER", value = "mongo" },
        { name = "ENTANGLE_AI_PROVIDER", value = "bedrock" },
        { name = "ENTANGLE_SEARCH_PROVIDER", value = "disabled" },
        { name = "ENTANGLE_GITHUB_PROVIDER", value = "github" },
        { name = "AI_MODEL", value = var.ai_model },
        { name = "AI_EMBEDDING_MODEL", value = var.embedding_model },
        { name = "ENTANGLE_EMBEDDINGS_ENABLED", value = var.embedding_model == "" ? "false" : "true" },
        { name = "FRONTEND_URL", value = var.frontend_url },
      ]
      secrets = [
        { name = "MONGO_URI", valueFrom = var.mongo_secret_arn },
        { name = "GITHUB_TOKEN", valueFrom = var.github_token_secret_arn },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = var.log_group
          awslogs-region        = split(":", var.cluster_arn)[3]
          awslogs-stream-prefix = "api"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "api" {
  name            = "${var.name}-api"
  cluster         = var.cluster_arn
  task_definition = aws_ecs_task_definition.api.arn
  launch_type     = "FARGATE"
  desired_count   = var.desired_count

  load_balancer {
    target_group_arn = var.target_group_arn
    container_name   = "api"
    container_port   = 8000
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = var.security_group_ids
    assign_public_ip = false
  }
}

output "service_name" {
  value = aws_ecs_service.api.name
}
