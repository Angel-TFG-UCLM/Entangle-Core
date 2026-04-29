# Auditoría del Dataset `quantum_github` — Informe Completo

> **Fecha:** 27 de febrero de 2026  
> **Estado:** Pendiente de decisiones del usuario  
> **Dataset:** 1688 repos | 191,094 estrellas | 28,246 users | 469 orgs

---

## 1. Problema Principal: Solo se usa 1 keyword de 72

### Causa raíz

El método `search_repositories_segmented()` en `src/github/graphql_client.py` (líneas 624-626) hardcodea la primera keyword del config:

```python
main_keyword = config.keywords[0]   # → "quantum"
query_parts.append(main_keyword)
```

La query enviada a GitHub es: `quantum stars:X..Y created:YEAR fork:false`

### Consecuencias

- **Falsos positivos:** Cualquier repo con "quantum" en nombre/descripción/README se encuentra, sin importar el contexto (QuantumultX, Firefox Quantum, bloomberg/quantum, etc.)
- **Falsos negativos:** Repos QC legítimos que usan `qiskit`, `cirq`, `braket`, `pennylane` en su nombre/descripción pero NO contienen la palabra "quantum" nunca se encuentran.

### Dónde se usan realmente las 72 keywords

Solo en el filtro post-búsqueda `matches_keywords()` de `src/github/filters.py` (líneas 271-309). Pero como GitHub ya filtró por "quantum", casi todos los repos contienen "quantum", así que el filtro casi nunca rechaza nada.

### Código alternativo no utilizado

Existe `_build_search_query()` (líneas 327-365 de `graphql_client.py`) con modo avanzado que usa las primeras 5 keywords con OR (`quantum OR qiskit OR braket OR cirq OR pennylane`), pero el flujo de ingesta segmentado **nunca lo llama**.

### Fix propuesto

Modificar `search_repositories_segmented()` para usar múltiples keywords con OR, o ejecutar búsquedas adicionales con keywords como `qiskit`, `cirq`, `pennylane`, `braket`, `pyquil` como término principal (una búsqueda segmentada por cada keyword importante).

---

## 2. Filtro de Inactividad Defectuoso

### Causa raíz

El filtro `is_active()` en `src/github/filters.py` (línea 97) usa:

```python
updated_at_str = repo.get("updatedAt") or repo.get("pushedAt")
```

`updatedAt` tiene **prioridad** sobre `pushedAt`. Pero `updatedAt` se actualiza por CUALQUIER actividad de GitHub:

- Alguien da una **estrella** → `updatedAt` se actualiza
- Se abre/cierra un **issue** → `updatedAt` se actualiza
- Se hace un **comentario** → `updatedAt` se actualiza
- Se **transfiere** el repo → `updatedAt` se actualiza
- Se modifica la **descripción/topics** → `updatedAt` se actualiza

### Consecuencia

Un repo sin push desde 2021 puede tener `updatedAt: 2025-01-15` porque alguien le dio una estrella recientemente. Esto explica por qué 655 repos QC legítimos están inactivos (sin código nuevo) pero pasaron el filtro de actividad.

### Fix propuesto

Cambiar a usar `pushedAt` como indicador primario:

```python
updated_at_str = repo.get("pushedAt") or repo.get("updatedAt")
```

---

## 3. Resultados de la Auditoría

### Tabla resumen

| Categoría | Repos | Estrellas | % Repos | % Estrellas |
|---|---|---|---|---|
| **QC Legítimo** | 1,305 | 121,000 | 77.3% | 63.3% |
| **QuantumultX (proxy iOS)** | 53 | 35,186 | 3.1% | 18.4% |
| **Firefox Quantum** | 9 | 1,547 | 0.5% | 0.8% |
| **Non-QC conocido** | 9 | 7,749 | 0.5% | 4.1% |
| **Post-quantum crypto** | 88 | 14,144 | 5.2% | 7.4% |
| **Sospechoso (sin keywords QC)** | 224 | 11,468 | 13.3% | 6.0% |

### Falsos Positivos Claros (71 repos, 44,482 estrellas)

#### QuantumultX (53 repos, 35,186⭐)
App proxy para iOS popular en China. Scripts JavaScript para configuración de VPN/proxy. Nada que ver con computación cuántica. Todos contienen "quantumult" en nombre.

Ejemplos top:
- `w37fhy/QuantumultX` (5,830⭐) — scripts de proxy
- `Orz-3/QuantumultX` (4,482⭐) — configuraciones
- `sve1r/Rules-For-Quantumult-X` (3,732⭐) — reglas de filtrado

