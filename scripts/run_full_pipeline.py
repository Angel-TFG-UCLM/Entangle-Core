"""
Script maestro para ejecutar el pipeline completo de ingesta y enriquecimiento.

Ejecuta automáticamente sin confirmaciones:
1. Ingesta de Repositorios
2. Enriquecimiento de Repositorios
3. Ingesta de Usuarios
4. Enriquecimiento de Usuarios
5. Ingesta de Organizaciones
6. Enriquecimiento de Organizaciones

Muestra un resumen completo con tiempos y resultados de cada operación.
Diseñado para ejecutarse en background en Azure sin intervención humana.
"""

import sys
import os
import time
from datetime import datetime, timedelta
from typing import List
from dataclasses import dataclass

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from src.core.logger import logger
from src.core.config import Config, ingestion_config
from src.github.repositories_ingestion import IngestionEngine
from src.github.repositories_enrichment import EnrichmentEngine
from src.github.user_ingestion import run_user_ingestion
from src.github.user_enrichment import UserEnrichmentEngine
from src.github.organization_ingestion import OrganizationIngestionEngine
from src.github.organization_enrichment import OrganizationEnrichmentEngine
from src.github.graphql_client import GitHubGraphQLClient
from src.core.mongo_repository import MongoRepository
from src.core.db import get_database


