// ===========================================
// Action Group + Metric Alerts for Entangle
// ===========================================
// Replica las alertas operativas que ya existen en producción (rg-entangle):
//   • api-container-restarts  → entangle-api restarts > 3 en 10 min     (Sev 2)
//   • api-high-cpu            → entangle-api CPU > 80%                   (Sev 2)
//   • api-high-memory         → entangle-api Memory > 80%                (Sev 2)
//   • cosmosdb-high-cpu       → entangle-db CPU > 80%                    (Sev 2)
//   • cosmosdb-high-memory    → entangle-db Memory > 80%                 (Sev 2)
//   • cosmosdb-high-storage   → entangle-db Storage > 75%                (Sev 2)
//   • staging-high-cpu        → entangle-api-staging CPU > 80%           (Sev 3)
// Todas notifican al Action Group `entangle-alerts` por email.

param actionGroupName string = 'entangle-alerts'
param location string = 'global'
param tags object = {}

@description('Email del destinatario de las alertas.')
param alertEmail string

@description('Resource ID del Container App entangle-api.')
param apiResourceId string

@description('Resource ID del Container App entangle-api-staging (opcional).')
param stagingResourceId string = ''

@description('Resource ID del cluster Cosmos Mongo vCore entangle-db.')
param mongoResourceId string

// ───────── ACTION GROUP ─────────
resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: actionGroupName
  location: location
  tags: tags
  properties: {
    groupShortName: 'entangle'
    enabled: true
    emailReceivers: [
      {
        name: 'Owner'
        emailAddress: alertEmail
        useCommonAlertSchema: true
      }
    ]
  }
}

// ───────── HELPER: metric alert resource ─────────
// (Bicep no soporta bucle con resource directo bien parametrizado en propiedades complejas,
//  así que se declaran de forma explícita y consistente.)

resource alertApiRestarts 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'api-container-restarts'
  location: location
  tags: tags
  properties: {
    description: 'Container restarts exceed 3 in 10 minutes'
    severity: 2
    enabled: true
    scopes: [ apiResourceId ]
    targetResourceType: 'Microsoft.App/containerApps'
    evaluationFrequency: 'PT5M'
    windowSize: 'PT10M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'RestartCount'
          metricName: 'RestartCount'
          metricNamespace: 'microsoft.app/containerapps'
          operator: 'GreaterThan'
          threshold: 3
          timeAggregation: 'Total'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [
      { actionGroupId: actionGroup.id }
    ]
  }
}

resource alertApiCpu 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'api-high-cpu'
  location: location
  tags: tags
  properties: {
    description: 'CPU usage exceeds 80%'
    severity: 2
    enabled: true
    scopes: [ apiResourceId ]
    targetResourceType: 'Microsoft.App/containerApps'
    evaluationFrequency: 'PT5M'
    windowSize: 'PT10M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'CpuPercentage'
          metricName: 'CpuPercentage'
          metricNamespace: 'microsoft.app/containerapps'
          operator: 'GreaterThan'
          threshold: 80
          timeAggregation: 'Average'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [
      { actionGroupId: actionGroup.id }
    ]
  }
}

resource alertApiMemory 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'api-high-memory'
  location: location
  tags: tags
  properties: {
    description: 'Memory usage exceeds 80%'
    severity: 2
    enabled: true
    scopes: [ apiResourceId ]
    targetResourceType: 'Microsoft.App/containerApps'
    evaluationFrequency: 'PT5M'
    windowSize: 'PT10M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'MemoryPercentage'
          metricName: 'MemoryPercentage'
          metricNamespace: 'microsoft.app/containerapps'
          operator: 'GreaterThan'
          threshold: 80
          timeAggregation: 'Average'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [
      { actionGroupId: actionGroup.id }
    ]
  }
}

resource alertMongoCpu 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'cosmosdb-high-cpu'
  location: location
  tags: tags
  properties: {
    description: 'Cosmos DB vCore CPU exceeds 80%'
    severity: 2
    enabled: true
    scopes: [ mongoResourceId ]
    targetResourceType: 'Microsoft.DocumentDB/mongoClusters'
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'CpuPercent'
          metricName: 'CpuPercent'
          metricNamespace: 'microsoft.documentdb/mongoclusters'
          operator: 'GreaterThan'
          threshold: 80
          timeAggregation: 'Average'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [
      { actionGroupId: actionGroup.id }
    ]
  }
}

resource alertMongoMemory 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'cosmosdb-high-memory'
  location: location
  tags: tags
  properties: {
    description: 'Cosmos DB vCore Memory exceeds 80%'
    severity: 2
    enabled: true
    scopes: [ mongoResourceId ]
    targetResourceType: 'Microsoft.DocumentDB/mongoClusters'
    evaluationFrequency: 'PT5M'
    windowSize: 'PT15M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'MemoryPercent'
          metricName: 'MemoryPercent'
          metricNamespace: 'microsoft.documentdb/mongoclusters'
          operator: 'GreaterThan'
          threshold: 80
          timeAggregation: 'Average'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [
      { actionGroupId: actionGroup.id }
    ]
  }
}

resource alertMongoStorage 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: 'cosmosdb-high-storage'
  location: location
  tags: tags
  properties: {
    description: 'Cosmos DB vCore Storage exceeds 75%'
    severity: 2
    enabled: true
    scopes: [ mongoResourceId ]
    targetResourceType: 'Microsoft.DocumentDB/mongoClusters'
    evaluationFrequency: 'PT15M'
    windowSize: 'PT1H'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'StoragePercent'
          metricName: 'StoragePercent'
          metricNamespace: 'microsoft.documentdb/mongoclusters'
          operator: 'GreaterThan'
          threshold: 75
          timeAggregation: 'Average'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [
      { actionGroupId: actionGroup.id }
    ]
  }
}

resource alertStagingCpu 'Microsoft.Insights/metricAlerts@2018-03-01' = if (!empty(stagingResourceId)) {
  name: 'staging-high-cpu'
  location: location
  tags: tags
  properties: {
    description: 'Staging Container App CPU exceeds 80%'
    severity: 3
    enabled: true
    scopes: [ stagingResourceId ]
    targetResourceType: 'Microsoft.App/containerApps'
    evaluationFrequency: 'PT5M'
    windowSize: 'PT10M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'CpuPercentage'
          metricName: 'CpuPercentage'
          metricNamespace: 'microsoft.app/containerapps'
          operator: 'GreaterThan'
          threshold: 80
          timeAggregation: 'Average'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [
      { actionGroupId: actionGroup.id }
    ]
  }
}

output actionGroupId string = actionGroup.id
output actionGroupName string = actionGroup.name
