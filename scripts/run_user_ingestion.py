"""
Script para ejecutar la ingesta de usuarios desde repositorios.

Extrae usuarios del campo 'collaborators' de repositorios ya ingestados.
"""

import sys
import os

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from src.github.user_ingestion import run_user_ingestion
from src.core.logger import logger


def main():
    """Ejecuta la ingesta de usuarios."""
    
    logger.info("=" * 80)
    logger.info("INICIANDO INGESTA DE USUARIOS")
    logger.info("=" * 80)
    
    # Cargar variables de entorno
    load_dotenv()
    
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        logger.error("❌ GITHUB_TOKEN no configurado en .env")
        return
    
    # Confirmar con usuario
    logger.info("\nConfiguración:")
    logger.info("  • Fuentes: colaboradores, contributors, watchers, stargazers")
    logger.info("  • Deduplicación: por ID de usuario")
    logger.info("  • Almacenamiento: MongoDB (colección 'users')")
    
    # Verificar auto-confirmación desde variable de entorno
    auto_confirm = os.getenv('AUTO_CONFIRM', 'false').lower() == 'true'
    
    if auto_confirm:
        logger.info("\n✓ Auto-confirmación activada, continuando...")
    else:
        response = input("\n¿Desea continuar? (s/n): ")
        if response.lower() not in ['s', 'si', 'sí', 'y', 'yes']:
            logger.info("❌ Operación cancelada por el usuario")
            return
    
    try:
        # Ejecutar ingesta
        logger.info("\n🔄 Ejecutando ingesta de usuarios...")
        stats = run_user_ingestion()
        
        # Mostrar estadísticas finales
        logger.info("\n" + "=" * 80)
        logger.info("✅ INGESTA DE USUARIOS COMPLETADA")
        logger.info("=" * 80)
        logger.info(f"\nEstadísticas:")
        logger.info(f"  • Repositorios procesados: {stats.get('repos_processed', 0)}")
        logger.info(f"  • Usuarios encontrados: {stats.get('users_found', 0)}")
        logger.info(f"  • Usuarios únicos: {stats.get('unique_users', 0)}")
        logger.info(f"  • Usuarios nuevos insertados: {stats.get('users_inserted', 0)}")
        logger.info(f"  • Usuarios ya existentes: {stats.get('users_existing', 0)}")
        
        logger.info(f"\nFuentes:")
        sources = stats.get('sources', {})
        logger.info(f"  • Colaboradores: {sources.get('collaborators', 0)}")
        logger.info(f"  • Contributors: {sources.get('contributors', 0)}")
        logger.info(f"  • Watchers: {sources.get('watchers', 0)}")
        logger.info(f"  • Stargazers: {sources.get('stargazers', 0)}")
        
        if stats.get('errors', 0) > 0:
            logger.warning(f"\n⚠️  Errores: {stats['errors']}")
        
        duration = stats.get('duration_seconds', 0)
        logger.info(f"\nDuración: {duration:.2f}s ({duration/60:.1f} minutos)")
        
    except KeyboardInterrupt:
        logger.warning("\n⚠️  Operación interrumpida por el usuario")
    except Exception as e:
        logger.error(f"\n❌ Error durante la ingesta: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit(main() or 0)
