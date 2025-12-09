"""
Script para ejecutar la ingesta de organizaciones desde usuarios.

Estrategia Bottom-Up: descubre organizaciones desde usuarios ya ingestados.
"""

import sys
import os

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from src.github.organization_ingestion import OrganizationIngestionEngine
from src.github.graphql_client import GitHubGraphQLClient
from src.core.mongo_repository import MongoRepository
from src.core.config import config
from src.core.logger import logger


def main():
    """Ejecuta la ingesta de organizaciones."""
    
    logger.info("=" * 80)
    logger.info("INICIANDO INGESTA DE ORGANIZACIONES")
    logger.info("=" * 80)
    
    # Cargar variables de entorno
    load_dotenv()
    
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        logger.error("❌ GITHUB_TOKEN no configurado en .env")
        return 1
    
    # Confirmar con usuario
    logger.info("\nConfiguración:")
    logger.info("  • Estrategia: Bottom-Up (desde usuarios)")
    logger.info("  • Fuente: Campo 'organizations' de usuarios")
    logger.info("  • Deduplicación: por login de organización")
    logger.info("  • Almacenamiento: MongoDB (colección 'organizations')")
    logger.info("  • Rate Limit: batch_size=5, sleep=0.5s")
    
    response = input("\n¿Desea continuar? (s/n): ")
    if response.lower() not in ['s', 'si', 'sí', 'y', 'yes']:
        logger.info("❌ Operación cancelada por el usuario")
        return 0
    
    try:
        # Crear repositorios
        logger.info("\nInicializando repositorios...")
        users_repo = MongoRepository("users")
        orgs_repo = MongoRepository("organizations", unique_fields=["id"])
        
        # Crear motor de ingesta
        logger.info("Creando motor de ingesta...")
        engine = OrganizationIngestionEngine(
            github_token=github_token,
            users_repository=users_repo,
            organizations_repository=orgs_repo,
            batch_size=5
        )
        
        # Ejecutar ingesta
        logger.info("\nEjecutando ingesta de organizaciones...")
        stats = engine.run(force_update=False)
        
        # Mostrar estadísticas finales
        logger.info("\n" + "=" * 80)
        logger.info("✅ INGESTA DE ORGANIZACIONES COMPLETADA")
        logger.info("=" * 80)
        logger.info(f"\n📊 Estadísticas:")
        logger.info(f"  • Organizaciones descubiertas: {stats.get('total_discovered', 0)}")
        logger.info(f"  • Organizaciones procesadas: {stats.get('total_processed', 0)}")
        logger.info(f"  • Organizaciones insertadas: {stats.get('total_inserted', 0)}")
        logger.info(f"  • Organizaciones actualizadas: {stats.get('total_updated', 0)}")
        logger.info(f"  • Organizaciones saltadas: {stats.get('total_skipped', 0)}")
        
        if stats.get('total_errors', 0) > 0:
            logger.warning(f"\n⚠️  Errores: {stats['total_errors']}")
        
        duration = stats.get('duration_seconds', 0)
        logger.info(f"\nDuración: {duration:.2f}s ({duration/60:.1f} minutos)")
        
        return 0
        
    except KeyboardInterrupt:
        logger.warning("\n⚠️  Operación interrumpida por el usuario")
        return 0
    except Exception as e:
        logger.error(f"\n❌ Error durante la ingesta: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
