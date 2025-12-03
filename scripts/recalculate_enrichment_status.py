"""
Script para recalcular enrichment_status de todos los usuarios existentes.

OBJETIVO: Corregir el campo fields_missing que marcaba incorrectamente a 
todos los usuarios como incompletos.

LÓGICA CORREGIDA:
- Campos faltantes: esperados que NO están en el usuario (verificación correcta)
- is_complete: basado en campos críticos (organizations, pinned_repositories, top_languages)
"""

import os
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Agregar el directorio raíz al PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.mongo_repository import MongoRepository
from src.core.config import Config
from src.core.logger import logger


def recalculate_enrichment_status():
    """
    Recalcula el enrichment_status de todos los usuarios con enriquecimiento previo.
    """
    logger.info("=" * 80)
    logger.info("🔄 RECALCULANDO ENRICHMENT_STATUS DE USUARIOS")
    logger.info("=" * 80)
    
    # Cargar configuración
    load_dotenv()
    config = Config()
    
    # Conectar a MongoDB
    users_repo = MongoRepository(config.get_mongo_uri(), "github_quantum", "users")
    
    # Obtener usuarios con enrichment_status previo
    users = list(users_repo.collection.find(
        {"enrichment_status": {"$exists": True}}
    ))
    
    total_users = len(users)
    logger.info(f"📊 Total usuarios con enrichment_status: {total_users}")
    
    if total_users == 0:
        logger.info("✅ No hay usuarios con enrichment_status para recalcular")
        return
    
    # Campos esperados
    expected_fields = [
        "email", "bio", "company", "location", "pronouns", "website_url",
        "twitter_username", "organizations", "pinned_repositories", 
        "top_languages", "social_accounts", "status_message", "status_emoji",
        "quantum_repositories", "quantum_expertise_score", 
        "follower_following_ratio", "stars_per_repo"
    ]
    
    # Campos críticos para determinar is_complete
    critical_fields = ["organizations", "pinned_repositories", "top_languages"]
    
    # Contadores
    updated_count = 0
    now_complete = 0
    still_incomplete = 0
    
    for i, user in enumerate(users, 1):
        login = user.get("login")
        
        # Campos enriquecidos: los que existen y no son None/[]/{}
        fields_enriched = [
            field for field in expected_fields
            if user.get(field) is not None and user.get(field) != [] and user.get(field) != {}
        ]
        
        # Campos faltantes: esperados que NO están en el usuario
        fields_missing = [
            field for field in expected_fields
            if user.get(field) is None
        ]
        
        # Determinar si está completo (tiene todos los campos críticos)
        is_complete = all(user.get(field) is not None for field in critical_fields)
        
        # Actualizar enrichment_status
        enrichment_status = user.get("enrichment_status", {})
        old_is_complete = enrichment_status.get("is_complete", False)
        
        new_enrichment_status = {
            "is_complete": is_complete,
            "last_enriched": enrichment_status.get("last_enriched", datetime.now()),
            "fields_enriched": fields_enriched,
            "fields_missing": fields_missing,
            "total_fields_enriched": len(fields_enriched),
            "version": "2.0.0"
        }
        
        # Actualizar en BD
        users_repo.collection.update_one(
            {"_id": user.get("_id")},
            {"$set": {"enrichment_status": new_enrichment_status}}
        )
        
        updated_count += 1
        
        # Contadores de completitud
        if is_complete:
            now_complete += 1
        else:
            still_incomplete += 1
        
        # Log de progreso
        if i % 1000 == 0 or i == total_users:
            logger.info(f"📊 Procesados: {i}/{total_users} | Completos: {now_complete} | Incompletos: {still_incomplete}")
    
    logger.info("\n" + "=" * 80)
    logger.info("📊 RESUMEN DE RECALCULACIÓN")
    logger.info("=" * 80)
    logger.info(f"✅ Total usuarios procesados: {total_users}")
    logger.info(f"✅ Total actualizados: {updated_count}")
    logger.info(f"✅ Usuarios completos: {now_complete} ({now_complete/total_users*100:.1f}%)")
    logger.info(f"⚠️  Usuarios incompletos: {still_incomplete} ({still_incomplete/total_users*100:.1f}%)")
    
    # Verificación de muestra
    logger.info("\n📋 VERIFICANDO MUESTRA DE USUARIOS:")
    sample_users = list(users_repo.collection.find(
        {"enrichment_status.is_complete": True}
    ).limit(3))
    
    for user in sample_users:
        login = user.get("login")
        status = user.get("enrichment_status", {})
        fields_enriched = status.get("fields_enriched", [])
        fields_missing = status.get("fields_missing", [])
        
        logger.info(f"\n👤 Usuario: {login}")
        logger.info(f"   ✅ Campos enriquecidos: {len(fields_enriched)}")
        logger.info(f"   ⚠️  Campos faltantes: {len(fields_missing)}")
        logger.info(f"   📝 Faltantes: {', '.join(fields_missing) if fields_missing else 'ninguno'}")


if __name__ == "__main__":
    try:
        recalculate_enrichment_status()
    except Exception as e:
        logger.error(f"❌ Error en recalculación: {e}")
        raise
