# Sistema de Ingesta y Enriquecimiento de Usuarios

## 📋 Descripción General

Sistema completo para extraer, almacenar y enriquecer información de usuarios de GitHub relacionados con proyectos de **Quantum Computing**. Sigue el mismo patrón exitoso implementado para repositorios: **ingesta básica + enriquecimiento detallado**.

**Fuente única**: Campo `collaborators` de repositorios ya ingestados, que incluye:
- Contributors con commits (REST API)
- Mentionable users (GraphQL)
- Metadata: `has_commits`, `is_mentionable`, `contributions`

---

## 🎯 Objetivos

1. **Identificar contribuyentes reales** del ecosistema quantum computing en GitHub
2. **Construir perfiles completos** de desarrolladores y organizaciones
3. **Calcular expertise quantum** mediante métricas específicas del dominio
4. **Preparar dataset** para análisis de colaboración y redes de investigación

---

## 🏗️ Arquitectura

```
┌─────────────────────────────────────────────────────────┐
│                    REPOSITORIOS                         │
│              (Ya ingestados y enriquecidos)             │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              FASE 1: INGESTA BÁSICA                     │
│                                                          │
│  Fuente Única de Extracción:                            │
│  • Campo 'collaborators' de repos en MongoDB            │
│    (Ya contiene fusión de Contributors + Mentionable)   │
│                                                          │
│  Proceso:                                               │
│  1. Leer 'collaborators' de cada repo                  │
│  2. Deduplicar por ID único de GitHub                  │
│  3. Filtrar bots automáticamente                       │
│  4. Obtener info completa vía GraphQL                  │
│  5. Almacenar en MongoDB con metadata                  │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              MONGODB: Colección "users"                 │
│                  (Datos básicos)                        │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│           FASE 2: ENRIQUECIMIENTO                       │
│                                                          │
│  Estrategias:                                           │
│  1. Repositorios destacados (pinned)                    │
│  2. Organizaciones                                      │
│  3. Repositorios quantum relacionados                   │
│  4. Top lenguajes de programación                       │
│  5. Actividad reciente (30 días)                        │
│  6. Métricas sociales                                   │
│  7. Quantum Expertise Score                             │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              MONGODB: Colección "users"                 │
│                 (Datos completos)                       │
└─────────────────────────────────────────────────────────┘
```

---

## 📦 Componentes

### 1. Motor de Ingesta (`src/github/user_ingestion.py`)

**Clase principal**: `UserIngestionEngine`

**Funcionalidad**:
- Extrae usuarios desde múltiples fuentes
- Deduplicación automática por ID
- Filtrado de bots y cuentas inválidas
- Almacenamiento en MongoDB

**Métodos clave**:
```python
run(max_repos: Optional[int]) -> Dict[str, Any]
_extract_users_from_collaborators(max_repos) -> Dict[str, Dict]
_fetch_and_save_users(users_dict: Dict) -> None
_is_bot(user: Dict) -> bool
```

**Fuente de extracción**:
| Campo | Contenido | Origen |
|-------|-----------|--------|
| **collaborators** | Fusión de Contributors + Mentionable Users | REST + GraphQL |
| └─ `has_commits` | Usuario tiene commits en el repo | REST API |
| └─ `is_mentionable` | Usuario puede ser mencionado | GraphQL |
| └─ `contributions` | Número de commits del usuario | REST API |

### 2. Motor de Enriquecimiento (`src/github/user_enrichment.py`)

**Clase principal**: `UserEnrichmentEngine`

**Funcionalidad**:
- Completa información faltante
- Calcula métricas específicas de quantum
- Procesa en lotes (batch processing)
- Tracking de campos enriquecidos

**Estrategias de enriquecimiento**:

#### 🔹 1. Repositorios Destacados
```graphql
pinnedItems(first: 6, types: REPOSITORY)
```
Extrae hasta 6 repos destacados por el usuario en su perfil.

#### 🔹 2. Organizaciones
```graphql
organizations(first: 20)
```
Lista organizaciones de las que es miembro.

#### 🔹 3. Repositorios Quantum
Busca en tu DB local repos donde el usuario:
- Es owner
- Es colaborador
- Ha contribuido

**Calcula**:
- Número de repos quantum
- Rol en cada uno
- Cantidad de contribuciones

#### 🔹 4. Top Lenguajes
Agrega lenguajes más usados desde sus repos.

