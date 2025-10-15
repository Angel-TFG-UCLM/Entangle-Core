"""
Test de integración con MOCKS: Motor de Ingesta + Persistencia MongoDB.

Este script prueba el flujo completo usando datos simulados (mocks)
para evitar dependencias de la API real de GitHub.

Tests:
1. Validación de datos raw → Pydantic models
2. Persistencia en MongoDB con bulk operations
3. Creación de relaciones
4. Modo incremental (insert vs update)
5. Manejo de errores de validación
"""
import sys
sys.path.insert(0, '.')

from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone
from src.github.ingestion import IngestionEngine
from src.core import db
from src.core.mongo_repository import MongoRepository
from src.models import Repository, Organization, User


# ==================== DATOS MOCK ====================

def get_mock_repository_data(repo_id: int, name: str, stars: int = 50):
    """Genera datos mock de un repositorio en formato GraphQL."""
    return {
        "id": f"R_{repo_id}",
        "name": name,
        "nameWithOwner": f"test-org/{name}",
        "description": f"Test repository {name} for quantum computing",
        "url": f"https://github.com/test-org/{name}",
        "createdAt": "2023-01-01T00:00:00Z",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "pushedAt": datetime.now(timezone.utc).isoformat(),
        "isArchived": False,
        "isFork": False,
        "isPrivate": False,
        "stargazerCount": stars,
        "forkCount": 10,
        "watchers": {"totalCount": 5},
        "issues": {"totalCount": 2},
        "pullRequests": {"totalCount": 1},
        "primaryLanguage": {"name": "Python"},
        "languages": {
            "edges": [
                {"size": 10000, "node": {"name": "Python"}},
                {"size": 2000, "node": {"name": "JavaScript"}}
            ]
        },
        "owner": {
            "login": "test-org",
            "id": f"U_{repo_id}",
            "url": f"https://github.com/test-org",
            "avatarUrl": "https://avatars.githubusercontent.com/u/123",
            "type": "Organization"
        },
        "defaultBranchRef": {
            "name": "main",
            "target": {
                "history": {"totalCount": 50}
            }
        },
        "diskUsage": 500,
        "hasIssuesEnabled": True,
        "hasWikiEnabled": True,
        "homepageUrl": f"https://{name}.example.com",
        "licenseInfo": {"name": "MIT License", "key": "mit"},
        "topics": {"nodes": [{"topic": {"name": "quantum"}}, {"topic": {"name": "python"}}]},
        "repositoryTopics": {
            "nodes": [
                {"topic": {"name": "quantum"}},
                {"topic": {"name": "computing"}}
            ]
        }
    }


def get_mock_graphql_response(num_repos: int = 3):
    """Genera una respuesta mock completa de GraphQL."""
    return {
        "search": {
            "repositoryCount": num_repos,
            "pageInfo": {
                "hasNextPage": False,
                "endCursor": None
            },
            "edges": [
                {
                    "node": get_mock_repository_data(i, f"quantum-repo-{i}", stars=100 - i*10)
                }
                for i in range(num_repos)
            ]
        }
    }


# ==================== TESTS ====================