#### Firefox Quantum (9 repos, 1,547⭐)
Extensiones y customizaciones para Firefox Quantum (rebrand de Firefox 57+).

Ejemplos:
- `mozilla/FirefoxColor` (489⭐) — temas para Firefox Quantum
- `Izheil/Quantum-Nox-Firefox-Customizations` (417⭐) — CSS/JS customizations
- `louisabraham/ffpass` (382⭐) — importar passwords de Firefox Quantum

#### Non-QC conocido (9 repos, 7,749⭐)
Repos que usan "quantum" como nombre de marca sin relación con QC.

- `sahibzada-allahyar/YC-Killer` (2,662⭐) — AI agents enterprise
- `joaomilho/Enterprise` (1,619⭐) — lenguaje de programación satírico
- `nashvail/Quttons` (628⭐) — botones CSS "Quantum Paper"
- `bloomberg/quantum` (626⭐) — coroutine dispatcher C++
- `foxyproxy/firefox-extension` (534⭐) — extensión Firefox
- `atilafassina/quantum` (523⭐) — Tauri + SolidStart (alternativa a Electron)
- `RafaelGoulartB/next-ecommerce` (483⭐) — "Quantum Ecommerce" Next.js
- `rodyherrera/Quantum` (471⭐) — alternativa a Vercel/Heroku
- `quantumui/quantumui` (203⭐) — UI framework AngularJS

### Categorías Debatibles

#### Post-quantum crypto (88 repos, 14,144⭐)
Criptografía resistente a ataques de computadores cuánticos. Son "quantum-adjacent" pero no computación cuántica directa. Usan algoritmos clásicos diseñados para resistir algoritmos cuánticos.

Top repos:
- `QuipNetwork/hashsigs-rs` (3,777⭐) — firmas hash post-quantum en Rust
- `open-quantum-safe/liboqs` (2,775⭐) — librería C de cripto post-quantum
- `rosenpass/rosenpass` (1,317⭐) — VPN post-quantum con WireGuard
- `PQClean/PQClean` (871⭐) — implementaciones limpias de PQC

**Decisión pendiente:** ¿Están dentro del alcance del TFG o no? Son software que existe PORQUE existen los computadores cuánticos, pero no son software cuántico per se.

#### Sospechosos sin keywords QC (224 repos, 11,468⭐)
Contienen "quantum" en nombre/descripción pero ningún keyword específico de QC (qiskit, cirq, qubit, superposition, etc.).

Es una mezcla — algunos son QC legítimo con terminología no estándar, otros no tienen nada que ver:

**Probablemente legítimos (pero sin keywords estándar):**
- `gdsfactory/gdsfactory` (860⭐) — diseño de chips fotónicos/cuánticos
- `netket/netket` (666⭐) — ML para sistemas cuánticos many-body
- `dynamiqs/dynamiqs` (272⭐) — simulación de sistemas cuánticos con JAX
- `qLDPCOrg/qLDPC` (206⭐) — códigos quantum LDPC
- `quantumgizmos/ldpc` (189⭐) — decodificación de códigos cuánticos y clásicos
- `SunnySuite/Sunny.jl` (136⭐) — dinámica de espín cuántico
- `ichuang/pyqsp` (131⭐) — quantum signal processing en Python

**Probablemente falsos positivos:**
- `ReactQuantum/ReactQuantum` (184⭐) — visualización de performance React
- `Mrmayman/quantumlauncher` (155⭐) — launcher de Minecraft
- `Heydon/beadz-drum-machine` (143⭐) — drum machine "quantum"
- `kareldonk/QuantumGate` (116⭐) — protocolo P2P C++
- `fox-it/quantuminsert` (214⭐) — herramienta de seguridad NSA

### Repos QC Legítimos — Estado de Actividad

| Métrica | Valor |
|---|---|
| Total legítimos | 1,305 repos (121,000⭐) |
| Activos (push < 1 año) | 650 repos (86,278⭐) |
| Inactivos (push > 1 año) | 655 repos (34,722⭐) |

Distribución de inactivos por año de último push:
- 2024: 155 repos (push hace 1-2 años)
- 2023: 136 repos
- 2022: 93 repos
- 2021: 90 repos
- 2020: 62 repos
- 2019: 40 repos
- 2018: 22 repos
- 2017: 5 repos
- 2016: 8 repos

Top repos QC legítimos inactivos:
- `OriginQ/QPanda-2` (1,166⭐)
- `quantum-visualizations/qmsolve` (1,131⭐)
- `JackHidary/quantumcomputingbook` (910⭐)
- `Lumorti/Quandoom` (905⭐)

---

