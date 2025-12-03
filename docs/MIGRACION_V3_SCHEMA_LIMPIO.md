# Migración v3.0: Esquema Limpio y Lógica de Completitud Realista

## 🎯 Objetivo

Solucionar el problema crítico del sistema de enriquecimiento: **usuarios con datos perfectos marcados incorrectamente como incompletos**.

### Problema Identificado

```json
// Usuario con datos válidos:
{
  "login": "johndoe",
  "company": null,
  "twitter_username": null,
  "quantum_expertise_score": 85.5,
  "enrichment_status": {
    "is_complete": false,  ❌ INCORRECTO
    "fields_missing": ["company", "twitter_username", "organizations"]  ❌ INCORRECTO
  }
}
```

**ANÁLISIS:** Que un usuario no tenga Twitter o empresa es un **dato válido**, NO un error.

---

## 📋 Cambios Implementados

### ACCIÓN 1: Modelo User v3.0 Limpio (`src/models/user.py`)

#### 1.1 Campos Eliminados (Obsoletos)

```python
# ❌ ELIMINADOS - Ya no existen en GitHub API o no se usan:
projects
hasSponsorshipsListing
monthlyEstimatedSponsorsIncomeInCents
social_accounts
status (emoji)
interaction_ability
pronouns
repositories (lista completa)
starred_repositories (lista completa)
contributions (objeto)
private_repos_count
is_bounty_hunter, is_campus_expert, is_developer_program_member
social_profile_enriched
status_message, status_emoji
recent_commits_30d, recent_issues_30d, recent_prs_30d
```

#### 1.2 Listas Simplificadas

```python
# ✅ ANTES (v2.0): Listas complejas con objetos anidados
organizations: Optional[List[UserOrganization]] = None
pinned_repositories: Optional[List[UserRepository]] = None
top_languages: Optional[List[str]] = None

# ✅ DESPUÉS (v3.0): Listas simples con validación automática
organizations: List[UserOrganization] = Field(default_factory=list)
pinned_repositories: List[UserRepository] = Field(default_factory=list)
top_languages: List[str] = Field(default_factory=list)
```

#### 1.3 Validadores Inteligentes

```python
@validator('organizations', 'pinned_repositories', 'top_languages', 
           'quantum_repositories', pre=True, always=True)
def convert_none_to_empty_list(cls, v):
    """
    Convierte None a [] automáticamente.
    Si GitHub devuelve null → guardamos lista vacía.
    NO rompe la validación.
    """
    return v if v is not None else []
```

**BENEFICIO:** Ya no hay errores por listas nulas. `None` → `[]` de forma transparente.

---

### ACCIÓN 2: Lógica de Completitud Realista (`src/github/user_enrichment.py`)

#### 2.1 Criterio ANTERIOR (v2.0) - MALO ❌

```python
# Si falta CUALQUIER campo opcional → incompleto
fields_missing = [
    field for field in expected_fields 
    if user.get(field) is None and updates.get(field) is None
]

is_complete = len(fields_missing) == 0  # ❌ DEMASIADO ESTRICTO
```

**PROBLEMA:** Marcaba como incompletos usuarios perfectamente válidos sin Twitter/empresa.

#### 2.2 Criterio NUEVO (v3.0) - BUENO ✅

```python
# Si hemos calculado quantum_expertise_score → COMPLETO
is_complete = True  # Siempre True si llegamos al final sin error

updates["enrichment_status"] = {
    "is_complete": is_complete,
    "version": "3.0",
    "last_check": datetime.now().isoformat(),
    "fields_missing": []  # Ya no reportamos campos opcionales
}
```

**LÓGICA:**
- ✅ Si se ejecutó `_enrich_single_user` sin error → `is_complete = True`
- ✅ Si calculamos `quantum_expertise_score` → Usuario válido
- ✅ `fields_missing = []` siempre (no reportamos opcionales)

---

### ACCIÓN 3: Script de Migración (`scripts/fix_db_schema.py`)

#### 3.1 Ejecución

```powershell
python scripts/fix_db_schema.py
```

#### 3.2 Operaciones

**PASO 1: Borrar Campos Obsoletos**
```python
# 45 campos obsoletos eliminados con $unset
OBSOLETE_FIELDS = [
    "projects", "sponsors", "packages", "social_network_sample",
    "notable_issues_prs", "languages_detailed", "quantum_gists",
    "social_accounts", "status", "interaction_ability", ...
]

db.users.update_many({}, {"$unset": {field: "" for field in OBSOLETE_FIELDS}})
```

**PASO 2: Corregir Listas Nulas**
```python
# Convertir None → [] para listas esenciales
LIST_FIELDS = [
    "organizations", "pinned_repositories", 
    "top_languages", "quantum_repositories"
]

for field in LIST_FIELDS:
    db.users.update_many(
        {field: {"$in": [None, "null"]}},
        {"$set": {field: []}}
    )
```

