"""
Script para verificar que ambos métodos recuperan los mismos campos.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.logger import logger
from src.core.config import Config, ingestion_config
from src.github.graphql_client import GitHubGraphQLClient


def get_repo_fields(repo):
    """Extrae todos los campos disponibles de un repositorio."""
    fields = set()
    
    def extract_keys(obj, prefix=""):
        if isinstance(obj, dict):
            for key, value in obj.items():
                field_name = f"{prefix}.{key}" if prefix else key
                fields.add(field_name)
                if isinstance(value, (dict, list)):
                    extract_keys(value, field_name)
        elif isinstance(obj, list) and obj:
            extract_keys(obj[0], prefix)
    
    extract_keys(repo)
    return fields


def compare_methods():
    """Compara los campos recuperados por ambos métodos."""
    try:
        Config.validate()
        
        logger.info("=" * 80)
        logger.info("🔬 COMPARACIÓN DE CAMPOS RECUPERADOS")
        logger.info("=" * 80)
        
        client = GitHubGraphQLClient()
        
        # Método 1: Búsqueda tradicional (1 repo)
        logger.info("\n📍 Método TRADICIONAL (search_repositories_all_pages)")
        traditional_repos = client.search_repositories_all_pages(
            config_criteria=ingestion_config,
            max_results=1
        )
        
        if not traditional_repos:
            logger.error("❌ No se obtuvo ningún repo con método tradicional")
            return False
        
        traditional_fields = get_repo_fields(traditional_repos[0])
        logger.info(f"  • Campos obtenidos: {len(traditional_fields)}")
        
        # Método 2: Búsqueda segmentada (1 repo)
        logger.info("\n📍 Método SEGMENTADO (search_repositories_segmented)")
        segmented_repos = client.search_repositories_segmented(
            config_criteria=ingestion_config,
            min_stars=10,
            max_stars=999,
            created_year=2023,
            max_results=1
        )
        
        if not segmented_repos:
            logger.error("❌ No se obtuvo ningún repo con método segmentado")
            return False
        
        segmented_fields = get_repo_fields(segmented_repos[0])
        logger.info(f"  • Campos obtenidos: {len(segmented_fields)}")
        
        # Comparar
        logger.info("\n" + "=" * 80)
        logger.info("📊 RESULTADOS DE LA COMPARACIÓN")
        logger.info("=" * 80)
        
        # Campos en común
        common_fields = traditional_fields & segmented_fields
        logger.info(f"\n✅ Campos comunes: {len(common_fields)}")
        
        # Campos solo en tradicional
        only_traditional = traditional_fields - segmented_fields
        if only_traditional:
            logger.warning(f"\n⚠️  Campos SOLO en método tradicional: {len(only_traditional)}")
            for field in sorted(only_traditional):
                logger.warning(f"  - {field}")
        else:
            logger.info("\n✅ No hay campos exclusivos del método tradicional")
        
        # Campos solo en segmentado
        only_segmented = segmented_fields - traditional_fields
        if only_segmented:
            logger.warning(f"\n⚠️  Campos SOLO en método segmentado: {len(only_segmented)}")
            for field in sorted(only_segmented):
                logger.warning(f"  - {field}")
        else:
            logger.info("✅ No hay campos exclusivos del método segmentado")
        
        # Verificación final
        logger.info("\n" + "=" * 80)
        if traditional_fields == segmented_fields:
            logger.info("✅ PERFECTO: Ambos métodos recuperan EXACTAMENTE los mismos campos")
            logger.info("=" * 80)
            return True
        else:
            logger.error("❌ PROBLEMA: Los métodos NO recuperan los mismos campos")
            logger.info("=" * 80)
            return False
        
    except Exception as e:
        logger.error(f"❌ Error en la comparación: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = compare_methods()
    sys.exit(0 if success else 1)
