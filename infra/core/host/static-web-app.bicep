// ===========================================
// Azure Static Web App (sin conectar a repo)
// ===========================================
// Crea una Static Web App vacía que luego se conecta a GitHub mediante el workflow
// existente (deployment token expuesto vía azd como output).

param name string
param location string = 'westeurope'
param tags object = {}

@description('SKU: Free o Standard. Standard requiere para custom domains, staging environments y SLA.')
@allowed([
  'Free'
  'Standard'
])
param sku string = 'Standard'

@description('Permitir que GitHub Actions actualice el archivo staticwebapp.config.json.')
param allowConfigFileUpdates bool = true

// Identidad gestionada del sistema: necesaria para que la Static Web App pueda
// acceder a recursos Azure (Key Vault, Storage, AI Foundry...) usando RBAC en
// vez de credenciales en codigo. Aunque hoy no se use, dejarlo activado evita
// tener que recrear la SWA en el futuro y satisface el security hotspot de Sonar.
resource staticWebApp 'Microsoft.Web/staticSites@2024-04-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  sku: {
    name: sku
    tier: sku
  }
  properties: {
    allowConfigFileUpdates: allowConfigFileUpdates
    stagingEnvironmentPolicy: 'Enabled'
    enterpriseGradeCdnStatus: 'Disabled'
  }
}

output id string = staticWebApp.id
output name string = staticWebApp.name
output defaultHostname string = staticWebApp.properties.defaultHostname
output uri string = 'https://${staticWebApp.properties.defaultHostname}'