#### 🔹 5. Actividad Reciente (30 días)
```graphql
contributionsCollection(from: "fecha")
```
Métricas:
- `recent_commits_30d`
- `recent_issues_30d`
- `recent_prs_30d`
- `recent_reviews_30d`

#### 🔹 6. Métricas Sociales
Calcula:
- **Follower/Following Ratio**: Popularidad relativa
- **Stars per Repo**: Calidad promedio de repos

#### 🔹 7. Quantum Expertise Score

**Algoritmo de puntuación** (0-100 puntos):

```
SCORE = (repos_owner * 5) 
      + (repos_collaborator * 2) 
      + min(total_stars * 0.1, 50) 
      + min(total_contributions * 0.05, 25)
      + (quantum_orgs * 10)
```

| Factor | Peso | Máximo |
|--------|------|--------|
| Repos quantum como owner | 5 pts c/u | Ilimitado |
| Repos quantum como colaborador | 2 pts c/u | Ilimitado |
| Estrellas en repos quantum | 0.1 pts c/u | 50 pts |
| Contribuciones en repos quantum | 0.05 pts c/u | 25 pts |
| Organizaciones quantum | 10 pts c/u | Ilimitado |

**Detección de organizaciones quantum**: Keywords en nombre/descripción:
- "quantum"
- "qiskit"
- "cirq"
- "pennylane"

---

## 🚀 Uso

### Script 1: Ingesta Básica

```bash
python scripts/run_user_ingestion.py
```

**Proceso**:
1. Confirma configuración
2. Lee repos de MongoDB
3. Extrae usuarios de cada repo
4. Deduplica y filtra
5. Guarda en colección `users`

**Salida esperada**:
```
📊 Estadísticas:
  • Repositorios procesados: 1,631
  • Usuarios únicos encontrados: 8,732
  • Usuarios nuevos insertados: 8,732
  • Usuarios ya existentes: 0
  • Errores: 0

⏱️  Duración: 785.42s (13.1 minutos)

Nota: Mucho más rápido que versión anterior (4 fuentes)
porque solo lee MongoDB, no hace llamadas redundantes a API.
```

### Script 2: Enriquecimiento

```bash
python scripts/run_user_enrichment.py
```

**Parámetros interactivos**:
- **Límite de usuarios**: Opcional, para pruebas
- **Batch size**: Default 10 (usuarios por lote)

**Proceso**:
1. Lee usuarios de MongoDB
2. Enriquece en lotes (rate limit safe)
3. Actualiza campos faltantes
4. Marca usuarios como enriquecidos

**Salida esperada**:
```
📊 Estadísticas:
  • Usuarios procesados: 8,732
  • Usuarios enriquecidos: 8,691
  • Errores: 41

📈 Campos enriquecidos:
  • quantum_repositories: 3,421
  • quantum_expertise_score: 3,421
  • organizations: 5,234
  • pinned_repositories: 6,789
  • recent_commits_30d: 8,691
  • recent_prs_30d: 8,691
  • follower_following_ratio: 8,691

⏱️  Duración: 2,145.67s (35.8 minutos)
```

---

## 📊 Estructura de Datos

### Documento de Usuario (MongoDB)

