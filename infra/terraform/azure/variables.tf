variable "name_prefix" {
  type = string
}

variable "location" {
  type    = string
  default = "spaincentral"
}

variable "ai_location" {
  type    = string
  default = "swedencentral"
}

variable "static_web_app_location" {
  type    = string
  default = "westeurope"
}

variable "profile" {
  type    = string
  default = "economy"

  validation {
    condition     = contains(["economy", "parity"], var.profile)
    error_message = "profile must be economy or parity."
  }
}

variable "api_image" {
  type        = string
  description = "Prebuilt image reference; Terraform does not build or push images."
}

variable "mongo_key_vault_secret_id" {
  type        = string
  description = "Versioned or versionless Key Vault secret URI for MONGO_URI; no secret value enters Terraform."
}

variable "github_key_vault_secret_id" {
  type        = string
  description = "Versioned or versionless Key Vault secret URI for GITHUB_TOKEN; no secret value enters Terraform."
}

variable "key_vault_id" {
  type        = string
  description = "Existing Key Vault resource ID granting the API identity Secrets User access."
}

variable "deploy_staging" {
  type    = bool
  default = true
}

variable "alert_email" {
  type    = string
  default = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "chat_model" {
  type = object({
    name       = string
    version    = string
    deployment = string
    capacity   = number
  })
  default = {
    name       = "gpt-5-mini"
    version    = "2025-08-07"
    deployment = "gpt-5-mini"
    capacity   = 250
  }
}

variable "embedding_model" {
  type = object({
    name       = string
    version    = string
    deployment = string
    capacity   = number
  })
  default = {
    name       = "text-embedding-3-small"
    version    = "1"
    deployment = "text-embedding-3-small"
    capacity   = 120
  }
}
