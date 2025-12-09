# Archivo: desplegar.ps1
Write-Host "Iniciando despliegue manual a Azure Container Apps..." -ForegroundColor Cyan

$APP_NAME = "ca-entangle-uclm-api"
$GROUP = "rg-entangle-uclm"
$IMAGE = "crentangleuclm.azurecr.io/tfg-backend:latest"

# Obtenemos la fecha y hora actual para obligar a Azure a actualizarse
$TIMESTAMP = Get-Date -Format "yyyyMMdd-HHmm"
Write-Host "Marca de tiempo para forzar despliegue: $TIMESTAMP"

# Ejecutar el comando de actualización
Write-Host "🔄 Ordenando a Azure que descargue la nueva imagen..."
az containerapp update --name $APP_NAME --resource-group $GROUP --image $IMAGE --set-env-vars LAST_DEPLOY=$TIMESTAMP

# Confirmación
if ($?) {
    Write-Host "Azure ha detectado el cambio y está creando la revision." -ForegroundColor Green
    Write-Host "Revisa el portal en un tiempo para verificar"
} else {
    Write-Host "❌ Hubo un error. Verifica tu conexion o el login." -ForegroundColor Red
}