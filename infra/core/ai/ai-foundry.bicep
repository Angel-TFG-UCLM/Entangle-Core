// ===========================================
// Azure AI Foundry (AIServices) + gpt-5-mini deployment
// ===========================================
// Crea un recurso multi-modelo de AIServices (sucesor de Cognitive Services + OpenAI)
// con custom subdomain (necesario para auth por Managed Identity con DefaultAzureCredential)
// y un deployment de gpt-5-mini (familia de razonamiento, 400K contexto, ~20x más barato que gpt-4o).

param name string
param location string = resourceGroup().location
param tags object = {}

@description('SKU del recurso AIServices.')
param sku string = 'S0'

@description('Subdominio personalizado. Si está vacío, se usa el name. Es necesario para Entra ID auth.')
param customSubDomainName string = ''

@description('Permitir acceso público al endpoint.')
param publicNetworkAccess string = 'Enabled'

@description('Modelo a desplegar (ej: gpt-5-mini, gpt-5-nano, gpt-4o-mini).')
param modelName string = 'gpt-5-mini'

@description('Versión del modelo. Por defecto, GA estable de gpt-5-mini.')
param modelVersion string = '2025-08-07'

@description('Nombre del deployment del modelo (lo que tu app pone en AZURE_AI_DEPLOYMENT).')
param deploymentName string = 'gpt-5-mini'

@description('Tipo de capacidad / SKU de despliegue. GlobalStandard reparte entre regiones, Standard local.')
@allowed([
  'GlobalStandard'
  'Standard'
  'DataZoneStandard'
])
param deploymentSkuName string = 'GlobalStandard'

@description('Tokens por minuto (TPM) en miles. Por ejemplo 250 = 250.000 TPM.')
param deploymentCapacity int = 250

resource ai 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: name
  location: location
  tags: tags
  kind: 'AIServices'
  identity: {
    type: 'SystemAssigned'
  }
  sku: {
    name: sku
  }
  properties: {
    customSubDomainName: empty(customSubDomainName) ? name : customSubDomainName
    publicNetworkAccess: publicNetworkAccess
    networkAcls: {
      defaultAction: 'Allow'
    }
    disableLocalAuth: false
  }
}

resource gpt 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: ai
  name: deploymentName
  sku: {
    name: deploymentSkuName
    capacity: deploymentCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
  }
}

output id string = ai.id
output name string = ai.name
output endpoint string = 'https://${ai.properties.customSubDomainName}.services.ai.azure.com'
output openAiEndpoint string = ai.properties.endpoint
output deploymentName string = gpt.name