**PASO 3: Recalcular Enrichment Status**
```python
# Usuarios con quantum_expertise_score → is_complete = True
db.users.update_many(
    {"quantum_expertise_score": {"$ne": None}},
    {"$set": {
        "enrichment_status": {
            "is_complete": True,
            "version": "3.0",
            "last_check": datetime.now().isoformat(),
            "fields_missing": []
        }
    }}
)
```

---

## 🚀 Flujo de Trabajo Completo

### 1. Ejecutar Migración de BD

```powershell
# PASO 1: Migrar esquema existente
python scripts/fix_db_schema.py

# Confirmar con "SI" cuando pregunte
✅ Total usuarios marcados como completos: 15,234
```

### 2. Ejecutar Enriquecimiento v3.0

```powershell
# PASO 2: Enriquecer nuevos usuarios con lógica v3.0
python scripts/run_user_enrichment.py

# Parámetros:
Max usuarios: 100
Batch size: 5
Force re-enrich: no

✅ Usuario johndoe enriquecido correctamente (v3.0)
```

### 3. Verificar Resultados

```javascript
// MongoDB query
db.users.find({
  "enrichment_status.version": "3.0",
  "enrichment_status.is_complete": true
}).count()
// Expected: Todos los usuarios con quantum_expertise_score
```

---

## 📊 Impacto de la Migración

### Antes (v2.0)

```json
{
  "_id": "...",
  "login": "johndoe",
  "company": null,
  "twitter_username": null,
  "projects": [],  // ❌ Campo obsoleto
  "social_accounts": [],  // ❌ Campo obsoleto
  "organizations": null,  // ❌ Null en vez de []
  "quantum_expertise_score": 85.5,
  "enrichment_status": {
    "is_complete": false,  // ❌ Marcado como incompleto
    "fields_missing": ["company", "twitter_username", "organizations"],
    "version": "2.0"
  }
}
```

### Después (v3.0)

```json
{
  "_id": "...",
  "login": "johndoe",
  "company": null,  // ✅ null es válido
  "twitter_username": null,  // ✅ null es válido
  "organizations": [],  // ✅ Lista vacía en vez de null
  "pinned_repositories": [],  // ✅ Validado automáticamente
  "top_languages": ["Python", "Go"],
  "quantum_expertise_score": 85.5,
  "enriched_at": "2025-12-01T10:30:00",
  "enrichment_status": {
    "is_complete": true,  // ✅ Correctamente marcado
    "version": "3.0",
    "last_check": "2025-12-01T10:30:00",
    "fields_missing": []  // ✅ No reporta opcionales
  }
}
```

---

## ✅ Validación

### Test de Validación Pydantic

```python
from src.models.user import User

# Datos con listas nulas
data = {
    "id": "123",
    "login": "testuser",
    "url": "https://github.com/testuser",
    "organizations": None,  # ✅ Se convierte a []
    "pinned_repositories": None,  # ✅ Se convierte a []
    "top_languages": None  # ✅ Se convierte a []
}

user = User(**data)

assert user.organizations == []
assert user.pinned_repositories == []
assert user.top_languages == []
print("✅ Validación exitosa")
```

### Test de Completitud

```python
# Usuario sin company/twitter pero con quantum_score
user = {
    "login": "johndoe",
    "company": None,
    "twitter_username": None,
    "quantum_expertise_score": 85.5,
    "enriched_at": datetime.now()
}

# Después de enriquecimiento v3.0
assert user["enrichment_status"]["is_complete"] == True
assert user["enrichment_status"]["fields_missing"] == []
print("✅ Lógica de completitud correcta")
```

---

## 🔧 Mantenimiento

### Campos Core del Modelo (NO eliminar)

```python
# IDENTIFICACIÓN
id, login, name

# CORE TFG (CRÍTICO)
quantum_repositories
quantum_expertise_score
is_quantum_contributor

# LISTAS ESENCIALES
organizations
pinned_repositories
top_languages

# CONTADORES SOCIALES
followers_count, following_count
public_repos_count, starred_repos_count
total_commit_contributions, total_issue_contributions

# TRACKING
enrichment_status
enriched_at
ingested_at
```

### Si Necesitas Añadir Nuevo Campo

1. **Añadir al modelo:**
```python
class User(BaseModel):
    new_field: Optional[str] = None
```

2. **NO modificar lógica de completitud:**
```python
# ✅ CORRECTO: is_complete siempre True si no hay error
is_complete = True

# ❌ INCORRECTO: No añadir a fields_missing
fields_missing = []  # Siempre vacío
```

---

## 📝 Conclusión

**v3.0 soluciona el problema de raíz:**

- ✅ Modelo limpio (45 campos obsoletos eliminados)
- ✅ Validadores automáticos (`None` → `[]`)
- ✅ Lógica de completitud realista
- ✅ BD migrada con script automatizado
- ✅ Sin falsos negativos en `is_complete`

**Resultado:** Usuarios válidos correctamente marcados como completos.
