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
                logger.error(f"Errores en la respuesta de GraphQL: {data['errors']}")
                raise Exception(f"GraphQL errors: {data['errors']}")
            
            logger.debug("Query ejecutada exitosamente")
            return data
            
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
            Información del rate limit con campos: limit, remaining, resetAt, used, cost
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
    
    def _build_search_query(self, config_criteria) -> str:
        """
        Construye una query de búsqueda de GitHub a partir de los criterios de configuración.
        
        Args:
            config_criteria: Instancia de IngestionConfig con los criterios
            
        Returns:
            String de búsqueda de GitHub (ej: "quantum language:Python stars:>10")
        """
        query_parts = []
        
        # Agregar keywords (unidas con OR)
        if config_criteria.keywords:
            # Usar las primeras keywords como búsqueda principal
            # GitHub limita la longitud de la query, así que seleccionamos las más importantes
            keywords_query = " OR ".join(config_criteria.keywords[:5])
            query_parts.append(f"({keywords_query})")
        
        # Agregar lenguajes (unidas con OR)
        if config_criteria.languages:
            languages_query = " OR ".join([f"language:{lang}" for lang in config_criteria.languages])
            query_parts.append(f"({languages_query})")
        
        # Agregar estrellas mínimas
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
        after: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Busca repositorios usando los criterios de configuración.
        
        Args:
            config_criteria: Instancia de IngestionConfig (usa ingestion_config por defecto)
            first: Número de resultados a obtener (máx 100 por página)
            after: Cursor para paginación
            
        Returns:
            Lista de diccionarios con información de repositorios
        """
        # Usar configuración global si no se proporciona
        if config_criteria is None:
            config_criteria = ingestion_config
        
        # Verificar rate limit antes de la búsqueda
        self.check_rate_limit()
        
        # Construir la query de búsqueda
        search_query = self._build_search_query(config_criteria)
        
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
                  login
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
            
            # Obtener página actual
            result = self.search_repositories(
                config_criteria=config_criteria,
                first=100,
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


# Instancia global del cliente
github_client = GitHubGraphQLClient()
