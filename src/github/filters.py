"""
Filtros avanzados de calidad y relevancia para repositorios de software cuántico.

Este módulo implementa filtros adicionales basados en criterios del paper académico
para garantizar que los datos finales sean representativos, activos y realmente 
relacionados con software cuántico.
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import logging
import re

# Usar logging directo para evitar importaciones circulares
logger = logging.getLogger(__name__)


# ============================================================================
# Funciones helper privadas para filtros avanzados
# ============================================================================

def _get_searchable_text(repo: Dict[str, Any]) -> str:
    """
    Extrae texto buscable del repositorio (nombre, descripción, topics, README).
    
    Args:
        repo: Repositorio del que extraer texto
        
    Returns:
        Texto combinado en minúsculas
    """
    name = repo.get("name", "").lower()
    description = repo.get("description") or ""
    description = description.lower()
    
    # Topics
    topics = (repo.get("repositoryTopics") or {}).get("nodes", [])
    topic_names = [
        (topic.get("topic") or {}).get("name", "").lower()
        for topic in topics
    ]
    
    # README (primeras 1000 caracteres para incluir más contexto)
    readme_text = ""
    readme_obj = repo.get("object")
    if readme_obj:
        readme_full = readme_obj.get("text", "")
        readme_text = readme_full[:1000].lower() if readme_full else ""
    
    return f"{name} {description} {' '.join(topic_names)} {readme_text}"


def _has_strong_keywords(text: str, keywords: List[str]) -> bool:
    """
    Verifica si el texto contiene keywords cuánticas fuertes.
    
    Args:
        text: Texto donde buscar (debe estar en minúsculas)
        keywords: Lista de keywords a buscar
        
    Returns:
        True si encuentra al menos una keyword, False si no
    """
    return any(keyword.lower() in text for keyword in keywords)


# ============================================================================
# Constantes para filtro de relevancia contextual
# ============================================================================

# Patrones que NUNCA son computación cuántica
NON_QC_BLACKLIST_PATTERNS = [
    r"\bquantumult\b",                          # Proxy iOS (QuantumultX)
    r"\bquantumultx\b",                         # QuantumultX variante
    r"firefox[\s._-]*quantum",                  # Firefox Quantum
    r"\bquantum[\s._-]*ui\b",                   # UI frameworks genéricos
    r"\bquantumui\b",                            # UI framework AngularJS
    r"\bminecraft\b.*\bquantum|quantum.*\bminecraft\b",  # Gaming
    r"\bdrum[\s._-]*machine\b",                  # Music
    r"\breact[\s._-]*quantum\b|\bquantum[\s._-]*react\b",  # React perf tools
]

# Repos específicos conocidos como Non-QC (por full_name / nameWithOwner)
NON_QC_KNOWN_REPOS = {
    "sahibzada-allahyar/yc-killer",         # AI agents enterprise
    "joaomilho/enterprise",                 # lenguaje satírico
    "nashvail/quttons",                     # botones CSS "Quantum Paper"
    "bloomberg/quantum",                    # C++ coroutine dispatcher
    "foxyproxy/firefox-extension",          # extensión Firefox proxy
    "atilafassina/quantum",                 # Tauri + SolidStart
    "rafaelgoulartb/next-ecommerce",        # "Quantum Ecommerce" Next.js
    "rodyherrera/quantum",                  # alternativa a Vercel/Heroku
    "quantumui/quantumui",                  # UI framework AngularJS
    "mrmayman/quantumlauncher",             # Minecraft launcher
    "kareldonk/quantumgate",                # P2P protocol C++
    "fox-it/quantuminsert",                 # herramienta seguridad NSA
    "heydon/beadz-drum-machine",            # drum machine
    "reactquantum/reactquantum",            # React performance tool
}

# Keywords QC reales para validación de relevancia contextual
REAL_QC_KEYWORDS = [
    # Frameworks y SDKs
    "qiskit", "cirq", "pennylane", "braket", "pyquil", "projectq",
    "strawberry fields", "ocean sdk", "openqasm", "qasm", "quil",
    "tket", "pytket", "stim", "quirk", "silq",
    # Conceptos core
    "qubit", "qubits", "superposition", "entanglement", "decoherence",
    "quantum gate", "quantum circuit", "quantum state", "bloch sphere",
    "hamiltonian", "unitary", "hermitian", "density matrix",
    "wave function", "wavefunction", "quantum mechanics",
    "quantum physics", "quantum theory",
    # Algoritmos
    "grover", "shor", "vqe", "qaoa", "qft", "quantum fourier",
    "quantum walk", "quantum annealing", "adiabatic",
    "variational quantum", "quantum approximate",
    # Hardware
    "quantum processor", "quantum computer", "qpu", "nisq",
    "fault.tolerant", "topological quantum", "trapped.ion",
    "superconducting qubit", "transmon", "quantum hardware",
    # Campos de estudio
    "quantum machine learning", "quantum chemistry", "quantum simulation",
    "quantum error correction", "quantum key distribution", "qkd",
    "quantum teleportation", "quantum cryptography",
    "quantum information", "quantum computing",
    "quantum programming", "quantum software",
    "quantum neural network", "qnn",
    "quantum optics", "photonic quantum",
    # Proveedores
    "ibm quantum", "google quantum", "azure quantum", "aws quantum",
    "rigetti", "ionq", "d-wave", "xanadu", "zapata",
    # Post-quantum (mantener en scope)
    "post-quantum", "post quantum", "pqc", "lattice-based",
    "code-based cryptography", "hash-based signature",
    # Otros QC
    "quantum spin", "many-body", "quantum field",
    "quantum dynamics", "quantum control",
    "quantum sensing", "quantum metrology",
    "quantum communication", "quantum network",
    "quantum internet", "quantum channel",
    "quantum espresso", "quantum optics",
    "quantum transport", "quantum dot",
    "quantum tomography", "quantum noise",
    "quantum measurement", "quantum state",
]


# ============================================================================
# Clase principal de filtros
# ============================================================================

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
        open_issues = (repo.get("openIssues") or {}).get("totalCount", 0)
        closed_issues = (repo.get("closedIssues") or {}).get("totalCount", 0)
        pull_requests = (repo.get("pullRequests") or {}).get("totalCount", 0)
        
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
        topics = (repo.get("repositoryTopics") or {}).get("nodes", [])
        topic_names = [
            (topic.get("topic") or {}).get("name", "").lower()
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
        valid_languages: List[str],
        strong_quantum_keywords: Optional[List[str]] = None
    ) -> bool:
        """
        Verifica que el repositorio use lenguajes válidos (con lógica inteligente).
        
        Estrategia de validación:
        1. Si el lenguaje principal está en valid_languages → ACEPTA
        2. Si algún lenguaje secundario está en valid_languages → ACEPTA
        3. Si contiene keywords cuánticas fuertes (override) → ACEPTA
        4. En cualquier otro caso → RECHAZA
        
        Esto permite capturar repos con Jupyter Notebook, HTML, TypeScript, etc.
        como lenguaje principal, pero que contienen código cuántico en Python/C++
        en lenguajes secundarios o tienen fuerte contenido cuántico.
        
        Args:
            repo: Repositorio a evaluar
            valid_languages: Lista de lenguajes válidos
            strong_quantum_keywords: Keywords cuánticas fuertes que activan override
            
        Returns:
            True si el lenguaje es válido, False si no lo es
        """
        if not valid_languages:
            return True
        
        # Keywords cuánticas fuertes por defecto (frameworks principales)
        if strong_quantum_keywords is None:
            strong_quantum_keywords = [
                "qiskit", "cirq", "pennylane", "braket", "pyquil",
                "quantum algorithm", "quantum circuit", "quantum gate",
                "vqe", "qaoa", "grover", "shor"
            ]
        
        # 1. Verificar lenguaje principal
        primary_language = repo.get("primaryLanguage")
        
        if not primary_language:
            # Sin lenguaje principal: verificar si tiene keywords fuertes
            searchable_text = _get_searchable_text(repo)
            if _has_strong_keywords(searchable_text, strong_quantum_keywords):
                logger.debug(
                    f"Repo aceptado (sin lenguaje principal pero con keywords cuánticas fuertes): "
                    f"{repo.get('nameWithOwner')}"
                )
                return True
            
            logger.debug(
                f"Repo rechazado (sin lenguaje principal): "
                f"{repo.get('nameWithOwner')}"
            )
            return False
        
        primary_lang_name = primary_language.get("name")
        
        # Si lenguaje principal es válido → aceptar directamente
        if primary_lang_name in valid_languages:
            return True
        
        # 2. Verificar lenguajes secundarios
        languages_edges = (repo.get("languages") or {}).get("edges", [])
        secondary_languages = [
            (edge.get("node") or {}).get("name")
            for edge in languages_edges
            if edge.get("node")
        ]
        
        for lang in secondary_languages:
            if lang in valid_languages:
                logger.debug(
                    f"Repo aceptado (lenguaje secundario válido {lang}, "
                    f"aunque lenguaje principal es {primary_lang_name}): "
                    f"{repo.get('nameWithOwner')}"
                )
                return True
        
        # 3. Override por keywords cuánticas fuertes
        searchable_text = _get_searchable_text(repo)
        if _has_strong_keywords(searchable_text, strong_quantum_keywords):
            logger.debug(
                f"Repo aceptado (override por keywords cuánticas fuertes, "
                f"aunque lenguaje principal es {primary_lang_name}): "
                f"{repo.get('nameWithOwner')}"
            )
            return True
        
        # 4. Rechazar si no cumple ningún criterio
        logger.debug(
            f"Repo rechazado (lenguaje principal {primary_lang_name} no válido, "
            f"sin lenguajes secundarios válidos: {secondary_languages}): "
            f"{repo.get('nameWithOwner')}"
        )
        return False
    
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
        watchers = (repo.get("watchers") or {}).get("totalCount", 0)
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

    @staticmethod
    def is_not_blacklisted(repo: Dict[str, Any]) -> bool:
        """
        Verifica que el repositorio NO esté en la blacklist de falsos positivos.
        
        Comprueba:
        1. Lista de repos conocidos como Non-QC (por nombre exacto)
        2. Patrones regex de contextos no-QC (QuantumultX, Firefox Quantum, etc.)
        
        Args:
            repo: Repositorio a evaluar
            
        Returns:
            True si NO está blacklisted (pasa el filtro), False si es un FP conocido
        """
        # Obtener identificador del repo
        name_with_owner = (
            repo.get("nameWithOwner") or repo.get("name_with_owner") or ""
        ).lower()
        
        # 1. Verificar contra lista de repos conocidos
        if name_with_owner in NON_QC_KNOWN_REPOS:
            logger.debug(
                f"Repo rechazado (blacklist - Non-QC conocido): "
                f"{repo.get('nameWithOwner', name_with_owner)}"
            )
            return False
        
        # 2. Verificar contra patrones regex en texto buscable
        searchable_text = _get_searchable_text(repo)
        repo.get("name", "").lower()
        
        for pattern in NON_QC_BLACKLIST_PATTERNS:
            if re.search(pattern, searchable_text, re.IGNORECASE):
                logger.debug(
                    f"Repo rechazado (blacklist - patrón '{pattern}'): "
                    f"{repo.get('nameWithOwner', name_with_owner)}"
                )
                return False
        
        return True

    @staticmethod
    def has_quantum_relevance(repo: Dict[str, Any]) -> bool:
        """
        Verifica relevancia contextual para repos que contienen 'quantum'.
        
        Para repos que matchean la keyword genérica 'quantum' pero no contienen
        keywords QC específicas (qiskit, cirq, qubit, etc.), aplica verificación
        adicional para descartar usos de 'quantum' como marca o nombre sin
        relación con computación cuántica.
        
        Lógica:
        - Si el repo contiene al menos 1 keyword QC específica → PASA
        - Si el repo NO contiene 'quantum' en absoluto → PASA (otro keyword lo trajo)
        - Si contiene solo 'quantum' genérico sin keywords QC:
          → Se requieren al menos 2 señales de contexto QC → PASA
          → Si no, RECHAZA
        
        Args:
            repo: Repositorio a evaluar
            
        Returns:
            True si es relevante para QC, False si parece un FP
        """
        searchable_text = _get_searchable_text(repo)
        (repo.get("name") or "").lower()
        description = (repo.get("description") or "").lower()
        
        # Si no contiene "quantum" en absoluto, no aplicar este filtro
        # (fue encontrado por otra keyword como qiskit/cirq)
        if "quantum" not in searchable_text:
            return True
        
        # Buscar keywords QC específicas en el texto
        qc_keywords_found = []
        for kw in REAL_QC_KEYWORDS:
            # Flexibilizar separadores (puntos, guiones, espacios)
            pattern = re.escape(kw).replace(r"\.", r"[\s._-]?")
            if re.search(pattern, searchable_text, re.IGNORECASE):
                qc_keywords_found.append(kw)
        
        # Si tiene al menos 1 keyword QC específica → relevante
        if qc_keywords_found:
            logger.debug(
                f"Repo aceptado (relevancia QC confirmada - keywords: "
                f"{', '.join(qc_keywords_found[:3])}): "
                f"{repo.get('nameWithOwner')}"
            )
            return True
        
        # Solo tiene "quantum" genérico, sin keywords QC específicas
        # Verificar señales de contexto (topics QC, patrones de README)
        context_signals = 0
        
        # Señal 1: Topics relacionados con QC
        topics = (repo.get("repositoryTopics") or {}).get("nodes", [])
        qc_topic_patterns = [
            "quantum", "physics", "simulation", "scientific",
            "chemistry", "optics", "photon", "spin",
        ]
        for topic_node in topics:
            topic_name = (topic_node.get("topic") or {}).get("name", "").lower()
            for tp in qc_topic_patterns:
                if tp in topic_name:
                    context_signals += 1
                    break
        
        # Señal 2: Lenguaje típico de QC (Python, C++, Julia, Q#)
        primary_lang = (repo.get("primaryLanguage") or {}).get("name", "").lower()
        if primary_lang in ["python", "julia", "q#", "c++", "rust"]:
            context_signals += 1
        
        # Señal 3: Descripción contiene lenguaje científico/técnico
        scientific_terms = [
            "simulation", "algorithm", "model", "solver", "library",
            "framework", "toolkit", "package", "dynamics", "system",
            "theory", "physics", "calculation", "matrix", "computation",
            "operator", "eigenvalue", "equation", "numerical",
        ]
        scientific_matches = sum(1 for t in scientific_terms if t in description)
        if scientific_matches >= 2:
            context_signals += 1
        
        # Necesita al menos 2 señales de contexto
        if context_signals >= 2:
            logger.debug(
                f"Repo aceptado (relevancia QC por contexto - "
                f"{context_signals} señales): "
                f"{repo.get('nameWithOwner')}"
            )
            return True
        
        # Sin suficientes señales de QC
        logger.debug(
            f"Repo rechazado (sin relevancia QC - 'quantum' genérico, "
            f"solo {context_signals} señales de contexto): "
            f"{repo.get('nameWithOwner')}"
        )
        return False


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
    valid_languages: List[str],
    strong_quantum_keywords: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Filtra repositorios por lenguaje (con lógica inteligente).
    
    Args:
        repositories: Lista de repositorios a filtrar
        valid_languages: Lenguajes válidos
        strong_quantum_keywords: Keywords cuánticas fuertes para override
        
    Returns:
        Repositorios que pasan el filtro de lenguaje
    """
    return [
        repo for repo in repositories
        if RepositoryFilters.has_valid_language(repo, valid_languages, strong_quantum_keywords)
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
    
    # Derivar keywords cuánticas fuertes de la lista completa
    # (frameworks y conceptos clave que indican software cuántico)
    strong_keywords = [
        kw for kw in keywords
        if any(framework in kw.lower() for framework in [
            "qiskit", "cirq", "pennylane", "braket", "pyquil",
            "algorithm", "circuit", "gate", "vqe", "qaoa",
            "grover", "shor", "quantum computing", "quantum programming"
        ])
    ]
    
    # Si no hay keywords fuertes derivadas, usar una lista mínima por defecto
    if not strong_keywords:
        strong_keywords = [
            "qiskit", "cirq", "pennylane", "braket",
            "quantum algorithm", "quantum circuit"
        ]
    
    # Aplicar filtros en cascada
    filtered = repositories
    
    # 1. No archivados
    filtered = [r for r in filtered if RepositoryFilters.is_not_archived(r)]
    logger.info(f"  Después de filtro archivados: {len(filtered)}")
    
    # 2. Blacklist (falsos positivos conocidos - QuantumultX, Firefox Quantum, etc.)
    filtered = [r for r in filtered if RepositoryFilters.is_not_blacklisted(r)]
    logger.info(f"  Después de filtro blacklist: {len(filtered)}")
    
    # 3. Relevancia contextual (verificar que 'quantum' sea QC, no marca/nombre)
    filtered = [r for r in filtered if RepositoryFilters.has_quantum_relevance(r)]
    logger.info(f"  Después de filtro relevancia QC: {len(filtered)}")
    
    # 4. Documentación (mover antes de actividad para rechazar rápido proyectos sin docs)
    filtered = filter_by_documentation(filtered)
    logger.info(f"  Después de filtro documentación: {len(filtered)}")
    
    # 5. Tamaño mínimo
    filtered = filter_by_project_size(filtered, min_commits, min_size_kb)
    logger.info(f"  Después de filtro tamaño: {len(filtered)}")
    
    # 6. Actividad reciente
    filtered = filter_by_activity(filtered, max_inactivity_days)
    logger.info(f"  Después de filtro actividad: {len(filtered)}")
    
    # 7. Forks válidos
    filtered = filter_by_fork_validity(filtered)
    logger.info(f"  Después de filtro forks: {len(filtered)}")
    
    # 8. Keywords
    filtered = filter_by_keywords(filtered, keywords)
    logger.info(f"  Después de filtro keywords: {len(filtered)}")
    
    # 9. Lenguaje (con lógica inteligente que usa strong_keywords para override)
    filtered = filter_by_language(filtered, valid_languages, strong_keywords)
    logger.info(f"  Después de filtro lenguaje: {len(filtered)}")
    
    # 10. Estrellas
    filtered = [r for r in filtered if RepositoryFilters.has_minimum_stars(r, min_stars)]
    logger.info(f"  Después de filtro estrellas: {len(filtered)}")
    
    # 11. Community engagement
    filtered = [r for r in filtered if RepositoryFilters.has_community_engagement(r)]
    logger.info(f"  Después de filtro engagement: {len(filtered)}")
    
    logger.info(f"Filtrado completo: {len(filtered)}/{len(repositories)} repositorios válidos")
    
    return filtered
