// ===========================================
// Role assignment scoped al recurso AIServices
// ===========================================
// Asigna el rol "Cognitive Services User" a un principal (la Managed Identity
// del Container App) para que pueda invocar los modelos por Entra ID.

@description('Nombre del recurso AIServices.')
param aiServiceName string

@description('Object ID del principal (Managed Identity) al que asignar el rol.')
param principalId string

@description('Tipo de principal.')
param principalType string = 'ServicePrincipal'

@description('GUID del rol. Por defecto: Cognitive Services User (a97b65f3-24c7-4388-baec-2e87135dc908).')
param roleDefinitionId string = 'a97b65f3-24c7-4388-baec-2e87135dc908'

resource aiService 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: aiServiceName
}

resource role 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiService.id, principalId, roleDefinitionId)
  scope: aiService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleDefinitionId)
    principalId: principalId
    principalType: principalType
  }
}

output roleAssignmentId string = role.id