```javascript
{
  // ═══════════════════════════════════════
  // FASE 1: INGESTA BÁSICA
  // ═══════════════════════════════════════
  
  // Identificación
  "id": "MDQ6VXNlcjEyMzQ1Njc=",
  "login": "quantum_dev",
  "node_id": "MDQ6VXNlcjEyMzQ1Njc=",
  
  // Perfil básico
  "name": "Jane Quantum Developer",
  "avatar_url": "https://avatars.githubusercontent.com/u/1234567?v=4",
  "html_url": "https://github.com/quantum_dev",
  "bio": "Quantum computing researcher | PhD Physics",
  "company": "@IBM",
  "location": "Boston, MA",
  "email": "jane@example.com",
  "blog": "https://quantumblog.dev",
  "twitter_username": "quantum_jane",
  
  // Contadores públicos
  "public_repos_count": 42,
  "public_gists_count": 15,
  "followers_count": 523,
  "following_count": 87,
  "starred_repos_count": 1245,
  
  // Metadata
  "type": "User",  // o "Organization"
  "site_admin": false,
  "hireable": true,
  "created_at": "2015-03-15T10:30:00Z",
  "updated_at": "2025-11-18T14:22:33Z",
  
  // Fuentes de extracción (metadata de colaboración)
  "extracted_from": [
    {
      "repo_id": "R_kgDOH...",
      "repo_name": "microsoft/qsharp",
      "has_commits": true,
      "is_mentionable": true,
      "contributions": 342
    },
    {
      "repo_id": "R_kgDOI...",
      "repo_name": "qiskit/qiskit",
      "has_commits": true,
      "is_mentionable": false,
      "contributions": 28
    }
  ],
  
  // ═══════════════════════════════════════
  // FASE 2: ENRIQUECIMIENTO
  // ═══════════════════════════════════════
  
  // Repositorios destacados
  "pinned_repositories": [
    {
      "id": "R_kgDOH...",
      "name": "quantum-ml",
      "name_with_owner": "quantum_dev/quantum-ml",
      "description": "Machine learning with quantum circuits",
      "stars": 1234,
      "language": "Python"
    }
    // ... hasta 6 repos
  ],
  
  // Organizaciones
  "organizations": [
    {
      "id": "MDEyOk9yZ2FuaXphdGlvbjE=",
      "login": "qiskit",
      "name": "Qiskit",
      "description": "Open-source quantum computing framework",
      "avatar_url": "https://avatars.githubusercontent.com/u/...",
      "website_url": "https://qiskit.org",
      "location": "Global"
    }
  ],
  "organizations_count": 3,
  
  // Repositorios Quantum
  "quantum_repositories": [
    {
      "id": "R_kgDOH...",
      "name": "qsharp",
      "name_with_owner": "microsoft/qsharp",
      "stars": 4521,
      "role": "collaborator",  // o "owner"
      "contributions": 342,
      "primary_language": "Q#"
    },
    {
      "id": "R_kgDOI...",
      "name": "quantum-algorithms",
      "name_with_owner": "quantum_dev/quantum-algorithms",
      "stars": 89,
      "role": "owner",
      "contributions": 0,
      "primary_language": "Python"
    }
  ],
  "quantum_repos_count": 7,
  "is_quantum_contributor": true,
  
  // Top lenguajes
  "top_languages": [
    {"name": "Python", "percentage": 45.2},
    {"name": "Q#", "percentage": 28.7},
    {"name": "Julia", "percentage": 15.3},
    {"name": "C++", "percentage": 10.8}
  ],
  
  // Actividad reciente (últimos 30 días)
  "recent_commits_30d": 87,
  "recent_issues_30d": 12,
  "recent_prs_30d": 15,
  "recent_reviews_30d": 23,
  
  // Métricas sociales
  "follower_following_ratio": 6.01,  // 523 / 87
  "stars_per_repo": 29.64,  // 1245 / 42
  
  // Quantum Expertise Score
  "quantum_expertise_score": 78.5,
  // Cálculo:
  // - 2 repos owner * 5 = 10
  // - 5 repos collaborator * 2 = 10
  // - 4521 stars * 0.1 = 50 (máx)
  // - 370 contributions * 0.05 = 18.5
  // Total normalizado: 78.5/100
  
  // Control de enriquecimiento
  "is_enriched": true,
  "enriched_at": "2025-11-19T15:45:00Z"
}
```

---

## 🎯 Casos de Uso

### 1. Identificar Expertos en Quantum Computing

```javascript
// Top 10 expertos por quantum_expertise_score
db.users.find({
  quantum_expertise_score: { $exists: true }
}).sort({
  quantum_expertise_score: -1
}).limit(10)
```

### 2. Colaboradores de Repos Específicos

```javascript
// Usuarios que contribuyeron a qiskit
db.users.find({
  "quantum_repositories.name_with_owner": /qiskit/i
})
```

### 3. Usuarios Activos (30 días)

```javascript
// Usuarios con más de 50 commits recientes
db.users.find({
  recent_commits_30d: { $gte: 50 }
}).sort({
  recent_commits_30d: -1
})
```

### 4. Investigadores por Organización

```javascript
// Miembros de IBM trabajando en quantum
db.users.find({
  "organizations.login": "IBM",
  is_quantum_contributor: true
})
```

### 5. Desarrolladores Multi-Lenguaje

```javascript
// Usuarios usando Q# y Python
db.users.find({
  "top_languages.name": { $all: ["Q#", "Python"] }
})
```

---

## 📈 Métricas y KPIs

