# Guía de Despliegue en Azure

Esta guía explica cómo desplegar el backend del TFG en Azure Container Apps usando Azure Developer CLI (azd).

## Prerrequisitos

1. **Azure Developer CLI (azd)**
   ```powershell
   # Instalar azd
   winget install microsoft.azd
   ```

2. **Azure CLI**
   ```powershell
   # Instalar Azure CLI
   winget install Microsoft.AzureCLI
   ```

3. **Docker Desktop**
   - Descargar e instalar desde https://www.docker.com/products/docker-desktop

4. **Cuenta de Azure**
   - Tener una suscripción activa de Azure

## Configuración Inicial

### 1. Iniciar sesión en Azure

```powershell
# Login con Azure CLI
az login

# Login con Azure Developer CLI
azd auth login
```

### 2. Configurar variables de entorno

Copia el archivo `.env.example` a `.env` y configura las variables:

```powershell
cp .env.example .env
```

Edita `.env` con tus valores reales:
- `GITHUB_TOKEN`: Tu token personal de GitHub
- `MONGO_URI`: URI de conexión a MongoDB (Azure CosmosDB o MongoDB Atlas)
- `MONGO_DB_NAME`: Nombre de tu base de datos

### 3. Configurar MongoDB

**Opción A: Azure CosmosDB con API MongoDB**

```powershell
# Crear cuenta de CosmosDB
az cosmosdb create \
  --name tfg-cosmosdb \
  --resource-group rg-tfg-backend \
  --kind MongoDB \
  --server-version 4.2

# Obtener cadena de conexión
az cosmosdb keys list \
  --name tfg-cosmosdb \
  --resource-group rg-tfg-backend \
  --type connection-strings
```

**Opción B: MongoDB Atlas**
- Crear cluster en https://cloud.mongodb.com
- Obtener cadena de conexión
- Configurar acceso desde Azure IPs

## Despliegue

### Método 1: Despliegue Completo con azd (Recomendado)

```powershell
# Inicializar el proyecto
azd init

# Provisionar infraestructura y desplegar
azd up
```

Durante `azd up`, se te pedirá:
- **Environment name**: nombre único para tu entorno (ej: `tfg-backend-dev`)
- **Azure location**: región donde desplegar (ej: `westeurope`, `eastus`)
- **Subscription**: tu suscripción de Azure

### Método 2: Despliegue Paso a Paso

```powershell
# 1. Provisionar infraestructura
azd provision

# 2. Desplegar la aplicación
azd deploy
```

### Método 3: Despliegue Manual con Azure CLI

```powershell
# 1. Crear grupo de recursos
az group create --name rg-tfg-backend --location westeurope

# 2. Desplegar infraestructura con Bicep
az deployment group create \
  --resource-group rg-tfg-backend \
  --template-file infra/main.bicep \
  --parameters environmentName=tfg-backend location=westeurope

# 3. Construir y subir imagen Docker
az acr build \
  --registry <tu-registry-name> \
  --image tfg-backend:latest \
  .

# 4. Actualizar Container App con la nueva imagen
az containerapp update \
  --name ca-tfg-backend-api \
  --resource-group rg-tfg-backend \
  --image <tu-registry-name>.azurecr.io/tfg-backend:latest
```

## Configuración Post-Despliegue

### 1. Configurar Secretos

```powershell
# Configurar GITHUB_TOKEN
azd env set GITHUB_TOKEN "tu_token_aqui"

# Configurar MONGO_URI
azd env set MONGO_URI "tu_mongo_uri_aqui"

# Actualizar Container App con los secretos
azd deploy
```

### 2. Verificar el Despliegue

```powershell
# Obtener URL de la aplicación
azd show

# Probar la API
curl https://<tu-app-url>/api/v1/health
```

### 3. Ver Logs

```powershell
# Ver logs en tiempo real
azd monitor --logs

# O usando Azure CLI
az containerapp logs show \
  --name ca-tfg-backend-api \
  --resource-group rg-tfg-backend \
  --follow
```

## Variables de Entorno en Azure

Las siguientes variables se configuran automáticamente:
- `ENVIRONMENT`: production
- `DEBUG`: False
- `PORT`: 8000

Debes configurar manualmente:
- `GITHUB_TOKEN`: Token de acceso a GitHub
- `MONGO_URI`: Cadena de conexión a MongoDB
- `MONGO_DB_NAME`: Nombre de la base de datos

### Configurar mediante Azure Portal

1. Ir a Azure Portal
2. Navegar a tu Container App
3. En el menú lateral: **Settings** → **Secrets**
4. Agregar secretos: `github-token` y `mongo-uri`
5. En **Settings** → **Containers** → **Environment variables**
6. Agregar referencias a los secretos

### Configurar mediante CLI

