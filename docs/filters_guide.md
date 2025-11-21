# Filtros Avanzados de Calidad para Repositorios

## Resumen

Este módulo (`src/github/filters.py`) implementa filtros adicionales de calidad y relevancia basados en los criterios del paper académico, garantizando que los datos finales sean representativos, activos y realmente relacionados con software cuántico.

## Arquitectura

### Clase RepositoryFilters

Clase estática que agrupa todos los filtros. Cada método es independiente y testeable.

```python
from src.github.filters import RepositoryFilters

# Usar filtros individualmente
is_valid = RepositoryFilters.is_active(repo, max_inactivity_days=365)
```

## Filtros Implementados

### 1. **is_active** - Actividad Reciente ⏰

Verifica que el repositorio haya sido actualizado recientemente.

**Criterios:**
- Última actualización dentro de `max_inactivity_days` (por defecto 365 días)
- Usa `updatedAt` o `pushedAt`

**Ejemplo:**
```python
# Repo actualizado hace 30 días → PASA
# Repo actualizado hace 400 días → RECHAZADO
RepositoryFilters.is_active(repo, max_inactivity_days=365)
```

**Test:**
```
✓ Repo activo (30 días): True
✓ Repo inactivo (400 días): False
```

---

### 2. **is_valid_fork** - Fork con Contribuciones 🔀

Excluye forks que son simples copias sin contribuciones propias.

**Criterios:**
- Si no es fork → PASA
- Si es fork → Debe tener:
  - Al menos 10 commits, O
  - Al menos 5 issues/PRs combinados

**Ejemplo:**
```python
# No es fork → PASA
# Fork con 100 commits → PASA
# Fork con 5 commits y 0 issues → RECHAZADO
RepositoryFilters.is_valid_fork(repo)
```

**Test:**
```
✓ No es fork: True
✓ Fork con 100 commits: True
✓ Fork sin contribuciones: False
```

---

### 3. **has_description** - Documentación 📝

Verifica que el repositorio tenga descripción o README.

**Criterios:**
- Tiene descripción no vacía, O
- Tiene README (campo `object.text` no nulo)

**Ejemplo:**
```python
# Con descripción y README → PASA
# Solo con descripción → PASA
# Sin descripción ni README → RECHAZADO
RepositoryFilters.has_description(repo)
```

**Test:**
```
✓ Con descripción y README: True
✓ Solo con descripción: True
✓ Sin descripción ni README: False
```

---

### 4. **is_minimal_project** - Tamaño Mínimo 📦

Excluye proyectos muy pequeños o triviales.

**Criterios:**
- Al menos X commits (por defecto 10)
- Al menos Y KB de tamaño (por defecto 10 KB)

**Ejemplo:**
```python
# 100 commits, 1000 KB → PASA
# 10 commits, 10 KB → PASA
# 5 commits, 5 KB → RECHAZADO
RepositoryFilters.is_minimal_project(repo, min_commits=10, min_size_kb=10)
```

**Test:**
```
✓ Proyecto grande (100 commits, 1000 KB): True
✓ Proyecto mínimo (10 commits, 10 KB): True
✓ Proyecto muy pequeño (5 commits, 5 KB): False
```

---

### 5. **matches_keywords** - Keywords Cuánticas 🔬

Verifica presencia de palabras clave cuánticas.

**Busca en:**
- Nombre del repositorio
- Descripción
- Topics
- README (primeras 500 caracteres)

**Criterios:**
- Al menos una keyword debe estar presente

**Ejemplo:**
```python
keywords = ["quantum", "qiskit", "braket", "cirq", "pennylane"]

# Nombre: "quantum-simulator" → PASA
# Descripción: "using qiskit" → PASA
# Sin keywords → RECHAZADO
RepositoryFilters.matches_keywords(repo, keywords)
```

**Test:**
```
✓ Keyword en nombre: True
✓ Keyword en descripción: True
✓ Sin keywords cuánticas: False
```

