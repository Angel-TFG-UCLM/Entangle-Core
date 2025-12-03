"""
Script de ejemplo para usar la API de ingesta y enriquecimiento.
Este script muestra cómo ejecutar el flujo completo desde Python.
"""
import requests
import time
import sys
from typing import Optional


class TFGAPIClient:
    """Cliente para interactuar con la API del TFG."""
    
    def __init__(self, api_url: str = "http://localhost:8000/api/v1"):
        """
        Inicializa el cliente.
        
        Args:
            api_url: URL base de la API
        """
        self.api_url = api_url.rstrip("/")
    
    def check_health(self) -> bool:
        """Verifica que la API esté disponible."""
        try:
            response = requests.get(f"{self.api_url}/health", timeout=5)
            return response.status_code == 200 and response.json()["status"] == "healthy"
        except Exception:
            return False
    
    def get_rate_limit(self) -> dict:
        """Obtiene información del rate limit de GitHub."""
        response = requests.get(f"{self.api_url}/rate-limit")
        response.raise_for_status()
        return response.json()
    
    def start_repository_ingestion(
        self,
        max_results: Optional[int] = None,
        incremental: bool = False,
        use_segmentation: bool = False
    ) -> str:
        """
        Inicia la ingesta de repositorios.
        
        Returns:
            task_id para monitorear el progreso
        """
        params = {}
        if max_results:
            params["max_results"] = max_results
        params["incremental"] = incremental
        params["use_segmentation"] = use_segmentation
        
        response = requests.post(f"{self.api_url}/ingestion/repositories", params=params)
        response.raise_for_status()
        return response.json()["task_id"]
    
    def start_user_ingestion(
        self,
        max_repos: Optional[int] = None,
        batch_size: int = 50
    ) -> str:
        """
        Inicia la ingesta de usuarios.
        
        Returns:
            task_id para monitorear el progreso
        """
        params = {"batch_size": batch_size}
        if max_repos:
            params["max_repos"] = max_repos
        
        response = requests.post(f"{self.api_url}/ingestion/users", params=params)
        response.raise_for_status()
        return response.json()["task_id"]
    
    def start_repository_enrichment(
        self,
        max_repos: Optional[int] = None,
        force_reenrich: bool = False,
        batch_size: int = 10
    ) -> str:
        """
        Inicia el enriquecimiento de repositorios.
        
        Returns:
            task_id para monitorear el progreso
        """
        params = {
            "batch_size": batch_size,
            "force_reenrich": force_reenrich
        }
        if max_repos:
            params["max_repos"] = max_repos
        
        response = requests.post(f"{self.api_url}/enrichment/repositories", params=params)
        response.raise_for_status()
        return response.json()["task_id"]
    
    def start_user_enrichment(
        self,
        max_users: Optional[int] = None,
        force_reenrich: bool = False,
        batch_size: int = 10
    ) -> str:
        """
        Inicia el enriquecimiento de usuarios.
        
        Returns:
            task_id para monitorear el progreso
        """
        params = {
            "batch_size": batch_size,
            "force_reenrich": force_reenrich
        }
        if max_users:
            params["max_users"] = max_users
        
        response = requests.post(f"{self.api_url}/enrichment/users", params=params)
        response.raise_for_status()
        return response.json()["task_id"]
    
    def get_task_status(self, task_id: str) -> dict:
        """Obtiene el estado de una tarea."""
        # Detectar tipo de tarea por el prefijo
        if "ingestion" in task_id:
            endpoint = "ingestion"
        else:
            endpoint = "enrichment"
        
        response = requests.get(f"{self.api_url}/{endpoint}/status/{task_id}")
        response.raise_for_status()
        return response.json()
    
    def wait_for_task(self, task_id: str, check_interval: int = 30) -> dict:
        """
        Espera a que una tarea complete.
        
        Args:
            task_id: ID de la tarea
            check_interval: Segundos entre cada verificación
            
        Returns:
            Estadísticas finales de la tarea
        """
        print(f"⏳ Esperando a que complete la tarea: {task_id}")
        
        while True:
            status = self.get_task_status(task_id)
            
            print(f"   Estado: {status['status']} - {status['progress']}")
            
            if status["status"] == "completed":
                print("✅ Tarea completada exitosamente")
                return status["stats"]
            elif status["status"] == "failed":
                raise Exception(f"Tarea fallida: {status.get('error', 'Error desconocido')}")
            
            time.sleep(check_interval)
    
    def list_tasks(self) -> dict:
        """Lista todas las tareas."""
        response = requests.get(f"{self.api_url}/tasks")
        response.raise_for_status()
        return response.json()


def main():
    """Ejemplo de uso del cliente."""
    print("=" * 80)
    print("  CLIENTE DE API - TFG BACKEND")
    print("=" * 80)
    
    # Cambiar esta URL por la de tu API desplegada
    API_URL = "http://localhost:8000/api/v1"
    # API_URL = "https://tu-api.azurecontainerapps.io/api/v1"
    
    client = TFGAPIClient(API_URL)
    
    # 1. Verificar que la API está disponible
    print("\n1️⃣ Verificando conexión con la API...")
    if not client.check_health():
        print("❌ Error: No se puede conectar a la API")
        print(f"   Verifica que la API está ejecutándose en: {API_URL}")
        return 1
    print("✅ API disponible")
    
    # 2. Verificar rate limit
    print("\n2️⃣ Verificando rate limit de GitHub...")
    rate_limit = client.get_rate_limit()
    print(f"✅ Rate limit: {rate_limit.get('remaining', 'N/A')}/{rate_limit.get('limit', 'N/A')}")
    
    # 3. Ejecutar ingesta de repositorios
    print("\n3️⃣ Iniciando ingesta de repositorios...")
    try:
        task_id = client.start_repository_ingestion(
            max_results=10,  # Limitar para prueba
            use_segmentation=False
        )
        print(f"✅ Tarea iniciada: {task_id}")
        
        # Esperar a que complete
        stats = client.wait_for_task(task_id, check_interval=10)
        print(f"\n📊 Estadísticas de ingesta:")
        print(f"   - Repositorios encontrados: {stats.get('total_found', 0)}")
        print(f"   - Repositorios insertados: {stats.get('repositories_inserted', 0)}")
        print(f"   - Duración: {stats.get('duration_seconds', 0):.1f}s")
        
    except Exception as e:
        print(f"❌ Error en ingesta de repositorios: {e}")
        return 1
    
    # 4. Ejecutar ingesta de usuarios
    print("\n4️⃣ Iniciando ingesta de usuarios...")
    try:
        task_id = client.start_user_ingestion(max_repos=5)
        print(f"✅ Tarea iniciada: {task_id}")
        
        stats = client.wait_for_task(task_id, check_interval=10)
        print(f"\n📊 Estadísticas de ingesta de usuarios:")
        print(f"   - Usuarios encontrados: {stats.get('users_found', 0)}")
        print(f"   - Usuarios insertados: {stats.get('users_inserted', 0)}")
        
    except Exception as e:
        print(f"❌ Error en ingesta de usuarios: {e}")
        return 1
    
    # 5. Listar todas las tareas
    print("\n5️⃣ Listando todas las tareas...")
    tasks = client.list_tasks()
    print(f"✅ Total de tareas: {tasks['total_tasks']}")
    
    print("\n" + "=" * 80)
    print("✅ PROCESO COMPLETADO EXITOSAMENTE")
    print("=" * 80)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
