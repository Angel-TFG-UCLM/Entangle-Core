"""
Motor de Ingesta de Organizaciones de GitHub - v1.0
Estrategia Bottom-Up: descubre organizaciones desde usuarios existentes.
"""
import time
from typing import List, Dict, Any, Optional, Set
from datetime import datetime
from pymongo.errors import OperationFailure

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
    
    def _retry_on_cosmos_throttle(self, operation, max_retries: int = 5):
        """
        Ejecuta una operación con retry automático cuando Cosmos DB retorna 429.
        
        Args:
            operation: Función a ejecutar
            max_retries: Número máximo de reintentos (default 5)
            
        Returns:
            Resultado de la operación o None si falla
        """
        for attempt in range(max_retries):
            try:
                return operation()
            except OperationFailure as e:
                if e.code == 16500:  # Cosmos DB throttling
                    # Parsear RetryAfterMs del mensaje de error
                    error_msg = str(e)
                    retry_after_ms = 1000  # default fallback
                    
                    if 'RetryAfterMs=' in error_msg:
                        start = error_msg.index('RetryAfterMs=') + len('RetryAfterMs=')
                        end = error_msg.index(',', start)
                        retry_after_ms = int(error_msg[start:end])
                    
                    retry_after_s = retry_after_ms / 1000.0
                    
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"⚠️  Cosmos DB 429: esperando {retry_after_s:.2f}s "
                            f"(intento {attempt + 1}/{max_retries})"
                        )
                        time.sleep(retry_after_s)
                    else:
                        logger.error(
                            f"❌ Max reintentos alcanzado tras {max_retries} intentos"
                        )
                        return None  # Degradación graciosa
                else:
                    raise  # Otro tipo de OperationFailure
            except Exception as e:
                logger.error(f"❌ Error inesperado: {e}")
                return None
        
        return None
    
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
            
            # Ejecutar con retry automático para Cosmos DB throttling
            results = self._retry_on_cosmos_throttle(
                lambda: list(self.users_repository.collection.aggregate(pipeline))
            )
            
            # Sleep después de lectura
            time.sleep(0.2)
            
            if results is None:
                logger.error("❌ No se pudo descubrir organizaciones tras reintentos")
                return set()
            
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
            
            # Verificar si ya existe con retry automático
            existing = self._retry_on_cosmos_throttle(
                lambda: self.organizations_repository.collection.find_one({"login": login})
            )
            
            # Sleep después de lectura
            time.sleep(0.2)
            
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
            
            # Calcular relevancia basándose en repos existentes
            relevance_data = self._calculate_organization_relevance(login)
            
            # Actualizar campos de relevancia
            org_dict = organization.model_dump(by_alias=False, exclude_none=False)
            org_dict.update(relevance_data)
            
            # Log de relevancia
            if relevance_data["is_relevant"]:
                logger.debug(f"   ✅ Organización {login} ES RELEVANTE ({len(relevance_data['discovered_from_repos'])} repos quantum)")
            else:
                logger.debug(f"   ⚠️  Organización {login} NO es relevante (sin repos quantum ingestados)")
            
            # Guardar en BD con retry para Cosmos DB throttling
            if existing:
                # ✅ Preservar campos enriquecidos durante actualización
                enriched_fields = [
                    "quantum_focus_score",
                    "quantum_repositories_count",
                    "quantum_contributors_count",
                    "total_stars",
                    "top_languages",
                    "top_quantum_contributors",
                    "quantum_repositories",
                    "is_quantum_focused",
                    "enriched_at",
                    "enrichment_status"
                ]
                
                # Separar campos a actualizar vs preservar
                fields_to_update = {}
                
                for key, value in org_dict.items():
                    if key in enriched_fields:
                        # Solo actualizar si el campo existente es null/vacío
                        existing_value = existing.get(key)
                        if existing_value is None or existing_value == [] or existing_value == {}:
                            fields_to_update[key] = value
                        # else: preservar valor existente (no incluir en update)
                    else:
                        # Campos básicos siempre se actualizan
                        fields_to_update[key] = value
                
                # Actualizar con retry automático
                if fields_to_update:
                    result = self._retry_on_cosmos_throttle(
                        lambda: self.organizations_repository.collection.update_one(
                            {"login": login},
                            {"$set": fields_to_update}
                        )
                    )
                    
                    if result is not None:
                        logger.debug(f"   ↻ Organización {login} actualizada (preservando enriquecimiento)")
                        self.stats["total_updated"] += 1
                    else:
                        logger.warning(f"   ⚠️  Organización {login} falló tras reintentos")
                        self.stats["total_errors"] += 1
                        return False
                else:
                    logger.debug(f"   ⏭️  Organización {login} sin cambios")
                    self.stats["total_skipped"] += 1
            else:
                # Insertar nueva organización con retry automático
                result = self._retry_on_cosmos_throttle(
                    lambda: self.organizations_repository.collection.insert_one(org_dict)
                )
                
                if result is not None:
                    logger.debug(f"   ✨ Organización {login} insertada")
                    self.stats["total_inserted"] += 1
                else:
                    logger.warning(f"   ⚠️  Organización {login} falló tras reintentos")
                    self.stats["total_errors"] += 1
                    return False
            
            # Sleep adicional para Cosmos DB (después de escritura)
            time.sleep(0.3)
            
            self.stats["total_processed"] += 1
            return True
            
        except Exception as e:
            logger.error(f"   ❌ Error procesando {login}: {e}")
            self.stats["total_errors"] += 1
            return False
    
    def _calculate_organization_relevance(self, org_login: str) -> Dict[str, Any]:
        """
        Calcula la relevancia de una organización basándose en repos quantum ingestados.
        
        Args:
            org_login: Login de la organización
            
        Returns:
            Dict con is_relevant, discovered_from_repos, discovered_from_repo_names
        """
        try:
            # Buscar repos de esta organización en nuestra BD
            # Si está en la colección repositories, ya es quantum-related (pasó filtros)
            repos_collection = self.users_repository.collection.database["repositories"]
            
            # Buscar con retry automático para Cosmos DB throttling
            org_repos = self._retry_on_cosmos_throttle(
                lambda: list(repos_collection.find({
                    "owner.login": org_login
                }))
            )
            
            # Sleep después de lectura
            time.sleep(0.2)
            
            if org_repos is None:
                logger.warning(f"   ⚠️  No se pudo leer repos de {org_login} tras reintentos")
                return {
                    "is_relevant": False,
                    "discovered_from_repos": []
                }
            
            is_relevant = len(org_repos) > 0
            
            # Crear lista unificada con ID y nombre
            discovered_repos = []
            for repo in org_repos:
                repo_id = repo.get("id")
                repo_name = repo.get("name")
                owner_login = repo.get("owner", {}).get("login", "")
                
                if repo_id and repo_name:
                    discovered_repos.append({
                        "id": repo_id,
                        "name": f"{owner_login}/{repo_name}" if owner_login else repo_name
                    })
            
            return {
                "is_relevant": is_relevant,
                "discovered_from_repos": discovered_repos
            }
            
        except Exception as e:
            logger.error(f"   ❌ Error calculando relevancia de {org_login}: {e}")
            return {
                "is_relevant": False,
                "discovered_from_repos": []
            }
    
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
        
        # Calcular organizaciones relevantes vs no relevantes con retry
        try:
            total_relevant = self._retry_on_cosmos_throttle(
                lambda: self.organizations_repository.collection.count_documents({"is_relevant": True})
            )
            total_non_relevant = self._retry_on_cosmos_throttle(
                lambda: self.organizations_repository.collection.count_documents({"is_relevant": False})
            )
            
            if total_relevant is not None and total_non_relevant is not None:
                self.stats["total_relevant"] = total_relevant
                self.stats["total_non_relevant"] = total_non_relevant
        except Exception as e:
            logger.error(f"Error calculando stats de relevancia: {e}")
        
        logger.info("\n" + "=" * 80)
        logger.info("📊 RESUMEN DE INGESTA DE ORGANIZACIONES")
        logger.info("=" * 80)
        logger.info(f"🔍 Total descubiertas: {self.stats['total_discovered']}")
        logger.info(f"✅ Total procesadas: {self.stats['total_processed']}")
        logger.info(f"✨ Total insertadas: {self.stats['total_inserted']}")
        logger.info(f"↻  Total actualizadas: {self.stats['total_updated']}")
        logger.info(f"⏭️  Total saltadas: {self.stats['total_skipped']}")
        logger.info(f"❌ Total errores: {self.stats['total_errors']}")
        
        if "total_relevant" in self.stats:
            logger.info("\n📊 Análisis de Relevancia:")
            logger.info(f"   ✅ Organizaciones relevantes (con repos quantum): {self.stats['total_relevant']}")
            logger.info(f"   ⚠️  Organizaciones no relevantes (sin repos quantum): {self.stats['total_non_relevant']}")
            if self.stats['total_relevant'] + self.stats['total_non_relevant'] > 0:
                relevance_pct = (self.stats['total_relevant'] / (self.stats['total_relevant'] + self.stats['total_non_relevant'])) * 100
                logger.info(f"   📈 % Relevancia: {relevance_pct:.1f}%")
        
        if "duration_seconds" in self.stats:
            logger.info(f"\n⏱️  Duración: {self.stats['duration_seconds']:.2f} segundos")
        
        return self.stats