## 4. Propuesta de Filtro para Sospechosos

### Nuevo filtro #10: Verificación de Relevancia Contextual

Para repos que SOLO matchean la keyword genérica "quantum" (sin qiskit, cirq, qubit, etc.), aplicar verificación adicional:

#### A) Blacklist de contextos no-QC

```python
NON_QC_PATTERNS = [
    r"quantumult",           # Proxy iOS
    r"firefox[\s._-]*quantum", # Firefox Quantum
    r"quantum[\s._-]*paper",   # CSS/UI (Material Design)
    r"quantum[\s._-]*ui",      # UI frameworks
    r"minecraft",              # Gaming
    r"drum[\s._-]*machine",    # Music
    r"ecommerce|e-commerce",   # E-commerce
    r"coroutine|dispatcher",   # bloomberg/quantum
    r"vercel|heroku|netlify",  # Hosting alternatives
    r"react[\s._-]*quantum",   # React performance tools
    r"hackbar",                # Security tools
    r"foxyproxy|proxy.*app",   # Proxy tools
]
```

#### B) Lista de keywords QC reales para validación

```python
REAL_QC_KEYWORDS = [
    # Frameworks
    "qiskit", "cirq", "pennylane", "braket", "pyquil", "projectq",
    "strawberry fields", "ocean", "openqasm", "qasm", "quil",
    # Conceptos core
    "qubit", "qubits", "superposition", "entanglement", "decoherence",
    "quantum gate", "quantum circuit", "quantum state", "bloch sphere",
    "hamiltonian", "unitary", "hermitian", "density matrix",
    # Algoritmos
    "grover", "shor", "vqe", "qaoa", "qft", "quantum fourier",
    "quantum walk", "quantum annealing", "adiabatic",
    # Hardware
    "quantum processor", "quantum computer", "qpu", "nisq",
    "fault.tolerant", "topological quantum", "trapped.ion",
    "superconducting qubit", "transmon",
    # Campos
    "quantum machine learning", "quantum chemistry", "quantum simulation",
    "quantum error correction", "quantum key distribution", "qkd",
    "quantum teleportation", "quantum cryptography",
    # Proveedores
    "ibm quantum", "google quantum", "azure quantum", "aws quantum",
    "rigetti", "ionq", "d-wave", "xanadu", "zapata",
]
```

#### C) Lógica del filtro

```
Si el repo matchea "quantum" Y al menos 1 keyword QC específica → PASA
Si el repo matchea solo "quantum" sin ninguna keyword QC:
  → Si matchea algún patrón de la blacklist → RECHAZA
  → Si tiene topics relacionados con QC → PASA
  → Si tiene ≥2 señales de contexto QC en README (1000 chars) → PASA
  → En otro caso → RECHAZA
```

---

## 5. Archivos a Modificar (cuando se decida actuar)

| Archivo | Cambio | Impacto |
|---|---|---|
| `src/github/graphql_client.py` L624-626 | Usar múltiples keywords en búsqueda segmentada | Encuentra repos con qiskit/cirq/etc. que no dicen "quantum" |
| `src/github/filters.py` L97 | Cambiar `updatedAt` → `pushedAt` como primario | Filtro de actividad basado en código real, no estrellas |
| `src/github/filters.py` (nuevo) | Añadir filtro de relevancia contextual (#10) | Elimina falsos positivos de "quantum" genérico |
| `config/ingestion_config.json` | Posible campo `exclude_patterns` con blacklist | Configuración externalizada |
| Base de datos | Eliminar 71 FP claros + lo que se decida | Limpieza del dataset actual |

---

## 6. Decisiones Pendientes del Usuario

1. **FP claros (71 repos, 44,482⭐):** ¿Eliminar de la BD?
2. **Post-quantum crypto (88 repos, 14,144⭐):** ¿Dentro del alcance del TFG o no?
3. **Sospechosos (224 repos, 11,468⭐):** ¿Implementar filtro de relevancia contextual?
4. **Inactivos legítimos (655 repos, 34,722⭐):** ¿Mantener como históricos? (Decisión actual: SÍ mantener)
5. **Búsqueda multi-keyword:** ¿Re-ingestar con búsquedas adicionales por qiskit/cirq/etc.?
6. **Fix `is_active`:** ¿Aplicar inmediatamente el cambio a `pushedAt`?

---

## 7. Script de Auditoría

El script `scripts/audit_dataset.py` permite re-ejecutar esta auditoría en cualquier momento:

```bash
cd Backend
python scripts/audit_dataset.py
```

Clasifica cada repo en las categorías anteriores y genera un informe con tablas.
