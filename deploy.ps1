# Archivo: desplegar.ps1
Write-Host "Iniciando despliegue manual a Azure Container Apps..." -ForegroundColor Cyan

$APP_NAME = "ca-entangle-uclm-api"
$GROUP = "rg-entangle-uclm"
$IMAGE = "crentangleuclm.azurecr.io/tfg-backend:latest"

Write-Host "Ordenando a Azure que descargue la nueva imagen..."
az containerapp update --name $APP_NAME --resource-group $GROUP --image $IMAGE

# 3. Confirmación
if ($?) {
    Write-Host "La actualizacion esta en marcha." -ForegroundColor Green
    Write-Host "Espera unos segundos y comprueba la web."
} else {
    Write-Host "Hubo un error. Asegurate de haber hecho 'az login' antes." -ForegroundColor Red
}