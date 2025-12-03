"""
Motor de Enriquecimiento de Organizaciones de GitHub - v1.0

ESTRATEGIA:
- Una super-query GraphQL por organización (optimizado)
- Calcula quantum_focus_score basado en repos quantum de la BD
- Identifica top contributors a repos quantum
- Determina is_quantum_focused (threshold: 30%)
- Batch processing con rate limiting
"""

import time
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from .graphql_client import GitHubGraphQLClient
from ..core.logger import logger
from ..core.mongo_repository import MongoRepository


class OrganizationEnrichmentEngine:
    """
    Motor para enriquecer organizaciones con métricas quantum.
    Calcula scores basándose en repos quantum de la BD local.
    """
    
    ENRICHMENT_VERSION = "1.0.0"
    
    # Query GraphQL para obtener repos y miembros de la organización
    ENRICHMENT_QUERY = """
    query GetOrganizationEnrichment($login: String!) {
      organization(login: $login) {
        id
        login
        
        # Repositorios (primeros 100, ordenados por estrellas)
        repositories(first: 100, orderBy: {field: STARGAZERS, direction: DESC}, privacy: PUBLIC) {
          totalCount
          nodes {
            id
            name
            nameWithOwner
            primaryLanguage {
              name
            }
            stargazerCount
          }
        }
        
        # Miembros con rol
        membersWithRole(first: 100) {
          totalCount
          nodes {
            login
            name
            avatarUrl
          }
        }
      }
    }
    """
    
    def __init__(
        self,
        github_token: str,
        organizations_repository: MongoRepository,
        repositories_repository: MongoRepository,
        users_repository: MongoRepository,
        batch_size: int = 5,
        sleep_time: float = 0.5,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Inicializa el motor de enriquecimiento.
        
        Args:
            github_token: Token de GitHub
            organizations_repository: Repositorio de organizaciones
            repositories_repository: Repositorio de repositorios (para buscar quantum repos)
            users_repository: Repositorio de usuarios (para contributors)
            batch_size: Tamaño del lote (default 5 para Rate Limit)
            sleep_time: Tiempo de espera entre requests (default 0.5s)
            config: Configuración opcional
        """
        self.github_token = github_token
        self.orgs_repository = organizations_repository
        self.repos_repository = repositories_repository
        self.users_repository = users_repository
        self.batch_size = batch_size
        self.sleep_time = sleep_time
        self.config = config or {}
        self.graphql_client = GitHubGraphQLClient(github_token)
        
        # Estadísticas
        self.stats = {
            "total_processed": 0,
            "total_enriched": 0,
            "total_skipped": 0,
            "total_errors": 0,
            "start_time": None,
            "end_time": None
        }
        
        logger.info(f"🚀 OrganizationEnrichmentEngine v1.0 inicializado (batch_size={batch_size}, sleep_time={sleep_time}s)")
    
    def enrich_all_organizations(
        self, 
        max_orgs: Optional[int] = None, 
        force_reenrich: bool = False
    ) -> Dict[str, Any]:
        """
        Enriquece todas las organizaciones en MongoDB.
        
        Args:
            max_orgs: Límite opcional de organizaciones a procesar
            force_reenrich: Si True, re-enriquece incluso organizaciones ya enriquecidas
            
        Returns:
            Estadísticas del proceso
        """
        logger.info("=" * 80)
        logger.info("🏢 INICIANDO ENRIQUECIMIENTO DE ORGANIZACIONES v1.0")
        logger.info("=" * 80)
        
        self.stats["start_time"] = datetime.now()
        
        # Construir query para seleccionar organizaciones
        if force_reenrich:
            query = {}
            logger.info("📌 Modo force_reenrich: procesando todas las organizaciones")
        else:
            # Re-enriquecer si:
            # 1. enrichment_status es null o no existe
            # 2. enriched_at es null o no existe
            # 3. No está completo (is_complete = false)
            # 4. Más de 7 días desde la última actualización
            seven_days_ago = datetime.now() - timedelta(days=7)
            query = {
                "$or": [
                    {"enrichment_status": {"$exists": False}},
                    {"enrichment_status": None},
                    {"enriched_at": {"$exists": False}},
                    {"enriched_at": None},
                    {"enrichment_status.is_complete": False},
                    {"enriched_at": {"$lt": seven_days_ago}}
                ]
            }
            logger.info("📌 Modo incremental: organizaciones sin enriquecer, incompletas o desactualizadas (>7 días)")
        
        # Obtener organizaciones
        orgs_cursor = self.orgs_repository.collection.find(query)
        
        if max_orgs:
            orgs_cursor = orgs_cursor.limit(max_orgs)
            logger.info(f"📊 Limitando a {max_orgs} organizaciones")
        
        orgs = list(orgs_cursor)
        total_orgs = len(orgs)
        
        logger.info(f"📊 Total organizaciones a enriquecer: {total_orgs}")
        
        if total_orgs == 0:
            logger.info("✅ No hay organizaciones para enriquecer")
            return self._finalize_stats()
        
        # Procesar en lotes
        for i in range(0, total_orgs, self.batch_size):
            batch = orgs[i:i + self.batch_size]
            batch_num = i // self.batch_size + 1
            total_batches = (total_orgs + self.batch_size - 1) // self.batch_size
            
            logger.info(f"\n📦 Procesando lote {batch_num}/{total_batches} ({len(batch)} organizaciones)")
            
            for org in batch:
                self._enrich_single_organization(org)
                
                # Sleep para evitar rate limits
                time.sleep(self.sleep_time)
            
            logger.info(f"✅ Lote {batch_num}/{total_batches} completado")
        
        return self._finalize_stats()
    
    def _enrich_single_organization(self, org: Dict[str, Any]) -> bool:
        """
        Enriquece una sola organización.
        
        Args:
            org: Documento de organización de MongoDB
            
        Returns:
            True si se enriqueció correctamente, False si hubo error
        """
        login = org.get("login")
        
        try:
            logger.info(f"\n🏢 Enriqueciendo organización: {login}")
            
            # ==================== SUPER-QUERY: UNA SOLA LLAMADA ====================
            graphql_data = self._fetch_organization_data(login)
            
            if not graphql_data:
                logger.warning(f"⚠️  No se pudo obtener datos de {login}")
                self.stats["total_errors"] += 1
                return False
            
            # ==================== PROCESAR DATOS ====================
            updates = {}
            
            # Obtener totales de la API
            updates["total_repositories_count"] = graphql_data.get("repositories", {}).get("totalCount", 0)
            updates["total_members_count"] = graphql_data.get("membersWithRole", {}).get("totalCount", 0)
            
            # ==================== IDENTIFICAR REPOS QUANTUM ====================
            quantum_repos_data = self._find_quantum_repositories(login, org)
            
            if quantum_repos_data:
                updates["quantum_repositories"] = quantum_repos_data["repo_ids"]
                updates["quantum_repositories_count"] = len(quantum_repos_data["repo_ids"])
                
                # Top contributors a repos quantum
                top_contributors = self._find_top_quantum_contributors(quantum_repos_data["repo_ids"])
                updates["top_quantum_contributors"] = top_contributors
                updates["quantum_contributors_count"] = len(top_contributors)
                
                # Stack tecnológico (top lenguajes)
                top_languages = self._calculate_top_languages(quantum_repos_data["repo_ids"])
                updates["top_languages"] = top_languages
                
                # Prestigio acumulado (suma de estrellas)
                total_stars = self._calculate_total_stars(quantum_repos_data["repo_ids"])
                updates["total_stars"] = total_stars
            else:
                updates["quantum_repositories"] = []
                updates["quantum_repositories_count"] = 0
                updates["top_quantum_contributors"] = []
                updates["quantum_contributors_count"] = 0
                updates["top_languages"] = []
                updates["total_stars"] = 0
            
            # ==================== CALCULAR QUANTUM FOCUS SCORE ====================
            quantum_score = self._calculate_quantum_focus_score(
                quantum_count=updates["quantum_repositories_count"],
                total_count=updates["total_repositories_count"],
                is_verified=org.get("is_verified", False),
                org_name=org.get("name", ""),
                org_description=org.get("description", "")
            )
            
            if quantum_score is not None:
                updates["quantum_focus_score"] = quantum_score
                updates["is_quantum_focused"] = quantum_score >= 30.0  # Threshold: 30%
            
            # Timestamp de enriquecimiento
            updates["enriched_at"] = datetime.now()
            
            # ==================== ENRICHMENT STATUS ====================
            updates["enrichment_status"] = {
                "is_complete": True,
                "version": self.ENRICHMENT_VERSION,
                "last_check": datetime.now().isoformat(),
                "fields_missing": []
            }
            
            # ==================== GUARDAR EN BD ====================
            self.orgs_repository.collection.update_one(
                {"_id": org.get("_id")},
                {"$set": updates}
            )
            
            self.stats["total_enriched"] += 1
            logger.info(f"✅ Organización {login} enriquecida correctamente")
            logger.info(f"   📊 Repos quantum: {updates['quantum_repositories_count']}/{updates['total_repositories_count']}")
            logger.info(f"   🎯 Quantum score: {updates.get('quantum_focus_score', 0):.2f}%")
            logger.info(f"   ⭐ Total estrellas: {updates.get('total_stars', 0)}")
            
            # Mostrar top lenguajes
            if updates.get('top_languages'):
                top_3_langs = updates['top_languages'][:3]
                langs_str = ", ".join([f"{lang['name']} ({lang['percentage']:.1f}%)" for lang in top_3_langs])
                logger.info(f"   💻 Top lenguajes: {langs_str}")
            
            # Mostrar info de relevancia
            if org.get("is_relevant"):
                discovered_repos = org.get("discovered_from_repos", [])
                if discovered_repos:
                    repo_names = [repo.get("name", "") for repo in discovered_repos if isinstance(repo, dict)]
                    if repo_names:
                        logger.info(f"   ✅ Relevante - Descubierta desde: {', '.join(repo_names[:3])}")
                        if len(repo_names) > 3:
                            logger.info(f"      ... y {len(repo_names) - 3} repos más")
            else:
                logger.info(f"   ⚠️  No relevante - Sin repos quantum ingestados")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error enriqueciendo organización {login}: {e}")
            self.stats["total_errors"] += 1
            return False
        
        finally:
            self.stats["total_processed"] += 1
    
    def _fetch_organization_data(self, login: str) -> Optional[Dict[str, Any]]:
        """
        Ejecuta la super-query para obtener datos de la organización.
        
        Args:
            login: Login de la organización
            
        Returns:
            Datos de la organización o None si falla
        """
        try:
            variables = {"login": login}
            response = self.graphql_client.execute_query(self.ENRICHMENT_QUERY, variables)
            
            if "errors" in response:
                logger.error(f"❌ Error GraphQL para {login}: {response['errors']}")
                return None
            
            return response.get("data", {}).get("organization")
            
        except Exception as e:
            logger.error(f"❌ Error ejecutando super-query para {login}: {e}")
            return None
    
    def _find_quantum_repositories(self, org_login: str, org: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Encuentra repositorios quantum de la organización en nuestra BD.
        
        Args:
            org_login: Login de la organización
            org: Documento de organización
            
        Returns:
            Dict con repo_ids y metadata o None
        """
        try:
            # Buscar repos de la org en nuestra BD
            # Si está en repositories, ya es quantum-related (pasó filtros)
            quantum_repos = list(self.repos_repository.collection.find({
                "owner.login": org_login
            }))
            
            if not quantum_repos:
                return None
            
            repo_ids = [repo.get("id") for repo in quantum_repos if repo.get("id")]
            
            return {
                "repo_ids": repo_ids,
                "repos": quantum_repos
            }
            
        except Exception as e:
            logger.error(f"❌ Error buscando repos quantum de {org_login}: {e}")
            return None
    
    def _find_top_quantum_contributors(self, repo_ids: List[str], limit: int = 10) -> List[Dict[str, str]]:
        """
        Encuentra los top contributors a repos quantum de la organización.
        
        Args:
            repo_ids: IDs de repositorios quantum
            limit: Número máximo de contributors
            
        Returns:
            Lista de diccionarios con {id, login} de los top contributors
        """
        try:
            # Agregación para contar contribuciones por usuario
            pipeline = [
                # Filtrar usuarios que tienen extracted_from
                {"$match": {"extracted_from": {"$exists": True, "$ne": []}}},
                
                # Desenrollar extracted_from
                {"$unwind": "$extracted_from"},
                
                # Filtrar solo repos quantum
                {"$match": {"extracted_from.repo_id": {"$in": repo_ids}}},
                
                # Agrupar por usuario y sumar contribuciones
                {"$group": {
                    "_id": "$id",
                    "login": {"$first": "$login"},
                    "total_contributions": {"$sum": "$extracted_from.contributions"}
                }},
                
                # Ordenar por contribuciones (descendente)
                {"$sort": {"total_contributions": -1}},
                
                # Limitar a top N
                {"$limit": limit}
            ]
            
            results = list(self.users_repository.collection.aggregate(pipeline))
            
            # Retornar lista con {id, login}
            contributors = []
            for result in results:
                user_id = result.get("_id")
                user_login = result.get("login")
                if user_id and user_login:
                    contributors.append({
                        "id": user_id,
                        "login": user_login
                    })
            
            return contributors
            
        except Exception as e:
            logger.error(f"❌ Error buscando top contributors: {e}")
            return []
    
    def _calculate_top_languages(self, repo_ids: List[str], limit: int = 10) -> List[Dict[str, Any]]:
        """
        Calcula el stack tecnológico (top lenguajes) de los repos quantum.
        
        Args:
            repo_ids: Lista de IDs de repositorios quantum
            limit: Número máximo de lenguajes a retornar
            
        Returns:
            Lista de diccionarios con {name, percentage, repo_count}
        """
        try:
            from collections import Counter
            
            if not repo_ids:
                return []
            
            # Buscar repos en la BD por sus IDs
            repos = list(self.repos_repository.collection.find(
                {"id": {"$in": repo_ids}},
                {"primary_language": 1, "_id": 0}
            ))
            
            if not repos:
                return []
            
            # Contar lenguajes y repos que los usan
            language_counter = Counter()
            repos_per_language = {}
            
            for repo in repos:
                primary_language = repo.get("primary_language", {})
                
                # Verificar que sea un dict y tenga el campo name
                if isinstance(primary_language, dict):
                    lang_name = primary_language.get("name")
                elif isinstance(primary_language, str):
                    lang_name = primary_language
                else:
                    continue
                
                if lang_name:
                    language_counter[lang_name] += 1
                    repos_per_language[lang_name] = repos_per_language.get(lang_name, 0) + 1
            
            if not language_counter:
                return []
            
            # Calcular porcentajes
            total_repos = len(repos)
            top_languages = []
            
            for lang_name, count in language_counter.most_common(limit):
                percentage = (count / total_repos) * 100
                top_languages.append({
                    "name": lang_name,
                    "percentage": round(percentage, 2),
                    "repo_count": count
                })
            
            return top_languages
            
        except Exception as e:
            logger.error(f"❌ Error calculando top languages: {e}")
            return []
    
    def _calculate_total_stars(self, repo_ids: List[str]) -> int:
        """
        Calcula el prestigio acumulado (suma de estrellas) de los repos quantum.
        
        Args:
            repo_ids: Lista de IDs de repositorios quantum
            
        Returns:
            Suma total de estrellas
        """
        try:
            if not repo_ids:
                return 0
            
            # Buscar repos en la BD por sus IDs
            repos = list(self.repos_repository.collection.find(
                {"id": {"$in": repo_ids}},
                {"stargazer_count": 1, "_id": 0}
            ))
            
            total = 0
            
            for repo in repos:
                stars = repo.get("stargazer_count", 0)
                if isinstance(stars, int) and stars > 0:
                    total += stars
            
            return total
            
        except Exception as e:
            logger.error(f"❌ Error calculando total stars: {e}")
            return 0
    
    def _calculate_quantum_focus_score(
        self,
        quantum_count: int,
        total_count: int,
        is_verified: bool,
        org_name: str,
        org_description: str
    ) -> Optional[float]:
        """
        Calcula el quantum focus score de una organización.
        
        Formula:
        - Base: (quantum_repos / total_repos) * 100
        - Bonus: +10 si tiene keywords quantum en nombre/descripción
        - Multiplicador: x1.2 si es organización verificada
        
        Args:
            quantum_count: Cantidad de repos quantum
            total_count: Total de repos públicos
            is_verified: Si la org está verificada
            org_name: Nombre de la organización
            org_description: Descripción de la organización
            
        Returns:
            Score 0-100 o None si no se puede calcular
        """
        try:
            if total_count == 0:
                return 0.0
            
            # Score base
            score = (quantum_count / total_count) * 100
            
            # Bonus por keywords quantum
            quantum_keywords = [
                "quantum", "qiskit", "cirq", "qubit", "entanglement",
                "qasm", "pennylane", "tket", "braket", "qdk", "ionq"
            ]
            text = f"{org_name or ''} {org_description or ''}".lower()
            if any(keyword in text for keyword in quantum_keywords):
                score += 10
            
            # Multiplicador por verificación
            if is_verified:
                score *= 1.2
            
            # Cap a 100
            return min(score, 100.0)
            
        except Exception as e:
            logger.error(f"❌ Error calculando quantum focus score: {e}")
            return None
    
    def _finalize_stats(self) -> Dict[str, Any]:
        """Finaliza y retorna las estadísticas."""
        self.stats["end_time"] = datetime.now()
        
        if self.stats["start_time"]:
            duration = self.stats["end_time"] - self.stats["start_time"]
            self.stats["duration_seconds"] = duration.total_seconds()
        
        logger.info("\n" + "=" * 80)
        logger.info("📊 RESUMEN DE ENRIQUECIMIENTO DE ORGANIZACIONES")
        logger.info("=" * 80)
        logger.info(f"✅ Total procesadas: {self.stats['total_processed']}")
        logger.info(f"✅ Total enriquecidas: {self.stats['total_enriched']}")
        logger.info(f"❌ Total errores: {self.stats['total_errors']}")
        
        if "duration_seconds" in self.stats:
            logger.info(f"⏱️  Duración: {self.stats['duration_seconds']:.2f} segundos")
        
        return self.stats
