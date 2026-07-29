variable "name_prefix" { type = string }
variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "environment_id" { type = string }
variable "registry_server" { type = string }
variable "identity_id" { type = string }
variable "identity_client_id" { type = string }
variable "image" { type = string }
variable "mongo_key_vault_secret_id" { type = string }
variable "github_key_vault_secret_id" { type = string }
variable "ai_endpoint" { type = string }
variable "ai_deployment" { type = string }
variable "frontend_url" { type = string }
variable "deploy_staging" { type = bool }
variable "min_replicas" { type = number }
variable "max_replicas" { type = number }

locals {
  environment = [
    { name = "ENVIRONMENT", value = "production" },
    { name = "AZURE_MANAGED_IDENTITY_CLIENT_ID", value = var.identity_client_id },
    { name = "ENTANGLE_DATA_MODE", value = "live" },
    { name = "ENTANGLE_DATABASE_PROVIDER", value = "mongo" },
    { name = "ENTANGLE_AI_PROVIDER", value = "azure-openai" },
    { name = "ENTANGLE_SEARCH_PROVIDER", value = "tavily" },
    { name = "ENTANGLE_GITHUB_PROVIDER", value = "github" },
    { name = "AZURE_AI_ENDPOINT", value = var.ai_endpoint },
    { name = "AZURE_AI_DEPLOYMENT", value = var.ai_deployment },
    { name = "MONGO_URI", secret_name = "mongo-uri" },
    { name = "GITHUB_TOKEN", secret_name = "github-token" },
    { name = "FRONTEND_URL", value = var.frontend_url },
  ]
}

resource "azurerm_container_app" "api" {
  name                         = "ca-${var.name_prefix}-api"
  resource_group_name          = var.resource_group_name
  container_app_environment_id = var.environment_id
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }

  registry {
    server   = var.registry_server
    identity = var.identity_id
  }

  secret {
    name                = "mongo-uri"
    key_vault_secret_id = var.mongo_key_vault_secret_id
    identity            = var.identity_id
  }

  secret {
    name                = "github-token"
    key_vault_secret_id = var.github_key_vault_secret_id
    identity            = var.identity_id
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    container {
      name   = "api"
      image  = var.image
      cpu    = 0.5
      memory = "1Gi"

      dynamic "env" {
        for_each = local.environment
        content {
          name        = env.value.name
          value       = try(env.value.value, null)
          secret_name = try(env.value.secret_name, null)
        }
      }

      liveness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/api/v1/health"
      }

      readiness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/api/v1/health/ready"
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }
}

resource "azurerm_container_app" "staging" {
  count                        = var.deploy_staging ? 1 : 0
  name                         = "ca-${var.name_prefix}-api-staging"
  resource_group_name          = var.resource_group_name
  container_app_environment_id = var.environment_id
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }

  registry {
    server   = var.registry_server
    identity = var.identity_id
  }

  secret {
    name                = "mongo-uri"
    key_vault_secret_id = var.mongo_key_vault_secret_id
    identity            = var.identity_id
  }

  secret {
    name                = "github-token"
    key_vault_secret_id = var.github_key_vault_secret_id
    identity            = var.identity_id
  }

  template {
    min_replicas = 0
    max_replicas = 1

    container {
      name   = "api"
      image  = var.image
      cpu    = 0.5
      memory = "1Gi"

      dynamic "env" {
        for_each = local.environment
        content {
          name        = env.value.name
          value       = try(env.value.value, null)
          secret_name = try(env.value.secret_name, null)
        }
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }
}

output "api_url" {
  value = "https://${azurerm_container_app.api.latest_revision_fqdn}"
}

output "staging_api_url" {
  value = try("https://${azurerm_container_app.staging[0].latest_revision_fqdn}", null)
}
