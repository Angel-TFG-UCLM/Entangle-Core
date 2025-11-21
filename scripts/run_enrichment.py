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
from src.core.config import load_ingestion_config
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
        
        # Cargar configuración
        config = load_ingestion_config()
        logger.info(f"📝 Configuración cargada:")
        logger.info(f"  • Reintentos máximos: {config.get('enrichment', {}).get('max_retries', 3)}")
        logger.info(f"  • Backoff base: {config.get('enrichment', {}).get('base_backoff_seconds', 2)}s")
        logger.info(f"  • Rate limit threshold: {config.get('enrichment', {}).get('rate_limit_threshold', 100)}")
        logger.info(f"  • Batch size: {config.get('enrichment', {}).get('batch_size', 10)}")
        
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
        batch_size = config.get('enrichment', {}).get('batch_size', 10)
        engine = EnrichmentEngine(
            github_token=github_token,
            repos_repository=repos_repository,
            batch_size=batch_size,
            config=config
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
        print(f"  • Total de reintentos: {stats.get('total_retries', 0)}")
        print(f"  • Pausas por rate limit: {stats.get('total_rate_limit_waits', 0)}")
        
        if stats.get('start_time') and stats.get('end_time'):
            duration = (stats['end_time'] - stats['start_time']).total_seconds()
            print(f"\n⏱️  Tiempo total: {duration:.2f}s ({duration/60:.1f} minutos)")
            if stats['total_processed'] > 0:
                avg_time = duration / stats['total_processed']
                print(f"⏱️  Tiempo promedio por repo: {avg_time:.2f}s")
        
        if stats.get('fields_enriched'):
            print(f"\n📝 Top 10 campos enriquecidos:")
            sorted_fields = sorted(stats['fields_enriched'].items(), key=lambda x: x[1], reverse=True)
            for field, count in sorted_fields[:10]:
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
