# Tests - Backend TFG

Suite de tests reorganizada para validar todos los componentes del sistema.

## 📁 Estructura

```
tests/
├── conftest.py              # Configuración pytest y fixtures compartidas
├── test_api.py              # Tests de endpoints REST
├── test_repositories.py     # Tests de ingesta/enriquecimiento de repos + filtros
├── test_users.py            # Tests de ingesta/enriquecimiento de usuarios
├── test_organizations.py    # Tests de ingesta/enriquecimiento de organizaciones
└── test_database.py         # Tests de conexiones y operaciones DB
```

## 🚀 Ejecutar Tests

### Tests unitarios (con mocks)
```bash
pytest tests/ -v
```

### Tests de integración (requiere MongoDB + GitHub Token)
```bash
pytest tests/ -v --integration
```

### Tests de API (usan TestClient de FastAPI)
```bash
# Los tests de API usan TestClient y se ejecutan automáticamente
pytest tests/test_api.py -v
```

### Tests específicos
```bash
# Solo tests de repositorios
pytest tests/test_repositories.py -v

# Solo tests de usuarios
pytest tests/test_users.py -v

# Solo tests de organizaciones
pytest tests/test_organizations.py -v

# Solo tests de base de datos
pytest tests/test_database.py -v
```

### Tests con cobertura
```bash
pytest tests/ -v --cov=src --cov-report=html
```

## 📊 Tipos de Tests

### 🧪 Unitarios (Mocks)
- **No requieren** servicios externos
- Usan mocks para GitHub API y MongoDB
- **Rápidos** (~segundos)
- Se ejecutan por defecto

**Ejemplo:**
```python
def test_repository_validation(self):
    """Verifica la validación de modelos Pydantic."""
    valid_data = {
        "full_name": "user/repo",
        "owner_login": "user",
        "stars": 100
    }
    repo = Repository(**valid_data)
    assert repo.stars == 100
```

### 🔗 Integración (Real)
- **Requieren** MongoDB y GitHub Token
- Usan servicios reales
- **Lentos** (~minutos)
- Se ejecutan con `--integration`

**Ejemplo:**
```python
@pytest.mark.integration
def test_full_pipeline_with_real_db(self):
    """Test de integración con base de datos real."""
    engine = RepositoryIngestionEngine(...)
    stats = engine.ingest(max_results=2)
    assert stats["total_extracted"] >= 0
```

### 🌐 API (TestClient)
- **No requieren** servidor ejecutándose
- Usan TestClient de FastAPI (levanta la app automáticamente)
- **Rápidos** (~segundos)
- Se ejecutan por defecto

**Ejemplo:**
```python
def test_health_check(self, client):
    """Verifica que el endpoint de health responda."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
```

## 🎯 Cobertura de Tests

### test_repositories.py
✅ Filtros de calidad (archived, inactive, language, stars)  
✅ Ingesta de repositorios (extracción, validación, persistencia)  
✅ Enriquecimiento (README, contributors, releases, commits)  
✅ Validación de modelos Pydantic  

### test_users.py
✅ Descubrimiento desde repositorios  
✅ Detección de bots  
✅ Ingesta de usuarios  
✅ Enriquecimiento con super-query v3.0  
✅ Cálculo de quantum_expertise_score  
✅ Extracción de top_languages y pinned_repos  

### test_organizations.py
✅ Descubrimiento bottom-up desde usuarios  
✅ Detección de organizaciones relevantes  
✅ Ingesta de organizaciones  
✅ Enriquecimiento con quantum_score  
✅ Cálculo de prestige_score  
✅ Distribución de lenguajes  

### test_database.py
✅ Conexión y desconexión a MongoDB  
✅ Operaciones CRUD (create, read, update, delete)  
✅ Operaciones bulk (insert_many, bulk_upsert)  
✅ Manejo de duplicados  
✅ Context managers  

### test_api.py
✅ Health check endpoint  
✅ Rate limit endpoint  
✅ Listado de repositorios/usuarios/organizaciones  
✅ Obtención por ID  
✅ Filtros (language, min_stars)  
✅ Paginación (limit, skip)  

## 🔧 Configuración

### Variables de Entorno
```bash
# .env
GITHUB_TOKEN=ghp_your_token_here
MONGODB_URI=mongodb://localhost:27017
DATABASE_NAME=tfg_backend
```

### Requisitos
```bash
pip install pytest pytest-cov pytest-mock requests
```

## 📝 Marcadores Personalizados

```python
@pytest.mark.integration  # Test de integración (requiere servicios externos)
@pytest.mark.slow         # Test lento (>5 segundos)
```

## 🐛 Debugging

### Ver output completo
```bash
pytest tests/ -v -s
```

### Solo tests fallidos
```bash
pytest tests/ -v --lf
```

### Detener en primer fallo
```bash
pytest tests/ -v -x
```

### Ver traceback completo
```bash
pytest tests/ -v --tb=long
```

## 📈 CI/CD

Los tests se ejecutan automáticamente en GitHub Actions:

```yaml
# .github/workflows/azure-deploy.yml
- name: Run tests
  run: |
    pytest tests/ -v --cov=src --cov-report=xml
```

Solo los tests unitarios se ejecutan en CI (sin `--integration` ni `--api`).

## ✨ Buenas Prácticas

1. **Usar fixtures compartidas** de `conftest.py`
2. **Marcar correctamente** los tests de integración
3. **Mantener tests unitarios rápidos** (<1s)
4. **Usar mocks para servicios externos** en tests unitarios
5. **Validar edge cases** (datos vacíos, nulos, inválidos)
6. **Documentar qué se está probando** con docstrings claros

## 🎓 Ejemplos

### Test Unitario Simple
```python
def test_archived_filter(self):
    """Verifica que se filtren repositorios archivados."""
    repo_data = {
        "is_archived": True,
        "stars": 100
    }
    filters = RepositoryFilters()
    result = filters.apply_filters(repo_data)
    assert result["accepted"] is False
```

### Test de Integración
```python
@pytest.mark.integration
def test_full_pipeline(self):
    """Test completo con servicios reales."""
    engine = RepositoryIngestionEngine(
        github_token=config.GITHUB_TOKEN,
        db_config=config.get_database_config()
    )
    stats = engine.ingest(max_results=2)
    assert stats["total_extracted"] >= 0
```

### Test de API
```python
def test_list_repositories(self):
    """Verifica que se puedan listar repositorios."""
    response = requests.get(f"{API_BASE_URL}/api/repositories")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
```

---

## 📈 Estadísticas Actuales

**Total Tests:** 61 tests  
✅ **Tests Pasando:** 61/61 (100%)  
⏭️ **Tests Skipped:** 0  
⚠️ **Warnings:** 0  
**Cobertura:** Tests de modelos, filtros, persistencia y API  
**Tiempo Ejecución:** ~1 segundo  

### Desglose por Módulo

- **test_database.py**: 23/23 ✅ (100%)
- **test_repositories.py**: 9/9 ✅ (100%)
- **test_users.py**: 9/9 ✅ (100%)
- **test_organizations.py**: 9/9 ✅ (100%)
- **test_api.py**: 11/11 ✅ (100%)
