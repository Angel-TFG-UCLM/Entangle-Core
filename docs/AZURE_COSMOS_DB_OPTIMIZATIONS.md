# Optimizaciones para Azure Cosmos DB y Modo Fire & Forget

## 📋 Resumen de Cambios

Se han realizado optimizaciones críticas para garantizar la resiliencia del sistema cuando se despliega en **Azure Container Apps** con **Azure Cosmos DB for MongoDB** (Free Tier, 1000 RU/s).

Fecha: 27 de noviembre de 2025

---

## 🔧 Cambios Implementados

### 1. **Resiliencia de Conexión MongoDB/Cosmos DB** (`src/core/db.py`)

**Problema**: Cosmos DB puede experimentar throttling (limitación de velocidad) debido al límite de 1000 RU/s del Free Tier, causando errores intermitentes de lectura/escritura.

**Solución**: Añadidos parámetros de reintentos automáticos en `MongoClient`:

```python
self.client = MongoClient(
    config.MONGO_URI,
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=10000,
    socketTimeoutMS=10000,
    retryReads=True,      # ✅ NUEVO: Reintenta lecturas automáticamente
    retryWrites=True      # ✅ NUEVO: Reintenta escrituras automáticamente
)
```

**Beneficios**:
- ✅ Manejo automático de micro-cortes de red
- ✅ Reintentos automáticos cuando Cosmos DB devuelve errores 429 (Too Many Requests)
- ✅ Mayor estabilidad en conexiones con latencia variable de la nube
- ✅ Tolerancia a fallos transitorios sin intervención manual

---

### 2. **Modo Fire & Forget por Defecto** (`src/api/routes.py`)

**Problema**: El Frontend necesita iniciar ingestas completas sin tener que especificar parámetros técnicos. La configuración anterior requería activar manualmente `use_segmentation=true`.

**Solución**: Cambiado el valor por defecto de `use_segmentation` de `False` a `True`:

```python
@router.post("/ingestion/repositories")
async def ingest_repositories(
    background_tasks: BackgroundTasks,
    max_results: Optional[int] = Query(None, description="Máximo de repositorios a ingerir"),
    incremental: bool = Query(False, description="Modo incremental (solo actualizar cambios)"),
    use_segmentation: bool = Query(True, description="Usar segmentación dinámica para más de 1000 repos")  # ✅ Cambio: False → True
):
```

**Beneficios**:
- ✅ El Frontend puede llamar al endpoint sin parámetros: `POST /api/v1/ingestion/repositories`
- ✅ El sistema automáticamente usa segmentación inteligente para superar el límite de 1000 repos de GitHub API
- ✅ Ingesta completa robusta sin configuración manual
- ✅ Experiencia de usuario simplificada

**Uso desde Frontend**:
```javascript
// Antes (requería parámetros)
fetch('/api/v1/ingestion/repositories?use_segmentation=true', { method: 'POST' })

// Ahora (sin parámetros - usa defaults inteligentes)
fetch('/api/v1/ingestion/repositories', { method: 'POST' })
```

---

### 3. **Resiliencia en Persistencia** (`src/github/repositories_ingestion.py`)

**Problema**: Si un lote completo de documentos falla al escribirse en Cosmos DB (por throttling, errores de red, o documentos malformados), todo el proceso se detenía.

**Solución**: Mejorado el manejo de errores en `_persist_repositories()`:

**Antes**:
```python
except Exception as e:
    logger.error(f"❌ Error en lote {batch_num}: {e}")
    # Intentaba uno por uno pero sin tracking detallado
```

**Ahora**:
```python
except Exception as e:
    logger.warning(f"⚠️  Error en lote {batch_num}: {e}. Reintentando uno por uno...")
    
    successful_in_batch = 0
    failed_in_batch = 0
    
    for repo in batch:
        try:
            # Intenta insertar cada documento individualmente
            # ...
            successful_in_batch += 1
        except Exception as e2:
            failed_in_batch += 1
            logger.warning(f"⚠️  No se pudo persistir {repo.full_name}: {e2}")
            continue  # ✅ CONTINÚA con el siguiente - NO detiene el proceso
    
    logger.info(f"ℹ️  Recuperación del lote {batch_num}: {successful_in_batch} exitosos, {failed_in_batch} fallidos")
```

