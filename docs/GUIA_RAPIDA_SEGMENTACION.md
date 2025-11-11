# 🚀 Guía Rápida: Ingesta con Segmentación Dinámica

## ⚡ Inicio Rápido (5 minutos)

### 1. Verificar Requisitos

```bash
# Verificar Python
python --version  # Python 3.8+

# Verificar MongoDB
# MongoDB debe estar corriendo en localhost:27017

# Verificar token de GitHub
# GITHUB_TOKEN debe estar en .env
```

### 2. Configuración (Ya está lista)

El archivo `config/ingestion_config.json` ya está configurado con:
- ✅ Segmentación habilitada
- ✅ 6 rangos de estrellas
- ✅ 11 años de creación (2015-2025)
- ✅ Control de rate limit

**No necesitas modificar nada** para empezar.

### 3. Ejecutar Ingesta Segmentada

```bash
cd scripts
python run_ingestion_segmented.py
```

### 4. Confirmar y Esperar

```
📊 Configuración de Segmentación:
  • Rangos de estrellas: 6
  • Años de creación: 11
  • Total de consultas estimadas: 66
  • Repositorios estimados: 66,000 (máximo teórico)

¿Deseas continuar con la ingesta segmentada? [s/N]: s  ← Escribe 's' y Enter
```

Tiempo estimado: **30-60 minutos**

---

## 📊 Monitoreo en Tiempo Real

Durante la ejecución verás:

```
📍 Consulta 5/66: stars:50..99 year:2016
  ✓ Encontrados: 342 repos, 298 nuevos
  📊 Total acumulado: 1,234 repos únicos
  
⏳ Rate limit: 4532/5000 restantes
```

---

## 🎯 Resultados

### Archivo JSON
**Ubicación**: `results/ingestion_segmented_results.json`

```json
{
  "metadata": {
    "total_repositories": 5432,
    "ingestion_date": "2025-10-30T...",
    "statistics": {
      "repositories_inserted": 4829,
      "repositories_updated": 603,
      "relations_created": 5432
    }
  },
  "repositories": [...]
}
```

### MongoDB
**Base de datos**: `quantum_github`

**Colecciones**:
- `repositories` → Repositorios ingresados
- `organizations` → Propietarios
- `users` → Colaboradores
- `relations` → Relaciones entre entidades

### Verificar en MongoDB

```bash
# Conectar a MongoDB
mongosh

# Usar la base de datos
use quantum_github

# Contar repositorios
db.repositories.countDocuments()

# Ver ejemplo
db.repositories.findOne()
```

---

## 🔧 Opciones Avanzadas

### Solo Testear (Sin Segmentación)

```bash
python tests/test_segmentation.py
```

Resultado: 50 repos en ~10 segundos

### Ingesta Simple (Límite 1000)

Si quieres la ingesta tradicional sin segmentación:

1. Editar `config/ingestion_config.json`:
   ```json
   {
     "enable_segmentation": false
   }
   ```

2. Ejecutar:
   ```bash
   python scripts/run_ingestion.py
   ```

### Configuración Personalizada

Editar `config/ingestion_config.json`:

```json
{
  "segmentation": {
    "stars": [
      [100, 499],    // Solo repos con 100-499 estrellas
      [500, 999]     // Y repos con 500-999 estrellas
    ],
    "created_years": [2023, 2024, 2025]  // Solo repos recientes
  }
}
```

Esto reduce: 2 rangos × 3 años = **6 consultas** (~5 minutos)

---

## 🐛 Solución de Problemas

### Rate Limit Agotado

**Síntoma**:
```
⏳ Rate limit bajo (45 restantes). Esperando hasta reset...
```

**Solución**: El sistema espera automáticamente. No interrumpir.

### Error de MongoDB

**Síntoma**:
```
Error: No se puede conectar a MongoDB
```

**Solución**:
```bash
# Iniciar MongoDB (Windows)
net start MongoDB

# O manualmente
"C:\Program Files\MongoDB\Server\7.0\bin\mongod.exe" --dbpath="C:\data\db"
```

### Token de GitHub Inválido

**Síntoma**:
```
Error: GITHUB_TOKEN no está configurado
```

**Solución**:
1. Crear archivo `.env` en la raíz
2. Agregar: `GITHUB_TOKEN=ghp_tu_token_aqui`
3. Obtener token en: https://github.com/settings/tokens

### Sin Resultados

**Síntoma**:
```
✅ Búsqueda segmentada completada:
  • Repositorios únicos obtenidos: 0
```

**Causas posibles**:
- Configuración muy restrictiva (ej: `min_stars: 10000`)
- Años sin actividad (ej: solo 2015)
- Keywords muy específicas

**Solución**: Revisar `config/ingestion_config.json`

---

## 📈 Siguiente Paso: Enrichment

Después de la ingesta, ejecutar enrichment:

```bash
python scripts/run_enrichment.py
```

Esto agregará:
- Colaboradores de cada repo
- Revisores de pull requests
- Métricas de contribución
- Relaciones completas

---

## 📚 Documentación Completa

- **Segmentación Dinámica**: [`docs/SEGMENTACION_DINAMICA.md`](../docs/SEGMENTACION_DINAMICA.md)
- **Implementación**: [`docs/IMPLEMENTACION_SEGMENTACION.md`](../docs/IMPLEMENTACION_SEGMENTACION.md)
- **Filtros Avanzados**: [`docs/filtros_avanzados_resumen.md`](../docs/filtros_avanzados_resumen.md)
- **Motor de Ingesta**: [`docs/ingestion_engine_guide.md`](../docs/ingestion_engine_guide.md)

---

## ❓ FAQ

**P: ¿Cuánto tarda la ingesta completa?**  
R: Con 66 consultas, entre 30-60 minutos dependiendo del rate limit.

**P: ¿Puedo interrumpir y continuar después?**  
R: Sí, MongoDB evita duplicados con `upsert`. Solo se reinsertarán los nuevos.

**P: ¿Cuántos repositorios obtendré?**  
R: Depende de tu configuración. Con la configuración por defecto, entre 5,000-15,000.

**P: ¿Consume mucha memoria?**  
R: No, los repositorios se procesan en lotes de 50. Uso típico: ~500MB RAM.

**P: ¿Puedo ejecutar en paralelo?**  
R: No recomendado por rate limit. Mejor ejecutar secuencialmente.

---

## ✅ Checklist Pre-Ejecución

- [ ] MongoDB corriendo
- [ ] Token de GitHub configurado (`.env`)
- [ ] Configuración revisada (`config/ingestion_config.json`)
- [ ] Espacio en disco (al menos 1GB libre)
- [ ] Conexión a internet estable

---

**Listo para ejecutar**: `python scripts/run_ingestion_segmented.py` 🚀