---

### 6. **has_valid_language** - Lenguaje Válido 💻

Verifica que el lenguaje principal esté permitido.

**Criterios:**
- El lenguaje principal (`primaryLanguage.name`) debe estar en la lista

**Ejemplo:**
```python
valid_languages = ["Python", "C++", "Q#", "Rust", "Julia", "JavaScript"]

# Python → PASA
# Rust → PASA
# Go → RECHAZADO
RepositoryFilters.has_valid_language(repo, valid_languages)
```

**Test:**
```
✓ Lenguaje Python: True
✓ Lenguaje Rust: True
✓ Lenguaje Go: False
```

---

### 7. **is_not_archived** - No Archivado 📂

Excluye repositorios archivados.

**Criterios:**
- `isArchived` debe ser `False`

**Ejemplo:**
```python
# isArchived = False → PASA
# isArchived = True → RECHAZADO
RepositoryFilters.is_not_archived(repo)
```

**Test:**
```
✓ Repo no archivado: True
✓ Repo archivado: False
```

---

### 8. **has_minimum_stars** - Estrellas Mínimas ⭐

Verifica popularidad mínima.

**Criterios:**
- Al menos X estrellas (por defecto 10)

**Ejemplo:**
```python
# 50 estrellas → PASA
# 10 estrellas → PASA
# 5 estrellas → RECHAZADO
RepositoryFilters.has_minimum_stars(repo, min_stars=10)
```

**Test:**
```
✓ Repo con 50 estrellas: True
✓ Repo con 10 estrellas: True
✓ Repo con 5 estrellas: False
```

---

### 9. **has_community_engagement** - Engagement 👥

Verifica que haya interacción de la comunidad.

**Criterios (flexible - cumplir al menos uno):**
- Al menos X watchers (por defecto 3), O
- Al menos Y forks (por defecto 1)

**Ejemplo:**
```python
# 10 watchers, 5 forks → PASA
# 3 watchers, 0 forks → PASA
# 1 watcher, 0 forks → RECHAZADO
RepositoryFilters.has_community_engagement(repo, min_watchers=3, min_forks=1)
```

**Test:**
```
✓ Repo con 10 watchers y 5 forks: True
✓ Repo con 3 watchers y 0 forks: True
✓ Repo con 1 watcher y 0 forks: False
```

---

## Integración con IngestionEngine

Los filtros están integrados en `IngestionEngine.filter_repositories()` en el siguiente orden:

```python
def filter_repositories(self, repositories):
    for repo in repositories:
        # 1. No archivado
        if not RepositoryFilters.is_not_archived(repo):
            continue
        
        # 2. Tiene descripción
        if not RepositoryFilters.has_description(repo):
            continue
        
        # 3. Tamaño mínimo
        if not RepositoryFilters.is_minimal_project(repo):
            continue
        
        # 4. Actividad reciente
        if not RepositoryFilters.is_active(repo):
            continue
        
        # 5. Fork válido
        if not RepositoryFilters.is_valid_fork(repo):
            continue
        
        # 6. Keywords cuánticas
        if not RepositoryFilters.matches_keywords(repo):
            continue
        
        # 7. Lenguaje válido
        if not RepositoryFilters.has_valid_language(repo):
            continue
        
        # 8. Estrellas mínimas
        if not RepositoryFilters.has_minimum_stars(repo):
            continue
        
        # 9. Engagement comunidad
        if not RepositoryFilters.has_community_engagement(repo):
            continue
        
        # PASA todos los filtros
        filtered.append(repo)
```

## Estadísticas Generadas

El `IngestionEngine` genera estadísticas detalladas de rechazos:

```python
{
    "filtering": {
        "rejected_by_archived": 0,
        "rejected_by_no_description": 5,
        "rejected_by_minimal_project": 8,
        "rejected_by_inactivity": 3,
        "rejected_by_fork": 2,
        "rejected_by_keywords": 1,
        "rejected_by_language": 7,
        "rejected_by_stars": 0,
        "rejected_by_community_engagement": 4
    }
}
```

