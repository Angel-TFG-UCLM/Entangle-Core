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
            query = {"is_enriched": {"$ne": True}}  # Solo no enriquecidos
        
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
                try:
                    self._enrich_user(user)
                    self.stats["total_enriched"] += 1
                except Exception as e:
                    logger.error(f"❌ Error enriqueciendo {user.get('login', 'unknown')}: {e}")
                    self.stats["total_errors"] += 1
                
                self.stats["total_processed"] += 1
            
            # Pausa entre lotes
            if i + self.batch_size < total_users:
                time.sleep(2)
        
        self.stats["end_time"] = datetime.now()
        duration = (self.stats["end_time"] - self.stats["start_time"]).total_seconds()
        
        logger.info("\n" + "=" * 80)
        logger.info("✅ ENRIQUECIMIENTO DE USUARIOS COMPLETADO")
        logger.info("=" * 80)
        logger.info(f"\n📊 Estadísticas:")
        logger.info(f"  • Usuarios procesados: {self.stats['total_processed']}")
        logger.info(f"  • Usuarios enriquecidos: {self.stats['total_enriched']}")
        logger.info(f"  • Errores: {self.stats['total_errors']}")
        
        if self.stats['fields_enriched']:
            logger.info(f"\n📋 Campos enriquecidos:")
            for field, count in self.stats['fields_enriched'].items():
                logger.info(f"  • {field}: {count} usuarios")
        
        logger.info(f"\n⏱️  Duración: {duration:.2f}s ({duration/60:.1f} minutos)")
        
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
        
        # 0. Campos básicos faltantes de ingesta (si son None)
        basic_fields_missing = any(
            user.get(field) is None 
            for field in ['public_gists_count', 'starred_repos_count', 'watching_count',
                         'total_commit_contributions', 'total_issue_contributions',
                         'total_pr_contributions', 'total_pr_review_contributions']
        )
        
        if basic_fields_missing:
            basic_data = self._fetch_basic_fields(login)
            if basic_data:
                updates.update(basic_data)
                fields_enriched.extend(basic_data.keys())
                self._increment_field_stat("basic_fields_completed")
        
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
        quantum_repos = self._find_quantum_repositories(login)
        if quantum_repos:
            updates["quantum_repositories"] = quantum_repos
            updates["quantum_repos_count"] = len(quantum_repos)
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
        
        # Actualizar en MongoDB
        if updates:
            updates["is_enriched"] = True
            updates["enriched_at"] = datetime.now().isoformat()
            
            self.users_repository.collection.update_one(
                {"id": user["id"]},
                {"$set": updates}
            )
            
            logger.debug(f"✅ {login}: {len(updates)} campos actualizados ({len(fields_enriched)} enriquecidos)")
    
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
            
            # Clasificar tipos de error
            if "NOT_FOUND" in error_str or "Could not resolve" in error_str:
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
            logger.error(f"❌ Error obteniendo organizaciones de {login}: {e}")
            return None
    
    def _find_quantum_repositories(self, login: str) -> Optional[List[Dict[str, Any]]]:
        """
        Encuentra repositorios quantum del usuario en nuestra base de datos.
        
        Busca:
        1. Repos donde el usuario es owner
        2. Repos donde el usuario es colaborador
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
            
            for repo in repos:
                # Determinar rol
                role = "owner" if repo.get("owner", {}).get("login") == login else "collaborator"
                
                # Buscar contribuciones si es colaborador
                contributions = 0
                if role == "collaborator":
                    for collab in repo.get("collaborators", []):
                        if collab.get("login") == login:
                            contributions = collab.get("contributions", 0)
                            break
                
                quantum_repos.append({
                    "id": repo.get("id"),
                    "name": repo.get("name"),
                    "name_with_owner": repo.get("name_with_owner"),
                    "stars": repo.get("stargazers_count", 0),
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
        followers = user.get("followers_count", 0)
        following = user.get("following_count", 0)
        
        if following > 0:
            metrics["follower_following_ratio"] = round(followers / following, 2)
        else:
            metrics["follower_following_ratio"] = followers
        
        # Engagement score
        repos = user.get("public_repos_count", 0)
        starred = user.get("starred_repos_count", 0)
        
        if repos > 0:
            metrics["stars_per_repo"] = round(starred / repos, 2)
        
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
                    if any(keyword in (org.get("name", "") + org.get("description", "")).lower() 
                           for keyword in ["quantum", "qiskit", "cirq", "pennylane"])
                ]
                score += len(quantum_orgs) * 10.0
            
            # Normalizar a escala 0-100
            score = min(score, 100.0)
            
            return round(score, 2) if score > 0 else None
            
        except Exception as e:
            logger.error(f"❌ Error calculando quantum expertise: {e}")
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