### Cobertura
- **Total usuarios únicos**: ~8,000-15,000 (depende de repos)
- **Tasa de enriquecimiento**: >99%
- **Usuarios con expertise quantum**: ~40-50%

### Calidad
- **Filtrado de bots**: 100% automático
- **Deduplicación**: Por ID único de GitHub
- **Campos enriquecidos**: 7 estrategias

### Performance
- **Ingesta**: ~20-30 min (para 1,631 repos)
- **Enriquecimiento**: ~35-45 min (para 8,000 usuarios)
- **Rate limit**: Respetado automáticamente

---

## 🔧 Configuración

### Variables de Entorno

```bash
GITHUB_TOKEN=ghp_xxxxxxxxxxxx  # Token con scopes: read:user, read:org
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=quantum_repos
```

### Configuración Avanzada

Archivo: `config/ingestion_config.json`

```json
{
  "enrichment": {
    "batch_size": 10,
    "max_retries": 3,
    "base_backoff_seconds": 2,
    "rate_limit_threshold": 100
  }
}
```

---

## ⚠️ Limitaciones y Consideraciones

### 1. Rate Limit de GitHub
- **5,000 requests/hora** (GraphQL)
- Solo se consumen llamadas para usuarios nuevos (info completa)
- **Ventaja**: Campo 'collaborators' ya está en MongoDB
- **Solución**: Batch processing + pausas automáticas

### 2. Datos Privados
- Solo información **pública** de usuarios
- Emails pueden estar ocultos
- Algunos repos privados no visibles

### 3. Bots y Cuentas Automáticas
- Filtrado automático por tipo "Bot"
- Pueden colarse algunos (ej: dependabot)

### 4. Cambios en GitHub
- Usuarios pueden cambiar login
- Repos pueden ser eliminados
- Organizaciones pueden cambiar privacidad

### 5. Quantum Expertise Score
- **Heurística**, no verdad absoluta
- Favorece cantidad sobre calidad
- No considera papers académicos

---

## 🔄 Mantenimiento

### Actualización Periódica

```bash
# Cada 1-2 semanas
python scripts/run_user_ingestion.py      # Nuevos usuarios
python scripts/run_user_enrichment.py     # Actualizar datos
```

### Limpieza de Datos

```javascript
// Eliminar usuarios sin repos quantum
db.users.deleteMany({
  quantum_repos_count: 0,
  is_quantum_contributor: false
})

// Eliminar usuarios inactivos (sin commits en 2+ años)
db.users.deleteMany({
  recent_commits_30d: 0,
  updated_at: { $lt: new Date("2023-01-01") }
})
```

---

## 📚 Referencias

### APIs Utilizadas
- [GitHub GraphQL API v4](https://docs.github.com/en/graphql)
- [GitHub REST API v3](https://docs.github.com/en/rest)

### Campos GraphQL
- [User object](https://docs.github.com/en/graphql/reference/objects#user)
- [Organization object](https://docs.github.com/en/graphql/reference/objects#organization)
- [ContributionsCollection](https://docs.github.com/en/graphql/reference/objects#contributionscollection)

### Similares
- `docs/ingestion_engine_guide.md` - Ingesta de repositorios
- `docs/MEJORAS_ENRIQUECIMIENTO.md` - Enriquecimiento de repositorios

---

## ✅ Checklist de Implementación

- [x] Motor de ingesta básica
- [x] Extracción desde 4 fuentes
- [x] Deduplicación por ID
- [x] Filtrado de bots
- [x] Motor de enriquecimiento
- [x] 7 estrategias de enriquecimiento
- [x] Quantum expertise score
- [x] Scripts de ejecución
- [x] Documentación completa
- [ ] Tests unitarios
- [ ] Tests de integración
- [ ] Validación de datos
- [ ] Dashboard de visualización

---

## 🎓 Próximos Pasos

1. **Ejecutar ingesta**: Obtener dataset inicial
2. **Analizar distribución**: Verificar calidad de datos
3. **Ajustar scores**: Refinar quantum expertise si es necesario
4. **Análisis de redes**: Grafo de colaboraciones
5. **Organizaciones**: Sistema similar para orgs
6. **Visualizaciones**: Dashboard con métricas

---

**Autor**: Sistema de Ingesta Quantum Computing  
**Fecha**: Noviembre 2025  
**Versión**: 1.0
