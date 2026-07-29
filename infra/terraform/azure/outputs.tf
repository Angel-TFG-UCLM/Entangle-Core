output "api_url" { value = module.runtime.api_url }
output "staging_api_url" { value = module.runtime.staging_api_url }
output "static_web_app_url" { value = azurerm_static_web_app.visualizer.default_host_name }
output "api_managed_identity_client_id" { value = azurerm_user_assigned_identity.api.client_id }
output "ai_endpoint" { value = azurerm_cognitive_account.ai.endpoint }
