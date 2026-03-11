""" Motor de enriquecimiento de usuarios de GitHub - Versión 2.0 Optimizada

MEJORAS PRINCIPALES:
- Una sola super-query GraphQL por usuario (elimina rate limits)
- Modelo simplificado (30 campos esenciales vs 78 anteriores)
- Robustez: try-except por usuario, continúa en fallos
- Optimizado para vCore: batch_size escalable, sin sleeps entre operaciones de BD
- Preserva lógica core TFG: quantum_repositories, quantum_expertise_score, métricas sociales
"""

import time
import threading
import concurrent.futures
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone

from .graphql_client import GitHubGraphQLClient
from ..core.logger import logger
from ..core.mongo_repository import MongoRepository


class UserEnrichmentEngine:
    """
    Motor para enriquecer datos de usuarios con estrategia de super-query.
    Una sola llamada GraphQL obtiene todos los datos necesarios.
    """
    
    ENRICHMENT_VERSION = "3.0.0"
    
    # Tamaño de lote para queries GraphQL batched (10 usuarios por query)
    # Conservador porque la super-query es compleja (~60 nodos por usuario)
    GRAPHQL_BATCH_SIZE = 10
    
    # Fragment reutilizable con todos los campos de enriquecimiento
    ENRICHMENT_FRAGMENT = """
    fragment UserEnrichmentFields on User {
        id
        login
        name
        email
        bio
        company
        location
        pronouns
        avatarUrl
        url
        websiteUrl
        twitterUsername
        createdAt
        updatedAt
        followers { totalCount }
        following { totalCount }
        repositories(first: 10, orderBy: {field: PUSHED_AT, direction: DESC}, privacy: PUBLIC) {
          totalCount
          nodes {
            id
            name
            nameWithOwner
            description
            url
            stargazerCount
            forkCount
            primaryLanguage { name }
            isPrivate
            isFork
            isArchived
            createdAt
            updatedAt
          }
        }
        pinnedItems(first: 6, types: REPOSITORY) {
          nodes {
            ... on Repository {
              id
              name
              nameWithOwner
              description
              url
              stargazerCount
              forkCount
              primaryLanguage { name }
              isPrivate
              isFork
              isArchived
              createdAt
              updatedAt
            }
          }
        }
        starredRepositories { totalCount }
        organizations(first: 20) {
          totalCount
          nodes {
            id
            login
            name
            avatarUrl
            url
            description
          }
        }
        contributionsCollection {
          totalCommitContributions
          totalIssueContributions
          totalPullRequestContributions
          totalPullRequestReviewContributions
          totalRepositoryContributions
          restrictedContributionsCount
        }
        gists { totalCount }
        packages { totalCount }
        sponsorshipsAsMaintainer { totalCount }
        sponsorshipsAsSponsor { totalCount }
        socialAccounts(first: 10) {
          nodes {
            provider
            displayName
            url
          }
        }
        status {
          emoji
          message
          expiresAt
        }
        isHireable
        isBountyHunter
        isCampusExpert
        isDeveloperProgramMember
        isEmployee
        isGitHubStar
        isSiteAdmin
    }
    """
    
    # Query individual que usa el fragment (para fallback single-user)
    SUPER_QUERY = """
    query GetUserComplete($login: String!) {
      user(login: $login) {
        ...UserEnrichmentFields
      }
    }
    """ + ENRICHMENT_FRAGMENT
    
    def __init__(
        self,
        github_token: str,
        users_repository: MongoRepository,
        repos_repository: MongoRepository,
        batch_size: int = 100,  # ✅ OPTIMIZADO para vCore
        config: Optional[Dict[str, Any]] = None,
        progress_callback=None,
        cancel_event=None
    ):
        """
        Inicializa el motor de enriquecimiento.
        
        Args:
            github_token: Token de GitHub
            users_repository: Repositorio de usuarios
            repos_repository: Repositorio de repositorios
            batch_size: Tamaño del lote (optimizado para vCore)
            config: Configuración opcional
            progress_callback: Callback opcional fn(items_processed, items_total, message)
        """
        self.github_token = github_token
        self.users_repository = users_repository
        self.repos_repository = repos_repository
        self.batch_size = batch_size
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
        
        logger.info(f"🚀 UserEnrichmentEngine v2.0 inicializado (batch_size={batch_size})")
    
    def enrich_all_users(self, max_users: Optional[int] = None, force_reenrich: bool = False) -> Dict[str, Any]:
        """
        Enriquece todos los usuarios en MongoDB.
        
        Args:
            max_users: Límite opcional de usuarios a procesar
            force_reenrich: Si True, re-enriquece incluso usuarios ya enriquecidos
            
        Returns:
            Estadísticas del proceso
        """
        logger.info("=" * 80)
        logger.info("👥 INICIANDO ENRIQUECIMIENTO DE USUARIOS v2.0")
        logger.info("=" * 80)
        
        self.stats["start_time"] = datetime.now()
        
        # Construir query para seleccionar usuarios
        if force_reenrich:
            query = {}
            logger.info("📌 Modo force_reenrich: procesando todos los usuarios")
        else:
            # Re-enriquecer si:
            # 1. No tiene enrichment_status (nunca enriquecido)
            # 2. No tiene enriched_at (nunca enriquecido)
            # 3. No está completo (is_complete = false)
            # 4. Más de 7 días desde la última actualización
            seven_days_ago = datetime.now() - timedelta(days=7)
            query = {
                "$or": [
                    {"enrichment_status": {"$exists": False}},
                    {"enriched_at": {"$exists": False}},
                    {"enrichment_status.is_complete": False},
                    {"enriched_at": {"$lt": seven_days_ago}}
                ]
            }
            logger.info("📌 Modo incremental: usuarios sin enriquecer, incompletos o desactualizados (>7 días)")
        
        # Obtener usuarios
        users_cursor = self.users_repository.collection.find(query)
        
        if max_users:
            users_cursor = users_cursor.limit(max_users)
            logger.info(f"📊 Limitando a {max_users} usuarios")
        
        users = list(users_cursor)
        total_users = len(users)
        self._total_items = total_users
        
        logger.info(f"📊 Total usuarios a enriquecer: {total_users}")
        
        if total_users == 0:
            logger.info("✅ No hay usuarios para enriquecer")
            return self._finalize_stats()
        
        # Procesar en lotes con queries GraphQL batched + ThreadPoolExecutor
        # En vez de 1 query por usuario (N requests), hacemos 10 usuarios por query (N/10 requests)
        # Y procesamos múltiples batches en paralelo con hilos
        total_batches = (total_users + self.GRAPHQL_BATCH_SIZE - 1) // self.GRAPHQL_BATCH_SIZE
        max_concurrent = self.config.get("enrichment", {}).get("max_concurrent_batches", 3)
        logger.info(f"🚀 Procesando {total_users} usuarios con {max_concurrent} workers paralelos (batches de {self.GRAPHQL_BATCH_SIZE})")
        
        batches = []
        for i in range(0, total_users, self.GRAPHQL_BATCH_SIZE):
            batch = users[i:i + self.GRAPHQL_BATCH_SIZE]
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
                    logger.warning("⚠️ Cancelación detectada en enrich_all_users")
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
        
        Args:
            batch: Lista de usuarios a procesar
            batch_num: Número de batch actual
            total_batches: Total de batches
        """
        # Esperar si hay rate limit activo de otro hilo
        now = time.time()
        wait_remaining = self._rate_limit_until - now
        if wait_remaining > 0:
            logger.debug(f"⏳ Lote {batch_num}: esperando rate limit activo ({wait_remaining:.0f}s)...")
            time.sleep(wait_remaining)
        
        logger.info(f"\n📦 Lote GraphQL {batch_num}/{total_batches} ({len(batch)} usuarios en 1 query)")
        
        success = self._enrich_batch(batch)
        
        if not success:
            # Rate limit: esperar al reset y reintentar este batch
            logger.warning(f"⏸️ Lote {batch_num}: Rate limit detectado. Esperando reset...")
            self._wait_for_rate_limit_reset()
            # Reintentar el batch fallido
            success = self._enrich_batch(batch)
            if not success:
                logger.error(f"❌ Lote {batch_num}: Rate limit persistente después de esperar reset.")
                return
        
        logger.info(f"✅ Lote {batch_num}/{total_batches} completado")
    
    def _enrich_single_user(self, user: Dict[str, Any]) -> bool:
        """
        Enriquece un solo usuario con query individual (fallback).
        Usado cuando la query batched falla para un usuario específico.
        
        Args:
            user: Documento de usuario de MongoDB
            
        Returns:
            True si se enriqueció correctamente, False si hubo error
        """
        login = user.get("login")
        
        if not login:
            logger.warning(f"⚠️  Usuario sin campo 'login' encontrado (ID: {user.get('_id')}). Saltando...")
            with self._stats_lock:
                self.stats["total_errors"] += 1
                self.stats["total_processed"] += 1
            return False
        
        try:
            self._clean_empty_arrays(user)
            graphql_data = self._fetch_user_data(login)
            
            if not graphql_data:
                logger.warning(f"⚠️  No se pudo obtener datos de {login}")
                with self._stats_lock:
                    self.stats["total_errors"] += 1
                    self.stats["total_processed"] += 1
                return False
            
            return self._process_enrichment_data(user, graphql_data)
            
        except Exception as e:
            logger.error(f"❌ Error enriqueciendo usuario {login}: {e}")
            with self._stats_lock:
                self.stats["total_errors"] += 1
                self.stats["total_processed"] += 1
            return False
    
    def _enrich_batch(self, users_batch: List[Dict[str, Any]]) -> bool:
        """
        Enriquece un lote de usuarios con UNA sola query GraphQL batched.
        
        Optimización: 10 usuarios por query en vez de 10 queries individuales.
        Ahorra ~10x en tokens de GitHub API.
        
        Si la query batched falla, hace fallback a queries individuales
        para garantizar que no se pierde información.
        
        Args:
            users_batch: Lista de documentos de usuario de MongoDB
            
        Returns:
            True si se procesó (con o sin errores individuales),
            False si hubo rate limit (señal para abortar)
        """
        # Preparar usuarios válidos
        valid_users = []
        for user in users_batch:
            login = user.get('login')
            if not login:
                logger.warning(f"⚠️  Usuario sin login (ID: {user.get('_id')}). Saltando...")
                self.stats['total_errors'] += 1
                self.stats['total_processed'] += 1
                continue
            self._clean_empty_arrays(user)
            valid_users.append(user)
        
        if not valid_users:
            return True
        
        logins = [u['login'] for u in valid_users]
        
        # Construir y ejecutar query batched
        query, variables = self._build_enrichment_batch_query(logins)
        
        try:
            result = self.graphql_client.execute_query(query, variables)
            
            if not result or 'data' not in result:
                logger.warning("⚠️  Batch enrichment query sin datos - fallback individual")
                for user in valid_users:
                    self._enrich_single_user(user)
                return True
            
            data = result['data']
            
            for i, user in enumerate(valid_users):
                if self.cancel_event and self.cancel_event.is_set():
                    break
                alias_key = f"user{i}"
                graphql_data = data.get(alias_key)
                login = user.get('login')
                
                if not graphql_data:
                    logger.debug(f"  ⚠️  {login}: sin datos en batch (cuenta eliminada?)")
                    with self._stats_lock:
                        self.stats['total_errors'] += 1
                        self.stats['total_processed'] += 1
                    continue
                
                try:
                    self._process_enrichment_data(user, graphql_data)
                except Exception as e:
                    logger.error(f"❌ Error procesando {login}: {e}")
                    with self._stats_lock:
                        self.stats['total_errors'] += 1
                        self.stats['total_processed'] += 1
            
            return True
            
        except Exception as e:
            error_str = str(e)
            if "RATE_LIMIT" in error_str or "rate limit" in error_str.lower() or "403" in error_str or "forbidden" in error_str.lower():
                # Esperar al reset del rate limit y reintentar
                logger.warning("⏸️  Rate limit/403 en batch enrichment - Esperando reset...")
                self._wait_for_rate_limit_reset()
                return True  # Señal para que el loop reintente
            
            # Fallback: procesar individualmente para no perder datos
            logger.warning(f"⚠️  Error en batch query ({error_str[:80]}), fallback individual...")
            for user in valid_users:
                self._enrich_single_user(user)
            return True
    
    def _build_enrichment_batch_query(self, logins: List[str]) -> tuple:
        """
        Construye una query GraphQL batched para enriquecer múltiples usuarios.
        
        Usa el ENRICHMENT_FRAGMENT para evitar repetir la definición de campos.
        Cada usuario se consulta como un alias (user0, user1, ...).
        
        Args:
            logins: Lista de logins a enriquecer
            
        Returns:
            Tupla (query_string, variables_dict)
        """
        variables_decl = []
        aliases = []
        variables = {}
        
        for i, login in enumerate(logins):
            var_name = f"login{i}"
            variables_decl.append(f"${var_name}: String!")
            aliases.append(f"    user{i}: user(login: ${var_name}) {{ ...UserEnrichmentFields }}")
            variables[var_name] = login
        
        aliases_str = "\n".join(aliases)
        vars_str = ", ".join(variables_decl)
        
        query = f"""
        query EnrichUsersBatch({vars_str}) {{
{aliases_str}
        }}
        {self.ENRICHMENT_FRAGMENT}
        """
        
        return query, variables
    
    def _process_enrichment_data(self, user: Dict[str, Any], graphql_data: Dict[str, Any]) -> bool:
        """
        Procesa datos de enriquecimiento GraphQL y los guarda en MongoDB.
        
        Lógica extraída de _enrich_single_user para poder reutilizarla
        tanto en queries individuales como batched sin perder información.
        
        Args:
            user: Documento de usuario original de MongoDB
            graphql_data: Datos de la respuesta GraphQL para este usuario
            
        Returns:
            True si se procesó correctamente
        """
        login = user.get('login', 'unknown')
        
        try:
            updates = {}
            
            # Campos básicos
            self._extract_basic_fields(graphql_data, updates)
            
            # Métricas sociales (counts)
            self._extract_counts(graphql_data, updates)
            
            # Organizaciones
            self._extract_organizations(graphql_data, updates)
            
            # Repositorios pinned
            self._extract_pinned_repos(graphql_data, updates)
            
            # Top languages (calculado en memoria desde repos recientes)
            self._extract_top_languages(graphql_data, updates)
            
            # Social accounts
            self._extract_social_accounts(graphql_data, updates)
            
            # Status
            self._extract_status(graphql_data, updates)
            
            # Flags
            self._extract_flags(graphql_data, updates)
            
            # ==================== LÓGICA CORE TFG ====================
            
            # Quantum repositories (de nuestra BD)
            quantum_repos = self._find_quantum_repositories(login, user)
            if quantum_repos:
                updates["quantum_repositories"] = quantum_repos
                updates["is_quantum_contributor"] = True
                # Contribuciones all-time a repos quantum (sum de extracted_from)
                # Útil porque contributionsCollection de GitHub solo cubre el último año
                updates["contributions_to_quantum_repos"] = sum(
                    r.get("contributions", 0) for r in quantum_repos
                )
            
            # Métricas sociales calculadas
            social_metrics = self._calculate_social_metrics(user, updates)
            updates.update(social_metrics)
            
            # Quantum expertise score
            quantum_score = self._calculate_quantum_expertise(user, updates)
            if quantum_score is not None:
                updates["quantum_expertise_score"] = quantum_score
            
            # Timestamp de enriquecimiento
            updates["enriched_at"] = datetime.now()
            
            # Tracking de enriquecimiento v3.0
            updates["enrichment_status"] = {
                "is_complete": True,
                "version": "3.0",
                "last_check": datetime.now().isoformat(),
                "fields_missing": []
            }
            
            # Guardar en BD
            self.users_repository.collection.update_one(
                {"_id": user.get("_id")},
                {"$set": updates}
            )
            
            with self._stats_lock:
                self.stats["total_enriched"] += 1
                self.stats["total_processed"] += 1
            logger.debug(f"✅ {login} enriquecido")
            
            # Notificar progreso
            if self.progress_callback:
                try:
                    total = getattr(self, '_total_items', 0)
                    self.progress_callback(
                        self.stats["total_processed"], total,
                        f"Enriqueciendo usuarios: {self.stats['total_processed']}/{total}"
                    )
                except Exception:
                    pass
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error procesando enriquecimiento de {login}: {e}")
            with self._stats_lock:
                self.stats["total_errors"] += 1
                self.stats["total_processed"] += 1
            return False
    
    def _check_rate_limit(self) -> None:
        """
        Verifica rate limit de GitHub y espera si es necesario.
        Thread-safe: coordina con _rate_limit_until entre hilos.
        """
        # Primero comprobar si hay rate limit activo de otro hilo
        now = time.time()
        wait_remaining = self._rate_limit_until - now
        if wait_remaining > 0:
            logger.debug(f"⏳ Rate limit activo, esperando {wait_remaining:.0f}s...")
            time.sleep(wait_remaining)
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
        Thread-safe: coordina entre hilos con _rate_limit_lock.
        El primer hilo que detecta el rate limit loguea; los demás esperan silenciosamente.
        """
        wait_seconds = 120  # Fallback conservador
        try:
            rate_info = self.graphql_client.get_rate_limit()
            remaining = rate_info.get('remaining', 5000)
            reset_at = rate_info.get('reset_at')
            
            if reset_at:
                wait = (reset_at - datetime.now(timezone.utc)).total_seconds() + 5
                if wait > 0:
                    wait_seconds = wait
            else:
                # Consultar REST API para timestamp real
                try:
                    rest_info = self.graphql_client._get_rate_limit_rest()
                    gql_reset = rest_info.get('resources', {}).get('graphql', {}).get('reset', 0)
                    if gql_reset > 0:
                        wait_seconds = max(0, gql_reset - time.time()) + 5
                except Exception:
                    pass
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
    
    def _fetch_user_data(self, login: str) -> Optional[Dict[str, Any]]:
        """
        Ejecuta la super-query para obtener TODOS los datos del usuario.
        
        Args:
            login: Login del usuario
            
        Returns:
            Datos del usuario o None si falla
        """
        try:
            variables = {"login": login}
            response = self.graphql_client.execute_query(self.SUPER_QUERY, variables)
            
            if "errors" in response:
                logger.error(f"❌ Error GraphQL para {login}: {response['errors']}")
                return None
            
            return response.get("data", {}).get("user")
            
        except Exception as e:
            logger.error(f"❌ Error ejecutando super-query para {login}: {e}")
            return None
    
    def _clean_empty_arrays(self, user: Dict[str, Any]) -> None:
        """Limpia arrays vacíos del usuario (legacy data)."""
        empty_arrays = [k for k, v in user.items() if v == []]
        if empty_arrays:
            self.users_repository.collection.update_one(
                {"_id": user.get("_id")},
                {"$set": {k: None for k in empty_arrays}}
            )
    
    def _extract_basic_fields(self, data: Dict[str, Any], updates: Dict[str, Any]) -> None:
        """Extrae campos básicos del perfil."""
        basic_fields = [
            "name", "email", "bio", "company", "location", "pronouns",
            "avatarUrl", "websiteUrl", "twitterUsername", "createdAt", "updatedAt"
        ]
        
        for field in basic_fields:
            value = data.get(field)
            if value is not None:
                # Convertir camelCase a snake_case
                field_name = field
                if field == "avatarUrl":
                    field_name = "avatar_url"
                elif field == "websiteUrl":
                    field_name = "website_url"
                elif field == "twitterUsername":
                    field_name = "twitter_username"
                elif field == "createdAt":
                    field_name = "created_at"
                elif field == "updatedAt":
                    field_name = "updated_at"
                
                updates[field_name] = value
    
    def _extract_counts(self, data: Dict[str, Any], updates: Dict[str, Any]) -> None:
        """Extrae todos los contadores."""
        updates["followers_count"] = data.get("followers", {}).get("totalCount", 0)
        updates["following_count"] = data.get("following", {}).get("totalCount", 0)
        updates["public_repos_count"] = data.get("repositories", {}).get("totalCount", 0)
        updates["starred_repos_count"] = data.get("starredRepositories", {}).get("totalCount", 0)
        updates["organizations_count"] = data.get("organizations", {}).get("totalCount", 0)
        updates["public_gists_count"] = data.get("gists", {}).get("totalCount", 0)
        updates["packages_count"] = data.get("packages", {}).get("totalCount", 0)
        updates["sponsors_count"] = data.get("sponsorshipsAsMaintainer", {}).get("totalCount", 0)
        updates["sponsoring_count"] = data.get("sponsorshipsAsSponsor", {}).get("totalCount", 0)
        
        # Contribuciones
        contributions = data.get("contributionsCollection", {})
        if contributions:
            updates["total_commit_contributions"] = contributions.get("totalCommitContributions", 0)
            updates["total_issue_contributions"] = contributions.get("totalIssueContributions", 0)
            updates["total_pr_contributions"] = contributions.get("totalPullRequestContributions", 0)
            updates["total_pr_review_contributions"] = contributions.get("totalPullRequestReviewContributions", 0)
    
    def _extract_organizations(self, data: Dict[str, Any], updates: Dict[str, Any]) -> None:
        """Extrae organizaciones."""
        orgs_data = data.get("organizations", {}).get("nodes", [])
        
        if orgs_data:
            updates["organizations"] = [
                {
                    "id": org.get("id"),
                    "login": org.get("login"),
                    "name": org.get("name"),
                    "avatar_url": org.get("avatarUrl"),
                    "url": org.get("url"),
                    "description": org.get("description")
                }
                for org in orgs_data
            ]
    
    def _extract_pinned_repos(self, data: Dict[str, Any], updates: Dict[str, Any]) -> None:
        """Extrae repositorios pinned."""
        pinned_data = data.get("pinnedItems", {}).get("nodes", [])
        
        if pinned_data:
            updates["pinned_repositories"] = [
                {
                    "id": repo.get("id"),
                    "name": repo.get("name"),
                    "name_with_owner": repo.get("nameWithOwner"),
                    "description": repo.get("description"),
                    "url": repo.get("url"),
                    "stargazer_count": repo.get("stargazerCount", 0),
                    "fork_count": repo.get("forkCount", 0),
                    "primary_language": repo.get("primaryLanguage", {}).get("name") if repo.get("primaryLanguage") else None,
                    "is_private": repo.get("isPrivate", False),
                    "is_fork": repo.get("isFork", False),
                    "is_archived": repo.get("isArchived", False),
                    "created_at": repo.get("createdAt"),
                    "updated_at": repo.get("updatedAt")
                }
                for repo in pinned_data
            ]
    
    def _extract_top_languages(self, data: Dict[str, Any], updates: Dict[str, Any]) -> None:
        """
        Calcula top languages en memoria desde los 10 repos más recientes.
        Reemplaza la necesidad de queries adicionales.
        """
        repos_data = data.get("repositories", {}).get("nodes", [])
        
        if repos_data:
            # Contar lenguajes
            language_counts = {}
            for repo in repos_data:
                lang = repo.get("primaryLanguage", {}).get("name") if repo.get("primaryLanguage") else None
                if lang:
                    language_counts[lang] = language_counts.get(lang, 0) + 1
            
            # Top 5 lenguajes
            if language_counts:
                sorted_langs = sorted(language_counts.items(), key=lambda x: x[1], reverse=True)
                updates["top_languages"] = [lang for lang, count in sorted_langs[:5]]
    
    def _extract_social_accounts(self, data: Dict[str, Any], updates: Dict[str, Any]) -> None:
        """Extrae cuentas sociales."""
        social_data = data.get("socialAccounts", {}).get("nodes", [])
        
        if social_data:
            updates["social_accounts"] = [
                {
                    "provider": acc.get("provider"),
                    "display_name": acc.get("displayName"),
                    "url": acc.get("url")
                }
                for acc in social_data
            ]
    
    def _extract_status(self, data: Dict[str, Any], updates: Dict[str, Any]) -> None:
        """Extrae status del usuario."""
        status = data.get("status")
        
        if status:
            updates["status_emoji"] = status.get("emoji")
            updates["status_message"] = status.get("message")
    
    def _extract_flags(self, data: Dict[str, Any], updates: Dict[str, Any]) -> None:
        """Extrae flags del usuario."""
        flag_fields = [
            "isHireable", "isBountyHunter", "isCampusExpert", 
            "isDeveloperProgramMember", "isEmployee", "isGitHubStar", 
            "isSiteAdmin"
        ]
        
        for field in flag_fields:
            value = data.get(field)
            if value is not None:
                # Convertir a snake_case
                field_name = ''.join(['_' + c.lower() if c.isupper() else c for c in field]).lstrip('_')
                updates[field_name] = value
    
    # ==================== MÉTODOS CORE TFG (PRESERVADOS) ====================
    
    def _find_quantum_repositories(self, login: str, user: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        """
        Encuentra repositorios quantum del usuario en nuestra base de datos.
        
        Busca:
        1. Repos donde el usuario es owner
        2. Repos donde el usuario es colaborador
        
        Obtiene contribuciones del campo extracted_from del usuario.
        """
        try:
            quantum_repos = []
            
            # Buscar en repos ingestados
            repos = self.repos_repository.collection.find({
                "$or": [
                    {"owner.login": login},
                    {"collaborators.login": login}
                ]
            })
            
            # Crear mapa de contribuciones desde extracted_from
            extracted_from = user.get("extracted_from", [])
            contributions_map = {}
            for extraction in extracted_from:
                repo_id = extraction.get("repo_id")
                if repo_id:
                    contributions_map[repo_id] = extraction.get("contributions", 0)
            
            for repo in repos:
                repo_id = repo.get("id")
                # Determinar rol
                role = "owner" if repo.get("owner", {}).get("login") == login else "collaborator"
                
                # Obtener contribuciones del mapa
                contributions = contributions_map.get(repo_id, 0)
                
                # Manejar primary_language que puede ser string o dict
                primary_lang = repo.get("primary_language")
                if isinstance(primary_lang, dict):
                    primary_lang_name = primary_lang.get("name")
                elif isinstance(primary_lang, str):
                    primary_lang_name = primary_lang
                else:
                    primary_lang_name = None
                
                quantum_repos.append({
                    "id": repo_id,
                    "name": repo.get("name"),
                    "name_with_owner": repo.get("name_with_owner"),
                    "stars": repo.get("stargazer_count", 0),
                    "role": role,
                    "contributions": contributions,
                    "primary_language": primary_lang_name
                })
            
            return quantum_repos if quantum_repos else None
            
        except Exception as e:
            logger.error(f"❌ Error buscando quantum repos de {login}: {e}")
            return None
    
    def _calculate_social_metrics(self, user: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        """Calcula métricas sociales del usuario."""
        metrics = {}
        
        # Ratio followers/following
        followers = updates.get("followers_count") or user.get("followers_count") or 0
        following = updates.get("following_count") or user.get("following_count") or 0
        
        if following > 0:
            metrics["follower_following_ratio"] = round(followers / following, 2)
        else:
            metrics["follower_following_ratio"] = followers
        
        # Stars per repo: calcular promedio en repos relevantes (owner O colaborador activo)
        quantum_repos = updates.get("quantum_repositories", [])
        
        if quantum_repos:
            relevant_repos = []
            total_stars = 0
            
            for repo in quantum_repos:
                stars = repo.get("stars", 0) or 0
                contributions = repo.get("contributions", 0) or 0
                
                # Incluir si es owner O tiene más de 5 contribuciones (colaborador activo)
                if repo.get("role") == "owner" or contributions > 5:
                    relevant_repos.append(repo)
                    total_stars += stars
            
            # Calcular promedio con repos relevantes
            if len(relevant_repos) > 0:
                metrics["stars_per_repo"] = round(total_stars / len(relevant_repos), 2)
                metrics["relevant_repos_count"] = len(relevant_repos)
                metrics["total_stars_received"] = total_stars
        
        return metrics
    
    def _calculate_quantum_expertise(self, user: Dict[str, Any], updates: Dict[str, Any]) -> Optional[float]:
        """
        Calcula un score de expertise en quantum computing.
        
        Factores:
        - Número de repos quantum (owner vs colaborador)
        - Estrellas en repos quantum
        - Contribuciones en repos quantum
        - Organizaciones relacionadas con quantum
        """
        try:
            score = 0.0
            
            # Factor 1: Repos quantum como owner (peso: 5 puntos c/u)
            quantum_repos = updates.get("quantum_repositories", user.get("quantum_repositories", []))
            if quantum_repos:
                owner_repos = [r for r in quantum_repos if r.get("role") == "owner"]
                collab_repos = [r for r in quantum_repos if r.get("role") == "collaborator"]
                
                score += len(owner_repos) * 5.0
                score += len(collab_repos) * 2.0
                
                # Factor 2: Estrellas (peso: 0.1 por estrella, máx 50 puntos)
                total_stars = sum(r.get("stars", 0) for r in quantum_repos)
                score += min(total_stars * 0.1, 50.0)
                
                # Factor 3: Contribuciones (peso: 0.05 por contribución, máx 25 puntos)
                total_contributions = sum(r.get("contributions", 0) for r in quantum_repos)
                score += min(total_contributions * 0.05, 25.0)
            
            # Factor 4: Organizaciones quantum (peso: 10 puntos c/u)
            orgs = updates.get("organizations", user.get("organizations", []))
            if orgs:
                quantum_orgs = [
                    org for org in orgs 
                    if any(keyword in ((org.get("name") or "") + (org.get("description") or "")).lower() 
                           for keyword in ["quantum", "qiskit", "cirq", "pennylane"])
                ]
                score += len(quantum_orgs) * 10.0
            
            # Normalizar a escala 0-100
            score = min(score, 100.0)
            
            return round(score, 2) if score > 0 else None
            
        except Exception as e:
            logger.error(f"❌ Error calculando quantum expertise: {e}")
            return None
    
    def _finalize_stats(self) -> Dict[str, Any]:
        """Finaliza y retorna las estadísticas."""
        self.stats["end_time"] = datetime.now()
        
        if self.stats["start_time"]:
            duration = self.stats["end_time"] - self.stats["start_time"]
            self.stats["duration_seconds"] = duration.total_seconds()
        
        logger.info("\n" + "=" * 80)
        logger.info("📊 RESUMEN DE ENRIQUECIMIENTO")
        logger.info("=" * 80)
        logger.info(f"✅ Total procesados: {self.stats['total_processed']}")
        logger.info(f"✅ Total enriquecidos: {self.stats['total_enriched']}")
        logger.info(f"❌ Total errores: {self.stats['total_errors']}")
        
        if "duration_seconds" in self.stats:
            logger.info(f"Duración: {self.stats['duration_seconds']:.2f} segundos")
        
        return self.stats