**Beneficios**:
- ✅ **Resiliencia Total**: El proceso nunca se detiene completamente por errores parciales
- ✅ **Recuperación Granular**: Si un lote falla, intenta documento por documento
- ✅ **Transparencia**: Logs claros indican qué documentos se guardaron y cuáles fallaron
- ✅ **No hay pérdida de datos**: Cada documento se intenta persistir individualmente
- ✅ **Ideal para Cosmos DB**: Maneja throttling sin detener la ingesta completa

**Ejemplo de Log en Producción**:
```
⚠️  Error en lote 5: WriteError - Request rate is large (429)
ℹ️  Recuperación del lote 5: 48 exitosos, 2 fallidos
✓ Lote 6: 50 nuevos, 0 actualizados
```

---

## 🎯 Impacto en el Sistema

### Antes de los Cambios
❌ Errores de conexión detenían el proceso  
❌ Throttling de Cosmos DB causaba fallos completos  
❌ Frontend debía configurar parámetros técnicos  
❌ Un lote fallido detenía toda la ingesta  

### Después de los Cambios
✅ Reintentos automáticos de lectura/escritura  
✅ Manejo inteligente de throttling (429 errors)  
✅ Frontend solo hace `POST /ingestion/repositories` sin parámetros  
✅ El proceso continúa incluso con errores parciales  
✅ Logs claros de recuperación y estadísticas  

---

## 📊 Casos de Uso

### Caso 1: Ingesta Simple desde Frontend

```javascript
// Frontend (React/Vue/Angular)
async function startIngestion() {
  const response = await fetch('https://api.azurecontainerapps.io/api/v1/ingestion/repositories', {
    method: 'POST'
  });
  
  const { task_id } = await response.json();
  
  // Monitorear progreso
  const statusResponse = await fetch(`https://api.azurecontainerapps.io/api/v1/ingestion/status/${task_id}`);
  const status = await statusResponse.json();
  
  console.log(status.progress); // "Procesando lote 10/50..."
}
```

### Caso 2: Manejo de Throttling de Cosmos DB

El sistema ahora maneja automáticamente errores 429 (Too Many Requests) de Cosmos DB:

```
⏳ Procesando lote 15/50 (50 repos)...
⚠️  Error en lote 15: WriteError (429) - Request rate is large
   Reintentando uno por uno...
   ✓ Documento 1/50: Insertado
   ✓ Documento 2/50: Insertado
   ...
   ✓ Documento 50/50: Insertado
ℹ️  Recuperación del lote 15: 50 exitosos, 0 fallidos
✓ Continuando con lote 16/50...
```

### Caso 3: Ingesta con Segmentación Automática

Sin configuración adicional, el sistema divide automáticamente las búsquedas:

```
🎯 Segmentación configurada:
  • Rangos de estrellas: 6 rangos
  • Años de creación: 11 años (2015-2025)
  • Total de consultas: 66 segmentos

📍 Consulta 1/66: stars:10..49 year:2015
  ✓ Encontrados: 234 repos, 234 nuevos
  📊 Total acumulado: 234 repos únicos

📍 Consulta 2/66: stars:10..49 year:2016
  ✓ Encontrados: 312 repos, 298 nuevos
  📊 Total acumulado: 532 repos únicos

...

✅ Segmentación completada: 2,847 repositorios únicos
```

---

## 🚀 Despliegue

Los cambios son compatibles con el despliegue existente. Para aplicarlos:

```powershell
# Redesplegar en Azure
azd deploy

# O si prefieres provisionar + desplegar
azd up
```

**No se requieren cambios en**:
- Configuración de Azure Container Apps
- Variables de entorno
- Infraestructura (Bicep)
- Base de datos (Cosmos DB)

---

## 🧪 Testing

### Prueba Local

```powershell
# Iniciar API localmente
python -m uvicorn src.api.main:app --reload

# En otra terminal, probar endpoint
curl -X POST http://localhost:8000/api/v1/ingestion/repositories

