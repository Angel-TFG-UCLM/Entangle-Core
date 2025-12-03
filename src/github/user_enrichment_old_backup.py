"""
Motor de enriquecimiento de usuarios de GitHub.

Completa información faltante usando GraphQL y REST API:
- Repositorios destacados (pinned)
- Contribuciones mensuales
- Organizaciones
- Proyectos
- Packages
- Sponsors
- Campos específicos para Quantum Computing
"""

import time
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime

from .graphql_client import GitHubGraphQLClient
from ..core.logger import logger
from ..core.mongo_repository import MongoRepository


class UserEnrichmentEngine:
    """
    Motor para enriquecer datos de usuarios ya ingestados.
    Completa campos faltantes usando múltiples fuentes.
    """
    
    ENRICHMENT_VERSION = "2.0.0"  # Versión del esquema de enriquecimiento
    
    def __init__(
        self,
        github_token: str,
        users_repository: MongoRepository,
        repos_repository: MongoRepository,
        batch_size: int = 10,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Inicializa el motor de enriquecimiento.
        
        Args:
            github_token: Token de GitHub
            users_repository: Repositorio de usuarios
            repos_repository: Repositorio de repositorios
            batch_size: Tamaño del lote
            config: Configuración opcional
        """
        self.github_token = github_token
        self.users_repository = users_repository
        self.repos_repository = repos_repository
        self.batch_size = batch_size
        self.config = config or {}
        self.graphql_client = GitHubGraphQLClient(github_token)
        
        # Headers para REST API
        self.rest_headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        
        # Estadísticas
        self.stats = {
            "total_processed": 0,
            "total_enriched": 0,
            "total_errors": 0,
            "fields_enriched": {},
            "start_time": None,
            "end_time": None
        }
        
        logger.info(f"🚀 UserEnrichmentEngine inicializado (batch_size={batch_size})")
    
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
        logger.info("👥 INICIANDO ENRIQUECIMIENTO DE USUARIOS")
        logger.info("=" * 80)
        
        self.stats["start_time"] = datetime.now()
        
        # Obtener usuarios de MongoDB
        if force_reenrich:
            query = {}  # Todos los usuarios
            logger.info("📌 Modo force_reenrich: procesando todos los usuarios")
        else:
            # Re-enriquecer si:
            # 1. No tiene enrichment_status
            # 2. No está completo (is_complete = false)
            # 3. Más de 7 días desde la última actualización
            from datetime import timedelta
            seven_days_ago = datetime.now() - timedelta(days=7)
            
            query = {
                "$or": [
                    {"enrichment_status": {"$exists": False}},
                    {"enrichment_status.is_complete": False},
                    {"enrichment_status.last_enriched": {"$lt": seven_days_ago.isoformat()}},
                    {"enrichment_status.last_enriched": {"$exists": False}}
                ]
            }
            logger.info("📋 Procesando: sin enriquecer, incompletos o >7 días sin actualizar")
        
        users = list(self.users_repository.collection.find(query).limit(max_users or 0))
        total_users = len(users)
        
        logger.info(f"📊 Usuarios a enriquecer: {total_users}")
        
        if total_users == 0:
            logger.warning("⚠️  No hay usuarios para enriquecer")
            return self.stats
        
        # Procesar en lotes
        for i in range(0, total_users, self.batch_size):
            batch = users[i:i + self.batch_size]
            batch_num = (i // self.batch_size) + 1
            total_batches = (total_users + self.batch_size - 1) // self.batch_size
            
            logger.info(f"\n📦 Lote {batch_num}/{total_batches} - Procesando {len(batch)} usuarios...")
            
            for user in batch:
                login = user.get('login', 'unknown')
                try:
                    self._enrich_user(user)
                    self.stats["total_enriched"] += 1
                except Exception as e:
                    error_str = str(e)
                    
                    # Detectar y manejar rate limit de forma crítica
                    if "RATE_LIMIT" in error_str or "rate limit" in error_str.lower():
                        logger.error(f"❌ Usuario {login}: Rate limit persistente después de esperar - Abortando lote")
                        self.stats["total_errors"] += 1
                        logger.warning("⏸️ Pausando procesamiento por rate limit. Continuar en próxima ejecución.")
                        # Detener completamente el procesamiento del lote
                        return self.stats
                    elif "NOT_FOUND" in error_str or "Could not resolve" in error_str:
                        logger.warning(f"⚠️ Usuario {login}: Cuenta eliminada o no existe")
                    elif "timeout" in error_str.lower() or "Timeout" in error_str:
                        logger.warning(f"⚠️ Usuario {login}: Timeout - Saltando y continuando")
                    elif any(code in error_str for code in ["408", "502", "503", "504"]):
                        logger.warning(f"⚠️ Usuario {login}: Error de servidor GitHub - Saltando y continuando")
                    elif "Connection" in error_str:
                        logger.warning(f"⚠️ Usuario {login}: Error de conexión - Saltando y continuando")
                    else:
                        logger.error(f"❌ Usuario {login}: Error inesperado: {e}")
                    
                    self.stats["total_errors"] += 1
                
                self.stats["total_processed"] += 1
            
            # Pausa entre lotes (más larga para prevenir rate limit)
            if i + self.batch_size < total_users:
                logger.debug("⏸️ Pausa de 2 segundos entre lotes para prevenir rate limit...")
                time.sleep(2)
        
        self.stats["end_time"] = datetime.now()
        duration = (self.stats["end_time"] - self.stats["start_time"]).total_seconds()
        
        # Calcular estadísticas de enrichment_status
        complete_count = self.users_repository.collection.count_documents({
            "enrichment_status.is_complete": True
        })
        incomplete_count = self.users_repository.collection.count_documents({
            "enrichment_status.is_complete": False
        })
        
        logger.info("\n" + "=" * 80)
        logger.info("✅ ENRIQUECIMIENTO DE USUARIOS COMPLETADO")
        logger.info("=" * 80)
        logger.info(f"\n📊 Estadísticas del Proceso:")
        logger.info(f"  • Usuarios procesados: {self.stats['total_processed']}")
        logger.info(f"  • Usuarios enriquecidos: {self.stats['total_enriched']}")
        logger.info(f"  • Errores: {self.stats['total_errors']}")
        logger.info(f"  • Duración: {duration:.2f}s ({duration/60:.1f} minutos)")
        
        logger.info(f"\n📊 Estado del Dataset:")
        logger.info(f"  • Completamente enriquecidos: {complete_count}")
        logger.info(f"  • Con campos faltantes: {incomplete_count}")
        
        if complete_count + incomplete_count > 0:
            completeness = (complete_count / (complete_count + incomplete_count)) * 100
            logger.info(f"  • Completitud: {completeness:.1f}%")
        
        if self.stats['fields_enriched']:
            logger.info(f"\n📋 Top 10 campos enriquecidos:")
            sorted_fields = sorted(self.stats['fields_enriched'].items(), key=lambda x: x[1], reverse=True)
            for field, count in sorted_fields[:10]:
                logger.info(f"  • {field}: {count} usuarios")
        
        return self.stats
    
    def _enrich_user(self, user: Dict[str, Any]) -> None:
        """
        Enriquece un usuario individual.
        
        Args:
            user: Documento del usuario de MongoDB
        """
        login = user.get("login")
        
        if not login:
            logger.warning(f"⚠️  Usuario sin login: {user.get('id')}")
            return
        
        logger.debug(f"🔍 Enriqueciendo usuario: {login}")
        
        updates = {}
        fields_enriched = []
        fields_missing = []
        
        # Limpiar arrays vacíos innecesarios de la ingesta
        empty_arrays_to_clean = [
            "repositories", "starred_repositories", "organizations", 
            "gists", "contributions_by_repository", "social_accounts"
        ]
        for field in empty_arrays_to_clean:
            if isinstance(user.get(field), list) and len(user.get(field, [])) == 0:
                updates[field] = None  # Convertir array vacío a None
        
        # 0. Campos básicos faltantes de ingesta (si son None o no existen)
        basic_fields = ['public_gists_count', 'starred_repos_count', 'watching_count',
                       'total_commit_contributions', 'total_issue_contributions',
                       'total_pr_contributions', 'total_pr_review_contributions']
        
        basic_fields_missing = any(
            user.get(field) is None for field in basic_fields
        )
        
        if basic_fields_missing:
            basic_data = self._fetch_basic_fields(login)
            if basic_data:
                # Solo actualizar los que son None
                for key, value in basic_data.items():
                    if user.get(key) is None:
                        updates[key] = value
                        fields_enriched.append(key)
                self._increment_field_stat("basic_fields_completed")
            else:
                # Si no pudimos obtener datos básicos, marcar como faltantes
                fields_missing.extend([f for f in basic_fields if user.get(f) is None])
        
        # 1. Repositorios destacados (pinned)
        if not user.get("pinned_repositories"):
            pinned = self._fetch_pinned_repositories(login)
            if pinned:
                updates["pinned_repositories"] = pinned
                fields_enriched.append("pinned_repositories")
                self._increment_field_stat("pinned_repositories")
        
        # 2. Organizaciones
        if not user.get("organizations"):
            orgs = self._fetch_organizations(login)
            if orgs:
                updates["organizations"] = orgs
                updates["organizations_count"] = len(orgs)
                fields_enriched.extend(["organizations", "organizations_count"])
                self._increment_field_stat("organizations")
        
        # 3. Repositorios relacionados con Quantum
        quantum_repos = self._find_quantum_repositories(login, user)
        if quantum_repos:
            updates["quantum_repositories"] = quantum_repos
            updates["is_quantum_contributor"] = True
            fields_enriched.extend(["quantum_repositories", "is_quantum_contributor"])
            self._increment_field_stat("quantum_repositories")
        
        # 4. Top lenguajes de programación
        if not user.get("top_languages"):
            languages = self._fetch_top_languages(login)
            if languages:
                updates["top_languages"] = languages
                fields_enriched.append("top_languages")
                self._increment_field_stat("top_languages")
        
        # 5. Actividad reciente
        activity = self._fetch_recent_activity(login)
        if activity:
            updates.update(activity)
            fields_enriched.extend(activity.keys())
        
        # 6. Social metrics
        social = self._calculate_social_metrics(user, updates)
        if social:
            updates.update(social)
            fields_enriched.extend(social.keys())
        
        # 7. Quantum expertise score
        quantum_score = self._calculate_quantum_expertise(user, updates)
        if quantum_score:
            updates["quantum_expertise_score"] = quantum_score
            fields_enriched.append("quantum_expertise_score")
            self._increment_field_stat("quantum_expertise_score")
        
        # 8. Campos sociales adicionales (pronouns, twitter, status, flags)
        if not user.get("social_profile_enriched"):
            social_profile = self._fetch_social_profile(login)
            if social_profile:
                updates.update(social_profile)
                updates["social_profile_enriched"] = True
                fields_enriched.extend(social_profile.keys())
                self._increment_field_stat("social_profile")
        
        # 9. Sponsors (patrocinadores)
        if not user.get("sponsors"):
            sponsors = self._fetch_sponsors(login)
            if sponsors is not None:  # Puede ser 0
                updates["sponsors_count"] = sponsors.get("total_count", 0)
                updates["sponsors"] = sponsors.get("sponsors", [])
                fields_enriched.extend(["sponsors_count", "sponsors"])
                self._increment_field_stat("sponsors")
        
        # 10. Gists destacados (quantum-related)
        if not user.get("quantum_gists"):
            quantum_gists = self._fetch_quantum_gists(login)
            if quantum_gists:
                updates["quantum_gists"] = quantum_gists
                updates["quantum_gists_count"] = len(quantum_gists)
                fields_enriched.extend(["quantum_gists", "quantum_gists_count"])
                self._increment_field_stat("quantum_gists")
        
        # 11. Lenguajes detallados (con bytes de código)
        if not user.get("languages_detailed"):
            languages_detailed = self._fetch_languages_detailed(login)
            if languages_detailed:
                updates["languages_detailed"] = languages_detailed
                fields_enriched.append("languages_detailed")
                self._increment_field_stat("languages_detailed")
        
        # 12. Contribuciones por repositorio (top repos)
        if not user.get("top_contributed_repos"):
            contrib_repos = self._fetch_contribution_repositories(login)
            if contrib_repos:
                updates["top_contributed_repos"] = contrib_repos
                fields_enriched.append("top_contributed_repos")
                self._increment_field_stat("top_contributed_repos")
        
        # 13. Issues y PRs destacados
        if not user.get("notable_issues_prs"):
            notable = self._fetch_notable_issues_prs(login)
            if notable:
                updates["notable_issues_prs"] = notable
                fields_enriched.append("notable_issues_prs")
                self._increment_field_stat("notable_issues_prs")
        
        # 14. Paquetes publicados
        if not user.get("packages"):
            packages = self._fetch_packages(login)
            if packages:
                updates["packages"] = packages
                updates["packages_count"] = len(packages)
                fields_enriched.extend(["packages", "packages_count"])
                self._increment_field_stat("packages")
        
        # 15. Proyectos personales
        if not user.get("projects"):
            projects = self._fetch_projects(login)
            if projects:
                updates["projects"] = projects
                updates["projects_count"] = len(projects)
                fields_enriched.extend(["projects", "projects_count"])
                self._increment_field_stat("projects")
        
        # 16. Red social (followers/following samples - no completos para evitar sobrecarga)
        if not user.get("social_network_sample"):
            social_network = self._fetch_social_network_sample(login)
            if social_network:
                updates["social_network_sample"] = social_network
                fields_enriched.append("social_network_sample")
                self._increment_field_stat("social_network_sample")
        
        # 17. Referencias a repositorios en tu colección
        repo_references = self._build_repository_references(login)
        if repo_references:
            updates["repository_references"] = repo_references
            fields_enriched.append("repository_references")
        
        # Identificar campos opcionales faltantes (que no se pudieron obtener)
        expected_optional_fields = [
            "pinned_repositories", "organizations", "quantum_repositories",
            "top_languages", "social_profile_enriched", "sponsors",
            "quantum_gists", "languages_detailed", "top_contributed_repos",
            "notable_issues_prs", "packages", "projects", "social_network_sample"
        ]
        
        for field in expected_optional_fields:
            # Si intentamos enriquecerlo pero no está en updates ni en user, está faltante
            if field not in fields_enriched and not user.get(field) and field not in updates:
                fields_missing.append(field)
        
        # Agregar enrichment_status (igual que repos)
        is_complete = len(fields_missing) == 0
        updates["enrichment_status"] = {
            "is_complete": is_complete,
            "last_enriched": datetime.now().isoformat(),
            "fields_enriched": list(set(fields_enriched)),
            "fields_missing": list(set(fields_missing)),
            "total_fields_enriched": len(set(fields_enriched))
        }
        
        # Actualizar en MongoDB
        if updates:
            self.users_repository.collection.update_one(
                {"id": user["id"]},
                {"$set": updates}
            )
            
            status_icon = "✅" if is_complete else "⚠️"
            logger.debug(f"{status_icon} {login}: {len(set(fields_enriched))} campos enriquecidos")
            
            if fields_missing and len(fields_missing) <= 3:
                logger.debug(f"  ⚠️ Faltantes: {', '.join(fields_missing)}")
        else:
            logger.debug(f"ℹ️  {login}: Sin cambios necesarios")
    
    def _fetch_basic_fields(self, login: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene campos básicos que faltaron en la ingesta simplificada.
        
        Campos obtenidos:
        - gists count
        - starred repos count
        - watching count
        - contributions (commits, issues, PRs, reviews)
        """
        query = """
        query GetBasicFields($login: String!) {
          user(login: $login) {
            gists {
              totalCount
            }
            starredRepositories {
              totalCount
            }
            watching {
              totalCount
            }
            contributionsCollection {
              totalCommitContributions
              totalIssueContributions
              totalPullRequestContributions
              totalPullRequestReviewContributions
            }
          }
        }
        """
        
        try:
            variables = {"login": login}
            result = self.graphql_client.execute_query(query, variables)
            
            user_data = result.get("data", {}).get("user", {})
            
            if not user_data:
                logger.warning(f"⚠️  Usuario {login}: No se encontró en GitHub")
                return None
            
            contributions = user_data.get("contributionsCollection", {})
            
            return {
                "public_gists_count": user_data.get("gists", {}).get("totalCount", 0),
                "starred_repos_count": user_data.get("starredRepositories", {}).get("totalCount", 0),
                "watching_count": user_data.get("watching", {}).get("totalCount", 0),
                "total_commit_contributions": contributions.get("totalCommitContributions", 0),
                "total_issue_contributions": contributions.get("totalIssueContributions", 0),
                "total_pr_contributions": contributions.get("totalPullRequestContributions", 0),
                "total_pr_review_contributions": contributions.get("totalPullRequestReviewContributions", 0)
            }
            
        except Exception as e:
            error_str = str(e)
            
            # Clasificar tipos de error - RATE_LIMIT se propaga para abortar
            if "RATE_LIMIT" in error_str or "rate limit" in error_str.lower():
                logger.error(f"❌ Rate limit alcanzado en campos básicos de {login}")
                raise  # Propagar para que el bucle principal lo detecte
            elif "NOT_FOUND" in error_str or "Could not resolve" in error_str:
                logger.warning(f"⚠️  Usuario {login}: Cuenta eliminada o no existe")
            elif "timeout" in error_str.lower() or "Timeout" in error_str:
                logger.warning(f"⚠️  Usuario {login}: Timeout obteniendo campos básicos - Se reintentará después")
            elif any(code in error_str for code in ["408", "502", "503", "504"]):
                logger.warning(f"⚠️  Usuario {login}: Error de servidor GitHub - Se reintentará después")
            else:
                logger.error(f"❌ Error obteniendo campos básicos de {login}: {e}")
            
            return None
    
    def _fetch_pinned_repositories(self, login: str) -> Optional[List[Dict[str, Any]]]:
        """Obtiene repositorios destacados del usuario."""
        query = """
        query GetPinnedRepos($login: String!) {
          user(login: $login) {
            pinnedItems(first: 6, types: REPOSITORY) {
              nodes {
                ... on Repository {
                  id
                  name
                  nameWithOwner
                  description
                  stargazerCount
                  primaryLanguage {
                    name
                  }
                }
              }
            }
          }
        }
        """
        
        try:
            variables = {"login": login}
            result = self.graphql_client.execute_query(query, variables)
            
            user_data = result.get("data", {}).get("user", {})
            pinned_items = user_data.get("pinnedItems", {}).get("nodes", [])
            
            if not pinned_items:
                return None
            
            formatted = []
            for repo in pinned_items:
                if repo:
                    formatted.append({
                        "id": repo.get("id"),
                        "name": repo.get("name"),
                        "name_with_owner": repo.get("nameWithOwner"),
                        "description": repo.get("description"),
                        "stars": repo.get("stargazerCount", 0),
                        "language": repo.get("primaryLanguage", {}).get("name") if repo.get("primaryLanguage") else None
                    })
            
            return formatted if formatted else None
            
        except Exception as e:
            error_str = str(e)
            if "RATE_LIMIT" in error_str or "rate limit" in error_str.lower():
                logger.error(f"❌ Rate limit alcanzado en pinned repos de {login}")
                raise
            logger.error(f"❌ Error obteniendo pinned repos de {login}: {e}")
            return None
    
    def _fetch_organizations(self, login: str) -> Optional[List[Dict[str, Any]]]:
        """Obtiene organizaciones del usuario."""
        query = """
        query GetUserOrgs($login: String!) {
          user(login: $login) {
            organizations(first: 20) {
              nodes {
                id
                login
                name
                description
                avatarUrl
                websiteUrl
                location
              }
            }
          }
        }
        """
        
        try:
            variables = {"login": login}
            result = self.graphql_client.execute_query(query, variables)
            
            user_data = result.get("data", {}).get("user", {})
            orgs = user_data.get("organizations", {}).get("nodes", [])
            
            if not orgs:
                return None
            
            formatted = []
            for org in orgs:
                if org:
                    formatted.append({
                        "id": org.get("id"),
                        "login": org.get("login"),
                        "name": org.get("name"),
                        "description": org.get("description"),
                        "avatar_url": org.get("avatarUrl"),
                        "website_url": org.get("websiteUrl"),
                        "location": org.get("location")
                    })
            
            return formatted if formatted else None
            
        except Exception as e:
            error_str = str(e)
            if "RATE_LIMIT" in error_str or "rate limit" in error_str.lower():
                logger.error(f"❌ Rate limit alcanzado en organizaciones de {login}")
                raise
            logger.error(f"❌ Error obteniendo organizaciones de {login}: {e}")
            return None
    
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
                
                quantum_repos.append({
                    "id": repo_id,
                    "name": repo.get("name"),
                    "name_with_owner": repo.get("name_with_owner"),
                    "stars": repo.get("stargazer_count", 0),
                    "role": role,
                    "contributions": contributions,
                    "primary_language": repo.get("primary_language", {}).get("name") if repo.get("primary_language") else None
                })
            
            return quantum_repos if quantum_repos else None
            
        except Exception as e:
            logger.error(f"❌ Error buscando quantum repos de {login}: {e}")
            return None
    
    def _fetch_top_languages(self, login: str) -> Optional[List[Dict[str, Any]]]:
        """Obtiene los lenguajes más usados por el usuario."""
        # TODO: Implementar agregación desde repos del usuario
        # Por ahora, retornar None para segunda fase
        return None
    
    def _fetch_recent_activity(self, login: str) -> Dict[str, Any]:
        """Obtiene métricas de actividad reciente."""
        updates = {}
        
        # Últimos 30 días de actividad
        query = """
        query GetRecentActivity($login: String!) {
          user(login: $login) {
            contributionsCollection(from: "2025-10-19T00:00:00Z") {
              totalCommitContributions
              totalIssueContributions
              totalPullRequestContributions
              totalPullRequestReviewContributions
            }
          }
        }
        """
        
        try:
            variables = {"login": login}
            result = self.graphql_client.execute_query(query, variables)
            
            user_data = result.get("data", {}).get("user", {})
            contrib = user_data.get("contributionsCollection", {})
            
            if contrib:
                updates["recent_commits_30d"] = contrib.get("totalCommitContributions", 0)
                updates["recent_issues_30d"] = contrib.get("totalIssueContributions", 0)
                updates["recent_prs_30d"] = contrib.get("totalPullRequestContributions", 0)
                updates["recent_reviews_30d"] = contrib.get("totalPullRequestReviewContributions", 0)
            
        except Exception as e:
            logger.error(f"❌ Error obteniendo actividad de {login}: {e}")
        
        return updates
    
    def _calculate_social_metrics(self, user: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
        """Calcula métricas sociales del usuario."""
        metrics = {}
        
        # Ratio followers/following
        followers = user.get("followers_count") or 0
        following = user.get("following_count") or 0
        
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
    def _fetch_social_profile(self, login: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene campos sociales adicionales del perfil.
        
        Campos: pronouns, twitterUsername, status, isHireable, isCampusExpert,
                isDeveloperProgramMember, isSiteAdmin
        """
        query = """
        query GetSocialProfile($login: String!) {
          user(login: $login) {
            pronouns
            twitterUsername
            status {
              message
              emoji
            }
            isHireable
            isCampusExpert
            isDeveloperProgramMember
            isSiteAdmin
          }
        }
        """
        
        try:
            variables = {"login": login}
            result = self.graphql_client.execute_query(query, variables)
            user_data = result.get("data", {}).get("user", {})
            
            if not user_data:
                return None
            
            status = user_data.get("status")
            return {
                "pronouns": user_data.get("pronouns"),
                "twitter_username": user_data.get("twitterUsername"),
                "status_message": status.get("message") if status else None,
                "status_emoji": status.get("emoji") if status else None,
                "is_hireable": user_data.get("isHireable", False),
                "is_campus_expert": user_data.get("isCampusExpert", False),
                "is_developer_program_member": user_data.get("isDeveloperProgramMember", False),
                "is_site_admin": user_data.get("isSiteAdmin", False)
            }
        except Exception as e:
            error_str = str(e)
            if "RATE_LIMIT" in error_str or "rate limit" in error_str.lower():
                logger.error(f"❌ Rate limit alcanzado en perfil social de {login}")
                raise
            logger.debug(f"⚠️ Error obteniendo perfil social de {login}: {e}")
            return None
    
    def _fetch_sponsors(self, login: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene información de sponsors (patrocinadores) del usuario.
        """
        query = """
        query GetSponsors($login: String!) {
          user(login: $login) {
            sponsors(first: 10) {
              totalCount
              nodes {
                ... on User {
                  login
                  name
                  avatarUrl
                }
                ... on Organization {
                  login
                  name
                  avatarUrl
                }
              }
            }
          }
        }
        """
        
        try:
            variables = {"login": login}
            result = self.graphql_client.execute_query(query, variables)
            user_data = result.get("data", {}).get("user", {})
            
            if not user_data:
                return None
            
            sponsors_data = user_data.get("sponsors", {})
            sponsors_list = []
            
            for sponsor in sponsors_data.get("nodes", []):
                if sponsor:
                    sponsors_list.append({
                        "login": sponsor.get("login"),
                        "name": sponsor.get("name"),
                        "avatar_url": sponsor.get("avatarUrl")
                    })
            
            return {
                "total_count": sponsors_data.get("totalCount", 0),
                "sponsors": sponsors_list
            }
        except Exception as e:
            error_str = str(e)
            if "RATE_LIMIT" in error_str or "rate limit" in error_str.lower():
                logger.error(f"❌ Rate limit alcanzado en sponsors de {login}")
                raise
            logger.debug(f"⚠️ Error obteniendo sponsors de {login}: {e}")
            return None
    
    def _fetch_quantum_gists(self, login: str) -> Optional[List[Dict[str, Any]]]:
        """
        Obtiene gists relacionados con quantum computing.
        Busca keywords: quantum, qiskit, cirq, pennylane, qubit, etc.
        """
        query = """
        query GetGists($login: String!) {
          user(login: $login) {
            gists(first: 50, orderBy: {field: UPDATED_AT, direction: DESC}) {
              nodes {
                name
                description
                url
                stargazerCount
                updatedAt
                files {
                  name
                }
              }
            }
          }
        }
        """
        
        try:
            variables = {"login": login}
            result = self.graphql_client.execute_query(query, variables)
            user_data = result.get("data", {}).get("user", {})
            
            if not user_data:
                return None
            
            gists = user_data.get("gists", {}).get("nodes", [])
            
            # Keywords quantum
            quantum_keywords = ['quantum', 'qiskit', 'cirq', 'pennylane', 'qubit', 'qasm', 
                               'variational', 'vqe', 'qaoa', 'grover', 'shor', 'bloch']
            
            quantum_gists = []
            for gist in gists:
                if not gist:
                    continue
                
                description = (gist.get("description") or "").lower()
                name = (gist.get("name") or "").lower()
                files = [f.get("name", "").lower() for f in gist.get("files", [])]
                
                # Verificar si contiene keywords quantum
                if any(kw in description or kw in name or any(kw in f for f in files) for kw in quantum_keywords):
                    quantum_gists.append({
                        "name": gist.get("name"),
                        "description": gist.get("description"),
                        "url": gist.get("url"),
                        "stars": gist.get("stargazerCount", 0),
                        "updated_at": gist.get("updatedAt"),
                        "files_count": len(gist.get("files", []))
                    })
            
            return quantum_gists if quantum_gists else None
        except Exception as e:
            error_str = str(e)
            if "RATE_LIMIT" in error_str or "rate limit" in error_str.lower():
                logger.error(f"❌ Rate limit alcanzado en gists de {login}")
                raise
            logger.debug(f"⚠️ Error obteniendo gists de {login}: {e}")
            return None
    
    def _fetch_languages_detailed(self, login: str) -> Optional[List[Dict[str, Any]]]:
        """
        Obtiene lenguajes con bytes de código en cada uno.
        Agrega desde los primeros 100 repos del usuario.
        """
        query = """
        query GetLanguagesDetailed($login: String!) {
          user(login: $login) {
            repositories(first: 100, orderBy: {field: STARGAZERS, direction: DESC}) {
              nodes {
                languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
                  edges {
                    size
                    node {
                      name
                      color
                    }
                  }
                }
              }
            }
          }
        }
        """
        
        try:
            variables = {"login": login}
            result = self.graphql_client.execute_query(query, variables)
            user_data = result.get("data", {}).get("user", {})
            
            if not user_data:
                return None
            
            repos = user_data.get("repositories", {}).get("nodes", [])
            
            # Agregar bytes por lenguaje
            language_stats = {}
            for repo in repos:
                if not repo:
                    continue
                
                langs = repo.get("languages", {}).get("edges", [])
                for lang_edge in langs:
                    size = lang_edge.get("size", 0)
                    lang_node = lang_edge.get("node", {})
                    lang_name = lang_node.get("name")
                    
                    if lang_name:
                        if lang_name not in language_stats:
                            language_stats[lang_name] = {
                                "name": lang_name,
                                "color": lang_node.get("color"),
                                "bytes": 0,
                                "repos_count": 0
                            }
                        
                        language_stats[lang_name]["bytes"] += size
                        language_stats[lang_name]["repos_count"] += 1
            
            # Ordenar por bytes
            sorted_langs = sorted(language_stats.values(), key=lambda x: x["bytes"], reverse=True)
            
            return sorted_langs[:15] if sorted_langs else None
        except Exception as e:
            error_str = str(e)
            if "RATE_LIMIT" in error_str or "rate limit" in error_str.lower():
                logger.error(f"❌ Rate limit alcanzado en lenguajes detallados de {login}")
                raise
            logger.debug(f"⚠️ Error obteniendo lenguajes detallados de {login}: {e}")
            return None
    
    def _fetch_contribution_repositories(self, login: str) -> Optional[List[Dict[str, Any]]]:
        """
        Obtiene repositorios donde el usuario ha contribuido más.
        """
        query = """
        query GetContribRepos($login: String!) {
          user(login: $login) {
            contributionsCollection {
              commitContributionsByRepository(maxRepositories: 20) {
                repository {
                  id
                  nameWithOwner
                  description
                  stargazerCount
                  primaryLanguage {
                    name
                  }
                }
                contributions {
                  totalCount
                }
              }
            }
          }
        }
        """
        
        try:
            variables = {"login": login}
            result = self.graphql_client.execute_query(query, variables)
            user_data = result.get("data", {}).get("user", {})
            
            if not user_data:
                return None
            
            contrib_data = user_data.get("contributionsCollection", {}).get("commitContributionsByRepository", [])
            
            formatted = []
            for item in contrib_data:
                repo = item.get("repository", {})
                contributions = item.get("contributions", {})
                
                if repo:
                    formatted.append({
                        "id": repo.get("id"),
                        "name_with_owner": repo.get("nameWithOwner"),
                        "description": repo.get("description"),
                        "stars": repo.get("stargazerCount", 0),
                        "language": repo.get("primaryLanguage", {}).get("name") if repo.get("primaryLanguage") else None,
                        "commits_count": contributions.get("totalCount", 0)
                    })
            
            return formatted if formatted else None
        except Exception as e:
            error_str = str(e)
            if "RATE_LIMIT" in error_str or "rate limit" in error_str.lower():
                logger.error(f"❌ Rate limit alcanzado en repos de contribución de {login}")
                raise
            logger.debug(f"⚠️ Error obteniendo repos de contribución de {login}: {e}")
            return None
    
    def _fetch_notable_issues_prs(self, login: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene issues y PRs más destacados del usuario.
        """
        query = """
        query GetNotableIssuesPRs($login: String!) {
          user(login: $login) {
            issues(first: 10, orderBy: {field: COMMENTS, direction: DESC}, states: [OPEN, CLOSED]) {
              nodes {
                title
                state
                url
                createdAt
                comments {
                  totalCount
                }
                repository {
                  nameWithOwner
                }
              }
            }
            pullRequests(first: 10, orderBy: {field: CREATED_AT, direction: DESC}, states: [MERGED, OPEN]) {
              nodes {
                title
                state
                url
                createdAt
                merged
                comments {
                  totalCount
                }
                repository {
                  nameWithOwner
                }
              }
            }
          }
        }
        """
        
        try:
            variables = {"login": login}
            result = self.graphql_client.execute_query(query, variables)
            user_data = result.get("data", {}).get("user", {})
            
            if not user_data:
                return None
            
            issues = []
            for issue in user_data.get("issues", {}).get("nodes", []):
                if issue:
                    issues.append({
                        "title": issue.get("title"),
                        "state": issue.get("state"),
                        "url": issue.get("url"),
                        "created_at": issue.get("createdAt"),
                        "comments_count": issue.get("comments", {}).get("totalCount", 0),
                        "repository": issue.get("repository", {}).get("nameWithOwner")
                    })
            
            prs = []
            for pr in user_data.get("pullRequests", {}).get("nodes", []):
                if pr:
                    prs.append({
                        "title": pr.get("title"),
                        "state": pr.get("state"),
                        "merged": pr.get("merged", False),
                        "url": pr.get("url"),
                        "created_at": pr.get("createdAt"),
                        "comments_count": pr.get("comments", {}).get("totalCount", 0),
                        "repository": pr.get("repository", {}).get("nameWithOwner")
                    })
            
            return {
                "notable_issues": issues[:5],
                "notable_prs": prs[:5],
                "total_notable_issues": len(issues),
                "total_notable_prs": len(prs)
            }
        except Exception as e:
            error_str = str(e)
            if "RATE_LIMIT" in error_str or "rate limit" in error_str.lower():
                logger.error(f"❌ Rate limit alcanzado en issues/PRs de {login}")
                raise
            logger.debug(f"⚠️ Error obteniendo issues/PRs de {login}: {e}")
            return None
    
    def _fetch_packages(self, login: str) -> Optional[List[Dict[str, Any]]]:
        """
        Obtiene paquetes publicados por el usuario.
        """
        query = """
        query GetPackages($login: String!) {
          user(login: $login) {
            packages(first: 20) {
              nodes {
                name
                packageType
                repository {
                  nameWithOwner
                }
              }
            }
          }
        }
        """
        
        try:
            variables = {"login": login}
            result = self.graphql_client.execute_query(query, variables)
            user_data = result.get("data", {}).get("user", {})
            
            if not user_data:
                return None
            
            packages = user_data.get("packages", {}).get("nodes", [])
            
            formatted = []
            for pkg in packages:
                if pkg:
                    formatted.append({
                        "name": pkg.get("name"),
                        "type": pkg.get("packageType"),
                        "repository": pkg.get("repository", {}).get("nameWithOwner") if pkg.get("repository") else None
                    })
            
            return formatted if formatted else None
        except Exception as e:
            error_str = str(e)
            if "RATE_LIMIT" in error_str or "rate limit" in error_str.lower():
                logger.error(f"❌ Rate limit alcanzado en paquetes de {login}")
                raise
            logger.debug(f"⚠️ Error obteniendo paquetes de {login}: {e}")
            return None
    
    def _fetch_projects(self, login: str) -> Optional[List[Dict[str, Any]]]:
        """
        Obtiene proyectos personales del usuario (ProjectsV2).
        """
        query = """
        query GetProjects($login: String!) {
          user(login: $login) {
            projectsV2(first: 20) {
              nodes {
                title
                shortDescription
                public
                url
              }
            }
          }
        }
        """
        
        try:
            variables = {"login": login}
            result = self.graphql_client.execute_query(query, variables)
            user_data = result.get("data", {}).get("user", {})
            
            if not user_data:
                return None
            
            projects = user_data.get("projectsV2", {}).get("nodes", [])
            
            formatted = []
            for proj in projects:
                if proj:
                    formatted.append({
                        "title": proj.get("title"),
                        "description": proj.get("shortDescription"),
                        "is_public": proj.get("public", False),
                        "url": proj.get("url")
                    })
            
            return formatted if formatted else None
        except Exception as e:
            error_str = str(e)
            if "RATE_LIMIT" in error_str or "rate limit" in error_str.lower():
                logger.error(f"❌ Rate limit alcanzado en proyectos de {login}")
                raise
            logger.debug(f"⚠️ Error obteniendo proyectos de {login}: {e}")
            return None
    
    def _fetch_social_network_sample(self, login: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene una muestra de la red social (primeros 50 followers/following).
        NO obtiene todos para evitar sobrecarga.
        """
        query = """
        query GetSocialNetwork($login: String!) {
          user(login: $login) {
            followers(first: 50) {
              nodes {
                login
                name
              }
            }
            following(first: 50) {
              nodes {
                login
                name
              }
            }
          }
        }
        """
        
        try:
            variables = {"login": login}
            result = self.graphql_client.execute_query(query, variables)
            user_data = result.get("data", {}).get("user", {})
            
            if not user_data:
                return None
            
            followers = []
            for follower in user_data.get("followers", {}).get("nodes", []):
                if follower:
                    followers.append({
                        "login": follower.get("login"),
                        "name": follower.get("name")
                    })
            
            following = []
            for followed in user_data.get("following", {}).get("nodes", []):
                if followed:
                    following.append({
                        "login": followed.get("login"),
                        "name": followed.get("name")
                    })
            
            return {
                "followers_sample": followers,
                "following_sample": following,
                "sample_size": 50
            }
        except Exception as e:
            error_str = str(e)
            if "RATE_LIMIT" in error_str or "rate limit" in error_str.lower():
                logger.error(f"❌ Rate limit alcanzado en red social de {login}")
                raise
            logger.debug(f"⚠️ Error obteniendo red social de {login}: {e}")
            return None
    
    def _build_repository_references(self, login: str) -> Optional[Dict[str, Any]]:
        """
        Construye referencias a repositorios en tu colección de MongoDB.
        Evita duplicar información que ya tienes en la colección 'repositories'.
        """
        try:
            # Buscar repos donde el usuario es owner
            owned_repos = list(self.repos_repository.collection.find(
                {"owner.login": login},
                {"_id": 0, "id": 1, "name": 1, "name_with_owner": 1, "stargazers_count": 1}
            ).limit(100))
            
            owned_repos_ids = [r["id"] for r in owned_repos]
            
            # Buscar repos donde es colaborador (pero NO es owner)
            collab_repos = list(self.repos_repository.collection.find(
                {
                    "collaborators.login": login,
                    "owner.login": {"$ne": login}  # Excluir repos donde es owner
                },
                {"_id": 0, "id": 1, "name": 1, "name_with_owner": 1, "stargazers_count": 1}
            ).limit(100))
            
            if not owned_repos and not collab_repos:
                return None
            
            return {
                "owned_repos_count": len(owned_repos),
                "owned_repos_ids": owned_repos_ids,
                "collaborated_repos_count": len(collab_repos),
                "collaborated_repos_ids": [r["id"] for r in collab_repos],
                "note": "Ver colección 'repositories' para detalles completos"
            }
        except Exception as e:
            logger.debug(f"⚠️ Error construyendo referencias de repos de {login}: {e}")
            return None
    
    def _increment_field_stat(self, field: str) -> None:
        """Incrementa contador de campo enriquecido."""
        if field not in self.stats["fields_enriched"]:
            self.stats["fields_enriched"][field] = 0
        self.stats["fields_enriched"][field] += 1


def run_user_enrichment(
    max_users: Optional[int] = None,
    batch_size: int = 10,
    config: Optional[Dict[str, Any]] = None,
    force_reenrich: bool = False
) -> Dict[str, Any]:
    """
    Función helper para ejecutar enriquecimiento de usuarios.
    
    Args:
        max_users: Límite opcional de usuarios
        batch_size: Tamaño del lote
        config: Configuración opcional
        force_reenrich: Si True, re-enriquece incluso usuarios ya enriquecidos
        
    Returns:
        Estadísticas del proceso
    """
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    github_token = os.getenv("GITHUB_TOKEN")
    
    users_repository = MongoRepository(
        collection_name="users",
        unique_fields=["id"]
    )
    
    repos_repository = MongoRepository(
        collection_name="repositories",
        unique_fields=["id"]
    )
    
    engine = UserEnrichmentEngine(
        github_token=github_token,
        users_repository=users_repository,
        repos_repository=repos_repository,
        batch_size=batch_size,
        config=config
    )
    
    return engine.enrich_all_users(max_users=max_users, force_reenrich=force_reenrich)
