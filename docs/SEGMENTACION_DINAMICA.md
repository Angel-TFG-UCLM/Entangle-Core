# 📊 Segmentación Dinámica para Superar el Límite de GitHub

## 🎯 Problema

GitHub Search API tiene un **límite de 1,000 resultados** por búsqueda. Esto significa que aunque haya 10,000 repositorios que coincidan con tu búsqueda, solo puedes recuperar los primeros 1,000.

**Ejemplo:**
```
Búsqueda: "quantum" stars:>10
Resultados reportados: 2,540
Resultados recuperables: 1,000 ❌
```

## 💡 Solución: Segmentación Dinámica

La segmentación dinámica divide la búsqueda en múltiples consultas más específicas, cada una con menos de 1,000 resultados:

```
Segmento 1: "quantum" stars:10..49  created:2020-01-01..2020-12-31  → 342 repos
Segmento 2: "quantum" stars:10..49  created:2021-01-01..2021-12-31  → 445 repos
Segmento 3: "quantum" stars:50..99  created:2020-01-01..2020-12-31  → 178 repos
...
Total: 5,000+ repositorios ✅
```

## 🔧 Configuración

### 1. Habilitar Segmentación

Editar `config/ingestion_config.json`:

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
  },
  "rate_limit": {
    "check_before_request": true,
    "min_remaining": 100,
    "wait_on_exhaustion": true
  }
}
```

### 2. Parámetros de Segmentación

#### `stars` (Rangos de Estrellas)

Define rangos de estrellas para dividir los repositorios:

```json
"stars": [
  [10, 49],      // Repos con 10-49 estrellas
  [50, 99],      // Repos con 50-99 estrellas
  [100, 499],    // Repos con 100-499 estrellas
  [500, 999],    // etc.
  [1000, 4999],
  [5000, 999999]
]
```

**Recomendaciones:**
- Rangos más pequeños = más consultas pero más exhaustivo
- Ajustar según la distribución esperada de repositorios
- El primer valor debe coincidir con `min_stars` de la configuración

#### `created_years` (Años de Creación)

Lista de años para segmentar temporalmente:

```json
"created_years": [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]
```

**Recomendaciones:**
- Incluir años con alta actividad en el dominio (ej: quantum computing desde 2015)
- Años recientes pueden tener más repos
- Puedes omitir años muy antiguos si no son relevantes

### 3. Control de Rate Limit

```json
"rate_limit": {
  "check_before_request": true,    // Verificar antes de cada consulta
  "min_remaining": 100,             // Mínimo de requests restantes
  "wait_on_exhaustion": true        // Esperar si se agota el límite
}
```

**Comportamiento:**
- ✅ `check_before_request: true` → Verifica antes de cada segmento
- ✅ `min_remaining: 100` → Si quedan menos de 100 requests, espera
- ✅ `wait_on_exhaustion: true` → Espera hasta que se resetee el rate limit
- ❌ `wait_on_exhaustion: false` → Continúa y puede fallar si se agota

## 📐 Cálculo de Consultas

### Fórmula

```
Total de Consultas = Rangos de Estrellas × Años de Creación
```

### Ejemplo

```json
"stars": [
  [10, 49], [50, 99], [100, 499], [500, 999], [1000, 4999], [5000, 999999]
],
"created_years": [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]
```

**Cálculo:**
- Rangos de estrellas: 6
- Años: 11
- **Total: 6 × 11 = 66 consultas**

### Repositorios Máximos Teóricos

```
Repositorios Máximos = Total Consultas × 1,000
66 consultas × 1,000 = 66,000 repositorios
```

**Nota:** En la práctica, será menor porque:
1. No todos los segmentos tienen 1,000 repos
2. Se aplican filtros de calidad después
3. Hay duplicados entre segmentos (eliminados automáticamente)

## 🚀 Ejecución

### Script Dedicado

```bash
cd scripts
python run_ingestion_segmented.py
```

### Flujo de Ejecución

1. **Validación**: Verifica que la segmentación esté habilitada
2. **Planificación**: Muestra número de consultas y repos estimados
3. **Confirmación**: Pide confirmación al usuario
4. **Segmentación**: Ejecuta cada combinación (estrellas × año)
5. **Deduplicación**: Elimina repos duplicados usando `full_name`
6. **Pipeline**: Aplica filtrado, validación y persistencia
7. **Resultados**: Guarda en `results/ingestion_segmented_results.json`

### Ejemplo de Salida

```
🚀 INICIANDO INGESTA CON SEGMENTACIÓN DINÁMICA

📊 Configuración de Segmentación:
  • Rangos de estrellas: 6
    1. 10 - 49 estrellas
    2. 50 - 99 estrellas
    3. 100 - 499 estrellas
    4. 500 - 999 estrellas
    5. 1,000 - 4,999 estrellas
    6. 5,000 - 999,999 estrellas

  • Años de creación: 11
    [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]

  • Total de consultas estimadas: 66
  • Repositorios estimados: 66,000 (máximo teórico)

¿Deseas continuar con la ingesta segmentada? [s/N]: s

