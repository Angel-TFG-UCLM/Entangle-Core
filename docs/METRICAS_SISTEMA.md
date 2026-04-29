# Métricas Especiales del Sistema ENTANGLE

> Documentación técnica de todas las métricas computadas en el sistema Quantum Universe (ENTANGLE).
> Última actualización: Junio 2025

---

## Índice

1. [Collab Score (Puntuación de Colaboración)](#1-collab-score)
2. [Quantum Expertise Score (Expertise en Quantum)](#2-quantum-expertise-score)
3. [Quantum Focus Score (Enfoque Quantum de Org)](#3-quantum-focus-score)
4. [Métricas Sociales](#4-métricas-sociales)
5. [Métricas Derivadas de Repositorios](#5-métricas-derivadas-de-repositorios)
6. [Resumen de Impacto en el Sistema](#6-resumen-de-impacto-en-el-sistema)

---

## 1. Collab Score

### Descripción
Cuantifica la relevancia colaborativa de un usuario dentro del ecosistema quantum. Combina el volumen de contribuciones en repositorios quantum con la amplitud de su participación (número de repos relevantes).

### Fórmula

$$\text{Collab Score} = \left\lfloor \sqrt{\text{quantum\_contributions} \times (\text{relevant\_repos} \times 100)} \right\rfloor$$

### Definición de Variables

| Variable | Descripción |
|---|---|
| `quantum_contributions` | Suma de contribuciones del usuario **exclusivamente en repos quantum** de la BD. Se obtiene cruzando las contribuciones registradas en el campo `collaborators` de cada repositorio con el login del usuario. |
| `relevant_repos` | Cantidad de repos quantum donde el usuario es **owner** o tiene **más de 5 contribuciones** (colaborador activo). |

### Origen de Datos

- **Dashboard (ChartsSection)**: Se calcula en el frontend a partir de los datos enriquecidos del endpoint `/dashboard/data`. Usa `total_contributions` (campo pre-calculado en enrichment) y `relevant_repos_count`.
- **Favoritos (FavoritesPanel)**: Se calcula en el **backend** mediante un pipeline de agregación en el endpoint `/search/entity/user_{login}`. El backend cruza la colección `repositories` buscando repos donde el usuario aparece en `collaborators.login`, suma sus contribuciones, y devuelve `_collab_score` pre-calculado.
- **Consistencia**: Ambos caminos producen el mismo resultado porque usan la misma lógica (contribuciones quantum + repos relevantes con umbral >5).

### Rango de Valores
- **Mínimo**: 0 (sin participación en repos quantum)
- **Típico**: 50 – 500
- **Máximo teórico**: Sin límite superior, pero en la práctica rara vez supera 1000

### Impacto en el Sistema
- **Dashboard**: Ordena el ranking "Top Contributors" de mayor a menor Collab Score.
- **Favoritos**: Se muestra en el panel de detalle inline al consultar un usuario.
- **3D Universe**: Influye en el tamaño del nodo del usuario en el grafo de colaboración.

---

## 2. Quantum Expertise Score

### Descripción
Mide el nivel de expertise de un usuario en computación cuántica. Es una métrica compuesta que pondera múltiples factores: repositorios propios vs colaborados, estrellas recibidas, contribuciones totales y pertenencia a organizaciones quantum.

### Fórmula

$$\text{Expertise} = \min\left(\sum \text{Factores}, 100\right)$$

### Factores y Pesos

| Factor | Cálculo | Peso | Máximo |
|---|---|---|---|
| Repos quantum como **owner** | `count(owner_repos)` | ×5 puntos c/u | Sin límite |
| Repos quantum como **colaborador** | `count(collab_repos)` | ×2 puntos c/u | Sin límite |
| Estrellas en repos quantum | `sum(stars)` | ×0.1 por estrella | 50 puntos |
| Contribuciones en repos quantum | `sum(contributions)` | ×0.05 por contrib. | 25 puntos |
| Organizaciones quantum | `count(quantum_orgs)` | ×10 puntos c/u | Sin límite |

> **Detección de orgs quantum**: Se buscan las keywords `quantum`, `qiskit`, `cirq`, `pennylane` en el nombre y descripción de la organización.

### Origen de Datos
- **Backend** (`user_enrichment.py` → `_calculate_quantum_expertise`): Se calcula durante el proceso de enriquecimiento y se almacena en el documento del usuario en MongoDB como campo `quantum_expertise_score`.
- Los datos de repos llegan de `_find_quantum_repositories`, que cruza la BD de repos con el login del usuario.

### Rango de Valores
- **Escala**: 0 – 100 (normalizado con cap)
- **0**: Sin repos quantum
- **100**: Alto volumen de repos propios + muchas estrellas + contribuciones activas + orgs quantum

### Impacto en el Sistema
- **Dashboard**: Se muestra como estadística clave en el perfil de usuario. Usado para identificar los expertos más relevantes.
- **Favoritos**: Visible en badges del panel de detalle inline (badge "Quantum Expert" cuando score ≥ 50).
- **3D Universe**: Puede influir en la intensidad visual (brillo/color) del nodo usuario.

---

## 3. Quantum Focus Score

### Descripción
Métrica a nivel de **organización** que indica qué proporción de su actividad pública está dedicada a computación cuántica. Incluye bonificaciones por branding quantum y verificación oficial.

### Fórmula

$$\text{Focus} = \min\left(\left(\frac{\text{quantum\_repos}}{\text{total\_repos}} \times 100\right) + B + V, \; 100\right)$$

Donde:
- $B = 10$ si el nombre o descripción de la org contiene keywords quantum, $0$ en caso contrario
- $V$: multiplicador $\times 1.2$ si la organización está verificada en GitHub

### Keywords Quantum Detectadas
`quantum`, `qiskit`, `cirq`, `qubit`, `entanglement`, `qasm`, `pennylane`, `tket`, `braket`, `qdk`, `ionq`

### Origen de Datos
- **Backend** (`organization_enrichment.py` → `_calculate_quantum_focus_score`): Se calcula durante el enriquecimiento de organizaciones.
- `quantum_repos`: Repos de la org presentes en la BD `quantum_github.repositories`.
- `total_repos`: Valor `public_repositories_count` del documento de la org.
- Se almacena como `quantum_focus_score` en el documento de la organización.

### Rango de Valores
- **Escala**: 0 – 100
- **0**: La org no tiene repos quantum o `total_repos = 0`
- **100**: Todos sus repos son quantum + tiene branding + está verificada

### Impacto en el Sistema
- **Dashboard**: Se muestra en el ranking de organizaciones. Ordena la relevancia de las orgs en el chart "Top Organizations".
- **Favoritos**: Visible en el panel de detalle de organizaciones.
- **3D Universe**: Influye en el color/tamaño del nodo de la organización.

---

## 4. Métricas Sociales

Calculadas en `user_enrichment.py` → `_calculate_social_metrics`.

### 4.1 Follower/Following Ratio

$$\text{Ratio} = \begin{cases} \frac{\text{followers}}{\text{following}} & \text{si } following > 0 \\ followers & \text{si } following = 0 \end{cases}$$

| Aspecto | Detalle |
|---|---|
| **Significado** | Mide la "influencia social" del usuario. Un ratio alto indica que atrae seguidores sin necesidad de seguir a muchos. |
| **Rango** | 0 – ∞ (típico: 0.5 – 50) |
| **Almacenamiento** | `follower_following_ratio` en el documento del usuario |
| **Impacto** | Indicador secundario de prestigio, visible en tooltips del Dashboard. |

### 4.2 Stars Per Repo

$$\text{Stars/Repo} = \frac{\sum \text{stars de repos relevantes}}{\text{count(repos relevantes)}}$$

> **Repo relevante**: El usuario es owner, o tiene > 5 contribuciones.

| Aspecto | Detalle |
|---|---|
| **Significado** | Calidad media de los repos quantum del usuario. Un valor alto indica que produce repos de alta visibilidad. |
| **Rango** | 0 – ∞ (típico: 0 – 500) |
| **Almacenamiento** | `stars_per_repo` en el documento del usuario |
| **Impacto** | Complementa el Quantum Expertise Score como indicador de calidad vs cantidad. |

### 4.3 Relevant Repos Count

| Aspecto | Detalle |
|---|---|
| **Significado** | Número total de repos quantum donde el usuario tiene participación significativa (owner o >5 contribuciones). |
| **Almacenamiento** | `relevant_repos_count` en el documento del usuario |
| **Impacto** | Se usa como input del Collab Score y como estadística visible en el perfil. |

### 4.4 Total Stars Received

| Aspecto | Detalle |
|---|---|
| **Significado** | Suma de estrellas de todos los repos quantum relevantes del usuario. |
| **Almacenamiento** | `total_stars_received` en el documento del usuario |
| **Impacto** | Indicador de prestigio acumulado. |

---

## 5. Métricas Derivadas de Repositorios

### 5.1 Total Stars (Organización)

Calculada en `organization_enrichment.py` → `_calculate_total_stars`.

$$\text{Total Stars} = \sum_{r \in \text{quantum\_repos}} r.\text{stargazer\_count}$$

| Aspecto | Detalle |
|---|---|
| **Significado** | Prestigio acumulado de todos los repos quantum de una organización. |
| **Almacenamiento** | `total_stars` en el documento de la organización |
| **Impacto** | Visible en Dashboard y Favoritos. Indica la tracción de la org en la comunidad. |

### 5.2 Quantum Repositories Count (Organización)

| Aspecto | Detalle |
|---|---|
| **Significado** | Número de repos de la organización que están indexados en la BD quantum. |
| **Almacenamiento** | `quantum_repositories_count` en el documento de la organización |
| **Impacto** | Input del Quantum Focus Score. Visible directamente en el Dashboard y Favoritos. |

---

## 6. Resumen de Impacto en el Sistema

### Matriz de Métricas × Componentes

| Métrica | Dashboard | Favoritos | 3D Universe | Backend |
|---|---|---|---|---|
| **Collab Score** | Ranking Top Contributors | Panel inline usuario | Tamaño nodo | Calculado en enrichment + `/search/entity` |
| **Quantum Expertise** | Perfil de usuario | Badge "Quantum Expert" | Brillo/color nodo | `user_enrichment.py` |
| **Quantum Focus** | Ranking orgs | Panel inline org | Tamaño/color nodo org | `organization_enrichment.py` |
| **Follower Ratio** | Tooltip usuario | — | — | `user_enrichment.py` |
| **Stars/Repo** | Estadística secundaria | — | — | `user_enrichment.py` |
| **Relevant Repos** | Estadística + input Collab | Panel inline usuario | — | `user_enrichment.py` |
| **Total Stars (Org)** | Chart orgs | Panel inline org | — | `organization_enrichment.py` |
| **Quantum Repos (Org)** | Chart orgs | Panel inline org | — | `organization_enrichment.py` |

### Flujo de Datos

```
GitHub API (GraphQL)
       │
       ▼
┌─────────────────┐
│   Ingestion     │  ← Recolecta datos brutos: repos, users, orgs
│   Scripts       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Enrichment    │  ← Calcula: quantum_expertise, quantum_focus,
│   Pipeline      │     social_metrics, quantum_repositories,
│                 │     total_stars, relevant_repos_count
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   MongoDB       │  ← Almacena documentos enriquecidos
│   (Cosmos DB)   │
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌────────┐ ┌──────────────┐
│  API   │ │  API Search  │  ← /dashboard/data computa collab_score en vuelo
│  Data  │ │  Entity      │  ← /search/entity computa _collab_score via
│        │ │              │     pipeline de agregación
└───┬────┘ └──────┬───────┘
    │              │
    ▼              ▼
┌─────────────────────────┐
│   Frontend              │
│   - ChartsSection       │  ← Muestra rankings, charts con scores
│   - FavoritesPanel      │  ← Muestra detalle inline con métricas
│   - UniverseView (3D)   │  ← Visualización de grafo con tamaños/colores
└─────────────────────────┘
```

### Principio de Consistencia

Todas las métricas de usuario (Collab Score, contribuciones quantum, repos relevantes) se calculan con la **misma lógica** independientemente del punto de acceso:

1. **Dashboard** → El frontend recibe datos pre-enriquecidos y calcula `√(contributions × repos × 100)`
2. **Favoritos** → El backend ejecuta un pipeline de agregación que aplica la misma fórmula y devuelve `_collab_score` pre-calculado
3. **Umbral de relevancia** → En ambos caminos: owner = relevante, colaborador con > 5 contribuciones = relevante

Esto garantiza que un mismo usuario muestre **idénticos valores** tanto en el Dashboard como en el panel de Favoritos.
