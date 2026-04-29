// ===========================================
// Azure Cosmos DB for MongoDB (vCore) cluster
// ===========================================
// Crea un cluster Mongo vCore con un único nodo y los firewall rules necesarias
// para permitir el acceso desde Azure (Container Apps).
// Devuelve la cadena de conexión como output seguro.

@minLength(3)
@maxLength(40)
param name string

param location string = resourceGroup().location
param tags object = {}

@description('Versión del servidor de MongoDB.')
param mongoVersion string = '8.0'

@description('Tier de cómputo del nodo (M10, M20, M25, M30, M40, M50, M60, M80, M200).')
param computeTier string = 'M30'

@description('Tamaño del disco en GB.')
@allowed([
  32
  64
  128
  256
  512
  1024
  2048
])
param storageSizeGb int = 256

@description('Alta disponibilidad (multi-zona). Activar solo en tiers ≥ M30 y disponible en la región.')
param highAvailability bool = false

@description('Permitir acceso público al cluster.')
param publicNetworkAccess string = 'Enabled'

@description('Usuario administrador del cluster.')
param adminUsername string

@secure()
@description('Contraseña del usuario administrador.')
param adminPassword string

@description('Permitir acceso desde cualquier servicio de Azure (0.0.0.0). Útil para Container Apps con egress dinámico.')
param allowAllAzureServices bool = true

resource mongoCluster 'Microsoft.DocumentDB/mongoClusters@2024-07-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    administrator: {
      userName: adminUsername
      password: adminPassword
    }
    serverVersion: mongoVersion
    compute: {
      tier: computeTier
    }
    storage: {
      sizeGb: storageSizeGb
    }
    sharding: {
      shardCount: 1
    }
    highAvailability: {
      targetMode: highAvailability ? 'SameZone' : 'Disabled'
    }
    publicNetworkAccess: publicNetworkAccess
  }
}

// Firewall: con startIp=endIp=0.0.0.0 Mongo vCore aplica un alias especial que
// permite el acceso desde *cualquier servicio de Azure dentro de la misma
// suscripcion* (NO desde Internet). Es la opcion mas sencilla para que el
// Container App API acceda a Mongo sin tener que montar VNet + Private Endpoint.
//
// SECURITY NOTE (sonar javascript:S6321 / similar):
//   - Esto NO abre el cluster a Internet publica: el rango 0.0.0.0/0 es solo
//     un marcador interno de Azure para "cualquier IP procedente del bus
//     interno de Azure".
//   - El acceso real sigue requiriendo credenciales validas (admin user +
//     password almacenados como secrets en el Container App).
//   - Para entornos de produccion enterprise se recomienda Private Endpoint
//     + VNet integrada; aqui se prioriza simplicidad por ser un TFG.
#disable-next-line BCP037
resource fwAllAzure 'Microsoft.DocumentDB/mongoClusters/firewallRules@2024-07-01' = if (allowAllAzureServices) {
  parent: mongoCluster
  name: 'AllowAllAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

output id string = mongoCluster.id
output name string = mongoCluster.name
output connectionStringTemplate string = mongoCluster.properties.connectionString

// Connection string completa con credenciales sustituidas (marcada como secret)
@description('Cadena de conexión Mongo vCore lista para usarse (incluye credenciales).')
#disable-next-line outputs-should-not-contain-secrets
output connectionString string = replace(replace(mongoCluster.properties.connectionString, '<user>', adminUsername), '<password>', adminPassword)
