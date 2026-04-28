// ===========================================
// Azure AI Foundry (AIServices) + GPT-4o deployment
// ===========================================
// Crea un recurso multi-modelo de AIServices (sucesor de Cognitive Services + OpenAI)
// con custom subdomain (necesario para auth por Managed Identity con DefaultAzureCredential)
// y un deployment de GPT-4o.

param name string
param location string = resourceGroup().location
param tags object = {}

@description('SKU del recurso AIServices.')
param sku string = 'S0'

@description('Subdominio personalizado. Si está vacío, se usa el name. Es necesario para Entra ID auth.')
param customSubDomainName string = ''

@description('Permitir acceso público al endpoint.')
param publicNetworkAccess string = 'Enabled'

@description('Modelo a desplegar (ej: gpt-4o, gpt-4o-mini).')
param modelName string = 'gpt-4o'

@description('Versión del modelo.')
param modelVersion string = '2024-08-06'

@description('Nombre del deployment del modelo (lo que tu app pone en AZURE_AI_DEPLOYMENT).')
param deploymentName string = 'gpt-4o'

@description('Tipo de capacidad / SKU de despliegue. GlobalStandard reparte entre regiones, Standard local.')
@allowed([
  'GlobalStandard'
  'Standard'
  'DataZoneStandard'
])
param deploymentSkuName string = 'GlobalStandard'

@description('Tokens por minuto (TPM) en miles. Por ejemplo 169 = 169.000 TPM.')
param deploymentCapacity int = 169

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
