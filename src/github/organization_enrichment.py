"""
Motor de Enriquecimiento de Organizaciones de GitHub - v2.0

ESTRATEGIA v2.0:
- Queries GraphQL batched (5 orgs/query) para reducir llamadas API
- Smart rate limit (solo pausa cuando remaining < 200)
- Bulk MongoDB updates (bulk_write en vez de update_one individual)
- Fallback individual automático si el batch falla
- Calcula quantum_focus_score basado en repos quantum de la BD
- Identifica top contributors a repos quantum
- Determina is_quantum_focused (threshold: 30%)
"""

import time
import threading
import concurrent.futures
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from pymongo import UpdateOne
from pymongo.errors import OperationFailure

from .graphql_client import GitHubGraphQLClient
from ..core.logger import logger
from ..core.mongo_repository import MongoRepository


class OrganizationEnrichmentEngine:
    """
    Motor para enriquecer organizaciones con métricas quantum.
    Calcula scores basándose en repos quantum de la BD local.
    """
    
    ENRICHMENT_VERSION = "2.0.0"
    GRAPHQL_BATCH_SIZE = 5  # Organizaciones por query GraphQL batched
    
    # Fragment para consultas batched
    ORG_ENRICHMENT_FRAGMENT = """
    fragment OrgEnrichmentFields on Organization {
        id
        login
        repositories(first: 100, orderBy: {field: STARGAZERS, direction: DESC}, privacy: PUBLIC) {
            totalCount
            nodes {
                id
                name
                nameWithOwner
                primaryLanguage {
                    name
                }
                stargazerCount
            }
        }
        membersWithRole(first: 100) {
            totalCount
            nodes {
                login
                name
                avatarUrl
            }
        }
    }
    """
    
    # Query GraphQL individual (para fallback)
    ENRICHMENT_QUERY = """
    query GetOrganizationEnrichment($login: String!) {
      organization(login: $login) {
        id
        login
        
        # Repositorios (primeros 100, ordenados por estrellas)
        repositories(first: 100, orderBy: {field: STARGAZERS, direction: DESC}, privacy: PUBLIC) {
          totalCount
          nodes {
            id
            name
            nameWithOwner
            primaryLanguage {
              name
            }
            stargazerCount
          }
        }
        
        # Miembros con rol
        membersWithRole(first: 100) {
          totalCount
          nodes {
            login
            name
            avatarUrl
          }
        }
      }
    }
    """
    
    def __init__(
        self,
        github_token: str,
        organizations_repository: MongoRepository,
        repositories_repository: MongoRepository,
        users_repository: MongoRepository,
        batch_size: int = 100,  # ✅ OPTIMIZADO para vCore
        sleep_time: float = 0.5,
        config: Optional[Dict[str, Any]] = None,
        progress_callback=None,
        cancel_event=None
    ):
        """
        Inicializa el motor de enriquecimiento.
        
        Args:
            github_token: Token de GitHub
            organizations_repository: Repositorio de organizaciones
            repositories_repository: Repositorio de repositorios (para buscar quantum repos)
            users_repository: Repositorio de usuarios (para contributors)
            batch_size: Tamaño del lote (optimizado para vCore)
            sleep_time: Tiempo de espera entre requests GitHub API (default 0.5s)
            config: Configuración opcional
            progress_callback: Callback opcional fn(items_processed, items_total, message)
        """
        self.github_token = github_token
        self.orgs_repository = organizations_repository
        self.repos_repository = repositories_repository
        self.users_repository = users_repository
        self.batch_size = batch_size
        self.sleep_time = sleep_time
        self.config = config or {}
        self.progress_callback = progress_callback
        self.cancel_event = cancel_event
        self.graphql_client = GitHubGraphQLClient(github_token)
        
        # Lock para estadísticas thread-safe
        self._stats_lock = threading.Lock()
        
        # Coordinación de rate limit entre hilos
        self._rate_limit_lock = threading.Lock()
        self._rate_limit_until = 0  # timestamp epoch hasta el que esperar
        
        # Estadísticas
        self.stats = {
            "total_processed": 0,
            "total_enriched": 0,
            "total_skipped": 0,
            "total_errors": 0,
            "start_time": None,
            "end_time": None
        }
        
        logger.info(f"OrganizationEnrichmentEngine v2.0 inicializado (graphql_batch={self.GRAPHQL_BATCH_SIZE}, sleep_time={sleep_time}s)")
    
    # DEPRECATED: Ya no necesario con Azure Cosmos DB for MongoDB (vCore)
    def _retry_on_cosmos_throttle(self, operation, max_retries: int = 5):
        """
        DEPRECATED: Método legacy de Cosmos DB RU-based.
        vCore no tiene throttling code 16500.
        Se mantiene por compatibilidad pero ahora solo ejecuta la operación directamente.
        
        Args:
            operation: Función a ejecutar
            max_retries: IGNORADO en vCore
            
        Returns:
            Resultado de la operación
        """
        try:
            return operation()
        except Exception as e:
            logger.error(f"❌ Error en operación: {e}")
            raise
    
    def enrich_all_organizations(
        self, 
        max_orgs: Optional[int] = None, 
        force_reenrich: bool = False
    ) -> Dict[str, Any]:
        """
        Enriquece todas las organizaciones en MongoDB.
        
        Args:
            max_orgs: Límite opcional de organizaciones a procesar
            force_reenrich: Si True, re-enriquece incluso organizaciones ya enriquecidas
            
        Returns:
            Estadísticas del proceso
        """
        logger.info("=" * 80)
        logger.info("INICIANDO ENRIQUECIMIENTO DE ORGANIZACIONES v2.0")
        logger.info("=" * 80)
        
        self.stats["start_time"] = datetime.now()
        
        # Construir query para seleccionar organizaciones
        if force_reenrich:
            query = {}
            logger.info("📌 Modo force_reenrich: procesando todas las organizaciones")
        else:
            # Re-enriquecer si:
            # 1. enrichment_status es null o no existe
            # 2. enriched_at es null o no existe
            # 3. No está completo (is_complete = false)
            # 4. Más de 7 días desde la última actualización
            seven_days_ago = datetime.now() - timedelta(days=7)
            query = {
                "$or": [
                    {"enrichment_status": {"$exists": False}},
                    {"enrichment_status": None},
                    {"enriched_at": {"$exists": False}},
                    {"enriched_at": None},
                    {"enrichment_status.is_complete": False},
                    {"enriched_at": {"$lt": seven_days_ago}}
                ]
            }
            logger.info("📌 Modo incremental: organizaciones sin enriquecer, incompletas o desactualizadas (>7 días)")
        
        # Obtener organizaciones
        orgs_cursor = self.orgs_repository.collection.find(query)
        
        if max_orgs:
            orgs_cursor = orgs_cursor.limit(max_orgs)
            logger.info(f"📊 Limitando a {max_orgs} organizaciones")
        
        orgs = list(orgs_cursor)
        total_orgs = len(orgs)
        self._total_items = total_orgs
        
        logger.info(f"📊 Total organizaciones a enriquecer: {total_orgs}")
        
        if total_orgs == 0:
            logger.info("✅ No hay organizaciones para enriquecer")
            return self._finalize_stats()
        
        # Procesar en lotes con queries GraphQL batched + ThreadPoolExecutor
        total_batches = (total_orgs + self.GRAPHQL_BATCH_SIZE - 1) // self.GRAPHQL_BATCH_SIZE
        max_concurrent = self.config.get("enrichment", {}).get("max_concurrent_batches", 3)
        logger.info(f"🚀 Procesando {total_orgs} organizaciones con {max_concurrent} workers paralelos (batches de {self.GRAPHQL_BATCH_SIZE})")
        
        batches = []
        for i in range(0, total_orgs, self.GRAPHQL_BATCH_SIZE):
            batch = orgs[i:i + self.GRAPHQL_BATCH_SIZE]
            batch_num = i // self.GRAPHQL_BATCH_SIZE + 1
            batches.append((batch_num, batch))
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            futures = {}
            for batch_num, batch in batches:
                future = executor.submit(self._enrich_batch_with_retry, batch, batch_num, total_batches)
                futures[future] = batch_num
            
            for future in concurrent.futures.as_completed(futures):
                if self.cancel_event and self.cancel_event.is_set():
                    for f in futures:
                        f.cancel()
                    logger.warning("⚠️ Cancelación detectada en enrich_all_organizations")
                    break
                batch_num = futures[future]
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"❌ Error en lote {batch_num}/{total_batches}: {e}")
        
        return self._finalize_stats()
    
    def _enrich_batch_with_retry(self, batch: List[Dict[str, Any]], batch_num: int, total_batches: int) -> None:
        """
        Procesa un batch con reintentos y coordinación de rate limit.
        Diseñado para ejecución en ThreadPoolExecutor.
        """
        # Esperar si hay rate limit activo de otro hilo
        now = time.time()
        wait_remaining = self._rate_limit_until - now
        if wait_remaining > 0:
            logger.debug(f"⏳ Lote {batch_num}: esperando rate limit activo ({wait_remaining:.0f}s)...")
            time.sleep(wait_remaining)
        
        logger.info(f"\n📦 Lote {batch_num}/{total_batches} ({len(batch)} orgs) - GraphQL batched")
        
        self._enrich_batch(batch)
        
        # Smart rate limit check
        self._check_rate_limit()
        
        logger.info(f"✅ Lote {batch_num}/{total_batches} completado")
    
    def _enrich_single_organization(self, org: Dict[str, Any]) -> bool:
        """
        Enriquece una sola organización (método fallback individual).
        
        Args:
            org: Documento de organización de MongoDB
            
        Returns:
            True si se enriqueció correctamente, False si hubo error
        """
        login = org.get("login")
        
        try:
            logger.info(f"\nEnriqueciendo organización (individual): {login}")
            
            # Fetch GraphQL data individualmente
            graphql_data = self._fetch_organization_data(login)
            
            if not graphql_data:
                logger.warning(f"⚠️  No se pudo obtener datos de {login}")
                with self._stats_lock:
                    self.stats["total_errors"] += 1
                return False
            
            # Calcular updates usando método compartido
            updates = self._calculate_enrichment_updates(org, graphql_data)
            
            if not updates:
                with self._stats_lock:
                    self.stats["total_errors"] += 1
                return False
            
            # Guardar en BD individualmente
            self._retry_on_cosmos_throttle(
                lambda: self.orgs_repository.collection.update_one(
                    {"_id": org.get("_id")},
                    {"$set": updates}
                )
            )
            
            with self._stats_lock:
                self.stats["total_enriched"] += 1
            self._log_enrichment_result(org, updates)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error enriqueciendo organización {login}: {e}")
            with self._stats_lock:
                self.stats["total_errors"] += 1
            return False
        
        finally:
            with self._stats_lock:
                self.stats["total_processed"] += 1
    
    # ==================== MÉTODOS DE PROCESAMIENTO BATCHED ====================
    
    def _enrich_batch(self, orgs_batch: List[Dict[str, Any]]) -> None:
        """
        Enriquece un lote de organizaciones con query GraphQL batched.
        
        1. Ejecuta una sola query GraphQL para todas las orgs del lote
        2. Procesa cálculos locales (quantum repos, contributors, etc.) por org
        3. Aplica updates con bulk_write
        
        Args:
            orgs_batch: Lista de documentos de organización
        """
        logins = [org.get("login") for org in orgs_batch if org.get("login")]
        
        if not logins:
            return
        
        try:
            # Construir y ejecutar query batched
            query, variables = self._build_enrichment_batch_query(logins)
            response = self.graphql_client.execute_query(query, variables)
            
            if "errors" in response and "data" not in response:
                logger.warning(f"⚠️ Error total en batch query, procesando individualmente")
                self._enrich_batch_individual_fallback(orgs_batch)
                return
            
            data = response.get("data", {})
            
            # Mapear datos GraphQL por login
            graphql_map = {}
            for i, login in enumerate(logins):
                alias = f"org{i}"
                org_data = data.get(alias)
                if org_data:
                    graphql_map[login] = org_data
            
            logger.info(f"📡 Batch GraphQL: {len(graphql_map)}/{len(logins)} orgs con datos")
            
            # Procesar cada org y recopilar updates
            bulk_updates = []
            
            for org in orgs_batch:
                if self.cancel_event and self.cancel_event.is_set():
                    break
                login = org.get("login")
                graphql_data = graphql_map.get(login)
                
                if not graphql_data:
                    logger.warning(f"⚠️ Sin datos GraphQL para {login}, procesando individualmente")
                    self._enrich_single_organization(org)
                    continue
                
                try:
                    updates = self._calculate_enrichment_updates(org, graphql_data)
                    
                    if updates:
                        bulk_updates.append(UpdateOne(
                            {"_id": org.get("_id")},
                            {"$set": updates}
                        ))
                        with self._stats_lock:
                            self.stats["total_enriched"] += 1
                        self._log_enrichment_result(org, updates)
                    else:
                        with self._stats_lock:
                            self.stats["total_errors"] += 1
                    
                except Exception as e:
                    logger.error(f"❌ Error procesando {login}: {e}")
                    with self._stats_lock:
                        self.stats["total_errors"] += 1
                
                with self._stats_lock:
                    self.stats["total_processed"] += 1
                
                # Notificar progreso
                if self.progress_callback:
                    try:
                        total = getattr(self, '_total_items', 0)
                        self.progress_callback(
                            self.stats["total_processed"], total,
                            f"Enriqueciendo orgs: {self.stats['total_processed']}/{total}"
                        )
                    except Exception:
                        pass
            
            # Bulk write de todas las actualizaciones
            if bulk_updates:
                try:
                    result = self.orgs_repository.collection.bulk_write(bulk_updates, ordered=False)
                    logger.info(f"📝 Bulk update: {result.modified_count} modificadas")
                except Exception as e:
                    logger.error(f"❌ Error en bulk_write, actualizando individualmente: {e}")
                    for update_op in bulk_updates:
                        try:
                            self.orgs_repository.collection.update_one(
                                update_op._filter, update_op._doc
                            )
                        except Exception as inner_e:
                            logger.error(f"❌ Error individual update: {inner_e}")
            
        except Exception as e:
            error_str = str(e)
            if "RATE_LIMIT" in error_str or "rate limit" in error_str.lower() or "403" in error_str or "forbidden" in error_str.lower():
                # Esperar al reset del rate limit y reintentar
                logger.warning("⏸️  Rate limit/403 en batch enrichment - Esperando reset...")
                self._wait_for_rate_limit_reset()
                # Reintentar con fallback individual (más conservador tras rate limit)
                logger.info("🔄 Reintentando batch tras esperar reset...")
                self._enrich_batch_individual_fallback(orgs_batch)
                return
            logger.error(f"❌ Error en batch enrichment: {e}")
            self._enrich_batch_individual_fallback(orgs_batch)
    
    def _build_enrichment_batch_query(self, logins: List[str]) -> tuple:
        """
        Construye una query GraphQL batched para múltiples organizaciones.
        
        Args:
            logins: Lista de logins de organizaciones
            
        Returns:
            Tupla (query_string, variables_dict)
        """
        variables = {}
        query_parts = []
        
        for i, login in enumerate(logins):
            variables[f"login{i}"] = login
            query_parts.append(f"    org{i}: organization(login: $login{i}) {{ ...OrgEnrichmentFields }}")
        
        var_defs = ", ".join([f"$login{i}: String!" for i in range(len(logins))])
        
        query = f"""{self.ORG_ENRICHMENT_FRAGMENT}
query GetOrgEnrichmentBatch({var_defs}) {{
{chr(10).join(query_parts)}
}}"""
        
        return query, variables
    
    def _calculate_enrichment_updates(self, org: Dict[str, Any], graphql_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Calcula los campos de enriquecimiento para una organización.
        Método compartido por batch e individual processing.
        
        Args:
            org: Documento de organización de MongoDB
            graphql_data: Datos de la API GraphQL
            
        Returns:
            Dict con updates o None si hay error
        """
        login = org.get("login")
        
        try:
            updates = {}
            
            # Obtener totales de la API
            updates["total_repositories_count"] = graphql_data.get("repositories", {}).get("totalCount", 0)
            updates["total_members_count"] = graphql_data.get("membersWithRole", {}).get("totalCount", 0)
            
            # Identificar repos quantum en BD local
            quantum_repos_data = self._find_quantum_repositories(login, org)
            
            if quantum_repos_data:
                updates["quantum_repositories"] = quantum_repos_data["repo_ids"]
                updates["quantum_repositories_count"] = len(quantum_repos_data["repo_ids"])
                
                top_contributors = self._find_top_quantum_contributors(quantum_repos_data["repo_ids"])
                updates["top_quantum_contributors"] = top_contributors
                updates["quantum_contributors_count"] = len(top_contributors)
                
                total_unique = self._count_unique_contributors(quantum_repos_data["repos"])
                updates["total_unique_contributors"] = total_unique
                
                top_languages = self._calculate_top_languages(quantum_repos_data["repo_ids"])
                updates["top_languages"] = top_languages
                
                total_stars = self._calculate_total_stars(quantum_repos_data["repo_ids"])
                updates["total_stars"] = total_stars
            else:
                updates["quantum_repositories"] = []
                updates["quantum_repositories_count"] = 0
                updates["top_quantum_contributors"] = []
                updates["quantum_contributors_count"] = 0
                updates["total_unique_contributors"] = 0
                updates["top_languages"] = []
                updates["total_stars"] = 0
            
            # Calcular quantum focus score
            quantum_score = self._calculate_quantum_focus_score(
                quantum_count=updates["quantum_repositories_count"],
                total_count=updates["total_repositories_count"],
                is_verified=org.get("is_verified", False),
                org_name=org.get("name", ""),
                org_description=org.get("description", "")
            )
            
            if quantum_score is not None:
                updates["quantum_focus_score"] = quantum_score
                updates["is_quantum_focused"] = quantum_score >= 30.0
            
            # Timestamp de enriquecimiento
            updates["enriched_at"] = datetime.now()
            
            # Enrichment status
            updates["enrichment_status"] = {
                "is_complete": True,
                "version": self.ENRICHMENT_VERSION,
                "last_check": datetime.now().isoformat(),
                "fields_missing": []
            }
            
            return updates
            
        except Exception as e:
            logger.error(f"❌ Error calculando enrichment para {login}: {e}")
            return None
    
    def _log_enrichment_result(self, org: Dict[str, Any], updates: Dict[str, Any]) -> None:
        """Registra los resultados de enriquecimiento de una organización."""
        login = org.get("login")
        logger.info(f"✅ Organización {login} enriquecida correctamente")
        logger.info(f"   📊 Repos quantum: {updates['quantum_repositories_count']}/{updates['total_repositories_count']}")
        logger.info(f"   🎯 Quantum score: {updates.get('quantum_focus_score', 0):.2f}%")
        logger.info(f"   ⭐ Total estrellas: {updates.get('total_stars', 0)}")
        
        if updates.get('top_languages'):
            top_3_langs = updates['top_languages'][:3]
            langs_str = ", ".join([f"{lang['name']} ({lang['percentage']:.1f}%)" for lang in top_3_langs])
            logger.info(f"   💻 Top lenguajes: {langs_str}")
        
        if org.get("is_relevant"):
            discovered_repos = org.get("discovered_from_repos", [])
            if discovered_repos:
                repo_names = [repo.get("name", "") for repo in discovered_repos if isinstance(repo, dict)]
                if repo_names:
                    logger.info(f"   ✅ Relevante - Descubierta desde: {', '.join(repo_names[:3])}")
                    if len(repo_names) > 3:
                        logger.info(f"      ... y {len(repo_names) - 3} repos más")
        else:
            logger.info(f"   ⚠️  No relevante - Sin repos quantum ingestados")
    
    def _enrich_batch_individual_fallback(self, orgs_batch: List[Dict[str, Any]]) -> None:
        """Fallback: enriquece cada organización individualmente."""
        logger.info("🔄 Fallback: procesando organizaciones individualmente")
        for org in orgs_batch:
            try:
                self._enrich_single_organization(org)
            except Exception as e:
                logger.error(f"❌ Error en fallback para {org.get('login')}: {e}")
            self._check_rate_limit()
    
    def _check_rate_limit(self) -> bool:
        """
        Smart rate limit: solo pausa cuando queda poco.
        Thread-safe: coordina con _rate_limit_until entre hilos.
        
        Returns:
            True si se puede continuar, False si se debe abortar
        """
        # Primero comprobar si hay rate limit activo de otro hilo
        now = time.time()
        wait_remaining = self._rate_limit_until - now
        if wait_remaining > 0:
            logger.debug(f"⏳ Rate limit activo, esperando {wait_remaining:.0f}s...")
            time.sleep(wait_remaining)
            return True
        
        try:
            rate_limit = self.graphql_client.get_rate_limit()
            remaining = rate_limit.get("remaining", 5000)
            
            if remaining < 50:
                self._wait_for_rate_limit_reset()
                return True
            elif remaining < 200:
                logger.info(f"⏳ Rate limit: {remaining} restantes, breve pausa (2s)")
                time.sleep(2)
            else:
                logger.debug(f"✅ Rate limit OK: {remaining} restantes")
            
            return True
            
        except Exception as e:
            logger.warning(f"⚠️ Error checking rate limit: {e}")
            time.sleep(1)
            return True
    
    def _wait_for_rate_limit_reset(self) -> None:
        """
        Espera hasta que el rate limit de GitHub se resetee.
        Thread-safe: coordina entre hilos con _rate_limit_lock.
        El primer hilo que detecta el rate limit loguea; los demás esperan silenciosamente.
        """
        wait_seconds = 120  # Fallback conservador
        try:
            rate_limit = self.graphql_client.get_rate_limit()
            remaining = rate_limit.get("remaining", 5000)
            reset_at = rate_limit.get("resetAt", "")
            
            if reset_at:
                reset_time = datetime.fromisoformat(reset_at.replace("Z", "+00:00"))
                now = datetime.now(reset_time.tzinfo)
                wait = (reset_time - now).total_seconds() + 5
                if 0 < wait < 3600:
                    wait_seconds = wait
            else:
                # Si GraphQL no da reset, consultar REST API
                rest_info = self.graphql_client._get_rate_limit_rest()
                gql_reset = rest_info.get('resources', {}).get('graphql', {}).get('reset', 0)
                if gql_reset > 0:
                    wait_seconds = max(0, gql_reset - time.time()) + 5
        except Exception:
            pass
        
        # Coordinación: primer hilo marca timestamp y loguea, otros esperan silenciosamente
        with self._rate_limit_lock:
            new_until = time.time() + wait_seconds
            if new_until > self._rate_limit_until:
                self._rate_limit_until = new_until
                logger.warning(f"⏳ Rate limit detectado. Todos los hilos esperarán {wait_seconds:.0f}s hasta reset...")
        
        # Dormir hasta el timestamp coordinado
        sleep_until = self._rate_limit_until - time.time()
        if sleep_until > 0:
            time.sleep(sleep_until)
            logger.info("✅ Rate limit reseteado, continuando")
    
    # ==================== MÉTODOS DE DATOS ====================
    
    def _fetch_organization_data(self, login: str) -> Optional[Dict[str, Any]]:
        """
        Ejecuta la super-query para obtener datos de la organización.
        
        Args:
            login: Login de la organización
            
        Returns:
            Datos de la organización o None si falla
        """
        try:
            variables = {"login": login}
            response = self.graphql_client.execute_query(self.ENRICHMENT_QUERY, variables)
            
            if "errors" in response:
                logger.error(f"❌ Error GraphQL para {login}: {response['errors']}")
                return None
            
            return response.get("data", {}).get("organization")
            
        except Exception as e:
            logger.error(f"❌ Error ejecutando super-query para {login}: {e}")
            return None
    
    def _find_quantum_repositories(self, org_login: str, org: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Encuentra repositorios quantum de la organización en nuestra BD.
        
        Args:
            org_login: Login de la organización
            org: Documento de organización
            
        Returns:
            Dict con repo_ids y metadata o None
        """
        try:
            # Buscar repos de la org en nuestra BD con retry automático
            quantum_repos = self._retry_on_cosmos_throttle(
                lambda: list(self.repos_repository.collection.find({
                    "owner.login": org_login
                }))
            )
            
            # NOTA: Sleep removido - vCore no necesita throttling
            
            if quantum_repos is None or not quantum_repos:
                return None
            
            repo_ids = [repo.get("id") for repo in quantum_repos if repo.get("id")]
            
            return {
                "repo_ids": repo_ids,
                "repos": quantum_repos
            }
            
        except Exception as e:
            logger.error(f"❌ Error buscando repos quantum de {org_login}: {e}")
            return None
    
    def _find_top_quantum_contributors(self, repo_ids: List[str], limit: int = 10) -> List[Dict[str, str]]:
        """
        Encuentra los top contributors a repos quantum de la organización.
        
        Args:
            repo_ids: IDs de repositorios quantum
            limit: Número máximo de contributors
            
        Returns:
            Lista de diccionarios con {id, login} de los top contributors
        """
        try:
            # Agregación para contar contribuciones por usuario
            pipeline = [
                # Filtrar usuarios que tienen extracted_from
                {"$match": {"extracted_from": {"$exists": True, "$ne": []}}},
                
                # Desenrollar extracted_from
                {"$unwind": "$extracted_from"},
                
                # Filtrar solo repos quantum
                {"$match": {"extracted_from.repo_id": {"$in": repo_ids}}},
                
                # Agrupar por usuario y sumar contribuciones
                {"$group": {
                    "_id": "$id",
                    "login": {"$first": "$login"},
                    "total_contributions": {"$sum": "$extracted_from.contributions"}
                }},
                
                # Ordenar por contribuciones (descendente)
                {"$sort": {"total_contributions": -1}},
                
                # Limitar a top N
                {"$limit": limit}
            ]
            
            results = self._retry_on_cosmos_throttle(
                lambda: list(self.users_repository.collection.aggregate(pipeline))
            )
            
            # NOTA: Sleep removido - vCore no necesita throttling
            
            if results is None:
                return []
            
            # Retornar lista con {id, login}
            contributors = []
            for result in results:
                user_id = result.get("_id")
                user_login = result.get("login")
                if user_id and user_login:
                    contributors.append({
                        "id": user_id,
                        "login": user_login
                    })
            
            return contributors
            
        except Exception as e:
            logger.error(f"❌ Error buscando top contributors: {e}")
            return []
    
    def _count_unique_contributors(self, repos: list) -> int:
        """
        Cuenta el total de contributors únicos sumando los collaborators
        de todos los repos de la organización.
        
        Args:
            repos: Lista de documentos de repositorio completos
            
        Returns:
            Número de contributors únicos
        """
        try:
            unique_logins = set()
            for repo in repos:
                for collab in (repo.get("collaborators") or []):
                    login = collab.get("login", "")
                    if login:
                        unique_logins.add(login)
            return len(unique_logins)
        except Exception as e:
            logger.error(f"❌ Error contando contributors únicos: {e}")
            return 0

    def _calculate_top_languages(self, repo_ids: List[str], limit: int = 10) -> List[Dict[str, Any]]:
        """
        Calcula el stack tecnológico (top lenguajes) de los repos quantum.
        
        Args:
            repo_ids: Lista de IDs de repositorios quantum
            limit: Número máximo de lenguajes a retornar
            
        Returns:
            Lista de diccionarios con {name, percentage, repo_count}
        """
        try:
            from collections import Counter
            
            if not repo_ids:
                return []
            
            # Buscar repos en la BD por sus IDs con retry automático
            repos = self._retry_on_cosmos_throttle(
                lambda: list(self.repos_repository.collection.find(
                    {"id": {"$in": repo_ids}},
                    {"primary_language": 1, "_id": 0}
                ))
            )
            
            # NOTA: Sleep removido - vCore no necesita throttling
            
            if repos is None or not repos:
                return []
            
            # Contar lenguajes y repos que los usan
            language_counter = Counter()
            repos_per_language = {}
            
            for repo in repos:
                primary_language = repo.get("primary_language", {})
                
                # Verificar que sea un dict y tenga el campo name
                if isinstance(primary_language, dict):
                    lang_name = primary_language.get("name")
                elif isinstance(primary_language, str):
                    lang_name = primary_language
                else:
                    continue
                
                if lang_name:
                    language_counter[lang_name] += 1
                    repos_per_language[lang_name] = repos_per_language.get(lang_name, 0) + 1
            
            if not language_counter:
                return []
            
            # Calcular porcentajes
            total_repos = len(repos)
            top_languages = []
            
            for lang_name, count in language_counter.most_common(limit):
                percentage = (count / total_repos) * 100
                top_languages.append({
                    "name": lang_name,
                    "percentage": round(percentage, 2),
                    "repo_count": count
                })
            
            return top_languages
            
        except Exception as e:
            logger.error(f"❌ Error calculando top languages: {e}")
            return []
    
    def _calculate_total_stars(self, repo_ids: List[str]) -> int:
        """
        Calcula el prestigio acumulado (suma de estrellas) de los repos quantum.
        
        Args:
            repo_ids: Lista de IDs de repositorios quantum
            
        Returns:
            Suma total de estrellas
        """
        try:
            if not repo_ids:
                return 0
            
            # Buscar repos en la BD por sus IDs con retry automático
            repos = self._retry_on_cosmos_throttle(
                lambda: list(self.repos_repository.collection.find(
                    {"id": {"$in": repo_ids}},
                    {"stargazer_count": 1, "_id": 0}
                ))
            )
            
            # NOTA: Sleep removido - vCore no necesita throttling
            
            if repos is None:
                return 0
            
            total = 0
            
            for repo in repos:
                stars = repo.get("stargazer_count", 0)
                if isinstance(stars, int) and stars > 0:
                    total += stars
            
            return total
            
        except Exception as e:
            logger.error(f"❌ Error calculando total stars: {e}")
            return 0
    
    def _calculate_quantum_focus_score(
        self,
        quantum_count: int,
        total_count: int,
        is_verified: bool,
        org_name: str,
        org_description: str
    ) -> Optional[float]:
        """
        Calcula el quantum focus score de una organización.
        
        Formula:
        - Base: (quantum_repos / total_repos) * 100
        - Bonus: +10 si tiene keywords quantum en nombre/descripción
        - Multiplicador: x1.2 si es organización verificada
        
        Args:
            quantum_count: Cantidad de repos quantum
            total_count: Total de repos públicos
            is_verified: Si la org está verificada
            org_name: Nombre de la organización
            org_description: Descripción de la organización
            
        Returns:
            Score 0-100 o None si no se puede calcular
        """
        try:
            if total_count == 0:
                return 0.0
            
            # Score base
            score = (quantum_count / total_count) * 100
            
            # Bonus por keywords quantum
            quantum_keywords = [
                "quantum", "qiskit", "cirq", "qubit", "entanglement",
                "qasm", "pennylane", "tket", "braket", "qdk", "ionq"
            ]
            text = f"{org_name or ''} {org_description or ''}".lower()
            if any(keyword in text for keyword in quantum_keywords):
                score += 10
            
            # Multiplicador por verificación
            if is_verified:
                score *= 1.2
            
            # Cap a 100
            return min(score, 100.0)
            
        except Exception as e:
            logger.error(f"❌ Error calculando quantum focus score: {e}")
            return None
    
    def _finalize_stats(self) -> Dict[str, Any]:
        """Finaliza y retorna las estadísticas."""
        self.stats["end_time"] = datetime.now()
        
        if self.stats["start_time"]:
            duration = self.stats["end_time"] - self.stats["start_time"]
            self.stats["duration_seconds"] = duration.total_seconds()
        
        logger.info("\n" + "=" * 80)
        logger.info("📊 RESUMEN DE ENRIQUECIMIENTO DE ORGANIZACIONES")
        logger.info("=" * 80)
        logger.info(f"✅ Total procesadas: {self.stats['total_processed']}")
        logger.info(f"✅ Total enriquecidas: {self.stats['total_enriched']}")
        logger.info(f"❌ Total errores: {self.stats['total_errors']}")
        
        if "duration_seconds" in self.stats:
            logger.info(f"⏱️  Duración: {self.stats['duration_seconds']:.2f} segundos")
        
        return self.stats
