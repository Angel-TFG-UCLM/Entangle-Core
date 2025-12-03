# 📊 Campos de Enriquecimiento de Usuarios

## Resumen Ejecutivo

El sistema de enriquecimiento de usuarios ahora obtiene **MÁXIMA INFORMACIÓN POSIBLE** de cada usuario, recopilando **17 categorías diferentes de datos** desde múltiples fuentes (GraphQL, REST API, MongoDB local).

**Total de campos enriquecidos:** ~80+ campos únicos por usuario

---

## 🎯 Categorías de Enriquecimiento

### **0. Campos Básicos Faltantes** ✅
Completa campos que pudieron faltar en la ingesta simplificada:
```python
{
  "public_gists_count": 42,
  "starred_repos_count": 1250,
  "watching_count": 85,
  "total_commit_contributions": 5420,
  "total_issue_contributions": 320,
  "total_pr_contributions": 180,
  "total_pr_review_contributions": 95
}
```

---

### **1. Repositorios Destacados (Pinned)** 📌
```python
{
  "pinned_repositories": [
    {
      "id": "R_kgDOGH4...",
      "name": "quantum-ml",
      "name_with_owner": "user/quantum-ml",
      "description": "Quantum ML algorithms",
      "stars": 1250,
      "language": "Python"
    },
    # ... hasta 6 repos
  ]
}
```

---

### **2. Organizaciones** 🏢
```python
{
  "organizations": [
    {
      "id": "O_kgDOABC...",
      "login": "qiskit",
      "name": "Qiskit Community",
      "description": "Open-source quantum computing",
      "avatarUrl": "https://...",
      "websiteUrl": "https://qiskit.org",
      "location": "Global"
    },
    # ... hasta 20 orgs
  ],
  "organizations_count": 3
}
```

---

### **3. Repositorios Quantum Relacionados** ⭐ **CLAVE TFG**
```python
{
  "quantum_repositories": [
    {
      "repo_id": "R_kgDOG...",
      "repo_name": "qiskit/qiskit-terra",
      "role": "owner" | "collaborator",
      "contributions": 42,
      "has_commits": true,
      "is_mentionable": true
    }
  ],
  "quantum_repos_count": 5,
  "is_quantum_contributor": true
}
```
**Fuente:** Base de datos local (colección `repositories`)

---

### **4. Top Lenguajes** 💻
```python
{
  "top_languages": [
    {"name": "Python", "percentage": 65.2},
    {"name": "Julia", "percentage": 15.8},
    {"name": "C++", "percentage": 12.3}
  ]
}
```

---

### **5. Actividad Reciente (30 días)** 📈
```python
{
  "recent_commits_30d": 87,
  "recent_issues_30d": 12,
  "recent_prs_30d": 8,
  "recent_reviews_30d": 15
}
```

---

### **6. Métricas Sociales Calculadas** 📊
```python
{
  "follower_following_ratio": 8.5,  # followers / following
  "stars_per_repo": 125.3           # starred_repos / public_repos
}
```

---

### **7. Quantum Expertise Score** 🎓 **MÉTRICA ÚNICA TFG**
```python
{
  "quantum_expertise_score": 67.5  # 0-100
}
```

**Cálculo:**
```
Score = 
  + (repos quantum como owner × 5)
  + (repos quantum como colaborador × 2)
  + (estrellas en repos quantum × 0.1, máx 50)
  + (contribuciones totales × 0.05, máx 25)
  + (organizaciones quantum × 10)
```

---

### **8. Perfil Social Enriquecido** 👤 **NUEVO**
```python
{
  "pronouns": "they/them",
  "twitter_username": "quantum_dev",
  "status_message": "Working on quantum algorithms",
  "status_emoji": "🚀",
  "is_hireable": true,
  "is_campus_expert": true,
  "is_developer_program_member": true,
  "is_site_admin": false,
  "social_profile_enriched": true
}
```

**Campos clave:**
- `is_campus_expert`: Identifica educadores/investigadores
- `is_developer_program_member`: Miembro de programas oficiales
- `pronouns`: Inclusividad y diversidad

---

### **9. Sponsors (Patrocinadores)** 💰 **NUEVO**
```python
{
  "sponsors_count": 15,
  "sponsors": [
    {
      "login": "ibm_quantum",
      "name": "IBM Quantum",
      "avatar_url": "https://..."
    },
    # ... hasta 10 sponsors principales
  ]
}
```

**Interpretación:** Indica reconocimiento y apoyo de la comunidad

---

### **10. Gists Quantum** 📝 **NUEVO**
```python
{
  "quantum_gists": [
    {
      "name": "vqe_algorithm.py",
      "description": "VQE implementation with Qiskit",
      "url": "https://gist.github.com/...",
      "stars": 42,
      "updated_at": "2025-11-20T10:30:00Z",
      "files_count": 3
    }
  ],
  "quantum_gists_count": 8
}
```