@dataclass
class OperationResult:
    """Resultado de una operación del pipeline."""
    name: str
    success: bool
    duration: float
    start_time: datetime
    end_time: datetime
    records_processed: int = 0
    error_message: str = ""
    
    def duration_formatted(self) -> str:
        """Retorna la duración formateada."""
        hours, remainder = divmod(int(self.duration), 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"


def run_operation(name: str, func, *args, **kwargs) -> OperationResult:
    """
    Ejecuta una operación y registra su resultado.
    
    Args:
        name: Nombre de la operación
        func: Función a ejecutar
        *args, **kwargs: Argumentos para la función
        
    Returns:
        OperationResult con el resultado de la operación
    """
    logger.info("")
    logger.info("=" * 80)
    logger.info(f"EJECUTANDO: {name}")
    logger.info("=" * 80)
    logger.info("")
    
    start_time = datetime.now()
    success = False
    records_processed = 0
    error_message = ""
    
    try:
        result = func(*args, **kwargs)
        success = True
        
        # Extraer el número de registros procesados según el tipo de resultado
        if isinstance(result, dict):
            records_processed = (
                result.get('total', 0) or 
                result.get('total_processed', 0) or
                result.get('processed', 0) or
                result.get('total_organizations', 0) or
                result.get('total_users', 0) or
                result.get('enriched', 0) or
                result.get('new_organizations', 0) or
                result.get('new_users', 0) or
                0
            )
        elif isinstance(result, int):
            records_processed = result
            
        logger.info(f"✅ {name} completado exitosamente")
        if records_processed > 0:
            logger.info(f"   Registros procesados: {records_processed:,}")
        
    except Exception as e:
        success = False
        error_message = str(e)
        logger.error(f"❌ Error en {name}: {error_message}")
        logger.exception(e)
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    result_obj = OperationResult(
        name=name,
        success=success,
        duration=duration,
        start_time=start_time,
        end_time=end_time,
        records_processed=records_processed,
        error_message=error_message
    )
    
    logger.info(f"Duración: {result_obj.duration_formatted()}")
    logger.info("")
    
    return result_obj


def run_repositories_ingestion() -> dict:
    """Ejecuta la ingesta de repositorios."""
    logger.info("Validando configuración...")
    Config.validate()
    
    if not ingestion_config.enable_segmentation:
        logger.warning("⚠️  La segmentación no está habilitada en ingestion_config.json")
        return {'total': 0}
    
    logger.info("Iniciando ingesta de repositorios...")
    engine = IngestionEngine(incremental=False)
    stats = engine.run(max_results=None)
    
    return stats


def run_repositories_enrichment() -> dict:
    """Ejecuta el enriquecimiento de repositorios."""
    logger.info("Iniciando enriquecimiento de repositorios...")
    
    db = get_database()
    repo = MongoRepository(db, "repositories")
    github_token = os.getenv("GITHUB_TOKEN")
    
    engine = EnrichmentEngine(
        github_token=github_token,
        repos_repository=repo,
        batch_size=10
    )
    
    stats = engine.enrich_all_repositories(
        max_repos=None,
        force_reenrich=False
    )
    
    return stats


def run_users_ingestion_operation() -> dict:
    """Ejecuta la ingesta de usuarios."""
    logger.info("Iniciando ingesta de usuarios...")
    
    # run_user_ingestion ya está implementado como función
    stats = run_user_ingestion()
    
    return stats


def run_users_enrichment() -> dict:
    """Ejecuta el enriquecimiento de usuarios."""
    logger.info("Iniciando enriquecimiento de usuarios...")
    
    db = get_database()
    users_repo = MongoRepository(db, "users")
    repos_repo = MongoRepository(db, "repositories")
    github_token = os.getenv("GITHUB_TOKEN")
    
    client = GitHubGraphQLClient(github_token)
    engine = UserEnrichmentEngine(users_repo, repos_repo, client)
    
    stats = engine.run()
    
    return stats


def run_organizations_ingestion() -> dict:
    """Ejecuta la ingesta de organizaciones."""
    logger.info("Iniciando ingesta de organizaciones...")
    
    db = get_database()
    repos_repo = MongoRepository(db, "repositories")
    orgs_repo = MongoRepository(db, "organizations")
    github_token = os.getenv("GITHUB_TOKEN")
    
    client = GitHubGraphQLClient(github_token)
    engine = OrganizationIngestionEngine(repos_repo, orgs_repo, client)
    
    stats = engine.run()
    
    return stats


def run_organizations_enrichment() -> dict:
    """Ejecuta el enriquecimiento de organizaciones."""
    logger.info("Iniciando enriquecimiento de organizaciones...")
    
    db = get_database()
    repos_repo = MongoRepository(db, "repositories")
    orgs_repo = MongoRepository(db, "organizations")
    github_token = os.getenv("GITHUB_TOKEN")
    
    client = GitHubGraphQLClient(github_token)
    engine = OrganizationEnrichmentEngine(orgs_repo, repos_repo, client)
    
    stats = engine.run()
    
    return stats


def print_summary(results: List[OperationResult], total_start: datetime, total_end: datetime):
    """Imprime un resumen detallado de toda la ejecución."""
    total_duration = (total_end - total_start).total_seconds()
    hours, remainder = divmod(int(total_duration), 3600)
    minutes, seconds = divmod(remainder, 60)
    
    logger.info("")
    logger.info("=" * 80)
    logger.info("📊 RESUMEN COMPLETO DE EJECUCIÓN")
    logger.info("=" * 80)
    logger.info("")
    logger.info(f"Inicio:  {total_start.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Fin:     {total_end.strftime('%Y-%m-%d %H:%M:%S')}")
    
    if hours > 0:
        logger.info(f"Duración Total: {hours}h {minutes}m {seconds}s")
    elif minutes > 0:
        logger.info(f"Duración Total: {minutes}m {seconds}s")
    else:
        logger.info(f"Duración Total: {seconds}s")
    
    logger.info("")
    logger.info("-" * 80)
    logger.info("DETALLE POR OPERACIÓN")
    logger.info("-" * 80)
    logger.info("")
    
    # Tabla de resultados
    logger.info(f"{'Operación':<50} {'Estado':<12} {'Registros':<12} {'Duración':<15}")
    logger.info("-" * 80)
    
    successful = 0
    total_records = 0
    
    for result in results:
        status = "✅ ÉXITO" if result.success else "❌ ERROR"
        records = f"{result.records_processed:,}" if result.records_processed > 0 else "N/A"
        
        logger.info(
            f"{result.name:<50} {status:<12} {records:<12} {result.duration_formatted():<15}"
        )
        
        if result.success:
            successful += 1
            total_records += result.records_processed
        else:
            logger.info(f"   ⚠️  Error: {result.error_message}")
    
    logger.info("-" * 80)
    logger.info("")
    
    # Estadísticas generales
    logger.info("ESTADÍSTICAS GENERALES")
    logger.info("-" * 80)
    logger.info(f"Total de operaciones: {len(results)}")
    logger.info(f"Operaciones exitosas: {successful}")
    logger.info(f"Operaciones fallidas: {len(results) - successful}")
    logger.info(f"Total de registros procesados: {total_records:,}")
    logger.info("")
    
    # Estado final
    if successful == len(results):
        logger.info("🎉 PIPELINE COMPLETADO EXITOSAMENTE 🎉")
    elif successful > 0:
        logger.info("⚠️  PIPELINE COMPLETADO CON ERRORES ⚠️")
    else:
        logger.info("❌ PIPELINE FALLÓ COMPLETAMENTE ❌")
    
    logger.info("=" * 80)
    logger.info("")


def main():
    """Punto de entrada principal."""
    try:
        # Cargar variables de entorno
        load_dotenv()
        
        # Validar token de GitHub
        github_token = os.getenv("GITHUB_TOKEN")
        if not github_token:
            logger.error("❌ GITHUB_TOKEN no configurado en .env")
            sys.exit(1)
        
        # Inicio del pipeline
        total_start = datetime.now()
        
        logger.info("🚀" * 40)
        logger.info("INICIANDO PIPELINE COMPLETO DE INGESTA Y ENRIQUECIMIENTO")
        logger.info(f"Inicio: {total_start.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("Modo: AUTOMÁTICO (sin confirmaciones)")
        logger.info("🚀" * 40)
        
        # Lista de operaciones a ejecutar
        operations = [
            ("1. Ingesta de Repositorios", run_repositories_ingestion),
            ("2. Enriquecimiento de Repositorios", run_repositories_enrichment),
            ("3. Ingesta de Usuarios", run_users_ingestion_operation),
            ("4. Enriquecimiento de Usuarios", run_users_enrichment),
            ("5. Ingesta de Organizaciones", run_organizations_ingestion),
            ("6. Enriquecimiento de Organizaciones", run_organizations_enrichment),
        ]
        
        # Ejecutar cada operación
        results = []
        
        for operation_name, operation_func in operations:
            result = run_operation(operation_name, operation_func)
            results.append(result)
            
            # Continuar con la siguiente operación aunque falle
            if not result.success:
                logger.warning(f"⚠️  Continuando con la siguiente operación a pesar del error...")
        
        # Fin del pipeline
        total_end = datetime.now()
        
        # Mostrar resumen
        print_summary(results, total_start, total_end)
        
        # Retornar código de salida según el éxito
        successful = sum(1 for r in results if r.success)
        if successful == len(results):
            sys.exit(0)  # Éxito total
        elif successful > 0:
            sys.exit(1)  # Éxito parcial
        else:
            sys.exit(2)  # Fallo total
            
    except KeyboardInterrupt:
        logger.warning("\n⚠️  Pipeline interrumpido por el usuario")
        sys.exit(130)
    except Exception as e:
        logger.error(f"❌ Error fatal en el pipeline: {e}")
        logger.exception(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
