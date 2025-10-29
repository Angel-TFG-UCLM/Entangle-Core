# IngestionEngine - Motor de Ingesta de Repositorios

## Resumen

El **IngestionEngine** es el componente central del sistema de ingesta parametrizable desarrollado para el TFG. Este módulo orquesta todo el flujo de extracción, filtrado y almacenamiento de repositorios de software cuántico desde GitHub.

## Características Implementadas

### ✅ Componentes Principales

1. **Clase IngestionEngine** (`src/github/ingestion.py`)
   - Motor central que orquesta todo el proceso
   - Integración con GitHubGraphQLClient
   - Sistema completo de filtros
   - Almacenamiento múltiple (MongoDB y JSON)
   - Generación de reportes con estadísticas

2. **Sistema de Filtros**
   - ✅ **Filtro de forks**: Excluye repositorios fork
   - ✅ **Filtro de estrellas**: Mínimo de 10 estrellas
   - ✅ **Filtro de lenguajes**: Python, C++, Q#, Rust, Julia, JavaScript
   - ✅ **Filtro de inactividad**: Máximo 365 días sin actualización
   - ✅ **Filtro de keywords**: Validación de términos cuánticos

3. **Almacenamiento**
   - ✅ MongoDB con upsert (actualizar o insertar)
   - ✅ Archivos JSON con metadata completa
   - ✅ Metadata de ingesta (fecha, versión)

4. **Estadísticas y Reportes**
   - Total de repositorios encontrados/filtrados/guardados
   - Tasa de éxito del proceso
   - Rechazo por tipo de filtro
   - Distribución por lenguaje
   - Estadísticas de estrellas (promedio, máximo, mínimo)
   - Duración del proceso

## Arquitectura

```
IngestionEngine
├── __init__()        → Inicializa cliente, config, db
├── run()             → Flujo completo de ingesta
│   ├── _search_repositories()     → Búsqueda con paginación
│   ├── filter_repositories()      → Aplicación de filtros
│   └── save_results()             → Almacenamiento
│       ├── MongoDB (upsert)
│       └── JSON (con metadata)
└── _generate_report() → Generación de estadísticas
```

## Flujo de Ejecución

### 1. Fase de Búsqueda
```python
# Busca repositorios usando GitHubGraphQLClient
repositories = engine._search_repositories(max_results=100)
```

**Output**: Lista de repositorios encontrados en GitHub con la query construida desde `IngestionConfig`

### 2. Fase de Filtrado
```python
# Aplica todos los filtros de calidad
filtered = engine.filter_repositories(repositories)
```

**Filtros aplicados en orden**:
1. Fork → Rechaza si `isFork=True` y `exclude_forks=True`
2. Stars → Rechaza si `stargazerCount < min_stars`
3. Language → Rechaza si lenguaje no está en lista permitida
4. Inactivity → Rechaza si `updatedAt` > `max_inactivity_days`
5. Keywords → Rechaza si no contiene ninguna keyword cuántica

### 3. Fase de Almacenamiento
```python
# Guarda resultados en MongoDB y/o JSON
engine.save_results(filtered, save_to_db=True, save_to_json=True)
```

**Formato JSON**:
```json
{
  "metadata": {
    "ingestion_date": "2024-10-13T19:01:14+00:00",
    "total_repositories": 13,
    "config_version": "1.0",
    "criteria": { ... }
  },
  "repositories": [ ... ]
}
```

### 4. Fase de Reporte
```python
# Genera reporte completo con estadísticas
report = engine._generate_report(filtered)
```

## Uso

### Uso Básico (Función Helper)
```python
from src.github.ingestion import run_ingestion

# Ejecuta ingesta completa con configuración por defecto
report = run_ingestion(
    max_results=100,
    save_to_db=True,
    save_to_json=True,
    output_file="ingestion_results.json"
)
```

### Uso Avanzado (Clase Completa)
```python
from src.github.ingestion import IngestionEngine
from src.github.graphql_client import GitHubGraphQLClient
from src.core.config import ingestion_config
from src.core.db import Database

# Crear instancias personalizadas
client = GitHubGraphQLClient()
config = ingestion_config
db = Database()

# Inicializar motor
engine = IngestionEngine(client, config, db)

# Ejecutar con opciones personalizadas
report = engine.run(
    max_results=200,
    save_to_db=True,
    save_to_json=True,
    output_file="custom_results.json"
)

# Acceder a estadísticas
print(f"Encontrados: {report['summary']['total_found']}")
print(f"Válidos: {report['summary']['total_filtered']}")
print(f"Tasa: {report['summary']['success_rate']}")
```

## Resultados de Pruebas

### Test Suite Completo (`tests/test_ingestion.py`)

```
✓ PASS - Inicialización
✓ PASS - Búsqueda
✓ PASS - Filtrado
✓ PASS - Flujo completo JSON
✓ PASS - Función helper
✓ PASS - Filtros individuales

Resultado: 6/6 pruebas pasadas
Tasa de éxito: 100.0%
```

### Ejemplo de Ejecución Real

**Input**:
- max_results: 15
- save_to_db: False
- save_to_json: True

