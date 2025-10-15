"""
Filtros avanzados de calidad y relevancia para repositorios de software cuántico.

Este módulo implementa filtros adicionales basados en criterios del paper académico
para garantizar que los datos finales sean representativos, activos y realmente 
relacionados con software cuántico.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
import logging

# Usar logging directo para evitar importaciones circulares
logger = logging.getLogger(__name__)


class RepositoryFilters:
    """
    Clase que agrupa todos los filtros avanzados de calidad para repositorios.
    
    Cada método es independiente y retorna True si el repositorio pasa el filtro,
    False si debe ser rechazado.
    """
    
    @staticmethod
    def is_active(
        repo: Dict[str, Any],
        max_inactivity_days: int = 365
    ) -> bool:
        """
        Verifica que el repositorio haya sido actualizado recientemente.
        
        Args:
            repo: Repositorio a evaluar
            max_inactivity_days: Número máximo de días sin actualización
            
        Returns:
            True si el repo está activo, False si está inactivo
        """
        updated_at_str = repo.get("updatedAt") or repo.get("pushedAt")
        
        if not updated_at_str:
            logger.debug(
                f"Repo rechazado (sin fecha de actualización): "
                f"{repo.get('nameWithOwner')}"
            )
            return False
        
        # Convertir fecha a datetime
        try:
            updated_at = datetime.fromisoformat(
                updated_at_str.replace('Z', '+00:00')
            )
            now = datetime.now(timezone.utc)
            
            # Calcular días de inactividad
            inactivity_days = (now - updated_at).days
            
            if inactivity_days > max_inactivity_days:
                logger.debug(
                    f"Repo rechazado (inactivo {inactivity_days} días > {max_inactivity_days}): "
                    f"{repo.get('nameWithOwner')}"
                )
                return False
            
            return True
            
        except Exception as e:
            logger.warning(
                f"Error al parsear fecha de {repo.get('nameWithOwner')}: {e}"
            )
            return False
    
    @staticmethod
    def is_valid_fork(repo: Dict[str, Any]) -> bool:
        """
        Verifica si un fork tiene contribuciones propias (no es simplemente una copia).
        
        Un fork es válido si:
        - No es fork, O
        - Es fork pero tiene commits propios (más de 5 commits de diferencia)
        
        Args:
            repo: Repositorio a evaluar
            
        Returns:
            True si no es fork o es fork con contribuciones, False si es fork sin aportes
        """
        is_fork = repo.get("isFork", False)
        
        # Si no es fork, está OK
        if not is_fork:
            return True
        
        # Si es fork, verificar que tenga actividad propia
        # Usamos varios indicadores:
        
        # 1. Número de commits propios
        commit_count = 0
        default_branch = repo.get("defaultBranchRef")
        if default_branch:
            target = default_branch.get("target", {})
            history = target.get("history", {})
            commit_count = history.get("totalCount", 0)
        
        # 2. Issues y PRs (indicadores de actividad)
        open_issues = repo.get("openIssues", {}).get("totalCount", 0)
        closed_issues = repo.get("closedIssues", {}).get("totalCount", 0)
        pull_requests = repo.get("pullRequests", {}).get("totalCount", 0)
        
        total_issues = open_issues + closed_issues
        
        # Criterio: Al menos 10 commits O al menos 5 issues/PRs
        has_own_contributions = (commit_count >= 10) or (total_issues + pull_requests >= 5)
        
        if not has_own_contributions:
            logger.debug(
                f"Repo rechazado (fork sin contribuciones propias - "
                f"{commit_count} commits, {total_issues} issues, {pull_requests} PRs): "
                f"{repo.get('nameWithOwner')}"
            )
            return False
        
        logger.debug(
            f"Fork válido con contribuciones ({commit_count} commits, "
            f"{total_issues} issues, {pull_requests} PRs): "
            f"{repo.get('nameWithOwner')}"
        )
        return True
    
    @staticmethod
    def has_description(repo: Dict[str, Any]) -> bool:
        """
        Verifica que el repositorio tenga descripción o README.
        
        Args:
            repo: Repositorio a evaluar
            
        Returns:
            True si tiene descripción o README, False si no tiene documentación
        """
        # Verificar descripción
        description = repo.get("description")
        has_desc = description and len(description.strip()) > 0
        
        # Verificar README
        readme_obj = repo.get("object")
        has_readme = readme_obj is not None and readme_obj.get("text")
        
        if not has_desc and not has_readme:
            logger.debug(
                f"Repo rechazado (sin descripción ni README): "
                f"{repo.get('nameWithOwner')}"
            )
            return False
        
        return True
    
    @staticmethod
    def is_minimal_project(
        repo: Dict[str, Any],
        min_commits: int = 10,
        min_size_kb: int = 10
    ) -> bool:
        """
        Verifica que el proyecto tenga un tamaño y actividad mínima.
        
        Criterios:
        - Al menos X commits (por defecto 10)
        - Al menos Y KB de tamaño (por defecto 10 KB)
        
        Args:
            repo: Repositorio a evaluar
            min_commits: Número mínimo de commits
            min_size_kb: Tamaño mínimo en KB
            
        Returns:
            True si cumple los criterios mínimos, False si es demasiado pequeño
        """
        # Verificar commits
        commit_count = 0
        default_branch = repo.get("defaultBranchRef")
        if default_branch:
            target = default_branch.get("target", {})
            history = target.get("history", {})
            commit_count = history.get("totalCount", 0)
        
        if commit_count < min_commits:
            logger.debug(
                f"Repo rechazado (muy pocos commits: {commit_count} < {min_commits}): "
                f"{repo.get('nameWithOwner')}"
            )
            return False
        
        # Verificar tamaño
        disk_usage = repo.get("diskUsage", 0)  # En KB
        if disk_usage < min_size_kb:
            logger.debug(
                f"Repo rechazado (muy pequeño: {disk_usage} KB < {min_size_kb} KB): "
                f"{repo.get('nameWithOwner')}"
            )
            return False
        
        return True
    
    @staticmethod
    def matches_keywords(
        repo: Dict[str, Any],
        keywords: List[str]
    ) -> bool:
        """
        Verifica que el repositorio contenga al menos una keyword cuántica.
        
        Busca en:
        - Nombre del repositorio
        - Descripción
        - Topics
        - README (primeras líneas si está disponible)
        
        Args:
            repo: Repositorio a evaluar
            keywords: Lista de palabras clave a buscar
            
        Returns:
            True si contiene al menos una keyword, False si no contiene ninguna
        """
        if not keywords:
            return True
        
        # Obtener textos donde buscar (en minúsculas)
        name = repo.get("name", "").lower()
        description = repo.get("description") or ""
        description = description.lower()
        
        # Topics
        topics = repo.get("repositoryTopics", {}).get("nodes", [])
        topic_names = [
            topic.get("topic", {}).get("name", "").lower()
            for topic in topics
        ]
        
        # README (primeras 500 caracteres)
        readme_text = ""
        readme_obj = repo.get("object")
        if readme_obj:
            readme_full = readme_obj.get("text", "")
            readme_text = readme_full[:500].lower() if readme_full else ""
        
        # Combinar todos los textos
        searchable_text = f"{name} {description} {' '.join(topic_names)} {readme_text}"
        
        # Buscar keywords
        for keyword in keywords:
            if keyword.lower() in searchable_text:
                return True
        
        logger.debug(
            f"Repo rechazado (sin keywords cuánticas): "
            f"{repo.get('nameWithOwner')}"
        )
        return False
    
    @staticmethod
    def has_valid_language(
        repo: Dict[str, Any],
        valid_languages: List[str]
    ) -> bool:
        """
        Verifica que el lenguaje principal esté en la lista de lenguajes válidos.
        
        Args:
            repo: Repositorio a evaluar
            valid_languages: Lista de lenguajes válidos
            
        Returns:
            True si el lenguaje es válido, False si no lo es
        """
        if not valid_languages:
            return True
        
        primary_language = repo.get("primaryLanguage")
        
        if not primary_language:
            logger.debug(
                f"Repo rechazado (sin lenguaje principal): "
                f"{repo.get('nameWithOwner')}"
            )
            return False
        
        language_name = primary_language.get("name")
        
        if language_name not in valid_languages:
            logger.debug(
                f"Repo rechazado (lenguaje {language_name} no permitido): "
                f"{repo.get('nameWithOwner')}"
            )
            return False
        
        return True
    
    @staticmethod
    def is_not_archived(repo: Dict[str, Any]) -> bool:
        """
        Verifica que el repositorio no esté archivado.
        
        Args:
            repo: Repositorio a evaluar
            
        Returns:
            True si no está archivado, False si está archivado
        """
        is_archived = repo.get("isArchived", False)
        
        if is_archived:
            logger.debug(
                f"Repo rechazado (archivado): "
                f"{repo.get('nameWithOwner')}"
            )
            return False
        
        return True
    
    @staticmethod
    def has_minimum_stars(
        repo: Dict[str, Any],
        min_stars: int = 10
    ) -> bool:
        """
        Verifica que el repositorio tenga un número mínimo de estrellas.
        
        Args:
            repo: Repositorio a evaluar
            min_stars: Número mínimo de estrellas
            
        Returns:
            True si cumple el mínimo, False si no
        """
        stars = repo.get("stargazerCount", 0)
        
        if stars < min_stars:
            logger.debug(
                f"Repo rechazado (estrellas {stars} < {min_stars}): "
                f"{repo.get('nameWithOwner')}"
            )
            return False
        
        return True
    
    @staticmethod
    def has_community_engagement(
        repo: Dict[str, Any],
        min_watchers: int = 3,
        min_forks: int = 1
    ) -> bool:
        """
        Verifica que el repositorio tenga engagement de la comunidad.
        
        Criterios:
        - Al menos X watchers (por defecto 3)
        - Al menos Y forks (por defecto 1)
        
        Args:
            repo: Repositorio a evaluar
            min_watchers: Número mínimo de watchers
            min_forks: Número mínimo de forks
            
        Returns:
            True si tiene engagement, False si no
        """
        watchers = repo.get("watchers", {}).get("totalCount", 0)
        forks = repo.get("forkCount", 0)
        
        # Criterio flexible: cumplir al menos uno de los dos
        has_engagement = (watchers >= min_watchers) or (forks >= min_forks)
        
        if not has_engagement:
            logger.debug(
                f"Repo rechazado (bajo engagement - "
                f"{watchers} watchers < {min_watchers}, "
                f"{forks} forks < {min_forks}): "
                f"{repo.get('nameWithOwner')}"
            )
            return False
        
        return True


# Funciones helper para usar filtros individuales fácilmente

def filter_by_activity(
    repositories: List[Dict[str, Any]],
    max_inactivity_days: int = 365
) -> List[Dict[str, Any]]:
    """Filtra repositorios por actividad reciente."""
    return [
        repo for repo in repositories
        if RepositoryFilters.is_active(repo, max_inactivity_days)
    ]


def filter_by_fork_validity(
    repositories: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Filtra forks sin contribuciones propias."""
    return [
        repo for repo in repositories
        if RepositoryFilters.is_valid_fork(repo)
    ]


