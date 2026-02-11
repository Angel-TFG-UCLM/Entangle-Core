"""
Script para ejecutar ingesta de repositorios con segmentación dinámica.

Este script ejecuta la ingesta completa con segmentación automática,
superando el límite de 1000 resultados de GitHub Search API.

Uso:
    python scripts/run_repositories_ingestion.py
"""

import sys
import os

# Agregar el directorio raíz al path para poder importar módulos
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.logger import logger
from src.core.config import Config, ingestion_config
from src.github.repositories_ingestion import IngestionEngine


def main():
    """Ejecuta la ingesta con segmentación dinámica."""
    try:
        # Validar configuración
        Config.validate()
        
        logger.info("=" * 80)
        logger.info("INICIANDO INGESTA CON SEGMENTACIÓN DINÁMICA")
        logger.info("=" * 80)
        
        # Verificar que la segmentación esté habilitada
        if not ingestion_config.enable_segmentation:
            logger.warning("⚠️  La segmentación no está habilitada en la configuración")
            logger.info("Por favor, establece 'enable_segmentation': true en ingestion_config.json")
            return
        
        segmentation = ingestion_config.segmentation
        if not segmentation:
            logger.error("❌ No se encontró configuración de segmentación")
            return
        
        # Mostrar configuración de segmentación
        star_ranges = segmentation.get("stars", [])
        created_years = segmentation.get("created_years", [])
        
        logger.info(f"\nConfiguración de Segmentación:")
        logger.info(f"  • Rangos de estrellas: {len(star_ranges)}")
        for i, (min_s, max_s) in enumerate(star_ranges, 1):
            logger.info(f"    {i}. {min_s:,} - {max_s:,} estrellas")
        
        logger.info(f"\n  • Años de creación: {len(created_years)}")
        logger.info(f"    {created_years}")
        
        total_queries = len(star_ranges) * len(created_years)
        logger.info(f"\n  • Total de consultas estimadas: {total_queries}")
        logger.info(f"  • Repositorios estimados: {total_queries * 1000:,} (máximo teórico)")
        
        # Verificar auto-confirmación desde variable de entorno
        auto_confirm = os.getenv('AUTO_CONFIRM', 'false').lower() == 'true'
        
        if auto_confirm:
            logger.info("\n✓ Auto-confirmación activada, continuando...")
        else:
            # Preguntar confirmación
            print("\n¿Deseas continuar con la ingesta segmentada? [s/N]: ", end="")
            response = input().strip().lower()
            
            if response not in ['s', 'si', 'sí', 'y', 'yes']:
                logger.info("Operación cancelada por el usuario")
                return
        
        # Crear motor de ingesta
        engine = IngestionEngine(
            incremental=False,
            batch_size=500  # ✅ OPTIMIZADO para vCore
        )
        
        # Ejecutar ingesta completa con segmentación
        logger.info("\nIniciando proceso de ingesta...")
        result = engine.run(
            max_results=None,  # Sin límite, obtener todos los segmentos
            save_to_json=False
        )
        
        # Mostrar resumen final
        logger.info("\n" + "=" * 80)
        logger.info("✅ INGESTA SEGMENTADA COMPLETADA")
        logger.info("=" * 80)
        logger.info(f"\nResumen:")
        logger.info(f"  • Repositorios encontrados: {result['summary']['total_found']:,}")
        logger.info(f"  • Repositorios válidos: {result['summary']['total_filtered']:,}")
        logger.info(f"  • Nuevos en DB: {result['summary']['repositories_inserted']:,}")
        logger.info(f"  • Actualizados en DB: {result['summary']['repositories_updated']:,}")
        # logger.info(f"  • Relaciones creadas: {result['summary']['relations_created']:,}")  # DESHABILITADO: Feature deprecada
        logger.info(f"  • Duración total: {result['timing']['total']}")
        
    except KeyboardInterrupt:
        logger.warning("\n\n⚠️  Proceso interrumpido por el usuario")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n❌ Error durante la ingesta: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
