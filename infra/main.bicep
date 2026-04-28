// ===========================================
// Entangle - Infraestructura Azure (deploy completo)
// Replica el entorno de producción 1-a-1:
//   • Resource Group + Log Analytics
//   • Azure Container Registry
//   • Container Apps Environment
//   • Container App API (entangle-api)
//   • Container App Staging (entangle-api-stagging)
//   • Cosmos DB for MongoDB vCore (cluster M30)
//   • Azure AI Foundry (AIServices) + GPT-4o deployment
//   • Azure Static Web App (Standard) para el frontend
//   • Role assignments para que las MIs invoquen AI Foundry
// ===========================================
targetScope = 'subscription'

// ============= PARÁMETROS GENERALES =============
@minLength(1)
@maxLength(64)
@description('Nombre del entorno (ej: dev, prod). Se usa para nombrar el resource group.')
param environmentName string

@minLength(1)
@description('Región principal (Container Apps + ACR + Log Analytics).')
param location string

// ─── Regiones específicas por servicio (motivo: cuotas/disponibilidad) ───
@description('Región del cluster Mongo vCore. Northeurope tiene mejor disponibilidad de M30 que Spain Central.')
param databaseLocation string = 'northeurope'

@description('Región del recurso Azure AI Foundry. Sweden Central tiene capacidad GPT-4o.')
param aiLocation string = 'swedencentral'

@description('Región de la Static Web App. West Europe es la única región europea que las soporta en muchas suscripciones.')
param staticWebAppLocation string = 'westeurope'

// ─── Secretos del API ───
@secure()
@description('Token de GitHub (PAT) para llamar a la API de GitHub. Si está vacío se inserta un placeholder y el API no funcionará.')
param githubToken string = ''

@description('Usuario administrador del cluster Mongo vCore.')
param mongoAdminUsername string = 'entangleadmin'

@secure()
@description('Contraseña del administrador Mongo vCore. Cumplir requisitos: 8-256 caracteres, una mayúscula, una minúscula, un número.')
param mongoAdminPassword string

// ─── Tier del cluster Mongo (parametrizable para no quemar dinero en dev) ───
@description('Tier de cómputo del cluster Mongo vCore.')
@allowed([
  'M10'
  'M20'
  'M25'
  'M30'
  'M40'
  'M50'
])
param mongoComputeTier string = 'M30'

@description('Storage del cluster Mongo en GB.')
param mongoStorageGb int = 256

// ─── AI Foundry ───
@description('Nombre del modelo a desplegar (gpt-4o, gpt-4o-mini, etc.).')
param aiModelName string = 'gpt-4o'

@description('Versión del modelo. La versión por defecto coincide con la usada en producción.')
param aiModelVersion string = '2024-08-06'

@description('Nombre del deployment del modelo (lo que tu app pone en AZURE_AI_DEPLOYMENT).')
param aiDeploymentName string = 'gpt-4o'

@description('Capacidad del deployment en miles de TPM.')
param aiDeploymentCapacity int = 169

// ─── Container App API ───
@description('CPU del container API (vCPUs). Producción actual usa 0.5.')
param apiCpu string = '0.5'

@description('Memoria del container API. Producción actual usa 1.0Gi.')
param apiMemory string = '1.0Gi'

@description('Réplicas mínimas del API.')
param apiMinReplicas int = 0

@description('Réplicas máximas del API.')
param apiMaxReplicas int = 1

@description('Si es true, también se despliega el Container App de staging.')
param deployStaging bool = true

// ============= VARIABLES =============
var abbrs = loadJsonContent('./abbreviations.json')
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = {
  'azd-env-name': environmentName
  project: 'entangle'
  environment: environmentName
}

// Convención de nombres centralizada
var rgName = '${abbrs.resourcesResourceGroups}${environmentName}'
var logName = '${abbrs.operationalInsightsWorkspaces}${resourceToken}'
var acrName = '${abbrs.containerRegistryRegistries}${resourceToken}'
var caeName = '${abbrs.appManagedEnvironments}${resourceToken}'
var apiAppName = '${abbrs.appContainerApps}${resourceToken}-api'
var stagingAppName = '${abbrs.appContainerApps}${resourceToken}-api-staging'
var mongoName = '${abbrs.documentDBMongoClusters}${resourceToken}'
var aiName = '${abbrs.cognitiveServicesAccounts}${resourceToken}'
var swaName = '${abbrs.webStaticSites}${resourceToken}'

// ============= RESOURCE GROUP =============
resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: rgName
  location: location
  tags: tags
}

// ============= LOG ANALYTICS =============
module logAnalytics './core/monitor/loganalytics.bicep' = {
  name: 'log-analytics'
  scope: rg
  params: {
    name: logName
    location: location
    tags: tags
  }
}

// ============= CONTAINER REGISTRY =============
module containerRegistry './core/host/container-registry.bicep' = {
  name: 'container-registry'
  scope: rg
  params: {
    name: acrName
    location: location
    tags: tags
  }
}

// ============= CONTAINER APPS ENVIRONMENT =============
module containerAppsEnvironment './core/host/container-apps-environment.bicep' = {
  name: 'container-apps-environment'
  scope: rg
  params: {
    name: caeName
    location: location
    tags: tags
    logAnalyticsCustomerId: logAnalytics.outputs.customerId
    logAnalyticsSharedKey: logAnalytics.outputs.sharedKey
  }
}

