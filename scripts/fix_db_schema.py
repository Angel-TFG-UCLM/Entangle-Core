#!/usr/bin/env python3
"""
Script de Migración v3.0 - Limpieza y Corrección de Esquema de Base de Datos
==============================================================================

Este script arregla la base de datos existente para alinearla con el modelo User v3.0.

ACCIONES:
1. BORRAR campos obsoletos que ya no existen en el modelo
2. CORREGIR campos nulos a listas vacías
3. RECALCULAR status de enriquecimiento con lógica realista

Ejecutar con: python scripts/fix_db_schema.py
"""

import sys
import os
from datetime import datetime
from pymongo import MongoClient, UpdateOne
from typing import Dict, Any, List

# Añadir src al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.core.logger import logger
from src.core.config import Config


class SchemaFixEngine:
    """Motor de corrección de esquema de base de datos."""
    
    # Campos obsoletos que ya NO existen en User v3.0
    OBSOLETE_FIELDS = [
        "projects",
        "sponsors",  # Lista (mantener sponsors_count)
        "packages",  # Lista (mantener packages_count)
        "social_network_sample",
        "notable_issues_prs",
        "languages_detailed",
        "quantum_gists",
        "quantum_gists_count",
        "social_accounts",
        "status",
        "interaction_ability",
        "hasSponsorshipsListing",
        "monthlyEstimatedSponsorsIncomeInCents",
        "pronouns",
        "repositories",
        "starred_repositories",
        "contributions",
        "contributions_by_repository",
        "private_repos_count",
        "owned_private_repos_count",
        "is_bounty_hunter",
        "is_campus_expert",
        "is_developer_program_member",
        "is_employee",
        "is_github_star",
        "is_site_admin",
        "is_viewer",
        "viewing_user_can_follow",
        "viewing_user_is_following",
        "can_receive_organization_emails_when_notifications_restricted",
        "has_sponsorships_featuring_enabled",
        "estimated_next_sponsors_payout_in_cents",
        "social_profile_enriched",
        "status_message",
        "status_emoji",
        "recent_commits_30d",
        "recent_issues_30d",
        "recent_prs_30d",
        "recent_reviews_30d",
        "repository_references",
        "custom_properties",
        "is_sponsoring_viewer",
        "monthly_estimated_sponsors_income",
        "top_contributed_repos"
    ]
    
    # Listas que deben ser [] en vez de None
    LIST_FIELDS = [
        "organizations",
        "pinned_repositories",
        "top_languages",
        "quantum_repositories",
        "extracted_from"
    ]
    
    def __init__(self):
        """Inicializa conexión a MongoDB."""
        try:
            self.client = MongoClient(Config.MONGO_URI)
            self.db = self.client[Config.MONGO_DB_NAME]
            self.users_collection = self.db["users"]
            logger.info("✅ Conexión a MongoDB establecida")
        except Exception as e:
            logger.error(f"❌ Error conectando a MongoDB: {e}")
            raise
    
    def run_migration(self):
        """Ejecuta la migración completa."""
        logger.info("\n" + "="*80)
        logger.info("🚀 INICIANDO MIGRACIÓN DE ESQUEMA v3.0")
        logger.info("="*80 + "\n")
        
        # Contar usuarios totales
        total_users = self.users_collection.count_documents({})
        logger.info(f"📊 Total de usuarios en BD: {total_users:,}")
        
        # PASO 1: Borrar campos obsoletos
        logger.info("\n" + "-"*80)
        logger.info("PASO 1: Eliminando campos obsoletos...")
        logger.info("-"*80)
        self._delete_obsolete_fields()
        
        # PASO 2: Corregir listas nulas
        logger.info("\n" + "-"*80)
        logger.info("PASO 2: Corrigiendo campos nulos a listas vacías...")
        logger.info("-"*80)
        self._fix_null_lists()
        
        # PASO 3: Recalcular status de enriquecimiento
        logger.info("\n" + "-"*80)
        logger.info("PASO 3: Recalculando enrichment_status con lógica v3.0...")
        logger.info("-"*80)
        self._recalculate_enrichment_status()
        
        logger.info("\n" + "="*80)
        logger.info("✅ MIGRACIÓN COMPLETADA CON ÉXITO")
        logger.info("="*80 + "\n")
    
    def _delete_obsolete_fields(self):
        """Elimina campos obsoletos de todos los documentos."""
        unset_dict = {field: "" for field in self.OBSOLETE_FIELDS}
        
        result = self.users_collection.update_many(
            {},
            {"$unset": unset_dict}
        )
        
        logger.info(f"✅ Documentos modificados: {result.modified_count:,}")
        logger.info(f"   Campos eliminados: {len(self.OBSOLETE_FIELDS)}")
        logger.info(f"   Campos: {', '.join(self.OBSOLETE_FIELDS[:10])}...")
    
    def _fix_null_lists(self):
        """Convierte campos nulos a listas vacías."""
        operations = []
        
        # Buscar documentos con listas nulas
        for field in self.LIST_FIELDS:
            query = {field: {"$in": [None, "null"]}}
            docs_with_null = self.users_collection.find(query, {"_id": 1})
            
            for doc in docs_with_null:
                operations.append(
                    UpdateOne(
                        {"_id": doc["_id"]},
                        {"$set": {field: []}}
                    )
                )
        
        if operations:
            result = self.users_collection.bulk_write(operations)
            logger.info(f"✅ Documentos corregidos: {result.modified_count:,}")
            logger.info(f"   Campos convertidos: {', '.join(self.LIST_FIELDS)}")
        else:
            logger.info("✅ No se encontraron listas nulas para corregir")
    
    def _recalculate_enrichment_status(self):
        """
        Recalcula enrichment_status con lógica v3.0.
        
        CRITERIO v3.0:
        - Si tiene quantum_expertise_score != null → is_complete = True
        - fields_missing = [] (ya no reportamos campos opcionales)
        - version = "3.0"
        """
        # Usuarios con quantum_expertise_score
        users_with_score = self.users_collection.find(
            {"quantum_expertise_score": {"$ne": None}},
            {"_id": 1, "login": 1, "quantum_expertise_score": 1}
        )
        
        operations = []
        count = 0
        
        for user in users_with_score:
            count += 1
            new_status = {
                "is_complete": True,
                "version": "3.0",
                "last_check": datetime.now().isoformat(),
                "fields_missing": []
            }
            
            operations.append(
                UpdateOne(
                    {"_id": user["_id"]},
                    {"$set": {"enrichment_status": new_status}}
                )
            )
            
            # Batch de 1000 para no sobrecargar
            if len(operations) >= 1000:
                result = self.users_collection.bulk_write(operations)
                logger.info(f"   Procesados: {count:,} usuarios...")
                operations = []
        
        # Procesar restantes
        if operations:
            result = self.users_collection.bulk_write(operations)
        
        logger.info(f"✅ Total usuarios marcados como completos: {count:,}")
        
        # Usuarios SIN quantum_expertise_score
        users_without_score = self.users_collection.count_documents(
            {"quantum_expertise_score": None}
        )
        
        if users_without_score > 0:
            logger.info(f"⚠️  Usuarios sin quantum_expertise_score: {users_without_score:,}")
            logger.info(f"   Estos usuarios necesitan enriquecimiento")
    
    def close(self):
        """Cierra la conexión a MongoDB."""
        self.client.close()
        logger.info("🔒 Conexión a MongoDB cerrada")


def main():
    """Punto de entrada del script."""
    engine = None
    
    try:
        # Confirmar antes de ejecutar
        print("\n" + "="*80)
        print("⚠️  ADVERTENCIA: Este script modificará TODOS los documentos de 'users'")
        print("="*80)
        print("\nACCIONES A REALIZAR:")
        print(f"1. BORRAR {len(SchemaFixEngine.OBSOLETE_FIELDS)} campos obsoletos")
        print(f"2. CORREGIR {len(SchemaFixEngine.LIST_FIELDS)} campos de listas nulas")
        print("3. RECALCULAR enrichment_status con lógica v3.0")
        print("\n" + "="*80)
        
        response = input("\n¿Continuar? (escribir 'SI' para confirmar): ")
        
        if response.strip().upper() != "SI":
            logger.info("❌ Migración cancelada por el usuario")
            return
        
        # Ejecutar migración
        engine = SchemaFixEngine()
        engine.run_migration()
        
    except KeyboardInterrupt:
        logger.warning("\n⚠️  Migración interrumpida por el usuario")
    except Exception as e:
        logger.error(f"\n❌ Error durante la migración: {e}")
        raise
    finally:
        if engine:
            engine.close()


if __name__ == "__main__":
    main()
