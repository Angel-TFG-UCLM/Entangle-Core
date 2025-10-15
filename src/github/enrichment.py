"""
Motor de enriquecimiento de datos de repositorios.
Realiza una segunda pasada para completar información faltante usando GraphQL y REST API.
"""
import time
from typing import List, Dict, Any, Optional
from datetime import datetime
import requests
from src.core.logger import logger
from src.core.mongo_repository import MongoRepository
from src.github.graphql_client import GitHubGraphQLClient


class EnrichmentEngine:
    """
    Motor para enriquecer datos de repositorios ya ingestados.
    Completa campos faltantes usando múltiples fuentes (GraphQL, REST API).
    """
    
    def __init__(
        self,
        github_token: str,
        repos_repository: MongoRepository,
        batch_size: int = 10
    ):
        """
        Inicializa el motor de enriquecimiento.
        
        Args:
            github_token: Token de autenticación de GitHub
            repos_repository: Repositorio MongoDB para repositorios
            batch_size: Número de repositorios a procesar por lote
        """
        self.github_token = github_token
        self.repos_repository = repos_repository
        self.batch_size = batch_size
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
        
        logger.info(f"EnrichmentEngine inicializado (batch_size={batch_size})")
    
    def enrich_all_repositories(self, max_repos: Optional[int] = None) -> Dict[str, Any]:
        """
        Enriquece todos los repositorios en MongoDB.
        
        Args:
            max_repos: Límite opcional de repositorios a procesar
            
        Returns:
            Diccionario con estadísticas del proceso
        """
        logger.info("=" * 80)
        logger.info("🔄 INICIANDO ENRIQUECIMIENTO DE REPOSITORIOS")
        logger.info("=" * 80)
        
        self.stats["start_time"] = datetime.now()
        
        # Obtener repositorios de MongoDB
        query = {}
        repos = list(self.repos_repository.collection.find(query).limit(max_repos or 0))
        total_repos = len(repos)
        
        logger.info(f"📊 Repositorios a enriquecer: {total_repos}")
        
        if total_repos == 0:
            logger.warning("⚠️  No hay repositorios para enriquecer")
            return self.stats
        
        # Procesar en lotes
        for i in range(0, total_repos, self.batch_size):
            batch = repos[i:i + self.batch_size]
            batch_num = (i // self.batch_size) + 1
            total_batches = (total_repos + self.batch_size - 1) // self.batch_size
            
            logger.info(f"\n🔄 Procesando lote {batch_num}/{total_batches} ({len(batch)} repos)...")
            
            for repo in batch:
                try:
                    self._enrich_repository(repo)
                    self.stats["total_enriched"] += 1
                except Exception as e:
                    logger.error(f"❌ Error enriqueciendo {repo.get('name_with_owner', 'unknown')}: {e}")
                    self.stats["total_errors"] += 1
                
                self.stats["total_processed"] += 1
            
            # Respetar rate limits
            if i + self.batch_size < total_repos:
                logger.debug("⏳ Esperando 1s entre lotes...")
                time.sleep(1)
        
        self.stats["end_time"] = datetime.now()
        duration = (self.stats["end_time"] - self.stats["start_time"]).total_seconds()
        
        logger.info("\n" + "=" * 80)
        logger.info("✅ ENRIQUECIMIENTO COMPLETADO")
        logger.info("=" * 80)
        logger.info(f"📊 Estadísticas:")
        logger.info(f"  • Repositorios procesados: {self.stats['total_processed']}")
        logger.info(f"  • Repositorios enriquecidos: {self.stats['total_enriched']}")
        logger.info(f"  • Errores: {self.stats['total_errors']}")
        logger.info(f"  • Duración: {duration:.2f}s")
        logger.info(f"\n📝 Campos enriquecidos:")
        for field, count in sorted(self.stats['fields_enriched'].items()):
            logger.info(f"  • {field}: {count}")
        
        return self.stats
    
    def _enrich_repository(self, repo: Dict[str, Any]) -> None:
        """
        Enriquece un único repositorio.
        
        Args:
            repo: Documento del repositorio de MongoDB
        """
        repo_id = repo.get("id")
        name_with_owner = repo.get("name_with_owner")
        
        if not name_with_owner:
            logger.warning(f"⚠️  Repositorio sin name_with_owner: {repo_id}")
            return
        
        logger.debug(f"🔍 Enriqueciendo {name_with_owner}...")
        
        updates = {}
        
        # 1. Campos calculables (no requieren API)
        updates.update(self._calculate_fields(repo))
        
        # 2. URLs calculables
        updates.update(self._generate_urls(repo))
        
        # 3. Owner type y organization_id
        updates.update(self._enrich_owner_info(repo))
        
        # 4. README text (si está en la query pero no se parseó)
        if not repo.get("readme_text"):
            readme = self._fetch_readme_rest(name_with_owner)
            if readme:
                updates["readme_text"] = readme
                updates["has_readme"] = True
                self._increment_field_stat("readme_text")
                self._increment_field_stat("has_readme")
        
        # 5. Releases (REST API)
        if not repo.get("releases") or repo.get("releases_count", 0) == 0:
            releases_data = self._fetch_releases_rest(name_with_owner)
            if releases_data:
                updates["releases"] = releases_data["releases"]
                updates["releases_count"] = releases_data["count"]
                updates["latest_release"] = releases_data["latest"]
                self._increment_field_stat("releases")
                self._increment_field_stat("releases_count")
                if releases_data["latest"]:
                    self._increment_field_stat("latest_release")
        
        # 6. Branches count (REST API)
        if repo.get("branches_count", 0) == 0:
            branches_count = self._fetch_branches_count_rest(name_with_owner)
            if branches_count > 0:
                updates["branches_count"] = branches_count
                self._increment_field_stat("branches_count")
        
        # 7. Tags count (REST API)
        if repo.get("tags_count", 0) == 0:
            tags_count = self._fetch_tags_count_rest(name_with_owner)
            if tags_count > 0:
                updates["tags_count"] = tags_count
                self._increment_field_stat("tags_count")
        
        # 8. Recent commits (GraphQL)
        if not repo.get("recent_commits"):
            recent_commits = self._fetch_recent_commits_graphql(name_with_owner)
            if recent_commits:
                updates["recent_commits"] = recent_commits
                self._increment_field_stat("recent_commits")
                # Extraer last_commit_date
                if recent_commits and "committed_date" in recent_commits[0]:
                    updates["last_commit_date"] = recent_commits[0]["committed_date"]
                    self._increment_field_stat("last_commit_date")
        
        # 9. Recent issues (GraphQL)
        if not repo.get("recent_issues"):
            recent_issues = self._fetch_recent_issues_graphql(name_with_owner)
            if recent_issues:
                updates["recent_issues"] = recent_issues
                self._increment_field_stat("recent_issues")
        
        # 10. Recent pull requests (GraphQL)
        if not repo.get("recent_pull_requests"):
            recent_prs = self._fetch_recent_pull_requests_graphql(name_with_owner)
            if recent_prs:
                updates["recent_pull_requests"] = recent_prs
                self._increment_field_stat("recent_pull_requests")
        
        # 11. Pull requests detallados (REST API)
        pr_counts = self._fetch_pull_request_counts_rest(name_with_owner)
        if pr_counts:
            updates.update(pr_counts)
            for field in pr_counts.keys():
                self._increment_field_stat(field)
        
        # Actualizar en MongoDB si hay cambios
        if updates:
            updates["updated_at"] = datetime.now()
            self.repos_repository.collection.update_one(
                {"id": repo_id},
                {"$set": updates}
            )
            logger.debug(f"✅ {name_with_owner}: {len(updates)} campos actualizados")
        else:
            logger.debug(f"ℹ️  {name_with_owner}: Sin cambios")
    
    def _calculate_fields(self, repo: Dict[str, Any]) -> Dict[str, Any]:
        """Calcula campos derivados de datos existentes."""
        updates = {}
        
        # languages_count
        languages = repo.get("languages", [])
        if languages and repo.get("languages_count", 0) == 0:
            updates["languages_count"] = len(languages)
            self._increment_field_stat("languages_count")
        
        # topics_count
        topics = repo.get("repository_topics", [])
        if topics and repo.get("topics_count", 0) == 0:
            updates["topics_count"] = len(topics)
            self._increment_field_stat("topics_count")
        
        # issues_count
        open_issues = repo.get("open_issues_count", 0)
        closed_issues = repo.get("closed_issues_count", 0)
        if (open_issues or closed_issues) and repo.get("issues_count", 0) == 0:
            updates["issues_count"] = open_issues + closed_issues
            self._increment_field_stat("issues_count")
        
        return updates
    
    def _generate_urls(self, repo: Dict[str, Any]) -> Dict[str, Any]:
        """Genera URLs calculables."""
        updates = {}
        name_with_owner = repo.get("name_with_owner")
        
        if not name_with_owner:
            return updates
        
        # clone_url
        if not repo.get("clone_url"):
            updates["clone_url"] = f"https://github.com/{name_with_owner}.git"
            self._increment_field_stat("clone_url")
        
        # ssh_url
        if not repo.get("ssh_url"):
            updates["ssh_url"] = f"git@github.com:{name_with_owner}.git"
            self._increment_field_stat("ssh_url")
        
        return updates
    
    def _enrich_owner_info(self, repo: Dict[str, Any]) -> Dict[str, Any]:
        """Enriquece información del owner."""
        updates = {}
        owner = repo.get("owner", {})
        
        if not owner:
            return updates
        
        # owner.type - extraer del owner.url
        if not owner.get("type"):
            owner_url = owner.get("url", "")
            if "/orgs/" in owner_url:
                owner["type"] = "Organization"
                self._increment_field_stat("owner.type")
            elif "/users/" in owner_url:
                owner["type"] = "User"
                self._increment_field_stat("owner.type")
            
            if owner.get("type"):
                updates["owner"] = owner
        
        # organization_id - si es Organization, usar owner.id
        if owner.get("type") == "Organization" and not repo.get("organization_id"):
            updates["organization_id"] = owner.get("id")
            self._increment_field_stat("organization_id")
        
        return updates
    
    def _fetch_readme_rest(self, name_with_owner: str) -> Optional[str]:
        """Obtiene el contenido del README usando REST API."""
        url = f"https://api.github.com/repos/{name_with_owner}/readme"
        
        try:
            response = requests.get(url, headers=self.rest_headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                # El contenido viene en base64
                import base64
                content = base64.b64decode(data.get("content", "")).decode("utf-8")
                return content
            elif response.status_code == 404:
                logger.debug(f"ℹ️  {name_with_owner}: Sin README")
                return None
            else:
                logger.warning(f"⚠️  Error obteniendo README de {name_with_owner}: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"❌ Error en _fetch_readme_rest para {name_with_owner}: {e}")
            return None
    
    def _fetch_releases_rest(self, name_with_owner: str, max_releases: int = 10) -> Optional[Dict[str, Any]]:
        """Obtiene releases usando REST API."""
        url = f"https://api.github.com/repos/{name_with_owner}/releases"
        params = {"per_page": max_releases}
        
        try:
            response = requests.get(url, headers=self.rest_headers, params=params, timeout=10)
            
            if response.status_code == 200:
                releases = response.json()
                
                if not releases:
                    return None
                
                # Formatear releases
                formatted_releases = []
                for release in releases:
                    formatted_releases.append({
                        "id": release.get("id"),
                        "tag_name": release.get("tag_name"),
                        "name": release.get("name"),
                        "published_at": release.get("published_at"),
                        "is_prerelease": release.get("prerelease", False),
                        "is_draft": release.get("draft", False)
                    })
                
                return {
                    "releases": formatted_releases,
                    "count": len(formatted_releases),
                    "latest": formatted_releases[0] if formatted_releases else None
                }
            else:
                logger.debug(f"ℹ️  {name_with_owner}: Sin releases o error {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"❌ Error en _fetch_releases_rest para {name_with_owner}: {e}")
            return None
    
    def _fetch_branches_count_rest(self, name_with_owner: str) -> int:
        """Obtiene el número de ramas usando REST API."""
        url = f"https://api.github.com/repos/{name_with_owner}/branches"
        params = {"per_page": 1}
        
        try:
            response = requests.get(url, headers=self.rest_headers, params=params, timeout=10)
            
            if response.status_code == 200:
                # El total viene en el header Link
                link_header = response.headers.get("Link", "")
                if "last" in link_header:
                    # Extraer el número de la última página
                    import re
                    match = re.search(r'page=(\d+)>; rel="last"', link_header)
                    if match:
                        return int(match.group(1))
                
                # Si no hay paginación, contar directamente
                branches = response.json()
                return len(branches) if branches else 0
            else:
                return 0
        except Exception as e:
            logger.error(f"❌ Error en _fetch_branches_count_rest para {name_with_owner}: {e}")
            return 0
    
    def _fetch_tags_count_rest(self, name_with_owner: str) -> int:
        """Obtiene el número de tags usando REST API."""
        url = f"https://api.github.com/repos/{name_with_owner}/tags"
        params = {"per_page": 1}
        
        try:
            response = requests.get(url, headers=self.rest_headers, params=params, timeout=10)
            
            if response.status_code == 200:
                link_header = response.headers.get("Link", "")
                if "last" in link_header:
                    import re
                    match = re.search(r'page=(\d+)>; rel="last"', link_header)
                    if match:
                        return int(match.group(1))
                
                tags = response.json()
                return len(tags) if tags else 0
            else:
                return 0
        except Exception as e:
            logger.error(f"❌ Error en _fetch_tags_count_rest para {name_with_owner}: {e}")
            return 0
    
    def _fetch_recent_commits_graphql(self, name_with_owner: str, max_commits: int = 10) -> Optional[List[Dict[str, Any]]]:
        """Obtiene commits recientes usando GraphQL."""
        owner, repo_name = name_with_owner.split("/")
        
        query = """
        query GetRecentCommits($owner: String!, $name: String!, $first: Int!) {
          repository(owner: $owner, name: $name) {
            defaultBranchRef {
              target {
                ... on Commit {
                  history(first: $first) {
                    nodes {
                      oid
                      message
                      committedDate
                      author {
                        user {
                          login
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """
        
        variables = {"owner": owner, "name": repo_name, "first": max_commits}
        
        try:
            result = self.graphql_client.execute_query(query, variables)
            repo_data = result.get("data", {}).get("repository", {})
            
            if not repo_data:
                return None
            
            default_branch = repo_data.get("defaultBranchRef", {})
            target = default_branch.get("target", {})
            history = target.get("history", {})
            commits = history.get("nodes", [])
            
            if not commits:
                return None
            
            # Formatear commits
            formatted_commits = []
            for commit in commits:
                author = commit.get("author", {})
                user = author.get("user", {})
                
                formatted_commits.append({
                    "oid": commit.get("oid"),
                    "message": commit.get("message", "")[:100],  # Truncar mensaje
                    "committed_date": commit.get("committedDate"),
                    "author_login": user.get("login") if user else None
                })
            
            return formatted_commits
        except Exception as e:
            logger.error(f"❌ Error en _fetch_recent_commits_graphql para {name_with_owner}: {e}")
            return None
    
    def _fetch_recent_issues_graphql(self, name_with_owner: str, max_issues: int = 10) -> Optional[List[Dict[str, Any]]]:
        """Obtiene issues recientes usando GraphQL."""
        owner, repo_name = name_with_owner.split("/")
        
        query = """
        query GetRecentIssues($owner: String!, $name: String!, $first: Int!) {
          repository(owner: $owner, name: $name) {
            issues(first: $first, orderBy: {field: CREATED_AT, direction: DESC}) {
              nodes {
                id
                number
                title
                state
                createdAt
                closedAt
              }
            }
          }
        }
        """
        
        variables = {"owner": owner, "name": repo_name, "first": max_issues}
        
        try:
            result = self.graphql_client.execute_query(query, variables)
            repo_data = result.get("data", {}).get("repository", {})
            
            if not repo_data:
                return None
            
            issues = repo_data.get("issues", {}).get("nodes", [])
            
            if not issues:
                return None
            
            # Formatear issues
            formatted_issues = []
            for issue in issues:
                formatted_issues.append({
                    "id": issue.get("id"),
                    "number": issue.get("number"),
                    "title": issue.get("title", "")[:100],
                    "state": issue.get("state"),
                    "created_at": issue.get("createdAt"),
                    "closed_at": issue.get("closedAt")
                })
            
            return formatted_issues
        except Exception as e:
            logger.error(f"❌ Error en _fetch_recent_issues_graphql para {name_with_owner}: {e}")
            return None
    
    def _fetch_recent_pull_requests_graphql(self, name_with_owner: str, max_prs: int = 10) -> Optional[List[Dict[str, Any]]]:
        """Obtiene PRs recientes usando GraphQL."""
        owner, repo_name = name_with_owner.split("/")
        
        query = """
        query GetRecentPRs($owner: String!, $name: String!, $first: Int!) {
          repository(owner: $owner, name: $name) {
            pullRequests(first: $first, orderBy: {field: CREATED_AT, direction: DESC}) {
              nodes {
                id
                number
                title
                state
                createdAt
                closedAt
                mergedAt
              }
            }
          }
        }
        """
        
        variables = {"owner": owner, "name": repo_name, "first": max_prs}
        
        try:
            result = self.graphql_client.execute_query(query, variables)
            repo_data = result.get("data", {}).get("repository", {})
            
            if not repo_data:
                return None
            
            prs = repo_data.get("pullRequests", {}).get("nodes", [])
            
            if not prs:
                return None
            
            # Formatear PRs
            formatted_prs = []
            for pr in prs:
                formatted_prs.append({
                    "id": pr.get("id"),
                    "number": pr.get("number"),
                    "title": pr.get("title", "")[:100],
                    "state": pr.get("state"),
                    "created_at": pr.get("createdAt"),
                    "closed_at": pr.get("closedAt"),
                    "merged_at": pr.get("mergedAt")
                })
            
            return formatted_prs
        except Exception as e:
            logger.error(f"❌ Error en _fetch_recent_pull_requests_graphql para {name_with_owner}: {e}")
            return None
    
    def _fetch_pull_request_counts_rest(self, name_with_owner: str) -> Optional[Dict[str, int]]:
        """Obtiene contadores detallados de PRs usando REST API."""
        base_url = f"https://api.github.com/repos/{name_with_owner}/pulls"
        
        counts = {}
        
        try:
            # PRs abiertos
            response = requests.get(
                base_url,
                headers=self.rest_headers,
                params={"state": "open", "per_page": 1},
                timeout=10
            )
            if response.status_code == 200:
                counts["open_pull_requests_count"] = self._extract_total_count(response)
            
            # PRs cerrados
            response = requests.get(
                base_url,
                headers=self.rest_headers,
                params={"state": "closed", "per_page": 1},
                timeout=10
            )
            if response.status_code == 200:
                closed_count = self._extract_total_count(response)
                
                # Para obtener merged vs closed sin merge, necesitamos otra query
                # Por ahora, guardamos el total de cerrados
                counts["closed_pull_requests_count"] = closed_count
            
            return counts if counts else None
        except Exception as e:
            logger.error(f"❌ Error en _fetch_pull_request_counts_rest para {name_with_owner}: {e}")
            return None
    
    def _extract_total_count(self, response: requests.Response) -> int:
        """Extrae el conteo total de una respuesta paginada de GitHub."""
        link_header = response.headers.get("Link", "")
        if "last" in link_header:
            import re
            match = re.search(r'page=(\d+)>; rel="last"', link_header)
            if match:
                return int(match.group(1))
        
        # Si no hay paginación, contar elementos
        data = response.json()
        return len(data) if isinstance(data, list) else 0
    
    def _increment_field_stat(self, field: str) -> None:
        """Incrementa el contador de un campo enriquecido."""
        self.stats["fields_enriched"][field] = self.stats["fields_enriched"].get(field, 0) + 1
