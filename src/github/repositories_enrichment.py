"""
Motor de enriquecimiento de datos de repositorios.
Realiza una segunda pasada para completar información faltante usando GraphQL y REST API.
"""
import time
from typing import List, Dict, Any, Optional
from datetime import datetime
import requests
from functools import wraps
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
        batch_size: int = 100,  # ✅ OPTIMIZADO para vCore
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Inicializa el motor de enriquecimiento.
        
        Args:
            github_token: Token de autenticación de GitHub
            repos_repository: Repositorio MongoDB para repositorios
            batch_size: Número de repositorios a procesar por lote
            config: Configuración opcional (se usa para rate limit y reintentos)
        """
        self.github_token = github_token
        self.repos_repository = repos_repository
        self.config = config or {}
        self.batch_size = batch_size
        self.graphql_client = GitHubGraphQLClient(github_token)
        
        # Headers para REST API
        self.rest_headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        
        # Configuración de reintentos (desde config o defaults)
        enrichment_config = self.config.get("enrichment", {})
        self.max_retries = enrichment_config.get("max_retries", 3)
        self.base_backoff = enrichment_config.get("base_backoff_seconds", 2)
        
        # Configuración de rate limit (desde config o defaults)
        self.rate_limit_threshold = enrichment_config.get("rate_limit_threshold", 100)
        self.last_rate_limit_check = None
        self.current_rate_limit = None
        
        # Estadísticas
        self.stats = {
            "total_processed": 0,
            "total_enriched": 0,
            "total_errors": 0,
            "total_retries": 0,
            "total_rate_limit_waits": 0,
            "fields_enriched": {},
            "start_time": None,
            "end_time": None
        }
        
        logger.info(f"EnrichmentEngine inicializado (batch_size={batch_size}, max_retries={self.max_retries})")
    
    def _check_and_display_rate_limit(self, force_display: bool = False) -> Dict[str, Any]:
        """
        Verifica el rate limit actual y lo muestra si es necesario.
        Si queda poco rate limit, pausa hasta el reset.
        
        Args:
            force_display: Forzar mostrar el rate limit aunque no haya cambiado
            
        Returns:
            Información del rate limit
        """
        try:
            # Obtener rate limit de GraphQL
            rate_limit_info = self.graphql_client.get_rate_limit()
            
            if not rate_limit_info:
                logger.warning("⚠️  No se pudo obtener información de rate limit")
                return {}
            
            remaining = rate_limit_info.get("remaining", 0)
            limit = rate_limit_info.get("limit", 5000)
            reset_at = rate_limit_info.get("resetAt")
            
            # Calcular porcentaje
            percentage = (remaining / limit * 100) if limit > 0 else 0
            
            # Guardar estado actual
            self.current_rate_limit = rate_limit_info
            self.last_rate_limit_check = datetime.now()
            
            # Mostrar con colores según el nivel
            if percentage > 50 or force_display:
                logger.info(f"📊 Rate Limit: {remaining}/{limit} ({percentage:.1f}%) - Reset: {reset_at}")
            elif percentage > 20:
                logger.warning(f"⚠️  Rate Limit: {remaining}/{limit} ({percentage:.1f}%) - Reset: {reset_at}")
            else:
                logger.error(f"Rate Limit CRÍTICO: {remaining}/{limit} ({percentage:.1f}%) - Reset: {reset_at}")
            
            # Si queda poco rate limit, pausar hasta el reset
            if remaining < self.rate_limit_threshold:
                logger.warning(f"⏸️  Rate limit bajo ({remaining} < {self.rate_limit_threshold}). Pausando hasta reset...")
                self._wait_for_rate_limit_reset(reset_at)
                self.stats["total_rate_limit_waits"] += 1
            
            return rate_limit_info
            
        except Exception as e:
            logger.error(f"❌ Error verificando rate limit: {e}")
            return {}
    
    def _wait_for_rate_limit_reset(self, reset_at: str) -> None:
        """
        Espera hasta que se resetee el rate limit.
        
        Args:
            reset_at: Timestamp ISO 8601 del reset
        """
        try:
            # Parsear el timestamp
            reset_time = datetime.fromisoformat(reset_at.replace('Z', '+00:00'))
            now = datetime.now(reset_time.tzinfo)
            
            if reset_time > now:
                wait_seconds = (reset_time - now).total_seconds() + 10  # 10 segundos de margen
                
                logger.warning(f"⏳ Esperando {wait_seconds:.0f} segundos hasta reset del rate limit...")
                logger.info(f"Hora de reset: {reset_at}")
                
                # Esperar en intervalos de 30s mostrando progreso
                elapsed = 0
                interval = 30
                
                while elapsed < wait_seconds:
                    sleep_time = min(interval, wait_seconds - elapsed)
                    time.sleep(sleep_time)
                    elapsed += sleep_time
                    
                    remaining_wait = wait_seconds - elapsed
                    if remaining_wait > 0:
                        logger.info(f"⏳ Esperando... {remaining_wait:.0f} segundos restantes")
                
                logger.info("✅ Rate limit reseteado. Continuando...")
                
        except Exception as e:
            logger.error(f"❌ Error esperando reset de rate limit: {e}")
            # Esperar 60 segundos por defecto
            logger.warning("⏳ Esperando 60 segundos por seguridad...")
            time.sleep(60)
    
    def _retry_with_backoff(self, func, *args, **kwargs) -> Any:
        """
        Ejecuta una función con reintentos y backoff exponencial.
        
        Args:
            func: Función a ejecutar
            *args: Argumentos posicionales
            **kwargs: Argumentos con nombre
            
        Returns:
            Resultado de la función
            
        Raises:
            Exception: Si fallan todos los reintentos
        """
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                # Verificar rate limit antes de cada intento
                if attempt > 0:
                    self._check_and_display_rate_limit()
                
                # Ejecutar función
                result = func(*args, **kwargs)
                
                # Si tuvimos reintentos, registrar éxito
                if attempt > 0:
                    logger.info(f"✅ Éxito después de {attempt} reintento(s)")
                    self.stats["total_retries"] += attempt
                
                return result
                
            except requests.exceptions.Timeout as e:
                last_exception = e
                if attempt < self.max_retries:
                    wait_time = self.base_backoff ** attempt  # Backoff exponencial: 2, 4, 8 segundos
                    logger.warning(f"Timeout en intento {attempt + 1}/{self.max_retries + 1}. Reintentando en {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"❌ Timeout después de {self.max_retries + 1} intentos")
                    
            except requests.exceptions.RequestException as e:
                last_exception = e
                error_msg = str(e).lower()
                
                # Si es rate limit, manejar especialmente
                if "rate limit" in error_msg or "403" in error_msg:
                    logger.warning(f"Rate limit detectado: {e}")
                    self._check_and_display_rate_limit(force_display=True)
                    if attempt < self.max_retries:
                        logger.info(f"🔄 Reintentando después de verificar rate limit...")
                        continue
                    else:
                        logger.error(f"❌ Rate limit persistente después de {self.max_retries + 1} intentos")
                elif "502" in error_msg or "503" in error_msg or "504" in error_msg:
                    # Errores de servidor de GitHub
                    if attempt < self.max_retries:
                        wait_time = self.base_backoff ** attempt
                        logger.warning(f"Error de servidor GitHub ({e}). Reintentando en {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"❌ Error de servidor persistente después de {self.max_retries + 1} intentos")
                else:
                    # Otros errores de requests
                    if attempt < self.max_retries:
                        wait_time = self.base_backoff ** attempt
                        logger.warning(f"⚠️  Error de red ({e}). Reintentando en {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"❌ Error de red persistente: {e}")
                        
            except Exception as e:
                last_exception = e
                # Otros errores no se reintentan
                logger.error(f"❌ Error no recuperable: {type(e).__name__}: {e}")
                break
        
        # Si llegamos aquí, todos los reintentos fallaron
        if last_exception:
            raise last_exception
        
        return None
    
    def enrich_all_repositories(self, max_repos: Optional[int] = None, force_reenrich: bool = False) -> Dict[str, Any]:
        """
        Enriquece todos los repositorios en MongoDB.
        
        Args:
            max_repos: Límite opcional de repositorios a procesar
            force_reenrich: Si True, re-enriquece incluso repositorios ya enriquecidos
            
        Returns:
            Diccionario con estadísticas del proceso
        """
        logger.info("=" * 80)
        logger.info("🔄 INICIANDO ENRIQUECIMIENTO DE REPOSITORIOS")
        logger.info("=" * 80)
        
        self.stats["start_time"] = datetime.now()
        
        # Verificar rate limit inicial
        logger.info("\n🔍 Verificando rate limit inicial...")
        self._check_and_display_rate_limit(force_display=True)
        
        # Obtener repositorios de MongoDB
        logger.info("\n📂 Consultando repositorios en MongoDB...")
        
        # Si force_reenrich, procesar todos; si no, solo los no enriquecidos o incompletos
        if force_reenrich:
            query = {}
            logger.info("📌 Modo force_reenrich: procesando todos los repositorios")
        else:
            # Solo repositorios que:
            # 1. No tienen enrichment_status (nunca enriquecidos)
            # 2. No están completos
            # 3. Fueron enriquecidos hace más de 7 días
            from datetime import timedelta
            seven_days_ago = datetime.now() - timedelta(days=7)
            
            query = {
                "$or": [
                    {"enrichment_status": {"$exists": False}},
                    {"enrichment_status.is_complete": False},
                    {"enrichment_status.is_complete": {"$exists": False}},
                    {"enrichment_status.last_enriched": {"$lt": seven_days_ago.isoformat()}}
                ]
            }
            logger.info("📌 Modo incremental: repos sin enriquecer, incompletos o desactualizados (>7 días)")
        
        repos = list(self.repos_repository.collection.find(query).limit(max_repos or 0))
        total_repos = len(repos)
        
        logger.info(f"✅ Encontrados {total_repos} repositorios para procesar")
        
        if total_repos == 0:
            logger.warning("⚠️  No hay repositorios para enriquecer")
            return self.stats
        
        # Procesar en lotes
        for i in range(0, total_repos, self.batch_size):
            batch = repos[i:i + self.batch_size]
            batch_num = (i // self.batch_size) + 1
            total_batches = (total_repos + self.batch_size - 1) // self.batch_size
            
            logger.info("\n" + "=" * 80)
            logger.info(f"📦 LOTE {batch_num}/{total_batches} - Procesando {len(batch)} repositorios")
            logger.info(f"📊 Progreso global: {self.stats['total_processed']}/{total_repos} ({self.stats['total_processed']/total_repos*100:.1f}%)")
            logger.info("=" * 80)
            
            # Verificar rate limit al inicio de cada lote
            self._check_and_display_rate_limit()
            
            for idx, repo in enumerate(batch, 1):
                repo_name = repo.get('name_with_owner', 'unknown')
                logger.info(f"\n🔄 [{batch_num}.{idx}] Procesando: {repo_name}")
                
                # NOTA: Retry simplificado - vCore no tiene throttling code 16500
                # Solo manejar errores inesperados
                try:
                    self._enrich_repository(repo)
                    self.stats["total_enriched"] += 1
                    logger.info(f"✅ [{batch_num}.{idx}] Completado: {repo_name}")
                except Exception as e:
                    logger.error(f"❌ [{batch_num}.{idx}] Error en {repo_name}: {type(e).__name__}: {e}")
                    self.stats["total_errors"] += 1
                
                self.stats["total_processed"] += 1
            
            # Mostrar resumen del lote
            logger.info(f"\n📊 Lote {batch_num} completado:")
            logger.info(f"  ✅ Enriquecidos: {self.stats['total_enriched']}")
            logger.info(f"  ❌ Errores: {self.stats['total_errors']}")
            logger.info(f"  🔄 Reintentos totales: {self.stats['total_retries']}")
            
            # NOTA: Sleep removido - solo verificar rate limit de GitHub API
            # (vCore no necesita throttling de BD)
        
        self.stats["end_time"] = datetime.now()
        duration = (self.stats["end_time"] - self.stats["start_time"]).total_seconds()
        
        # Calcular estadísticas de enrichment_status
        complete_count = self.repos_repository.collection.count_documents({
            "enrichment_status.is_complete": True
        })
        incomplete_count = self.repos_repository.collection.count_documents({
            "enrichment_status.is_complete": False
        })
        
        logger.info("\n" + "=" * 80)
        logger.info("✅ ENRIQUECIMIENTO COMPLETADO")
        logger.info("=" * 80)
        
        # Verificar rate limit final
        logger.info("\n🔍 Rate limit final:")
        self._check_and_display_rate_limit(force_display=True)
        
        logger.info(f"\n📊 Estadísticas del Proceso:")
        logger.info(f"  • Repositorios procesados: {self.stats['total_processed']}")
        logger.info(f"  • Repositorios enriquecidos: {self.stats['total_enriched']}")
        logger.info(f"  • Errores: {self.stats['total_errors']}")
        logger.info(f"  • Total de reintentos: {self.stats['total_retries']}")
        logger.info(f"  • Pausas por rate limit: {self.stats['total_rate_limit_waits']}")
        logger.info(f"  • Duración total: {duration:.2f}s ({duration/60:.1f} minutos)")
        
        if self.stats['total_processed'] > 0:
            avg_time = duration / self.stats['total_processed']
            success_rate = (self.stats['total_enriched'] / self.stats['total_processed']) * 100
            logger.info(f"  • Tiempo promedio por repo: {avg_time:.2f}s")
            logger.info(f"  • Tasa de éxito: {success_rate:.1f}%")
        
        logger.info(f"\n📊 Estado del Dataset:")
        logger.info(f"  • Completamente enriquecidos: {complete_count}")
        logger.info(f"  • Con campos faltantes: {incomplete_count}")
        
        if complete_count + incomplete_count > 0:
            complete_percentage = (complete_count / (complete_count + incomplete_count)) * 100
            logger.info(f"  • Porcentaje completo: {complete_percentage:.1f}%")
        
        logger.info(f"\n📝 Campos Enriquecidos:")
        for field, count in sorted(self.stats['fields_enriched'].items(), key=lambda x: x[1], reverse=True):
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
        
        # Verificar si necesita enriquecimiento (optimización)
        enrichment_status = repo.get("enrichment_status", {})
        last_enriched = enrichment_status.get("last_enriched")
        
        if last_enriched:
            try:
                last_enriched_dt = datetime.fromisoformat(last_enriched)
                days_since = (datetime.now() - last_enriched_dt).days
                
                # Si fue enriquecido hace menos de 7 días y está completo, saltar
                if days_since < 7 and enrichment_status.get("is_complete"):
                    logger.info(f"  ⏭️  SALTADO: Enriquecido hace {days_since} días y completo")
                    return
                elif enrichment_status.get("is_complete") == False:
                    logger.info(f"  🔄 RE-ENRIQUECIENDO: Campos incompletos detectados")
            except (ValueError, TypeError):
                pass  # Si hay error parseando fecha, continuar con enriquecimiento
        
        logger.info(f"  🔧 Iniciando enriquecimiento de 18 estrategias...")
        
        updates = {}
        fields_enriched = []
        fields_missing = []
        
        # 1. Campos calculables (no requieren API)
        calculated = self._calculate_fields(repo)
        updates.update(calculated)
        fields_enriched.extend(calculated.keys())
        
        # 2. URLs calculables
        urls = self._generate_urls(repo)
        updates.update(urls)
        fields_enriched.extend(urls.keys())
        
        # 3. Owner type y organization_id
        owner_info = self._enrich_owner_info(repo)
        updates.update(owner_info)
        fields_enriched.extend(owner_info.keys())
        
        # 4. README text (si está en la query pero no se parseó)
        if not repo.get("readme_text"):
            logger.debug(f"  ├─ Obteniendo README...")
            readme = self._retry_with_backoff(self._fetch_readme_rest, name_with_owner)
            if readme:
                updates["readme_text"] = readme
                updates["has_readme"] = True
                fields_enriched.extend(["readme_text", "has_readme"])
                self._increment_field_stat("readme_text")
                self._increment_field_stat("has_readme")
            else:
                # No marcar como faltante - ya pasó filtro has_readme en ingesta
                logger.debug(f"    ℹ️  Sin README (campo opcional)")
        
        # 5. Releases (REST API) - OPCIONAL: No todos los repos tienen releases
        if not repo.get("releases") or repo.get("releases_count", 0) == 0:
            logger.debug(f"  ├─ Obteniendo releases...")
            releases_data = self._retry_with_backoff(self._fetch_releases_rest, name_with_owner)
            if releases_data:
                updates["releases"] = releases_data["releases"]
                updates["releases_count"] = releases_data["count"]
                updates["latest_release"] = releases_data["latest"]
                fields_enriched.extend(["releases", "releases_count"])
                if releases_data["latest"]:
                    fields_enriched.append("latest_release")
                self._increment_field_stat("releases")
                self._increment_field_stat("releases_count")
                if releases_data["latest"]:
                    self._increment_field_stat("latest_release")
            else:
                # No marcar como faltante - es normal que repos no tengan releases
                logger.debug(f"    ℹ️  Sin releases (campo opcional)")
        
        # 6. Branches count (REST API)
        if repo.get("branches_count", 0) == 0:
            logger.debug(f"  ├─ Contando branches...")
            branches_count = self._retry_with_backoff(self._fetch_branches_count_rest, name_with_owner)
            if branches_count and branches_count > 0:
                updates["branches_count"] = branches_count
                fields_enriched.append("branches_count")
                self._increment_field_stat("branches_count")
        
        # 7. Tags count (REST API)
        if repo.get("tags_count", 0) == 0:
            logger.debug(f"  ├─ Contando tags...")
            tags_count = self._retry_with_backoff(self._fetch_tags_count_rest, name_with_owner)
            if tags_count and tags_count > 0:
                updates["tags_count"] = tags_count
                fields_enriched.append("tags_count")
                self._increment_field_stat("tags_count")
        
        # 8. Recent commits (GraphQL)
        if not repo.get("recent_commits"):
            logger.debug(f"  ├─ Obteniendo commits recientes...")
            recent_commits = self._retry_with_backoff(self._fetch_recent_commits_graphql, name_with_owner)
            if recent_commits:
                updates["recent_commits"] = recent_commits
                fields_enriched.append("recent_commits")
                self._increment_field_stat("recent_commits")
                # Extraer last_commit_date
                if recent_commits and "committed_date" in recent_commits[0]:
                    updates["last_commit_date"] = recent_commits[0]["committed_date"]
                    fields_enriched.append("last_commit_date")
                    self._increment_field_stat("last_commit_date")
        
        # 9. Recent issues (GraphQL)
        if not repo.get("recent_issues"):
            logger.debug(f"  ├─ Obteniendo issues recientes...")
            recent_issues = self._retry_with_backoff(self._fetch_recent_issues_graphql, name_with_owner)
            if recent_issues:
                updates["recent_issues"] = recent_issues
                fields_enriched.append("recent_issues")
                self._increment_field_stat("recent_issues")
        
        # 10. Recent pull requests (GraphQL)
        if not repo.get("recent_pull_requests"):
            logger.debug(f"  ├─ Obteniendo pull requests recientes...")
            recent_prs = self._retry_with_backoff(self._fetch_recent_pull_requests_graphql, name_with_owner)
            if recent_prs:
                updates["recent_pull_requests"] = recent_prs
                fields_enriched.append("recent_pull_requests")
                self._increment_field_stat("recent_pull_requests")
        
        # 11. Pull requests detallados (REST API)
        logger.debug(f"  ├─ Contando pull requests...")
        pr_counts = self._retry_with_backoff(self._fetch_pull_request_counts_rest, name_with_owner)
        if pr_counts:
            updates.update(pr_counts)
            fields_enriched.extend(pr_counts.keys())
            for field in pr_counts.keys():
                self._increment_field_stat(field)
        
        # 12. Campos calculables simples
        simple_fields = self._fix_simple_fields(repo)
        updates.update(simple_fields)
        fields_enriched.extend(simple_fields.keys())
        
        # 13. Owner type (REST API)
        if not repo.get("owner", {}).get("type"):
            logger.debug(f"  ├─ Obteniendo tipo de owner...")
            owner_type = self._retry_with_backoff(self._fetch_owner_type_rest, name_with_owner)
            if owner_type:
                owner = repo.get("owner", {})
                owner["type"] = owner_type
                updates["owner"] = owner
                fields_enriched.append("owner.type")
                self._increment_field_stat("owner.type")
                
                # Si es Organization, agregar organization_id
                if owner_type == "Organization" and not repo.get("organization_id"):
                    updates["organization_id"] = owner.get("id")
                    fields_enriched.append("organization_id")
                    self._increment_field_stat("organization_id")
        
        # 14. License info completa (REST API)
        license_info = repo.get("license_info", {})
        if license_info and (not license_info.get("key") or not license_info.get("url")):
            logger.debug(f"  ├─ Obteniendo licencia completa...")
            complete_license = self._retry_with_backoff(self._fetch_license_info_rest, name_with_owner)
            if complete_license:
                updates["license_info"] = complete_license
                fields_enriched.extend(["license_info.key", "license_info.url"])
                self._increment_field_stat("license_info.key")
                self._increment_field_stat("license_info.url")
        
        # 15. Campos adicionales desde REST API
        logger.debug(f"  ├─ Obteniendo campos adicionales (REST)...")
        additional_fields = self._retry_with_backoff(self._fetch_additional_fields_rest, name_with_owner, repo)
        if additional_fields:
            updates.update(additional_fields)
            fields_enriched.extend(additional_fields.keys())
            for field in additional_fields.keys():
                self._increment_field_stat(field)
        
        # 16. Campos adicionales desde GraphQL
        logger.debug(f"  ├─ Obteniendo campos adicionales (GraphQL)...")
        graphql_fields = self._retry_with_backoff(self._fetch_additional_fields_graphql, name_with_owner, repo)
        if graphql_fields:
            updates.update(graphql_fields)
            fields_enriched.extend(graphql_fields.keys())
            for field in graphql_fields.keys():
                self._increment_field_stat(field)
        
        # 17. Merged PRs count desde REST API (búsqueda)
        if repo.get("merged_pull_requests_count", 0) == 0:
            logger.debug(f"  ├─ Contando PRs merged...")
            merged_count = self._retry_with_backoff(self._fetch_merged_prs_count_rest, name_with_owner)
            if merged_count and merged_count > 0:
                updates["merged_pull_requests_count"] = merged_count
                fields_enriched.append("merged_pull_requests_count")
                self._increment_field_stat("merged_pull_requests_count")
        
        # 18. Colaboradores completos (contributors + mentionableUsers)
        if not repo.get("collaborators") or len(repo.get("collaborators", [])) == 0:
            logger.debug(f"  └─ Obteniendo colaboradores (puede tardar)...")
            collaborators_data = self._retry_with_backoff(self._fetch_collaborators_combined, name_with_owner)
            if collaborators_data:
                updates["collaborators"] = collaborators_data["collaborators"]
                updates["collaborators_count"] = collaborators_data["count"]
                fields_enriched.extend(["collaborators", "collaborators_count"])
                self._increment_field_stat("collaborators")
                self._increment_field_stat("collaborators_count")
            else:
                fields_missing.append("collaborators")
        
        # Agregar enrichment_status
        is_complete = len(fields_missing) == 0
        updates["enrichment_status"] = {
            "is_complete": is_complete,
            "last_enriched": datetime.now().isoformat(),
            "fields_enriched": list(set(fields_enriched)),
            "fields_missing": list(set(fields_missing)),
            "total_fields_enriched": len(set(fields_enriched))
        }
        
        # Actualizar en MongoDB si hay cambios
        if updates:
            updates["updated_at"] = datetime.now()
            self.repos_repository.collection.update_one(
                {"id": repo_id},
                {"$set": updates}
            )
            
            # Logging detallado
            status_icon = "✅" if is_complete else "⚠️"
            logger.info(f"  {status_icon} COMPLETADO: {len(updates)} campos actualizados, {len(set(fields_enriched))} enriquecidos")
            
            if fields_missing:
                logger.warning(f"  ❌ Campos faltantes: {', '.join(fields_missing)}")
            else:
                logger.info(f"  🎉 Repositorio completamente enriquecido!")
        else:
            logger.info(f"  ℹ️  Sin cambios necesarios")
    
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
                logger.debug(f"    ✓ README obtenido ({len(content)} caracteres)")
                return content
            elif response.status_code == 404:
                logger.debug(f"    ℹ️  Sin README disponible")
                return None
            elif response.status_code == 403:
                # Rate limit o acceso denegado - propagar para reintentar
                raise requests.exceptions.RequestException(f"HTTP 403: {response.text[:100]}")
            elif response.status_code >= 500:
                # Error de servidor - propagar para reintentar
                raise requests.exceptions.RequestException(f"HTTP {response.status_code}: Error de servidor GitHub")
            else:
                logger.warning(f"    ⚠️  Error HTTP {response.status_code}")
                return None
        except requests.exceptions.Timeout:
            # Propagar timeout para que se reintente
            logger.debug(f"    ⏱️  Timeout obteniendo README")
            raise
        except requests.exceptions.RequestException:
            # Propagar errores de red para que se reintenten
            raise
        except Exception as e:
            logger.error(f"    ❌ Error inesperado: {type(e).__name__}: {e}")
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
            elif response.status_code == 404:
                # Repo sin releases - normal
                logger.debug(f"    ℹ️  Sin releases disponibles")
                return None
            elif response.status_code == 403:
                # Rate limit - propagar para reintentar
                raise requests.exceptions.RequestException(f"HTTP 403: {response.text[:100]}")
            elif response.status_code >= 500:
                # Error de servidor - propagar para reintentar
                raise requests.exceptions.RequestException(f"HTTP {response.status_code}: Error de servidor")
            else:
                logger.warning(f"    ⚠️  Error HTTP {response.status_code}")
                return None
        except requests.exceptions.Timeout:
            logger.debug(f"    ⏱️  Timeout obteniendo releases")
            raise
        except requests.exceptions.RequestException:
            raise
        except Exception as e:
            logger.error(f"    ❌ Error inesperado: {type(e).__name__}: {e}")
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
    
    def _fix_simple_fields(self, repo: Dict[str, Any]) -> Dict[str, Any]:
        """Corrige campos simples que son copias directas de otros campos."""
        updates = {}
        
        # node_id es igual a id
        if not repo.get("node_id") and repo.get("id"):
            updates["node_id"] = repo["id"]
            self._increment_field_stat("node_id")
        
        # full_name es igual a name_with_owner
        if not repo.get("full_name") and repo.get("name_with_owner"):
            updates["full_name"] = repo["name_with_owner"]
            self._increment_field_stat("full_name")
        
        return updates
    
    def _fetch_owner_type_rest(self, name_with_owner: str) -> Optional[str]:
        """
        Obtiene el tipo de owner (User/Organization) desde la REST API.
        
        Args:
            name_with_owner: Nombre completo del repo (e.g., "Qiskit/qiskit")
        
        Returns:
            "User" o "Organization", o None si hay error
        """
        try:
            owner_login = name_with_owner.split("/")[0]
            url = f"https://api.github.com/users/{owner_login}"
            
            response = requests.get(url, headers=self.rest_headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                return data.get("type")  # "User" o "Organization"
            else:
                logger.warning(f"⚠️  Error al obtener owner type para {owner_login}: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"❌ Error en _fetch_owner_type_rest para {name_with_owner}: {e}")
            return None
    
    def _fetch_license_info_rest(self, name_with_owner: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene información completa de licencia desde la REST API.
        
        Args:
            name_with_owner: Nombre completo del repo (e.g., "Qiskit/qiskit")
        
        Returns:
            Diccionario con todos los campos de licencia o None
        """
        try:
            url = f"https://api.github.com/repos/{name_with_owner}"
            response = requests.get(url, headers=self.rest_headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                license_data = data.get("license")
                
                if license_data:
                    return {
                        "key": license_data.get("key"),
                        "name": license_data.get("name"),
                        "spdx_id": license_data.get("spdx_id"),
                        "url": license_data.get("url"),
                        "nickname": None  # La REST API no tiene nickname
                    }
            else:
                logger.warning(f"⚠️  Error al obtener licencia para {name_with_owner}: {response.status_code}")
            
            return None
        except Exception as e:
            logger.error(f"❌ Error en _fetch_license_info_rest para {name_with_owner}: {e}")
            return None
    
    def _fetch_additional_fields_rest(self, name_with_owner: str, current_repo: Dict[str, Any]) -> Dict[str, Any]:
        """
        Obtiene campos adicionales desde la REST API que no están en GraphQL.
        
        Args:
            name_with_owner: Nombre completo del repo (e.g., "Qiskit/qiskit")
            current_repo: Documento actual del repositorio
        
        Returns:
            Diccionario con campos adicionales a actualizar
        """
        updates = {}
        
        try:
            url = f"https://api.github.com/repos/{name_with_owner}"
            response = requests.get(url, headers=self.rest_headers, timeout=10)
            
            if response.status_code != 200:
                logger.warning(f"⚠️  Error al obtener campos adicionales para {name_with_owner}: {response.status_code}")
                return updates
            
            data = response.json()
            
            # subscribers_count (watchers reales)
            if current_repo.get("subscribers_count", 0) == 0:
                subscribers = data.get("subscribers_count", 0)
                if subscribers > 0:
                    updates["subscribers_count"] = subscribers
            
            # network_count (forks totales en toda la red)
            if current_repo.get("network_count", 0) == 0:
                network = data.get("network_count", 0)
                if network > 0:
                    updates["network_count"] = network
            
            # has_projects_enabled
            if current_repo.get("has_projects_enabled") is None:
                has_projects = data.get("has_projects", False)
                updates["has_projects_enabled"] = has_projects
            
            # has_discussions_enabled
            if current_repo.get("has_discussions_enabled") is None:
                has_discussions = data.get("has_discussions", False)
                updates["has_discussions_enabled"] = has_discussions
            
            # Parent info (si es un fork)
            if current_repo.get("is_fork") and not current_repo.get("parent_id"):
                parent = data.get("parent")
                if parent:
                    updates["parent_id"] = parent.get("node_id")
                    updates["parent_name_with_owner"] = parent.get("full_name")
            
            # Mirror URL (si es un mirror)
            if current_repo.get("is_mirror") and not current_repo.get("mirror_url"):
                mirror_url = data.get("mirror_url")
                if mirror_url:
                    updates["mirror_url"] = mirror_url
            
            # Security and analysis
            security = data.get("security_and_analysis")
            if security:
                updates["is_security_policy_enabled"] = security.get("advanced_security", {}).get("status") == "enabled"
            
            return updates
            
        except Exception as e:
            logger.error(f"❌ Error en _fetch_additional_fields_rest para {name_with_owner}: {e}")
            return updates
    
    def _fetch_additional_fields_graphql(self, name_with_owner: str, current_repo: Dict[str, Any]) -> Dict[str, Any]:
        """
        Obtiene campos adicionales desde GraphQL que no están en la ingesta inicial.
        
        Args:
            name_with_owner: Nombre completo del repo (e.g., "Qiskit/qiskit")
            current_repo: Documento actual del repositorio
        
        Returns:
            Diccionario con campos adicionales a actualizar
        """
        updates = {}
        
        try:
            owner, name = name_with_owner.split("/")
            
            query = """
            query($owner: String!, $name: String!) {
              repository(owner: $owner, name: $name) {
                codeOfConduct {
                  name
                  url
                }
                fundingLinks {
                  platform
                  url
                }
                discussionCategories(first: 1) {
                  totalCount
                }
                hasProjectsEnabled
                vulnerabilityAlerts(first: 1) {
                  totalCount
                }
                isSecurityPolicyEnabled
                mergedPullRequests: pullRequests(states: MERGED) {
                  totalCount
                }
              }
            }
            """
            
            variables = {"owner": owner, "name": name}
            result = self.graphql_client.execute_query(query, variables)
            
            # El resultado viene dentro de "data"
            if result:
                data = result.get("data", result)  # Compatibilidad con ambos formatos
                if data and "repository" in data and data["repository"]:
                    repo_data = data["repository"]
                    
                    # Code of Conduct
                    if not current_repo.get("code_of_conduct"):
                        code_of_conduct = repo_data.get("codeOfConduct")
                        if code_of_conduct:
                            updates["code_of_conduct"] = {
                                "name": code_of_conduct.get("name"),
                                "url": code_of_conduct.get("url")
                            }
                    
                    # Funding Links
                    if not current_repo.get("funding_links") or len(current_repo.get("funding_links", [])) == 0:
                        funding_links = repo_data.get("fundingLinks", [])
                        if funding_links:
                            updates["funding_links"] = [
                                {
                                    "platform": link.get("platform"),
                                    "url": link.get("url")
                                }
                                for link in funding_links
                            ]
                    
                    # Discussions count
                    if current_repo.get("discussions_count", 0) == 0:
                        discussions = repo_data.get("discussionCategories", {}).get("totalCount", 0)
                        if discussions > 0:
                            updates["discussions_count"] = discussions
                    
                    # Projects enabled
                    if current_repo.get("has_projects_enabled") is None:
                        has_projects = repo_data.get("hasProjectsEnabled", False)
                        updates["has_projects_enabled"] = has_projects
                    
                    # Vulnerability alerts count
                    if current_repo.get("vulnerability_alerts_count", 0) == 0:
                        vuln_alerts = repo_data.get("vulnerabilityAlerts", {}).get("totalCount", 0)
                        if vuln_alerts > 0:
                            updates["vulnerability_alerts_count"] = vuln_alerts
                    
                    # Security policy enabled
                    if current_repo.get("is_security_policy_enabled") is None:
                        security_policy = repo_data.get("isSecurityPolicyEnabled", False)
                        updates["is_security_policy_enabled"] = security_policy
                    
                    # Merged pull requests count
                    if current_repo.get("merged_pull_requests_count", 0) == 0:
                        merged_prs = repo_data.get("mergedPullRequests", {}).get("totalCount", 0)
                        if merged_prs > 0:
                            updates["merged_pull_requests_count"] = merged_prs
            
            return updates
            
        except Exception as e:
            logger.error(f"❌ Error en _fetch_additional_fields_graphql para {name_with_owner}: {e}")
            return updates
    
    def _fetch_merged_prs_count_rest(self, name_with_owner: str) -> int:
        """
        Obtiene el conteo de PRs mergeados usando la Search API de GitHub.
        
        Args:
            name_with_owner: Nombre completo del repo (e.g., "Qiskit/qiskit")
        
        Returns:
            Conteo de PRs mergeados
        """
        try:
            url = "https://api.github.com/search/issues"
            params = {
                "q": f"repo:{name_with_owner} type:pr is:merged",
                "per_page": 1
            }
            
            response = requests.get(url, headers=self.rest_headers, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                return data.get("total_count", 0)
            else:
                logger.warning(f"⚠️  Error al obtener PRs mergeados para {name_with_owner}: {response.status_code}")
                return 0
                
        except Exception as e:
            logger.error(f"❌ Error en _fetch_merged_prs_count_rest para {name_with_owner}: {e}")
            return 0
    
    def _fetch_collaborators_combined(self, name_with_owner: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene colaboradores combinando contributors (REST) y mentionableUsers (GraphQL).
        
        Estrategia:
        1. Contributors: Usuarios que han hecho commits (REST API)
        2. MentionableUsers: Usuarios que pueden ser mencionados (GraphQL)
        3. Combinar: Marcar quiénes han hecho commits y quiénes no
        
        Args:
            name_with_owner: Nombre completo del repo (e.g., "Qiskit/qiskit")
        
        Returns:
            Diccionario con lista de colaboradores y conteo total
        """
        try:
            # 1. Obtener contributors (REST API)
            contributors = self._fetch_contributors_rest(name_with_owner)
            contributors_logins = {c["login"]: c for c in contributors}
            
            # 2. Obtener mentionableUsers (GraphQL)
            mentionable = self._fetch_mentionable_users_graphql(name_with_owner)
            
            # 3. Combinar ambas listas
            collaborators_map = {}
            
            # Primero, agregar todos los contributors (tienen commits)
            for login, contributor_data in contributors_logins.items():
                collaborators_map[login] = {
                    "login": login,
                    "id": contributor_data.get("id"),
                    "avatar_url": contributor_data.get("avatar_url"),
                    "type": contributor_data.get("type"),
                    "contributions": contributor_data.get("contributions", 0),
                    "has_commits": True,
                    "is_mentionable": login in [m["login"] for m in mentionable]
                }
            
            # Luego, agregar mentionableUsers que NO están en contributors
            for mentionable_user in mentionable:
                login = mentionable_user["login"]
                if login not in collaborators_map:
                    collaborators_map[login] = {
                        "login": login,
                        "id": mentionable_user.get("id"),
                        "avatar_url": mentionable_user.get("avatar_url"),
                        "type": mentionable_user.get("type"),
                        "contributions": 0,
                        "has_commits": False,
                        "is_mentionable": True
                    }
            
            # Convertir a lista ordenada por contributions
            collaborators_list = sorted(
                collaborators_map.values(),
                key=lambda x: x["contributions"],
                reverse=True
            )
            
            return {
                "collaborators": collaborators_list,
                "count": len(collaborators_list)
            }
            
        except Exception as e:
            logger.error(f"❌ Error en _fetch_collaborators_combined para {name_with_owner}: {e}")
            return None
    
    def _fetch_contributors_rest(self, name_with_owner: str, max_contributors: int = None) -> List[Dict[str, Any]]:
        """
        Obtiene la lista COMPLETA de contributors (usuarios que han hecho commits) desde REST API.
        Usa paginación con Link headers para obtener TODOS los contributors, no solo los primeros 100.
        
        Args:
            name_with_owner: Nombre completo del repo (e.g., "Qiskit/qiskit")
            max_contributors: Número máximo de contributors a obtener (None = todos)
        
        Returns:
            Lista de contributors
        """
        try:
            url = f"https://api.github.com/repos/{name_with_owner}/contributors"
            all_contributors = []
            page = 1
            per_page = 100  # Máximo permitido por REST API
            
            logger.info(f"🔄 Recuperando contributors para {name_with_owner}...")
            
            while True:
                params = {
                    "per_page": per_page,
                    "anon": "false",  # Excluir usuarios anónimos
                    "page": page
                }
                
                response = requests.get(url, headers=self.rest_headers, params=params, timeout=10)
                
                if response.status_code != 200:
                    logger.warning(f"⚠️  Error al obtener contributors para {name_with_owner}: {response.status_code}")
                    break
                
                contributors = response.json()
                
                if not contributors:  # No hay más contributors
                    break
                
                # Agregar contributors de esta página
                for c in contributors:
                    if c.get("login"):
                        all_contributors.append({
                            "login": c.get("login"),
                            "id": c.get("node_id"),
                            "avatar_url": c.get("avatar_url"),
                            "type": c.get("type"),
                            "contributions": c.get("contributions", 0)
                        })
                        
                        # Romper si alcanzamos el límite
                        if max_contributors and len(all_contributors) >= max_contributors:
                            break
                
                logger.info(f"   Página {page}: +{len(contributors)} contributors (total: {len(all_contributors)})")
                
                # Si alcanzamos el límite o no hay más páginas, salir
                if max_contributors and len(all_contributors) >= max_contributors:
                    break
                
                # Verificar si hay más páginas usando Link header
                link_header = response.headers.get("Link", "")
                if "next" not in link_header:
                    break
                
                page += 1
                
                # Logging de progreso cada N páginas
                log_every = self.config.get("enrichment", {}).get("log_progress_every_n_pages", 100)
                if page % log_every == 0:
                    logger.info(f"📊 Progreso: {page} páginas procesadas, {len(all_contributors)} contributors acumulados")
                
                # Seguridad: evitar bucles infinitos (límite configurable)
                max_pages = self.config.get("enrichment", {}).get("max_collaborator_pages", 1000)
                if page > max_pages:
                    logger.warning(f"⚠️  Límite de páginas alcanzado ({max_pages} páginas, {len(all_contributors)} contributors)")
                    break
            
            logger.info(f"✅ Recuperados {len(all_contributors)} contributors para {name_with_owner}")
            
            return all_contributors
                
        except Exception as e:
            logger.error(f"❌ Error en _fetch_contributors_rest para {name_with_owner}: {e}")
            return []
    
    def _fetch_mentionable_users_graphql(self, name_with_owner: str, max_users: int = None) -> List[Dict[str, Any]]:
        """
        Obtiene la lista COMPLETA de mentionableUsers (usuarios que pueden ser mencionados) desde GraphQL.
        Usa paginación con cursores para obtener TODOS los usuarios, no solo los primeros 100.
        
        Args:
            name_with_owner: Nombre completo del repo (e.g., "Qiskit/qiskit")
            max_users: Número máximo de usuarios a obtener (None = todos)
        
        Returns:
            Lista de usuarios mencionables
        """
        try:
            owner, name = name_with_owner.split("/")
            
            # Query con paginación usando cursores
            query = """
            query($owner: String!, $name: String!, $first: Int!, $after: String) {
              repository(owner: $owner, name: $name) {
                mentionableUsers(first: $first, after: $after) {
                  totalCount
                  pageInfo {
                    hasNextPage
                    endCursor
                  }
                  nodes {
                    id
                    login
                    avatarUrl
                    name
                    email
                  }
                }
              }
            }
            """
            
            all_users = []
            has_next_page = True
            after_cursor = None
            page = 1
            per_page = 100  # Máximo permitido por GraphQL
            
            # Primera petición para obtener el totalCount
            variables = {
                "owner": owner,
                "name": name,
                "first": per_page,
                "after": None
            }
            
            result = self.graphql_client.execute_query(query, variables)
            
            if not result:
                return []
            
            data = result.get("data", result)
            if not data or "repository" not in data:
                return []
            
            repo_data = data["repository"]
            mentionable_data = repo_data.get("mentionableUsers", {})
            total_count = mentionable_data.get("totalCount", 0)
            
            logger.info(f"📊 Total de mentionableUsers para {name_with_owner}: {total_count}")
            
            # Si max_users está definido y es menor que el total, limitamos
            target_count = min(max_users, total_count) if max_users else total_count
            
            logger.info(f"� Recuperando {target_count} mentionableUsers mediante paginación...")
            
            # Iterar paginación hasta obtener todos los usuarios
            while has_next_page and len(all_users) < target_count:
                variables = {
                    "owner": owner,
                    "name": name,
                    "first": per_page,
                    "after": after_cursor
                }
                
                result = self.graphql_client.execute_query(query, variables)
                
                if not result:
                    break
                
                data = result.get("data", result)
                if not data or "repository" not in data:
                    break
                
                repo_data = data["repository"]
                mentionable_data = repo_data.get("mentionableUsers", {})
                
                users = mentionable_data.get("nodes", [])
                page_info = mentionable_data.get("pageInfo", {})
                
                # Agregar usuarios de esta página
                for u in users:
                    if u.get("login"):
                        all_users.append({
                            "login": u.get("login"),
                            "id": u.get("id"),
                            "avatar_url": u.get("avatarUrl"),
                            "name": u.get("name"),
                            "email": u.get("email"),
                            "type": "User"  # GraphQL no devuelve type, asumimos User
                        })
                        
                        # Romper si alcanzamos el límite
                        if max_users and len(all_users) >= max_users:
                            break
                
                # Actualizar paginación
                has_next_page = page_info.get("hasNextPage", False)
                after_cursor = page_info.get("endCursor")
                
                logger.info(f"   Página {page}: +{len(users)} usuarios (total: {len(all_users)}/{target_count})")
                page += 1
                
                # Logging de progreso cada N páginas
                log_every = self.config.get("enrichment", {}).get("log_progress_every_n_pages", 100)
                if page % log_every == 0:
                    logger.info(f"📊 Progreso: {page} páginas procesadas, {len(all_users)} usuarios acumulados de {target_count}")
                
                # Seguridad: evitar bucles infinitos (límite configurable)
                max_pages = self.config.get("enrichment", {}).get("max_collaborator_pages", 1000)
                if page > max_pages:
                    logger.warning(f"⚠️  Límite de páginas alcanzado ({max_pages} páginas, {len(all_users)} usuarios de {target_count})")
                    break
            
            logger.info(f"✅ Recuperados {len(all_users)} mentionableUsers para {name_with_owner}")
            
            return all_users
            
        except Exception as e:
            logger.error(f"❌ Error en _fetch_mentionable_users_graphql para {name_with_owner}: {e}")
            return []
