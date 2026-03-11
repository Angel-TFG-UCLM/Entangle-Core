// ===========================================
// Entangle Backend - Infraestructura Azure
// Azure Container Apps + Container Registry
// ===========================================
targetScope = 'subscription'

// ============= PARÁMETROS =============
@minLength(1)
@maxLength(64)
@description('Nombre del entorno (ej: dev, prod)')
param environmentName string

@minLength(1)
@description('Región principal para todos los recursos')
param location string

@secure()
@description('URI de conexión a MongoDB/CosmosDB')
param mongoUri string = ''

@secure()
@description('Token de GitHub para la API')
param githubToken string = ''

@description('URL del Frontend para configurar CORS (ej: https://mi-frontend.azurestaticapps.net)')
param frontendUrl string = ''

@description('Endpoint del servicio Azure AI Foundry')
param azureAiEndpoint string = 'https://entangle-ai-resource.services.ai.azure.com'

@description('Nombre del proyecto en Azure AI Foundry')
param azureAiProject string = 'entangle-ai'

@description('Nombre del deployment del modelo (ej: gpt-4o)')
param azureAiDeployment string = 'gpt-4o'

@secure()
@description('API Key del servicio Azure AI Foundry')
param azureAiApiKey string = ''

// ============= VARIABLES =============
var abbrs = loadJsonContent('./abbreviations.json')
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = {
  'azd-env-name': environmentName
  project: 'entangle'
  environment: environmentName
}

// ============= RESOURCE GROUP =============
resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: '${abbrs.resourcesResourceGroups}${environmentName}'
  location: location
  tags: tags
}

// ============= LOG ANALYTICS =============
module logAnalytics './core/monitor/loganalytics.bicep' = {
  name: 'log-analytics'
  scope: rg
  params: {
    name: '${abbrs.operationalInsightsWorkspaces}${resourceToken}'
    location: location
    tags: tags
  }
}

// ============= CONTAINER REGISTRY =============
module containerRegistry './core/host/container-registry.bicep' = {
  name: 'container-registry'
  scope: rg
  params: {
    name: '${abbrs.containerRegistryRegistries}${resourceToken}'
    location: location
    tags: tags
  }
}

// ============= CONTAINER APPS ENVIRONMENT =============
module containerAppsEnvironment './core/host/container-apps-environment.bicep' = {
  name: 'container-apps-environment'
  scope: rg
  params: {
    name: '${abbrs.appManagedEnvironments}${resourceToken}'
    location: location
    tags: tags
    logAnalyticsCustomerId: logAnalytics.outputs.customerId
    logAnalyticsSharedKey: logAnalytics.outputs.sharedKey
  }
}

// ============= API CONTAINER APP =============
module api './core/host/container-app.bicep' = {
  name: 'api'
  scope: rg
  params: {
    name: '${abbrs.appContainerApps}${resourceToken}-api'
    location: location
    tags: union(tags, { 'azd-service-name': 'api' })
    containerAppsEnvironmentName: containerAppsEnvironment.outputs.name
    containerRegistryName: containerRegistry.outputs.name
    containerCpuCoreCount: '1.0'
    containerMemory: '2.0Gi'
    containerMaxReplicas: 3
    containerMinReplicas: 0
    targetPort: 8000
    env: [
      {
        name: 'ENVIRONMENT'
        value: 'production'
      }
      {
        name: 'DEBUG'
        value: 'False'
      }
      {
        name: 'PORT'
        value: '8000'
      }
      {
        name: 'MONGO_DB_NAME'
        value: 'quantum_github'
      }
      {
        name: 'FRONTEND_URL'
        value: frontendUrl
      }
      {
        name: 'MONGO_URI'
        secretRef: 'mongo-uri'
      }
      {
        name: 'GITHUB_TOKEN'
        secretRef: 'github-token'
      }
      {
        name: 'AZURE_AI_ENDPOINT'
        value: azureAiEndpoint
      }
      {
        name: 'AZURE_AI_PROJECT'
        value: azureAiProject
      }
      {
        name: 'AZURE_AI_DEPLOYMENT'
        value: azureAiDeployment
      }
      {
        name: 'AZURE_AI_API_KEY'
        secretRef: 'azure-ai-api-key'
      }
    ]
    secrets: [
      {
        name: 'mongo-uri'
        value: !empty(mongoUri) ? mongoUri : 'placeholder-configure-after-deploy'
      }
      {
        name: 'github-token'
        value: !empty(githubToken) ? githubToken : 'placeholder-configure-after-deploy'
      }
      {
        name: 'azure-ai-api-key'
        value: !empty(azureAiApiKey) ? azureAiApiKey : 'placeholder-configure-after-deploy'
      }
    ]
  }
}

// ============= OUTPUTS =============
output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = containerRegistry.outputs.loginServer
output AZURE_CONTAINER_REGISTRY_NAME string = containerRegistry.outputs.name
output AZURE_CONTAINER_APPS_ENVIRONMENT_NAME string = containerAppsEnvironment.outputs.name
output SERVICE_API_URI string = api.outputs.uri
output SERVICE_API_NAME string = api.outputs.name
