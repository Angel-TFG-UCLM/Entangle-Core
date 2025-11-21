# Resumen de Preparación para Despliegue en Azure

## 📋 Archivos Creados/Modificados

### 1. Configuración Docker
- ✅ **`.dockerignore`** - Excluye archivos innecesarios del build
- ✅ **`Dockerfile`** - Optimizado para Azure Container Apps con:
  - Usuario no-root para seguridad
  - Health check integrado
  - Soporte para variable PORT de Azure
  - Multi-stage build preparado

### 2. Variables de Entorno
- ✅ **`.env.example`** - Plantilla con todas las variables necesarias
- ✅ **`src/core/config.py`** - Actualizado para soportar:
  - Variable `PORT` de Azure Container Apps
  - `LOG_LEVEL` configurable
  - Compatibilidad con Azure Key Vault (preparado)

### 3. Infraestructura como Código (IaC)
- ✅ **`azure.yaml`** - Configuración de Azure Developer CLI
- ✅ **`infra/main.bicep`** - Plantilla principal de infraestructura
- ✅ **`infra/main.parameters.json`** - Parámetros de despliegue
- ✅ **`infra/core/host/container-app.bicep`** - Definición de Container App
- ✅ **`infra/core/host/container-apps-environment.bicep`** - Entorno de Container Apps
- ✅ **`infra/core/host/container-registry.bicep`** - Azure Container Registry
- ✅ **`infra/core/monitor/loganalytics.bicep`** - Log Analytics Workspace

### 4. CI/CD
- ✅ **`.github/workflows/azure-deploy.yml`** - Pipeline de GitHub Actions para:
  - Build automático
  - Tests
  - Despliegue a Azure
  - Health check post-despliegue

### 5. Documentación
- ✅ **`DEPLOYMENT.md`** - Guía completa de despliegue (10+ páginas)
- ✅ **`QUICKSTART.md`** - Guía rápida de 5 minutos
- ✅ **`README.md`** - Actualizado con información de despliegue

### 6. Scripts de Utilidad
- ✅ **`scripts/verify_deployment_ready.py`** - Verificación pre-despliegue

### 7. Configuración Git
- ✅ **`.gitignore`** - Actualizado para excluir:
  - `.azure/` (configuración local de azd)
  - `.env.local`
  - `*.bicepparam`

## 🎯 Recursos de Azure que se Crearán

1. **Resource Group** (`rg-{environmentName}`)
2. **Container Registry** (`cr{environmentName}`) - Para imágenes Docker
3. **Container Apps Environment** (`cae-{environmentName}`) - Entorno gestionado
4. **Container App** (`ca-{environmentName}-api`) - Tu aplicación
5. **Log Analytics Workspace** (`log-{environmentName}`) - Monitoreo y logs

## 💰 Costos Estimados Mensuales

- Container Apps: $20-50 (dependiendo del uso)
- Container Registry (Basic): $5
- Log Analytics: $2-10
- **Total estimado: $30-85/mes**

## 🚀 Próximos Pasos

### Opción 1: Despliegue con Azure Developer CLI (Recomendado)

```powershell
# 1. Instalar herramientas
winget install microsoft.azd

# 2. Autenticarse
azd auth login

# 3. Configurar variables en .env
cp .env.example .env
# Editar .env con valores reales

# 4. Verificar que todo está listo
python scripts/verify_deployment_ready.py

# 5. Desplegar
azd up
```

### Opción 2: Despliegue Manual con Azure CLI

Ver guía completa en `DEPLOYMENT.md`, sección "Método 3".

### Opción 3: CI/CD con GitHub Actions

1. Configurar secretos en GitHub:
   - `AZURE_CREDENTIALS`
   - `AZURE_CONTAINER_REGISTRY`
   - `AZURE_CONTAINER_REGISTRY_NAME`

2. Push a branch `main` o `Ingesta_MongoDB`

3. El workflow se ejecutará automáticamente

## ⚙️ Configuración Post-Despliegue

### Configurar Secretos en Azure

```powershell
# Opción 1: Con azd
azd env set GITHUB_TOKEN "tu_token_aqui"
azd env set MONGO_URI "tu_mongo_uri"
azd deploy

# Opción 2: Con Azure CLI
az containerapp secret set \
  --name ca-tfg-backend-api \
  --resource-group rg-tfg-backend \
  --secrets github-token="tu_token" mongo-uri="tu_uri"
```

### Verificar Despliegue

```powershell
# Obtener URL de la app
azd show

# O con Azure CLI
az containerapp show \
  --name ca-tfg-backend-api \
  --resource-group rg-tfg-backend \
  --query properties.configuration.ingress.fqdn

# Probar health check
curl https://<tu-url>/api/v1/health
```

## 📊 Monitoreo

### Ver Logs en Tiempo Real

```powershell
# Con azd
azd monitor --logs

# Con Azure CLI
az containerapp logs show \
  --name ca-tfg-backend-api \
  --resource-group rg-tfg-backend \
  --follow
```

### Ver Métricas

```powershell
az monitor metrics list \
  --resource ca-tfg-backend-api \
  --resource-group rg-tfg-backend \
  --resource-type Microsoft.App/containerApps
```

## 🔒 Seguridad

### Configurado ✅
- Usuario no-root en contenedor
- Variables sensibles como secretos
- HTTPS habilitado por defecto
- Health checks configurados

### Recomendaciones Adicionales
- [ ] Configurar Azure Key Vault para secretos
- [ ] Habilitar Application Insights
- [ ] Configurar alertas de monitoreo
- [ ] Implementar API rate limiting
- [ ] Configurar CORS específico (no wildcard)

## 📚 Documentación de Referencia

- [Azure Container Apps](https://learn.microsoft.com/azure/container-apps/)
- [Azure Developer CLI](https://learn.microsoft.com/azure/developer/azure-developer-cli/)
- [Azure Bicep](https://learn.microsoft.com/azure/azure-resource-manager/bicep/)
- [FastAPI Deployment](https://fastapi.tiangolo.com/deployment/)

## ✅ Checklist de Despliegue

Antes de ejecutar `azd up`:

- [ ] Instalado Azure Developer CLI (`azd`)
- [ ] Instalado Docker Desktop
- [ ] Creado archivo `.env` con valores reales
- [ ] Token de GitHub configurado con permisos correctos
- [ ] MongoDB/CosmosDB disponible y accesible
- [ ] Ejecutado `python scripts/verify_deployment_ready.py`
- [ ] Autenticado con `azd auth login`
- [ ] Seleccionada suscripción de Azure correcta

## 🆘 Solución de Problemas

### Error: "No space left on device"
```powershell
docker system prune -a
```

### Error: "Authentication failed"
```powershell
azd auth login --use-device-code
```

### Error: "Resource quota exceeded"
```powershell
# Ver cuotas disponibles
az vm list-usage --location westeurope --output table

# O cambiar a otra región con más cuota
azd env set AZURE_LOCATION eastus
azd provision
```

### La aplicación no inicia
1. Verificar logs: `azd monitor --logs`
2. Verificar variables de entorno configuradas
3. Verificar conectividad a MongoDB
4. Verificar que el health check endpoint existe

## 📞 Soporte

Para problemas o preguntas:
1. Revisar logs con `azd monitor --logs`
2. Consultar `DEPLOYMENT.md` para guía detallada
3. Revisar la documentación oficial de Azure
4. Contactar al equipo de desarrollo

---

**¡Todo listo para desplegar!** 🚀

Ejecuta: `python scripts/verify_deployment_ready.py` para verificar.