// ============= COSMOS DB FOR MONGODB (vCore) =============
module mongoCluster './core/database/cosmos-mongo-vcore.bicep' = {
  name: 'mongo-vcore'
  scope: rg
  params: {
    name: mongoName
    location: databaseLocation
    tags: tags
    computeTier: mongoComputeTier
    storageSizeGb: mongoStorageGb
    adminUsername: mongoAdminUsername
    adminPassword: mongoAdminPassword
  }
}

// ============= AZURE AI FOUNDRY =============
module aiFoundry './core/ai/ai-foundry.bicep' = {
  name: 'ai-foundry'
  scope: rg
  params: {
    name: aiName
    location: aiLocation
    tags: tags
    customSubDomainName: aiName
    modelName: aiModelName
    modelVersion: aiModelVersion
    deploymentName: aiDeploymentName
    deploymentCapacity: aiDeploymentCapacity
  }
}

// ============= STATIC WEB APP =============
module staticWebApp './core/host/static-web-app.bicep' = {
  name: 'static-web-app'
  scope: rg
  params: {
    name: swaName
    location: staticWebAppLocation
    tags: tags
  }
}

// ============= API CONTAINER APP =============
module api './core/host/container-app.bicep' = {
  name: 'api'
  scope: rg
  params: {
    name: apiAppName
    location: location
    tags: union(tags, { 'azd-service-name': 'api' })
    containerAppsEnvironmentName: containerAppsEnvironment.outputs.name
    containerRegistryName: containerRegistry.outputs.name
    containerCpuCoreCount: apiCpu
    containerMemory: apiMemory
    containerMaxReplicas: apiMaxReplicas
    containerMinReplicas: apiMinReplicas
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
        value: staticWebApp.outputs.uri
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
        value: aiFoundry.outputs.endpoint
      }
      {
        name: 'AZURE_AI_PROJECT'
        value: aiName
      }
      {
        name: 'AZURE_AI_DEPLOYMENT'
        value: aiFoundry.outputs.deploymentName
      }
    ]
    secrets: [
      {
        name: 'mongo-uri'
        value: mongoCluster.outputs.connectionString
      }
      {
        name: 'github-token'
        value: !empty(githubToken) ? githubToken : 'placeholder-configure-after-deploy'
      }
    ]
  }
}

// ============= STAGING CONTAINER APP (opcional) =============
module apiStaging './core/host/container-app.bicep' = if (deployStaging) {
  name: 'api-staging'
  scope: rg
  params: {
    name: stagingAppName
    location: location
    tags: union(tags, { 'azd-service-name': 'api-staging' })
    containerAppsEnvironmentName: containerAppsEnvironment.outputs.name
    containerRegistryName: containerRegistry.outputs.name
    containerCpuCoreCount: apiCpu
    containerMemory: apiMemory
    containerMaxReplicas: 1
    containerMinReplicas: 0
    targetPort: 8000
    env: [
      {
        name: 'ENVIRONMENT'
        value: 'staging'
      }
      {
        name: 'DEBUG'
        value: 'False'
      }
      {
        name: 'MONGO_DB_NAME'
        value: 'quantum_github'
      }
      {
        name: 'MONGO_URI'
        secretRef: 'mongo-uri'
      }
      {
        name: 'GITHUB_TOKEN'
        secretRef: 'github-token'
      }
    ]
    secrets: [
      {
        name: 'mongo-uri'
        value: mongoCluster.outputs.connectionString
      }
      {
        name: 'github-token'
        value: !empty(githubToken) ? githubToken : 'placeholder-configure-after-deploy'
      }
    ]
  }
}

// ============= ROLE ASSIGNMENTS (Managed Identity → AI Foundry) =============
// Permite a la MI del Container App API invocar GPT-4o por Entra ID
module aiRoleApi './core/security/ai-role-assignment.bicep' = {
  name: 'ai-role-api'
  scope: rg
  params: {
    aiServiceName: aiFoundry.outputs.name
    principalId: api.outputs.principalId
  }
}

module aiRoleStaging './core/security/ai-role-assignment.bicep' = if (deployStaging) {
  name: 'ai-role-staging'
  scope: rg
  params: {
    aiServiceName: aiFoundry.outputs.name
    principalId: apiStaging.?outputs.principalId ?? ''
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

output SERVICE_API_STAGING_URI string = deployStaging ? (apiStaging.?outputs.uri ?? '') : ''
output SERVICE_API_STAGING_NAME string = deployStaging ? (apiStaging.?outputs.name ?? '') : ''

output AZURE_AI_ENDPOINT string = aiFoundry.outputs.endpoint
output AZURE_AI_NAME string = aiFoundry.outputs.name
output AZURE_AI_DEPLOYMENT string = aiFoundry.outputs.deploymentName

output AZURE_MONGO_NAME string = mongoCluster.outputs.name
output AZURE_MONGO_HOST string = '${mongoCluster.outputs.name}.global.mongocluster.cosmos.azure.com'

output AZURE_STATIC_WEB_APP_NAME string = staticWebApp.outputs.name
output AZURE_STATIC_WEB_APP_URI string = staticWebApp.outputs.uri
