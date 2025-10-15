"""
Motor de ingesta de repositorios de GitHub.

Este módulo implementa el flujo completo de ingesta:
1. Búsqueda de repositorios usando criterios configurables
2. Filtrado por criterios de calidad
3. Almacenamiento en MongoDB y/o archivos locales
"""

import json
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from pathlib import Path

from .graphql_client import GitHubGraphQLClient
from ..core.config import IngestionConfig, ingestion_config
from ..core.logger import logger
from ..core.db import Database


class IngestionEngine:
    """
    Motor central de ingesta de repositorios de software cuántico.
    
    Orquesta el flujo completo:
    - Búsqueda con GitHubGraphQLClient
    - Filtrado según criterios de calidad
    - Almacenamiento de resultados
    """
    
    def __init__(
        self,
        client: Optional[GitHubGraphQLClient] = None,
        config: Optional[IngestionConfig] = None,
        db: Optional[Database] = None
    ):
        """
        Inicializa el motor de ingesta.
        
        Args:
            client: Cliente GraphQL de GitHub (crea uno nuevo si es None)
            config: Configuración de ingesta (usa global si es None)
            db: Instancia de base de datos (crea una nueva si es None)
        """
        self.client = client or GitHubGraphQLClient()
        self.config = config or ingestion_config
        self.db = db or Database()
        
        # Estadísticas de la ingesta
        self.stats = {
            "total_found": 0,
            "total_filtered": 0,
            "filtered_by_fork": 0,
            "filtered_by_stars": 0,
            "filtered_by_language": 0,
            "filtered_by_inactivity": 0,
            "filtered_by_keywords": 0,
            "total_saved": 0,
            "start_time": None,
            "end_time": None
        }
        
        logger.info("Motor de ingesta inicializado correctamente")
    
    def run(
        self,
        max_results: Optional[int] = None,
        save_to_db: bool = True,
        save_to_json: bool = True,
        output_file: str = "ingestion_results.json"
    ) -> Dict[str, Any]:
        """
        Ejecuta el flujo completo de ingesta.
        
        Args:
            max_results: Número máximo de repositorios a obtener (None = todos)
            save_to_db: Si se deben guardar los resultados en MongoDB
            save_to_json: Si se deben guardar los resultados en JSON
            output_file: Nombre del archivo JSON de salida
            
        Returns:
            Diccionario con resultados y estadísticas
        """
        logger.info("=" * 80)
        logger.info("INICIANDO PROCESO DE INGESTA")
        logger.info("=" * 80)
        
        self.stats["start_time"] = datetime.now(timezone.utc)
        
        try:
            # 1. Buscar repositorios
            logger.info("Fase 1: Búsqueda de repositorios")
            repositories = self._search_repositories(max_results)
            self.stats["total_found"] = len(repositories)
            
            logger.info(f"✓ Repositorios encontrados: {len(repositories)}")
            
            # 2. Filtrar repositorios
            logger.info("\nFase 2: Filtrado de repositorios")
            filtered_repos = self.filter_repositories(repositories)
            self.stats["total_filtered"] = len(filtered_repos)
            
            logger.info(f"✓ Repositorios después de filtrado: {len(filtered_repos)}")
            
            # 3. Guardar resultados
            logger.info("\nFase 3: Almacenamiento de resultados")
            self.save_results(
                filtered_repos,
                save_to_db=save_to_db,
                save_to_json=save_to_json,
                output_file=output_file
            )
            
            self.stats["end_time"] = datetime.now(timezone.utc)
            
            # 4. Generar reporte
            report = self._generate_report(filtered_repos)
            
            logger.info("=" * 80)
            logger.info("PROCESO DE INGESTA COMPLETADO EXITOSAMENTE")
            logger.info("=" * 80)
            
            return report
            
        except Exception as e:
            logger.error(f"Error durante el proceso de ingesta: {e}", exc_info=True)
            raise
    
    def _search_repositories(self, max_results: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Busca repositorios usando el cliente GraphQL.
        
        Args:
            max_results: Número máximo de repositorios a obtener
            
        Returns:
            Lista de repositorios encontrados
        """
        logger.info("Ejecutando búsqueda en GitHub...")
        
        try:
            # Búsqueda con paginación automática
            result = self.client.search_repositories_all_pages(
                config_criteria=self.config,
                max_results=max_results
            )
            
            logger.info(f"Búsqueda completada: {len(result)} repositorios obtenidos")
            return result
            
        except Exception as e:
            logger.error(f"Error en la búsqueda de repositorios: {e}")
            raise
    
    def filter_repositories(self, repositories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Aplica todos los filtros de calidad a los repositorios.
        
        Args:
            repositories: Lista de repositorios a filtrar
            
        Returns:
            Lista de repositorios que pasan todos los filtros
        """
        logger.info(f"Aplicando filtros a {len(repositories)} repositorios...")
        
        filtered = []
        
        for repo in repositories:
            # Aplicar cada filtro
            if not self._filter_by_fork(repo):
                self.stats["filtered_by_fork"] += 1
                continue
            
            if not self._filter_by_stars(repo):
                self.stats["filtered_by_stars"] += 1
                continue
            
            if not self._filter_by_language(repo):
                self.stats["filtered_by_language"] += 1
                continue
            
            if not self._filter_by_inactivity(repo):
                self.stats["filtered_by_inactivity"] += 1
                continue
            
            if not self._filter_by_keywords(repo):
                self.stats["filtered_by_keywords"] += 1
                continue
            
            # Si pasa todos los filtros, agregarlo
            filtered.append(repo)
        
        logger.info(f"Filtrado completado: {len(filtered)} repositorios válidos")
        logger.info(f"  - Rechazados por ser fork: {self.stats['filtered_by_fork']}")
        logger.info(f"  - Rechazados por estrellas: {self.stats['filtered_by_stars']}")
        logger.info(f"  - Rechazados por lenguaje: {self.stats['filtered_by_language']}")
        logger.info(f"  - Rechazados por inactividad: {self.stats['filtered_by_inactivity']}")
        logger.info(f"  - Rechazados por keywords: {self.stats['filtered_by_keywords']}")
        
        return filtered
    
    def _filter_by_fork(self, repo: Dict[str, Any]) -> bool:
        """
        Filtra por fork.
        
        Args:
            repo: Repositorio a evaluar
            
        Returns:
            True si pasa el filtro, False si debe ser rechazado
        """
        if not self.config.exclude_forks:
            return True
        
        is_fork = repo.get("isFork", False)
        
        if is_fork:
            logger.debug(f"Repo rechazado (fork): {repo.get('nameWithOwner')}")
            return False
        
        return True
    
    def _filter_by_stars(self, repo: Dict[str, Any]) -> bool:
        """
        Filtra por número de estrellas.
        
        Args:
            repo: Repositorio a evaluar
            
        Returns:
            True si pasa el filtro, False si debe ser rechazado
        """
        stars = repo.get("stargazerCount", 0)
        min_stars = self.config.min_stars
        
        if stars < min_stars:
            logger.debug(
                f"Repo rechazado (stars {stars} < {min_stars}): "
                f"{repo.get('nameWithOwner')}"
            )
            return False
        
        return True
    
    def _filter_by_language(self, repo: Dict[str, Any]) -> bool:
        """
        Filtra por lenguaje de programación.
        
        Args:
            repo: Repositorio a evaluar
            
        Returns:
            True si pasa el filtro, False si debe ser rechazado
        """
        if not self.config.languages:
            return True
        
        primary_language = repo.get("primaryLanguage")
        
        if not primary_language:
            logger.debug(f"Repo sin lenguaje principal: {repo.get('nameWithOwner')}")
            return False
        
        language_name = primary_language.get("name")
        
        if language_name not in self.config.languages:
            logger.debug(
                f"Repo rechazado (lenguaje {language_name} no permitido): "
                f"{repo.get('nameWithOwner')}"
            )
            return False
        
        return True
    
    def _filter_by_inactivity(self, repo: Dict[str, Any]) -> bool:
        """
        Filtra por inactividad (última actualización).
        
        Args:
            repo: Repositorio a evaluar
            
        Returns:
            True si pasa el filtro, False si debe ser rechazado
        """
        updated_at_str = repo.get("updatedAt")
        
        if not updated_at_str:
            logger.debug(f"Repo sin fecha de actualización: {repo.get('nameWithOwner')}")
            return False
        
        # Convertir fecha
        updated_at = datetime.fromisoformat(updated_at_str.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        
        # Calcular días de inactividad
        inactivity_days = (now - updated_at).days
        max_inactivity = self.config.max_inactivity_days
        
        if inactivity_days > max_inactivity:
            logger.debug(
                f"Repo rechazado (inactivo {inactivity_days} días > {max_inactivity}): "
                f"{repo.get('nameWithOwner')}"
            )
            return False
        
        return True
    
    def _filter_by_keywords(self, repo: Dict[str, Any]) -> bool:
        """
        Filtra por presencia de keywords en nombre o descripción.
        
        Args:
            repo: Repositorio a evaluar
            
        Returns:
            True si pasa el filtro, False si debe ser rechazado
        """
        if not self.config.keywords:
            return True
        
        # Obtener textos donde buscar
        name = repo.get("name", "").lower()
        description = repo.get("description", "") or ""
        description = description.lower()
        
        # Combinar nombre y descripción
        searchable_text = f"{name} {description}"
        
        # Verificar si alguna keyword está presente
        for keyword in self.config.keywords:
            if keyword.lower() in searchable_text:
                return True
        
        # También verificar en topics si existen
        topics = repo.get("repositoryTopics", {}).get("nodes", [])
        for topic_node in topics:
            topic_name = topic_node.get("topic", {}).get("name", "").lower()
            for keyword in self.config.keywords:
                if keyword.lower() in topic_name:
                    return True
        
        logger.debug(
            f"Repo rechazado (sin keywords cuánticas): "
            f"{repo.get('nameWithOwner')}"
        )
        return False
    
    def save_results(
        self,
        repositories: List[Dict[str, Any]],
        save_to_db: bool = True,
        save_to_json: bool = True,
        output_file: str = "ingestion_results.json"
    ):
        """
        Guarda los resultados en MongoDB y/o archivo JSON.
        
        Args:
            repositories: Lista de repositorios a guardar
            save_to_db: Si se deben guardar en MongoDB
            save_to_json: Si se deben guardar en JSON
            output_file: Nombre del archivo JSON
        """
        saved_count = 0
        
        # Guardar en MongoDB
        if save_to_db:
            try:
                logger.info("Guardando repositorios en MongoDB...")
                self.db.connect()
                collection = self.db.get_collection("repositories")
                
                for repo in repositories:
                    # Agregar metadata de ingesta
                    repo["ingestion_date"] = datetime.now(timezone.utc).isoformat()
                    repo["ingestion_version"] = self.config.version
                    
                    # Upsert (actualizar o insertar)
                    collection.update_one(
                        {"id": repo["id"]},
                        {"$set": repo},
                        upsert=True
                    )
                    saved_count += 1
                
                self.db.disconnect()
                logger.info(f"✓ {saved_count} repositorios guardados en MongoDB")
                
            except Exception as e:
                logger.error(f"Error al guardar en MongoDB: {e}")
                logger.warning("Continuando con guardado en JSON...")
        
        # Guardar en JSON
        if save_to_json:
            try:
                logger.info(f"Guardando repositorios en {output_file}...")
                
                # Crear directorio si no existe
                output_path = Path(output_file)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Guardar con metadata
                output_data = {
                    "metadata": {
                        "ingestion_date": datetime.now(timezone.utc).isoformat(),
                        "total_repositories": len(repositories),
                        "config_version": self.config.version,
                        "criteria": {
                            "keywords": self.config.keywords,
                            "languages": self.config.languages,
                            "min_stars": self.config.min_stars,
                            "max_inactivity_days": self.config.max_inactivity_days,
                            "exclude_forks": self.config.exclude_forks
                        }
                    },
                    "repositories": repositories
                }
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(output_data, f, indent=2, ensure_ascii=False, default=str)
                
                logger.info(f"✓ {len(repositories)} repositorios guardados en {output_file}")
                
            except Exception as e:
                logger.error(f"Error al guardar en JSON: {e}")
        
        self.stats["total_saved"] = saved_count if save_to_db else len(repositories)
    
    def _generate_report(self, repositories: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Genera un reporte completo del proceso de ingesta.
        
        Args:
            repositories: Lista de repositorios procesados
            
        Returns:
            Diccionario con el reporte completo
        """
        duration = None
        if self.stats["start_time"] and self.stats["end_time"]:
            duration = (self.stats["end_time"] - self.stats["start_time"]).total_seconds()
        
        # Estadísticas por lenguaje
        language_stats = {}
        for repo in repositories:
            lang = repo.get("primaryLanguage", {}).get("name", "Unknown")
            language_stats[lang] = language_stats.get(lang, 0) + 1
        
        # Estadísticas de estrellas
        star_counts = [repo.get("stargazerCount", 0) for repo in repositories]
        avg_stars = sum(star_counts) / len(star_counts) if star_counts else 0
        
        report = {
            "summary": {
                "total_found": self.stats["total_found"],
                "total_filtered": self.stats["total_filtered"],
                "total_saved": self.stats["total_saved"],
                "success_rate": f"{(self.stats['total_filtered'] / self.stats['total_found'] * 100):.1f}%" if self.stats["total_found"] > 0 else "0%",
                "duration_seconds": duration
            },
            "filtering": {
                "rejected_by_fork": self.stats["filtered_by_fork"],
                "rejected_by_stars": self.stats["filtered_by_stars"],
                "rejected_by_language": self.stats["filtered_by_language"],
                "rejected_by_inactivity": self.stats["filtered_by_inactivity"],
                "rejected_by_keywords": self.stats["filtered_by_keywords"]
            },
            "statistics": {
                "languages": language_stats,
                "average_stars": round(avg_stars, 1),
                "max_stars": max(star_counts) if star_counts else 0,
                "min_stars": min(star_counts) if star_counts else 0
            },
            "repositories": repositories
        }
        
        # Log del reporte
        logger.info("\n" + "=" * 80)
        logger.info("REPORTE DE INGESTA")
        logger.info("=" * 80)
        logger.info(f"Repositorios encontrados: {report['summary']['total_found']}")
        logger.info(f"Repositorios válidos: {report['summary']['total_filtered']}")
        logger.info(f"Tasa de éxito: {report['summary']['success_rate']}")
        logger.info(f"Duración: {duration:.1f}s" if duration else "N/A")
        logger.info(f"\nDistribución por lenguaje:")
        for lang, count in sorted(language_stats.items(), key=lambda x: x[1], reverse=True):
            logger.info(f"  - {lang}: {count}")
        logger.info("=" * 80)
        
        return report


# Función helper para ejecutar ingesta rápida
def run_ingestion(
    max_results: Optional[int] = None,
    save_to_db: bool = True,
    save_to_json: bool = True,
    output_file: str = "ingestion_results.json"
) -> Dict[str, Any]:
    """
    Ejecuta una ingesta completa con configuración por defecto.
    
    Args:
        max_results: Número máximo de repositorios
        save_to_db: Guardar en MongoDB
        save_to_json: Guardar en JSON
        output_file: Archivo de salida
        
    Returns:
        Reporte de la ingesta
    """
    engine = IngestionEngine()
    return engine.run(
        max_results=max_results,
        save_to_db=save_to_db,
        save_to_json=save_to_json,
        output_file=output_file
    )
