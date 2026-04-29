# Infraestructura Azure (Bicep) para Entangle

Este directorio contiene la infraestructura como código (IaC) que despliega el
**entorno completo de Entangle** en Azure: backend, base de datos, IA y frontend.

## Recursos que se crean

| Recurso | Tipo | Región por defecto | Notas |
|---|---|---|---|
| Resource Group | `Microsoft.Resources/resourceGroups` | `location` | Contenedor de todo |
| Log Analytics Workspace | `Microsoft.OperationalInsights/workspaces` | `location` | Logs de Container Apps |
| Azure Container Registry (Basic) | `Microsoft.ContainerRegistry/registries` | `location` | Imágenes Docker |
| Container Apps Environment | `Microsoft.App/managedEnvironments` | `location` | Plataforma de hosting |
| Container App `*-api` | `Microsoft.App/containerApps` | `location` | Backend FastAPI (producción) |
| Container App `*-api-staging` | `Microsoft.App/containerApps` | `location` | Backend FastAPI (staging, opcional) |
| Cosmos DB for MongoDB vCore | `Microsoft.DocumentDB/mongoClusters` | `databaseLocation` (`northeurope`) | Cluster M30 por defecto, MongoDB 8.0 |
| Azure AI Foundry (AIServices) | `Microsoft.CognitiveServices/accounts` | `aiLocation` (`swedencentral`) | Multi-modelo, custom subdomain |
| GPT-4o deployment | `Microsoft.CognitiveServices/accounts/deployments` | (mismo que AI) | GlobalStandard, 169k TPM |
| Static Web App (Standard) | `Microsoft.Web/staticSites` | `staticWebAppLocation` (`westeurope`) | Hosting del frontend React |
| Role assignment AI ↔ MI API | `Microsoft.Authorization/roleAssignments` | — | "Cognitive Services User" |
| Role assignment AI ↔ MI Staging | `Microsoft.Authorization/roleAssignments` | — | "Cognitive Services User" |

> Algunos servicios viven en regiones distintas a la principal por **disponibilidad
> de cuota**: M30 de MongoDB no está siempre en Spain Central, GPT-4o tiene capacidad
> en Sweden Central, y las Static Web Apps requieren regiones específicas.

## Despliegue rápido con `azd`

```powershell
# 1. Login
azd auth login

# 2. Crear/seleccionar entorno
azd env new entangle-prod
# (o: azd env select entangle-prod)

# 3. Configurar valores. Los obligatorios son:
azd env set AZURE_LOCATION spaincentral
azd env set MONGO_ADMIN_PASSWORD "TuPasswordSeguraAqui!"   # ≥8 chars, mayúscula, minúscula, número
azd env set GITHUB_TOKEN "ghp_xxxxxxxxxxxxxxxxxxxx"

# 4. (Opcional) Override de regiones / tier
azd env set AZURE_DATABASE_LOCATION northeurope
azd env set AZURE_AI_LOCATION       swedencentral
azd env set AZURE_SWA_LOCATION      westeurope
azd env set MONGO_COMPUTE_TIER      M30        # Bájalo a M10/M20 en dev
azd env set DEPLOY_STAGING          true

# 5. Provisionar + build/push imagen + deploy
azd up
```

Tras el `azd up` se imprimen los outputs principales (URI del API, URI de la SWA,
endpoint de AI, hostname de Mongo). Los necesitarás para configurar tu DNS/CD.

## Despliegue manual con `az deployment`

Si prefieres no usar `azd`:

```powershell
$env:AZURE_LOCATION         = "spaincentral"
$env:MONGO_ADMIN_PASSWORD   = "TuPasswordSeguraAqui!"
$env:GITHUB_TOKEN           = "ghp_xxxxxxxxxxxxxxxxxxxx"

az deployment sub create `
  --location $env:AZURE_LOCATION `
  --template-file main.bicep `
  --parameters environmentName=entangle-prod `
               location=$env:AZURE_LOCATION `
               mongoAdminPassword=$env:MONGO_ADMIN_PASSWORD `
               githubToken=$env:GITHUB_TOKEN
```

Después tendrás que construir y subir la imagen del API a ACR a mano, por
ejemplo:

```powershell
$acr = az acr list --resource-group rg-entangle-prod --query "[0].name" -o tsv
az acr build --registry $acr --image entangle-api:latest -f Dockerfile ..
az containerapp update -g rg-entangle-prod -n ca-<token>-api `
  --image "$acr.azurecr.io/entangle-api:latest"
```

## ⚠️ Coste estimado mensual (defaults)

| Recurso | Coste aproximado/mes (USD) |
|---|---|
| Cosmos Mongo vCore **M30** + 256 GB | ~330 |
| Container Apps (consumption, 0.5 vCPU + 1 Gi, max 1) | ~5 a 30 según tráfico |
| Container Registry (Basic) | ~5 |
| Log Analytics (Pay-as-you-go) | ~3 a 10 |
| AI Foundry (S0 + GPT-4o GlobalStandard) | Pago por uso de tokens |
| Static Web App (Standard) | ~9 |
| **Total** | **~360+ USD/mes** (dominado por el Mongo M30) |

> Para entornos de **desarrollo o pruebas**, baja el tier de Mongo:
> `azd env set MONGO_COMPUTE_TIER M10` reduce el coste a ~50 USD/mes.

## Idempotencia con recursos ya existentes

Esta plantilla parte de un RG vacío. Si ya tienes un entorno desplegado a mano
(como el actual `rg-entangle`), tienes tres opciones:

1. **Crear un entorno nuevo** (`AZURE_ENV_NAME=entangle-staging`) y dejar el
   actual intacto.
2. **Importar** los recursos existentes a la suscripción/RG bajo el mismo
   nombre y ejecutar `azd provision` (el deploy detectará que existen).
3. **Borrar todo** y volver a desplegar desde cero (no recomendado salvo que
   sea un entorno desechable).

## Cómo conectar el repo del frontend a la Static Web App creada

El módulo `static-web-app.bicep` crea una SWA **desconectada** del repositorio
para no exponer tokens de GitHub al deploy. Tras el `azd up`:

1. Ve a Azure Portal → tu Static Web App → **Manage deployment token**
2. Copia el token y añádelo como secret en `Angel-TFG-UCLM/Frontend`
   (Settings → Secrets → Actions → `AZURE_STATIC_WEB_APPS_API_TOKEN`)
3. Comprueba que el workflow `azure-static-web-apps-blue-rock-...yml` apunta a
   ese secret.

## Validación rápida

```powershell
# Compila el Bicep sin desplegar nada
az bicep build --file infra/main.bicep --stdout > $null

# What-if (muestra qué recursos se crearían/cambiarían)
az deployment sub what-if `
  --location spaincentral `
  --template-file infra/main.bicep `
  --parameters environmentName=test `
               location=spaincentral `
               mongoAdminPassword=DummyPwd_123 `
               githubToken=dummy
```
