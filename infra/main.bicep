targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the environment that can be used as part of naming resource convention')
param environmentName string

@minLength(1)
@description('Primary location for all resources')
param location string

// Optional parameters
@description('Id of the user or app to assign application roles')
//param principalId string = ''

// Tags
var tags = {
  'azd-env-name': environmentName
  project: 'tfg-backend'
}

// Resource group
resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

// Container Apps Environment
module containerAppsEnvironment './core/host/container-apps-environment.bicep' = {
  name: 'container-apps-environment'
  scope: rg
  params: {
    name: 'cae-${environmentName}'
    location: location
    tags: tags
    logAnalyticsCustomerId: logAnalytics.outputs.customerId
    logAnalyticsSharedKey: logAnalytics.outputs.sharedKey
  }
}

// Container Registry
module containerRegistry './core/host/container-registry.bicep' = {
  name: 'container-registry'
  scope: rg
  params: {
    name: 'cr${replace(environmentName, '-', '')}'
    location: location
    tags: tags
  }
}

// Log Analytics Workspace
module logAnalytics './core/monitor/loganalytics.bicep' = {
  name: 'log-analytics'
  scope: rg
  params: {
    name: 'log-${environmentName}'
    location: location
    tags: tags
  }
}

// API Container App
module api './core/host/container-app.bicep' = {
  name: 'api'
  scope: rg
  params: {
    name: 'ca-${environmentName}-api'
    location: location
    tags: union(tags, { 'azd-service-name': 'api' })
    containerAppsEnvironmentName: containerAppsEnvironment.outputs.name
    containerRegistryName: containerRegistry.outputs.name
    containerCpuCoreCount: '1.0'
    containerMemory: '2.0Gi'
    containerMaxReplicas: 1
    containerMinReplicas: 0
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
        name: 'github-token'
        value: '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' // Se configura después del despliegue
      }
      {
        name: 'mongo-uri'
        value: 'mongodb://db-entangle-uclm:T3sv72J6kvKJ9BTiWSSy6vZVCzN7velCtb1vmK2PlgC2Bi7Y52448sA22TI708pGcyNPyf0UZnoRACDbbP6lvw==@db-entangle-uclm.mongo.cosmos.azure.com:10255/?ssl=true&replicaSet=globaldb&retrywrites=false&maxIdleTimeMS=120000&appName=@db-entangle-uclm@' // Se configura después del despliegue
      }
    ]
    targetPort: 8000
  }
}

// Outputs
output AZURE_LOCATION string = location
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = containerRegistry.outputs.loginServer
output AZURE_CONTAINER_REGISTRY_NAME string = containerRegistry.outputs.name
output API_URI string = api.outputs.uri
output RESOURCE_GROUP_NAME string = rg.name
