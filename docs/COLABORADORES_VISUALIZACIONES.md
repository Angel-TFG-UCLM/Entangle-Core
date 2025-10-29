# 📊 Visualizaciones: Sistema de Colaboradores

## 🎯 Diagrama del Sistema

```
┌─────────────────────────────────────────────────────────────────┐
│                    SISTEMA HÍBRIDO DE COLABORADORES              │
└─────────────────────────────────────────────────────────────────┘

┌──────────────────────┐         ┌──────────────────────┐
│   REST API           │         │   GraphQL API        │
│   Contributors       │         │   MentionableUsers   │
│                      │         │                      │
│  • 472 usuarios      │         │  • 638 usuarios      │
│  • Con commits       │         │  • Mencionables      │
│  • 5 páginas         │         │  • 7 páginas         │
└──────────┬───────────┘         └──────────┬───────────┘
           │                                 │
           │  _fetch_contributors_rest()     │  _fetch_mentionable_users_graphql()
           │  (con paginación)               │  (con cursores)
           │                                 │
           └────────────┬────────────────────┘
                        │
                        ▼
           ┌────────────────────────┐
           │  _fetch_collaborators_ │
           │      combined()        │
           │                        │
           │  • Combina ambas listas│
           │  • Elimina duplicados  │
           │  • Añade flags         │
           └───────────┬────────────┘
                       │
                       ▼
          ┌────────────────────────┐
          │   MongoDB: 641 únicos  │
          │                        │
          │  • has_commits: bool   │
          │  • is_mentionable: bool│
          │  • contributions: int  │
          └────────────────────────┘
```

---

## 📈 Distribución de Colaboradores (Qiskit)

### Diagrama de Venn

```
                  ┌─────────────────────────────────┐
                  │    MentionableUsers (638)       │
                  │                                 │
                  │  ┌─────────────────────────┐   │
                  │  │   Intersection (469)    │   │
                  │  │                         │   │
    ┌─────────────┼──┤   has_commits: true     │   │
    │ Contributors│  │   is_mentionable: true  ├───┤
    │   (472)     │  │                         │   │
    │             │  │  "Developers activos"   │   │
    │             │  └─────────────────────────┘   │
    │             │                                 │
    │    (3)      │              (169)              │
    │  "Inactivos"│          "Reviewers"            │
    └─────────────┴─────────────────────────────────┘
    
    Total colaboradores únicos: 641
```

### Tabla de Distribución

| Segmento | Cantidad | % | Descripción |
|----------|----------|---|-------------|
| **Developers activos** | 469 | 73.2% | Commits + Mencionables |
| **Reviewers/Triage** | 169 | 26.4% | Solo mencionables |
| **Contributors inactivos** | 3 | 0.4% | Commits, no mencionables |
| **TOTAL** | **641** | **100%** | - |

---

## 📊 Gráfico de Barras: Top 10 Contributors

```
Contribuciones por usuario (Top 10)

mtreinish        ████████████████████████████ 1322
jakelishman      ████████████████ 609
1ucian0          ███████████████ 544
ajavadia         ██████████ 372
nkanazawa1989    █████████ 345
chriseclectic    ████████ 312
ewinston         ███████ 280
ikkoham          ██████ 245
levbishop        █████ 198
nonhermitian     █████ 185

0       200      400      600      800     1000    1200    1400
                        Commits
```

---

## 🔄 Flujo de Paginación

### Contributors (REST API)

```
┌─────────┐
│ Página 1│  per_page=100
│  100    │  page=1
└────┬────┘
     │ Link: rel="next"
     ▼
┌─────────┐
│ Página 2│  per_page=100
│  100    │  page=2
└────┬────┘
     │ Link: rel="next"
     ▼
┌─────────┐
│ Página 3│  per_page=100
│  100    │  page=3
└────┬────┘
     │ Link: rel="next"
     ▼
┌─────────┐
│ Página 4│  per_page=100
│  100    │  page=4
└────┬────┘
     │ Link: rel="next"
     ▼
┌─────────┐
│ Página 5│  per_page=100
│   72    │  page=5
└────┬────┘
     │ No "next" → FIN
     ▼
  Total: 472
```

### MentionableUsers (GraphQL)

```
┌─────────┐
│ Página 1│  first=100
│  100    │  after=null
└────┬────┘
     │ hasNextPage=true, endCursor="Y..."
     ▼
┌─────────┐
│ Página 2│  first=100
│  100    │  after="Y..."
└────┬────┘
     │ hasNextPage=true, endCursor="Z..."
     ▼
┌─────────┐
│ Página 3│  first=100
│  100    │  after="Z..."
└────┬────┘
     │ hasNextPage=true, endCursor="A..."
     ▼
     ...
     │
     ▼
┌─────────┐
│ Página 7│  first=100
│   38    │  after="F..."
└────┬────┘
     │ hasNextPage=false → FIN
     ▼
  Total: 638
```

---

## 🎨 Diagrama de Flujo: Proceso de Enriquecimiento

```
                    ┌──────────────────┐
                    │  Iniciar         │
                    │  Enriquecimiento │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │ Obtener repo de  │
                    │    MongoDB       │
                    └────────┬─────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
          ▼                  ▼                  ▼
    ┌──────────┐      ┌──────────┐      ┌──────────┐
    │ Step 1-14│      │ Step 15  │      │ Step 16  │
    │ Campos   │      │REST fields│     │GraphQL   │
    │ básicos  │      │           │      │ fields   │
    └──────────┘      └──────────┘      └──────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │    Step 18       │
                    │  Colaboradores   │
                    └────────┬─────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
          ▼                  ▼                  ▼
    ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
    │Fetch         │   │Fetch        │   │Combinar     │
    │Contributors  │   │Mentionable  │   │Listas       │
    │(REST)        │   │Users(GraphQL)│  │             │
    │              │   │              │   │             │
    │5 páginas     │   │7 páginas    │   │641 únicos   │
    │472 usuarios  │   │638 usuarios │   │             │
    └──────┬───────┘   └──────┬──────┘   └──────┬──────┘
           │                  │                  │
           └──────────────────┼──────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │ Actualizar       │
                    │ MongoDB          │
                    │                  │
                    │ collaborators:   │
                    │   [641 usuarios] │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │   Completado ✅   │
                    │  88.9% campos    │
                    └──────────────────┘
```

