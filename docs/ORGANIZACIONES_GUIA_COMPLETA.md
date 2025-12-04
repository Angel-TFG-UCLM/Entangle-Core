# 🏢 Guía Completa: Ingesta y Enriquecimiento de Organizaciones

## 📋 Índice

1. [Visión General](#visión-general)
2. [Arquitectura del Sistema](#arquitectura-del-sistema)
3. [Modelo de Datos](#modelo-de-datos)
4. [Ingesta de Organizaciones](#ingesta-de-organizaciones)
5. [Enriquecimiento de Organizaciones](#enriquecimiento-de-organizaciones)
6. [Scripts de Ejecución](#scripts-de-ejecución)
7. [Casos de Uso](#casos-de-uso)
8. [Troubleshooting](#troubleshooting)

---

## 🎯 Visión General

El sistema de **Ingesta y Enriquecimiento de Organizaciones** permite identificar, analizar y clasificar organizaciones del ecosistema quantum computing en GitHub.

### **Objetivos:**

1. ✅ **Descubrir organizaciones** desde usuarios quantum (estrategia Bottom-Up)
2. ✅ **Determinar relevancia** basándose en repositorios quantum ingestados
3. ✅ **Calcular métricas quantum** (focus score, top contributors, stack tecnológico)
4. ✅ **Medir prestigio** (estrellas acumuladas)
5. ✅ **Trazabilidad completa** (qué repos llevaron a descubrir cada org)

---

## 🏗️ Arquitectura del Sistema

### **Pipeline Completo:**

```
┌─────────────────────────────────────────────────────────────────┐
│                    FASE 1: INGESTA DE REPOS                     │
│              (Filtros estrictos de Quantum Computing)            │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FASE 2: INGESTA DE USERS                     │
│          (Colaboradores de repos quantum ingestados)             │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│               FASE 3: INGESTA DE ORGANIZACIONES                 │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  1. Descubrimiento (Bottom-Up)                         │    │
│  │     └─ Campo "organizations" de cada user              │    │
│  │                                                         │    │
│  │  2. Deduplicación                                      │    │
│  │     └─ Por login único de organización                 │    │
│  │                                                         │    │
│  │  3. Fetch desde GitHub API                             │    │
│  │     └─ Datos básicos (GraphQL)                         │    │
│  │                                                         │    │
│  │  4. Cálculo de Relevancia                              │    │
│  │     └─ ¿Tiene repos quantum en nuestra BD?             │    │
│  │     └─ discovered_from_repos: [{id, name}]             │    │
│  │                                                         │    │
│  │  5. Guardado en MongoDB                                │    │
│  │     └─ Colección "organizations"                       │    │
│  └────────────────────────────────────────────────────────┘    │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│            FASE 4: ENRIQUECIMIENTO DE ORGANIZACIONES            │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  1. Super-Query GraphQL                                │    │
│  │     └─ 1 query por org (totales de repos y miembros)   │    │
│  │                                                         │    │
│  │  2. Identificación de Repos Quantum                    │    │
│  │     └─ Busca en BD local (owner.login = org)           │    │
│  │                                                         │    │
│  │  3. Análisis Tecnológico                               │    │
│  │     └─ top_languages: Stack tecnológico                │    │
│  │     └─ total_stars: Prestigio acumulado                │    │
│  │                                                         │    │
│  │  4. Top Contributors                                   │    │
│  │     └─ Usuarios con más contributions a repos quantum  │    │
│  │                                                         │    │
│  │  5. Quantum Focus Score                                │    │
│  │     └─ (quantum_repos / total_repos) × 100             │    │
│  │     └─ + Bonus keywords quantum (+10)                  │    │
│  │     └─ × Multiplicador verificación (×1.2)             │    │
│  │                                                         │    │
│  │  6. Actualización en MongoDB                           │    │
│  │     └─ Merge de métricas calculadas                    │    │
│  └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📊 Modelo de Datos

### **Archivo:** `src/models/organization.py`

```python
class Organization(BaseModel):
    """
    Modelo de Organización de GitHub v2.0
    
    FASE 1 (INGESTA): Campos básicos desde GitHub API
    FASE 2 (ENRIQUECIMIENTO): Métricas quantum calculadas
    """
    
    # ==================== IDENTIFICACIÓN ====================
    id: str                                    # GitHub ID (inmutable)
    login: str                                 # Username de la org
    name: Optional[str]                        # Nombre completo
    description: Optional[str]                 # Descripción
    
    # ==================== CONTACTO ====================
    email: Optional[str]
    url: str                                   # URL de GitHub
    avatar_url: str
    website_url: Optional[str]
    
    # ==================== PRESENCIA SOCIAL ====================
    twitter_username: Optional[str]
    location: Optional[str]
    
    # ==================== VERIFICACIÓN ====================
    is_verified: bool                          # Verificada por GitHub
    
    # ==================== FECHAS ====================
    created_at: Optional[str]                  # Fecha de creación
    updated_at: Optional[str]                  # Última actualización
    ingested_at: Optional[datetime]            # Timestamp de ingesta
    enriched_at: Optional[datetime]            # Timestamp de enriquecimiento
    
    # ==================== RELEVANCIA Y TRAZABILIDAD ====================
    is_relevant: bool = False                  # ¿Tiene repos quantum?
    
    discovered_from_repos: List[Dict[str, str]] = []
    # [{id: "R_123", name: "qiskit/qiskit-terra"}, ...]
    # Repos que llevaron a descubrir esta org
    
    # ==================== MÉTRICAS BÁSICAS (Ingesta) ====================
    public_repos_count: Optional[int]          # Total de repos públicos
    members_count: Optional[int]               # Total de miembros
    sponsorable: Optional[bool]                # ¿Acepta sponsors?
    is_active: Optional[bool]                  # Actividad últimos 6 meses
    
    # ==================== MÉTRICAS QUANTUM (Enriquecimiento) ====================
    quantum_focus_score: Optional[float]       # 0-100 (% de enfoque quantum)
    quantum_repositories_count: Optional[int]  # Cantidad de repos quantum
    total_repositories_count: Optional[int]    # Total de repos públicos
    quantum_contributors_count: Optional[int]  # Contributors a repos quantum
    total_members_count: Optional[int]         # Total de miembros públicos
    is_quantum_focused: Optional[bool]         # score >= 30%
    
    # ==================== LISTAS DE REFERENCIA ====================
    quantum_repositories: List[str] = []       # IDs de repos quantum
    
    top_quantum_contributors: List[Dict[str, str]] = []
    # [{id: "U_456", login: "john_doe"}, ...]
    # Top 10 contributors por contributions
    
    # ==================== ANÁLISIS TECNOLÓGICO ====================
    top_languages: List[Dict[str, Any]] = []
    # [
    #   {name: "Python", percentage: 65.5, repo_count: 12},
    #   {name: "C++", percentage: 20.0, repo_count: 4},
    #   {name: "Julia", percentage: 14.5, repo_count: 3}
    # ]
    
    total_stars: Optional[int]                 # Suma de estrellas de repos quantum
    
    # ==================== STATUS DE ENRIQUECIMIENTO ====================
    enrichment_status: Optional[EnrichmentStatus]
```

---

## 🔽 Ingesta de Organizaciones

### **Archivo:** `src/github/organization_ingestion.py`

### **Características:**

- ✅ **Estrategia Bottom-Up:** Descubre orgs desde usuarios
- ✅ **Deduplicación automática:** Por login único
- ✅ **Cálculo de relevancia:** Basado en repos en BD
- ✅ **Trazabilidad completa:** discovered_from_repos
- ✅ **Rate Limit:** 0.5s entre organizaciones
- ✅ **Batch processing:** Lotes configurables

### **Flujo de Ingesta:**

#### **1. Descubrimiento de Organizaciones**

```python
def _discover_organizations(self) -> List[Dict]:
    """
    Descubre organizaciones desde el campo 'organizations' de usuarios.
    
    Pipeline MongoDB:
    1. Desenrollar array de organizations de cada user
    2. Agrupar por login único de organización
    3. Contar cuántos usuarios pertenecen a cada org
    4. Ordenar por cantidad de miembros
    """
    pipeline = [
        {"$unwind": "$organizations"},
        {"$group": {
            "_id": "$organizations.login",
            "count": {"$sum": 1},
            "users": {"$addToSet": "$login"}
        }},
        {"$sort": {"count": -1}}
    ]
```

**Output Ejemplo:**
```javascript
[
  {_id: "qiskit-community", count: 45, users: ["user1", "user2", ...]},
  {_id: "microsoft", count: 2699, users: ["user3", ...]},
  {_id: "qiskit-advocate", count: 2, users: ["user4", "user5"]}
]
```

---

#### **2. Cálculo de Relevancia**

```python
def _calculate_organization_relevance(self, org_login: str) -> Dict[str, Any]:
    """
    Determina si una organización es relevante.
    
    RELEVANTE = Tiene al menos 1 repo quantum ingestado en nuestra BD
    
    Lógica:
    1. Busca repos en MongoDB donde owner.login = org_login
    2. Si encuentra repos → is_relevant = True
    3. Guarda lista de repos: [{id, name}]
    """
    repos_collection = self.users_repository.collection.database["repositories"]
    
    org_repos = list(repos_collection.find({
        "owner.login": org_login
    }))
    
    is_relevant = len(org_repos) > 0
    
    discovered_repos = [
        {"id": repo["id"], "name": f"{repo['owner']['login']}/{repo['name']}"}
        for repo in org_repos
    ]
    
    return {
        "is_relevant": is_relevant,
        "discovered_from_repos": discovered_repos
    }
```

**¿Por qué es importante?**
- ❌ **Org NO relevante:** Descubierta porque usuarios pertenecen a ella, pero no tiene repos quantum
- ✅ **Org relevante:** Tiene repos quantum ingestados → Es parte del ecosistema quantum

---

#### **3. Fetch y Guardado**

```python
def _fetch_and_save_organization(self, login: str, force_update: bool) -> bool:
    """
    Obtiene datos de GitHub y guarda en MongoDB.
    
    Pasos:
    1. Query GraphQL para datos básicos
    2. Calcula relevancia (repos en BD)
    3. Crea modelo Organization
    4. Upsert en MongoDB
    """
    # GraphQL query
    org_data = self._fetch_organization_basic(login)
    
    # Calcular relevancia
    relevance_data = self._calculate_organization_relevance(login)
    
    # Crear modelo
    org = Organization.from_graphql_response(org_data)
    
    # Merge relevance data
    org_dict = org.model_dump()
    org_dict.update(relevance_data)
    
    # Guardar
    self.orgs_repository.upsert_one(
        query={"login": login},
        document=org_dict
    )
```

---

### **Estadísticas de Ingesta:**

```
📊 Análisis de Relevancia:
   ✅ Organizaciones relevantes (con repos quantum): 150
   ⚠️  Organizaciones no relevantes (sin repos quantum): 5217
   📈 % Relevancia: 2.8%
```

**Interpretación:**
- Solo el 2.8% de orgs descubiertas tienen repos quantum reales
- El resto son orgs donde trabajan usuarios quantum, pero en otros proyectos

---

## ⚡ Enriquecimiento de Organizaciones

### **Archivo:** `src/github/organization_enrichment.py`

### **Características:**

- ✅ **Super-Query GraphQL:** 1 query por organización
- ✅ **Análisis local:** Usa repos ya ingestados
- ✅ **Stack tecnológico:** Top lenguajes de programación
- ✅ **Prestigio:** Suma de estrellas de repos quantum
- ✅ **Contributors:** Top 10 por contributions
- ✅ **Quantum Score:** Fórmula ponderada 0-100

---

### **1. Super-Query GraphQL**

```graphql
query GetOrganizationEnrichment($login: String!) {
  organization(login: $login) {
    id
    login
    
    repositories(first: 100, orderBy: {field: STARGAZERS, direction: DESC}) {
      totalCount
      nodes {
        id
        name
        stargazerCount
      }
    }
    
    membersWithRole(first: 100) {
      totalCount
    }
  }
}
```

**Optimización:**
- ✅ 1 sola llamada a API por organización
- ✅ Solo pide totales (no todos los datos)
- ✅ Reduce rate limit consumption

---

### **2. Identificación de Repos Quantum**

```python
def _find_quantum_repositories(self, org_login: str, org: Dict) -> Optional[Dict]:
    """
    Encuentra repos quantum de la org en nuestra BD.
    
    IMPORTANTE: No consulta GitHub API, solo MongoDB local
    
    Si un repo está en la colección 'repositories', 
    ya es quantum-related (pasó filtros estrictos).
    """
    quantum_repos = list(self.repos_repository.collection.find({
        "owner.login": org_login
    }))
    
    if not quantum_repos:
        return None
    
    repo_ids = [repo["id"] for repo in quantum_repos]
    
    return {
        "repo_ids": repo_ids,
        "repos": quantum_repos
    }
```

---

### **3. Stack Tecnológico (Top Languages)**

```python
def _calculate_top_languages(self, repo_ids: List[str], limit: int = 10) -> List[Dict]:
    """
    Calcula el stack tecnológico basado en repos quantum.
    
    Pasos:
    1. Busca repos en BD por IDs
    2. Extrae primary_language de cada uno
    3. Cuenta frecuencias
    4. Calcula porcentajes
    5. Retorna top N
    """
    repos = list(self.repos_repository.collection.find(
        {"id": {"$in": repo_ids}},
        {"primary_language": 1}
    ))
    
    language_counter = Counter()
    for repo in repos:
        lang_name = repo.get("primary_language", {}).get("name")
        if lang_name:
            language_counter[lang_name] += 1
    
    total_repos = len(repos)
    top_languages = []
    
    for lang_name, count in language_counter.most_common(limit):
        percentage = (count / total_repos) * 100
        top_languages.append({
            "name": lang_name,
            "percentage": round(percentage, 2),
            "repo_count": count
        })
    
    return top_languages
```

**Output Ejemplo:**
```json
[
  {"name": "Python", "percentage": 65.5, "repo_count": 12},
  {"name": "C++", "percentage": 20.0, "repo_count": 4},
  {"name": "Julia", "percentage": 14.5, "repo_count": 3}
]
```

---

### **4. Prestigio Acumulado (Total Stars)**

```python
def _calculate_total_stars(self, repo_ids: List[str]) -> int:
    """
    Suma las estrellas de todos los repos quantum.
    
    Mide el prestigio/popularidad de la organización
    en el ecosistema quantum.
    """
    repos = list(self.repos_repository.collection.find(
        {"id": {"$in": repo_ids}},
        {"stargazer_count": 1}
    ))
    
    total = sum(repo.get("stargazer_count", 0) for repo in repos)
    return total
```

**Uso:**
- 📊 **Ranking de orgs** por popularidad (no solo cantidad)
- 🎯 **Calidad vs Cantidad:** 
  - `public_repos_count` = Cuánto trabajan
  - `total_stars` = Cuánto les quiere la comunidad

---

### **5. Top Quantum Contributors**

```python
def _find_top_quantum_contributors(self, repo_ids: List[str], limit: int = 10) -> List[Dict]:
    """
    Encuentra los top contributors a repos quantum de la org.
    
    Pipeline de Agregación MongoDB:
    1. Filtra usuarios con contributions
    2. Desenrolla extracted_from
    3. Filtra solo repos quantum de esta org
    4. Suma contributions por usuario
    5. Ordena por total (descendente)
    6. Retorna top N
    """
    pipeline = [
        {"$match": {"extracted_from": {"$exists": True, "$ne": []}}},
        {"$unwind": "$extracted_from"},
        {"$match": {"extracted_from.repo_id": {"$in": repo_ids}}},
        {"$group": {
            "_id": "$id",
            "login": {"$first": "$login"},
            "total_contributions": {"$sum": "$extracted_from.contributions"}
        }},
        {"$sort": {"total_contributions": -1}},
        {"$limit": limit}
    ]
    
    results = list(self.users_repository.collection.aggregate(pipeline))
    
    return [
        {"id": r["_id"], "login": r["login"]}
        for r in results
    ]
```

**Output Ejemplo:**
```json
[
  {"id": "MDQ6VXNlcjEyMzQ1Njc=", "login": "john_doe"},
  {"id": "MDQ6VXNlcjc4OTAxMjM=", "login": "jane_smith"},
  {"id": "MDQ6VXNlcjQ1Njc4OTA=", "login": "quantum_dev"}
]
```

---

### **6. Quantum Focus Score**

```python
def _calculate_quantum_focus_score(
    self,
    quantum_count: int,
    total_count: int,
    is_verified: bool,
    org_name: str,
    org_description: str
) -> float:
    """
    Calcula el quantum focus score (0-100).
    
    Fórmula:
    1. Base = (quantum_repos / total_repos) × 100
    2. Bonus = +10 si tiene keywords quantum en nombre/descripción
    3. Multiplicador = ×1.2 si está verificada
    4. Cap = máximo 100.0
    """
    if total_count == 0:
        return 0.0
    
    # Score base
    score = (quantum_count / total_count) * 100
    
    # Bonus por keywords
    quantum_keywords = [
        "quantum", "qiskit", "cirq", "qubit", "entanglement",
        "qasm", "pennylane", "tket", "braket", "qdk", "ionq"
    ]
    text = f"{org_name or ''} {org_description or ''}".lower()
    if any(keyword in text for keyword in quantum_keywords):
        score += 10
    
    # Multiplicador por verificación
    if is_verified:
        score *= 1.2
    
    # Cap a 100
    return min(score, 100.0)
```

**Ejemplos:**

| Org | Quantum Repos | Total Repos | Keywords | Verified | Score |
|-----|--------------|-------------|----------|----------|-------|
| qiskit-community | 8 | 12 | ✅ | ✅ | 92.0% |
| microsoft | 2 | 5000 | ❌ | ✅ | 0.05% |
| qiskit-advocate | 0 | 16 | ✅ | ❌ | 10.0% |

**Threshold:**
- `is_quantum_focused = score >= 30%`

---

## 🚀 Scripts de Ejecución

### **1. Ingesta de Organizaciones**

**Archivo:** `scripts/run_organization_ingestion.py`

```bash
python scripts/run_organization_ingestion.py
```

**Parámetros Configurables:**
```python
batch_size = 5          # Organizaciones por lote
sleep_time = 0.5        # Segundos entre organizaciones
force_update = False    # Re-ingestar organizaciones existentes
```

**Output Ejemplo:**
```
================================================================================
🏢 INICIANDO INGESTA DE ORGANIZACIONES
================================================================================

📋 Configuración:
   • Estrategia: Bottom-Up (desde usuarios)
   • Fuente: Campo 'organizations' de usuarios
   • Deduplicación: por login de organización
   • Rate Limit: batch_size=5, sleep=0.5s

🔍 Descubriendo organizaciones desde usuarios...
✅ Encontradas 5367 organizaciones únicas

📊 Top 10 organizaciones por número de miembros:
   1. microsoft (2699 miembros)
   2. Azure (1436 miembros)
   3. qiskit-community (45 miembros)
   ...

📦 Procesando 5367 organizaciones en lotes de 5...

📦 Lote 1/1074 (5 organizaciones)
   🏢 Procesando: microsoft
      ✅ Organización guardada
      ⚠️  No relevante (sin repos quantum en BD)
   
   🏢 Procesando: qiskit-community
      ✅ Organización guardada
      ✅ Relevante - 8 repos quantum encontrados

================================================================================
📊 RESUMEN DE INGESTA
================================================================================
✅ Total procesadas: 5367
✅ Total guardadas: 5367
⚠️  Total ya existentes: 0

📊 Análisis de Relevancia:
   ✅ Organizaciones relevantes: 150 (2.8%)
   ⚠️  Organizaciones no relevantes: 5217 (97.2%)

⏱️  Duración: 2847.5 segundos (47.5 minutos)
```

---

### **2. Enriquecimiento de Organizaciones**

**Archivo:** `scripts/run_organization_enrichment.py`

```bash
python scripts/run_organization_enrichment.py
```

**Parámetros Interactivos:**
```
¿Límite de organizaciones? (Enter para todas): 10
Tamaño de lote (default=5 para Azure): 5
¿Forzar re-enriquecimiento? (s/n, default=n): n
```

**Output Ejemplo:**
```
================================================================================
🏢 INICIANDO ENRIQUECIMIENTO DE ORGANIZACIONES
================================================================================

📋 Configuración:
   • Motor: Super-query GraphQL (1 query por organización)
   • Campos a enriquecer:
     - quantum_focus_score (0-100)
     - quantum_repositories (IDs desde BD local)
     - top_quantum_contributors
     - top_languages (stack tecnológico)
     - total_stars (prestigio acumulado)
     - is_quantum_focused (threshold 30%)
   • Optimizaciones:
     - Sleep 0.5s entre organizaciones
     - Batch size optimizado para Azure Free Tier

📦 Procesando lote 1/2 (5 organizaciones)

🏢 Enriqueciendo organización: qiskit-community
   📊 Repos quantum: 8/12
   🎯 Quantum score: 92.00%
   ⭐ Total estrellas: 12450
   💻 Top lenguajes: Python (75.0%), Jupyter Notebook (12.5%), C++ (12.5%)
   ✅ Relevante - Descubierta desde: qiskit/qiskit-terra, qiskit/qiskit-aer
✅ Organización qiskit-community enriquecida correctamente

🏢 Enriqueciendo organización: xanadu-ai
   📊 Repos quantum: 5/8
   🎯 Quantum score: 75.50%
   ⭐ Total estrellas: 8920
   💻 Top lenguajes: Python (80.0%), C++ (20.0%)
   ✅ Relevante - Descubierta desde: xanadu-ai/pennylane
✅ Organización xanadu-ai enriquecida correctamente

================================================================================
📊 RESUMEN DE ENRIQUECIMIENTO
================================================================================
✅ Total procesadas: 10
✅ Total enriquecidas: 10
❌ Total errores: 0

⏱️  Duración: 12.50 segundos (0.2 minutos)
```

---

## 🎯 Casos de Uso

### **1. Ranking de Organizaciones Quantum**

```javascript
// Ordenar por Quantum Focus Score
db.organizations.find({
  is_quantum_focused: true
}).sort({
  quantum_focus_score: -1
}).limit(10)

// Output:
// 1. qiskit-community (92.0%)
// 2. xanadu-ai (75.5%)
// 3. ionq (68.2%)
```

---

### **2. Análisis de Stack Tecnológico**

```javascript
// Organizaciones que usan Python
db.organizations.find({
  "top_languages.name": "Python"
})

// Comparar Python vs C++ en Quantum
db.organizations.aggregate([
  {$unwind: "$top_languages"},
  {$match: {is_quantum_focused: true}},
  {$group: {
    _id: "$top_languages.name",
    total_orgs: {$sum: 1},
    avg_percentage: {$avg: "$top_languages.percentage"}
  }},
  {$sort: {total_orgs: -1}}
])
```

---

### **3. Prestigio vs Cantidad**

```javascript
// Top orgs por estrellas (calidad)
db.organizations.find({
  is_relevant: true
}).sort({
  total_stars: -1
}).limit(10)

// Top orgs por cantidad de repos
db.organizations.find({
  is_relevant: true
}).sort({
  quantum_repositories_count: -1
}).limit(10)
```

---

### **4. Identificar Líderes Técnicos**

```javascript
// Contributors en múltiples organizaciones
db.organizations.aggregate([
  {$unwind: "$top_quantum_contributors"},
  {$group: {
    _id: "$top_quantum_contributors.login",
    orgs_count: {$sum: 1},
    orgs: {$push: "$login"}
  }},
  {$sort: {orgs_count: -1}},
  {$limit: 10}
])

// Output:
// john_doe: 5 organizaciones (qiskit, ibm, microsoft, ...)
```

---

### **5. Trazabilidad de Descubrimiento**

```javascript
// Qué repos llevaron a descubrir cada org
db.organizations.find({
  is_relevant: true
}).forEach(org => {
  print(`${org.login}:`);
  org.discovered_from_repos.forEach(repo => {
    print(`  - ${repo.name}`);
  });
})

// Output:
// qiskit-community:
//   - qiskit/qiskit-terra
//   - qiskit/qiskit-aer
//   - qiskit/qiskit-ibmq-provider
```

---

### **6. Filtrar Organizaciones No Relevantes**

```javascript
// Solo organizaciones con repos quantum
db.organizations.find({
  is_relevant: true,
  quantum_repositories_count: {$gt: 0}
})

// Excluir "ruido" del ecosistema
db.organizations.find({
  is_relevant: false
}).count()  // 5217 orgs descubiertas pero sin repos quantum
```

---

## 🔧 Troubleshooting

### **Problema 1: No encuentra organizaciones para enriquecer**

**Síntoma:**
```
📊 Total organizaciones a enriquecer: 0
✅ No hay organizaciones para enriquecer
```

**Causa:** El filtro incremental no detecta orgs con `enriched_at: null`

**Solución:**
```python
# El query debe incluir:
{
    "$or": [
        {"enrichment_status": {"$exists": False}},
        {"enrichment_status": None},  # ← AÑADIR esto
        {"enriched_at": {"$exists": False}},
        {"enriched_at": None},  # ← AÑADIR esto
        {"enrichment_status.is_complete": False}
    ]
}
```

---

### **Problema 2: Campo `is_quantum_related` no existe**

**Síntoma:**
```
Error: Campo 'is_quantum_related' no encontrado en repos
```

**Causa:** Intentar filtrar repos con campo que no se guarda (redundante)

**Solución:**
```python
# ❌ INCORRECTO:
quantum_repos = repos_collection.find({
    "owner.login": org_login,
    "is_quantum_related": True  # Campo que no existe
})

# ✅ CORRECTO:
org_repos = repos_collection.find({
    "owner.login": org_login  # Si está en BD, ya es quantum
})
```

---

### **Problema 3: Estrellas siempre en 0**

**Síntoma:**
```
⭐ Total estrellas: 0
```

**Causa:** Buscar campo incorrecto

**Solución:**
```python
# ❌ INCORRECTO:
stars = repo.get("stars_count", 0)

# ✅ CORRECTO:
stars = repo.get("stargazer_count", 0)  # Campo real en MongoDB
```

---

### **Problema 4: Rate Limit Exceeded**

**Síntoma:**
```
Error 429: API rate limit exceeded
```

**Causa:** No hay sleep entre requests

**Solución:**
```python
# Asegurar sleep_time en el loop
for org in batch:
    self._enrich_single_organization(org)
    time.sleep(self.sleep_time)  # 0.5s por defecto
```

---

### **Problema 5: discovered_from_repos desincronizado**

**Síntoma:**
```python
discovered_from_repos: ["R_123", "R_456"]
discovered_from_repo_names: ["qiskit/qiskit-terra"]  # Falta uno
```

**Causa:** Usar dos arrays separados

**Solución:** Unificar en un solo array de objetos
```python
# ✅ MEJOR:
discovered_from_repos: [
  {"id": "R_123", "name": "qiskit/qiskit-terra"},
  {"id": "R_456", "name": "qiskit/qiskit-aer"}
]
```

---

### **Problema 6: Cosmos DB Rate Limit Errors (429 TooManyRequests)**

**Síntoma:**
```
pymongo.errors.OperationFailure: Command find failed: 
Request rate is large. ActivityId: xxx, Error: 16500, 
RetryAfterMs: 660, Details: Response status code does not 
indicate success: TooManyRequests (429)
```

**Causa:** Azure Cosmos DB Free Tier tiene límite de 400 RU/s (Request Units por segundo)

**Solución Implementada:**

#### **1. Sistema de Reintentos con Backoff Exponencial**

```python
def _retry_on_cosmos_throttle(self, operation, max_retries: int = 5):
    """
    Reintenta operaciones de MongoDB con manejo de throttling de Cosmos DB.
    
    Características:
    - Detecta error 16500 (Cosmos DB throttling)
    - Extrae RetryAfterMs del mensaje de error
    - Espera el tiempo indicado por Cosmos DB
    - Máximo 5 reintentos
    - Degradación graciosa (retorna None si falla)
    """
    for attempt in range(max_retries):
        try:
            return operation()
        except OperationFailure as e:
            if e.code == 16500:  # Cosmos DB throttling
                # Parsear RetryAfterMs del mensaje de error
                error_msg = str(e)
                retry_after_ms = 1000  # default fallback
                
                if 'RetryAfterMs=' in error_msg:
                    start = error_msg.index('RetryAfterMs=') + len('RetryAfterMs=')
                    end = error_msg.index(',', start)
                    retry_after_ms = int(error_msg[start:end])
                
                retry_after_s = retry_after_ms / 1000.0
                
                if attempt < max_retries - 1:
                    logger.warning(
                        f"⚠️  Cosmos DB 429: esperando {retry_after_s:.2f}s "
                        f"(intento {attempt + 1}/{max_retries})"
                    )
                    time.sleep(retry_after_s)
                else:
                    logger.error(
                        f"❌ Max reintentos alcanzado tras {max_retries} intentos"
                    )
                    return None  # Degradación graciosa
            else:
                raise  # Otro tipo de OperationFailure
        except Exception as e:
            logger.error(f"❌ Error inesperado: {e}")
            return None
    
    return None
```

#### **2. Wrapping de Operaciones MongoDB**

```python
# Todas las operaciones usan retry automático:

# Lectura de repos
quantum_repos = self._retry_on_cosmos_throttle(
    lambda: list(self.repos_repository.collection.find({
        "owner.login": org_login
    }))
)

# Validación de None (degradación graciosa)
if quantum_repos is None or not quantum_repos:
    return None

# Sleep adicional para reducir presión sobre RU/s
time.sleep(0.2)  # Lecturas
time.sleep(0.3)  # Escrituras
```

#### **3. Configuración de Sleeps Optimizada**

```python
# En OrganizationEnrichmentEngine.__init__:
sleep_time: float = 1.0  # Entre organizaciones

# En scripts/run_organization_enrichment.py:
engine = OrganizationEnrichmentEngine(
    batch_size=5,
    sleep_time=1.0  # Aumentado de 0.5s a 1.0s
)
```

#### **4. Manejo de Resultados None**

```python
# _find_quantum_repositories
if quantum_repos is None or not quantum_repos:
    return None

# _find_top_quantum_contributors
if results is None:
    return []

# _calculate_top_languages
if repos is None or not repos:
    return []

# _calculate_total_stars
if repos is None:
    return 0
```

**Resultados Esperados:**
```
✅ Tiempos de espera variables basados en RetryAfterMs de Cosmos DB
   ⚠️  Cosmos DB 429: esperando 0.66s (intento 1/5)
   ⚠️  Cosmos DB 429: esperando 1.85s (intento 2/5)
   ⚠️  Cosmos DB 429: esperando 3.14s (intento 3/5)

✅ Sistema continúa procesando tras fallos individuales
✅ Organizaciones exitosas se enrichecen correctamente
✅ Métricas parciales (si algunas queries fallan)
```

**Recomendaciones Adicionales:**

1. **Reducir batch_size** si persisten errores:
   ```python
   batch_size = 3  # Reducir de 5 a 3
   ```

2. **Aumentar sleep_time** entre orgs:
   ```python
   sleep_time = 2.0  # Aumentar de 1.0s a 2.0s
   ```

3. **Considerar Azure Cosmos DB Tier superior** si el volumen crece:
   - Free Tier: 400 RU/s
   - Standard: 1000+ RU/s configurable

4. **Implementar caching** para reducir queries repetitivas

---

## 📚 Referencias

### **Archivos Principales:**

- **Modelo:** `src/models/organization.py`
- **Ingesta:** `src/github/organization_ingestion.py`
- **Enriquecimiento:** `src/github/organization_enrichment.py`
- **Script Ingesta:** `scripts/run_organization_ingestion.py`
- **Script Enriquecimiento:** `scripts/run_organization_enrichment.py`

### **Documentación Relacionada:**

- [Ingesta de Repositorios](./README_DB.md)
- [Ingesta de Usuarios](./INGESTA_ENRIQUECIMIENTO_USUARIOS.md)
- [Filtros Avanzados](./filtros_avanzados_resumen.md)
- [GraphQL Client](./graphql_client_guide.md)

---

## 🎉 Resumen Ejecutivo

✅ **Sistema completo** de ingesta y enriquecimiento de organizaciones  
✅ **Estrategia Bottom-Up** desde usuarios quantum  
✅ **Sistema de relevancia** basado en repos ingestados  
✅ **Trazabilidad completa** de descubrimiento  
✅ **Análisis tecnológico** (stack, prestigio, contributors)  
✅ **Quantum Focus Score** ponderado con bonificaciones  
✅ **Rate Limit management** en todos los procesos  
✅ **Optimizado para Azure Free Tier** (batch_size=5, sleep=0.5s)

---

**Última actualización:** 3 de diciembre de 2025  
**Versión:** 2.0.0
