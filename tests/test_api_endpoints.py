"""
Script de prueba para los nuevos endpoints de la API.
Prueba los endpoints de ingesta y enriquecimiento.
"""
import requests
import time
import json
from typing import Dict, Any

# Configuración
API_BASE_URL = "http://localhost:8000/api/v1"


def print_section(title: str):
    """Imprime un separador de sección."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def test_health():
    """Prueba el endpoint de health."""
    print_section("TEST: Health Check")
    
    response = requests.get(f"{API_BASE_URL}/health")
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
    
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    print("✅ Health check OK")


def test_rate_limit():
    """Prueba el endpoint de rate limit."""
    print_section("TEST: Rate Limit")
    
    response = requests.get(f"{API_BASE_URL}/rate-limit")
    print(f"Status Code: {response.status_code}")
    data = response.json()
    print(f"Rate Limit: {data.get('remaining', 'N/A')}/{data.get('limit', 'N/A')}")
    print(f"Reset At: {data.get('resetAt', 'N/A')}")
    
    assert response.status_code == 200
    print("✅ Rate limit check OK")


def test_repository_ingestion():
    """Prueba el endpoint de ingesta de repositorios."""
    print_section("TEST: Repository Ingestion")
    
    # Iniciar ingesta con límite bajo para prueba
    print("🔄 Iniciando ingesta de repositorios (max 5)...")
    response = requests.post(
        f"{API_BASE_URL}/ingestion/repositories",
        params={
            "max_results": 5,
            "use_segmentation": False
        }
    )
    
    print(f"Status Code: {response.status_code}")
    data = response.json()
    print(json.dumps(data, indent=2))
    
    assert response.status_code == 200
    assert "task_id" in data
    assert data["status"] == "running"
    
    task_id = data["task_id"]
    print(f"✅ Tarea iniciada: {task_id}")
    
    # Monitorear progreso
    print("\n⏳ Monitoreando progreso...")
    max_checks = 10
    check_count = 0
    
    while check_count < max_checks:
        time.sleep(5)
        check_count += 1
        
        status_response = requests.get(f"{API_BASE_URL}/ingestion/status/{task_id}")
        status_data = status_response.json()
        
        print(f"[{check_count}/{max_checks}] Estado: {status_data['status']} - {status_data.get('progress', 'N/A')}")
        
        if status_data["status"] in ["completed", "failed"]:
            print(f"\n{'✅' if status_data['status'] == 'completed' else '❌'} Tarea {status_data['status']}")
            if status_data.get("stats"):
                print("\n📊 Estadísticas:")
                print(json.dumps(status_data["stats"], indent=2))
            if status_data.get("error"):
                print(f"\n❌ Error: {status_data['error']}")
            break
    
    return task_id


def test_user_ingestion():
    """Prueba el endpoint de ingesta de usuarios."""
    print_section("TEST: User Ingestion")
    
    print("🔄 Iniciando ingesta de usuarios (max 5 repos)...")
    response = requests.post(
        f"{API_BASE_URL}/ingestion/users",
        params={
            "max_repos": 5,
            "batch_size": 10
        }
    )
    
    print(f"Status Code: {response.status_code}")
    data = response.json()
    print(json.dumps(data, indent=2))
    
    assert response.status_code == 200
    assert "task_id" in data
    
    task_id = data["task_id"]
    print(f"✅ Tarea iniciada: {task_id}")
    
    return task_id


def test_repository_enrichment():
    """Prueba el endpoint de enriquecimiento de repositorios."""
    print_section("TEST: Repository Enrichment")
    
    print("🔄 Iniciando enriquecimiento de repositorios (max 3)...")
    response = requests.post(
        f"{API_BASE_URL}/enrichment/repositories",
        params={
            "max_repos": 3,
            "batch_size": 2
        }
    )
    
    print(f"Status Code: {response.status_code}")
    data = response.json()
    print(json.dumps(data, indent=2))
    
    assert response.status_code == 200
    assert "task_id" in data
    
    task_id = data["task_id"]
    print(f"✅ Tarea iniciada: {task_id}")
    
    return task_id


def test_user_enrichment():
    """Prueba el endpoint de enriquecimiento de usuarios."""
    print_section("TEST: User Enrichment")
    
    print("🔄 Iniciando enriquecimiento de usuarios (max 3)...")
    response = requests.post(
        f"{API_BASE_URL}/enrichment/users",
        params={
            "max_users": 3,
            "batch_size": 2
        }
    )
    
    print(f"Status Code: {response.status_code}")
    data = response.json()
    print(json.dumps(data, indent=2))
    
    assert response.status_code == 200
    assert "task_id" in data
    
    task_id = data["task_id"]
    print(f"✅ Tarea iniciada: {task_id}")
    
    return task_id


def test_list_tasks():
    """Prueba el endpoint de listar tareas."""
    print_section("TEST: List Tasks")
    
    response = requests.get(f"{API_BASE_URL}/tasks")
    print(f"Status Code: {response.status_code}")
    data = response.json()
    print(f"\nTotal de tareas: {data['total_tasks']}")
    
    if data["tasks"]:
        print("\n📋 Tareas:")
        for task in data["tasks"]:
            print(f"  - {task['task_id']}: {task['status']} ({task['progress']})")
    
    assert response.status_code == 200
    print("✅ Listar tareas OK")


def main():
    """Ejecuta todos los tests."""
    print("\n" + "🚀" * 40)
    print("  PRUEBAS DE ENDPOINTS DE INGESTA Y ENRIQUECIMIENTO")
    print("🚀" * 40)
    
    try:
        # Tests básicos
        test_health()
        test_rate_limit()
        
        # Test de ingesta de repositorios (completo con monitoreo)
        test_repository_ingestion()
        
        # Tests de otros endpoints (solo inicio, no monitoreo completo)
        test_user_ingestion()
        test_repository_enrichment()
        test_user_enrichment()
        
        # Esperar un poco para que las tareas se registren
        time.sleep(2)
        
        # Listar todas las tareas
        test_list_tasks()
        
        print_section("RESUMEN")
        print("✅ Todos los tests pasaron correctamente")
        print("\n💡 Puedes consultar el estado de las tareas con:")
        print(f"   GET {API_BASE_URL}/tasks")
        print(f"   GET {API_BASE_URL}/ingestion/status/{{task_id}}")
        print(f"   GET {API_BASE_URL}/enrichment/status/{{task_id}}")
        
    except AssertionError as e:
        print(f"\n❌ Test fallido: {e}")
        return 1
    except requests.exceptions.ConnectionError:
        print("\n❌ Error: No se puede conectar a la API")
        print("   Asegúrate de que la API está ejecutándose en http://localhost:8000")
        return 1
    except Exception as e:
        print(f"\n❌ Error inesperado: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
