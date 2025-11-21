"""
Funciones de extracción de datos de GitHub.
"""
from typing import Dict, Any, Optional, List

from .graphql_client import github_client
from .queries import (
    ORGANIZATION_QUERY,
    REPOSITORY_QUERY,
    USER_QUERY,
    SEARCH_REPOSITORIES_QUERY
)
from ..core.logger import logger
from ..core.db import db


def extract_organization(org_login: str, save_to_db: bool = True) -> Dict[str, Any]:
    """
    Extrae información de una organización de GitHub.
    
    Args:
        org_login: Login de la organización
        save_to_db: Si se debe guardar en la base de datos
        
    Returns:
        Datos de la organización
    """
    logger.info(f"Extrayendo información de la organización: {org_login}")
    
    variables = {"login": org_login}
    result = github_client.execute_query(ORGANIZATION_QUERY, variables)
    
    org_data = result.get("data", {}).get("organization")
    
    if not org_data:
        logger.warning(f"No se encontró la organización: {org_login}")
        return {}
    
    if save_to_db:
        collection = db.get_collection("organizations")
        collection.update_one(
            {"id": org_data["id"]},
            {"$set": org_data},
            upsert=True
        )
        logger.info(f"Organización {org_login} guardada en la base de datos")
    
    return org_data


def extract_repository(owner: str, name: str, save_to_db: bool = True) -> Dict[str, Any]:
    """
    Extrae información de un repositorio de GitHub.
    
    Args:
        owner: Propietario del repositorio
        name: Nombre del repositorio
        save_to_db: Si se debe guardar en la base de datos
        
    Returns:
        Datos del repositorio
    """
    logger.info(f"Extrayendo información del repositorio: {owner}/{name}")
    
    variables = {"owner": owner, "name": name}
    result = github_client.execute_query(REPOSITORY_QUERY, variables)
    
    repo_data = result.get("data", {}).get("repository")
    
    if not repo_data:
        logger.warning(f"No se encontró el repositorio: {owner}/{name}")
        return {}
    
    if save_to_db:
        collection = db.get_collection("repositories")
        collection.update_one(
            {"id": repo_data["id"]},
            {"$set": repo_data},
            upsert=True
        )
        logger.info(f"Repositorio {owner}/{name} guardado en la base de datos")
    
    return repo_data


def extract_user(user_login: str, save_to_db: bool = True) -> Dict[str, Any]:
    """
    Extrae información de un usuario de GitHub.
    
    Args:
        user_login: Login del usuario
        save_to_db: Si se debe guardar en la base de datos
        
    Returns:
        Datos del usuario
    """
    logger.info(f"Extrayendo información del usuario: {user_login}")
    
    variables = {"login": user_login}
    result = github_client.execute_query(USER_QUERY, variables)
    
    user_data = result.get("data", {}).get("user")
    
    if not user_data:
        logger.warning(f"No se encontró el usuario: {user_login}")
        return {}
    
    if save_to_db:
        collection = db.get_collection("users")
        collection.update_one(
            {"id": user_data["id"]},
            {"$set": user_data},
            upsert=True
        )
        logger.info(f"Usuario {user_login} guardado en la base de datos")
    
    return user_data


def search_repositories(
    query: str,
    first: int = 10,
    save_to_db: bool = False
) -> List[Dict[str, Any]]:
    """
    Busca repositorios en GitHub.
    
    Args:
        query: Query de búsqueda
        first: Número de resultados
        save_to_db: Si se debe guardar en la base de datos
        
    Returns:
        Lista de repositorios encontrados
    """
    logger.info(f"Buscando repositorios con query: {query}")
    
    variables = {"query": query, "first": first}
    result = github_client.execute_query(SEARCH_REPOSITORIES_QUERY, variables)
    
    search_data = result.get("data", {}).get("search", {})
    edges = search_data.get("edges", [])
    
    repositories = [edge["node"] for edge in edges]
    
    logger.info(f"Se encontraron {len(repositories)} repositorios")
    
    if save_to_db and repositories:
        collection = db.get_collection("repositories")
        for repo in repositories:
            collection.update_one(
                {"id": repo["id"]},
                {"$set": repo},
                upsert=True
            )
        logger.info(f"{len(repositories)} repositorios guardados en la base de datos")
    
    return repositories
