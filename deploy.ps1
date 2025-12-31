# Archivo: deploy.ps1
# Script completo de despliegue a Azure Container Apps
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "Iniciando despliegue a Azure Container Apps" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

$APP_NAME = "ca-entangle-uclm-api"
$GROUP = "rg-entangle-uclm"
$REGISTRY = "crentangleuclm.azurecr.io"
$IMAGE_NAME = "tfg-backend"
$IMAGE_TAG = "latest"
$FULL_IMAGE = "$REGISTRY/${IMAGE_NAME}:${IMAGE_TAG}"

# Obtenemos la fecha y hora actual
$TIMESTAMP = Get-Date -Format "yyyyMMdd-HHmmss"
Write-Host "`nMarca de tiempo: $TIMESTAMP" -ForegroundColor Gray

# Paso 1: Login en Azure Container Registry
Write-Host "`n[1/4] Autenticando en Azure Container Registry..." -ForegroundColor Yellow
az acr login --name crentangleuclm
if (-not $?) {
    Write-Host "❌ Error al autenticar en ACR. Ejecuta 'az login' primero." -ForegroundColor Red
    exit 1
}

# Paso 2: Construir la imagen Docker
Write-Host "`n[2/4] Construyendo imagen Docker (sin cache)..." -ForegroundColor Yellow
docker build --no-cache -t ${FULL_IMAGE} .
if (-not $?) {
    Write-Host "❌ Error al construir la imagen Docker." -ForegroundColor Red
    exit 1
}
Write-Host "✅ Imagen construida correctamente" -ForegroundColor Green

# Paso 3: Subir la imagen al registro
Write-Host "`n[3/4] Subiendo imagen a Azure Container Registry..." -ForegroundColor Yellow
docker push ${FULL_IMAGE}
if (-not $?) {
    Write-Host "❌ Error al subir la imagen al registro." -ForegroundColor Red
    exit 1
}
Write-Host "✅ Imagen subida correctamente" -ForegroundColor Green

# Paso 4: Actualizar el Container App
Write-Host "`n[4/4] Actualizando Azure Container App..." -ForegroundColor Yellow
az containerapp update --name $APP_NAME --resource-group $GROUP --image $FULL_IMAGE --set-env-vars LAST_DEPLOY=$TIMESTAMP
if (-not $?) {
    Write-Host "❌ Error al actualizar el Container App." -ForegroundColor Red
    exit 1
}

# Confirmación final
Write-Host "`n=============================================" -ForegroundColor Green
Write-Host "✅ DESPLIEGUE COMPLETADO EXITOSAMENTE" -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
Write-Host "Imagen: $FULL_IMAGE"
Write-Host "Timestamp: $TIMESTAMP"
Write-Host "`nRevisa el portal de Azure para verificar que la nueva revision este activa."
