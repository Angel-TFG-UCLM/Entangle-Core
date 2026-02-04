"""
Script para ejecutar el enriquecimiento de organizaciones.

Calcula métricas quantum:
- quantum_focus_score (0-100)
- quantum_repositories_count
- quantum_contributors_count
- is_quantum_focused (threshold 30%)
"""

import sys
import os

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from src.github.organization_enrichment import OrganizationEnrichmentEngine
from src.core.mongo_repository import MongoRepository
from src.core.config import config
from src.core.logger import logger


def main():
    """Ejecuta el enriquecimiento de organizaciones."""
    
    logger.info("=" * 80)
    logger.info("INICIANDO ENRIQUECIMIENTO DE ORGANIZACIONES")
    logger.info("=" * 80)
    
    # Cargar variables de entorno
    load_dotenv()
    
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        logger.error("❌ GITHUB_TOKEN no configurado en .env")
        return 1
    
    # Obtener parámetros desde variables de entorno o usar defaults
    logger.info("\nConfiguración:")
    logger.info("  • Motor: Super-query GraphQL (1 query por organización)")
    logger.info("  • Campos a enriquecer:")
    logger.info("    - quantum_focus_score (0-100)")
    logger.info("    - quantum_repositories (IDs desde BD local)")
    logger.info("    - top_quantum_contributors")
    logger.info("    - is_quantum_focused (threshold 30%)")
    logger.info("  • Optimizaciones:")
    logger.info("    - Sleep 0.5s entre organizaciones")
    logger.info("    - Try-except por organización (continúa en fallos)")
    logger.info("    - Batch size optimizado para Azure Free Tier")
    
    # Leer parámetros desde variables de entorno
    max_orgs_env = os.getenv('ENRICHMENT_LIMIT')
    max_orgs = int(max_orgs_env) if max_orgs_env else None
    
    batch_size_env = os.getenv('BATCH_SIZE')
    batch_size = int(batch_size_env) if batch_size_env else 100  # ✅ OPTIMIZADO para vCore
    
    force_reenrich_env = os.getenv('FORCE_REENRICHMENT', 'false').lower()
    force_reenrich = force_reenrich_env == 'true'
    
    auto_confirm = os.getenv('AUTO_CONFIRM', 'false').lower() == 'true'
    
    logger.info(f"\nParámetros:")
    logger.info(f"  • Límite: {max_orgs or 'Todas'}")
    logger.info(f"  • Batch size: {batch_size}")
    logger.info(f"  • Force reenrich: {force_reenrich}")
    
    # Confirmar
    if auto_confirm:
        logger.info("\n✓ Auto-confirmación activada, continuando...")
    else:
        response = input("\n¿Desea continuar? (s/n): ")
        if response.lower() not in ['s', 'si', 'sí', 'y', 'yes']:
            logger.info("❌ Operación cancelada por el usuario")
            return 0
    
    try:
        # Crear repositorios
        logger.info("\nInicializando repositorios...")
        orgs_repo = MongoRepository("organizations")
        repos_repo = MongoRepository("repositories")
        users_repo = MongoRepository("users")
        
        # Crear motor de enriquecimiento
        logger.info("Creando motor de enriquecimiento...")
        engine = OrganizationEnrichmentEngine(
            github_token=github_token,
            organizations_repository=orgs_repo,
            repositories_repository=repos_repo,
            users_repository=users_repo,
            batch_size=batch_size,
            sleep_time=0.5  # Para respetar GitHub API Rate Limit
        )
        
        # Ejecutar enriquecimiento
        logger.info("\nEjecutando enriquecimiento de organizaciones...")
        stats = engine.enrich_all_organizations(
            max_orgs=max_orgs,
            force_reenrich=force_reenrich
        )
        
        # Mostrar estadísticas finales
        logger.info("\n" + "=" * 80)
        logger.info("✅ ENRIQUECIMIENTO DE ORGANIZACIONES COMPLETADO")
        logger.info("=" * 80)
        logger.info(f"\n📊 Estadísticas:")
        logger.info(f"  • Organizaciones procesadas: {stats.get('total_processed', 0)}")
        logger.info(f"  • Organizaciones enriquecidas: {stats.get('total_enriched', 0)}")
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
        logger.error(f"\n❌ Error durante el enriquecimiento: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
