# Instalación de Herramientas para Despliegue en Azure

## ✅ Herramientas Requeridas

### 1. Azure Developer CLI (azd) - OBLIGATORIO ⚠️

Azure Developer CLI es la herramienta principal para desplegar en Azure.

**Instalación en Windows:**

```powershell
# Opción 1: Con winget (recomendado)
winget install microsoft.azd

# Opción 2: Con Chocolatey
choco install azd

# Opción 3: Con PowerShell script
powershell -ex AllSigned -c "Invoke-RestMethod 'https://aka.ms/install-azd.ps1' | Invoke-Expression"
```

**Verificar instalación:**
```powershell
azd version
```

**Documentación:** https://aka.ms/azd

---

### 2. Docker Desktop - OBLIGATORIO ⚠️

Necesario para construir imágenes de contenedor.

**Instalación:**
1. Descargar desde: https://www.docker.com/products/docker-desktop
2. Instalar y reiniciar el sistema
3. Iniciar Docker Desktop

**O con winget:**
```powershell
winget install Docker.DockerDesktop
```

**Verificar instalación:**
```powershell
docker --version
docker ps
```

---

### 3. Azure CLI (az) - OPCIONAL pero RECOMENDADO

Útil para operaciones avanzadas y debugging.

**Instalación:**

```powershell
# Opción 1: Con winget (recomendado)
winget install Microsoft.AzureCLI

# Opción 2: Con instalador MSI
# Descargar desde: https://aka.ms/installazurecliwindows
```

**Verificar instalación:**
```powershell
az --version
```

**Documentación:** https://learn.microsoft.com/cli/azure/

---

### 4. Git - Ya deberías tenerlo instalado ✅

**Verificar:**
```powershell
git --version
```

**Si no está instalado:**
```powershell
winget install Git.Git
```

---

### 5. Python 3.11+ - Ya lo tienes instalado ✅

**Verificar:**
```powershell
python --version
```

---

## 🔐 Configuración Inicial

### 1. Autenticación con Azure

```powershell
# Con Azure Developer CLI
azd auth login

# Con Azure CLI (si lo instalaste)
az login
```

Esto abrirá tu navegador para autenticarte.

### 2. Configurar Docker

Asegúrate de que Docker Desktop está ejecutándose:
- Verifica que el icono de Docker aparece en la bandeja del sistema
- Debe mostrar "Docker Desktop is running"

### 3. Verificar Suscripción de Azure

```powershell
# Listar suscripciones disponibles
az account list --output table

# Seleccionar una suscripción específica
az account set --subscription "Nombre o ID de suscripción"

# Verificar la suscripción activa
az account show
```

---

## 🧪 Verificar que Todo Está Listo

Ejecuta el script de verificación:

```powershell
python .\scripts\verify_deployment_ready.py
```

Deberías ver:
```
✅ Dockerfile: Dockerfile
✅ Requirements: requirements.txt
✅ Configuración Azure: azure.yaml
✅ Infraestructura Bicep: infra/main.bicep
✅ Ejemplo de variables: .env.example
✅ Archivo .env configurado correctamente
✅ Docker instalado: Docker version ...
✅ Azure Developer CLI instalado
✅ TODO LISTO PARA DESPLEGAR
```

---

## 🚀 Primer Despliegue

Una vez instaladas todas las herramientas:

```powershell
# 1. Autenticarse
azd auth login

# 2. Inicializar proyecto (solo la primera vez)
azd init

# 3. Desplegar
azd up
```

Durante `azd up` se te preguntará:
- **Environment name**: `tfg-backend-dev` (o el nombre que prefieras)
- **Azure location**: `westeurope` (o tu región preferida)
- **Subscription**: Selecciona tu suscripción de Azure

---

## 📝 Notas Importantes

### Requisitos de Sistema
- **Sistema Operativo**: Windows 10/11, macOS, o Linux
- **RAM**: Mínimo 8GB (16GB recomendado)
- **Espacio en Disco**: 10GB libres para Docker
- **Internet**: Conexión estable para descargar imágenes y desplegar

### Permisos en Azure
Necesitas tener permisos en tu suscripción de Azure para:
- Crear grupos de recursos
- Crear Container Apps
- Crear Container Registry
- Crear Log Analytics Workspace

Si no tienes permisos, contacta al administrador de tu suscripción.

### Firewall y Proxy
Si estás detrás de un firewall corporativo o proxy:
1. Configura las variables de entorno HTTP_PROXY y HTTPS_PROXY
2. Configura Docker para usar el proxy (Settings → Resources → Proxies)

---

## 🆘 Problemas Comunes

### "azd: command not found"

**Solución:**
```powershell
# Cerrar y reabrir PowerShell después de instalar
# O reiniciar el sistema
```

### "Docker daemon is not running"

**Solución:**
1. Iniciar Docker Desktop manualmente
2. Esperar a que inicie completamente (icono en bandeja del sistema)
3. Verificar con: `docker ps`

### "Az login fails"

**Solución:**
```powershell
# Usar el método de código de dispositivo
azd auth login --use-device-code
```

### Error de permisos en PowerShell

**Solución:**
```powershell
# Ejecutar PowerShell como Administrador
# O cambiar política de ejecución:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## 📚 Recursos Adicionales

- **Azure Developer CLI**: https://aka.ms/azd
- **Docker Desktop**: https://docs.docker.com/desktop/
- **Azure CLI**: https://learn.microsoft.com/cli/azure/
- **Azure Container Apps**: https://learn.microsoft.com/azure/container-apps/

---

## ✅ Checklist Post-Instalación

- [ ] `azd version` funciona
- [ ] `docker --version` funciona
- [ ] `docker ps` funciona (sin errores)
- [ ] `azd auth login` completado exitosamente
- [ ] `python .\scripts\verify_deployment_ready.py` muestra TODO OK
- [ ] Archivo `.env` configurado con valores reales

**¡Cuando todos los checks estén ✅, estás listo para desplegar!** 🚀

```powershell
azd up
```
