# Sistema de Configuración de Criterios de Ingesta

## 📋 Descripción

Sistema de configuración parametrizable para definir criterios de filtrado de repositorios de software cuántico. Permite modificar los parámetros sin cambiar el código fuente.

## 📁 Estructura

```
Backend/
├── config/
│   └── ingestion_config.json     # Criterios de filtrado
├── src/
│   └── core/
│       ├── config.py              # Clase IngestionConfig
│       └── logger.py              # Sistema de logging
└── test_ingestion_config.py      # Script de prueba
```

## 🔧 Archivo de Configuración

**Ubicación:** [`config/ingestion_config.json`](../config/ingestion_config.json )

### Estructura del JSON:

```json
{
  "description": "Configuración de criterios de ingesta para repositorios de software cuántico",
  "version": "1.0",
  "keywords": [
    "quantum",
    "qiskit",
    "braket",
    "cirq",
    "pennylane"
  ],
  "languages": [
    "Python",
    "C++",
    "Q#",
    "Rust"
  ],
  "min_stars": 10,
  "max_inactivity_days": 365,
  "exclude_forks": true,
  "min_contributors": 1,
  "additional_filters": {
    "has_topics": true,
    "has_readme": true,
    "min_size_kb": 10
  }
}
```

### Parámetros:

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `keywords` | List[str] | Palabras clave para identificar repos cuánticos |
| `languages` | List[str] | Lenguajes de programación permitidos |
| `min_stars` | int | Número mínimo de estrellas requeridas |
| `max_inactivity_days` | int | Máximos días de inactividad permitidos |
| `exclude_forks` | bool | Si se deben excluir forks |
| `min_contributors` | int | Número mínimo de contribuidores |
| `additional_filters` | dict | Filtros adicionales opcionales |

## 💻 Uso

### 1. Importar la configuración

```python
from src.core.config import ingestion_config

# Acceder a los criterios
keywords = ingestion_config.keywords
languages = ingestion_config.languages
min_stars = ingestion_config.min_stars
```

### 2. Usar propiedades

```python
# Obtener keywords
for keyword in ingestion_config.keywords:
    print(keyword)

# Obtener criterios numéricos
if repo_stars >= ingestion_config.min_stars:
    print("Repositorio válido")

# Verificar exclusión de forks
if ingestion_config.exclude_forks and is_fork:
    print("Repositorio excluido (es fork)")
```

### 3. Obtener toda la configuración

```python
# Como diccionario
config_dict = ingestion_config.get_all_config()

# Información
print(ingestion_config.description)
print(ingestion_config.version)
```

### 4. Recargar configuración

```python
# Si se modificó el JSON, recargar
ingestion_config.reload()
```

## 🧪 Pruebas

### Ejecutar script de prueba:

```powershell
# Desde la raíz del proyecto
python test_ingestion_config.py
```

### Salida esperada:

```
======================================================================
  PRUEBA DE CONFIGURACIÓN DE INGESTA
======================================================================

📋 Información General:
  - Descripción: Configuración de criterios de ingesta...
  - Versión: 1.0
  - Archivo: config\ingestion_config.json

======================================================================
  KEYWORDS (Palabras Clave)
======================================================================

📌 Total de keywords: 12
  1. quantum
  2. qiskit
  ...

✅ Configuración cargada y validada exitosamente
```

## ⚠️ Manejo de Errores

La clase `IngestionConfig` valida automáticamente:

1. **Archivo no encontrado**: `FileNotFoundError`
2. **JSON inválido**: `ValueError`
3. **Campos ausentes**: `ValueError`
4. **Tipos incorrectos**: `TypeError`
5. **Valores negativos**: `ValueError`

Todos los errores se registran en [`logs/errors.log`](../logs/errors.log )

### Ejemplo:

```python
try:
    config = IngestionConfig(config_path="ruta/inexistente.json")
except FileNotFoundError as e:
    print(f"Error: {e}")
    # Se registra automáticamente en logs
```

## 🔄 Modificar Configuración

1. Editar [`config/ingestion_config.json`](../config/ingestion_config.json )
2. Recargar configuración:
   ```python
   ingestion_config.reload()
   ```

### Ejemplo de modificación:

```json
{
  "keywords": ["quantum", "qiskit", "nuevo_framework"],
  "min_stars": 20,
  "exclude_forks": false
}
```

## 📊 Propiedades Disponibles

| Propiedad | Tipo | Descripción |
|-----------|------|-------------|
| `keywords` | List[str] | Lista de palabras clave |
| `languages` | List[str] | Lista de lenguajes |
| `min_stars` | int | Estrellas mínimas |
| `max_inactivity_days` | int | Días máximos de inactividad |
| `exclude_forks` | bool | Excluir forks |
| `min_contributors` | int | Contribuidores mínimos |
| `additional_filters` | dict | Filtros adicionales |
| `description` | str | Descripción del config |
| `version` | str | Versión del config |

## 🎯 Próximos Pasos

Este módulo sirve como base para:

1. **Motor de filtrado**: Aplicar criterios a búsquedas GraphQL
2. **Validación de repos**: Verificar si un repo cumple criterios
3. **Re-ingesta**: Actualizar dataset con nuevos criterios
4. **Logs de filtrado**: Registrar decisiones de inclusión/exclusión

## 📝 Notas

- La configuración se carga **una vez** al importar el módulo
- Usar `reload()` para actualizar sin reiniciar la aplicación
- Los valores por defecto están en las propiedades de la clase
- Todos los errores se registran con el logger centralizado