---

## 📉 Comparativa: Antes vs Después

### Tabla Comparativa

| Métrica | ❌ Antes | ✅ Después | Mejora |
|---------|---------|-----------|--------|
| **Contributors** | 100 | 472 | +372% |
| **MentionableUsers** | 100 | 638 | +538% |
| **Colaboradores únicos** | 172 | 641 | +273% |
| **Completitud** | 87.5% | 88.9% | +1.4% |
| **Páginas REST** | 1 | 5 | +400% |
| **Páginas GraphQL** | 1 | 7 | +600% |

### Gráfico de Mejora

```
Contributors Recuperados

600 ┤
    │                                          ████
550 ┤                                          ████
    │                                          ████
500 ┤                                          ████
    │                                          ████
450 ┤                                          ████
    │                                          ████  472 ✅
400 ┤                                          ████
    │                                          ████
350 ┤                                          ████
    │                                          ████
300 ┤                                          ████
    │                                          ████
250 ┤                                          ████
    │                                          ████
200 ┤                                          ████
    │                                          ████
150 ┤                                          ████
    │                                          ████
100 ┤         ████                             ████
    │         ████  100 ❌                      ████
 50 ┤         ████                             ████
    │         ████                             ████
  0 └─────────────────────────────────────────────
          Antes                             Después
```

---

## 🔢 Estadísticas Detalladas

### Distribución de Commits

```
Rango de Commits       Usuarios    %
────────────────────────────────────────
1000+                      2       0.4%
500-999                    2       0.4%
100-499                   25       5.3%
50-99                     38       8.0%
10-49                    132      28.0%
1-9                      273      57.9%
0 (sin commits)          169      26.4% ← Reviewers
────────────────────────────────────────
TOTAL                    641     100.0%
```

### Top Contributors

| Rank | Usuario | Commits | has_commits | is_mentionable |
|------|---------|---------|-------------|----------------|
| 1 | mtreinish | 1322 | ✅ | ✅ |
| 2 | jakelishman | 609 | ✅ | ❌ |
| 3 | 1ucian0 | 544 | ✅ | ✅ |
| 4 | ajavadia | 372 | ✅ | ✅ |
| 5 | nkanazawa1989 | 345 | ✅ | ✅ |
| 6 | chriseclectic | 312 | ✅ | ✅ |
| 7 | ewinston | 280 | ✅ | ✅ |
| 8 | ikkoham | 245 | ✅ | ✅ |
| 9 | levbishop | 198 | ✅ | ✅ |
| 10 | nonhermitian | 185 | ✅ | ✅ |

---

## 🎯 Casos de Uso para Análisis

### 1. Identificar Core Team

```python
# Contributors con >100 commits
core_team = [
    c for c in collaborators 
    if c["has_commits"] and c["contributions"] > 100
]

# Resultado: 27 desarrolladores core (5.7%)
```

### 2. Medir Diversidad de Contribución

```python
# Long Tail: Contributors con 1-9 commits
long_tail = [
    c for c in collaborators 
    if c["has_commits"] and 1 <= c["contributions"] <= 9
]

# Resultado: 273 contributors ocasionales (57.9%)
```

### 3. Identificar Equipo de Revisión

```python
# Solo reviewers (sin commits)
review_team = [
    c for c in collaborators 
    if not c["has_commits"] and c["is_mentionable"]
]

# Resultado: 169 reviewers/triagers (26.4%)
```

### 4. Detectar Contributors Inactivos

```python
# Con commits pero ya no mencionables
inactive = [
    c for c in collaborators 
    if c["has_commits"] and not c["is_mentionable"]
]

# Resultado: 3 contributors inactivos (0.6%)
```

---

## 📋 Checklist de Validación

### Paginación Contributors (REST)

- [x] Implementada paginación con Link headers
- [x] Recupera todas las páginas hasta que no hay "next"
- [x] Logging de progreso por página
- [x] Protección contra bucles infinitos (max 100 páginas)
- [x] Manejo de errores HTTP
- [x] **Resultado**: 472 contributors (5 páginas) ✅

### Paginación MentionableUsers (GraphQL)

- [x] Implementada paginación con cursores
- [x] Usa `pageInfo.hasNextPage` y `pageInfo.endCursor`
- [x] Recupera hasta que `hasNextPage=false`
- [x] Logging de progreso por página
- [x] Protección contra bucles infinitos (max 100 páginas)
- [x] **Resultado**: 638 usuarios (7 páginas) ✅

### Combinación Híbrida

- [x] Combina contributors + mentionableUsers
- [x] Elimina duplicados
- [x] Añade flag `has_commits`
- [x] Añade flag `is_mentionable`
- [x] Ordena por contributions
- [x] **Resultado**: 641 únicos ✅

### Validación de Datos

- [x] Verificado límite de 100 en REST
- [x] Verificado límite de 100 en GraphQL
- [x] Confirmado total de 472 contributors
- [x] Confirmado total de 638 mentionableUsers
- [x] Confirmado 641 colaboradores únicos
- [x] **Completitud**: 88.9% ✅

---

*Visualizaciones generadas: 29 de octubre de 2025*  
*Proyecto: TFG - Sistema de Colaboradores Híbrido*
