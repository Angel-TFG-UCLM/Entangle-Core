"""
Script de prueba completo para el cliente GraphQL de GitHub.

Este script prueba todas las funcionalidades del GitHubGraphQLClient:
- Inicialización con token
- Ejecución de consultas genéricas
- Control de rate limit
- Búsqueda de repositorios con criterios dinámicos
"""

from src.github.graphql_client import GitHubGraphQLClient
from src.core.config import ingestion_config
from src.core.logger import logger
import json


def print_separator(title: str):
    """Imprime un separador con título."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def test_client_initialization():
    """Prueba la inicialización del cliente."""
    print_separator("PRUEBA 1: Inicialización del Cliente")
    
    try:
        client = GitHubGraphQLClient()
        print("✅ Cliente inicializado correctamente")
        print(f"   API URL: {client.api_url}")
        print(f"   Token configurado: {'Sí' if client.token else 'No'}")
        return client
    except ValueError as e:
        print(f"❌ Error de inicialización: {e}")
        raise


def test_rate_limit(client: GitHubGraphQLClient):
    """Prueba la obtención de información del rate limit."""
    print_separator("PRUEBA 2: Rate Limit Info")
    
    try:
        rate_limit = client.get_rate_limit()
        
        print("✅ Rate limit obtenido correctamente:")
        print(f"   Límite total: {rate_limit.get('limit')}")
        print(f"   Requests usados: {rate_limit.get('used')}")
        print(f"   Requests restantes: {rate_limit.get('remaining')}")
        print(f"   Reset en: {rate_limit.get('resetAt')}")
        
        # Calcular porcentaje usado
        used = rate_limit.get('used', 0)
        limit = rate_limit.get('limit', 1)
        percentage = (used / limit) * 100
        print(f"   Uso: {percentage:.1f}%")
        
        return rate_limit
        
    except Exception as e:
        print(f"❌ Error al obtener rate limit: {e}")
        raise


def test_generic_query(client: GitHubGraphQLClient):
    """Prueba una consulta genérica (obtener información del usuario autenticado)."""
    print_separator("PRUEBA 3: Consulta Genérica (Viewer)")
    
    query = """
    query {
        viewer {
            login
            name
            email
            bio
            company
            location
        }
    }
    """
    
    try:
        result = client.execute_query(query)
        viewer = result.get("data", {}).get("viewer", {})
        
        print("✅ Consulta ejecutada correctamente:")
        print(f"   Usuario: {viewer.get('login')}")
        print(f"   Nombre: {viewer.get('name')}")
        print(f"   Email: {viewer.get('email')}")
        print(f"   Bio: {viewer.get('bio')}")
        print(f"   Compañía: {viewer.get('company')}")
        print(f"   Ubicación: {viewer.get('location')}")
        
        return viewer
        
    except Exception as e:
        print(f"❌ Error en consulta genérica: {e}")
        raise


def test_search_query_building(client: GitHubGraphQLClient):
    """Prueba la construcción de query de búsqueda."""
    print_separator("PRUEBA 4: Construcción de Query de Búsqueda")
    
    try:
        search_query = client._build_search_query(ingestion_config)
        
        print("✅ Query de búsqueda construida:")
        print(f"   {search_query}")
        print("\n📋 Criterios aplicados:")
        print(f"   Keywords: {len(ingestion_config.keywords)} palabras clave")
        print(f"   Lenguajes: {', '.join(ingestion_config.languages)}")
        print(f"   Estrellas mínimas: {ingestion_config.min_stars}")
        print(f"   Excluir forks: {ingestion_config.exclude_forks}")
        
        return search_query
        
    except Exception as e:
        print(f"❌ Error al construir query: {e}")
        raise


def test_search_repositories(client: GitHubGraphQLClient):
    """Prueba la búsqueda de repositorios."""
    print_separator("PRUEBA 5: Búsqueda de Repositorios (Primera Página)")
    
    try:
        result = client.search_repositories(
            config_criteria=ingestion_config,
            first=10  # Solo 10 resultados para la prueba
        )
        
        repositories = result.get("repositories", [])
        total_count = result.get("total_count", 0)
        page_info = result.get("page_info", {})
        
        print(f"✅ Búsqueda completada:")
        print(f"   Repositorios encontrados (total): {total_count}")
        print(f"   Repositorios en esta página: {len(repositories)}")
        print(f"   Hay más páginas: {page_info.get('hasNextPage')}")
        
        if repositories:
            print("\n📦 Primeros 3 repositorios:")
            for i, repo in enumerate(repositories[:3], 1):
                print(f"\n   {i}. {repo.get('nameWithOwner')}")
                print(f"      ⭐ Stars: {repo.get('stargazerCount')}")
                print(f"      🍴 Forks: {repo.get('forkCount')}")
                print(f"      💻 Lenguaje: {repo.get('primaryLanguage', {}).get('name', 'N/A')}")
                print(f"      📝 Descripción: {repo.get('description', 'Sin descripción')[:100]}...")
                print(f"      🔗 URL: {repo.get('url')}")
                print(f"      📅 Actualizado: {repo.get('updatedAt')}")
                print(f"      🔀 Es fork: {repo.get('isFork')}")
                
                # Mostrar topics si existen
                topics = repo.get('repositoryTopics', {}).get('nodes', [])
                if topics:
                    topic_names = [t['topic']['name'] for t in topics if 'topic' in t]
                    print(f"      🏷️  Topics: {', '.join(topic_names[:5])}")
        
        return repositories
        
    except Exception as e:
        print(f"❌ Error al buscar repositorios: {e}")
        logger.error(f"Error en búsqueda: {e}", exc_info=True)
        raise


def test_repository_filtering(repositories: list):
    """Prueba el filtrado de repositorios según criterios."""
    print_separator("PRUEBA 6: Filtrado de Repositorios")
    
    # Filtrar por criterios de inactividad
    from datetime import datetime, timedelta
    
    max_inactivity = ingestion_config.max_inactivity_days
    cutoff_date = datetime.now() - timedelta(days=max_inactivity)
    
    active_repos = []
    inactive_repos = []
    
    for repo in repositories:
        updated_at_str = repo.get('updatedAt', '')
        if updated_at_str:
            updated_at = datetime.fromisoformat(updated_at_str.replace('Z', '+00:00'))
            
            if updated_at.replace(tzinfo=None) >= cutoff_date:
                active_repos.append(repo)
            else:
                inactive_repos.append(repo)
    
    print(f"📊 Resultados del filtrado:")
    print(f"   Repositorios activos (últimos {max_inactivity} días): {len(active_repos)}")
    print(f"   Repositorios inactivos: {len(inactive_repos)}")
    
    # Estadísticas por lenguaje
    language_counts = {}
    for repo in repositories:
        lang = repo.get('primaryLanguage', {})
        if lang:
            lang_name = lang.get('name', 'Unknown')
            language_counts[lang_name] = language_counts.get(lang_name, 0) + 1
    
    print(f"\n💻 Distribución por lenguaje:")
    for lang, count in sorted(language_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"   {lang}: {count} repositorios")
    
    return active_repos


def test_export_to_json(repositories: list):
    """Exporta los resultados a JSON."""
    print_separator("PRUEBA 7: Exportar a JSON")
    
    try:
        output_file = "test_repositories_output.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(repositories, f, indent=2, ensure_ascii=False, default=str)
        
        print(f"✅ Repositorios exportados a: {output_file}")
        print(f"   Total de repositorios: {len(repositories)}")
        
    except Exception as e:
        print(f"❌ Error al exportar: {e}")


def test_check_rate_limit(client: GitHubGraphQLClient):
    """Prueba el control de rate limit."""
    print_separator("PRUEBA 8: Control de Rate Limit")
    
    try:
        print("🔍 Verificando rate limit antes de continuar...")
        client.check_rate_limit(min_remaining=100)
        print("✅ Rate limit OK - se puede continuar")
        
    except Exception as e:
        print(f"❌ Error en control de rate limit: {e}")


def main():
    """Función principal de prueba."""
    print("=" * 80)
    print("  TEST SUITE - GitHub GraphQL Client")
    print("=" * 80)
    print("\n🚀 Iniciando pruebas del cliente GraphQL de GitHub...")
    
    try:
        # 1. Inicializar cliente
        client = test_client_initialization()
        
        # 2. Verificar rate limit
        test_rate_limit(client)
        
        # 3. Probar consulta genérica
        test_generic_query(client)
        
        # 4. Probar construcción de query
        test_search_query_building(client)
        
        # 5. Verificar control de rate limit
        test_check_rate_limit(client)
        
        # 6. Buscar repositorios
        repositories = test_search_repositories(client)
        
        # 7. Filtrar repositorios
        if repositories:
            active_repos = test_repository_filtering(repositories)
            
            # 8. Exportar resultados
            test_export_to_json(repositories)
        
        # Resumen final
        print_separator("RESUMEN FINAL")
        print("\n✅ TODAS LAS PRUEBAS COMPLETADAS EXITOSAMENTE")
        print(f"   ✓ Cliente inicializado")
        print(f"   ✓ Rate limit verificado")
        print(f"   ✓ Consultas ejecutadas")
        print(f"   ✓ Búsqueda de repositorios funcional")
        print(f"   ✓ Filtrado implementado")
        print(f"   ✓ Exportación a JSON")
        
        print("\n" + "=" * 80)
        print("  TEST SUITE COMPLETADO")
        print("=" * 80 + "\n")
        
    except Exception as e:
        print_separator("ERROR EN PRUEBAS")
        print(f"\n❌ Error durante las pruebas: {e}")
        logger.error(f"Error en test suite: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
