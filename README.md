# Análisis de patrones de colaboración en proyectos de software cuántico

## Descripción general

Este proyecto forma parte del Trabajo Fin de Grado en Ingeniería Informática y tiene como objetivo estudiar cómo colaboran los desarrolladores dentro del ecosistema del **software cuántico de código abierto**.

---

## Objetivos del proyecto

El objetivo general es estudiar los patrones de colaboración entre desarrolladores en proyectos de software cuántico alojados en GitHub.

### Fases del proyecto:

1. **Ingesta y filtrado de datos**: Construcción de un dataset base de repositorios cuánticos relevantes mediante la API de GitHub.
2. **Enriquecimiento y modelado**: Expansión de la información con datos de organizaciones, repositorios y usuarios interrelacionados.
3. **Análisis de colaboración**: Aplicación de técnicas de análisis de redes sociales sobre los datos obtenidos.

---

## Contexto y motivación

El software cuántico es un campo emergente con una comunidad activa de desarrolladores. Este proyecto busca comprender cómo colaboran los desarrolladores en este ecosistema para identificar patrones, comunidades clave y oportunidades de mejora en la colaboración.

---

## Enfoque general

El proyecto se desarrollará en varias fases:

1. **Recolección de datos** desde los repositorios más relevantes de software cuántico en GitHub.
2. **Enriquecimiento** con información de organizaciones y desarrolladores.
3. **Análisis de redes** para identificar patrones de colaboración.

### Base de datos (MongoDB)

Los datos se almacenarán en MongoDB con la siguiente estructura:

- **organizations**: Información de organizaciones propietarias de repositorios
- **repositories**: Proyectos de software cuántico
- **users**: Colaboradores y desarrolladores principales

---

## 🧭 Estado actual

**Sprint 2: Sistema de Ingesta Parametrizable y Extensible**

Sistema completo de ingesta de repositorios de software cuántico desde GitHub con filtrado dinámico y almacenamiento flexible.

### ✅ Completado:
- ✅ **Sistema de configuración** ([`config/ingestion_config.json`](config/ingestion_config.json))
  - Clase `IngestionConfig` para carga y validación dinámica
  - Criterios parametrizables: keywords, lenguajes, estrellas, inactividad
  
- ✅ **Cliente GraphQL de GitHub** ([`src/github/graphql_client.py`](src/github/graphql_client.py))
  - Búsqueda parametrizable con construcción dinámica de queries
  - Control automático de rate limit
  - Paginación automática
  
- ✅ **Motor de ingesta** ([`src/github/ingestion.py`](src/github/ingestion.py))
  - Orquestación completa del flujo: búsqueda → filtrado → almacenamiento
  - Sistema de **9 filtros avanzados** integrado
  - Almacenamiento dual: MongoDB + JSON
  - Reportes con estadísticas detalladas
  
- ✅ **Filtros avanzados de calidad** ([`src/github/filters.py`](src/github/filters.py))
  - ⏰ Actividad reciente (max_inactivity_days)
  - 🔀 Forks válidos (con contribuciones propias)
  - 📝 Documentación (descripción o README obligatorios)
  - 📦 Tamaño mínimo (commits y KB)
  - 🔬 Keywords cuánticas (nombre, descripción, topics, README)
  - 💻 Lenguaje válido (lista configurable)
  - 📂 No archivado
  - ⭐ Estrellas mínimas
  - 👥 Engagement de comunidad (watchers/forks)
  
- ✅ **Sistema de logging** ([`src/core/logger.py`](src/core/logger.py))
  - Múltiples handlers: console, app.log, errors.log, debug.log
  - Trazabilidad completa del proceso
  
- ✅ **Suite de pruebas** ([`tests/`](tests/))
  - test_ingestion_config.py - Validación de configuración
  - test_github_client_complete.py - Cliente GraphQL
  - test_ingestion.py - Motor de ingesta (6/6 tests ✓)
  - test_filters.py - Filtros avanzados (10/10 tests ✓ 100%)

### 📊 Resultados de pruebas:
- **Total repositorios encontrados**: 2519 (query cuántica en GitHub)
- **Tasa de éxito filtrado**: 80-87% (según criterios)
- **Lenguajes principales**: Python (90%+), C++, Julia, Rust
- **Ejemplos**: Qiskit (6561⭐), Cirq (4724⭐), PennyLane (2838⭐)

---

## 🧑‍💻 Autor

**Autor:** Ángel Luis Lara Martín
**Tutorizado por:** Ricardo Pérez del Castillo
**Grado:** Ingeniería Informática  
**Universidad:** Universidad de Castilla La-Mancha
**Año:** 2025
