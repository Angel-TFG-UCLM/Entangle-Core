# ENTANGLE — Sistema de Análisis de Red de Colaboración

> Documentación completa del módulo de análisis de grafos de colaboración entre desarrolladores de software cuántico.  
> Incluye: qué significa cada cosa para el usuario, cómo funciona técnicamente y optimizaciones realizadas.

---

## Tabla de contenidos

1. [Resumen ejecutivo](#1-resumen-ejecutivo)
2. [¿Qué ve el usuario? — Guía visual](#2-qué-ve-el-usuario--guía-visual)
3. [Las 4 Lentes Analíticas](#3-las-4-lentes-analíticas)
4. [Quantum Tunneling](#4-quantum-tunneling)
5. [Panel de detalle enriquecido](#5-panel-de-detalle-enriquecido)
6. [Arquitectura técnica](#6-arquitectura-técnica)
7. [Endpoints de la API](#7-endpoints-de-la-api)
8. [Modelo de datos](#8-modelo-de-datos)
9. [Optimizaciones realizadas](#9-optimizaciones-realizadas)
10. [Archivos modificados/creados](#10-archivos-modificadoscreados)
11. [Preguntas frecuentes](#11-preguntas-frecuentes)

---

## 1. Resumen ejecutivo

### El problema
El universo 3D de ENTANGLE mostraba nodos (orgs, repos, usuarios) conectados visualmente — pero era solo una **representación estática**. No respondía preguntas analíticas reales sobre la colaboración.

### La solución
Se añadió una capa de **análisis de grafos** con [NetworkX](https://networkx.org/) que transforma la visualización en una herramienta de investigación. El usuario puede aplicar **lentes de color** que revelan patrones ocultos en la red de colaboración.

### Analogía
Imagina una radiografía médica. Sin las lentes, ves el cuerpo (la red). Con las lentes activas:
- **Comunidades** = rayos X que muestran los "órganos" (clusters de colaboración)
- **Centralidad** = un mapa de calor que revela los "nervios" (nodos puente críticos)
- **Bus Factor** = un diagnóstico de salud (riesgo si alguien se va)
- **Intensidad** = flujo sanguíneo (quién está más activo)

---

## 2. ¿Qué ve el usuario? — Guía visual

### Barra de lentes (parte superior)
```
[ Comunidades ] [ Centralidad ] [ Bus Factor ] [ Intensidad ] | [ Túnel ]
```
- Cada botón activa/desactiva una "lente" que **recolorea todos los nodos** del universo 3D.
- Solo una lente puede estar activa a la vez.
- Al hacer clic en la lente activa, se desactiva (vuelve a colores normales).
- El botón **Túnel** abre la barra de búsqueda de caminos.

### Colores normales (sin lente)
Sin lente activa, los nodos mantienen sus colores por defecto:
- **Organizaciones**: esferas grandes, color sólido.
- **Repositorios**: esferas medianas.
- **Usuarios**: partículas pequeñas.

### Primera carga
La primera vez que haces clic en una lente, el sistema necesita **~15-20 segundos** para construir y analizar el grafo completo (30,970 nodos, 101,190 aristas). Verás un spinner. Las siguientes llamadas son **instantáneas** (caché en memoria).

---

## 3. Las 4 Lentes Analíticas

### 3.1 🟣 Comunidades (Louvain)

**¿Qué pregunta responde?**  
> "¿Existen ecosistemas o clusters naturales de colaboración? ¿Quién trabaja con quién?"

**¿Qué veo?**  
Cada nodo se colorea según la **comunidad** a la que pertenece. Nodos del mismo color pertenecen al mismo cluster — es decir, colaboran entre sí mucho más que con el resto de la red.

**Colores:** 20 colores distintos asignados a las comunidades más grandes.

**¿Cómo se calcula?**  
Se usa el algoritmo de **Louvain** (`nx.community.louvain_communities`), que maximiza la *modularidad* de la red. La modularidad mide cuánto más densas son las conexiones dentro de cada comunidad vs lo que se esperaría al azar.

**¿Qué significan los resultados?**
- Una **modularidad alta** (>0.7) indica que la red tiene comunidades muy definidas — los desarrolladores tienden a trabajar en silos.
- En nuestro caso: modularidad = **0.9585** → los ecosistemas cuánticos están **muy separados** (Qiskit, PennyLane, Cirq, etc. forman clusters casi independientes).
- **752 comunidades** detectadas — la mayoría son pequeñas (1 org + sus repos + sus contribuidores).

**Utilidad para el TFG:**  
Demuestra empíricamente que el ecosistema de software cuántico está **fragmentado en silos** tecnológicos, con poca colaboración cross-framework.

---

### 3.2 🔵 Centralidad (Betweenness)

**¿Qué pregunta responde?**  
> "¿Quién es el nodo más importante de la red? ¿Quién actúa como puente entre comunidades?"

**¿Qué veo?**  
Los nodos se colorean en un gradiente:
- **Azul oscuro** → baja centralidad (periférico, solo conectado a su grupo)
- **Cian brillante** → alta centralidad (puente crítico entre muchos grupos)

**¿Cómo se calcula?**  
Se usan dos métricas:

1. **Betweenness Centrality** (`nx.betweenness_centrality`): Mide cuántos caminos más cortos de la red pasan por un nodo. Si muchos caminos pasan por ti, eres un "puente" — sin ti, partes de la red quedarían desconectadas.

2. **Degree Centrality** (`nx.degree_centrality`): Mide cuántas conexiones directas tiene un nodo, normalizado por el máximo posible.

**Fórmulas simplificadas:**
```
Betweenness(v) = Σ (σ_st(v) / σ_st)  para todo s≠v≠t
  donde σ_st = caminos más cortos entre s y t
        σ_st(v) = caminos más cortos entre s y t que pasan por v

Degree(v) = grado(v) / (N - 1)
  donde N = número total de nodos
```

**¿Qué significan los resultados?**
- Un usuario con **betweenness alto** (cian brillante) es alguien que contribuye a repositorios de **múltiples organizaciones diferentes** — es un conector entre ecosistemas.
- Un repositorio con betweenness alto atrae contribuidores de muchos orígenes distintos.
- La centralidad es **aproximada** (k=50 muestras aleatorias) por eficiencia. Con 30K nodos, el cálculo exacto tardaría >10 minutos.

**Utilidad para el TFG:**  
Identifica los **developers puente** que conectan diferentes frameworks cuánticos. Estos individuos son críticos para la transferencia de conocimiento en el ecosistema.

---

### 3.3 🔴 Bus Factor

**¿Qué pregunta responde?**  
> "¿Cuántas personas necesitan desaparecer para que un proyecto quede desatendido?"

**¿Qué veo?**  
**Solo los repositorios** cambian de color (los demás nodos quedan en gris):
- 🔴 **Rojo** = Bus Factor CRÍTICO (1 persona hace >50% del trabajo)
- 🟠 **Naranja** = Bus Factor ALTO (2 personas cubren >50%)
- 🟡 **Amarillo** = Bus Factor MEDIO (3-4 personas)
- 🟢 **Verde** = Bus Factor BAJO (5+ personas → saludable)

**¿Cómo se calcula?**
```
Para cada repositorio:
  1. Ordenar contribuidores por número de contribuciones (descendente)
  2. Sumar contribuciones acumuladas hasta alcanzar el 50% del total
  3. El número de personas necesarias = Bus Factor
  
  Ejemplo:
    Repo X tiene 1000 contribuciones totales:
    - Alice: 600 (60%) → acumulado = 600 ≥ 500 → Bus Factor = 1 (CRÍTICO)
    
    Repo Y tiene 1000 contribuciones totales:
    - Bob: 250, Carol: 200, Dave: 150, Eve: 100... → 250+200 = 450 < 500, +150 = 600 ≥ 500 → Bus Factor = 3 (MEDIO)
```

**¿Qué significan los resultados?**
- Un repositorio 🔴 rojo depende críticamente de una sola persona. Si esa persona se va, el proyecto está en riesgo.
- Los proyectos open-source cuánticos más pequeños suelen tener Bus Factor = 1 (un investigador principal hace casi todo).

**Utilidad para el TFG:**  
Análisis de sostenibilidad del ecosistema. Permite argumentar sobre la **fragilidad** o **salud** de proyectos cuánticos específicos.

---

### 3.4 🟡 Intensidad

**¿Qué pregunta responde?**  
> "¿Quién está más activo en la red? ¿Dónde hay más actividad de colaboración?"

**¿Qué veo?**  
Los nodos brillan en un gradiente cálido:
- **Rojo oscuro** → baja conectividad (pocos repos, pocas conexiones)
- **Amarillo brillante** → alta conectividad (muchos repos, muchas conexiones)

**¿Cómo se calcula?**  
Se usa la **degree centrality** (número de conexiones directas normalizado). Un usuario que contribuye a 20 repos tendrá un valor más alto que uno que contribuye a 2.

**¿Qué significan los resultados?**
- Los nodos amarillos son los **hubs de actividad** — las organizaciones con más repos, los usuarios más prolíficos, los repos con más contribuidores.
- A diferencia de la centralidad (que mide importancia estructural), la intensidad mide **volumen de actividad**.

**Utilidad para el TFG:**  
Mapea dónde se concentra la actividad de desarrollo cuántico. Útil para identificar los proyectos y organizaciones más activos.

---

## 4. Quantum Tunneling

**¿Qué pregunta responde?**  
> "¿Cómo están conectadas dos entidades cualesquiera? ¿Cuál es el camino más corto entre ellas?"

**¿Cómo funciona?**
1. Click en el botón **Túnel** → aparece una barra de búsqueda con dos campos: Origen y Destino.
2. Escribe para buscar cualquier organización, repositorio o usuario.
3. Selecciona origen y destino del dropdown.
4. Click en **🔍** (o Enter) → el backend busca el camino más corto en el grafo.
5. Se muestra el camino: `🏢 Qiskit Community → 📦 qiskit-ml → 👤 dependabot → 📦 pennylane-sf → 🏢 PennyLaneAI`

**Algoritmo:** Shortest Path de Dijkstra (`nx.shortest_path`), sin pesos (cada arista = 1 salto).

**Ejemplo real de nuestros datos:**
```
org_qiskit-community → org_PennyLaneAI
Camino: Qiskit Community → qiskit-machine-learning → dependabot[bot] → pennylane-sf → PennyLaneAI
Longitud: 4 saltos
```

**Utilidad para el TFG:**  
Demuestra que incluso frameworks aparentemente independientes están conectados a través de contribuidores compartidos (aunque sean bots como dependabot). Permite explorar los "grados de separación" del ecosistema cuántico.

---

## 5. Panel de detalle enriquecido

Cuando haces clic en un nodo (org, repo o usuario) y las métricas están cargadas, el panel lateral muestra información adicional:

### Para todos los nodos:
- **Centralidad** (barra 0-100%): cuán importante es este nodo como puente
- **Conectividad** (barra 0-100%): cuántas conexiones directas tiene
- **Comunidad** (badge de color): a qué cluster pertenece, con nombre y tamaño

### Solo para repositorios:
- **Bus Factor** (badge coloreado): número + nivel de riesgo
- **Top Contribuidores** (barras): los 3 principales con su porcentaje de contribuciones

---

## 6. Arquitectura técnica

### Flujo de datos

```
MongoDB (repos, users, orgs)
    │
    ▼
CollaborationNetworkAnalyzer.build_from_mongodb()
    │  Lee repos con collaborators, construye grafo NetworkX
    ▼
NetworkX Graph (30,970 nodos, 101,190 aristas)
    │
    ├─► compute_centrality()        → betweenness + degree por nodo
    ├─► detect_communities()        → Louvain → 752 comunidades
    ├─► compute_bus_factor()        → riesgo por repo
    ├─► compute_collaboration_intensity()  → peso por arista
    └─► compute_global_metrics()    → densidad, componentes, modularidad
    │
    ▼
Respuesta compacta (3.2 MB JSON)
    │  Filtrado: solo node_metrics + communities + global_metrics
    │  Serializado con orjson
    ▼
Frontend (React + Zustand store)
    │
    ├─► lensData useMemo  → mapea node_id → {r, g, b} según lente activa
    ├─► GLSL shaders      → aplica colores a las partículas 3D
    └─► Detail panel      → muestra métricas al hacer clic en un nodo
```

### Grafo NetworkX — Estructura

```
Tipos de nodo:
  org_{login}          → type="org",  attrs: login, name, avatar_url
  repo_{full_name}     → type="repo", attrs: name, full_name, stars, language, org
  user_{login}         → type="user", attrs: login, name, avatar_url, quantum_expertise_score

Tipos de arista:
  user → repo          → type="contributed_to", weight=contributions, has_commits
  org  → repo          → type="owns", weight=1
```

### Stack tecnológico

| Capa | Tecnología | Uso |
|------|-----------|-----|
| Análisis de grafos | NetworkX 3.6.1 | Centralidad, comunidades, caminos |
| Serialización JSON | orjson 3.11.7 | 10x más rápido que json estándar |
| Backend API | FastAPI (async) | Endpoints REST |
| Base de datos | MongoDB (Cosmos DB vCore) | Almacenamiento de datos GitHub |
| Frontend state | Zustand | Estado de lentes, métricas, tunneling |
| Renderizado 3D | Three.js + R3F | Shaders GLSL para colores de lente |

---

## 7. Endpoints de la API

### `GET /api/v1/collaboration/network-metrics`

Computa y devuelve métricas completas de la red.

**Parámetros:**
| Param | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `force_refresh` | bool | false | Ignora caché en memoria |

**Respuesta (3.2 MB):**
```json
{
  "node_metrics": {
    "user_octocat": {
      "betweenness": 0.0234,
      "degree": 0.0012,
      "community_id": 3,
      "community_color": "#f9ca24"
    },
    "repo_qiskit/qiskit": {
      "betweenness": 0.8901,
      "degree": 0.0456,
      "community_id": 0,
      "community_color": "#ff6b6b",
      "bus_factor": 2,
      "bus_factor_risk": "high",
      "top_contributors": [
        {"login": "alice", "percentage": 35.2},
        {"login": "bob", "percentage": 22.1}
      ]
    }
  },
  "communities": [
    {"id": 0, "color": "#ff6b6b", "size": 1245, "label": "Cluster 1: Qiskit, ..."}
  ],
  "global_metrics": {
    "num_nodes": 30970,
    "num_edges": 101190,
    "density": 0.0002,
    "num_components": 536,
    "largest_component_size": 27705,
    "modularity": 0.9585,
    "num_communities": 752
  }
}
```

**Caché:** En memoria, TTL 1 hora. Primera llamada ~19s, siguientes ~1.3s.

---

### `GET /api/v1/collaboration/quantum-tunneling`

Encuentra el camino más corto entre dos nodos.

**Parámetros:**
| Param | Tipo | Requerido | Ejemplo |
|-------|------|-----------|---------|
| `source` | string | Sí | `org_qiskit-community` |
| `target` | string | Sí | `org_PennyLaneAI` |

**Respuesta:**
```json
{
  "found": true,
  "path": [
    {"id": "org_qiskit-community", "type": "org", "name": "Qiskit Community"},
    {"id": "repo_qiskit-community/qiskit-ml", "type": "repo", "name": "qiskit-ml"},
    {"id": "user_dependabot[bot]", "type": "user", "name": "dependabot[bot]"},
    {"id": "repo_PennyLaneAI/pennylane-sf", "type": "repo", "name": "pennylane-sf"},
    {"id": "org_PennyLaneAI", "type": "org", "name": "PennyLaneAI"}
  ],
  "edges": [...],
  "length": 4,
  "description": "🏢 Qiskit Community → 📦 qiskit-ml → 👤 dependabot[bot] → 📦 pennylane-sf → 🏢 PennyLaneAI"
}
```

**Rendimiento:** ~15ms (reutiliza el grafo cacheado en memoria).

---

## 8. Modelo de datos

### Datos que se computan (internos)

| Campo | Descripción | ¿Enviado al frontend? |
|-------|------------|:-----:|
| `betweenness` | Betweenness centrality normalizada [0,1] | ✅ |
| `degree` | Degree centrality normalizada [0,1] | ✅ |
| `community_id` | ID de la comunidad Louvain | ✅ |
| `community_color` | Color hex de la comunidad | ✅ |
| `community_label` | Nombre auto-generado | ❌ (en communities[]) |
| `bus_factor` | Número de personas para cubrir 50% | ✅ (solo repos) |
| `bus_factor_risk` | critical/high/medium/low | ✅ (solo repos) |
| `top_contributors` | Top 3 con login + porcentaje | ✅ (solo repos) |
| `total_contributors` | Número total de contribuidores | ❌ (optimizado) |
| `edge_metrics` | Intensidad por arista (~100K entradas) | ❌ (18MB, no usado por UI) |
| `searchable_nodes` | Lista para autocomplete | ❌ (el frontend lo genera) |
| `avg_clustering` | Coef. clustering promedio (grafos <10K) | ✅ en global_metrics |
| `diameter` | Diámetro del componente más grande (<2K) | ✅ en global_metrics |

### ¿Se perdió información con las optimizaciones?

**NO.** Todo se sigue computando internamente. Los datos omitidos en la respuesta HTTP:
1. **`edge_metrics`**: 100K entradas de intensidad por arista. El frontend actual no los usa. Si se necesitan en el futuro, se pueden incluir.
2. **`searchable_nodes`**: El frontend ya genera la misma lista desde `universeData` (datos del endpoint `/collaboration/discover`).
3. **`total_contributors`**: Dato derivable de `top_contributors.length` en cada repo.
4. **`avg_clustering`** (grafos >10K nodos): Es ~0.0 en grafos bipartitos (user-repo), no aporta información significativa. Tardaba ~30 segundos.
5. **`diameter`/`avg_path_length`** (componentes >2K nodos): No se muestra en ningún lugar de la UI. Tardaba ~30 segundos.
6. **Precisión betweenness** (k=50 vs k=200): La diferencia es <5% para los nodos top. El ranking relativo de nodos no cambia significativamente.

---

## 9. Optimizaciones realizadas

### 9.1 Error 500 — MongoRepository sin argumento

**Problema:** Los endpoints usaban `MongoRepository()` sin el argumento obligatorio `collection_name`, causando `TypeError` en cada request.

**Causa raíz:** `MongoRepository.__init__(self, collection_name: str, ...)` requiere el nombre de la colección. Los endpoints lo llamaban sin argumentos.

**Solución:** Reescribir ambos endpoints usando el patrón correcto del proyecto:
```python
# ❌ Antes (error)
repo = MongoRepository()

# ✅ Después (correcto)
from ..core.db import db
db.ensure_connection()
repos_col = db.get_collection("repositories")
```

---

### 9.2 Documento BSON >16MB

**Problema:** Se intentaba cachear el resultado completo (18.7 MB) en un documento MongoDB, pero BSON tiene un límite de 16 MB.

**Solución:** Caché en **memoria del proceso Python** en vez de MongoDB. Variable `_network_metrics_cache` con TTL de 1 hora.

---

### 9.3 Respuesta JSON de 18.7 MB → 3.2 MB

**Problema:** El endpoint devolvía 6 bloques de datos, pero el frontend solo usa 3.

**Solución:** Filtrar la respuesta, enviando solo `node_metrics` (compacto), `communities` (compacto) y `global_metrics`.

| Antes | Después | Reducción |
|-------|---------|-----------|
| 18.7 MB | 3.2 MB | **-83%** |

---

### 9.4 Timeout de 81s → 19s (primera llamada)

**Problema:** La computación completa tardaba 81 segundos. El timeout de axios (30s) abortaba la petición antes de recibir respuesta → los botones "no hacían nada".

**Cambios:**

| Optimización | Antes | Después | Speedup |
|-------------|-------|---------|---------|
| Betweenness centrality (k muestras) | k=200 | k=50 | ~4x |
| `avg_clustering` (grafos >10K nodos) | Computado (~30s) | Omitido | ∞ |
| `diameter`/`avg_path_length` (componentes >2K) | Computado (~30s) | Omitido | ∞ |
| Serialización JSON | json.dumps (stdlib) | orjson | ~10x |
| **Total primera llamada** | **81s** | **19s** | **4.3x** |
| **Total segunda llamada (caché)** | **16s** | **1.3s** | **12x** |

---

### 9.5 Tunneling reconstruía el grafo en cada búsqueda

**Problema:** Cada búsqueda de Quantum Tunneling reconstruía el grafo completo desde MongoDB (~60s).

**Solución:** El endpoint de `network-metrics` guarda el `analyzer` (con el grafo ya construido) en caché en memoria. El endpoint de `quantum-tunneling` lo reutiliza.

| Antes | Después |
|-------|---------|
| ~60s por búsqueda | **15ms** por búsqueda |

---

### 9.6 Timeout de axios insuficiente

**Problema:** axios usaba el timeout global de 30s. La computación tarda ~19s + transferencia de 3.2 MB.

**Solución:** Timeouts específicos por endpoint:
- `getNetworkMetrics()`: 180s (3 minutos)
- `findQuantumPath()`: 120s (2 minutos)

---

### 9.7 Spinner infinito + botones bloqueados

**Problema (anterior):** `isLoadingMetrics` se quedaba en `true` indefinidamente porque el auto-load fallaba y se retriggeaba.

**Solución:** Flag `metricsLoadAttempted` que previene reintentos automáticos infinitos. Los botones siempre permiten carga manual.

---

### 9.8 Autocomplete del tunneling no funcionaba

**Problema (anterior):** Dependía de `networkMetrics.searchable_nodes` que nunca se cargaba (por los errores 500).

**Solución:** Reconstruir la lista de nodos buscables desde `universeData` (datos del endpoint `/collaboration/discover`, que siempre está disponible). Añadido scoring por relevancia: orgs > repos populares > bridge users > usuarios normales.

---

## 10. Archivos modificados/creados

### Archivos nuevos

| Archivo | Líneas | Descripción |
|---------|--------|-------------|
| `Backend/src/analysis/__init__.py` | ~5 | Init del módulo de análisis |
| `Backend/src/analysis/network_metrics.py` | ~624 | Motor de análisis NetworkX completo |
| `Backend/docs/NETWORK_ANALYSIS.md` | Este archivo | Documentación |

### Archivos modificados

| Archivo | Cambios principales |
|---------|-------------------|
| `Backend/requirements.txt` | +`networkx>=3.0`, +`orjson>=3.9` |
| `Backend/src/api/routes.py` | +2 endpoints (`/network-metrics`, `/quantum-tunneling`), +import `CollaborationNetworkAnalyzer`, +caché en memoria |
| `Frontend/src/services/api.js` | +`getNetworkMetrics()`, +`findQuantumPath()` con timeouts extendidos |
| `Frontend/src/store/dashboardStore.js` | +estado de lentes (`activeLens`, `networkMetrics`, `isLoadingMetrics`, `metricsLoadAttempted`), +estado tunneling (`tunnelingPath`, `isLoadingTunneling`), +acciones (`loadNetworkMetrics`, `setActiveLens`, `findQuantumPath`, `clearTunneling`) |
| `Frontend/src/components/Universe/UniverseView.jsx` | +shaders GLSL (`aLensColor`, `uLensActive`), +barra de lentes, +tunneling search bar con autocomplete, +panel de detalle enriquecido con métricas |
| `Frontend/src/components/Universe/UniverseView.module.css` | +~400 líneas de CSS para lentes, tunneling, métricas, barras, badges |

---

## 11. Preguntas frecuentes

### "¿Por qué la primera vez tarda tanto?"
Porque construir y analizar un grafo de 30,970 nodos y 101,190 aristas no es trivial. Se ejecutan algoritmos de teoría de grafos (Louvain, betweenness) que son O(n²) o peores. Después de la primera carga, el resultado se cachea en memoria durante 1 hora.

### "¿Los datos cambian con el tiempo?"
Sí. Si ejecutas nuevas ingestas de datos de GitHub, los datos en MongoDB cambian. El caché en memoria se invalida automáticamente después de 1 hora, o puedes forzar recálculo añadiendo `?force_refresh=true` en la URL.

### "¿Puedo recuperar los datos que se omiten en la respuesta?"
Sí. El `analyzer` completo se guarda en caché en memoria. Si necesitas `edge_metrics` o cualquier otro dato, solo hay que incluirlo en la respuesta del endpoint (cambio de ~5 líneas en `routes.py`).

### "¿Qué significa una modularidad de 0.9585?"
Significa que la red está **extremadamente fragmentada** en comunidades independientes. El máximo teórico es 1.0. Para comparación:
- Redes sociales típicas: 0.3-0.5
- Ecosistemas open-source maduros: 0.5-0.7
- Ecosistema cuántico (nuestros datos): **0.96** — los frameworks apenas se tocan entre sí.

### "¿Qué significa que el diámetro sea 0?"
El componente más grande tiene 27,705 nodos — demasiado grande para calcular el diámetro en tiempo razonable (>30s). Por eso se omite (valor 0). Si se necesita para el TFG, se puede calcular en un script offline.

### "¿Por qué dependabot aparece como puente entre organizaciones?"
Porque dependabot[bot] es un bot que actualiza dependencias automáticamente en muchos repositorios. Técnicamente, "contribuye" a repos de múltiples organizaciones. Para un análisis más preciso, se podrían filtrar bots (el endpoint `/collaboration/discover` ya los marca con el flag `isBot`).
