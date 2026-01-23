"""
Modelo de datos para User (Usuario de GitHub) - v3.0 LIMPIO
Incluye SOLO los campos esenciales que realmente usamos.
Validadores automáticos convierten None a [] para evitar errores.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, validator, root_validator


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


class UserRepository(BaseModel):
    """Repositorio simplificado (para pinned_repositories)."""
    id: str
    name: str
    name_with_owner: str = Field(alias="nameWithOwner")
    description: Optional[str] = None
    stargazer_count: int = Field(0, alias="stargazerCount")
    primary_language: Optional[str] = None
    
    @validator('description', pre=True)
    def truncate_description(cls, v):
        """Trunca la descripción si es muy larga."""
        return _truncate_text(v, max_length=300)
    
    class Config:
        populate_by_name = True


class UserOrganization(BaseModel):
    """Organización del usuario."""
    id: str
    login: str
    name: Optional[str] = None
    description: Optional[str] = None
    
    @validator('name', 'description', pre=True)
    def truncate_text_fields(cls, v):
        """Trunca campos de texto si son muy largos."""
        return _truncate_text(v, max_length=300)
    
    class Config:
        populate_by_name = True


# Modelos auxiliares eliminados: ContributionsCollection, CommitContributionsByRepository,
# StarredRepository, Gist, SocialAccount - Ya no se usan en v3.0


class User(BaseModel):
    """
    Modelo de Usuario de GitHub v3.0 - LIMPIO Y VALIDADO
    Solo campos esenciales. Validadores automáticos convierten None a [].
    """
    # ==================== IDENTIFICACIÓN ====================
    id: str
    login: str
    name: Optional[str] = None
    
    # ==================== INFORMACIÓN PERSONAL (OPCIONAL) ====================
    email: Optional[str] = None
    bio: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    
    # ==================== URLs ====================
    avatar_url: Optional[str] = Field(None, alias="avatarUrl")
    url: str
    website_url: Optional[str] = Field(None, alias="websiteUrl")
    twitter_username: Optional[str] = Field(None, alias="twitterUsername")
    
    # ==================== FECHAS ====================
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    
    # ==================== CONTADORES SOCIALES ====================
    followers_count: int = Field(0, alias="followersCount")
    following_count: int = Field(0, alias="followingCount")
    public_repos_count: int = Field(0, alias="publicReposCount")
    starred_repos_count: Optional[int] = Field(None, alias="starredReposCount")  # Enriquecido después
    public_gists_count: Optional[int] = Field(None, alias="publicGistsCount")  # Enriquecido después
    packages_count: Optional[int] = Field(None, alias="packagesCount")  # Enriquecido después
    sponsors_count: Optional[int] = Field(None, alias="sponsorsCount")  # Enriquecido después
    sponsoring_count: Optional[int] = Field(None, alias="sponsoringCount")  # Enriquecido después
    
    # ==================== CONTADORES DE CONTRIBUCIONES ====================
    total_commit_contributions: Optional[int] = Field(None, alias="totalCommitContributions")  # Enriquecido después
    total_issue_contributions: Optional[int] = Field(None, alias="totalIssueContributions")  # Enriquecido después
    total_pr_contributions: Optional[int] = Field(None, alias="totalPrContributions")  # Enriquecido después
    total_pr_review_contributions: Optional[int] = Field(None, alias="totalPrReviewContributions")  # Enriquecido después
    
    # ==================== LISTAS ESENCIALES (con validación automática) ====================
    organizations: List[UserOrganization] = Field(default_factory=list)
    pinned_repositories: List[UserRepository] = Field(default_factory=list)
    top_languages: List[str] = Field(default_factory=list)
    
    # ==================== CORE TFG ====================
    quantum_repositories: List[Dict[str, Any]] = Field(default_factory=list)
    is_quantum_contributor: bool = Field(False)
    quantum_expertise_score: Optional[float] = None
    
    # ==================== MÉTRICAS CALCULADAS ====================
    follower_following_ratio: Optional[float] = None
    stars_per_repo: Optional[float] = None
    
    # ==================== FLAGS ====================
    is_hireable: bool = Field(False, alias="isHireable")
    is_bot: bool = Field(False)
    
    # ==================== METADATA ====================
    extracted_from: List[Dict[str, Any]] = Field(default_factory=list)
    
    # ==================== TRACKING DE ENRIQUECIMIENTO ====================
    enrichment_status: Optional[Dict[str, Any]] = None
    
    # ==================== VALIDADORES AUTOMÁTICOS ====================
    
    @validator('organizations', 'pinned_repositories', 'top_languages', 'quantum_repositories', pre=True, always=True)
    def convert_none_to_empty_list(cls, v):
        """Convierte None a [] para evitar errores. Si GitHub devuelve null, guardamos lista vacía."""
        return v if v is not None else []
    
    @validator('ingested_at', pre=True, always=True)
    def set_ingested_at(cls, v):
        """Establece la fecha de ingesta si no está presente."""
        return v or datetime.utcnow()
    
    class Config:
        populate_by_name = True
        extra = "ignore"  # Ignorar campos obsoletos de BD
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }
    
    def to_dict(self) -> dict:
        """Convierte el modelo a diccionario para MongoDB."""
        return self.model_dump(by_alias=True, exclude_none=True)
    
    def to_mongo_dict(self) -> dict:
        """
        Convierte el modelo a diccionario optimizado para MongoDB.
        Usa _id en lugar de id para aprovechar el índice primario.
        """
        data = self.to_dict()
        if 'id' in data:
            data['_id'] = data.pop('id')
        return data
    
    @classmethod
    def from_graphql_response(cls, data: dict) -> "User":
        """
        Crea instancia desde GraphQL v3.0 - SIMPLIFICADO.
        Los validadores automáticos convierten None a [].
        """
        # Procesar organizaciones
        orgs_nodes = data.get("organizations", {}).get("nodes", [])
        organizations = [UserOrganization(**org) for org in orgs_nodes] if orgs_nodes else []
        
        # Procesar repos pinned
        pinned_nodes = data.get("pinnedItems", {}).get("nodes", [])
        pinned_repositories = [
            UserRepository(**repo) for repo in pinned_nodes 
            if repo.get("__typename") == "Repository"
        ] if pinned_nodes else []
        
        # Contadores básicos (disponibles en ingesta)
        followers_count = data.get("followers", {}).get("totalCount", 0)
        following_count = data.get("following", {}).get("totalCount", 0)
        public_repos_count = data.get("repositories", {}).get("totalCount", 0)
        
        # Contadores que se enriquecen después (pueden ser None en ingesta)
        starred_repos_count = data.get("starredRepositories", {}).get("totalCount") if data.get("starredRepositories") else None
        public_gists_count = data.get("gists", {}).get("totalCount") if data.get("gists") else None
        packages_count = data.get("packages", {}).get("totalCount") if data.get("packages") else None
        sponsors_count = data.get("sponsorshipsAsMaintainer", {}).get("totalCount") if data.get("sponsorshipsAsMaintainer") else None
        sponsoring_count = data.get("sponsorshipsAsSponsor", {}).get("totalCount") if data.get("sponsorshipsAsSponsor") else None
        
        # Contribuciones (se enriquecen después, pueden ser None en ingesta)
        contrib = data.get("contributionsCollection", {})
        total_commit_contributions = contrib.get("totalCommitContributions") if contrib else None
        total_issue_contributions = contrib.get("totalIssueContributions") if contrib else None
        total_pr_contributions = contrib.get("totalPullRequestContributions") if contrib else None
        total_pr_review_contributions = contrib.get("totalPullRequestReviewContributions") if contrib else None
        
        # Construir diccionario limpio
        user_data = {
            **data,
            "name": _truncate_text(data.get("name"), max_length=200),
            "bio": _truncate_text(data.get("bio"), max_length=500),
            "company": _truncate_text(data.get("company"), max_length=200),
            "organizations": organizations,
            "pinnedRepositories": pinned_repositories,
            "followersCount": followers_count,
            "followingCount": following_count,
            "publicReposCount": public_repos_count,
            "starredReposCount": starred_repos_count,
            "publicGistsCount": public_gists_count,
            "packagesCount": packages_count,
            "sponsorsCount": sponsors_count,
            "sponsoringCount": sponsoring_count,
            "totalCommitContributions": total_commit_contributions,
            "totalIssueContributions": total_issue_contributions,
            "totalPrContributions": total_pr_contributions,
            "totalPrReviewContributions": total_pr_review_contributions
        }
        
        return cls(**user_data)
