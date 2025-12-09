"""
Cliente GraphQL para interactuar con la API de GitHub.
"""
import requests
import time
from datetime import datetime
from typing import Dict, Any, Optional, List

from ..core.config import config, ingestion_config
from ..core.logger import logger


class GitHubGraphQLClient:
    """Cliente para realizar consultas GraphQL a GitHub."""
    
    def __init__(self, token: Optional[str] = None):
        """
        Inicializa el cliente GraphQL.
        
        Args:
            token: Token de autenticación de GitHub (opcional, usa config si no se proporciona)
            
        Raises:
            ValueError: Si el token no está configurado
        """
        self.token = token or config.GITHUB_TOKEN
        
        if not self.token:
            error_msg = "GITHUB_TOKEN no está configurado. Define la variable de entorno o pasa el token al constructor."
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        self.api_url = config.GITHUB_API_URL
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        logger.info("Cliente GraphQL de GitHub inicializado correctamente")
    
    def execute_query(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Ejecuta una consulta GraphQL.
        
        Args:
            query: Query GraphQL a ejecutar
            variables: Variables para la query
            
        Returns:
            Respuesta de la API en formato diccionario
            
        Raises:
            requests.HTTPError: Si la petición falla
        """
        payload = {"query": query}
        if variables:
            payload["variables"] = variables
        
        logger.debug(f"Ejecutando query GraphQL: {query[:100]}...")
        
        # Reintentos automáticos en caso de errores 502/503
        max_retries = 5
        retry_delay = 5  # segundos
        
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    self.api_url,
                    json=payload,
                    headers=self.headers,
                    timeout=30
                )
                response.raise_for_status()
                
                data = response.json()
                
                # Verificar si hay errores en la respuesta
                if "errors" in data:
                    errors = data['errors']
                    
                    # Detectar específicamente errores de RATE_LIMIT
                    is_rate_limit_error = False
                    for error in errors:
                        if error.get('type') == 'RATE_LIMIT' or 'rate limit' in str(error).lower():
                            is_rate_limit_error = True
                            logger.warning(f"⚠️ Rate limit de GitHub alcanzado: {error.get('message')}")
                            
                            # Obtener información del rate limit usando REST API (no GraphQL)
                            try:
                                rate_info = self._get_rate_limit_rest()
                                graphql_rate = rate_info.get('resources', {}).get('graphql', {})
                                
                                reset_timestamp = graphql_rate.get('reset', 0)
                                remaining = graphql_rate.get('remaining', 0)
                                limit = graphql_rate.get('limit', 5000)
                                
                                logger.info(f"Rate limit GraphQL: {remaining}/{limit} requests restantes")
                                
                                if reset_timestamp > 0:
                                    # Calcular tiempo de espera exacto
                                    reset_time = datetime.fromtimestamp(reset_timestamp)
                                    now = datetime.now()
                                    wait_seconds = max(0, (reset_time - now).total_seconds()) + 5  # +5s margen
                                    
                                    reset_str = reset_time.strftime('%Y-%m-%d %H:%M:%S')
                                    logger.info(f"Rate limit se reseteará el: {reset_str}")
                                    logger.info(f"Esperando {wait_seconds:.0f} segundos ({wait_seconds/60:.1f} minutos)...")
                                    
                                    # Esperar con progreso cada minuto
                                    remaining_wait = wait_seconds
                                    while remaining_wait > 0:
                                        sleep_chunk = min(60, remaining_wait)
                                        time.sleep(sleep_chunk)
                                        remaining_wait -= sleep_chunk
                                        if remaining_wait > 60:
                                            logger.info(f"Quedan {remaining_wait:.0f}s ({remaining_wait/60:.1f} min)...")
                                    
                                    logger.info("✅ Rate limit reseteado. Reintentando query...")
                                    # Salir del for de errores para reintentar
                                    break
                                else:
                                    # Espera por defecto si no hay timestamp
                                    logger.warning("⚠️ No se pudo obtener tiempo de reset. Esperando 1 hora...")
                                    time.sleep(3600)
                                    break
                                    
                            except Exception as rate_err:
                                logger.error(f"❌ Error obteniendo rate limit REST: {rate_err}")
                                # Espera por defecto
                                logger.info("Esperando 1 hora por defecto...")
                                time.sleep(3600)
                                break
                    
                    # Si detectamos rate limit, continuar al siguiente intento
                    if is_rate_limit_error and attempt < max_retries - 1:
                        continue
                    
                    # Si no es rate limit o se agotaron reintentos, lanzar error
                    logger.error(f"Errores en la respuesta de GraphQL: {errors}")
                    raise Exception(f"GraphQL errors: {errors}")
                
                logger.debug("Query ejecutada exitosamente")
                return data
                
            except requests.exceptions.Timeout as timeout_err:
                # Timeout de la petición
                if attempt < max_retries - 1:
                    logger.warning(f"⚠️ Timeout después de 30s, reintentando en {retry_delay}s (intento {attempt + 1}/{max_retries})...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                else:
                    logger.error(f"Error en la petición GraphQL: {timeout_err}")
                    raise
                    
            except requests.exceptions.HTTPError as http_err:
                # Reintentar en errores de servidor temporal (408, 502, 503, 504)
                if hasattr(http_err, 'response') and http_err.response is not None:
                    status_code = http_err.response.status_code
                    if status_code in [408, 502, 503, 504] and attempt < max_retries - 1:
                        logger.warning(f"⚠️ Error {status_code}, reintentando en {retry_delay}s (intento {attempt + 1}/{max_retries})...")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                
                logger.error(f"Error en la petición GraphQL: {http_err}")
                raise
                    
            except requests.exceptions.ConnectionError as conn_err:
                # Error de conexión
                if attempt < max_retries - 1:
                    logger.warning(f"⚠️ Error de conexión, reintentando en {retry_delay}s (intento {attempt + 1}/{max_retries})...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                else:
                    logger.error(f"Error en la petición GraphQL: {conn_err}")
                    raise
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"Error en la petición GraphQL: {e}")
                raise
                
            except Exception as e:
                logger.error(f"Error inesperado al ejecutar query: {e}")
                raise
    
    def get_rate_limit(self) -> Dict[str, Any]:
        """
        Obtiene información sobre el rate limit actual.
        
        Returns:
            Información del rate limit con campos: limit, remaining, resetAt, reset_at (datetime), used, cost
        """
        query = """
        query {
            rateLimit {
                limit
                cost
                remaining
                resetAt
                used
            }
        }
        """
        result = self.execute_query(query)
        rate_limit = result.get("data", {}).get("rateLimit", {})
        
        # Agregar reset_at como datetime para compatibilidad
        if rate_limit.get("resetAt"):
            try:
                reset_at_str = rate_limit.get("resetAt")
                rate_limit["reset_at"] = datetime.fromisoformat(reset_at_str.replace('Z', '+00:00'))
            except Exception:
                rate_limit["reset_at"] = None
        
        logger.debug(
            f"Rate limit - Remaining: {rate_limit.get('remaining')}/{rate_limit.get('limit')}, "
            f"Reset at: {rate_limit.get('resetAt')}"
        )
        
        return rate_limit
    
    def check_rate_limit(self, min_remaining: int = 50):
        """
        Verifica el rate limit y espera si es necesario.
        
        Args:
            min_remaining: Número mínimo de requests restantes antes de esperar
            
        Si quedan menos de `min_remaining` requests, el método esperará
        hasta que se resetee el rate limit.
        """
        rate_limit = self.get_rate_limit()
        remaining = rate_limit.get("remaining", 0)
        reset_at = rate_limit.get("resetAt")
        
        if remaining < min_remaining:
            logger.warning(
                f"Rate limit bajo ({remaining}/{rate_limit.get('limit')}). "
                f"Esperando hasta el reset..."
            )
            
            if reset_at:
                # Convertir timestamp ISO 8601 a datetime
                reset_time = datetime.fromisoformat(reset_at.replace('Z', '+00:00'))
                now = datetime.now(reset_time.tzinfo)
                
                if reset_time > now:
                    wait_seconds = (reset_time - now).total_seconds() + 5  # 5 segundos de margen
                    logger.warning(f"Esperando {wait_seconds:.0f} segundos hasta el reset del rate limit...")
                    time.sleep(wait_seconds)
                    logger.info("Rate limit reseteado. Continuando...")
    
    def _get_rate_limit_rest(self) -> Dict[str, Any]:
        """
        Obtiene información del rate limit usando REST API en lugar de GraphQL.
        
        Esto evita el bucle recursivo cuando GraphQL está en rate limit.
        Endpoint: https://api.github.com/rate_limit
        
        Returns:
            Dict con información completa del rate limit:
            {
                "resources": {
                    "core": {"limit": 5000, "remaining": 4999, "reset": 1234567890},
                    "search": {"limit": 30, "remaining": 30, "reset": 1234567890},
                    "graphql": {"limit": 5000, "remaining": 0, "reset": 1234567890}
                }
            }
        """
        rest_url = "https://api.github.com/rate_limit"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        try:
            response = requests.get(rest_url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            logger.debug(f"Rate limit REST obtenido: {data.get('resources', {}).get('graphql', {})}")
            return data
        except Exception as e:
            logger.error(f"Error obteniendo rate limit REST: {e}")
            raise
    
    def _build_search_query(self, config_criteria, use_simple_query: bool = False) -> str:
        """
        Construye una query de búsqueda de GitHub a partir de los criterios de configuración.
        
        Args:
            config_criteria: Instancia de IngestionConfig con los criterios
            use_simple_query: Si True, usa solo la keyword principal (para búsquedas amplias)
            
        Returns:
            String de búsqueda de GitHub (ej: "quantum stars:>10 fork:false")
        """
        query_parts = []
        
        # Agregar keywords como términos de búsqueda principales
        if config_criteria.keywords:
            if use_simple_query:
                # Búsqueda simple: solo la primera keyword
                query_parts.append(config_criteria.keywords[0])
            else:
                # Búsqueda avanzada: combinar keywords principales con OR
                # Seleccionar las primeras 5 keywords más relevantes
                main_keywords = config_criteria.keywords[:5]
                # GitHub entiende espacios como OR cuando están en el texto de búsqueda
                keywords_query = " OR ".join(main_keywords)
                query_parts.append(f"({keywords_query})")
        
        # Agregar estrellas mínimas (criterio importante para calidad)
        if config_criteria.min_stars > 0:
            query_parts.append(f"stars:>={config_criteria.min_stars}")
        
        # Excluir forks si está configurado
        if config_criteria.exclude_forks:
            query_parts.append("fork:false")
        
        # Construir query final
        search_query = " ".join(query_parts)
        logger.debug(f"Query de búsqueda construida: {search_query}")
        
        return search_query
    
    def search_repositories(
        self, 
        config_criteria=None,
        first: int = 100,
        after: Optional[str] = None,
        use_simple_query: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Busca repositorios usando los criterios de configuración.
        
        Args:
            config_criteria: Instancia de IngestionConfig (usa ingestion_config por defecto)
            first: Número de resultados a obtener (máx 100 por página)
            after: Cursor para paginación
            use_simple_query: Si True, usa búsqueda simple (más resultados)
            
        Returns:
            Lista de diccionarios con información de repositorios
        """
        # Usar configuración global si no se proporciona
        if config_criteria is None:
            config_criteria = ingestion_config
        
        # Verificar rate limit antes de la búsqueda
        self.check_rate_limit()
        
        # Construir la query de búsqueda
        search_query = self._build_search_query(config_criteria, use_simple_query)
        
        # Query GraphQL para búsqueda de repositorios
        graphql_query = """
        query SearchRepositories($query: String!, $first: Int!, $after: String) {
          search(query: $query, type: REPOSITORY, first: $first, after: $after) {
            repositoryCount
            pageInfo {
              hasNextPage
              endCursor
            }
            nodes {
              ... on Repository {
                id
                name
                nameWithOwner
                owner {
                  id
                  login
                  url
                  avatarUrl
                  ... on User {
                    name
                    email
                  }
                  ... on Organization {
                    name
                    email
                  }
                }
                description
                url
                homepageUrl
                createdAt
                updatedAt
                pushedAt
                stargazerCount
                forkCount
                watchers {
                  totalCount
                }
                primaryLanguage {
                  name
                  color
                }
                languages(first: 10) {
                  edges {
                    node {
                      name
                    }
                    size
                  }
                }
                isFork
                isArchived
                isPrivate
                licenseInfo {
                  name
                  spdxId
                }
                repositoryTopics(first: 10) {
                  nodes {
                    topic {
                      name
                    }
                  }
                }
                hasIssuesEnabled
                hasWikiEnabled
                openIssues: issues(states: OPEN) {
                  totalCount
                }
                closedIssues: issues(states: CLOSED) {
                  totalCount
                }
                pullRequests {
                  totalCount
                }
                defaultBranchRef {
                  name
                  target {
                    ... on Commit {
                      history {
                        totalCount
                      }
                    }
                  }
                }
                diskUsage
                object(expression: "HEAD:README.md") {
                  ... on Blob {
                    text
                  }
                }
              }
            }
          }
        }
        """
        
        variables = {
            "query": search_query,
            "first": min(first, 100),  # GitHub limita a 100 por página
            "after": after
        }
        
        logger.info(f"Buscando repositorios con criterios: {search_query}")
        
        try:
            result = self.execute_query(graphql_query, variables)
            search_data = result.get("data", {}).get("search", {})
            
            repositories = search_data.get("nodes", [])
            repository_count = search_data.get("repositoryCount", 0)
            page_info = search_data.get("pageInfo", {})
            
            logger.info(
                f"Encontrados {len(repositories)} repositorios en esta página. "
                f"Total: {repository_count}"
            )
            
            # Agregar información de paginación
            result_data = {
                "repositories": repositories,
                "total_count": repository_count,
                "page_info": page_info
            }
            
            return result_data
            
        except Exception as e:
            logger.error(f"Error al buscar repositorios: {e}")
            raise
    
    def search_repositories_all_pages(
        self,
        config_criteria=None,
        max_results: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Busca repositorios obteniendo todas las páginas disponibles.
        
        Args:
            config_criteria: Instancia de IngestionConfig (usa ingestion_config por defecto)
            max_results: Número máximo de resultados a obtener (None = todos)
            
        Returns:
            Lista completa de repositorios
        """
        all_repositories = []
        after_cursor = None
        has_next_page = True
        
        logger.info("Iniciando búsqueda de repositorios (todas las páginas)...")
        
        while has_next_page:
            # Verificar si ya alcanzamos el máximo
            if max_results and len(all_repositories) >= max_results:
                logger.info(f"Alcanzado el límite de {max_results} repositorios")
                break
            
            # Obtener página actual (reducido a 20 para evitar RESOURCE_LIMITS_EXCEEDED)
            result = self.search_repositories(
                config_criteria=config_criteria,
                first=20,  # Reducido de 100 a 20 para evitar límites de recursos
                after=after_cursor
            )
            
            # Agregar repositorios de esta página
            repositories = result.get("repositories", [])
            all_repositories.extend(repositories)
            
            # Verificar si hay más páginas
            page_info = result.get("page_info", {})
            has_next_page = page_info.get("hasNextPage", False)
            after_cursor = page_info.get("endCursor")
            
            logger.info(f"Repositorios recolectados hasta ahora: {len(all_repositories)}")
            
            # Pausa breve entre páginas para evitar rate limit
            if has_next_page:
                time.sleep(1)
        
        logger.info(f"Búsqueda completada. Total de repositorios: {len(all_repositories)}")
        
        # Limitar al máximo si se especificó
        if max_results:
            all_repositories = all_repositories[:max_results]
        
        return all_repositories
    
    def search_repositories_segmented(
        self,
        config_criteria=None,
        min_stars: int = 0,
        max_stars: int = 999999,
        created_year: int = 2020,
        max_results: Optional[int] = 1000
    ) -> List[Dict[str, Any]]:
        """
        Busca repositorios en un segmento específico (estrellas + año de creación).
        
        Este método permite segmentar búsquedas para superar el límite de 1000
        resultados de GitHub Search API.
        
        Args:
            config_criteria: Instancia de IngestionConfig (usa ingestion_config por defecto)
            min_stars: Número mínimo de estrellas del segmento
            max_stars: Número máximo de estrellas del segmento
            created_year: Año de creación de los repositorios
            max_results: Máximo de resultados para este segmento (default 1000)
            
        Returns:
            Lista de repositorios del segmento especificado
        """
        # Usar la configuración global si no se proporciona
        from ..core.config import ingestion_config
        config = config_criteria or ingestion_config
        
        # Construir query base con keywords y lenguajes
        query_parts = []
        
        # Keyword principal (solo la primera, sin comillas si tiene espacios)
        if config.keywords:
            # Usar solo la primera keyword para simplificar
            main_keyword = config.keywords[0]
            query_parts.append(main_keyword)
        
        # Segmentación por estrellas
        query_parts.append(f"stars:{min_stars}..{max_stars}")
        
        # Segmentación por año de creación
        query_parts.append(f"created:{created_year}-01-01..{created_year}-12-31")
        
        # Excluir forks si está configurado
        if config.exclude_forks:
            query_parts.append("fork:false")
        
        # Construir query final
        query_string = " ".join(query_parts)
        
        logger.debug(f"Query segmentada: {query_string}")
        
        # Query GraphQL (IDÉNTICA al método search_repositories para mantener compatibilidad)
        graphql_query = """
        query SearchRepositories($query: String!, $first: Int!, $after: String) {
          search(query: $query, type: REPOSITORY, first: $first, after: $after) {
            repositoryCount
            pageInfo {
              hasNextPage
              endCursor
            }
            nodes {
              ... on Repository {
                id
                name
                nameWithOwner
                owner {
                  id
                  login
                  url
                  avatarUrl
                  ... on User {
                    name
                    email
                  }
                  ... on Organization {
                    name
                    email
                  }
                }
                description
                url
                homepageUrl
                createdAt
                updatedAt
                pushedAt
                stargazerCount
                forkCount
                watchers {
                  totalCount
                }
                primaryLanguage {
                  name
                  color
                }
                languages(first: 10) {
                  edges {
                    node {
                      name
                    }
                    size
                  }
                }
                isFork
                isArchived
                isPrivate
                licenseInfo {
                  name
                  spdxId
                }
                repositoryTopics(first: 10) {
                  nodes {
                    topic {
                      name
                    }
                  }
                }
                hasIssuesEnabled
                hasWikiEnabled
                openIssues: issues(states: OPEN) {
                  totalCount
                }
                closedIssues: issues(states: CLOSED) {
                  totalCount
                }
                pullRequests {
                  totalCount
                }
                defaultBranchRef {
                  name
                  target {
                    ... on Commit {
                      history {
                        totalCount
                      }
                    }
                  }
                }
                diskUsage
                object(expression: "HEAD:README.md") {
                  ... on Blob {
                    text
                  }
                }
              }
            }
          }
        }
        """
        
        # Ejecutar búsqueda con paginación
        all_repositories = []
        after_cursor = None
        has_next_page = True
        
        while has_next_page and len(all_repositories) < max_results:
            try:
                # Verificar rate limit
                self.check_rate_limit()
                
                # Variables para la query
                variables = {
                    "query": query_string,
                    "first": min(20, max_results - len(all_repositories)),
                    "after": after_cursor
                }
                
                # Ejecutar query
                response = self.execute_query(graphql_query, variables)
                
                # Parsear respuesta
                search_data = response.get("data", {}).get("search", {})
                repositories = search_data.get("nodes", [])
                
                all_repositories.extend(repositories)
                
                # Verificar paginación
                page_info = search_data.get("pageInfo", {})
                has_next_page = page_info.get("hasNextPage", False)
                after_cursor = page_info.get("endCursor")
                
                logger.debug(f"  Página obtenida: {len(repositories)} repos (total: {len(all_repositories)})")
                
                # Pausa breve entre páginas
                if has_next_page:
                    time.sleep(0.5)
                
            except Exception as e:
                logger.warning(f"Error en paginación del segmento: {e}")
                break
        
        # Limitar resultados
        if max_results:
            all_repositories = all_repositories[:max_results]
        
        return all_repositories


# Instancia global del cliente
github_client = GitHubGraphQLClient()