**Output**:
```
Encontrados: 15
Válidos: 13
Guardados: 13
Tasa de éxito: 86.7%
Duración: 7.48s

Distribución por lenguaje:
  - Python: 13

Estadísticas:
  - Promedio estrellas: 1339.8
  - Máximo: 6561 (Qiskit/qiskit)
  - Mínimo: 59

Rechazos:
  - Por fork: 0
  - Por estrellas: 0
  - Por lenguaje: 2 (Jupyter Notebook, OpenQASM)
  - Por inactividad: 0
  - Por keywords: 0
```

## Repositorios de Ejemplo Encontrados

1. **Qiskit/qiskit** - 6561 ⭐ - Python
2. **quantumlib/Cirq** - 4724 ⭐ - Python
3. **PennyLaneAI/pennylane** - 2838 ⭐ - Python
4. **PennyLaneAI/pennylane-qiskit** - 217 ⭐ - Python
5. **qiskit-community/qiskit-braket-provider** - 68 ⭐ - Python

## Integración con Otros Componentes

### 1. IngestionConfig (`src/core/config.py`)
```python
# Carga criterios de config/ingestion_config.json
config.keywords          # ["quantum", "qiskit", "braket", ...]
config.languages         # ["Python", "C++", "Q#", ...]
config.min_stars         # 10
config.max_inactivity_days  # 365
config.exclude_forks     # True
```

### 2. GitHubGraphQLClient (`src/github/graphql_client.py`)
```python
# Ejecuta búsqueda con paginación automática
client.search_repositories_all_pages(
    config_criteria=config,
    max_results=100
)
```

### 3. Database (`src/core/db.py`)
```python
# Conexión y almacenamiento en MongoDB
db.connect()
collection = db.get_collection("repositories")
collection.update_one({"id": repo_id}, {"$set": repo}, upsert=True)
```

### 4. Logger (`src/core/logger.py`)
```python
# Log completo del proceso
logger.info("Búsqueda completada")
logger.debug("Repo rechazado (fork): owner/repo")
logger.error("Error en la ingesta", exc_info=True)
```

## Próximos Pasos

### Sprint Actual (Sprint 2)
- [x] ✅ Sistema de configuración parametrizable
- [x] ✅ Cliente GraphQL de GitHub
- [x] ✅ Motor de ingesta (IngestionEngine)
- [ ] ⏳ Integración con API REST (endpoints)
- [ ] ⏳ Pruebas de integración completas

### Sprint Futuro (Sprint 3)
- [ ] Extracción de organizaciones
- [ ] Extracción de usuarios/colaboradores
- [ ] Análisis de patrones de colaboración
- [ ] Métricas de calidad

## Archivos Generados

```
Backend/
├── src/github/ingestion.py          [NUEVO] Motor de ingesta
├── tests/test_ingestion.py          [NUEVO] Suite de pruebas
├── tests/test_ingestion_results.json [GENERADO] Resultados test
├── tests/test_helper_results.json    [GENERADO] Resultados helper
└── ingestion_results.json            [GENERADO] Salida por defecto
```

## Configuración Utilizada

**Archivo**: `config/ingestion_config.json`

```json
{
  "version": "1.0",
  "keywords": ["quantum", "qiskit", "braket", "cirq", "pennylane"],
  "languages": ["Python", "C++", "Q#", "Rust", "Julia", "JavaScript"],
  "min_stars": 10,
  "max_inactivity_days": 365,
  "exclude_forks": true,
  "additional_filters": {
    "min_contributors": null,
    "topics": []
  }
}
```

## Logs del Sistema

El sistema genera logs detallados en 3 niveles:

1. **logs/app.log** - Información general (INFO)
2. **logs/errors.log** - Solo errores (ERROR)
3. **logs/debug.log** - Todo incluyendo debug (DEBUG)

Ejemplo de log durante ingesta:
```
2025-10-13 19:01:14 - [INFO] - INICIANDO PROCESO DE INGESTA
2025-10-13 19:01:14 - [INFO] - Fase 1: Búsqueda de repositorios
2025-10-13 19:01:14 - [INFO] - Búsqueda completada: 15 repositorios
2025-10-13 19:01:14 - [INFO] - Fase 2: Filtrado de repositorios
2025-10-13 19:01:14 - [DEBUG] - Repo rechazado (lenguaje Jupyter Notebook)
2025-10-13 19:01:14 - [INFO] - Filtrado completado: 13 repositorios válidos
2025-10-13 19:01:14 - [INFO] - Fase 3: Almacenamiento de resultados
2025-10-13 19:01:14 - [INFO] - ✓ 13 repositorios guardados
2025-10-13 19:01:14 - [INFO] - PROCESO COMPLETADO EXITOSAMENTE
```

## Conclusión

El **IngestionEngine** está completamente implementado y probado. Es el "corazón del sistema" que integra todos los componentes desarrollados hasta ahora:

- ✅ Configuración parametrizable (IngestionConfig)
- ✅ Cliente GraphQL con rate limit (GitHubGraphQLClient)
- ✅ Sistema completo de filtros (5 filtros)
- ✅ Almacenamiento dual (MongoDB + JSON)
- ✅ Estadísticas y reportes detallados
- ✅ Logging exhaustivo
- ✅ Suite de pruebas (100% pass rate)

**Estado**: ✅ **COMPLETADO Y FUNCIONAL**
