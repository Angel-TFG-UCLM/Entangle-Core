"""
Test de segmentación dinámica con un segmento pequeño.

Este script prueba la funcionalidad de segmentación dinámica
ejecutando solo un segmento pequeño (10-49 estrellas, año 2024).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.logger import logger
from src.core.config import Config, ingestion_config
from src.github.graphql_client import GitHubGraphQLClient


def test_single_segment():
    """Prueba un solo segmento de búsqueda."""
    try:
        Config.validate()
        
        logger.info("=" * 80)
        logger.info("🧪 TEST DE SEGMENTACIÓN DINÁMICA - UN SEGMENTO")
        logger.info("=" * 80)
        
        # Crear cliente
        client = GitHubGraphQLClient()
        
        # Probar un segmento: stars:10..999, año 2023 (más amplio)
        logger.info("\n📍 Probando segmento: stars:10..999 created:2023")
        
        repos = client.search_repositories_segmented(
            config_criteria=ingestion_config,
            min_stars=10,
            max_stars=999,
            created_year=2023,
            max_results=50  # Limitar a 50 para el test
        )
        
        logger.info(f"\n✅ Test completado:")
        logger.info(f"  • Repositorios encontrados: {len(repos)}")
        
        if repos:
            logger.info(f"\n📋 Primeros 3 repositorios:")
            for i, repo in enumerate(repos[:3], 1):
                logger.info(f"  {i}. {repo.get('nameWithOwner')} - ⭐ {repo.get('stargazerCount')}")
        
        logger.info("\n" + "=" * 80)
        logger.info("✅ TEST EXITOSO")
        logger.info("=" * 80)
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error en el test: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = test_single_segment()
    sys.exit(0 if success else 1)
