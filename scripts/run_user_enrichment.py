"""
Script para ejecutar el enriquecimiento de usuarios.

Completa información de usuarios ya ingestados:
- Repositorios destacados (pinned)
- Organizaciones
- Repositorios quantum
- Lenguajes principales
- Actividad reciente
- Métricas sociales
- Quantum expertise score
"""

import sys
import os

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from src.github.user_enrichment import run_user_enrichment
from src.core.logger import logger


def main():
    """Ejecuta el enriquecimiento de usuarios."""
    
    logger.info("=" * 80)
    logger.info("🚀 INICIANDO ENRIQUECIMIENTO DE USUARIOS")
    logger.info("=" * 80)
    
    # Cargar variables de entorno
    load_dotenv()
    
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        logger.error("❌ GITHUB_TOKEN no configurado en .env")
        return
    
    # Obtener parámetros
    logger.info("\n📋 Configuración:")
    logger.info("  • Campos a enriquecer:")
    logger.info("    - Repositorios destacados (pinned)")
    logger.info("    - Organizaciones")
    logger.info("    - Repositorios quantum relacionados")
    logger.info("    - Top lenguajes de programación")
    logger.info("    - Actividad reciente (30 días)")
    logger.info("    - Métricas sociales")
    logger.info("    - Quantum expertise score")
    
    # Límite de usuarios (opcional)
    max_users_input = input("\n¿Límite de usuarios? (Enter para todos): ").strip()
    max_users = int(max_users_input) if max_users_input else None
    
    # Tamaño de lote
    batch_size_input = input("Tamaño de lote (default=10): ").strip()
    batch_size = int(batch_size_input) if batch_size_input else 10
    
    # Confirmar
    response = input("\n¿Desea continuar? (s/n): ")
    if response.lower() not in ['s', 'si', 'sí', 'y', 'yes']:
        logger.info("❌ Operación cancelada por el usuario")
        return
    
    try:
        # Ejecutar enriquecimiento
        logger.info("\n🔄 Ejecutando enriquecimiento de usuarios...")
        stats = run_user_enrichment(
            max_users=max_users,
            batch_size=batch_size
        )
        
        # Mostrar estadísticas finales
        logger.info("\n" + "=" * 80)
        logger.info("✅ ENRIQUECIMIENTO DE USUARIOS COMPLETADO")
        logger.info("=" * 80)
        logger.info(f"\n📊 Estadísticas:")
        logger.info(f"  • Usuarios procesados: {stats.get('total_processed', 0)}")
        logger.info(f"  • Usuarios enriquecidos: {stats.get('total_enriched', 0)}")
        logger.info(f"  • Errores: {stats.get('total_errors', 0)}")
        
        logger.info(f"\n📈 Campos enriquecidos:")
        fields = stats.get('fields_enriched', {})
        for field, count in sorted(fields.items(), key=lambda x: x[1], reverse=True):
            logger.info(f"  • {field}: {count}")
        
        duration_seconds = (stats.get('end_time') - stats.get('start_time')).total_seconds()
        logger.info(f"\n⏱️  Duración: {duration_seconds:.2f}s ({duration_seconds/60:.1f} minutos)")
        
    except KeyboardInterrupt:
        logger.warning("\n⚠️  Operación interrumpida por el usuario")
    except Exception as e:
        logger.error(f"\n❌ Error durante el enriquecimiento: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit(main() or 0)
