"""
Script para ejecutar el enriquecimiento de usuarios v2.0.

Completa información de usuarios ya ingestados usando super-query:
- Repositorios destacados (pinned)
- Organizaciones
- Repositorios quantum
- Lenguajes principales
- Actividad reciente
- Métricas sociales
- Quantum expertise score

VERSIÓN 2.0: Una sola query GraphQL por usuario, optimizado para Azure Free Tier.
"""

import sys
import os

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from src.github.user_enrichment import UserEnrichmentEngine
from src.core.mongo_repository import MongoRepository
from src.core.logger import logger


def main():
    """Ejecuta el enriquecimiento de usuarios v2.0."""
    
    logger.info("=" * 80)
    logger.info("INICIANDO ENRIQUECIMIENTO DE USUARIOS v2.0")
    logger.info("=" * 80)
    
    # Cargar variables de entorno
    load_dotenv()
    
    # Obtener token de GitHub
    github_token = os.getenv("GITHUB_TOKEN")
    
    if not github_token:
        logger.error("GITHUB_TOKEN no configurado en .env")
        return 1
    
    # Obtener parámetros desde variables de entorno o usar defaults
    logger.info("\nConfiguración v2.0:")
    logger.info("  • Motor: Super-query GraphQL (1 query por usuario)")
    logger.info("  • Campos a enriquecer:")
    logger.info("    - Repositorios destacados (pinned)")
    logger.info("    - Organizaciones")
    logger.info("    - Repositorios quantum relacionados")
    logger.info("    - Top lenguajes (calculado en memoria)")
    logger.info("    - Métricas sociales")
    logger.info("    - Quantum expertise score")
    logger.info("  • Optimizaciones:")
    logger.info("    - Sleep 0.5s entre usuarios")
    logger.info("    - Try-except por usuario (continúa en fallos)")
    logger.info("    - Batch size optimizado para Azure Free Tier")
    
    # Leer parámetros desde variables de entorno
    max_users_env = os.getenv('ENRICHMENT_LIMIT')
    max_users = int(max_users_env) if max_users_env else None
    
    batch_size_env = os.getenv('BATCH_SIZE')
    batch_size = int(batch_size_env) if batch_size_env else 5
    
    force_reenrich_env = os.getenv('FORCE_REENRICHMENT', 'false').lower()
    force_reenrich = force_reenrich_env == 'true'
    
    auto_confirm = os.getenv('AUTO_CONFIRM', 'false').lower() == 'true'
    
    logger.info(f"\nParámetros:")
    logger.info(f"  • Límite: {max_users or 'Todos'}")
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
        # Conectar a MongoDB
        logger.info("\nConectando a MongoDB...")
        users_repo = MongoRepository("users")
        repos_repo = MongoRepository("repositories")
        
        # Inicializar motor
        logger.info("Inicializando UserEnrichmentEngine v2.0...")
        engine = UserEnrichmentEngine(
            github_token=github_token,
            users_repository=users_repo,
            repos_repository=repos_repo,
            batch_size=batch_size
        )
        
        # Ejecutar enriquecimiento
        logger.info("\nEjecutando enriquecimiento de usuarios...")
        stats = engine.enrich_all_users(
            max_users=max_users,
            force_reenrich=force_reenrich
        )
        
        # Mostrar estadísticas finales
        logger.info("\n" + "=" * 80)
        logger.info("✅ ENRIQUECIMIENTO DE USUARIOS v2.0 COMPLETADO")
        logger.info("=" * 80)
        logger.info(f"\n📊 Estadísticas:")
        logger.info(f"  • Usuarios procesados: {stats.get('total_processed', 0)}")
        logger.info(f"  • Usuarios enriquecidos: {stats.get('total_enriched', 0)}")
        logger.info(f"  • Errores: {stats.get('total_errors', 0)}")
        
        if 'duration_seconds' in stats:
            duration = stats['duration_seconds']
            logger.info(f"\n⏱Duración: {duration:.2f}s ({duration/60:.1f} minutos)")
        
        return 0
        
    except KeyboardInterrupt:
        logger.warning("\nOperación interrumpida por el usuario")
        return 1
    except Exception as e:
        logger.error(f"\n❌ Error durante el enriquecimiento: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit(main() or 0)
