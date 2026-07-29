terraform {
  required_version = ">= 1.6.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 4.2"
    }
    azapi = {
      source  = "Azure/azapi"
      version = ">= 2.0"
    }
  }
}

provider "azurerm" {
  features {}
}

provider "azapi" {}

locals {
  suffix  = substr(replace(lower(var.name_prefix), "-", ""), 0, 12)
  tags    = merge(var.tags, { project = "entangle", profile = var.profile })
  economy = var.profile == "economy"
}

resource "azurerm_resource_group" "this" {
  name     = "rg-${var.name_prefix}"
  location = var.location
  tags     = local.tags
}

resource "azurerm_log_analytics_workspace" "this" {
  name                = "log-${local.suffix}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

resource "azurerm_container_registry" "this" {
  name                = "acr${local.suffix}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = "Basic"
  admin_enabled       = false
  tags                = local.tags
}

resource "azurerm_user_assigned_identity" "api" {
  name                = "id-${var.name_prefix}-api"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  tags                = local.tags
}

resource "azurerm_container_app_environment" "this" {
  name                       = "cae-${var.name_prefix}"
  location                   = azurerm_resource_group.this.location
  resource_group_name        = azurerm_resource_group.this.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id
  tags                       = local.tags
}

resource "azurerm_cognitive_account" "ai" {
  name                          = "ai-${local.suffix}"
  resource_group_name           = azurerm_resource_group.this.name
  location                      = var.ai_location
  kind                          = "AIServices"
  sku_name                      = "S0"
  custom_subdomain_name         = "ai-${local.suffix}"
  local_auth_enabled            = false
  public_network_access_enabled = true
  tags                          = local.tags

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_cognitive_deployment" "chat" {
  name                 = var.chat_model.deployment
  cognitive_account_id = azurerm_cognitive_account.ai.id

  model {
    format  = "OpenAI"
    name    = var.chat_model.name
    version = var.chat_model.version
  }

  sku {
    name     = "GlobalStandard"
    capacity = local.economy ? 20 : var.chat_model.capacity
  }
}

resource "azurerm_cognitive_deployment" "embeddings" {
  name                 = var.embedding_model.deployment
  cognitive_account_id = azurerm_cognitive_account.ai.id

  model {
    format  = "OpenAI"
    name    = var.embedding_model.name
    version = var.embedding_model.version
  }

  sku {
    name     = "GlobalStandard"
    capacity = local.economy ? 10 : var.embedding_model.capacity
  }
}

resource "azurerm_role_assignment" "ai_user" {
  scope                = azurerm_cognitive_account.ai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = azurerm_container_registry.this.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
}

resource "azurerm_role_assignment" "mongo_secret_reader" {
  scope                = var.mongo_key_vault_secret_resource_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
}

resource "azurerm_role_assignment" "github_secret_reader" {
  scope                = var.github_key_vault_secret_resource_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
}

module "runtime" {
  source                     = "./modules/runtime"
  name_prefix                = var.name_prefix
  resource_group_name        = azurerm_resource_group.this.name
  location                   = var.location
  environment_id             = azurerm_container_app_environment.this.id
  registry_server            = azurerm_container_registry.this.login_server
  identity_id                = azurerm_user_assigned_identity.api.id
  identity_client_id         = azurerm_user_assigned_identity.api.client_id
  image                      = var.api_image
  mongo_key_vault_secret_id  = var.mongo_key_vault_secret_id
  github_key_vault_secret_id = var.github_key_vault_secret_id
  ai_endpoint                = azurerm_cognitive_account.ai.endpoint
  ai_deployment              = azurerm_cognitive_deployment.chat.name
  frontend_url               = "https://${azurerm_static_web_app.visualizer.default_host_name}"
  deploy_staging             = var.deploy_staging
  min_replicas               = local.economy ? 0 : 1
  max_replicas               = local.economy ? 1 : 3

  depends_on = [
    azurerm_role_assignment.acr_pull,
    azurerm_role_assignment.ai_user,
    azurerm_role_assignment.mongo_secret_reader,
    azurerm_role_assignment.github_secret_reader,
  ]
}

resource "azurerm_static_web_app" "visualizer" {
  name                = "swa-${local.suffix}"
  resource_group_name = azurerm_resource_group.this.name
  location            = var.static_web_app_location
  sku_tier            = "Standard"
  sku_size            = "Standard"
  tags                = local.tags
}

resource "azurerm_monitor_action_group" "alerts" {
  count               = var.alert_email == "" ? 0 : 1
  name                = "entangle-alerts"
  resource_group_name = azurerm_resource_group.this.name
  short_name          = "entangle"
  tags                = local.tags

  email_receiver {
    name          = "operations"
    email_address = var.alert_email
  }
}

# Mongo vCore remains in reconciled Bicep because its ARM API and regions vary.
# Key Vault references keep MONGO_URI and GITHUB_TOKEN values out of Terraform state.