**Detección:** Keywords: quantum, qiskit, cirq, pennylane, qubit, qasm, vqe, qaoa, grover, shor, bloch

**Uso en TFG:** Identificar recursos educativos, ejemplos de código, tutoriales

---

### **11. Lenguajes Detallados (con Bytes)** 💾 **NUEVO**
```python
{
  "languages_detailed": [
    {
      "name": "Python",
      "color": "#3572A5",
      "bytes": 2_450_320,
      "repos_count": 45
    },
    {
      "name": "Julia",
      "color": "#a270ba",
      "bytes": 580_120,
      "repos_count": 8
    },
    # ... top 15 lenguajes
  ]
}
```

**Análisis:** Agrega datos de los primeros 100 repos del usuario

**Ventaja vs `top_languages`:** Incluye tamaño real de código, no solo porcentajes

---

### **12. Top Repositorios por Contribución** 🏆 **NUEVO**
```python
{
  "top_contributed_repos": [
    {
      "id": "R_kgDOGH...",
      "name_with_owner": "qiskit/qiskit-terra",
      "description": "Terra provides the foundations...",
      "stars": 4250,
      "language": "Python",
      "commits_count": 187
    },
    # ... hasta 20 repos
  ]
}
```

**Análisis:** Ordena repos por número de commits del usuario

**Uso en TFG:** Identificar proyectos donde el usuario es más activo

---

### **13. Issues y PRs Notables** 🎯 **NUEVO**
```python
{
  "notable_issues_prs": {
    "notable_issues": [
      {
        "title": "Improve VQE convergence",
        "state": "OPEN",
        "url": "https://github.com/qiskit/qiskit-terra/issues/...",
        "created_at": "2025-10-15T14:20:00Z",
        "comments_count": 42,
        "repository": "qiskit/qiskit-terra"
      }
    ],
    "notable_prs": [
      {
        "title": "Add QAOA optimizer",
        "state": "MERGED",
        "merged": true,
        "url": "https://github.com/...",
        "created_at": "2025-09-20T10:00:00Z",
        "comments_count": 15,
        "repository": "qiskit/qiskit-algorithms"
      }
    ],
    "total_notable_issues": 5,
    "total_notable_prs": 5
  }
}
```

**Análisis:** 
- Issues ordenados por número de comentarios (más discutidos)
- PRs recientes (últimos 10)
- Filtrados por estado: OPEN, CLOSED, MERGED

**Uso en TFG:** Evaluar calidad de contribuciones y engagement

---

### **14. Paquetes Publicados** 📦 **NUEVO**
```python
{
  "packages": [
    {
      "name": "quantum-optimizer",
      "type": "NPM",
      "repository": "user/quantum-optimizer"
    },
    {
      "name": "qml-toolkit",
      "type": "DOCKER",
      "repository": "user/qml-toolkit"
    }
  ],
  "packages_count": 2
}
```

**Tipos soportados:** NPM, Docker, Maven, NuGet, RubyGems, PyPI

**Uso en TFG:** Identificar desarrolladores que publican herramientas

---

### **15. Proyectos Personales** 🗂️ **NUEVO**
```python
{
  "projects": [
    {
      "title": "Quantum Research 2025",
      "description": "Research on quantum algorithms",
      "is_public": true,
      "url": "https://github.com/users/alice/projects/1"
    }
  ],
  "projects_count": 3
}
```

**Nota:** GitHub Projects V2 (nuevo formato de proyectos)

**Uso en TFG:** Ver organización y planificación del usuario

---

### **16. Red Social (Muestra)** 👥 **NUEVO**
```python
{
  "social_network_sample": {
    "followers_sample": [
      {"login": "bob", "name": "Bob Smith"},
      {"login": "charlie", "name": "Charlie Johnson"},
      # ... hasta 50 followers
    ],
    "following_sample": [
      {"login": "qiskit", "name": "Qiskit"},
      # ... hasta 50 following
    ],
    "sample_size": 50
  }
}
```

**Nota:** Solo primeros 50 de cada tipo para evitar sobrecarga

**Uso en TFG:** 
- Análisis de red social (quién sigue a quién)
- Identificar clusters de investigadores
- Detectar comunidades

---

### **17. Referencias a Repositorios (Colección Local)** 🔗 **NUEVO**
```python
{
  "repository_references": {
    "owned_repos_count": 12,
    "owned_repos_ids": ["R_kgDOGH...", "R_kgDOAB...", ...],
    "collaborated_repos_count": 45,
    "collaborated_repos_ids": ["R_kgDOXY...", ...],
    "note": "Ver colección 'repositories' para detalles completos"
  }
}
```

**Propósito:** 
- ✅ **Evita duplicar** información que ya existe en la colección `repositories`
- ✅ **Proporciona IDs** para hacer JOINs/lookups entre colecciones
- ✅ **Mantiene integridad** referencial

