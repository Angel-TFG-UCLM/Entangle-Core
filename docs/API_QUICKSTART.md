# Guía Rápida: Usar la API

## 🚀 Inicio Rápido

### 1. Iniciar la API

```powershell
# Local
python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload

# En Azure ya está desplegada en:
# https://tu-app.azurecontainerapps.io
```

### 2. Verificar que Funciona

```bash
curl http://localhost:8000/api/v1/health
# Respuesta: {"status": "healthy"}
```

---

## 📝 Flujo Completo de Ingesta y Enriquecimiento

### Paso 1: Ingerir Repositorios

```bash
# Iniciar ingesta (usa config/ingestion_config.json)
curl -X POST "http://localhost:8000/api/v1/ingestion/repositories?use_segmentation=true"

# Respuesta:
{
  "task_id": "repo_ingestion_20251126_143022",
  "status": "running",
  "check_status_url": "/api/v1/ingestion/status/repo_ingestion_20251126_143022"
}
```

### Paso 2: Verificar Progreso

```bash
curl "http://localhost:8000/api/v1/ingestion/status/repo_ingestion_20251126_143022"

# Mientras ejecuta:
{
  "status": "running",
  "progress": "Procesando lote 5/10..."
}

# Cuando completa:
{
  "status": "completed",
  "stats": {
    "total_found": 2519,
    "repositories_inserted": 2150,
    "duration_seconds": 915.3
  }
}
```

### Paso 3: Ingerir Usuarios

```bash
curl -X POST "http://localhost:8000/api/v1/ingestion/users"

# Task ID: user_ingestion_20251126_143122
```

### Paso 4: Enriquecer Repositorios

```bash
curl -X POST "http://localhost:8000/api/v1/enrichment/repositories"

# Task ID: repo_enrichment_20251126_143222
```

### Paso 5: Enriquecer Usuarios

```bash
curl -X POST "http://localhost:8000/api/v1/enrichment/users"

# Task ID: user_enrichment_20251126_143322
```

### Paso 6: Ver Todas las Tareas

```bash
curl "http://localhost:8000/api/v1/tasks"

{
  "total_tasks": 4,
  "tasks": [
    {"task_id": "repo_ingestion_...", "status": "completed"},
    {"task_id": "user_ingestion_...", "status": "completed"},
    {"task_id": "repo_enrichment_...", "status": "completed"},
    {"task_id": "user_enrichment_...", "status": "running"}
  ]
}
```

---

## 🐍 Uso desde Python

```python
import requests

API_URL = "http://localhost:8000/api/v1"

# Iniciar ingesta
response = requests.post(f"{API_URL}/ingestion/repositories")
task_id = response.json()["task_id"]

# Monitorear
while True:
    status = requests.get(f"{API_URL}/ingestion/status/{task_id}").json()
    print(f"Estado: {status['status']}")
    if status["status"] in ["completed", "failed"]:
        break
    time.sleep(30)
```

**Script completo**: `scripts/api_client_example.py`

---

## 🌐 Uso desde Azure

```bash
# Reemplazar localhost con tu URL de Azure
API_URL="https://tu-app.azurecontainerapps.io/api/v1"

# Mismo flujo que local
curl -X POST "$API_URL/ingestion/repositories?use_segmentation=true"
```

---

## 📊 Parámetros Importantes

### Ingesta de Repositorios
- `max_results`: Límite de repos (opcional)
- `incremental`: Solo actualizar cambios (default: false)
- `use_segmentation`: Superar límite de 1000 (default: false)

### Ingesta de Usuarios
- `max_repos`: Límite de repos a procesar (opcional)
- `batch_size`: Tamaño de lote (default: 50)

### Enriquecimiento
- `max_repos`/`max_users`: Límite de elementos (opcional)
- `force_reenrich`: Re-enriquecer ya enriquecidos (default: false)
- `batch_size`: Tamaño de lote (default: 10)

---

## 🔍 Otros Endpoints Útiles

```bash
# Rate limit de GitHub
curl "$API_URL/rate-limit"

# Info de organización
curl "$API_URL/organizations/qiskit"

# Info de repositorio
curl "$API_URL/repositories/qiskit/qiskit"

# Info de usuario
curl "$API_URL/users/torvalds"

# Buscar repositorios
curl "$API_URL/search/repositories?query=quantum+computing&first=10"
```

---

## 📖 Documentación Completa

- **Documentación detallada**: [`docs/API_ENDPOINTS.md`](API_ENDPOINTS.md)
- **Swagger UI (interactivo)**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

---

## ⚡ Tips

1. **Background Tasks**: Todas las operaciones de ingesta/enriquecimiento son asíncronas
2. **Persistencia**: Los datos se guardan automáticamente en MongoDB
3. **Rate Limit**: Los procesos manejan automáticamente el rate limit de GitHub
4. **Monitoreo**: Usa `/tasks` para ver todas las tareas activas e históricas

---

## 🆘 Problemas Comunes

### API no responde
```bash
# Verificar que está ejecutándose
curl http://localhost:8000/api/v1/health

# Verificar logs
azd monitor --logs  # En Azure
```

### Tarea queda en "running"
- Es normal, las operaciones pueden tomar 15-45 minutos
- Consulta progreso con `/status/{task_id}`

### Error de MongoDB
- Verifica que `MONGO_URI` está configurado correctamente
- Verifica conectividad a MongoDB

---

## 💡 Ejemplos Avanzados

### Ingesta Incremental Diaria
```bash
# Solo actualiza repos modificados (rápido)
curl -X POST "$API_URL/ingestion/repositories?incremental=true"
```

### Ingesta Completa con Segmentación
```bash
# Supera límite de 1000 repos
curl -X POST "$API_URL/ingestion/repositories?use_segmentation=true"
```

### Re-enriquecimiento Forzado
```bash
# Re-enriquecer todos los usuarios
curl -X POST "$API_URL/enrichment/users?force_reenrich=true"
```

---

Para más información, consulta [`docs/API_ENDPOINTS.md`](API_ENDPOINTS.md)
