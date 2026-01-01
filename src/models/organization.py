"""
Modelo de datos para Organization (Organización de GitHub) - v2.0
Datos básicos (ingesta) + Métricas quantum (enriquecimiento).
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from pydantic import BaseModel, Field, validator


def _truncate_text(text: Optional[str], max_length: int = 500, suffix: str = "... [TRUNCATED]") -> Optional[str]:
    """
    Trunca un texto si excede la longitud máxima.
    
    Args:
        text: Texto a truncar
        max_length: Longitud máxima permitida
        suffix: Sufijo a añadir cuando se trunca
    
    Returns:
        Texto truncado o None si el texto es None
    """
    if not text:
        return text
    if len(text) > max_length:
        return text[:max_length] + suffix
    return text


class EnrichmentStatus(BaseModel):
    """Estado del enriquecimiento de la organización."""
    is_complete: bool = False
    version: str = "2.0"
    last_check: Optional[str] = None
    fields_missing: List[str] = []


class Organization(BaseModel):
    """
    Modelo de Organización de GitHub v2.0
    
    FASE 1 (INGESTA): Campos básicos desde GitHub API
    FASE 2 (ENRIQUECIMIENTO): Métricas quantum calculadas y análisis
    """
    # ==================== IDENTIFICACIÓN ====================
    id: str
    login: str
    name: Optional[str] = None
    description: Optional[str] = None
    
    # ==================== CONTACTO ====================
    email: Optional[str] = None
    url: str
    avatar_url: str = Field(alias="avatarUrl")
    website_url: Optional[str] = Field(None, alias="websiteUrl")
    
    # ==================== PRESENCIA SOCIAL ====================
    twitter_username: Optional[str] = Field(None, alias="twitterUsername")
    location: Optional[str] = None
    
    # ==================== VERIFICACIÓN ====================
    is_verified: bool = Field(False, alias="isVerified")
    
    # ==================== FECHAS ====================
    created_at: Optional[str] = Field(None, alias="createdAt")
    updated_at: Optional[str] = Field(None, alias="updatedAt")
    
    # ==================== METADATA DE INGESTA ====================
    ingested_at: Optional[datetime] = None
    enriched_at: Optional[datetime] = None
    
    # ==================== RELEVANCIA Y TRAZABILIDAD ====================
    is_relevant: bool = Field(
        False,
        description="True si tenemos repositorios quantum ingestados de esta organización"
    )
    
    discovered_from_repos: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Repositorios quantum de nuestra BD que pertenecen a esta org [{id, name}]"
    )
    
    # ==================== MÉTRICAS BÁSICAS (Ingesta) ====================
    public_repos_count: Optional[int] = Field(
        None,
        description="Total de repositorios públicos"
    )
    
    members_count: Optional[int] = Field(
        None,
        description="Total de miembros de la organización"
    )
    
    sponsorable: Optional[bool] = Field(
        None,
        description="Si la organización acepta sponsors"
    )
    
    is_active: Optional[bool] = Field(
        None,
        description="Actividad en los últimos 6 meses (calculado desde updatedAt)"
    )
    
    # ==================== MÉTRICAS QUANTUM (Enriquecimiento) ====================
    quantum_focus_score: Optional[float] = Field(
        None,
        description="Score calculado: porcentaje de repos quantum sobre total (0-100)"
    )
    
    quantum_repositories_count: Optional[int] = Field(
        None,
        description="Cantidad de repositorios relacionados con quantum computing"
    )
    
    total_repositories_count: Optional[int] = Field(
        None,
        description="Total de repositorios públicos de la organización"
    )
    
    quantum_contributors_count: Optional[int] = Field(
        None,
        description="Cantidad de miembros que contribuyen a repos quantum"
    )
    
    total_members_count: Optional[int] = Field(
        None,
        description="Total de miembros públicos de la organización"
    )
    
    is_quantum_focused: Optional[bool] = Field(
        None,
        description="True si quantum_focus_score > 30% (organización enfocada en quantum)"
    )
    
    # ==================== LISTAS DE REFERENCIA (Enriquecimiento) ====================
    quantum_repositories: List[str] = Field(
        default_factory=list,
        description="IDs de repositorios quantum de la organización"
    )
    
    top_quantum_contributors: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Top 10 contribuidores a repos quantum [{id, login}]"
    )
    
    # ==================== ANÁLISIS TECNOLÓGICO Y PRESTIGIO ====================
    top_languages: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Top lenguajes de programación usados en repos quantum [{name, percentage, repo_count}]"
    )
    
    total_stars: Optional[int] = Field(
        None,
        description="Suma total de estrellas de todos los repositorios quantum de la organización"
    )
    
    # ==================== STATUS DE ENRIQUECIMIENTO ====================
    enrichment_status: Optional[EnrichmentStatus] = None
    
    class Config:
        populate_by_name = True
        extra = "ignore"  # Ignora campos desconocidos de la API
    
    @validator('quantum_repositories', 'top_quantum_contributors', 'discovered_from_repos', 'top_languages', pre=True)
    def convert_none_to_empty_list(cls, v):
        """Convierte None a lista vacía automáticamente."""
        return v if v is not None else []
    
    @staticmethod
    def _calculate_is_active(updated_at: Optional[str]) -> bool:
        """Calcula si la organización está activa (actividad en últimos 6 meses)."""
        if not updated_at:
            return False
        
        try:
            # Parse ISO 8601 format (GitHub API format)
            updated_date = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
            six_months_ago = datetime.now() - timedelta(days=180)
            return updated_date.replace(tzinfo=None) >= six_months_ago
        except Exception:
            return False
    
    @classmethod
    def from_graphql_response(cls, data: Dict[str, Any]) -> "Organization":
        """
        Crea una instancia de Organization desde la respuesta GraphQL.
        Solo llena campos básicos (fase de ingesta).
        Los campos de enriquecimiento quedan en None/[] hasta la fase 2.
        
        Args:
            data: Datos de la organización desde GraphQL
            
        Returns:
            Instancia de Organization
        """
        return cls(
            id=data.get("id"),
            login=data.get("login"),
            name=_truncate_text(data.get("name"), max_length=200),
            description=_truncate_text(data.get("description"), max_length=500),
            email=data.get("email"),
            url=data.get("url"),
            avatarUrl=data.get("avatarUrl"),
            websiteUrl=data.get("websiteUrl"),
            twitterUsername=data.get("twitterUsername"),
            location=data.get("location"),
            isVerified=data.get("isVerified", False),
            createdAt=data.get("createdAt"),
            updatedAt=data.get("updatedAt"),
            ingested_at=datetime.now(),
            # Métricas básicas
            public_repos_count=data.get("repositories", {}).get("totalCount") if data.get("repositories") else None,
            members_count=data.get("membersWithRole", {}).get("totalCount") if data.get("membersWithRole") else None,
            sponsorable=data.get("sponsorshipsAsMaintainer", {}).get("totalCount", 0) > 0 if data.get("sponsorshipsAsMaintainer") else False,
            is_active=cls._calculate_is_active(data.get("updatedAt")),
            # Campos de enriquecimiento quedan en None/[]
        )
