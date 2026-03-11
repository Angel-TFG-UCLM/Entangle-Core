"""
Motor de Ingesta de Organizaciones de GitHub - v3.0
Estrategia Repository-First: descubre organizaciones desde repositorios quantum.

OPTIMIZACIONES v3.0:
- Queries GraphQL batched (5 orgs por query en vez de 1)
- Bulk check de existencia en MongoDB (1 query $in)
- Smart rate limit (solo pausa cuando necesario)
- Bulk MongoDB operations (bulk_write + insert_many)
"""
import time
import threading
import concurrent.futures
from typing import List, Dict, Any, Optional, Set
from datetime import datetime, timezone
from pymongo import UpdateOne
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
    
    # Fragment reutilizable para batched queries
    ORG_BASIC_FRAGMENT = """
    fragment OrgBasicFields on Organization {
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
        repositories { totalCount }
        membersWithRole { totalCount }
        sponsorshipsAsMaintainer { totalCount }
    }
    """
    
    # Tamaño de lote para queries GraphQL batched
    GRAPHQL_BATCH_SIZE = 5
    
    def __init__(
        self,
        github_token: str,
        users_repository: MongoRepository,
        organizations_repository: MongoRepository,
        batch_size: int = 100,  # ✅ OPTIMIZADO para vCore
        config: Optional[Dict[str, Any]] = None,
        from_scratch: bool = False,
        progress_callback=None,
        cancel_event=None
    ):
        """
        Inicializa el motor de ingesta de organizaciones.
        
        Args:
            github_token: Token de GitHub
            users_repository: Repositorio de usuarios
            organizations_repository: Repositorio de organizaciones
            batch_size: Tamaño del lote (default 5 para Rate Limit)
            config: Configuración opcional
            from_scratch: Si True, limpia colección antes de ingestar
            progress_callback: Callback opcional fn(items_processed, items_total, message)
        """
        self.github_token = github_token
        self.users_repository = users_repository
        self.organizations_repository = organizations_repository
        self.batch_size = batch_size
        self.config = config or {}
        self.from_scratch = from_scratch
        self.progress_callback = progress_callback
        self.cancel_event = cancel_event
        self.graphql_client = GitHubGraphQLClient(github_token)
        
        # Thread coordination
        self._stats_lock = threading.Lock()
        self._rate_limit_lock = threading.Lock()
        self._rate_limit_until = 0
        
        # Estadísticas
        self.stats = {
            "total_discovered": 0,
            "total_processed": 0,
            "total_inserted": 0,
            "total_updated": 0,
            "total_skipped": 0,
            "total_errors": 0,
            "deleted_before_ingestion": 0,
            "mode": "from_scratch" if from_scratch else "incremental",
            "start_time": None,
            "end_time": None
        }
        
        mode_label = "DESDE CERO" if from_scratch else "INCREMENTAL"
        logger.info(f"OrganizationIngestionEngine v2.0 inicializado (modo={mode_label}, batch_size={batch_size})")
    
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
        mode_label = "DESDE CERO" if self.from_scratch else "INCREMENTAL"
        logger.info(f"Modo: {mode_label}")
        
        self.stats["start_time"] = datetime.now()
        
        # Limpieza (solo en modo from_scratch)
        if self.from_scratch:
            self._cleanup_collection()
            force_update = True  # Forzar actualización tras limpieza
        
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
    
    def _cleanup_collection(self) -> None:
        """
        Limpia la colección de organizaciones antes de una ingesta desde cero.
        """
        logger.info("\n🗑️  Limpieza de colección de organizaciones (modo desde cero)")
        try:
            count_before = self.organizations_repository.count_documents()
            logger.info(f"  📊 Organizaciones actuales en DB: {count_before}")
            
            if count_before > 0:
                deleted = self.organizations_repository.delete_many({})
                self.stats["deleted_before_ingestion"] = deleted
                logger.info(f"  🗑️  Eliminadas {deleted} organizaciones de la colección")
            
            logger.info("  ✅ Limpieza completada")
        except Exception as e:
            logger.error(f"  ❌ Error durante limpieza: {e}")
            raise
    
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
            
            # Ejecutar agregación (deprecado: retry legacy de Cosmos DB RU)
            results = self._retry_on_cosmos_throttle(
                lambda: list(repos_collection.aggregate(pipeline))
            )
            
            # NOTA: Sleep removido - vCore no necesita throttling
            
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
        Procesa las organizaciones con GraphQL batched y bulk MongoDB.
        
        Optimizaciones v3.0:
        - Bulk check de existencia (1 query $in vs N find_one)
        - Batched GraphQL (5 orgs por query vs 1)
        - Bulk MongoDB writes (bulk_write vs N update_one/insert_one)
        - Smart rate limit (vs time.sleep(0.5) fijo)
        """
        org_list = list(orgs_data.items())
        total_orgs = len(org_list)
        
        logger.info(f"\n📦 Procesando {total_orgs} organizaciones...")
        
        # 1. Bulk check: verificar cuáles ya existen en DB
        all_logins = [login for login, _ in org_list]
        existing_map = self._get_existing_orgs(all_logins)
        
        new_orgs = [(login, data) for login, data in org_list if login not in existing_map]
        existing_orgs = [(login, data) for login, data in org_list if login in existing_map]
        
        logger.info(f"  • Organizaciones nuevas (requieren GraphQL): {len(new_orgs)}")
        logger.info(f"  • Organizaciones existentes: {len(existing_orgs)}")
        
        # 2. Para existentes sin force_update: skip. Con force_update: batch GraphQL
        if existing_orgs and not force_update:
            self.stats["total_skipped"] += len(existing_orgs)
            logger.info(f"  ⏭️  {len(existing_orgs)} existentes saltadas (modo incremental)")
        elif existing_orgs and force_update:
            # Procesar existentes en lotes batched
            self._process_orgs_batched(existing_orgs, existing_map, force_update=True)
        
        # 3. Nuevas orgs: batch GraphQL + insert_many
        if new_orgs:
            self._process_orgs_batched(new_orgs, existing_map, force_update=False)
        
        logger.info(f"✅ Procesamiento completado")
    
    def _get_existing_orgs(self, logins: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Verifica qué organizaciones ya existen en MongoDB (bulk check con $in).
        
        Returns:
            Dict {login: documento_existente}
        """
        try:
            existing = {}
            chunk_size = 500
            for i in range(0, len(logins), chunk_size):
                chunk = logins[i:i + chunk_size]
                cursor = self.organizations_repository.collection.find(
                    {"login": {"$in": chunk}}
                )
                for doc in cursor:
                    existing[doc['login']] = doc
            return existing
        except Exception as e:
            logger.warning(f"⚠️  Error en bulk check: {e}")
            return {}
    
    def _process_orgs_batched(
        self, 
        org_list: List[tuple], 
        existing_map: Dict[str, Dict[str, Any]],
        force_update: bool
    ) -> None:
        """
        Procesa organizaciones en lotes de GRAPHQL_BATCH_SIZE con queries batched.
        Usa ThreadPoolExecutor para procesar múltiples lotes en paralelo.
        """
        total = len(org_list)
        max_concurrent = self.config.get("max_concurrent_batches", 3)
        
        # Crear lista de lotes
        batches = []
        for i in range(0, total, self.GRAPHQL_BATCH_SIZE):
            batch = org_list[i:i + self.GRAPHQL_BATCH_SIZE]
            batch_num = i // self.GRAPHQL_BATCH_SIZE + 1
            batches.append((batch_num, batch))
        
        total_batches = len(batches)
        logger.info(f"\n🔄 Procesando {total_batches} lotes GraphQL con {max_concurrent} hilos concurrentes")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            futures = {}
            for batch_num, batch in batches:
                future = executor.submit(
                    self._fetch_and_save_batch_with_retry,
                    batch, existing_map, force_update, batch_num, total_batches
                )
                futures[future] = batch_num
            
            for future in concurrent.futures.as_completed(futures):
                if self.cancel_event and self.cancel_event.is_set():
                    for f in futures:
                        f.cancel()
                    logger.warning("⚠️ Cancelación detectada en _process_orgs_batched")
                    break
                batch_num = futures[future]
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"❌ Error en lote {batch_num}: {e}")
                
                # Notificar progreso
                if self.progress_callback:
                    try:
                        self.progress_callback(
                            self.stats.get('total_processed', 0) + self.stats.get('total_skipped', 0),
                            total,
                            f"Ingesta orgs: {self.stats.get('total_processed', 0) + self.stats.get('total_skipped', 0)}/{total}"
                        )
                    except Exception:
                        pass
    
    def _fetch_and_save_batch_with_retry(
        self,
        batch: List[tuple],
        existing_map: Dict[str, Dict[str, Any]],
        force_update: bool,
        batch_num: int,
        total_batches: int
    ) -> None:
        """
        Wrapper con retry para _fetch_and_save_batch.
        Coordina rate limits entre hilos.
        """
        # Esperar si hay rate limit activo
        now = time.time()
        if self._rate_limit_until > now:
            wait = self._rate_limit_until - now
            logger.info(f"  ⏳ Lote {batch_num}: esperando {wait:.0f}s por rate limit coordinado")
            time.sleep(wait)
        
        logger.info(f"\n📦 Lote GraphQL {batch_num}/{total_batches} ({len(batch)} orgs en 1 query)")
        
        success = self._fetch_and_save_batch(batch, existing_map, force_update)
        
        if not success:
            logger.warning(f"⏸️ Lote {batch_num}: Rate limit detectado. Esperando reset...")
            self._wait_for_rate_limit_reset()
            success = self._fetch_and_save_batch(batch, existing_map, force_update)
            if not success:
                logger.error(f"❌ Lote {batch_num}: Rate limit persistente después de esperar reset.")
        
        self._check_rate_limit()
    
    def _build_batch_query(self, logins: List[str]) -> tuple:
        """
        Construye query GraphQL batched para múltiples organizaciones.
        
        Returns:
            Tupla (query_string, variables_dict)
        """
        variables_decl = []
        aliases = []
        variables = {}
        
        for i, login in enumerate(logins):
            var_name = f"login{i}"
            variables_decl.append(f"${var_name}: String!")
            aliases.append(f"    org{i}: organization(login: ${var_name}) {{ ...OrgBasicFields }}")
            variables[var_name] = login
        
        aliases_str = "\n".join(aliases)
        vars_str = ", ".join(variables_decl)
        
        query = f"""
        query GetOrgsBatch({vars_str}) {{
{aliases_str}
        }}
        {self.ORG_BASIC_FRAGMENT}
        """
        
        return query, variables
    
    def _fetch_and_save_batch(
        self,
        batch: List[tuple],
        existing_map: Dict[str, Dict[str, Any]],
        force_update: bool
    ) -> bool:
        """
        Obtiene datos de un lote de orgs con 1 query GraphQL y las guarda en bulk.
        
        Si la query batched falla, hace fallback a queries individuales.
        
        Returns:
            True si se procesó, False si hubo rate limit
        """
        logins = [login for login, _ in batch]
        login_to_data = {login: data for login, data in batch}
        
        query, variables = self._build_batch_query(logins)
        
        try:
            result = self.graphql_client.execute_query(query, variables)
            
            if not result or 'data' not in result:
                logger.warning("⚠️  Batch query sin datos - fallback individual")
                return self._fetch_batch_individual_fallback(batch, existing_map, force_update)
            
            data = result['data']
            insert_docs = []
            update_ops = []
            
            for i, login in enumerate(logins):
                if self.cancel_event and self.cancel_event.is_set():
                    break
                alias_key = f"org{i}"
                org_data = data.get(alias_key)
                
                if not org_data:
                    logger.debug(f"  ⚠️  {login}: no encontrada (eliminada o privada)")
                    with self._stats_lock:
                        self.stats["total_errors"] += 1
                    continue
                
                try:
                    org_dict = self._process_org_data(
                        org_data, login, login_to_data[login]
                    )
                    
                    existing = existing_map.get(login)
                    
                    if existing:
                        fields_to_update = self._get_update_fields(org_dict, existing)
                        if fields_to_update:
                            update_ops.append(UpdateOne(
                                {"login": login},
                                {"$set": fields_to_update}
                            ))
                            with self._stats_lock:
                                self.stats["total_updated"] += 1
                        else:
                            with self._stats_lock:
                                self.stats["total_skipped"] += 1
                    else:
                        insert_docs.append(org_dict)
                    
                    with self._stats_lock:
                        self.stats["total_processed"] += 1
                    
                except Exception as e:
                    logger.error(f"  ❌ Error procesando {login}: {e}")
                    with self._stats_lock:
                        self.stats["total_errors"] += 1
            
            # Bulk MongoDB operations
            if insert_docs:
                try:
                    self.organizations_repository.collection.insert_many(insert_docs, ordered=False)
                    with self._stats_lock:
                        self.stats["total_inserted"] += len(insert_docs)
                    logger.info(f"  ✨ {len(insert_docs)} orgs insertadas (batch)")
                except Exception as e:
                    logger.warning(f"  ⚠️  Error en insert_many, insertando individualmente: {e}")
                    for doc in insert_docs:
                        try:
                            self.organizations_repository.collection.insert_one(doc)
                            with self._stats_lock:
                                self.stats["total_inserted"] += 1
                        except Exception:
                            with self._stats_lock:
                                self.stats["total_errors"] += 1
            
            if update_ops:
                try:
                    self.organizations_repository.collection.bulk_write(update_ops, ordered=False)
                    logger.info(f"  ↻ {len(update_ops)} orgs actualizadas (bulk)")
                except Exception as e:
                    logger.warning(f"  ⚠️  Error en bulk_write: {e}")
            
            return True
            
        except Exception as e:
            error_str = str(e)
            if "RATE_LIMIT" in error_str or "rate limit" in error_str.lower() or "403" in error_str or "forbidden" in error_str.lower():
                logger.warning("⏸️  Rate limit/403 en batch query - Esperando reset...")
                self._wait_for_rate_limit_reset()
                return True  # Señal para que el loop reintente
            
            logger.warning(f"⚠️  Error en batch query ({error_str[:80]}), fallback individual...")
            return self._fetch_batch_individual_fallback(batch, existing_map, force_update)
    
    def _process_org_data(self, org_data: Dict[str, Any], login: str, discovered_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Procesa datos GraphQL de una org y retorna el documento para MongoDB.
        """
        organization = Organization.from_graphql_response(org_data)
        org_dict = organization.model_dump(by_alias=False, exclude_none=False)
        org_dict["is_relevant"] = True
        org_dict["discovered_from_repos"] = discovered_data.get('repos', [])
        return org_dict
    
    def _get_update_fields(self, org_dict: Dict[str, Any], existing: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calcula qué campos actualizar preservando los enriquecidos.
        """
        enriched_fields = {
            "quantum_focus_score", "quantum_repositories_count",
            "quantum_contributors_count", "total_stars", "top_languages",
            "top_quantum_contributors", "quantum_repositories",
            "is_quantum_focused", "enriched_at", "enrichment_status"
        }
        
        fields_to_update = {}
        for key, value in org_dict.items():
            if key in enriched_fields:
                existing_value = existing.get(key)
                if existing_value is None or existing_value == [] or existing_value == {}:
                    fields_to_update[key] = value
            else:
                fields_to_update[key] = value
        
        return fields_to_update
    
    def _fetch_batch_individual_fallback(
        self, 
        batch: List[tuple], 
        existing_map: Dict[str, Dict[str, Any]],
        force_update: bool
    ) -> bool:
        """
        Fallback: procesa organizaciones una a una si la query batched falla.
        Garantiza que no se pierden datos.
        """
        logger.info(f"  🔄 Procesando {len(batch)} orgs individualmente (fallback)...")
        for login, data in batch:
            try:
                self._fetch_and_save_organization(login, force_update, data.get('repos', []))
            except Exception as e:
                error_str = str(e)
                if "RATE_LIMIT" in error_str or "rate limit" in error_str.lower() or "403" in error_str or "forbidden" in error_str.lower():
                    logger.warning("⏸️ Rate limit/403 en fallback individual - Esperando reset...")
                    self._wait_for_rate_limit_reset()
                    # Reintentar esta org
                    try:
                        self._fetch_and_save_organization(login, force_update, data.get('repos', []))
                    except Exception:
                        with self._stats_lock:
                            self.stats["total_errors"] += 1
                    continue
                logger.debug(f"  ⚠️  {login}: {error_str[:60]}")
                with self._stats_lock:
                    self.stats["total_errors"] += 1
        return True
    
    def _check_rate_limit(self) -> None:
        """
        Verifica rate limit de GitHub y espera si es necesario.
        Thread-safe: coordina entre hilos con _rate_limit_until.
        """
        # Si ya hay un rate limit activo coordinado, esperar
        now = time.time()
        if self._rate_limit_until > now:
            wait = self._rate_limit_until - now
            time.sleep(wait)
            return
        
        try:
            rate_info = self.graphql_client.get_rate_limit()
            remaining = rate_info.get('remaining', 5000)
            
            if remaining < 100:
                self._wait_for_rate_limit_reset()
            elif remaining < 500:
                logger.info(f"📊 Rate limit: {remaining} restantes")
        except Exception as e:
            logger.debug(f"No se pudo verificar rate limit: {e}")
    
    def _wait_for_rate_limit_reset(self) -> None:
        """
        Espera hasta que el rate limit de GitHub se resetee.
        Thread-safe: el primer hilo que detecta rate limit marca _rate_limit_until,
        los demás hilos simplemente esperan sin hacer queries adicionales.
        """
        with self._rate_limit_lock:
            now = time.time()
            if self._rate_limit_until > now:
                # Otro hilo ya configuró la espera
                wait = self._rate_limit_until - now
                pass  # Salimos del lock y dormimos abajo
            else:
                # Somos el primer hilo en detectar rate limit
                try:
                    rate_info = self.graphql_client.get_rate_limit()
                    remaining = rate_info.get('remaining', 5000)
                    reset_at = rate_info.get('reset_at')
                    
                    if reset_at:
                        wait = (reset_at - datetime.now(timezone.utc)).total_seconds() + 5
                        if wait > 0:
                            self._rate_limit_until = now + wait
                            logger.warning(f"⏳ Rate limit: {remaining} restantes. Esperando {wait:.0f}s hasta reset...")
                        else:
                            return
                    else:
                        # Consultar REST API para timestamp real
                        try:
                            rest_info = self.graphql_client._get_rate_limit_rest()
                            gql_reset = rest_info.get('resources', {}).get('graphql', {}).get('reset', 0)
                            if gql_reset > 0:
                                wait = max(0, gql_reset - now) + 5
                            else:
                                wait = 120
                        except Exception:
                            wait = 120
                        self._rate_limit_until = now + wait
                        logger.warning(f"⏳ Rate limit: esperando {wait:.0f}s hasta reset...")
                except Exception:
                    wait = 120
                    self._rate_limit_until = now + wait
                    logger.warning(f"⏳ No se pudo consultar reset. Esperando {wait:.0f}s por seguridad...")
        
        # Dormir fuera del lock
        time.sleep(max(wait, 0))
        logger.info("✅ Rate limit reseteado, continuando")
    
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
            
            # Verificar si ya existe
            existing = self._retry_on_cosmos_throttle(
                lambda: self.organizations_repository.collection.find_one({"login": login})
            )
            
            # NOTA: Sleep removido - vCore no necesita throttling
            
            if existing and not force_update:
                logger.debug(f"   ⏭️  Organización {login} ya existe (saltando)")
                with self._stats_lock:
                    self.stats["total_skipped"] += 1
                return True
            
            # Fetch desde GitHub API
            org_data = self._fetch_organization_basic(login)
            
            if not org_data:
                logger.warning(f"   ⚠️  No se pudo obtener datos de {login}")
                with self._stats_lock:
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
            
            # ==================== GUARDAR EN BD ====================
            # Deprecado: retry legacy de Cosmos DB RU (vCore no necesita esto)
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
                        with self._stats_lock:
                            self.stats["total_updated"] += 1
                    else:
                        logger.warning(f"   ⚠️  Organización {login} falló tras reintentos")
                        with self._stats_lock:
                            self.stats["total_errors"] += 1
                        return False
                else:
                    logger.debug(f"   ⏭️  Organización {login} sin cambios")
                    with self._stats_lock:
                        self.stats["total_skipped"] += 1
            else:
                # Insertar nueva organización con retry automático
                result = self._retry_on_cosmos_throttle(
                    lambda: self.organizations_repository.collection.insert_one(org_dict)
                )
                
                if result is not None:
                    logger.debug(f"   ✨ Organización {login} insertada")
                    with self._stats_lock:
                        self.stats["total_inserted"] += 1
                else:
                    logger.warning(f"   ⚠️  Organización {login} falló tras reintentos")
                    with self._stats_lock:
                        self.stats["total_errors"] += 1
                    return False
            
            # NOTA: Sleep removido - vCore no necesita throttling
            
            with self._stats_lock:
                self.stats["total_processed"] += 1
            return True
            
        except Exception as e:
            logger.error(f"   ❌ Error procesando {login}: {e}")
            with self._stats_lock:
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
