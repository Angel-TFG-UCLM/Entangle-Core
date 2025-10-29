"""
Script para enriquecer repositorios ya ingestados en MongoDB.
Completa información faltante usando GraphQL y REST API.
"""
import sys
import os

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.db import get_database
from src.core.mongo_repository import MongoRepository
from src.core.logger import logger
from src.github.enrichment import EnrichmentEngine


def main():
    """Punto de entrada principal del script de enriquecimiento."""
    try:
        # Cargar variables de entorno
        load_dotenv()
        github_token = os.getenv("GITHUB_TOKEN")
        
        if not github_token:
            logger.error("❌ GITHUB_TOKEN no encontrado en el archivo .env")
            sys.exit(1)
        
        print("\n" + "=" * 80)
        print("  🔄 INICIANDO ENRIQUECIMIENTO DE REPOSITORIOS")
        print("=" * 80 + "\n")
        
        # Conectar a MongoDB
        db = get_database()
        
        # Inicializar repositorios
        repos_repository = MongoRepository(
            collection_name="repositories",
            unique_fields=["id"]
        )
        
        # Preguntar cuántos repositorios enriquecer
        print("💡 TIP: Para pruebas, usa un número pequeño (ej: 5-10)")
        print("        Para enriquecer todos, presiona Enter")
        
        user_input = input("\n¿Cuántos repositorios quieres enriquecer? [Enter = todos]: ").strip()
        
        max_repos = None
        if user_input:
            try:
                max_repos = int(user_input)
                print(f"✅ Enriquecimiento limitado a {max_repos} repositorios\n")
            except ValueError:
                print("⚠️  Entrada inválida, enriqueciendo todos los repositorios\n")
        else:
            print("✅ Enriqueciendo todos los repositorios\n")
        
        print("=" * 80)
        print("  🔄 PROCESANDO...")
        print("=" * 80 + "\n")
        
        # Inicializar motor de enriquecimiento
        engine = EnrichmentEngine(
            github_token=github_token,
            repos_repository=repos_repository,
            batch_size=10
        )
        
        # Ejecutar enriquecimiento
        stats = engine.enrich_all_repositories(max_repos=max_repos)
        
        # Mostrar resumen final
        print("\n" + "=" * 80)
        print("  ✅ ENRIQUECIMIENTO COMPLETADO")
        print("=" * 80)
        print(f"\n📊 RESUMEN FINAL:")
        print(f"  • Repositorios procesados: {stats['total_processed']}")
        print(f"  • Repositorios enriquecidos: {stats['total_enriched']}")
        print(f"  • Errores: {stats['total_errors']}")
        
        if stats.get('start_time') and stats.get('end_time'):
            duration = (stats['end_time'] - stats['start_time']).total_seconds()
            print(f"\n⏱️  Tiempo total: {duration:.2f}s")
        
        if stats.get('fields_enriched'):
            print(f"\n📝 Campos enriquecidos:")
            for field, count in sorted(stats['fields_enriched'].items()):
                print(f"  • {field}: {count}")
        
        print("\n" + "=" * 80 + "\n")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Enriquecimiento interrumpido por el usuario")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Error durante el enriquecimiento: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