def test_validation_phase():
    """Test de la fase de validación con datos mock."""
    print("\n" + "="*80)
    print("  🧪 TEST 1: Fase de Validación (Raw Data → Pydantic)")
    print("="*80 + "\n")
    
    try:
        # Crear mock del cliente GraphQL
        mock_client = Mock()
        mock_response = get_mock_graphql_response(3)
        mock_client.search_repositories_all_pages.return_value = mock_response
        
        # Crear engine con cliente mock
        engine = IngestionEngine(client=mock_client, batch_size=10)
        
        # Extraer datos raw
        repos_raw = [edge["node"] for edge in mock_response["search"]["edges"]]
        print(f"📦 Datos raw extraídos: {len(repos_raw)} repositorios")
        
        # Validar con Pydantic
        validated_repos, validation_errors = engine._validate_repositories(repos_raw)
        
        # Verificaciones
        assert len(validated_repos) == 3, f"Esperaba 3 repos validados, obtuvo {len(validated_repos)}"
        assert len(validation_errors) == 0, f"No debería haber errores, obtuvo {len(validation_errors)}"
        
        print(f"✅ Validados: {len(validated_repos)} repositorios")
        print(f"✅ Errores: {len(validation_errors)}")
        
        # Verificar que son objetos Pydantic
        assert all(isinstance(repo, Repository) for repo in validated_repos), "No son instancias de Repository"
        print(f"✅ Todos son instancias de Repository (Pydantic)")
        
        # Verificar algunos campos
        repo = validated_repos[0]
        print(f"\n📋 Sample de repositorio validado:")
        print(f"  • ID: {repo.id}")
        print(f"  • Nombre: {repo.full_name}")
        print(f"  • Estrellas: {repo.stargazer_count}")
        print(f"  • Lenguaje: {repo.primary_language}")
        print(f"  • Owner: {repo.owner.login if repo.owner else 'N/A'}")
        
        print("\n✅ TEST 1 PASADO")
        return True
        
    except Exception as e:
        print(f"\n❌ TEST 1 FALLÓ: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_persistence_phase():
    """Test de la fase de persistencia con bulk operations."""
    print("\n" + "="*80)
    print("  🧪 TEST 2: Fase de Persistencia (Bulk Operations)")
    print("="*80 + "\n")
    
    try:
        # Limpiar colección antes del test
        repo_db = MongoRepository("repositories")
        repo_db.delete_many({})
        print("🧹 Colección limpiada")
        
        # Crear mock del cliente
        mock_client = Mock()
        mock_response = get_mock_graphql_response(5)
        mock_client.search_repositories_all_pages.return_value = mock_response
        
        # Crear engine
        engine = IngestionEngine(client=mock_client, batch_size=2)
        
        # Validar datos
        repos_raw = [edge["node"] for edge in mock_response["search"]["edges"]]
        validated_repos, _ = engine._validate_repositories(repos_raw)
        
        print(f"📦 {len(validated_repos)} repositorios listos para persistir")
        print(f"📦 Batch size: {engine.batch_size}")
        
        # Persistir
        engine._persist_repositories(validated_repos)
        
        # Verificar en MongoDB
        count = repo_db.count_documents({})
        assert count == 5, f"Esperaba 5 repos en DB, obtuvo {count}"
        print(f"✅ Repositorios en MongoDB: {count}")
        
        # Verificar estadísticas
        inserted = engine.stats["repositories_inserted"]
        updated = engine.stats["repositories_updated"]
        print(f"✅ Insertados: {inserted}")
        print(f"✅ Actualizados: {updated}")
        
        assert inserted == 5, f"Esperaba 5 inserts, obtuvo {inserted}"
        assert updated == 0, f"Esperaba 0 updates, obtuvo {updated}"
        
        # Verificar algunos documentos
        sample = repo_db.find_one({"name": "quantum-repo-0"})
        assert sample is not None, "No se encontró el repo sample"
        print(f"\n📋 Sample de documento en MongoDB:")
        print(f"  • ID: {sample.get('id')}")
        print(f"  • Nombre: {sample.get('full_name')}")
        print(f"  • Estrellas: {sample.get('stars_count')}")
        
        print("\n✅ TEST 2 PASADO")
        return True
        
    except Exception as e:
        print(f"\n❌ TEST 2 FALLÓ: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_incremental_mode():
    """Test del modo incremental (insert vs update)."""
    print("\n" + "="*80)
    print("  🧪 TEST 3: Modo Incremental (Insert → Update)")
    print("="*80 + "\n")
    
    try:
        # Limpiar colección
        repo_db = MongoRepository("repositories")
        repo_db.delete_many({})
        
        # Mock client
        mock_client = Mock()
        mock_response = get_mock_graphql_response(3)
        mock_client.search_repositories_all_pages.return_value = mock_response
        
        # PRIMERA INGESTA (completa)
        print("1️⃣  Primera ingesta (modo completo)...")
        engine1 = IngestionEngine(client=mock_client, incremental=False, batch_size=5)
        repos_raw = [edge["node"] for edge in mock_response["search"]["edges"]]
        validated, _ = engine1._validate_repositories(repos_raw)
        engine1._persist_repositories(validated)
        
        inserted_first = engine1.stats["repositories_inserted"]
        updated_first = engine1.stats["repositories_updated"]
        print(f"  ✓ Insertados: {inserted_first}")
        print(f"  ✓ Actualizados: {updated_first}")
        
        # SEGUNDA INGESTA (incremental - mismo cliente mock)
        print("\n2️⃣  Segunda ingesta (modo incremental)...")
        engine2 = IngestionEngine(client=mock_client, incremental=True, batch_size=5)
        validated2, _ = engine2._validate_repositories(repos_raw)
        engine2._persist_repositories(validated2)
        
        inserted_second = engine2.stats["repositories_inserted"]
        updated_second = engine2.stats["repositories_updated"]
        print(f"  ✓ Insertados: {inserted_second}")
        print(f"  ✓ Actualizados: {updated_second}")
        
        # Verificaciones
        assert inserted_first == 3, f"Primera ingesta debería insertar 3, obtuvo {inserted_first}"
        assert updated_first == 0, f"Primera ingesta no debería actualizar, obtuvo {updated_first}"
        
        # En la segunda ingesta, como los IDs ya existen, serán updates
        assert updated_second == 3, f"Segunda ingesta debería actualizar 3, obtuvo {updated_second}"
        assert inserted_second == 0, f"Segunda ingesta no debería insertar, obtuvo {inserted_second}"
        
        # Verificar que solo hay 3 documentos (no duplicados)
        count = repo_db.count_documents({})
        assert count == 3, f"Debería haber 3 repos únicos, obtuvo {count}"
        print(f"\n✅ Total en DB: {count} (sin duplicados)")
        
        print("\n✅ TEST 3 PASADO")
        return True
        
    except Exception as e:
        print(f"\n❌ TEST 3 FALLÓ: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_relations_creation():
    """Test de creación de relaciones."""
    print("\n" + "="*80)
    print("  🧪 TEST 4: Creación de Relaciones")
    print("="*80 + "\n")
    
    try:
        # Limpiar colecciones
        repo_db = MongoRepository("repositories")
        relation_db = MongoRepository("relations")
        repo_db.delete_many({})
        relation_db.delete_many({})
        print("🧹 Colecciones limpiadas")
        
        # Mock client
        mock_client = Mock()
        mock_response = get_mock_graphql_response(3)
        mock_client.search_repositories_all_pages.return_value = mock_response
        
        # Crear engine
        engine = IngestionEngine(client=mock_client, batch_size=5)
        
        # Validar y persistir
        repos_raw = [edge["node"] for edge in mock_response["search"]["edges"]]
        validated, _ = engine._validate_repositories(repos_raw)
        engine._persist_repositories(validated)
        
        print(f"📦 {len(validated)} repositorios persistidos")
        
        # Crear relaciones
        engine._create_relations(validated)
        
        # Verificar
        relations_count = relation_db.count_documents({})
        print(f"✅ Relaciones creadas: {relations_count}")
        print(f"✅ Stats: {engine.stats['relations_created']}")
        
        assert relations_count == 3, f"Esperaba 3 relaciones, obtuvo {relations_count}"
        assert engine.stats["relations_created"] == 3, f"Stats incorrectos"
        
        # Verificar una relación
        sample_relation = relation_db.find_one({})
        assert sample_relation is not None, "No se encontró ninguna relación"
        print(f"\n📋 Sample de relación:")
        print(f"  • Source: {sample_relation.get('source_login')}")
        print(f"  • Target: {sample_relation.get('target_name')}")
        print(f"  • Type: {sample_relation.get('relation_type')}")
        
        print("\n✅ TEST 4 PASADO")
        return True
        
    except Exception as e:
        print(f"\n❌ TEST 4 FALLÓ: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_validation_errors():
    """Test de manejo de errores de validación."""
    print("\n" + "="*80)
    print("  🧪 TEST 5: Manejo de Errores de Validación")
    print("="*80 + "\n")
    
    try:
        # Crear datos inválidos (falta campo requerido)
        invalid_data = [
            get_mock_repository_data(1, "valid-repo", 100),
            {
                "id": "R_INVALID",
                "name": "invalid-repo",
                # Falta nameWithOwner (requerido)
                "description": "Invalid repo",
                "stargazerCount": 10
            },
            get_mock_repository_data(3, "valid-repo-2", 80)
        ]
        
        print(f"📦 Datos de prueba: 2 válidos + 1 inválido")
        
        # Mock client
        mock_client = Mock()
        engine = IngestionEngine(client=mock_client)
        
        # Validar
        validated, errors = engine._validate_repositories(invalid_data)
        
        print(f"\n✅ Validados: {len(validated)}")
        print(f"⚠️  Errores: {len(errors)}")
        
        assert len(validated) == 2, f"Esperaba 2 válidos, obtuvo {len(validated)}"
        assert len(errors) == 1, f"Esperaba 1 error, obtuvo {len(errors)}"
        
        # Verificar estadísticas
        assert engine.stats["validation_success"] == 2
        assert engine.stats["validation_errors"] == 1
        
        print(f"\n📋 Error capturado:")
        print(f"  • Repo: {errors[0].get('repository', 'unknown')}")
        print(f"  • Error: {errors[0].get('error', 'unknown')[:100]}...")
        
        print("\n✅ TEST 5 PASADO")
        return True
        
    except Exception as e:
        print(f"\n❌ TEST 5 FALLÓ: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_full_integration_flow():
    """Test del flujo completo de integración."""
    print("\n" + "="*80)
    print("  🧪 TEST 6: Flujo Completo de Integración")
    print("="*80 + "\n")
    
    try:
        # Limpiar todo
        repo_db = MongoRepository("repositories")
        relation_db = MongoRepository("relations")
        repo_db.delete_many({})
        relation_db.delete_many({})
        print("🧹 Colecciones limpiadas\n")
        
        # Mock client
        mock_client = Mock()
        mock_response = get_mock_graphql_response(5)
        # search_repositories_all_pages() retorna solo la lista de nodos, no la respuesta completa
        mock_nodes = [edge["node"] for edge in mock_response["search"]["edges"]]
        mock_client.search_repositories_all_pages.return_value = mock_nodes
        
        # Crear engine
        engine = IngestionEngine(client=mock_client, batch_size=2)
        
        # Ejecutar flujo completo
        print("🚀 Ejecutando flujo completo...")
        report = engine.run(max_results=5, save_to_json=False)
        
        # Verificar reporte
        print(f"\n📊 REPORTE:")
        print(f"  • Total encontrado: {report['summary']['total_found']}")
        print(f"  • Validados: {report['summary']['validation_success']}")
        print(f"  • Insertados: {report['summary']['repositories_inserted']}")
        print(f"  • Relaciones: {report['summary']['relations_created']}")
        
        # Assertions
        assert report['summary']['total_found'] == 5
        assert report['summary']['validation_success'] == 5
        assert report['summary']['repositories_inserted'] == 5
        assert report['summary']['relations_created'] == 5
        
        # Verificar en DB
        repos_in_db = repo_db.count_documents({})
        relations_in_db = relation_db.count_documents({})
        
        print(f"\n💾 En MongoDB:")
        print(f"  • Repositorios: {repos_in_db}")
        print(f"  • Relaciones: {relations_in_db}")
        
        assert repos_in_db == 5
        assert relations_in_db == 5
        
        # Verificar tiempos
        print(f"\n⏱️  Tiempos:")
        print(f"  • Validación: {report['timing']['validation']}")
        print(f"  • Persistencia: {report['timing']['persistence']}")
        print(f"  • Total: {report['timing']['total']}")
        
        print("\n✅ TEST 6 PASADO")
        return True
        
    except Exception as e:
        print(f"\n❌ TEST 6 FALLÓ: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Ejecuta todos los tests con mocks."""
    print("\n" + "="*80)
    print("  🧪 SUITE DE TESTS DE INTEGRACIÓN (CON MOCKS)")
    print("  Motor de Ingesta + Módulo de Persistencia")
    print("="*80)
    
    # Asegurar conexión a MongoDB
    if not db.is_connected():
        db.connect()
    
    results = {
        "Validación (Raw → Pydantic)": test_validation_phase(),
        "Persistencia (Bulk Operations)": test_persistence_phase(),
        "Modo Incremental": test_incremental_mode(),
        "Creación de Relaciones": test_relations_creation(),
        "Manejo de Errores": test_validation_errors(),
        "Flujo Completo": test_full_integration_flow()
    }
    
    # Resumen
    print("\n" + "="*80)
    print("  📊 RESUMEN DE TESTS")
    print("="*80)
    
    passed = sum(1 for result in results.values() if result)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASÓ" if result else "❌ FALLÓ"
        print(f"  {status}: {test_name}")
    
    print(f"\n  Total: {passed}/{total} tests pasados")
    
    if passed == total:
        print("\n  🎉 TODOS LOS TESTS PASARON EXITOSAMENTE")
    else:
        print(f"\n  ⚠️  {total - passed} test(s) fallaron")
    
    print("="*80 + "\n")
    
    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
