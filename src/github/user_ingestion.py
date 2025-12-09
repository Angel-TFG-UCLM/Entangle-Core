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
from typing import List, Dict, Any, Optional, Set
from datetime import datetime
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
    """
    
    def __init__(
        self,
        github_client: GitHubGraphQLClient,
        repos_repository: MongoRepository,
        users_repository: MongoRepository,
        batch_size: int = 50
    ):
        """
        Inicializa el motor de ingesta de usuarios.
        
        Args:
            github_client: Cliente GraphQL de GitHub
            repos_repository: Repositorio de repositorios
            users_repository: Repositorio de usuarios
            batch_size: Tamaño del lote para procesamiento
        """
        self.github_client = github_client
        self.repos_repository = repos_repository
        self.users_repository = users_repository
        self.batch_size = batch_size
        
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
            "start_time": None,
            "end_time": None,
            "duration_seconds": 0
        }
        
        logger.info(f"UserIngestionEngine inicializado (batch_size={batch_size})")
    
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
        
        self.stats["start_time"] = datetime.now()
        
        # 1. Extraer usuarios únicos desde campo 'collaborators'
        logger.info("\n📊 Extrayendo usuarios desde campo 'collaborators' de repositorios...")
        users_dict = self._extract_users_from_collaborators(max_repos)
        
        self.stats["users_found"] = len(users_dict)
        self.stats["unique_users"] = len(users_dict)
        logger.info(f"✅ Encontrados {len(users_dict)} usuarios únicos")
        
        if len(users_dict) == 0:
            logger.warning("⚠️  No se encontraron usuarios para ingestar")
            return self.stats
        
        # 2. Obtener información completa y guardar
        logger.info(f"\n📊 Obteniendo información completa de {len(users_dict)} usuarios...")
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
    
    def _fetch_and_save_users(self, users_dict: Dict[str, Dict[str, Any]]) -> None:
        """
        Obtiene información completa de usuarios via GraphQL y los guarda en MongoDB.
        
        Args:
            users_dict: Diccionario de usuarios {user_id: {login, extracted_from}}
        """
        users_list = list(users_dict.values())
        total = len(users_list)
        
        for i in range(0, total, self.batch_size):
            batch = users_list[i:i + self.batch_size]
            batch_num = (i // self.batch_size) + 1
            total_batches = (total + self.batch_size - 1) // self.batch_size
            
            logger.info(f"\n📦 Lote {batch_num}/{total_batches} - Procesando {len(batch)} usuarios...")
            
            for idx, user_stub in enumerate(batch, 1):
                login = user_stub.get('login', 'unknown')
                
                try:
                    logger.debug(f"  [{idx}/{len(batch)}] Procesando usuario: {login}")
                    self._fetch_and_save_single_user(user_stub)
                    
                except Exception as e:
                    error_str = str(e)
                    
                    # Distinguir tipos de errores
                    if "RATE_LIMIT" in error_str or "rate limit" in error_str.lower():
                        # El error de rate limit ya fue manejado en graphql_client con espera
                        # Si llegamos aquí, significa que se agotaron los reintentos
                        logger.error(f"❌ Usuario {login}: Rate limit persistente después de esperar - Abortando lote")
                        self.stats["total_errors"] += 1
                        # Detener el procesamiento del lote actual para no seguir golpeando la API
                        logger.warning("⏸️ Pausando procesamiento por rate limit. Continuar en próxima ejecución.")
                        return  # Salir del método completamente
                    elif "NOT_FOUND" in error_str or "Could not resolve" in error_str:
                        logger.warning(f"⚠️  Usuario {login}: Cuenta eliminada o no existe")
                    elif "timeout" in error_str.lower() or "Timeout" in error_str:
                        logger.warning(f"⚠️  Usuario {login}: Timeout después de 5 reintentos - Saltando y continuando")
                    elif any(code in error_str for code in ["408", "502", "503", "504"]):
                        logger.warning(f"⚠️  Usuario {login}: Error de servidor GitHub ({error_str[:50]}) - Saltando y continuando")
                    elif "Connection" in error_str:
                        logger.warning(f"⚠️  Usuario {login}: Error de conexión - Saltando y continuando")
                    else:
                        logger.error(f"❌ Usuario {login}: Error inesperado: {e}")
                    
                    self.stats["total_errors"] += 1
                    continue  # Continuar con siguiente usuario
            
            # Pausa entre lotes (más larga para prevenir rate limit)
            if i + self.batch_size < total:
                logger.debug("⏸️ Pausa de 2 segundos entre lotes para prevenir rate limit...")
                time.sleep(2)
    
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
            self.stats["users_existing"] += 1
            logger.debug(f"  ↻ Usuario existente actualizado: {login}")
            return
        
        # Usuario nuevo, obtener información completa
        try:
            # Ejecutar query (graphql_client ya tiene reintentos incorporados)
            result = self.github_client.execute_query(query, variables)
            
            if not result or "data" not in result:
                logger.warning(f"⚠️  Usuario {login}: Sin datos de GraphQL")
                self.stats["total_errors"] += 1
                return
            
            user_data = result["data"].get("user")
            
            if not user_data:
                logger.warning(f"⚠️  Usuario {login}: No encontrado en GitHub (probablemente eliminado)")
                self.stats["total_errors"] += 1
                return
            
            # Formatear datos
            formatted_user = self._format_user_data(user_data)
            
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
            
            # Insertar en MongoDB
            self.users_repository.collection.insert_one(user_dict)
            self.stats["users_inserted"] += 1
            logger.debug(f"  ✨ Usuario nuevo insertado: {login}")
                
        except Exception as e:
            # Si es un error de usuario no encontrado (bot eliminado), no fallar
            if "NOT_FOUND" in str(e) or "Could not resolve" in str(e):
                logger.warning(f"⚠️  Usuario {login}: No encontrado en GitHub (cuenta eliminada o bot)")
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


def run_user_ingestion(max_repos: Optional[int] = None, batch_size: int = 50) -> Dict[str, Any]:
    """
    Función helper para ejecutar ingesta de usuarios desde colaboradores.
    
    Args:
        max_repos: Límite opcional de repositorios a procesar
        batch_size: Tamaño del lote
        
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
        batch_size=batch_size
    )
    
    return engine.run(max_repos=max_repos)
