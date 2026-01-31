"""
Motor de Ingesta de Organizaciones de GitHub - v2.0
Estrategia Repository-First: descubre organizaciones desde repositorios quantum.
"""
import time
from typing import List, Dict, Any, Optional
from datetime import datetime
from pymongo.errors import OperationFailure

from .graphql_client import GitHubGraphQLClient
from ..core.logger import logger
from ..core.mongo_repository import MongoRepository
from ..models.organization import Organization


class OrganizationIngestionEngine:
    """
    Motor para ingerir organizaciones de GitHub usando estrategia Repository-First.
    Descubre organizaciones desde los repositorios quantum ya ingestados.
    Garantiza que solo se ingestán organizaciones con repos quantum confirmados.
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
        
        logger.info(f"OrganizationIngestionEngine v2.0 inicializado (batch_size={batch_size})")
    
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
        logger.info("INICIANDO INGESTA DE ORGANIZACIONES v2.0 (Repository-First)")
        logger.info("=" * 80)
        
        self.stats["start_time"] = datetime.now()
        
        # Paso 1: Descubrir organizaciones desde repositorios quantum
        orgs_data = self._discover_organizations()
        
        if not orgs_data:
            logger.warning("⚠️  No se encontraron organizaciones para procesar")
            return self._finalize_stats()
        
        self.stats["total_discovered"] = len(orgs_data)
        logger.info(f"📊 Total organizaciones descubiertas: {len(orgs_data)}")
        
        # Paso 2: Procesar en lotes
        self._process_batch(orgs_data, force_update)
        
        return self._finalize_stats()
    
    def _discover_organizations(self) -> Dict[str, Dict[str, Any]]:
        """
        Descubre organizaciones únicas desde los repositorios quantum en MongoDB.
        Solo incluye organizaciones (owner.type == 'Organization').
        
        Returns:
            Dict con {org_login: {'repos': [{id, name}], 'repo_count': int}}
        """
        logger.info("\nDescubriendo organizaciones desde repositorios quantum...")
        
        try:
            # Obtener repositorios collection
            repos_collection = self.users_repository.collection.database["repositories"]
            
            # Agregación para obtener organizaciones únicas con sus repos
            pipeline = [
                # Filtrar solo repos de organizaciones (no usuarios individuales)
                {"$match": {"owner.type": "Organization"}},
                
                # Agrupar por login de la organización
                {"$group": {
                    "_id": "$owner.login",
                    "repos": {
                        "$push": {
                            "id": "$id",
                            "name": {"$concat": ["$owner.login", "/", "$name"]}
                        }
                    },
                    "repo_count": {"$sum": 1}
                }},
                
                # Proyectar campos
                {"$project": {
                    "login": "$_id",
                    "repos": 1,
                    "repo_count": 1,
                    "_id": 0
                }},
                
                # Ordenar por número de repos (descendente)
                {"$sort": {"repo_count": -1}}
            ]
            
            # Ejecutar con retry automático para Cosmos DB throttling
            results = self._retry_on_cosmos_throttle(
                lambda: list(repos_collection.aggregate(pipeline))
            )
            
            # Sleep después de lectura
            time.sleep(0.2)
            
            if results is None:
                logger.error("❌ No se pudo descubrir organizaciones tras reintentos")
                return {}
            
            logger.info(f"✅ Encontradas {len(results)} organizaciones con repos quantum")
            
            # Mostrar top 10
            if results:
                logger.info("\n📊 Top 10 organizaciones por número de repos quantum:")
                for i, org in enumerate(results[:10], 1):
                    logger.info(f"   {i}. {org['login']} ({org['repo_count']} repos quantum)")
            
            # Convertir a dict para acceso rápido
            orgs_dict = {}
            for org in results:
                login = org.get("login")
                if login:
                    orgs_dict[login] = {
                        "repos": org.get("repos", []),
                        "repo_count": org.get("repo_count", 0)
                    }
            
            return orgs_dict
            
        except Exception as e:
            logger.error(f"❌ Error descubriendo organizaciones: {e}")
            return {}
    
    def _process_batch(self, orgs_data: Dict[str, Dict[str, Any]], force_update: bool) -> None:
        """
        Procesa las organizaciones en lotes.
        
        Args:
            orgs_data: Dict con {login: {'repos': [...], 'repo_count': int}}
            force_update: Si True, actualiza organizaciones existentes
        """
        org_list = list(orgs_data.items())
        total_orgs = len(org_list)
        
        logger.info(f"\n📦 Procesando {total_orgs} organizaciones en lotes de {self.batch_size}...")
        
        for i in range(0, total_orgs, self.batch_size):
            batch = org_list[i:i + self.batch_size]
            batch_num = i // self.batch_size + 1
            total_batches = (total_orgs + self.batch_size - 1) // self.batch_size
            
            logger.info(f"\n📦 Lote {batch_num}/{total_batches} ({len(batch)} organizaciones)")
            
            for login, data in batch:
                # Pasar repos directamente (ya los tenemos)
                self._fetch_and_save_organization(login, force_update, data['repos'])
                
                # Sleep para respetar Rate Limit
                time.sleep(0.5)
            
            logger.info(f"✅ Lote {batch_num}/{total_batches} completado")
    
    def _fetch_and_save_organization(self, login: str, force_update: bool = False, discovered_repos: List[Dict[str, str]] = None) -> bool:
        """
        Obtiene y guarda una organización individual.
        
        Args:
            login: Login de la organización
            force_update: Si True, actualiza si ya existe
            discovered_repos: Lista de repos ya descubiertos [{id, name}]
            
        Returns:
            True si se procesó correctamente, False si hubo error
        """
        try:
            logger.debug(f"\nProcesando organización: {login}")
            
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
            
            # Usar repos descubiertos (ya los tenemos, no necesitamos calcularlos)
            # TODAS las organizaciones encontradas son relevantes por definición
            org_dict = organization.model_dump(by_alias=False, exclude_none=False)
            org_dict["is_relevant"] = True
            org_dict["discovered_from_repos"] = discovered_repos or []
            
            # Log de relevancia
            logger.debug(f"   ✅ Organización {login} - {len(discovered_repos or [])} repos quantum")
            
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
