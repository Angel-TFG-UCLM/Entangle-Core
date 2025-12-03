"""
Motor de Ingesta de Organizaciones de GitHub - v1.0
Estrategia Bottom-Up: descubre organizaciones desde usuarios existentes.
"""
import time
from typing import List, Dict, Any, Optional, Set
from datetime import datetime

from .graphql_client import GitHubGraphQLClient
from ..core.logger import logger
from ..core.mongo_repository import MongoRepository
from ..models.organization import Organization


class OrganizationIngestionEngine:
    """
    Motor para ingerir organizaciones de GitHub usando estrategia Bottom-Up.
    Descubre organizaciones desde los usuarios ya ingestados.
    """
    
    # Query GraphQL ligera para datos básicos de organización
    BASIC_ORG_QUERY = """
    query GetOrganizationBasic($login: String!) {
      organization(login: $login) {
        id
        login
        name
        description
        email
        url
        avatarUrl
        websiteUrl
        twitterUsername
        location
        isVerified
        createdAt
        updatedAt
        repositories {
          totalCount
        }
        membersWithRole {
          totalCount
        }
        sponsorshipsAsMaintainer {
          totalCount
        }
      }
    }
    """
    
    def __init__(
        self,
        github_token: str,
        users_repository: MongoRepository,
        organizations_repository: MongoRepository,
        batch_size: int = 5,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Inicializa el motor de ingesta de organizaciones.
        
        Args:
            github_token: Token de GitHub
            users_repository: Repositorio de usuarios
            organizations_repository: Repositorio de organizaciones
            batch_size: Tamaño del lote (default 5 para Rate Limit)
            config: Configuración opcional
        """
        self.github_token = github_token
        self.users_repository = users_repository
        self.organizations_repository = organizations_repository
        self.batch_size = batch_size
        self.config = config or {}
        self.graphql_client = GitHubGraphQLClient(github_token)
        
        # Estadísticas
        self.stats = {
            "total_discovered": 0,
            "total_processed": 0,
            "total_inserted": 0,
            "total_updated": 0,
            "total_skipped": 0,
            "total_errors": 0,
            "start_time": None,
            "end_time": None
        }
        
        logger.info(f"🚀 OrganizationIngestionEngine v1.0 inicializado (batch_size={batch_size})")
    
    def run(self, force_update: bool = False) -> Dict[str, Any]:
        """
        Ejecuta el proceso completo de ingesta de organizaciones.
        
        Args:
            force_update: Si True, actualiza organizaciones ya existentes
            
        Returns:
            Estadísticas del proceso
        """
        logger.info("=" * 80)
        logger.info("🏢 INICIANDO INGESTA DE ORGANIZACIONES v1.0")
        logger.info("=" * 80)
        
        self.stats["start_time"] = datetime.now()
        
        # Paso 1: Descubrir organizaciones desde usuarios
        org_logins = self._discover_organizations()
        
        if not org_logins:
            logger.warning("⚠️  No se encontraron organizaciones para procesar")
            return self._finalize_stats()
        
        self.stats["total_discovered"] = len(org_logins)
        logger.info(f"📊 Total organizaciones descubiertas: {len(org_logins)}")
        
        # Paso 2: Procesar en lotes
        self._process_batch(org_logins, force_update)
        
        return self._finalize_stats()
    
    def _discover_organizations(self) -> Set[str]:
        """
        Descubre organizaciones únicas desde los usuarios en MongoDB.
        
        Returns:
            Set de logins únicos de organizaciones
        """
        logger.info("\n🔍 Descubriendo organizaciones desde usuarios...")
        
        try:
            # Agregación para obtener todos los logins únicos de organizaciones
            pipeline = [
                # Filtrar usuarios que tienen organizaciones
                {"$match": {"organizations": {"$exists": True, "$ne": []}}},
                
                # Desenrollar el array de organizaciones
                {"$unwind": "$organizations"},
                
                # Agrupar por login para obtener valores únicos
                {"$group": {
                    "_id": "$organizations.login",
                    "count": {"$sum": 1}  # Cuenta cuántos usuarios pertenecen a esta org
                }},
                
                # Proyectar solo el login
                {"$project": {
                    "login": "$_id",
                    "member_count": "$count",
                    "_id": 0
                }},
                
                # Ordenar por número de miembros (descendente)
                {"$sort": {"member_count": -1}}
            ]
            
            results = list(self.users_repository.collection.aggregate(pipeline))
            
            logger.info(f"✅ Encontradas {len(results)} organizaciones únicas")
            
            # Mostrar top 10
            if results:
                logger.info("\n📊 Top 10 organizaciones por número de miembros:")
                for i, org in enumerate(results[:10], 1):
                    logger.info(f"   {i}. {org['login']} ({org['member_count']} miembros)")
            
            # Retornar solo los logins
            return {org["login"] for org in results if org.get("login")}
            
        except Exception as e:
            logger.error(f"❌ Error descubriendo organizaciones: {e}")
            return set()
    
    def _process_batch(self, org_logins: Set[str], force_update: bool) -> None:
        """
        Procesa las organizaciones en lotes.
        
        Args:
            org_logins: Set de logins de organizaciones
            force_update: Si True, actualiza organizaciones existentes
        """
        org_list = list(org_logins)
        total_orgs = len(org_list)
        
        logger.info(f"\n📦 Procesando {total_orgs} organizaciones en lotes de {self.batch_size}...")
        
        for i in range(0, total_orgs, self.batch_size):
            batch = org_list[i:i + self.batch_size]
            batch_num = i // self.batch_size + 1
            total_batches = (total_orgs + self.batch_size - 1) // self.batch_size
            
            logger.info(f"\n📦 Lote {batch_num}/{total_batches} ({len(batch)} organizaciones)")
            
            for login in batch:
                self._fetch_and_save_organization(login, force_update)
                
                # Sleep para respetar Rate Limit
                time.sleep(0.5)
            
            logger.info(f"✅ Lote {batch_num}/{total_batches} completado")
    
    def _fetch_and_save_organization(self, login: str, force_update: bool = False) -> bool:
        """
        Obtiene y guarda una organización individual.
        
        Args:
            login: Login de la organización
            force_update: Si True, actualiza si ya existe
            
        Returns:
            True si se procesó correctamente, False si hubo error
        """
        try:
            logger.debug(f"\n🏢 Procesando organización: {login}")
            
            # Verificar si ya existe
            existing = self.organizations_repository.collection.find_one({"login": login})
            
            if existing and not force_update:
                logger.debug(f"   ⏭️  Organización {login} ya existe (saltando)")
                self.stats["total_skipped"] += 1
                return True
            
            # Fetch desde GitHub API
            org_data = self._fetch_organization_basic(login)
            
            if not org_data:
                logger.warning(f"   ⚠️  No se pudo obtener datos de {login}")
                self.stats["total_errors"] += 1
                return False
            
            # Crear modelo
            organization = Organization.from_graphql_response(org_data)
            
            # Guardar en BD
            if existing:
                # Actualizar
                self.organizations_repository.collection.update_one(
                    {"login": login},
                    {"$set": organization.model_dump(by_alias=False, exclude_none=False)}
                )
                logger.debug(f"   ↻ Organización {login} actualizada")
                self.stats["total_updated"] += 1
            else:
                # Insertar
                self.organizations_repository.collection.insert_one(
                    organization.model_dump(by_alias=False, exclude_none=False)
                )
                logger.debug(f"   ✨ Organización {login} insertada")
                self.stats["total_inserted"] += 1
            
            self.stats["total_processed"] += 1
            return True
            
        except Exception as e:
            logger.error(f"   ❌ Error procesando {login}: {e}")
            self.stats["total_errors"] += 1
            return False
    
    def _fetch_organization_basic(self, login: str) -> Optional[Dict[str, Any]]:
        """
        Ejecuta la query GraphQL básica para obtener datos de organización.
        
        Args:
            login: Login de la organización
            
        Returns:
            Datos de la organización o None si falla
        """
        try:
            variables = {"login": login}
            response = self.graphql_client.execute_query(self.BASIC_ORG_QUERY, variables)
            
            if "errors" in response:
                # Manejar error NOT_FOUND (organización no existe o fue eliminada)
                errors = response.get("errors", [])
                if any("NOT_FOUND" in str(error) for error in errors):
                    logger.debug(f"   ⚠️  Organización {login} no encontrada (eliminada o privada)")
                    return None
                
                logger.error(f"   ❌ Error GraphQL para {login}: {errors}")
                return None
            
            org_data = response.get("data", {}).get("organization")
            
            if not org_data:
                logger.warning(f"   ⚠️  No hay datos para organización {login}")
                return None
            
            return org_data
            
        except Exception as e:
            logger.error(f"   ❌ Error ejecutando query para {login}: {e}")
            return None
    
    def _finalize_stats(self) -> Dict[str, Any]:
        """Finaliza y retorna las estadísticas."""
        self.stats["end_time"] = datetime.now()
        
        if self.stats["start_time"]:
            duration = self.stats["end_time"] - self.stats["start_time"]
            self.stats["duration_seconds"] = duration.total_seconds()
        
        logger.info("\n" + "=" * 80)
        logger.info("📊 RESUMEN DE INGESTA DE ORGANIZACIONES")
        logger.info("=" * 80)
        logger.info(f"🔍 Total descubiertas: {self.stats['total_discovered']}")
        logger.info(f"✅ Total procesadas: {self.stats['total_processed']}")
        logger.info(f"✨ Total insertadas: {self.stats['total_inserted']}")
        logger.info(f"↻  Total actualizadas: {self.stats['total_updated']}")
        logger.info(f"⏭️  Total saltadas: {self.stats['total_skipped']}")
        logger.info(f"❌ Total errores: {self.stats['total_errors']}")
        
        if "duration_seconds" in self.stats:
            logger.info(f"⏱️  Duración: {self.stats['duration_seconds']:.2f} segundos")
        
        return self.stats