```powershell
# Actualizar secretos
az containerapp secret set \
  --name ca-tfg-backend-api \
  --resource-group rg-tfg-backend \
  --secrets github-token="tu_token" mongo-uri="tu_mongo_uri"

# Actualizar variables de entorno
az containerapp update \
  --name ca-tfg-backend-api \
  --resource-group rg-tfg-backend \
  --set-env-vars \
    GITHUB_TOKEN=secretref:github-token \
    MONGO_URI=secretref:mongo-uri \
    MONGO_DB_NAME=quantum_github
```

## Escalado

### Configurar Escalado Automático

```powershell
az containerapp update \
  --name ca-tfg-backend-api \
  --resource-group rg-tfg-backend \
  --min-replicas 1 \
  --max-replicas 10 \
  --scale-rule-name http-scaling \
  --scale-rule-type http \
  --scale-rule-http-concurrency 100
```

## Monitoreo

### Application Insights

El proyecto está configurado para usar Log Analytics. Para habilitar Application Insights:

1. Crear recurso de Application Insights en Azure Portal
2. Copiar la cadena de conexión
3. Configurar en Container App:

```powershell
azd env set APPLICATIONINSIGHTS_CONNECTION_STRING "tu_connection_string"
azd deploy
```

### Métricas y Alertas

```powershell
# Ver métricas
az monitor metrics list \
  --resource ca-tfg-backend-api \
  --resource-group rg-tfg-backend \
  --resource-type Microsoft.App/containerApps

# Crear alerta de disponibilidad
az monitor metrics alert create \
  --name "API Down Alert" \
  --resource-group rg-tfg-backend \
  --scopes /subscriptions/.../resourceGroups/rg-tfg-backend/providers/Microsoft.App/containerApps/ca-tfg-backend-api \
  --condition "avg Percentage CPU > 80" \
  --description "Alert when CPU exceeds 80%"
```

## CI/CD con GitHub Actions

### 1. Configurar Secretos en GitHub

Agregar estos secretos en tu repositorio de GitHub:
- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`
- `AZURE_CREDENTIALS`

### 2. Crear Workflow

Crea `.github/workflows/azure-deploy.yml`:

```yaml
name: Deploy to Azure

on:
  push:
    branches: [ main ]
  workflow_dispatch:

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Log in to Azure
        uses: azure/login@v1
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS }}
      
      - name: Build and deploy
        run: |
          azd auth login --client-id ${{ secrets.AZURE_CLIENT_ID }} \
            --tenant-id ${{ secrets.AZURE_TENANT_ID }} \
            --federated-credential-provider github
          azd deploy --no-prompt
```

## Actualización de la Aplicación

```powershell
# Actualizar código y redesplegar
azd deploy

# O forzar reconstrucción completa
azd deploy --force
```

## Rollback

```powershell
# Ver revisiones anteriores
az containerapp revision list \
  --name ca-tfg-backend-api \
  --resource-group rg-tfg-backend

# Activar revisión anterior
az containerapp revision activate \
  --name ca-tfg-backend-api \
  --resource-group rg-tfg-backend \
  --revision <revision-name>
```

## Limpieza de Recursos

```powershell
# Eliminar todos los recursos
azd down

# O eliminar grupo de recursos completo
az group delete --name rg-tfg-backend --yes
```

## Solución de Problemas

### La aplicación no inicia

1. Verificar logs:
   ```powershell
   azd monitor --logs
   ```

2. Verificar variables de entorno configuradas
3. Verificar que MongoDB es accesible desde Azure

### Error de conexión a MongoDB

1. Verificar cadena de conexión en secretos
2. Para CosmosDB: verificar que la API de MongoDB está habilitada
3. Verificar reglas de firewall en MongoDB/CosmosDB

### Rate Limit de GitHub

La API incluye un endpoint para verificar el rate limit:
```powershell
curl https://<tu-app-url>/api/v1/rate-limit
```

## Costos Estimados

- **Container Apps**: ~$20-50/mes (dependiendo del uso)
- **Container Registry**: ~$5/mes (Basic tier)
- **Log Analytics**: ~$2-10/mes (dependiendo de logs)
- **CosmosDB**: ~$25/mes (400 RU/s) o MongoDB Atlas: Gratis (tier M0)

**Total estimado**: $30-85/mes

## Referencias

- [Azure Container Apps Documentation](https://learn.microsoft.com/azure/container-apps/)
- [Azure Developer CLI Documentation](https://learn.microsoft.com/azure/developer/azure-developer-cli/)
- [Azure Bicep Documentation](https://learn.microsoft.com/azure/azure-resource-manager/bicep/)

## Soporte

Para problemas o preguntas:
1. Revisar logs con `azd monitor --logs`
2. Consultar documentación de Azure
3. Contactar al equipo de desarrollo
