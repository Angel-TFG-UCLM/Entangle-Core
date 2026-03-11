"""
Motor de ingesta de repositorios de GitHub.

Este módulo implementa el flujo completo de ingesta:
1. Búsqueda de repositorios usando criterios configurables
2. Filtrado por criterios de calidad
3. Validación con modelos Pydantic
4. Almacenamiento en MongoDB usando MongoRepository
5. Soporte para reingestas incrementales y desde cero

Modos de ingesta:
- incremental: Solo busca repos nuevos/actualizados desde la última ingesta.
  Usa el filtro `pushed:>DATE` en GitHub Search para reducir llamadas API.
- from_scratch: Limpia la colección y reingesta todo desde cero.
  Elimina datos "zombi" que ya no pasan los filtros actuales.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from pydantic import ValidationError
from pymongo.errors import OperationFailure

from .graphql_client import GitHubGraphQLClient
from .filters import RepositoryFilters
from ..core.config import IngestionConfig, ingestion_config
from ..core.logger import logger
from ..core.db import db, get_database
from ..core.mongo_repository import MongoRepository
from ..models import Repository, Organization, User  # , Relation  # DESHABILITADO: Para futura implementación de análisis de grafos


class IngestionEngine:
    """
    Motor central de ingesta de datos de GitHub con persistencia MongoDB.
    
    Orquesta el flujo completo:
    - Búsqueda con GitHubGraphQLClient
    - Filtrado según criterios de calidad
    - Validación con modelos Pydantic
    - Almacenamiento con MongoRepository
    - Soporte para reingestas incrementales
    """
    
    def __init__(
        self,
        client: Optional[GitHubGraphQLClient] = None,
        config: Optional[IngestionConfig] = None,
        incremental: bool = False,
        from_scratch: bool = False,
        batch_size: int = 500,  # ✅ OPTIMIZADO para vCore: batch masivo
        max_workers: int = 4,  # Workers para búsquedas paralelas de segmentos
        progress_callback=None,
        cancel_event=None
    ):
        """
        Inicializa el motor de ingesta.
        
        Args:
            client: Cliente GraphQL de GitHub (crea uno nuevo si es None)
            config: Configuración de ingesta (usa global si es None)
            incremental: Si True, solo busca repos nuevos/actualizados desde última ingesta
            from_scratch: Si True, limpia la colección antes de ingestar (elimina datos zombi)
            batch_size: Tamaño de lote para operaciones bulk
            max_workers: Número de workers para búsquedas paralelas (1-8)
            progress_callback: Callback opcional fn(items_processed, items_total, message)
        """
        self.client = client or GitHubGraphQLClient()
        self.config = config or ingestion_config
        self.incremental = incremental
        self.from_scratch = from_scratch
        self.batch_size = batch_size
        self.max_workers = max(1, min(8, max_workers))  # Clamp 1-8
        self.progress_callback = progress_callback
        self.cancel_event = cancel_event
        
        # Conectar a MongoDB
        if not db.is_connected():
            db.connect()
        
        # Crear repositorios MongoDB para cada colección
        self.repo_db = MongoRepository("repositories", unique_fields=["id"])
        self.org_db = MongoRepository("organizations", unique_fields=["id"])
        self.user_db = MongoRepository("users", unique_fields=["id"])
        # self.relation_db = MongoRepository("relations", unique_fields=["source_id", "target_id", "relation_type"])  # DESHABILITADO: Para futura implementación de análisis de grafos
        
        # Estadísticas de la ingesta (ampliadas con nuevos filtros y persistencia)
        self.stats = {
            # Extracción
            "total_found": 0,
            "total_filtered": 0,
            
            # Modo
            "mode": "from_scratch" if from_scratch else ("incremental" if incremental else "full"),
            "deleted_before_ingestion": 0,
            "skipped_unchanged": 0,
            
            # Filtrado
            "filtered_by_archived": 0,
            "filtered_by_blacklist": 0,
            "filtered_by_relevance": 0,
            "filtered_by_fork": 0,
            "filtered_by_stars": 0,
            "filtered_by_language": 0,
            "filtered_by_inactivity": 0,
            "filtered_by_keywords": 0,
            "filtered_by_no_description": 0,
            "filtered_by_minimal_project": 0,
            "filtered_by_community_engagement": 0,
            
            # Validación
            "validation_errors": 0,
            "validation_success": 0,
            
            # Persistencia
            "repositories_inserted": 0,
            "repositories_updated": 0,
            "organizations_inserted": 0,
            "organizations_updated": 0,
            "users_inserted": 0,
            "users_updated": 0,
            # "relations_created": 0,  # DESHABILITADO: Para futura implementación de análisis de grafos
            
            # Tiempos
            "time_extraction": 0.0,
            "time_filtering": 0.0,
            "time_validation": 0.0,
            "time_persistence": 0.0,
            
            "start_time": None,
            "end_time": None
        }
        
        mode_label = "DESDE CERO" if from_scratch else ("INCREMENTAL" if incremental else "COMPLETO")
        logger.info(f"Motor de ingesta inicializado (modo={mode_label}, batch_size={batch_size}, workers={self.max_workers})")
    
    def _sanitize_repo_data(self, repo_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Crea una copia saneada del repositorio para logs/errores.
        Trunca campos largos como el README para evitar logs excesivos.
        """
        try:
            # Hacer una copia superficial es suficiente para el nivel superior
            # pero necesitamos profundizar para 'object.text'
            sanitized = repo_data.copy()
            
            # Truncar README si existe
            if "object" in sanitized and isinstance(sanitized["object"], dict):
                obj = sanitized["object"].copy()
                if "text" in obj and isinstance(obj["text"], str):
                    text = obj["text"]
                    if len(text) > 500:
                        obj["text"] = text[:500] + "... [TRUNCATED FOR LOGS]"
                sanitized["object"] = obj
            
            return sanitized
        except Exception:
            return {"error": "Could not sanitize data"}
    
    # DEPRECATED: Ya no necesario con Azure Cosmos DB for MongoDB (vCore)
    # vCore es MongoDB nativo sin throttling code 16500
    def _retry_on_cosmos_throttle(self, operation, max_retries: int = 5):
        """
        DEPRECATED: Método legacy de Cosmos DB RU-based.
        vCore no tiene throttling code 16500.
        Se mantiene por compatibilidad pero ahora solo ejecuta la operación directamente.
        
        Args:
            operation: Función a ejecutar
            max_retries: IGNORADO en vCore
            
        Returns:
            Resultado de la operación
        """
        try:
            return operation()
        except Exception as e:
            logger.error(f"❌ Error en operación: {e}")
            raise
    
    def _cleanup_collection(self) -> None:
        """
        Limpia la colección de repositorios antes de una ingesta desde cero.
        Elimina todos los documentos para garantizar que no queden datos zombi.
        También limpia la metadata de última ingesta.
        """
        logger.info("\n🗑️  FASE 0: LIMPIEZA (Modo desde cero)")
        
        try:
            count_before = self.repo_db.count_documents()
            logger.info(f"  📊 Repositorios actuales en DB: {count_before}")
            
            if count_before > 0:
                deleted = self.repo_db.delete_many({})
                self.stats["deleted_before_ingestion"] = deleted
                logger.info(f"  🗑️  Eliminados {deleted} repositorios de la colección")
            
            # Limpiar metadata de última ingesta
            try:
                from ..core.db import get_database
                metadata_collection = get_database()["ingestion_metadata"]
                metadata_collection.delete_one({"type": "repositories_last_ingestion"})
                logger.info("  🗑️  Metadata de última ingesta eliminada")
            except Exception:
                pass
            
            logger.info("  ✅ Limpieza completada")
            
        except Exception as e:
            logger.error(f"  ❌ Error durante limpieza: {e}")
            raise
    
    def _get_last_ingestion_date(self) -> Optional[datetime]:
        """
        Obtiene la fecha de la última ingesta exitosa desde metadata en MongoDB.
        
        Returns:
            datetime de la última ingesta o None si no existe
        """
        try:
            from ..core.db import get_database
            metadata_collection = get_database()["ingestion_metadata"]
            doc = metadata_collection.find_one({"type": "repositories_last_ingestion"})
            if doc and "date" in doc:
                return doc["date"]
        except Exception as e:
            logger.debug(f"No se pudo obtener fecha de última ingesta: {e}")
        return None
    
    def _save_ingestion_date(self) -> None:
        """Guarda la fecha actual como última ingesta exitosa."""
        try:
            from ..core.db import get_database
            metadata_collection = get_database()["ingestion_metadata"]
            metadata_collection.update_one(
                {"type": "repositories_last_ingestion"},
                {"$set": {
                    "type": "repositories_last_ingestion",
                    "date": datetime.now(timezone.utc),
                    "stats": {
                        "total_found": self.stats["total_found"],
                        "total_filtered": self.stats["total_filtered"],
                        "repositories_inserted": self.stats["repositories_inserted"],
                        "repositories_updated": self.stats["repositories_updated"]
                    }
                }},
                upsert=True
            )
            logger.info("📅 Fecha de ingesta guardada en metadata")
        except Exception as e:
            logger.warning(f"⚠️  No se pudo guardar fecha de ingesta: {e}")
    
    def run(
        self,
        max_results: Optional[int] = None,
        save_to_json: bool = True,
        output_file: str = "ingestion_results.json"
    ) -> Dict[str, Any]:
        """
        Ejecuta el flujo completo de ingesta con validación y persistencia.
        
        Flujo:
        0. Limpieza (solo en modo from_scratch)
        1. Extracción → Búsqueda de repositorios
        2. Filtrado → Aplicar criterios de calidad
        3. Validación → Parsear y validar con Pydantic
        4. Persistencia → Guardar en MongoDB (bulk operations)
        
        Args:
            max_results: Número máximo de repositorios a obtener (None = todos)
            save_to_json: Si se deben guardar los resultados en JSON
            output_file: Nombre del archivo JSON de salida
            
        Returns:
            Diccionario con resultados y estadísticas completas
        """
        logger.info("=" * 80)
        logger.info("🚀 INICIANDO PROCESO DE INGESTA")
        logger.info("=" * 80)
        mode_label = "DESDE CERO" if self.from_scratch else ("INCREMENTAL" if self.incremental else "COMPLETO")
        logger.info(f"Modo: {mode_label}")
        logger.info(f"Tamaño de lote: {self.batch_size}")
        logger.info(f"Workers paralelos: {self.max_workers}")
        
        self.stats["start_time"] = datetime.now(timezone.utc)
        
        try:
            # ==================== FASE 0: LIMPIEZA (SOLO FROM_SCRATCH) ====================
            if self.from_scratch:
                self._cleanup_collection()
            
            # ==================== FASE 1: EXTRACCIÓN ====================
            start_extraction = time.time()
            logger.info("\n📥 FASE 1: Extracción de Repositorios")
            if self.progress_callback:
                try:
                    self.progress_callback(0, 4, "Fase 1/4: Extrayendo repositorios...")
                except Exception:
                    pass
            repositories_raw = self._search_repositories(max_results)
            self.stats["total_found"] = len(repositories_raw)
            self.stats["time_extraction"] = time.time() - start_extraction
            
            logger.info(f"✅ {len(repositories_raw)} repositorios extraídos en {self.stats['time_extraction']:.2f}s")
            
            if self.cancel_event and self.cancel_event.is_set():
                self.stats["end_time"] = datetime.now(timezone.utc)
                return self.stats
            
            # ==================== FASE 2: FILTRADO ====================
            start_filtering = time.time()
            logger.info("\n🔍 FASE 2: Filtrado de Calidad")
            if self.progress_callback:
                try:
                    self.progress_callback(1, 4, f"Fase 2/4: Filtrando {len(repositories_raw)} repos...")
                except Exception:
                    pass
            filtered_repos_raw = self.filter_repositories(repositories_raw)
            self.stats["total_filtered"] = len(filtered_repos_raw)
            self.stats["time_filtering"] = time.time() - start_filtering
            
            logger.info(f"✅ {len(filtered_repos_raw)} repositorios válidos en {self.stats['time_filtering']:.2f}s")
            
            if self.cancel_event and self.cancel_event.is_set():
                self.stats["end_time"] = datetime.now(timezone.utc)
                return self.stats
            
            # ==================== FASE 3: VALIDACIÓN ====================
            start_validation = time.time()
            logger.info("\n✔️  FASE 3: Validación con Modelos Pydantic")
            if self.progress_callback:
                try:
                    self.progress_callback(2, 4, f"Fase 3/4: Validando {len(filtered_repos_raw)} repos...")
                except Exception:
                    pass
            validated_repos, validation_errors = self._validate_repositories(filtered_repos_raw)
            self.stats["validation_success"] = len(validated_repos)
            self.stats["validation_errors"] = len(validation_errors)
            self.stats["time_validation"] = time.time() - start_validation
            
            logger.info(f"✅ {len(validated_repos)} repositorios validados en {self.stats['time_validation']:.2f}s")
            if validation_errors:
                logger.warning(f"⚠️  {len(validation_errors)} errores de validación")
            
            if self.cancel_event and self.cancel_event.is_set():
                self.stats["end_time"] = datetime.now(timezone.utc)
                return self.stats
            
            # ==================== FASE 4: PERSISTENCIA ====================
            start_persistence = time.time()
            logger.info("\n💾 FASE 4: Persistencia en MongoDB")
            if self.progress_callback:
                try:
                    self.progress_callback(3, 4, f"Fase 4/4: Guardando {len(validated_repos)} repos en BD...")
                except Exception:
                    pass
            self._persist_repositories(validated_repos)
            self.stats["time_persistence"] = time.time() - start_persistence
            
            logger.info(f"✅ Persistencia completada en {self.stats['time_persistence']:.2f}s")
            
            # ==================== FASE 5: RELACIONES ====================
            # DESHABILITADO: Preservado para futura implementación de análisis de grafos
            # logger.info("\n🔗 FASE 5: Creación de Relaciones")
            # self._create_relations(validated_repos)
            # 
            # logger.info(f"✅ {self.stats['relations_created']} relaciones creadas")
            
            # ==================== GUARDAR JSON (OPCIONAL) ====================
            if save_to_json:
                logger.info(f"\n📄 Guardando resultados en {output_file}...")
                self._save_to_json(validated_repos, output_file)
            
            self.stats["end_time"] = datetime.now(timezone.utc)
            
            # Guardar fecha de ingesta para modo incremental futuro
            self._save_ingestion_date()
            
            # ==================== REPORTE FINAL ====================
            report = self._generate_report(validated_repos, validation_errors)
            
            logger.info("\n" + "=" * 80)
            logger.info("✅ PROCESO DE INGESTA COMPLETADO EXITOSAMENTE")
            logger.info("=" * 80)
            
            return report
            
        except Exception as e:
            logger.error(f"❌ Error durante el proceso de ingesta: {e}", exc_info=True)
            raise
    
    def _report_progress(self, processed: int, total: int, message: str):
        """Wrapper para reportar progreso de forma segura."""
        if self.progress_callback:
            try:
                self.progress_callback(processed, total, message)
            except Exception:
                pass

    def _search_repositories(self, max_results: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Busca repositorios usando el cliente GraphQL.
        En modo incremental, filtra por fecha de última ingesta para reducir consultas.
        Si la segmentación está habilitada, ejecuta búsquedas segmentadas (con paralelismo).
        
        Args:
            max_results: Número máximo de repositorios a obtener
            
        Returns:
            Lista de repositorios encontrados (datos raw de GraphQL)
        """
        logger.info("🔎 Ejecutando búsqueda en GitHub...")
        
        # En modo incremental, obtener fecha de última ingesta
        incremental_since = None
        if self.incremental:
            incremental_since = self._get_last_ingestion_date()
            if incremental_since:
                logger.info(f"📅 Modo incremental: buscando repos actualizados desde {incremental_since.strftime('%Y-%m-%d')}")
            else:
                logger.info("📅 Modo incremental: sin fecha previa, búsqueda completa")
        
        try:
            # Verificar si está habilitada la segmentación
            if self.config.enable_segmentation and self.config.segmentation:
                logger.info("📊 Modo de segmentación dinámica activado")
                return self._search_with_segmentation(max_results, incremental_since)
            else:
                # Búsqueda tradicional con paginación automática
                result = self.client.search_repositories_all_pages(
                    config_criteria=self.config,
                    max_results=max_results
                )
                
                logger.debug(f"Búsqueda completada: {len(result)} repositorios obtenidos")
                return result
            
        except Exception as e:
            logger.error(f"❌ Error en la búsqueda de repositorios: {e}")
            raise
    
    def _search_with_segmentation(
        self,
        max_results: Optional[int] = None,
        incremental_since: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Ejecuta búsquedas segmentadas por rangos de estrellas y años de creación
        para superar el límite de 1000 resultados de GitHub Search API.
        
        Usa ThreadPoolExecutor para ejecutar segmentos en paralelo (respetando
        rate limits de GitHub con check proactivo).
        
        En modo incremental, añade filtro `pushed:>DATE` para solo obtener repos
        actualizados desde la última ingesta, reduciendo drásticamente las llamadas API.
        
        Args:
            max_results: Número máximo total de repositorios a obtener
            incremental_since: Fecha desde la cual buscar repos actualizados (modo incremental)
            
        Returns:
            Lista combinada de repositorios de todos los segmentos
        """
        segmentation = self.config.segmentation
        star_ranges = segmentation.get("stars", [])
        created_years = segmentation.get("created_years", [])
        
        # Obtener keywords de búsqueda (cada una genera su propio set de segmentos)
        search_keywords = self.config.search_keywords
        
        logger.info(f"🎯 Segmentación configurada:")
        logger.info(f"  • Keywords de búsqueda: {search_keywords}")
        logger.info(f"  • Rangos de estrellas: {len(star_ranges)}")
        logger.info(f"  • Años de creación: {len(created_years)}")
        
        total_combinations = len(star_ranges) * len(created_years) * len(search_keywords)
        logger.info(f"  • Total de consultas a ejecutar: {total_combinations}")
        
        if incremental_since:
            logger.info(f"  • Filtro incremental: pushed > {incremental_since.strftime('%Y-%m-%d')}")
        
        if self.max_workers > 1:
            logger.info(f"  • Workers paralelos: {self.max_workers}")
        
        # Generar lista de segmentos a procesar (keyword, stars, year)
        segments = []
        for keyword in search_keywords:
            for star_range in star_ranges:
                min_stars, max_stars = star_range
                for year in created_years:
                    segments.append((min_stars, max_stars, year, keyword))
        
        all_repositories = {}  # Usar dict para evitar duplicados por full_name
        
        if self.max_workers > 1:
            # Ejecución PARALELA con ThreadPoolExecutor
            all_repositories = self._search_segments_parallel(
                segments, total_combinations, max_results, incremental_since
            )
        else:
            # Ejecución SECUENCIAL (legacy)
            all_repositories = self._search_segments_sequential(
                segments, total_combinations, max_results, incremental_since
            )
        
        result = list(all_repositories.values())
        
        logger.info(f"\n✅ Búsqueda segmentada completada:")
        logger.info(f"  • Repositorios únicos obtenidos: {len(result)}")
        if incremental_since:
            logger.info(f"  • Modo: incremental (desde {incremental_since.strftime('%Y-%m-%d')})")
        
        return result
    
    def _search_single_segment(
        self,
        min_stars: int,
        max_stars: int,
        year: int,
        incremental_since: Optional[datetime] = None,
        search_keyword: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Ejecuta la búsqueda de un segmento individual con reintentos.
        Hilo-safe: cada llamada usa el cliente GraphQL singleton con su propio estado.
        
        Si falla por 403 (secondary rate limit) u otro error transitorio,
        reintenta hasta 3 veces con backoff exponencial.
        
        Args:
            min_stars: Estrellas mínimas
            max_stars: Estrellas máximas
            year: Año de creación
            incremental_since: Fecha para filtro pushed (modo incremental)
            search_keyword: Keyword específica para la búsqueda
            
        Returns:
            Lista de repos encontrados en este segmento
        """
        segment_name = f"[{search_keyword or 'default'}] stars:{min_stars}..{max_stars} year:{year}"
        max_segment_retries = 3
        
        for attempt in range(max_segment_retries):
            try:
                # Verificar rate limit antes de cada búsqueda
                self._check_rate_limit()
                
                # En modo incremental, crear un config modificado con filtro pushed
                config_to_use = self.config
                
                segment_repos = self.client.search_repositories_segmented(
                    config_criteria=config_to_use,
                    min_stars=min_stars,
                    max_stars=max_stars,
                    created_year=year,
                    max_results=1000,
                    pushed_after=incremental_since.strftime('%Y-%m-%d') if incremental_since else None,
                    search_keyword=search_keyword
                )
                
                return segment_repos
                
            except Exception as e:
                error_str = str(e).lower()
                is_retryable = any(kw in error_str for kw in ['403', 'forbidden', 'rate limit', 'secondary', '502', '503', '504', 'timeout'])
                
                if is_retryable and attempt < max_segment_retries - 1:
                    # Consultar timestamp real de reset vía REST API
                    try:
                        rest_info = self.client._get_rate_limit_rest()
                        core_reset = rest_info.get('resources', {}).get('core', {}).get('reset', 0)
                        gql_reset = rest_info.get('resources', {}).get('graphql', {}).get('reset', 0)
                        search_reset = rest_info.get('resources', {}).get('search', {}).get('reset', 0)
                        reset_ts = max(core_reset, gql_reset, search_reset)
                        if reset_ts > 0:
                            wait_time = max(0, reset_ts - time.time()) + 5
                        else:
                            wait_time = 120  # Fallback conservador
                    except Exception:
                        wait_time = 120  # Fallback conservador
                    logger.warning(
                        f"⚠️ Error retryable en segmento {segment_name} "
                        f"(intento {attempt + 1}/{max_segment_retries}): {e}. "
                        f"Reintentando en {wait_time:.0f}s..."
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"❌ Error en segmento {segment_name} tras {attempt + 1} intentos: {e}")
                    return []
    
    def _search_segments_parallel(
        self,
        segments: List[tuple],
        total_combinations: int,
        max_results: Optional[int],
        incremental_since: Optional[datetime]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Ejecuta búsquedas en paralelo usando ThreadPoolExecutor.
        
        Args:
            segments: Lista de (min_stars, max_stars, year, keyword)
            total_combinations: Total de segmentos
            max_results: Límite máximo de repos
            incremental_since: Fecha para filtro incremental
            
        Returns:
            Dict {full_name: repo_data} deduplicado
        """
        all_repositories = {}
        completed = 0
        
        logger.info(f"\n🚀 Ejecutando {total_combinations} segmentos con {self.max_workers} workers...")
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Enviar todos los segmentos al pool
            future_to_segment = {
                executor.submit(
                    self._search_single_segment,
                    min_stars, max_stars, year, incremental_since, keyword
                ): (min_stars, max_stars, year, keyword)
                for min_stars, max_stars, year, keyword in segments
            }
            
            # Recoger resultados a medida que terminan
            for future in as_completed(future_to_segment):
                if self.cancel_event and self.cancel_event.is_set():
                    for f in future_to_segment:
                        f.cancel()
                    break
                min_stars, max_stars, year, keyword = future_to_segment[future]
                completed += 1
                segment_name = f"[{keyword}] stars:{min_stars}..{max_stars} year:{year}"

                # Progreso granular durante extracci\u00f3n (0-74 de 100)
                extraction_progress = int((completed / total_combinations) * 74)
                self._report_progress(
                    extraction_progress, 100,
                    f"Fase 1/4: Segmento {completed}/{total_combinations} - {len(all_repositories)} repos"
                )
                
                try:
                    segment_repos = future.result()
                    
                    # Agregar al conjunto total (evitando duplicados)
                    new_repos = 0
                    for repo in segment_repos:
                        full_name = repo.get("nameWithOwner", repo.get("name", ""))
                        if full_name and full_name not in all_repositories:
                            all_repositories[full_name] = repo
                            new_repos += 1
                    
                    if new_repos > 0:
                        logger.info(
                            f"  [{completed}/{total_combinations}] {segment_name}: "
                            f"{len(segment_repos)} encontrados, {new_repos} nuevos "
                            f"(total: {len(all_repositories)})"
                        )
                    else:
                        logger.debug(
                            f"  [{completed}/{total_combinations}] {segment_name}: "
                            f"{len(segment_repos)} encontrados, 0 nuevos"
                        )
                    
                except Exception as e:
                    logger.warning(f"  [{completed}/{total_combinations}] ❌ {segment_name}: {e}")
                
                # Si se alcanzó el límite global, cancelar futures pendientes
                if max_results and len(all_repositories) >= max_results:
                    logger.info(f"\n🎯 Límite alcanzado: {len(all_repositories)} repositorios")
                    # Cancelar futures pendientes
                    for f in future_to_segment:
                        f.cancel()
                    break
        
        return all_repositories
    
    def _search_segments_sequential(
        self,
        segments: List[tuple],
        total_combinations: int,
        max_results: Optional[int],
        incremental_since: Optional[datetime]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Ejecuta búsquedas secuencialmente (modo legacy, 1 worker).
        
        Args:
            segments: Lista de (min_stars, max_stars, year, keyword)
            total_combinations: Total de segmentos
            max_results: Límite máximo de repos
            incremental_since: Fecha para filtro incremental
            
        Returns:
            Dict {full_name: repo_data} deduplicado
        """
        all_repositories = {}
        query_count = 0
        
        for min_stars, max_stars, year, keyword in segments:
            if self.cancel_event and self.cancel_event.is_set():
                break
            query_count += 1
            segment_name = f"[{keyword}] stars:{min_stars}..{max_stars} year:{year}"

            # Progreso granular durante extracción (0-74 de 100)
            extraction_progress = int((query_count / total_combinations) * 74)
            self._report_progress(
                extraction_progress, 100,
                f"Fase 1/4: Segmento {query_count}/{total_combinations} - {len(all_repositories)} repos"
            )
            
            logger.info(f"\n📍 Consulta {query_count}/{total_combinations}: {segment_name}")
            
            segment_repos = self._search_single_segment(
                min_stars, max_stars, year, incremental_since, keyword
            )
            
            # Agregar al conjunto total (evitando duplicados)
            new_repos = 0
            for repo in segment_repos:
                full_name = repo.get("nameWithOwner", repo.get("name", ""))
                if full_name and full_name not in all_repositories:
                    all_repositories[full_name] = repo
                    new_repos += 1
            
            logger.info(f"  ✓ Encontrados: {len(segment_repos)} repos, {new_repos} nuevos")
            logger.info(f"  📊 Total acumulado: {len(all_repositories)} repos únicos")
            
            # Si se alcanzó el límite global, parar
            if max_results and len(all_repositories) >= max_results:
                logger.info(f"\n🎯 Límite alcanzado: {len(all_repositories)} repositorios")
                break
        
        return all_repositories
    
    def _check_rate_limit(self) -> None:
        """
        Verifica el rate limit de GitHub y espera si es necesario.
        """
        try:
            rate_limit_config = self.config._config_data.get("rate_limit", {})
            
            if not rate_limit_config.get("check_before_request", True):
                return
            
            rate_limit_info = self.client.get_rate_limit()
            remaining = rate_limit_info.get("remaining", 5000)
            limit = rate_limit_info.get("limit", 5000)
            reset_at = rate_limit_info.get("reset_at")
            
            min_remaining = rate_limit_config.get("min_remaining", 100)
            
            logger.debug(f"Rate Limit: {remaining}/{limit} restantes")
            
            if remaining < min_remaining:
                if rate_limit_config.get("wait_on_exhaustion", True):
                    if reset_at:
                        wait_seconds = (reset_at - datetime.now(timezone.utc)).total_seconds()
                        if wait_seconds > 0:
                            logger.warning(
                                f"⏳ Rate limit bajo ({remaining} restantes). "
                                f"Esperando {wait_seconds:.0f}s hasta reset..."
                            )
                            time.sleep(wait_seconds + 5)  # +5s de margen
                            logger.info("✅ Rate limit reseteado, continuando...")
                else:
                    logger.warning(
                        f"⚠️  Rate limit bajo ({remaining} restantes) pero "
                        f"wait_on_exhaustion=False, continuando..."
                    )
        
        except Exception as e:
            logger.debug(f"No se pudo verificar rate limit: {e}")
    
    def _validate_repositories(
        self,
        repositories_raw: List[Dict[str, Any]]
    ) -> Tuple[List[Repository], List[Dict[str, Any]]]:
        """
        Valida repositorios raw de GraphQL y los convierte a modelos Pydantic.
        
        Args:
            repositories_raw: Lista de repositorios sin validar (dict de GraphQL)
            
        Returns:
            Tupla de (repos_validados, errores_validación)
        """
        validated = []
        errors = []
        
        logger.info(f"📋 Validando {len(repositories_raw)} repositorios...")
        
        for i, repo_raw in enumerate(repositories_raw, 1):
            try:
                # Parsear datos GraphQL a modelo Pydantic
                repository = Repository.from_graphql_response(repo_raw)
                validated.append(repository)
                
                if i % 10 == 0:
                    logger.debug(f"  Validados: {i}/{len(repositories_raw)}")
                    
            except ValidationError as e:
                sanitized_data = self._sanitize_repo_data(repo_raw)
                error_info = {
                    "repository": repo_raw.get("nameWithOwner", "unknown"),
                    "errors": e.errors(),
                    "raw_data": sanitized_data
                }
                errors.append(error_info)
                # No loguear la excepción completa si puede contener datos masivos
                logger.warning(f"⚠️  Error validando {repo_raw.get('nameWithOwner')}: {str(e)[:500]}...")
                
            except Exception as e:
                sanitized_data = self._sanitize_repo_data(repo_raw)
                error_info = {
                    "repository": repo_raw.get("nameWithOwner", "unknown"),
                    "error": str(e),
                    "raw_data": sanitized_data
                }
                errors.append(error_info)
                logger.error(f"❌ Error inesperado validando {repo_raw.get('nameWithOwner')}: {e}")
        
        # Actualizar estadísticas
        self.stats["validation_success"] = len(validated)
        self.stats["validation_errors"] = len(errors)
        
        logger.info(f"✅ Validación completada: {len(validated)} exitosos, {len(errors)} errores")
        
        return validated, errors
    
    def _persist_repositories(self, repositories: List[Repository]) -> None:
        """
        Persiste repositorios en MongoDB usando operaciones bulk.
        
        Args:
            repositories: Lista de repositorios validados (modelos Pydantic)
        """
        if not repositories:
            logger.warning("⚠️  No hay repositorios para persistir")
            return
        
        logger.info(f"💾 Persistiendo {len(repositories)} repositorios en lotes de {self.batch_size}...")
        
        total_inserted = 0
        total_updated = 0
        
        # Procesar en lotes
        for i in range(0, len(repositories), self.batch_size):
            if self.cancel_event and self.cancel_event.is_set():
                break
            batch = repositories[i:i + self.batch_size]
            batch_num = i // self.batch_size + 1
            total_batches = (len(repositories) + self.batch_size - 1) // self.batch_size
            
            logger.debug(f"  Procesando lote {batch_num}/{total_batches} ({len(batch)} repos)...")
            
            try:
                # Bulk upsert (deprecado: retry automático legacy de Cosmos DB RU)
                result = self._retry_on_cosmos_throttle(
                    lambda: self.repo_db.bulk_upsert(
                        documents=batch,
                        unique_field="id"
                    )
                )
                
                if result:
                    total_inserted += result["upserted_count"]
                    total_updated += result["modified_count"]
                    
                    logger.debug(
                        f"    ✓ Lote {batch_num}: "
                        f"{result['upserted_count']} nuevos, "
                        f"{result['modified_count']} actualizados"
                    )
                    
                    # NOTA: Sleep removido - vCore no necesita throttling
                else:
                    logger.warning(f"⚠️  Lote {batch_num} falló tras reintentos. Intentando uno por uno...")
                    # Fallback a inserción individual
                    raise Exception("Bulk upsert failed after retries")
                
            except Exception as e:
                logger.warning(f"⚠️  Error en lote {batch_num}: {e}. Reintentando uno por uno...")
                # Intentar insertar uno por uno en caso de error (resiliencia)
                # Esto permite que el proceso continúe incluso si hay problemas con algunos documentos
                successful_in_batch = 0
                failed_in_batch = 0
                
                for repo in batch:
                    try:
                        upsert_result = self._retry_on_cosmos_throttle(
                            lambda: self.repo_db.upsert_one(
                                query={"id": repo.id},
                                document=repo.dict(),
                                update_timestamp=True
                            )
                        )
                        
                        if upsert_result:
                            if upsert_result["operation"] == "insert":
                                total_inserted += 1
                                successful_in_batch += 1
                            else:
                                total_updated += 1
                                successful_in_batch += 1
                            
                            # NOTA: Sleep removido - vCore no necesita throttling
                        else:
                            failed_in_batch += 1
                            logger.warning(f"⚠️  No se pudo persistir {repo.full_name if hasattr(repo, 'full_name') else repo.id}: falló tras reintentos")
                    except Exception as e2:
                        failed_in_batch += 1
                        logger.warning(f"⚠️  No se pudo persistir {repo.full_name if hasattr(repo, 'full_name') else repo.id}: {e2}")
                        # NO lanzar excepción - continuar con el siguiente
                        continue
                
                logger.info(f"  ℹ️  Recuperación del lote {batch_num}: {successful_in_batch} exitosos, {failed_in_batch} fallidos")
        
        self.stats["repositories_inserted"] = total_inserted
        self.stats["repositories_updated"] = total_updated
        
        logger.info(
            f"✅ Persistencia completada: "
            f"{total_inserted} nuevos, {total_updated} actualizados"
        )
    
    # DESHABILITADO: Método preservado para futura implementación de análisis de grafos
    # Para reactivar: descomentar este método, el import de Relation, self.relation_db, 
    # la estadística relations_created, y las llamadas en FASE 5 y en el reporte
    # def _create_relations(self, repositories: List[Repository]) -> None:
    #     """
    #     Crea relaciones entre repositorios y sus owners (organizaciones/usuarios).
    #     
    #     Args:
    #         repositories: Lista de repositorios validados
    #     """
    #     logger.info("🔗 Creando relaciones...")
    #     
    #     relations_created = 0
    #     
    #     for repo in repositories:
    #         try:
    #             # Verificar que tiene owner
    #             if not repo.owner:
    #                 logger.debug(f"Repositorio {repo.full_name} no tiene owner, saltando relación")
    #                 continue
    #             
    #             # Relación: Organization/User owns Repository
    #             from src.models.relation import ContributionMetrics
    #             
    #             contribution_metrics = ContributionMetrics(
    #                 commits_count=repo.commits_count or 0,
    #                 issues_opened=0,  # No disponible en datos de repo
    #                 pull_requests_opened=0  # No disponible en datos de repo
    #             )
    #             
    #             relation = Relation.create_user_repo_contribution(
    #                 user_id=repo.owner.id,
    #                 user_login=repo.owner.login,
    #                 repo_id=repo.id,
    #                 repo_name=repo.full_name or repo.name,
    #                 contribution_metrics=contribution_metrics,
    #                 started_at=repo.created_at
    #             )
    #             
    #             # Insertar relación (evitar duplicados)
    #             result = self.relation_db.insert_one(relation.dict(), check_duplicates=True)
    #             if result:
    #                 relations_created += 1
    #                 
    #         except Exception as e:
    #             logger.debug(f"No se pudo crear relación para {repo.full_name if hasattr(repo, 'full_name') else 'unknown'}: {e}")
    #     
    #     self.stats["relations_created"] = relations_created
    #     logger.debug(f"✓ {relations_created} relaciones creadas")
    
    def filter_repositories(self, repositories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Aplica todos los filtros de calidad y relevancia a los repositorios.
        
        Orden de filtros (de más restrictivo a menos):
        1. Archivado
        2. Descripción/README
        3. Tamaño mínimo del proyecto
        4. Actividad reciente
        5. Fork válido (si es fork)
        6. Keywords cuánticas
        7. Lenguaje válido
        8. Estrellas mínimas
        9. Engagement de comunidad
        
        Args:
            repositories: Lista de repositorios a filtrar
            
        Returns:
            Lista de repositorios que pasan todos los filtros
        """
        logger.info(f"Aplicando filtros avanzados a {len(repositories)} repositorios...")
        
        filtered = []
        
        for repo in repositories:
            repo_name = repo.get("nameWithOwner", "unknown")
            repo_url = repo.get("url", "")
            
            # 1. Filtro: No archivado
            if not RepositoryFilters.is_not_archived(repo):
                self.stats["filtered_by_archived"] += 1
                logger.debug(f"❌ RECHAZADO [Archivado]: {repo_name} | {repo_url}")
                continue
            
            # 2. Filtro: Blacklist (QuantumultX, Firefox Quantum, Non-QC conocidos)
            if not RepositoryFilters.is_not_blacklisted(repo):
                self.stats["filtered_by_blacklist"] += 1
                logger.debug(f"❌ RECHAZADO [Blacklist FP]: {repo_name} | {repo_url}")
                continue
            
            # 3. Filtro: Relevancia contextual QC
            if not RepositoryFilters.has_quantum_relevance(repo):
                self.stats["filtered_by_relevance"] += 1
                logger.debug(f"❌ RECHAZADO [Sin relevancia QC]: {repo_name} | {repo_url}")
                continue
            
            # 4. Filtro: Tiene descripción o README
            if not RepositoryFilters.has_description(repo):
                self.stats["filtered_by_no_description"] += 1
                logger.debug(f"❌ RECHAZADO [Sin descripción/README]: {repo_name} | {repo_url}")
                continue
            
            # 5. Filtro: Tamaño mínimo (commits y KB)
            if not RepositoryFilters.is_minimal_project(repo, min_commits=10, min_size_kb=10):
                self.stats["filtered_by_minimal_project"] += 1
                default_branch = repo.get("defaultBranchRef") or {}
                target = default_branch.get("target") or {}
                history = target.get("history") or {}
                commits = history.get("totalCount", 0)
                size_kb = repo.get("diskUsage", 0)
                logger.debug(f"❌ RECHAZADO [Tamaño mínimo: {commits} commits, {size_kb} KB]: {repo_name} | {repo_url}")
                continue
            
            # 6. Filtro: Actividad reciente
            if not RepositoryFilters.is_active(repo, self.config.max_inactivity_days):
                self.stats["filtered_by_inactivity"] += 1
                last_update = repo.get("updatedAt", "unknown")
                logger.debug(f"❌ RECHAZADO [Inactivo desde {last_update}]: {repo_name} | {repo_url}")
                continue
            
            # 7. Filtro: Fork válido (si es fork, debe tener contribuciones propias)
            if not RepositoryFilters.is_valid_fork(repo):
                self.stats["filtered_by_fork"] += 1
                logger.debug(f"❌ RECHAZADO [Fork sin contribuciones propias]: {repo_name} | {repo_url}")
                continue
            
            # 8. Filtro: Keywords cuánticas
            if not RepositoryFilters.matches_keywords(repo, self.config.keywords):
                self.stats["filtered_by_keywords"] += 1
                logger.debug(f"❌ RECHAZADO [Sin keywords cuánticas]: {repo_name} | {repo_url}")
                continue
            
            # 9. Filtro: Lenguaje válido
            if not RepositoryFilters.has_valid_language(repo, self.config.languages):
                self.stats["filtered_by_language"] += 1
                primary_lang = (repo.get("primaryLanguage") or {}).get("name", "unknown")
                secondary_langs = [(edge.get("node") or {}).get("name") for edge in (repo.get("languages") or {}).get("edges", [])]
                logger.debug(f"❌ RECHAZADO [Lenguaje: primario={primary_lang}, secundarios={secondary_langs}]: {repo_name} | {repo_url}")
                continue
            
            # 10. Filtro: Estrellas mínimas
            if not RepositoryFilters.has_minimum_stars(repo, self.config.min_stars):
                self.stats["filtered_by_stars"] += 1
                stars = repo.get("stargazerCount", 0)
                logger.debug(f"❌ RECHAZADO [Pocas estrellas: {stars}]: {repo_name} | {repo_url}")
                continue
            
            # 11. Filtro: Engagement de comunidad (opcional pero recomendado)
            if not RepositoryFilters.has_community_engagement(repo, min_watchers=3, min_forks=1):
                self.stats["filtered_by_community_engagement"] += 1
                watchers = (repo.get("watchers") or {}).get("totalCount", 0)
                forks = repo.get("forkCount", 0)
                logger.debug(f"❌ RECHAZADO [Bajo engagement: {watchers} watchers, {forks} forks]: {repo_name} | {repo_url}")
                continue
            
            # Si pasa todos los filtros, agregarlo
            stars = repo.get("stargazerCount", 0)
            primary_lang = (repo.get("primaryLanguage") or {}).get("name", "unknown")
            logger.debug(f"✅ ACEPTADO [{primary_lang}, {stars}⭐]: {repo_name} | {repo_url}")
            filtered.append(repo)
        
        logger.info(f"Filtrado completado: {len(filtered)} repositorios válidos")
        logger.info(f"  - Rechazados por archivado: {self.stats['filtered_by_archived']}")
        logger.info(f"  - Rechazados por blacklist FP: {self.stats.get('filtered_by_blacklist', 0)}")
        logger.info(f"  - Rechazados por sin relevancia QC: {self.stats.get('filtered_by_relevance', 0)}")
        logger.info(f"  - Rechazados por falta de descripción: {self.stats['filtered_by_no_description']}")
        logger.info(f"  - Rechazados por tamaño mínimo: {self.stats['filtered_by_minimal_project']}")
        logger.info(f"  - Rechazados por inactividad: {self.stats['filtered_by_inactivity']}")
        logger.info(f"  - Rechazados por fork sin aportes: {self.stats['filtered_by_fork']}")
        logger.info(f"  - Rechazados por keywords: {self.stats['filtered_by_keywords']}")
        logger.info(f"  - Rechazados por lenguaje: {self.stats['filtered_by_language']}")
        logger.info(f"  - Rechazados por estrellas: {self.stats['filtered_by_stars']}")
        logger.info(f"  - Rechazados por bajo engagement: {self.stats['filtered_by_community_engagement']}")
        
        return filtered
    
    def _save_to_json(
        self,
        repositories: List[Repository],
        output_file: str = "ingestion_results.json"
    ) -> None:
        """
        Guarda los resultados en archivo JSON.
        
        Args:
            repositories: Lista de repositorios validados
            output_file: Nombre del archivo JSON
        """
        try:
            logger.info(f"📄 Guardando {len(repositories)} repositorios en {output_file}...")
            
            # Crear directorio si no existe
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Convertir modelos Pydantic a dict
            repos_dict = [repo.dict() for repo in repositories]
            
            # Guardar con metadata
            output_data = {
                "metadata": {
                    "ingestion_date": datetime.now(timezone.utc).isoformat(),
                    "total_repositories": len(repositories),
                    "config_version": self.config.version,
                    "incremental_mode": self.incremental,
                    "criteria": {
                        "keywords": self.config.keywords,
                        "languages": self.config.languages,
                        "min_stars": self.config.min_stars,
                        "max_inactivity_days": self.config.max_inactivity_days,
                        "exclude_forks": self.config.exclude_forks
                    },
                    "statistics": {
                        "repositories_inserted": self.stats["repositories_inserted"],
                        "repositories_updated": self.stats["repositories_updated"],
                        # "relations_created": self.stats["relations_created"],  # DESHABILITADO: Para futura implementación de análisis de grafos
                        "validation_errors": self.stats["validation_errors"]
                    }
                },
                "repositories": repos_dict
            }
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False, default=str)
            
            logger.info(f"✅ Repositorios guardados en {output_file}")
            
        except Exception as e:
            logger.error(f"❌ Error al guardar en JSON: {e}")
    
    def _generate_report(
        self,
        repositories: List[Repository],
        validation_errors: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Genera un reporte completo del proceso de ingesta con todas las métricas.
        
        Args:
            repositories: Lista de repositorios validados
            validation_errors: Lista de errores de validación
            
        Returns:
            Diccionario con el reporte completo
        """
        duration = None
        if self.stats["start_time"] and self.stats["end_time"]:
            duration = (self.stats["end_time"] - self.stats["start_time"]).total_seconds()
        
        # Estadísticas por lenguaje
        language_stats = {}
        for repo in repositories:
            # primary_language es un objeto Language, extraer el nombre
            lang_name = "Unknown"
            if repo.primary_language:
                lang_name = repo.primary_language.name if hasattr(repo.primary_language, 'name') else str(repo.primary_language)
            language_stats[lang_name] = language_stats.get(lang_name, 0) + 1
        
        # Estadísticas de estrellas (atributo correcto: stargazer_count)
        star_counts = [repo.stargazer_count or 0 for repo in repositories]
        avg_stars = sum(star_counts) / len(star_counts) if star_counts else 0
        
        # Calcular tasa de persistencia
        total_persisted = self.stats["repositories_inserted"] + self.stats["repositories_updated"]
        persistence_rate = (total_persisted / len(repositories) * 100) if repositories else 0
        
        # Contexto de la base de datos (útil para modo incremental)
        db_context = {}
        try:
            db_total = self.repo_db.count_documents()
            from ..core.db import get_database
            db = get_database()
            db_enriched = db["repositories"].count_documents({"enrichment_status.is_complete": True})
            db_pending_enrichment = db_total - db_enriched
            db_users = db["users"].count_documents({})
            db_orgs = db["organizations"].count_documents({})
            
            # Obtener fecha de última ingesta
            metadata = db["ingestion_metadata"].find_one({"type": "repositories_last_ingestion"})
            last_ingestion_date = metadata.get("date") if metadata else None
            
            db_context = {
                "total_repos_in_db": db_total,
                "enriched_repos": db_enriched,
                "pending_enrichment": db_pending_enrichment,
                "total_users": db_users,
                "total_organizations": db_orgs,
                "last_ingestion_date": last_ingestion_date.strftime('%Y-%m-%d %H:%M UTC') if last_ingestion_date else "N/A"
            }
        except Exception as e:
            logger.debug(f"No se pudo obtener contexto de BD: {e}")
        
        report = {
            "summary": {
                "total_found": self.stats["total_found"],
                "total_filtered": self.stats["total_filtered"],
                "validation_success": self.stats["validation_success"],
                "validation_errors": self.stats["validation_errors"],
                "repositories_inserted": self.stats["repositories_inserted"],
                "repositories_updated": self.stats["repositories_updated"],
                "success_rate": f"{(self.stats['total_filtered'] / self.stats['total_found'] * 100):.1f}%" if self.stats["total_found"] > 0 else "N/A",
                "persistence_rate": f"{persistence_rate:.1f}%",
                "duration_seconds": duration,
                "mode": "from_scratch" if self.from_scratch else ("incremental" if self.incremental else "full")
            },
            "database_context": db_context,
            "timing": {
                "extraction": f"{self.stats['time_extraction']:.2f}s",
                "filtering": f"{self.stats['time_filtering']:.2f}s",
                "validation": f"{self.stats['time_validation']:.2f}s",
                "persistence": f"{self.stats['time_persistence']:.2f}s",
                "total": f"{duration:.2f}s" if duration else "N/A"
            },
            "filtering": {
                "rejected_by_archived": self.stats["filtered_by_archived"],
                "rejected_by_blacklist": self.stats.get("filtered_by_blacklist", 0),
                "rejected_by_relevance": self.stats.get("filtered_by_relevance", 0),
                "rejected_by_no_description": self.stats["filtered_by_no_description"],
                "rejected_by_minimal_project": self.stats["filtered_by_minimal_project"],
                "rejected_by_inactivity": self.stats["filtered_by_inactivity"],
                "rejected_by_fork": self.stats["filtered_by_fork"],
                "rejected_by_keywords": self.stats["filtered_by_keywords"],
                "rejected_by_language": self.stats["filtered_by_language"],
                "rejected_by_stars": self.stats["filtered_by_stars"],
                "rejected_by_community_engagement": self.stats["filtered_by_community_engagement"]
            },
            "statistics": {
                "languages": language_stats,
                "average_stars": round(avg_stars, 1),
                "max_stars": max(star_counts) if star_counts else 0,
                "min_stars": min(star_counts) if star_counts else 0
            },
            "errors": {
                "validation_errors": len(validation_errors),
                "sample_errors": validation_errors[:5] if validation_errors else []
            }
        }
        
        # Log del reporte
        logger.info("\n" + "=" * 80)
        mode_label = report['summary']['mode'].upper()
        logger.info(f"📊 REPORTE DE INGESTA ({mode_label})")
        logger.info("=" * 80)
        
        # En modo incremental, mostrar contexto de BD primero
        if self.incremental and db_context:
            is_up_to_date = (self.stats["total_found"] == 0)
            if is_up_to_date:
                logger.info(f"\n✅ BASE DE DATOS AL DÍA - No se encontraron repositorios nuevos/actualizados")
            logger.info(f"\n🗄️  Estado de la Base de Datos:")
            logger.info(f"  • Repositorios totales en BD: {db_context.get('total_repos_in_db', '?')}")
            logger.info(f"  • Enriquecidos completamente: {db_context.get('enriched_repos', '?')}")
            logger.info(f"  • Pendientes de enriquecimiento: {db_context.get('pending_enrichment', '?')}")
            logger.info(f"  • Usuarios en BD: {db_context.get('total_users', '?')}")
            logger.info(f"  • Organizaciones en BD: {db_context.get('total_organizations', '?')}")
            logger.info(f"  • Última ingesta: {db_context.get('last_ingestion_date', 'N/A')}")
        
        logger.info(f"\n🔍 Extracción:")
        logger.info(f"  • Repos nuevos/actualizados encontrados: {report['summary']['total_found']}")
        logger.info(f"  • Tiempo: {report['timing']['extraction']}")
        
        if self.stats["total_found"] > 0:
            logger.info(f"\n🔍 Filtrado:")
            logger.info(f"  • Repositorios válidos: {report['summary']['total_filtered']}")
            logger.info(f"  • Tasa de aceptación: {report['summary']['success_rate']}")
            logger.info(f"  • Tiempo: {report['timing']['filtering']}")
            
            logger.info(f"\n✔️  Validación:")
            logger.info(f"  • Validaciones exitosas: {report['summary']['validation_success']}")
            logger.info(f"  • Errores de validación: {report['summary']['validation_errors']}")
            logger.info(f"  • Tiempo: {report['timing']['validation']}")
            
            logger.info(f"\n💾 Persistencia:")
            logger.info(f"  • Repositorios nuevos: {report['summary']['repositories_inserted']}")
            logger.info(f"  • Repositorios actualizados: {report['summary']['repositories_updated']}")
            logger.info(f"  • Tasa de persistencia: {report['summary']['persistence_rate']}")
            logger.info(f"  • Tiempo: {report['timing']['persistence']}")
            
            logger.info(f"\n📈 Estadísticas:")
            logger.info(f"  • Distribución por lenguaje:")
            for lang, count in sorted(language_stats.items(), key=lambda x: x[1], reverse=True)[:5]:
                logger.info(f"    - {lang}: {count}")
            logger.info(f"  • Estrellas promedio: {report['statistics']['average_stars']}")
        else:
            logger.info(f"\n💡 No se requirieron fases de filtrado/validación/persistencia")
        
        logger.info(f"\n⏱️  Tiempo total: {report['timing']['total']}")
        logger.info("=" * 80)
        
        return report


# ==================== FUNCIONES HELPER ====================

def run_ingestion(
    max_results: Optional[int] = None,
    incremental: bool = False,
    from_scratch: bool = False,
    batch_size: int = 500,  # ✅ OPTIMIZADO para vCore
    max_workers: int = 4,
    save_to_json: bool = True,
    output_file: str = "ingestion_results.json"
) -> Dict[str, Any]:
    """
    Ejecuta una ingesta completa con configuración por defecto.
    
    Args:
        max_results: Número máximo de repositorios
        incremental: Si True, solo busca repos nuevos/actualizados
        from_scratch: Si True, limpia colección antes de ingestar
        batch_size: Tamaño de lote para operaciones bulk
        max_workers: Workers paralelos para segmentos
        save_to_json: Guardar en JSON
        output_file: Archivo de salida
        
    Returns:
        Reporte de la ingesta
    """
    engine = IngestionEngine(
        incremental=incremental,
        from_scratch=from_scratch,
        batch_size=batch_size,
        max_workers=max_workers
    )
    return engine.run(
        max_results=max_results,
        save_to_json=save_to_json,
        output_file=output_file
    )


def run_incremental_ingestion(
    max_results: Optional[int] = None,
    batch_size: int = 500,  # ✅ OPTIMIZADO para vCore
    max_workers: int = 4
) -> Dict[str, Any]:
    """
    Ejecuta una ingesta incremental (solo repos nuevos/actualizados desde última ingesta).
    
    Args:
        max_results: Número máximo de repositorios
        batch_size: Tamaño de lote
        max_workers: Workers paralelos
        
    Returns:
        Reporte de la ingesta
    """
    return run_ingestion(
        max_results=max_results,
        incremental=True,
        batch_size=batch_size,
        max_workers=max_workers,
        save_to_json=False
    )


def run_from_scratch_ingestion(
    max_results: Optional[int] = None,
    batch_size: int = 500,
    max_workers: int = 4
) -> Dict[str, Any]:
    """
    Ejecuta una ingesta desde cero (limpia colección y reingesta todo).
    Elimina datos zombi que ya no pasan los filtros actuales.
    
    Args:
        max_results: Número máximo de repositorios
        batch_size: Tamaño de lote
        max_workers: Workers paralelos
        
    Returns:
        Reporte de la ingesta
    """
    return run_ingestion(
        max_results=max_results,
        from_scratch=True,
        batch_size=batch_size,
        max_workers=max_workers,
        save_to_json=False
    )
