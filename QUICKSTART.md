# Quick Start - Despliegue en Azure

## Despliegue Rápido (5 minutos)

### 1. Instalar Herramientas
```powershell
winget install microsoft.azd
winget install Microsoft.AzureCLI
```

### 2. Login
```powershell
azd auth login
```

### 3. Configurar Variables
Edita `.env` con tus valores:
```env
GITHUB_TOKEN=tu_token_github
MONGO_URI=tu_cadena_conexion_mongodb
MONGO_DB_NAME=quantum_github
```

### 4. Desplegar
```powershell
azd up
```

Selecciona:
- Environment name: `tfg-backend-dev`
- Location: `westeurope`
- Subscription: Tu suscripción

### 5. Configurar Secretos
```powershell
azd env set GITHUB_TOKEN "tu_token"
azd env set MONGO_URI "tu_mongo_uri"
azd deploy
```

### 6. Verificar
```powershell
azd show
# Visita la URL mostrada + /api/v1/health
```

## Comandos Útiles

```powershell
# Ver logs
azd monitor --logs

# Actualizar aplicación
azd deploy

# Eliminar recursos
azd down
```

Para más detalles, consulta `DEPLOYMENT.md`.