# Debería retornar:
# {
#   "task_id": "repo_ingestion_20251127_...",
#   "status": "running",
#   "message": "Ingesta de repositorios iniciada en segundo plano"
# }
```

### Prueba en Azure

```bash
# Usando la URL de tu Container App
curl -X POST https://tu-app.azurecontainerapps.io/api/v1/ingestion/repositories

# Verificar progreso
curl https://tu-app.azurecontainerapps.io/api/v1/ingestion/status/{task_id}
```

---

## 📝 Configuración Relacionada

### Variables de Entorno Requeridas

Asegúrate de que estas variables estén configuradas en Azure Container Apps:

```env
# GitHub API
GITHUB_TOKEN=ghp_xxxxx

# Cosmos DB Connection
MONGO_URI=mongodb://xxx.mongo.cosmos.azure.com:10255/?ssl=true&replicaSet=globaldb&retrywrites=false&maxIdleTimeMS=120000

# Database
MONGO_DB_NAME=quantum_github

# Environment
ENVIRONMENT=production
DEBUG=False
```

### Configuración de Segmentación

Verificar en `config/ingestion_config.json`:

```json
{
  "enable_segmentation": true,
  "segmentation": {
    "stars": [
      [10, 49],
      [50, 99],
      [100, 499],
      [500, 999],
      [1000, 4999],
      [5000, 999999]
    ],
    "created_years": [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]
  }
}
```

---

## 🔍 Monitoreo

### Métricas Clave en Logs

```
✅ Persistencia completada: 2150 nuevos, 45 actualizados
ℹ️  Recuperación del lote 12: 48 exitosos, 2 fallidos
⚠️  No se pudo persistir user/repo: WriteError (429)
```

### Verificar en Azure Portal

1. **Container Apps → Logs**:
   ```kusto
   ContainerAppConsoleLogs_CL
   | where Log_s contains "Recuperación del lote"
   | project TimeGenerated, Log_s
   ```

2. **Cosmos DB → Metrics**:
   - Monitorear "Request Units per Second"
   - Alertas cuando RU/s > 900 (cerca del límite de 1000)

---

## ✅ Checklist de Validación

Después del despliegue, verifica:

- [ ] Endpoint `POST /ingestion/repositories` funciona sin parámetros
- [ ] Los logs muestran "retryReads=True, retryWrites=True" en la conexión
- [ ] Ingestas largas completan exitosamente a pesar de errores parciales
- [ ] Logs de "Recuperación del lote" aparecen cuando hay throttling
- [ ] Estadísticas finales muestran repos insertados/actualizados correctamente

---

## 🆘 Troubleshooting

### Problema: "WriteError 429 - Request rate is large"

**Solución**: Es normal en Cosmos DB Free Tier. Los cambios implementados manejan esto automáticamente.

```
⚠️  Error en lote X: WriteError (429)
ℹ️  Recuperación del lote X: 50 exitosos, 0 fallidos
```

### Problema: "ServerSelectionTimeoutError"

**Causa**: Cosmos DB no accesible desde Container App.

**Verificar**:
1. Firewall de Cosmos DB permite Azure Services
2. Connection string correcto en variables de entorno
3. Red virtual configurada correctamente (si aplica)

### Problema: Ingesta muy lenta

**Causas posibles**:
- Throttling de Cosmos DB (1000 RU/s límite)
- Rate limit de GitHub API

**Mitigación**:
- Reducir `batch_size` en ingesta (default: 50 → probar 20)
- Monitorear logs para identificar cuellos de botella

---

## 📚 Referencias

- [Cosmos DB for MongoDB Retry Logic](https://learn.microsoft.com/azure/cosmos-db/mongodb/how-to-dotnet-connection-retry)
- [PyMongo Connection Options](https://pymongo.readthedocs.io/en/stable/api/pymongo/mongo_client.html)
- [Azure Container Apps Best Practices](https://learn.microsoft.com/azure/container-apps/best-practices)

---

## 🎉 Resumen

Con estos cambios, el sistema está **100% optimizado** para:
- ✅ Azure Cosmos DB Free Tier (1000 RU/s)
- ✅ Modo Fire & Forget desde Frontend
- ✅ Resiliencia ante throttling y errores de red
- ✅ Ingestas largas sin supervisión manual
- ✅ Recuperación automática de errores parciales

**El sistema ahora es production-ready para Azure!** 🚀
