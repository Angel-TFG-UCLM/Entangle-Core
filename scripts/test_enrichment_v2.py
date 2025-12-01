"""
Script de prueba para el UserEnrichmentEngine v2.0

Prueba el nuevo motor de enriquecimiento con super-query en un usuario de muestra.
"""

import os
import sys
from dotenv import load_dotenv

# Agregar el directorio raíz al PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.github.user_enrichment import UserEnrichmentEngine
from src.core.mongo_repository import MongoRepository
from src.core.config import Config
from src.core.logger import logger


def test_enrichment_v2():
    """
    Prueba el motor de enriquecimiento v2.0 con un usuario de muestra.
    """
    logger.info("=" * 80)
    logger.info("🧪 PROBANDO UserEnrichmentEngine v2.0")
    logger.info("=" * 80)
    
    # Cargar configuración
    load_dotenv()
    config = Config()
    
    # Conectar a MongoDB
    users_repo = MongoRepository(config.get_mongo_uri(), "github_quantum", "users")
    repos_repo = MongoRepository(config.get_mongo_uri(), "github_quantum", "repositories")
    
    # Inicializar motor con batch_size=1 para test
    engine = UserEnrichmentEngine(
        github_token=config.github_token,
        users_repository=users_repo,
        repos_repository=repos_repo,
        batch_size=1
    )
    
    logger.info("\n🔍 Buscando usuario de prueba...")
    
    # Buscar un usuario sin enrichment_status o con is_complete=false
    test_user = users_repo.collection.find_one({
        "$or": [
            {"enrichment_status": {"$exists": False}},
            {"enrichment_status.is_complete": False}
        ]
    })
    
    if not test_user:
        logger.info("⚠️  No hay usuarios para enriquecer, probando con usuario aleatorio...")
        test_user = users_repo.collection.find_one({})
    
    if not test_user:
        logger.error("❌ No hay usuarios en la base de datos")
        return
    
    login = test_user.get("login")
    logger.info(f"✅ Usuario de prueba seleccionado: {login}")
    
    # Estado ANTES del enriquecimiento
    logger.info("\n📊 ESTADO ANTES DEL ENRIQUECIMIENTO:")
    logger.info(f"   - Email: {test_user.get('email', 'N/A')}")
    logger.info(f"   - Bio: {test_user.get('bio', 'N/A')[:50] if test_user.get('bio') else 'N/A'}...")
    logger.info(f"   - Organizaciones: {len(test_user.get('organizations', []))}")
    logger.info(f"   - Repos pinned: {len(test_user.get('pinned_repositories', []))}")
    logger.info(f"   - Top languages: {test_user.get('top_languages', 'N/A')}")
    logger.info(f"   - Quantum repos: {len(test_user.get('quantum_repositories', []))}")
    logger.info(f"   - Quantum expertise: {test_user.get('quantum_expertise_score', 'N/A')}")
    
    old_status = test_user.get("enrichment_status", {})
    logger.info(f"   - Status previo: {old_status.get('is_complete', False)} (completo)")
    logger.info(f"   - Campos enriquecidos: {old_status.get('total_fields_enriched', 0)}")
    logger.info(f"   - Campos faltantes: {len(old_status.get('fields_missing', []))}")
    
    # Ejecutar enriquecimiento
    logger.info("\n🚀 EJECUTANDO ENRIQUECIMIENTO v2.0...")
    stats = engine.enrich_all_users(max_users=1, force_reenrich=True)
    
    # Estado DESPUÉS del enriquecimiento
    logger.info("\n📊 ESTADO DESPUÉS DEL ENRIQUECIMIENTO:")
    enriched_user = users_repo.collection.find_one({"login": login})
    
    logger.info(f"   - Email: {enriched_user.get('email', 'N/A')}")
    logger.info(f"   - Bio: {enriched_user.get('bio', 'N/A')[:50] if enriched_user.get('bio') else 'N/A'}...")
    logger.info(f"   - Organizaciones: {len(enriched_user.get('organizations', []))}")
    logger.info(f"   - Repos pinned: {len(enriched_user.get('pinned_repositories', []))}")
    logger.info(f"   - Top languages: {enriched_user.get('top_languages', 'N/A')}")
    logger.info(f"   - Quantum repos: {len(enriched_user.get('quantum_repositories', []))}")
    logger.info(f"   - Quantum expertise: {enriched_user.get('quantum_expertise_score', 'N/A')}")
    logger.info(f"   - Follower/Following ratio: {enriched_user.get('follower_following_ratio', 'N/A')}")
    logger.info(f"   - Stars per repo: {enriched_user.get('stars_per_repo', 'N/A')}")
    
    new_status = enriched_user.get("enrichment_status", {})
    logger.info(f"\n📋 ENRICHMENT STATUS:")
    logger.info(f"   - Completo: {new_status.get('is_complete', False)}")
    logger.info(f"   - Última actualización: {new_status.get('last_enriched', 'N/A')}")
    logger.info(f"   - Campos enriquecidos: {new_status.get('total_fields_enriched', 0)}")
    logger.info(f"   - Campos faltantes: {len(new_status.get('fields_missing', []))}")
    logger.info(f"   - Versión: {new_status.get('version', 'N/A')}")
    
    if new_status.get('fields_missing'):
        logger.info(f"   - Lista de faltantes: {', '.join(new_status.get('fields_missing', []))}")
    
    # Comparación
    logger.info("\n📈 COMPARACIÓN:")
    old_count = old_status.get('total_fields_enriched', 0)
    new_count = new_status.get('total_fields_enriched', 0)
    difference = new_count - old_count
    
    logger.info(f"   - Campos antes: {old_count}")
    logger.info(f"   - Campos después: {new_count}")
    logger.info(f"   - Diferencia: {difference:+d}")
    
    # Verificar campos eliminados no presentes
    logger.info("\n🔍 VERIFICANDO CAMPOS ELIMINADOS NO PRESENTES:")
    eliminated_fields = [
        "quantum_gists", "quantum_gists_count", "social_network_sample",
        "notable_issues_prs", "languages_detailed", "top_contributed_repos",
        "gists", "sponsors", "packages", "projects"
    ]
    
    found_eliminated = [field for field in eliminated_fields if field in enriched_user]
    
    if found_eliminated:
        logger.warning(f"   ⚠️  Campos eliminados encontrados: {', '.join(found_eliminated)}")
    else:
        logger.info(f"   ✅ Ningún campo eliminado presente (correcto)")
    
    logger.info("\n" + "=" * 80)
    logger.info("✅ PRUEBA COMPLETADA")
    logger.info("=" * 80)


if __name__ == "__main__":
    try:
        test_enrichment_v2()
    except Exception as e:
        logger.error(f"❌ Error en prueba: {e}")
        raise