def filter_by_documentation(
    repositories: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Filtra repositorios sin descripción o README."""
    return [
        repo for repo in repositories
        if RepositoryFilters.has_description(repo)
    ]


def filter_by_project_size(
    repositories: List[Dict[str, Any]],
    min_commits: int = 10,
    min_size_kb: int = 10
) -> List[Dict[str, Any]]:
    """Filtra proyectos muy pequeños."""
    return [
        repo for repo in repositories
        if RepositoryFilters.is_minimal_project(repo, min_commits, min_size_kb)
    ]


def filter_by_keywords(
    repositories: List[Dict[str, Any]],
    keywords: List[str]
) -> List[Dict[str, Any]]:
    """Filtra repositorios sin keywords cuánticas."""
    return [
        repo for repo in repositories
        if RepositoryFilters.matches_keywords(repo, keywords)
    ]


def filter_by_language(
    repositories: List[Dict[str, Any]],
    valid_languages: List[str]
) -> List[Dict[str, Any]]:
    """Filtra repositorios por lenguaje."""
    return [
        repo for repo in repositories
        if RepositoryFilters.has_valid_language(repo, valid_languages)
    ]


def apply_all_filters(
    repositories: List[Dict[str, Any]],
    keywords: List[str],
    valid_languages: List[str],
    max_inactivity_days: int = 365,
    min_stars: int = 10,
    min_commits: int = 10,
    min_size_kb: int = 10
) -> List[Dict[str, Any]]:
    """
    Aplica todos los filtros en secuencia.
    
    Args:
        repositories: Lista de repositorios a filtrar
        keywords: Keywords cuánticas
        valid_languages: Lenguajes válidos
        max_inactivity_days: Días máximos de inactividad
        min_stars: Estrellas mínimas
        min_commits: Commits mínimos
        min_size_kb: Tamaño mínimo en KB
        
    Returns:
        Lista de repositorios que pasan todos los filtros
    """
    logger.info(f"Aplicando filtros avanzados a {len(repositories)} repositorios...")
    
    # Aplicar filtros en cascada
    filtered = repositories
    
    # 1. No archivados
    filtered = [r for r in filtered if RepositoryFilters.is_not_archived(r)]
    logger.info(f"  Después de filtro archivados: {len(filtered)}")
    
    # 2. Actividad reciente
    filtered = filter_by_activity(filtered, max_inactivity_days)
    logger.info(f"  Después de filtro actividad: {len(filtered)}")
    
    # 3. Forks válidos
    filtered = filter_by_fork_validity(filtered)
    logger.info(f"  Después de filtro forks: {len(filtered)}")
    
    # 4. Documentación
    filtered = filter_by_documentation(filtered)
    logger.info(f"  Después de filtro documentación: {len(filtered)}")
    
    # 5. Tamaño mínimo
    filtered = filter_by_project_size(filtered, min_commits, min_size_kb)
    logger.info(f"  Después de filtro tamaño: {len(filtered)}")
    
    # 6. Keywords
    filtered = filter_by_keywords(filtered, keywords)
    logger.info(f"  Después de filtro keywords: {len(filtered)}")
    
    # 7. Lenguaje
    filtered = filter_by_language(filtered, valid_languages)
    logger.info(f"  Después de filtro lenguaje: {len(filtered)}")
    
    # 8. Estrellas
    filtered = [r for r in filtered if RepositoryFilters.has_minimum_stars(r, min_stars)]
    logger.info(f"  Después de filtro estrellas: {len(filtered)}")
    
    logger.info(f"Filtrado completo: {len(filtered)}/{len(repositories)} repositorios válidos")
    
    return filtered