**Uso:**
```python
# Para obtener detalles completos de un repo del usuario:
user_repo_ids = user["repository_references"]["owned_repos_ids"]
repos = db.repositories.find({"id": {"$in": user_repo_ids}})
```

---

## 📊 Estadísticas de Enriquecimiento

### **Campos Totales por Usuario:**
```
Campos básicos:              ~30 campos
Enriquecimiento estándar:    ~20 campos
Enriquecimiento nuevo:       ~30 campos
─────────────────────────────────────
TOTAL:                       ~80 campos
```

### **Queries GraphQL por Usuario:**
```
1. Campos básicos faltantes
2. Perfil social
3. Repositorios destacados
4. Organizaciones
5. Sponsors
6. Gists
7. Lenguajes detallados
8. Contribuciones por repo
9. Issues/PRs notables
10. Paquetes
11. Proyectos
12. Red social (muestra)
─────────────────────────────
TOTAL: ~12 queries GraphQL
```

### **Queries MongoDB por Usuario:**
```
1. Repositorios quantum (owned)
2. Repositorios quantum (collaborated)
─────────────────────────────
TOTAL: 2 queries MongoDB
```

---

## 🚀 Ejecución

### **Desde Script:**
```bash
python scripts/run_user_enrichment.py
```

### **Desde API:**
```bash
POST /api/v1/enrichment/users
{
  "max_users": 100,
  "batch_size": 10,
  "force_reenrich": false
}
```

### **Parámetros:**
- `max_users`: Límite de usuarios a enriquecer (None = todos)
- `batch_size`: Usuarios por lote (default: 10, reduce para evitar rate limit)
- `force_reenrich`: Re-enriquecer usuarios ya enriquecidos (default: false)

---

## ⚡ Rendimiento

### **Tiempos Estimados:**
```
Por usuario:  ~5-10 segundos
Por lote (10): ~60-90 segundos (incluye pausas anti-rate-limit)
100 usuarios: ~10-15 minutos
1000 usuarios: ~1.5-2.5 horas
```

### **Rate Limit GitHub:**
```
GraphQL: 5,000 puntos/hora
Consumo por usuario: ~40-50 puntos
Usuarios posibles/hora: ~100-125 usuarios
```

### **Optimizaciones Implementadas:**
- ✅ Procesamiento por lotes
- ✅ Pausas entre lotes (2 segundos)
- ✅ Manejo automático de rate limit con espera
- ✅ Reintentos en errores temporales
- ✅ Logs de progreso cada minuto

---

## 🎯 Uso en el TFG

### **Análisis Posibles:**

1. **Perfiles de Expertos Quantum**
   - Score > 70: Expertos reconocidos
   - Score 40-70: Contribuidores activos
   - Score < 40: Colaboradores ocasionales

2. **Comunidades y Redes**
   - Análisis de followers/following
   - Identificar clusters por organizaciones
   - Detectar influencers (sponsor_count alto)

3. **Diversidad de la Comunidad**
   - Análisis de `pronouns`
   - Distribución geográfica (`location`)
   - Participación académica (`is_campus_expert`)

4. **Calidad de Contribuciones**
   - Issues con más comentarios = más impacto
   - PRs merged = contribuciones aceptadas
   - Gists quantum = recursos educativos

5. **Tecnologías Utilizadas**
   - `languages_detailed`: Análisis de stack tecnológico
   - `packages`: Herramientas publicadas
   - Comparar con repos quantum para ver patrones

6. **Recursos Educativos**
   - `quantum_gists`: Tutoriales, ejemplos
   - `pinned_repositories`: Proyectos destacados
   - `projects`: Organización de investigación

---

## ✅ Checklist de Implementación

- [x] Campos sociales (pronouns, twitter, status, flags)
- [x] Sponsors (patrocinadores)
- [x] Gists quantum
- [x] Lenguajes detallados (bytes)
- [x] Top repos por contribución
- [x] Issues/PRs notables
- [x] Paquetes publicados
- [x] Proyectos personales
- [x] Red social (muestra)
- [x] Referencias a colección repositories
- [x] Modelo User actualizado
- [x] Documentación completa
- [x] Manejo de rate limit mejorado
- [x] Tests de enriquecimiento

---

## 📝 Notas Finales

**Máxima información recopilada:**
- ✅ Todos los campos disponibles en GraphQL API
- ✅ Referencias inteligentes a colección `repositories` (sin duplicar)
- ✅ Análisis de gists, issues, PRs, paquetes, proyectos
- ✅ Métricas sociales y de expertise calculadas
- ✅ Muestra de red social para análisis

**Optimizado para:**
- ✅ Análisis de comunidad quantum computing
- ✅ Identificación de expertos
- ✅ Mapeo de tecnologías
- ✅ Análisis de recursos educativos
- ✅ Estudios de redes sociales

**Total:** Sistema de enriquecimiento más completo posible con las APIs disponibles 🎓🚀
