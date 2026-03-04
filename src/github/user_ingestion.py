"""
Motor de ingesta de usuarios de GitHub.

Extrae usuarios desde el campo 'collaborators' de repositorios ya ingestados.
Este campo ya contiene la fusión de:
- Contributors (REST API)
- Mentionable Users (GraphQL)
- Con flags: has_commits, is_mentionable, contributions

Flujo:
1. Extracción de usuarios únicos desde campo 'collaborators' en MongoDB
2. Deduplicación por ID único de GitHub
3. Búsqueda de información básica via GraphQL
4. Validación con modelo Pydantic
5. Almacenamiento en MongoDB
"""

import time
import threading
import concurrent.futures
from typing import List, Dict, Any, Optional, Set
from datetime import datetime, timezone
from pydantic import ValidationError

from .graphql_client import GitHubGraphQLClient
from ..core.logger import logger
from ..core.mongo_repository import MongoRepository
from ..models.user import User


class UserIngestionEngine:
    """
    Motor de ingesta de usuarios desde repositorios ya ingestados.
    
    Extrae usuarios únicos del campo 'collaborators' que ya contiene:
    - Contributors con commits (REST)
    - Mentionable users (GraphQL)
    - Metadata: has_commits, is_mentionable, contributions
    
    Modos:
    - incremental (default): Salta usuarios ya existentes en DB, solo añade nuevos
    - from_scratch: Limpia la colección de usuarios y reingesta todo
    """
    
    def __init__(
        self,
        github_client: GitHubGraphQLClient,
        repos_repository: MongoRepository,
        users_repository: MongoRepository,
        batch_size: int = 500,  # ✅ OPTIMIZADO para vCore
        from_scratch: bool = False,
        progress_callback=None,
        cancel_event=None
    ):
        """
        Inicializa el motor de ingesta de usuarios.
        
        Args:
            github_client: Cliente GraphQL de GitHub
            repos_repository: Repositorio de repositorios
            users_repository: Repositorio de usuarios
            batch_size: Tamaño del lote para procesamiento
            from_scratch: Si True, limpia colección antes de ingestar
            progress_callback: Callback opcional fn(items_processed, items_total, message)
        """
        self.github_client = github_client
        self.repos_repository = repos_repository
        self.users_repository = users_repository
        self.batch_size = batch_size
        self.from_scratch = from_scratch
        self.progress_callback = progress_callback
        self.cancel_event = cancel_event
        
        # Lock para estadísticas thread-safe
        self._stats_lock = threading.Lock()
        
        # Coordinación de rate limit entre hilos
        self._rate_limit_lock = threading.Lock()
        self._rate_limit_until = 0  # timestamp epoch hasta el que esperar
        
        # Estadísticas
        self.stats = {
            "repos_processed": 0,
            "users_found": 0,
            "unique_users": 0,
            "users_inserted": 0,
            "users_existing": 0,
            "bots_detected": 0,
            "real_users": 0,
            "total_errors": 0,
            "deleted_before_ingestion": 0,
            "mode": "from_scratch" if from_scratch else "incremental",
            "start_time": None,
            "end_time": None,
            "duration_seconds": 0
        }
        
        mode_label = "DESDE CERO" if from_scratch else "INCREMENTAL"
        logger.info(f"UserIngestionEngine inicializado (modo={mode_label}, batch_size={batch_size})")
    
    def run(self, max_repos: Optional[int] = None) -> Dict[str, Any]:
        """
        Ejecuta la ingesta completa de usuarios desde campo 'collaborators'.
        
        Args:
            max_repos: Límite opcional de repositorios a procesar
            
        Returns:
            Diccionario con estadísticas del proceso
        """
        logger.info("=" * 80)
        logger.info("👥 INICIANDO INGESTA DE USUARIOS DESDE COLABORADORES")
        logger.info("=" * 80)
        mode_label = "DESDE CERO" if self.from_scratch else "INCREMENTAL"
        logger.info(f"Modo: {mode_label}")
        
        self.stats["start_time"] = datetime.now()
        
        # Limpieza (solo en modo from_scratch)
        if self.from_scratch:
            self._cleanup_collection()
        
        # 1. Extraer usuarios únicos desde campo 'collaborators'
        logger.info("\n📊 Extrayendo usuarios desde campo 'collaborators' de repositorios...")
        users_dict = self._extract_users_from_collaborators(max_repos)
        
        self.stats["users_found"] = len(users_dict)
        self.stats["unique_users"] = len(users_dict)
        logger.info(f"✅ Encontrados {len(users_dict)} usuarios únicos")
        
        if len(users_dict) == 0:
            logger.warning("⚠️  No se encontraron usuarios para ingestar")
            if self.progress_callback:
                try:
                    self.progress_callback(1, 1, "No se encontraron usuarios nuevos")
                except Exception:
                    pass
            return self.stats
        
        # 2. Obtener información completa y guardar
        logger.info(f"\n📊 Obteniendo información completa de {len(users_dict)} usuarios...")
        if self.progress_callback:
            try:
                self.progress_callback(0, len(users_dict), f"Obteniendo datos de {len(users_dict)} usuarios...")
            except Exception:
                pass
        self._fetch_and_save_users(users_dict)
        
        # 3. Finalizar
        self.stats["end_time"] = datetime.now()
        self.stats["duration_seconds"] = (self.stats["end_time"] - self.stats["start_time"]).total_seconds()
        
        logger.info("\n" + "=" * 80)
        logger.info("✅ INGESTA DE USUARIOS COMPLETADA")
        logger.info("=" * 80)
        logger.info(f"\n📊 Estadísticas:")
        logger.info(f"  • Repositorios procesados: {self.stats['repos_processed']}")
        logger.info(f"  • Usuarios únicos encontrados: {self.stats['unique_users']}")
        logger.info(f"  • Usuarios nuevos insertados: {self.stats['users_inserted']}")
        logger.info(f"  • Usuarios ya existentes: {self.stats['users_existing']}")
        logger.info(f"\nClasificación:")
        logger.info(f"  • Usuarios reales: {self.stats['real_users']} ({self.stats['real_users']/self.stats['unique_users']*100:.1f}%)")
        logger.info(f"  • Bots detectados: {self.stats['bots_detected']} ({self.stats['bots_detected']/self.stats['unique_users']*100:.1f}%)")
        logger.info(f"\n⚠️  Errores: {self.stats['total_errors']}")
        logger.info(f"Duración: {self.stats['duration_seconds']:.2f}s ({self.stats['duration_seconds']/60:.1f} minutos)")
        
        return self.stats
    
    def _cleanup_collection(self) -> None:
        """
        Limpia la colección de usuarios antes de una ingesta desde cero.
        """
        logger.info("\n🗑️  Limpieza de colección de usuarios (modo desde cero)")
        try:
            count_before = self.users_repository.count_documents()
            logger.info(f"  📊 Usuarios actuales en DB: {count_before}")
            
            if count_before > 0:
                deleted = self.users_repository.delete_many({})
                self.stats["deleted_before_ingestion"] = deleted
                logger.info(f"  🗑️  Eliminados {deleted} usuarios de la colección")
            
            logger.info("  ✅ Limpieza completada")
        except Exception as e:
            logger.error(f"  ❌ Error durante limpieza: {e}")
            raise
    
    def _extract_users_from_collaborators(self, max_repos: Optional[int] = None) -> Dict[str, Dict[str, Any]]:
        """
        Extrae usuarios únicos desde el campo 'collaborators' de repositorios.
        Deduplica por ID único de GitHub.
        
        Args:
            max_repos: Límite opcional de repositorios a procesar
            
        Returns:
            Dict con {user_id: {login, extracted_from: [repo_info]}}
        """
        users_dict = {}  # {user_id: user_stub}
        
        # Obtener repos con colaboradores
        query = {"collaborators": {"$exists": True, "$ne": []}}
        cursor = self.repos_repository.collection.find(query)
        
        if max_repos:
            cursor = cursor.limit(max_repos)
        
        repos = list(cursor)
        total_repos = len(repos)
        
        logger.info(f"📂 Procesando {total_repos} repositorios con colaboradores...")
        
        for idx, repo in enumerate(repos, 1):
            if self.cancel_event and self.cancel_event.is_set():
                break
            repo_name = repo.get("name_with_owner", repo.get("name", "unknown"))
            collaborators = repo.get("collaborators", [])
            
            if idx % 100 == 0 or idx == total_repos:
                logger.info(f"  📦 [{idx}/{total_repos}] Procesando: {repo_name} ({len(collaborators)} colaboradores)")
            
            for collab in collaborators:
                user_id = collab.get("id") or collab.get("node_id")
                login = collab.get("login")
                
                if not user_id or not login:
                    continue
                
                # Detectar si es bot (pero NO filtrar, solo marcar)
                is_bot = self._is_bot(collab)
                
                # Deduplicación por ID
                if user_id not in users_dict:
                    users_dict[user_id] = {
                        "id": user_id,
                        "login": login,
                        "is_bot": is_bot,
                        "extracted_from": []
                    }
                else:
                    # Si ya existe, actualizar is_bot si es True (una vez bot, siempre bot)
                    if is_bot:
                        users_dict[user_id]["is_bot"] = True
                
                # Añadir metadata de este repo
                source_info = {
                    "repo_id": str(repo.get("id")),
                    "repo_name": repo_name,
                    "has_commits": collab.get("has_commits", False),
                    "is_mentionable": collab.get("is_mentionable", False),
                    "contributions": collab.get("contributions", 0)
                }
                
                users_dict[user_id]["extracted_from"].append(source_info)
            
            self.stats["repos_processed"] += 1
        
        # Contar bots vs usuarios reales
        bots = sum(1 for u in users_dict.values() if u.get("is_bot", False))
        real_users = len(users_dict) - bots
        
        self.stats["bots_detected"] = bots
        self.stats["real_users"] = real_users
        
        logger.info(f"✅ Deduplicación completada: {len(users_dict)} usuarios únicos de {total_repos} repos")
        logger.info(f"   • Usuarios reales: {real_users}")
        logger.info(f"   • Bots detectados: {bots}")
        
        return users_dict
    
    def _is_bot(self, user: Dict[str, Any]) -> bool:
        """
        Detecta si un usuario es un bot.
        
        Criterios:
        - Tipo 'Bot' en GitHub
        - Login termina en '[bot]'
        - Login contiene palabras clave de bots conocidos
        
        Args:
            user: Datos del usuario
            
        Returns:
            True si es bot, False en caso contrario
        """
        login = user.get("login", "").lower()
        user_type = user.get("type", "").lower()
        
        # Tipos conocidos de bot
        if user_type == "bot":
            return True
        
        # Sufijo [bot]
        if login.endswith("[bot]"):
            return True
        
        # Patrones comunes en nombres de bots
        bot_patterns = [
            "bot",
            "dependabot",
            "renovate",
            "greenkeeper",
            "snyk",
            "codecov",
            "travis",
            "circleci",
            "github-actions",
            "automation",
            "auto-"
        ]
        
        return any(pattern in login for pattern in bot_patterns)
    
    # ==================== OPTIMIZACIÓN: QUERIES GRAPHQL BATCHED ====================
    
    # Tamaño de lote para queries GraphQL batched (25 usuarios por query)
    GRAPHQL_BATCH_SIZE = 25
    
    def _fetch_and_save_users(self, users_dict: Dict[str, Dict[str, Any]]) -> None:
        """
        Obtiene información completa de usuarios via GraphQL y los guarda en MongoDB.
        
        Optimizado con:
        - Bulk check de existencia en MongoDB (1 query en vez de N)
        - Batched GraphQL queries (25 usuarios por query en vez de 1)
        - Bulk update para usuarios existentes (pymongo bulk_write)
        - Smart rate limit check en vez de sleeps fijos
        
        Args:
            users_dict: Diccionario de usuarios {user_id: {login, extracted_from}}
        """
        users_list = list(users_dict.values())
        total = len(users_list)
        
        # 1. Bulk check: verificar qué usuarios ya existen en DB (1 query)
        logger.info("📊 Verificando usuarios existentes en DB (bulk check)...")
        all_ids = [u['id'] for u in users_list]
        existing_ids = self._get_existing_user_ids(all_ids)
        
        new_users = [u for u in users_list if u['id'] not in existing_ids]
        existing_users = [u for u in users_list if u['id'] in existing_ids]
        
        logger.info(f"  • Usuarios nuevos (requieren GraphQL): {len(new_users)}")
        logger.info(f"  • Usuarios existentes (solo actualizar metadata): {len(existing_users)}")
        
        # 2. Bulk update extracted_from para usuarios existentes (sin llamar a GitHub)
        if existing_users:
            self._bulk_update_extracted_from(existing_users)
            self.stats["users_existing"] = len(existing_users)
        
        # 3. Fetch usuarios nuevos en lotes via batched GraphQL + ThreadPoolExecutor
        if new_users:
            total_batches = (len(new_users) + self.GRAPHQL_BATCH_SIZE - 1) // self.GRAPHQL_BATCH_SIZE
            max_concurrent = 3  # Workers paralelos para batches GraphQL
            logger.info(f"🚀 Procesando {len(new_users)} usuarios nuevos con {max_concurrent} workers paralelos (batches de {self.GRAPHQL_BATCH_SIZE})")
            
            batches = []
            for i in range(0, len(new_users), self.GRAPHQL_BATCH_SIZE):
                batch = new_users[i:i + self.GRAPHQL_BATCH_SIZE]
                batch_num = i // self.GRAPHQL_BATCH_SIZE + 1
                batches.append((batch_num, batch))
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
                futures = {}
                for batch_num, batch in batches:
                    future = executor.submit(self._fetch_and_save_batch_with_retry, batch, batch_num, total_batches)
                    futures[future] = batch_num
                
                for future in concurrent.futures.as_completed(futures):
                    if self.cancel_event and self.cancel_event.is_set():
                        for f in futures:
                            f.cancel()
                        logger.warning("⚠️ Cancelación detectada en _fetch_and_save_users")
                        break
                    batch_num = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        logger.error(f"❌ Error en lote {batch_num}/{total_batches}: {e}")
                    
                    # Notificar progreso
                    if self.progress_callback:
                        try:
                            processed = self.stats.get('users_inserted', 0) + self.stats.get('total_errors', 0)
                            self.progress_callback(
                                batch_num, total_batches,
                                f"Ingesta usuarios: lote {batch_num}/{total_batches} ({self.stats.get('users_inserted', 0)} insertados)"
                            )
                        except Exception:
                            pass
    
    def _fetch_and_save_batch_with_retry(self, batch: List[Dict[str, Any]], batch_num: int, total_batches: int) -> None:
        """
        Procesa un batch de usuarios con reintentos y coordinación de rate limit.
        Diseñado para ejecución en ThreadPoolExecutor.
        """
        # Esperar si hay rate limit activo de otro hilo
        now = time.time()
        wait_remaining = self._rate_limit_until - now
        if wait_remaining > 0:
            logger.debug(f"⏳ Lote {batch_num}: esperando rate limit activo ({wait_remaining:.0f}s)...")
            time.sleep(wait_remaining)
        
        logger.info(f"\n📦 Lote GraphQL {batch_num}/{total_batches} ({len(batch)} usuarios en 1 query)")
        
        success = self._fetch_and_save_batch(batch)
        
        if not success:
            logger.warning(f"⏸️ Lote {batch_num}: Rate limit detectado. Esperando reset...")
            self._wait_for_rate_limit_reset()
            success = self._fetch_and_save_batch(batch)
            if not success:
                logger.error(f"❌ Lote {batch_num}: Rate limit persistente después de esperar reset.")
                return
        
        logger.info(f"✅ Lote {batch_num}/{total_batches} completado")
    
    def _get_existing_user_ids(self, user_ids: List[str]) -> Set[str]:
        """
        Verifica qué IDs de usuario ya existen en MongoDB (bulk check).
        
        En vez de hacer N queries individuales, hace 1 sola con $in.
        
        Args:
            user_ids: Lista de IDs a verificar
            
        Returns:
            Set de IDs que ya existen en la colección
        """
        try:
            # Procesar en chunks de 10000 para evitar queries demasiado grandes
            existing = set()
            chunk_size = 10000
            for i in range(0, len(user_ids), chunk_size):
                chunk = user_ids[i:i + chunk_size]
                cursor = self.users_repository.collection.find(
                    {"id": {"$in": chunk}},
                    {"id": 1, "_id": 0}
                )
                existing.update(doc['id'] for doc in cursor)
            return existing
        except Exception as e:
            logger.warning(f"⚠️  Error en bulk check, procesando todos como nuevos: {e}")
            return set()
    
    def _bulk_update_extracted_from(self, existing_users: List[Dict[str, Any]]) -> None:
        """
        Actualiza extracted_from para usuarios existentes en bulk (pymongo bulk_write).
        
        En vez de N update_one individuales, usa bulk_write para máximo rendimiento.
        
        Args:
            existing_users: Lista de stubs de usuarios existentes
        """
        from pymongo import UpdateOne
        
        logger.info(f"  📝 Actualizando metadata de {len(existing_users)} usuarios existentes (bulk)...")
        
        operations = []
        for user_stub in existing_users:
            operations.append(UpdateOne(
                {"id": user_stub['id']},
                {
                    "$addToSet": {"extracted_from": {"$each": user_stub['extracted_from']}},
                    "$set": {"updated_at": datetime.now().isoformat()}
                }
            ))
        
        # Ejecutar en chunks de 500
        total_updated = 0
        for i in range(0, len(operations), 500):
            chunk = operations[i:i + 500]
            result = self.users_repository.collection.bulk_write(chunk, ordered=False)
            total_updated += result.modified_count
        
        logger.info(f"  ✅ {total_updated} usuarios existentes actualizados en bulk")
    
    def _build_batch_query(self, logins: List[str]) -> tuple:
        """
        Construye una query GraphQL batched para múltiples usuarios.
        
        En vez de N queries individuales, crea 1 query con N aliases:
        query { user0: user(login: $login0) { ...fields } user1: ... }
        
        Esto reduce N requests a 1, ahorrando tokens de GitHub.
        
        Args:
            logins: Lista de logins a consultar
            
        Returns:
            Tupla (query_string, variables_dict)
        """
        variables_decl = []
        aliases = []
        variables = {}
        
        for i, login in enumerate(logins):
            var_name = f"login{i}"
            variables_decl.append(f"${var_name}: String!")
            aliases.append(f"    user{i}: user(login: ${var_name}) {{ ...UserBasicFields }}")
            variables[var_name] = login
        
        aliases_str = "\n".join(aliases)
        vars_str = ", ".join(variables_decl)
        
        query = f"""
        query GetUsersBatch({vars_str}) {{
{aliases_str}
        }}
        
        fragment UserBasicFields on User {{
            id
            login
            name
            email
            bio
            company
            location
            url
            websiteUrl
            twitterUsername
            avatarUrl
            createdAt
            updatedAt
            followers {{ totalCount }}
            following {{ totalCount }}
            repositories {{ totalCount }}
        }}
        """
        
        return query, variables
    
    def _fetch_and_save_batch(self, users_batch: List[Dict[str, Any]]) -> bool:
        """
        Obtiene información de un lote de usuarios con UNA sola query GraphQL
        y los guarda en MongoDB con insert_many.
        
        Si un usuario individual falla (cuenta eliminada), se salta sin afectar al resto.
        
        Args:
            users_batch: Lista de stubs de usuarios nuevos
            
        Returns:
            True si el batch se procesó (con o sin errores individuales),
            False si hubo rate limit (señal para abortar)
        """
        logins = [u['login'] for u in users_batch]
        login_to_stub = {u['login']: u for u in users_batch}
        
        # Construir y ejecutar query batched
        query, variables = self._build_batch_query(logins)
        
        try:
            result = self.github_client.execute_query(query, variables)
            
            if not result or 'data' not in result:
                logger.warning("⚠️  Batch query sin datos - fallback a queries individuales")
                return self._fetch_batch_individual_fallback(users_batch)
            
            data = result['data']
            docs_to_insert = []
            
            for i, login in enumerate(logins):
                if self.cancel_event and self.cancel_event.is_set():
                    break
                alias_key = f"user{i}"
                user_data = data.get(alias_key)
                
                if not user_data:
                    # Usuario no encontrado (cuenta eliminada o bot)
                    logger.debug(f"  ⚠️  {login}: no encontrado en GitHub (cuenta eliminada?)")
                    with self._stats_lock:
                        self.stats["total_errors"] += 1
                    continue
                
                stub = login_to_stub[login]
                formatted = self._format_user_data(user_data)
                
                if not formatted.get('login'):
                    logger.debug(f"  ⚠️  {login}: sin login válido en respuesta")
                    with self._stats_lock:
                        self.stats["total_errors"] += 1
                    continue
                
                # Añadir metadata de extracción
                formatted['extracted_from'] = stub['extracted_from']
                formatted['is_bot'] = stub.get('is_bot', False)
                
                # Validar con modelo Pydantic
                try:
                    user_model = User(**formatted)
                    user_dict = user_model.model_dump()
                except ValidationError:
                    user_dict = formatted
                
                # Verificar login final
                if user_dict.get('login'):
                    docs_to_insert.append(user_dict)
                else:
                    with self._stats_lock:
                        self.stats["total_errors"] += 1
            
            # Bulk insert en MongoDB
            if docs_to_insert:
                try:
                    self.users_repository.collection.insert_many(docs_to_insert, ordered=False)
                    with self._stats_lock:
                        self.stats["users_inserted"] += len(docs_to_insert)
                    logger.info(f"  ✨ {len(docs_to_insert)} usuarios insertados (batch de {len(logins)})")
                except Exception as db_err:
                    # Si hay duplicados, insertar uno a uno como fallback
                    logger.warning(f"  ⚠️  Error en insert_many, insertando individualmente: {db_err}")
                    for doc in docs_to_insert:
                        try:
                            self.users_repository.collection.insert_one(doc)
                            with self._stats_lock:
                                self.stats["users_inserted"] += 1
                        except Exception:
                            with self._stats_lock:
                                self.stats["users_existing"] += 1
            
            return True
            
        except Exception as e:
            error_str = str(e)
            if "RATE_LIMIT" in error_str or "rate limit" in error_str.lower() or "403" in error_str or "forbidden" in error_str.lower():
                logger.warning("⏸️  Rate limit/403 en batch query - Esperando reset...")
                self._wait_for_rate_limit_reset()
                return True  # Señal para que el loop reintente
            
            # Para otros errores, intentar fallback individual
            logger.warning(f"⚠️  Error en batch query ({error_str[:80]}), fallback individual...")
            return self._fetch_batch_individual_fallback(users_batch)
    
    def _fetch_batch_individual_fallback(self, users_batch: List[Dict[str, Any]]) -> bool:
        """
        Fallback: procesa usuarios uno a uno si la query batched falla.
        Garantiza que no se pierden datos.
        
        Args:
            users_batch: Lista de stubs de usuarios
            
        Returns:
            True siempre (errores individuales no abortan)
        """
        logger.info(f"  🔄 Procesando {len(users_batch)} usuarios individualmente (fallback)...")
        for user_stub in users_batch:
            try:
                self._fetch_and_save_single_user(user_stub)
            except Exception as e:
                error_str = str(e)
                if "RATE_LIMIT" in error_str or "rate limit" in error_str.lower() or "403" in error_str or "forbidden" in error_str.lower():
                    logger.warning("⏸️ Rate limit/403 en fallback individual - Esperando reset...")
                    self._wait_for_rate_limit_reset()
                    # Reintentar este usuario
                    try:
                        self._fetch_and_save_single_user(user_stub)
                    except Exception:
                        with self._stats_lock:
                            self.stats["total_errors"] += 1
                    continue
                logger.debug(f"  ⚠️  {user_stub.get('login')}: {error_str[:60]}")
                with self._stats_lock:
                    self.stats["total_errors"] += 1
        return True
    
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
            rate_info = self.github_client.get_rate_limit()
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
            rate_info = self.github_client.get_rate_limit()
            remaining = rate_info.get('remaining', 5000)
            reset_at = rate_info.get('reset_at')
            
            if reset_at:
                wait = (reset_at - datetime.now(timezone.utc)).total_seconds() + 5
                if wait > 0:
                    wait_seconds = wait
            else:
                # Consultar REST API para timestamp real
                try:
                    rest_info = self.github_client._get_rate_limit_rest()
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
    
    def _fetch_and_save_single_user(self, user_stub: Dict[str, Any]) -> None:
        """
        Obtiene información completa de un usuario y lo guarda en MongoDB.
        
        Args:
            user_stub: Datos básicos del usuario {id, login, extracted_from}
        """
        login = user_stub["login"]
        user_id = user_stub["id"]
        
        # Query SIMPLIFICADO para ingesta rápida
        # contributionsCollection y campos pesados se obtienen en enriquecimiento
        query = """
        query GetUser($login: String!) {
          user(login: $login) {
            id
            login
            name
            email
            bio
            company
            location
            url
            websiteUrl
            twitterUsername
            avatarUrl
            createdAt
            updatedAt
            followers {
              totalCount
            }
            following {
              totalCount
            }
            repositories {
              totalCount
            }
          }
        }
        """
        
        variables = {"login": login}
        
        # Verificar si ya existe en MongoDB
        existing = self.users_repository.collection.find_one({"id": user_id})
        
        if existing:
            # Usuario ya existe, solo actualizar extracted_from
            self.users_repository.collection.update_one(
                {"id": user_id},
                {
                    "$addToSet": {
                        "extracted_from": {"$each": user_stub["extracted_from"]}
                    },
                    "$set": {
                        "updated_at": datetime.now().isoformat()
                    }
                }
            )
            with self._stats_lock:
                self.stats["users_existing"] += 1
            logger.debug(f"  ↻ Usuario existente actualizado: {login}")
            return
        
        # Usuario nuevo, obtener información completa
        try:
            # Ejecutar query (graphql_client ya tiene reintentos incorporados)
            result = self.github_client.execute_query(query, variables)
            
            if not result or "data" not in result:
                logger.warning(f"⚠️  Usuario {login}: Sin datos de GraphQL")
                with self._stats_lock:
                    self.stats["total_errors"] += 1
                return
            
            user_data = result["data"].get("user")
            
            if not user_data:
                logger.warning(f"⚠️  Usuario {login}: No encontrado en GitHub (probablemente eliminado)")
                with self._stats_lock:
                    self.stats["total_errors"] += 1
                return
            
            # Formatear datos
            formatted_user = self._format_user_data(user_data)
            
            # VALIDACIÓN CRÍTICA: Verificar que el usuario tiene login válido
            if not formatted_user.get("login"):
                logger.warning(f"⚠️  Usuario con ID {user_id}: Sin campo 'login' válido en respuesta de GitHub. Saltando...")
                with self._stats_lock:
                    self.stats["total_errors"] += 1
                return
            
            # Añadir metadata de extracción
            formatted_user["extracted_from"] = user_stub["extracted_from"]
            formatted_user["is_bot"] = user_stub.get("is_bot", False)
            
            # Validar con modelo Pydantic
            try:
                user_model = User(**formatted_user)
                user_dict = user_model.model_dump()
            except ValidationError as e:
                logger.warning(f"⚠️  Usuario {login}: Error de validación: {e}")
                # Guardar sin validar
                user_dict = formatted_user
            
            # VALIDACIÓN FINAL: Verificar login antes de insertar
            if not user_dict.get("login"):
                logger.warning(f"⚠️  Usuario con ID {user_id}: login perdido después de validación. Saltando...")
                with self._stats_lock:
                    self.stats["total_errors"] += 1
                return
            
            # Insertar en MongoDB
            self.users_repository.collection.insert_one(user_dict)
            with self._stats_lock:
                self.stats["users_inserted"] += 1
            logger.debug(f"  ✨ Usuario nuevo insertado: {login}")
                
        except Exception as e:
            # Si es un error de usuario no encontrado (bot eliminado), no fallar
            if "NOT_FOUND" in str(e) or "Could not resolve" in str(e):
                logger.warning(f"⚠️  Usuario {login}: No encontrado en GitHub (cuenta eliminada o bot)")
                with self._stats_lock:
                    self.stats["total_errors"] += 1
                return
            
            # Re-lanzar para que sea capturado en el nivel superior
            raise
    
    def _format_user_data(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Formatea datos de usuario desde GraphQL (ingesta básica).
        
        Args:
            user_data: Datos crudos de GraphQL
            
        Returns:
            Datos formateados con campos básicos
            
        Note:
            Campos pesados (gists, starred, watching, contributions) se obtienen en enriquecimiento
        """
        return {
            "id": user_data.get("id"),
            "login": user_data.get("login"),
            "name": user_data.get("name"),
            "email": user_data.get("email"),
            "bio": user_data.get("bio"),
            "company": user_data.get("company"),
            "location": user_data.get("location"),
            "url": user_data.get("url"),
            "website_url": user_data.get("websiteUrl"),
            "twitter_username": user_data.get("twitterUsername"),
            "avatar_url": user_data.get("avatarUrl"),
            "created_at": user_data.get("createdAt"),
            "updated_at": user_data.get("updatedAt"),
            "followers_count": user_data.get("followers", {}).get("totalCount", 0),
            "following_count": user_data.get("following", {}).get("totalCount", 0),
            "public_repos_count": user_data.get("repositories", {}).get("totalCount", 0),
            # Campos pesados se obtienen en enriquecimiento
            "public_gists_count": None,
            "starred_repos_count": None,
            "watching_count": None,
            "total_commit_contributions": None,
            "total_issue_contributions": None,
            "total_pr_contributions": None,
            "total_pr_review_contributions": None,
            # Metadata
            "ingested_at": datetime.now().isoformat(),
            "is_enriched": False
        }


def run_user_ingestion(
    max_repos: Optional[int] = None,
    batch_size: int = 500,
    from_scratch: bool = False
) -> Dict[str, Any]:  # ✅ OPTIMIZADO
    """
    Función helper para ejecutar ingesta de usuarios desde colaboradores.
    
    Args:
        max_repos: Límite opcional de repositorios a procesar
        batch_size: Tamaño del lote
        from_scratch: Si True, limpia colección antes de ingestar
        
    Returns:
        Estadísticas del proceso
    """
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    github_token = os.getenv("GITHUB_TOKEN")
    
    # Inicializar componentes
    github_client = GitHubGraphQLClient(github_token)
    
    repos_repository = MongoRepository(
        collection_name="repositories",
        unique_fields=["id"]
    )
    
    users_repository = MongoRepository(
        collection_name="users",
        unique_fields=["id"]
    )
    
    # Ejecutar ingesta
    engine = UserIngestionEngine(
        github_client=github_client,
        repos_repository=repos_repository,
        users_repository=users_repository,
        batch_size=batch_size,
        from_scratch=from_scratch
    )
    
    return engine.run(max_repos=max_repos)
