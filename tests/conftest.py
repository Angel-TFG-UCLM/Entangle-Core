"""
Configuración compartida de pytest y fixtures globales.
"""
import pytest
import os
from unittest.mock import Mock


def pytest_configure(config):
    """Configuración inicial de pytest."""
    # Agregar marcadores personalizados
    config.addinivalue_line(
        "markers", "integration: Tests de integración que requieren servicios externos (MongoDB, GitHub API)"
    )
    config.addinivalue_line(
        "markers", "slow: Tests lentos que tardan más de 5 segundos"
    )
    config.addinivalue_line(
        "markers", "api: Tests que requieren la API REST ejecutándose en localhost:8000"
    )


@pytest.fixture(scope="session")
def github_token():
    """Fixture que proporciona el token de GitHub para tests."""
    from src.core.config import config
    return config.GITHUB_TOKEN


@pytest.fixture(scope="session")
def db_config():
    """Fixture que proporciona la configuración de base de datos."""
    from src.core.config import config
    return config.get_database_config()


@pytest.fixture
def mock_graphql_client():
    """Fixture que crea un cliente GraphQL mock."""
    mock = Mock()
    mock.execute_query = Mock(return_value={})
    mock.get_rate_limit = Mock(return_value={
        "remaining": 5000,
        "limit": 5000,
        "reset_at": "2024-12-31T23:59:59Z"
    })
    return mock


@pytest.fixture
def mock_database():
    """Fixture que crea una base de datos mock."""
    mock = Mock()
    mock.client = Mock()
    mock.db = Mock()
    mock.is_connected = Mock(return_value=True)
    mock.connect = Mock()
    mock.disconnect = Mock()
    mock.get_collection = Mock()
    return mock


@pytest.fixture
def mock_repository():
    """Fixture que crea un MongoRepository mock."""
    mock = Mock()
    mock.insert_one = Mock(return_value="mock_id_12345")
    mock.insert_many = Mock(return_value={
        "inserted_count": 5,
        "duplicate_count": 0,
        "inserted_ids": ["id1", "id2", "id3", "id4", "id5"]
    })
    mock.bulk_upsert = Mock(return_value={
        "inserted": 5,
        "updated": 0
    })
    mock.find_one = Mock(return_value=None)
    mock.find_all = Mock(return_value=[])
    mock.update_one = Mock(return_value=True)
    mock.delete_one = Mock(return_value=True)
    return mock


@pytest.fixture
def sample_repository_data():
    """Fixture con datos de ejemplo de un repositorio."""
    from datetime import datetime
    return {
        "full_name": "quantum-org/qiskit",
        "owner_login": "quantum-org",
        "name": "qiskit",
        "description": "Qiskit is an open-source SDK for working with quantum computers",
        "stars": 5000,
        "language": "Python",
        "is_archived": False,
        "created_at": datetime(2017, 3, 5),
        "updated_at": datetime.now(),
        "pushed_at": datetime.now()
    }


@pytest.fixture
def sample_user_data():
    """Fixture con datos de ejemplo de un usuario."""
    from datetime import datetime
    return {
        "login": "quantumdev",
        "github_id": 12345678,
        "type": "User",
        "name": "Quantum Developer",
        "email": "dev@quantum.org",
        "bio": "Quantum computing enthusiast",
        "company": "Quantum Corp",
        "location": "San Francisco, CA",
        "followers": 250,
        "following": 100,
        "public_repos": 42,
        "created_at": datetime(2015, 1, 1),
        "updated_at": datetime.now()
    }


@pytest.fixture
def sample_organization_data():
    """Fixture con datos de ejemplo de una organización."""
    from datetime import datetime
    return {
        "login": "quantum-org",
        "github_id": 98765432,
        "name": "Quantum Computing Organization",
        "description": "Open source quantum computing tools",
        "email": "contact@quantum-org.org",
        "location": "Cambridge, MA",
        "website_url": "https://quantum-org.org",
        "public_repos": 150,
        "members_count": 45,
        "created_at": datetime(2012, 6, 15),
        "updated_at": datetime.now()
    }


# Hooks para personalizar el output de pytest
def pytest_collection_modifyitems(config, items):
    """Modifica los items de la colección de tests."""
    # Agregar marcador 'integration' a tests que lo necesiten
    for item in items:
        if "integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)


def pytest_runtest_setup(item):
    """Hook que se ejecuta antes de cada test."""
    # Saltar tests de integración si no se especifica --integration
    if "integration" in [mark.name for mark in item.iter_markers()]:
        if not item.config.getoption("--integration", default=False):
            pytest.skip("Test de integración: ejecuta con --integration")


def pytest_addoption(parser):
    """Agregar opciones de línea de comandos personalizadas."""
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Ejecutar tests de integración (requiere MongoDB y GitHub token)"
    )