## Funciones Helper

El módulo también proporciona funciones helper para aplicar filtros en lote:

```python
from src.github.filters import (
    filter_by_activity,
    filter_by_fork_validity,
    filter_by_documentation,
    filter_by_project_size,
    filter_by_keywords,
    filter_by_language,
    apply_all_filters
)

# Aplicar un filtro específico
active_repos = filter_by_activity(repositories, max_inactivity_days=365)

# Aplicar todos los filtros
filtered = apply_all_filters(
    repositories,
    keywords=["quantum", "qiskit"],
    valid_languages=["Python", "C++"],
    max_inactivity_days=365,
    min_stars=10,
    min_commits=10,
    min_size_kb=10
)
```

## Datos Adicionales en GraphQL Query

Para soportar los nuevos filtros, se agregaron campos a la query GraphQL:

```graphql
hasIssuesEnabled
hasWikiEnabled
openIssues: issues(states: OPEN) { totalCount }
closedIssues: issues(states: CLOSED) { totalCount }
pullRequests { totalCount }
defaultBranchRef {
  target {
    ... on Commit {
      history { totalCount }
    }
  }
}
diskUsage
object(expression: "HEAD:README.md") {
  ... on Blob {
    text
  }
}
```

## Resultados de Tests

Suite completa de tests en `tests/test_filters.py`:

```
✅ PASS - Actividad reciente
✅ PASS - Forks válidos
✅ PASS - Descripción/README
✅ PASS - Tamaño mínimo
✅ PASS - Keywords cuánticas
✅ PASS - Lenguaje válido
✅ PASS - No archivado
✅ PASS - Estrellas mínimas
✅ PASS - Engagement comunidad
✅ PASS - Cadena completa

Resultado: 10/10 tests pasados
Tasa de éxito: 100.0%
```

## Ejemplo de Uso Completo

```python
from src.github.ingestion import run_ingestion

# Los filtros se aplican automáticamente
report = run_ingestion(
    max_results=100,
    save_to_db=True,
    save_to_json=True,
    output_file="filtered_repos.json"
)

# Ver estadísticas
print(f"Total encontrados: {report['summary']['total_found']}")
print(f"Total válidos: {report['summary']['total_filtered']}")
print(f"Tasa de éxito: {report['summary']['success_rate']}")

# Ver rechazos por filtro
for filtro, count in report['filtering'].items():
    print(f"  - {filtro}: {count}")
```

## Configuración

Los criterios se configuran en `config/ingestion_config.json`:

```json
{
  "keywords": ["quantum", "qiskit", "braket", "cirq", "pennylane"],
  "languages": ["Python", "C++", "Q#", "Rust", "Julia", "JavaScript"],
  "min_stars": 10,
  "max_inactivity_days": 365,
  "exclude_forks": true
}
```

## Criterios de Calidad Cumplidos

✅ **Modularidad**: Cada filtro es una función independiente  
✅ **Testabilidad**: Tests unitarios para cada filtro  
✅ **Logging**: Todos los rechazos se registran con `logger.debug()`  
✅ **Estadísticas**: Contadores detallados por tipo de filtro  
✅ **Documentación**: Docstrings completos y ejemplos  
✅ **Configurabilidad**: Parámetros ajustables  

## Conclusión

El sistema de filtros avanzados garantiza que solo se almacenen repositorios de software cuántico que sean:

- ✅ Activos (actualizados recientemente)
- ✅ Documentados (con descripción o README)
- ✅ Sustanciales (tamaño y commits mínimos)
- ✅ Relevantes (keywords cuánticas presentes)
- ✅ En lenguajes adecuados
- ✅ Con engagement de comunidad
- ✅ No archivados
- ✅ Con contribuciones propias (si son forks)

**Estado**: ✅ **COMPLETADO Y VALIDADO (100% tests)**
