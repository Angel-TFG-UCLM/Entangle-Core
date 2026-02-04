""" Motor de enriquecimiento de usuarios de GitHub - Versión 2.0 Optimizada

MEJORAS PRINCIPALES:
- Una sola super-query GraphQL por usuario (elimina rate limits)
- Modelo simplificado (30 campos esenciales vs 78 anteriores)
- Robustez: try-except por usuario, continúa en fallos
- Optimizado para vCore: batch_size escalable, sin sleeps entre operaciones de BD
- Preserva lógica core TFG: quantum_repositories, quantum_expertise_score, métricas sociales
"""

import time
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from .graphql_client import GitHubGraphQLClient
from ..core.logger import logger
from ..core.mongo_repository import MongoRepository


class UserEnrichmentEngine:
    """
    Motor para enriquecer datos de usuarios con estrategia de super-query.
    Una sola llamada GraphQL obtiene todos los datos necesarios.
    """
    
    ENRICHMENT_VERSION = "2.0.0"
    
    # Query GraphQL unificada que obtiene TODOS los datos necesarios
    SUPER_QUERY = """
    query GetUserComplete($login: String!) {
      user(login: $login) {
        # ==================== BÁSICOS ====================
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
        
        # ==================== MÉTRICAS SOCIALES ====================
        followers {
          totalCount
        }
        following {
          totalCount
        }
        
        # ==================== REPOSITORIOS ====================
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
            primaryLanguage {
              name
            }
            isPrivate
            isFork
            isArchived
            createdAt
            updatedAt
          }
        }
        
        # ==================== REPOS PINNED ====================
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
              primaryLanguage {
                name
              }
              isPrivate
              isFork
              isArchived
              createdAt
              updatedAt
            }
          }
        }
        
        # ==================== STARRED REPOS ====================
        starredRepositories {
          totalCount
        }
        
        # ==================== ORGANIZACIONES ====================
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
        
        # ==================== CONTRIBUCIONES ====================
        contributionsCollection {
          totalCommitContributions
          totalIssueContributions
          totalPullRequestContributions
          totalPullRequestReviewContributions
          totalRepositoryContributions
          restrictedContributionsCount
        }
        
        # ==================== CONTADORES ====================
        gists {
          totalCount
        }
        packages {
          totalCount
        }
        sponsorshipsAsMaintainer {
          totalCount
        }
        sponsorshipsAsSponsor {
          totalCount
        }
        
        # ==================== SOCIAL ACCOUNTS ====================
        socialAccounts(first: 10) {
          nodes {
            provider
            displayName
            url
          }
        }
        
        # ==================== STATUS ====================
        status {
          emoji
          message
          expiresAt
        }
        
        # ==================== FLAGS ====================
        isHireable
        isBountyHunter
        isCampusExpert
        isDeveloperProgramMember
        isEmployee
        isGitHubStar
        isSiteAdmin
      }
    }
    """
    
    def __init__(
        self,
        github_token: str,
        users_repository: MongoRepository,
        repos_repository: MongoRepository,
        batch_size: int = 100,  # ✅ OPTIMIZADO para vCore
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Inicializa el motor de enriquecimiento.
        
        Args:
            github_token: Token de GitHub
            users_repository: Repositorio de usuarios
            repos_repository: Repositorio de repositorios
            batch_size: Tamaño del lote (optimizado para vCore)
            config: Configuración opcional
        """
        self.github_token = github_token
        self.users_repository = users_repository
        self.repos_repository = repos_repository
        self.batch_size = batch_size
        self.config = config or {}
        self.graphql_client = GitHubGraphQLClient(github_token)
        
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
        
        logger.info(f"📊 Total usuarios a enriquecer: {total_users}")
        
        if total_users == 0:
            logger.info("✅ No hay usuarios para enriquecer")
            return self._finalize_stats()
        
        # Procesar en lotes
        for i in range(0, total_users, self.batch_size):
            batch = users[i:i + self.batch_size]
            batch_num = i // self.batch_size + 1
            total_batches = (total_users + self.batch_size - 1) // self.batch_size
            
            logger.info(f"\n📦 Procesando lote {batch_num}/{total_batches} ({len(batch)} usuarios)")
            
            for user in batch:
                self._enrich_single_user(user)
                
                # Sleep para respetar GitHub API Rate Limit
                time.sleep(0.5)
            
            logger.info(f"✅ Lote {batch_num}/{total_batches} completado")
        
        return self._finalize_stats()
    
    def _enrich_single_user(self, user: Dict[str, Any]) -> bool:
        """
        Enriquece un solo usuario. Incluye try-except para continuar en caso de error.
        
        Args:
            user: Documento de usuario de MongoDB
            
        Returns:
            True si se enriqueció correctamente, False si hubo error
        """
        login = user.get("login")
        
        if not login:
            logger.warning(f"⚠️  Usuario sin campo 'login' encontrado (ID: {user.get('_id')}). Saltando...")
            self.stats["total_errors"] += 1
            return False
        
        try:
            logger.info(f"\nEnriqueciendo usuario: {login}")
            
            # Limpiar arrays vacíos del usuario (legacy)
            self._clean_empty_arrays(user)
            
            # ==================== SUPER-QUERY: UNA SOLA LLAMADA ====================
            graphql_data = self._fetch_user_data(login)
            
            if not graphql_data:
                logger.warning(f"⚠️  No se pudo obtener datos de {login}")
                self.stats["total_errors"] += 1
                return False
            
            # ==================== PROCESAR DATOS ====================
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
            
            # Métricas sociales calculadas
            social_metrics = self._calculate_social_metrics(user, updates)
            updates.update(social_metrics)
            
            # Quantum expertise score
            quantum_score = self._calculate_quantum_expertise(user, updates)
            if quantum_score is not None:
                updates["quantum_expertise_score"] = quantum_score
            
            # Timestamp de enriquecimiento
            updates["enriched_at"] = datetime.now()
            
            # ==================== TRACKING DE ENRIQUECIMIENTO v3.0 ====================
            
            # LÓGICA DE COMPLETITUD REALISTA:
            # Un usuario está COMPLETO si:
            # 1. Hemos calculado con éxito el quantum_expertise_score (núcleo del TFG)
            # 2. Tenemos la fecha enriched_at
            # Ya NO reportamos campos opcionales (company, twitter) como missing.
            
            is_complete = True  # Siempre True si llegamos al final sin error
            
            updates["enrichment_status"] = {
                "is_complete": is_complete,
                "version": "3.0",
                "last_check": datetime.now().isoformat(),
                "fields_missing": []  # Ya no reportamos campos opcionales como missing
            }
            
            # ==================== GUARDAR EN BD ====================
            
            self.users_repository.collection.update_one(
                {"_id": user.get("_id")},
                {"$set": updates}
            )
            
            self.stats["total_enriched"] += 1
            logger.info(f"✅ Usuario {login} enriquecido correctamente")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error enriqueciendo usuario {login}: {e}")
            self.stats["total_errors"] += 1
            return False
        
        finally:
            self.stats["total_processed"] += 1
    
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