📍 Consulta 1/66: stars:10..49 year:2015
  ✓ Encontrados: 234 repos, 234 nuevos
  📊 Total acumulado: 234 repos únicos

📍 Consulta 2/66: stars:10..49 year:2016
  ✓ Encontrados: 389 repos, 389 nuevos
  📊 Total acumulado: 623 repos únicos

...

✅ Búsqueda segmentada completada:
  • Consultas ejecutadas: 66/66
  • Repositorios únicos obtenidos: 5,432
```

## ⚙️ Implementación Técnica

### 1. Motor de Ingesta (`ingestion.py`)

```python
def _search_repositories(self, max_results: Optional[int] = None) -> List[Dict[str, Any]]:
    """Detecta si usar segmentación o búsqueda tradicional."""
    if self.config.enable_segmentation and self.config.segmentation:
        logger.info("📊 Modo de segmentación dinámica activado")
        return self._search_with_segmentation(max_results)
    else:
        # Búsqueda tradicional (límite 1000)
        return self.client.search_repositories_all_pages(...)
```

### 2. Búsqueda Segmentada

```python
def _search_with_segmentation(self, max_results: Optional[int] = None) -> List[Dict[str, Any]]:
    """Ejecuta múltiples consultas segmentadas."""
    all_repositories = {}  # Dict para evitar duplicados
    
    for star_range in star_ranges:
        for year in created_years:
            # Verificar rate limit
            self._check_rate_limit()
            
            # Buscar segmento
            segment_repos = self.client.search_repositories_segmented(
                min_stars=min_stars,
                max_stars=max_stars,
                created_year=year,
                max_results=1000
            )
            
            # Deduplicar por full_name
            for repo in segment_repos:
                full_name = repo.get("nameWithOwner")
                if full_name not in all_repositories:
                    all_repositories[full_name] = repo
```

### 3. Cliente GraphQL (`graphql_client.py`)

```python
def search_repositories_segmented(
    self,
    min_stars: int,
    max_stars: int,
    created_year: int,
    max_results: int = 1000
) -> List[Dict[str, Any]]:
    """Busca repos en un segmento específico."""
    
    # Construir query con segmentación
    query_parts = [
        f"stars:{min_stars}..{max_stars}",
        f"created:{created_year}-01-01..{created_year}-12-31",
        # ... keywords, languages, etc.
    ]
    
    # Ejecutar con paginación
    return self._execute_paginated_search(query_string)
```

### 4. Control de Duplicados

**Nivel 1: En Memoria (durante búsqueda)**
```python
all_repositories = {}  # Dict por full_name
for repo in segment_repos:
    full_name = repo.get("nameWithOwner")
    if full_name not in all_repositories:
        all_repositories[full_name] = repo
```

**Nivel 2: MongoDB (durante persistencia)**
```python
self.repo_db.bulk_upsert(
    documents=repositories,
    unique_field="id"  # GitHub ID único
)
```

## 📊 Ventajas y Consideraciones

### ✅ Ventajas

1. **Supera el límite de 1,000**: Obtén decenas de miles de repositorios
2. **Control granular**: Ajusta rangos según tus necesidades
3. **Deduplicación automática**: No te preocupes por duplicados
4. **Rate limit inteligente**: Espera automáticamente si se agota
5. **Reiniciable**: Si falla, MongoDB evita reinsertar duplicados
6. **Progreso visible**: Muestra avance de cada segmento

### ⚠️ Consideraciones

1. **Tiempo de ejecución**: 66 consultas pueden tardar 30-60 minutos
2. **Rate limit**: GitHub tiene límite de 5,000 requests/hora
3. **Memoria**: Miles de repos se mantienen en memoria temporalmente
4. **API costs**: Más consultas = más uso de la API (pero es gratis para cuentas normales)

## 🎓 Para tu TFG

### Documentar en la Memoria

```
"Para superar la limitación de 1,000 resultados de GitHub Search API, 
se implementó un sistema de segmentación dinámica que divide la búsqueda 
en múltiples consultas específicas por rangos de estrellas y años de 
creación. Este enfoque permitió obtener N repositorios frente a los 
1,000 del límite inicial, asegurando una muestra más representativa del 
ecosistema de computación cuántica en GitHub."
```

### Justificación Técnica

- **Problema identificado**: Limitación documentada de la API
- **Solución propuesta**: Segmentación dinámica configurable
- **Implementación**: 3 archivos modificados (config.py, ingestion.py, graphql_client.py)
- **Resultados**: X repositorios obtenidos vs 1,000 del límite
- **Trade-offs**: Mayor tiempo vs mayor completitud

## 📚 Referencias

- [GitHub Search API Documentation](https://docs.github.com/en/rest/search)
- [GraphQL API Rate Limits](https://docs.github.com/en/graphql/overview/resource-limitations)
- [Best Practices for Integrators](https://docs.github.com/en/rest/guides/best-practices-for-integrators)

---

**Última actualización**: 30 de octubre de 2025  
**Versión de configuración**: 2.0
