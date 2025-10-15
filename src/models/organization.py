"""
Modelo de datos para Organization (Organización de GitHub).
Incluye todos los campos relevantes disponibles en la API GraphQL de GitHub.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, validator


class OrganizationRepository(BaseModel):
    """Modelo simplificado de repositorio dentro de una organización."""
    id: str
    name: str
    name_with_owner: str = Field(alias="nameWithOwner")
    description: Optional[str] = None
    url: str
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")
    pushed_at: Optional[datetime] = Field(None, alias="pushedAt")
    stargazer_count: int = Field(0, alias="stargazerCount")
    fork_count: int = Field(0, alias="forkCount")
    watchers_count: int = Field(0, alias="watchersCount")
    is_private: bool = Field(False, alias="isPrivate")
    is_fork: bool = Field(False, alias="isFork")
    is_archived: bool = Field(False, alias="isArchived")
    primary_language: Optional[str] = None
    
    class Config:
        populate_by_name = True


class Member(BaseModel):
    """Modelo de miembro de una organización."""
    id: str
    login: str
    name: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = Field(None, alias="avatarUrl")
    url: str
    bio: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    website_url: Optional[str] = Field(None, alias="websiteUrl")
    twitter_username: Optional[str] = Field(None, alias="twitterUsername")
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    followers_count: int = Field(0, alias="followersCount")
    
    class Config:
        populate_by_name = True


class Team(BaseModel):
    """Modelo de equipo dentro de una organización."""
    id: str
    name: str
    slug: str
    description: Optional[str] = None
    privacy: Optional[str] = None  # SECRET, VISIBLE
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")
    members_count: int = Field(0, alias="membersCount")
    repositories_count: int = Field(0, alias="repositoriesCount")
    
    class Config:
        populate_by_name = True


class SponsorListing(BaseModel):
    """Modelo de listado de sponsors."""
    id: str
    name: str
    full_description: Optional[str] = Field(None, alias="fullDescription")
    is_public: bool = Field(False, alias="isPublic")
    
    class Config:
        populate_by_name = True


class Organization(BaseModel):
    """
    Modelo completo de datos para una organización de GitHub.
    Preparado para almacenamiento en MongoDB con todos los campos relevantes de GraphQL.
    """
    # ==================== IDENTIFICACIÓN ====================
    id: str  # ID único de GitHub
    node_id: Optional[str] = Field(None, alias="nodeId")
    login: str
    name: Optional[str] = None
    
    # ==================== DESCRIPCIÓN Y URLs ====================
    description: Optional[str] = None
    url: str
    website_url: Optional[str] = Field(None, alias="websiteUrl")
    avatar_url: Optional[str] = Field(None, alias="avatarUrl")
    
    # ==================== REDES SOCIALES ====================
    twitter_username: Optional[str] = Field(None, alias="twitterUsername")
    email: Optional[str] = None
    
    # ==================== UBICACIÓN ====================
    location: Optional[str] = None
    
    # ==================== FECHAS ====================
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    
    # ==================== MÉTRICAS ====================
    repositories_count: int = Field(0, alias="repositoriesCount")
    public_repos_count: int = Field(0, alias="publicReposCount")
    private_repos_count: int = Field(0, alias="privateReposCount")
    members_count: int = Field(0, alias="membersCount")
    teams_count: int = Field(0, alias="teamsCount")
    projects_count: int = Field(0, alias="projectsCount")
    packages_count: int = Field(0, alias="packagesCount")
    
    # ==================== ESTADOS ====================
    is_verified: bool = Field(False, alias="isVerified")
    has_organization_projects_enabled: bool = Field(True, alias="hasOrganizationProjectsEnabled")
    has_repository_projects_enabled: bool = Field(True, alias="hasRepositoryProjectsEnabled")
    
    # ==================== PLAN ====================
    plan_name: Optional[str] = None
    plan_space: Optional[int] = None
    plan_private_repos: Optional[int] = None
    
    # ==================== REPOSITORIOS ====================
    repositories: List[OrganizationRepository] = Field(default_factory=list)
    pinned_repositories: List[OrganizationRepository] = Field(default_factory=list)
    
    # ==================== MIEMBROS ====================
    members: List[Member] = Field(default_factory=list)
    
    # ==================== EQUIPOS ====================
    teams: List[Team] = Field(default_factory=list)
    
    # ==================== SPONSORSHIP ====================
    is_sponsoring_viewer: bool = Field(False, alias="isSponsoringViewer")
    has_sponsors_listing: bool = Field(False, alias="hasSponsorshipsListing")
    sponsors_listing: Optional[SponsorListing] = Field(None, alias="sponsorsListing")
    sponsors_count: int = Field(0, alias="sponsorsCount")
    
    # ==================== IP ALLOWLIST ====================
    ip_allow_list_enabled_setting: Optional[str] = Field(None, alias="ipAllowListEnabledSetting")
    
    # ==================== METADATA ADICIONAL ====================
    announcement: Optional[str] = None
    announcement_user_dismissible: bool = Field(False, alias="announcementUserDismissible")
    any_pinnable_items: bool = Field(False, alias="anyPinnableItems")
    
    # ==================== CAMPOS PERSONALIZADOS ====================
    custom_properties: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }
    
    @validator('ingested_at', pre=True, always=True)
    def set_ingested_at(cls, v):
        """Establece la fecha de ingesta si no está presente."""
        return v or datetime.utcnow()
    
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
    def from_graphql_response(cls, data: dict) -> "Organization":
        """
        Crea una instancia desde la respuesta de GraphQL.
        Procesa y normaliza todos los campos anidados.
        
        Args:
            data: Datos de la respuesta GraphQL
            
        Returns:
            Instancia de Organization
        """
        # ==================== PROCESAR REPOSITORIOS ====================
        repos_data = data.get("repositories", {})
        repos_nodes = repos_data.get("nodes", [])
        repositories = [OrganizationRepository(**repo) for repo in repos_nodes]
        repositories_count = repos_data.get("totalCount", 0)
        
        # Repositorios fijados
        pinned_repos_data = data.get("pinnedRepositories", {})
        pinned_repos_nodes = pinned_repos_data.get("nodes", [])
        pinned_repositories = [OrganizationRepository(**repo) for repo in pinned_repos_nodes]
        
        # ==================== PROCESAR MIEMBROS ====================
        members_data = data.get("membersWithRole", {})
        members_nodes = members_data.get("nodes", [])
        members = [Member(**member) for member in members_nodes]
        members_count = members_data.get("totalCount", 0)
        
        # ==================== PROCESAR EQUIPOS ====================
        teams_data = data.get("teams", {})
        teams_nodes = teams_data.get("nodes", [])
        teams = []
        for team_node in teams_nodes:
            team = Team(
                id=team_node.get("id", ""),
                name=team_node.get("name", ""),
                slug=team_node.get("slug", ""),
                description=team_node.get("description"),
                privacy=team_node.get("privacy"),
                createdAt=team_node.get("createdAt"),
                updatedAt=team_node.get("updatedAt"),
                membersCount=team_node.get("members", {}).get("totalCount", 0),
                repositoriesCount=team_node.get("repositories", {}).get("totalCount", 0)
            )
            teams.append(team)
        teams_count = teams_data.get("totalCount", 0)
        
        # ==================== EXTRAER CONTADORES ====================
        public_repos_count = data.get("publicRepositories", {}).get("totalCount", 0)
        private_repos_count = data.get("privateRepositories", {}).get("totalCount", 0)
        projects_count = data.get("projects", {}).get("totalCount", 0)
        packages_count = data.get("packages", {}).get("totalCount", 0)
        sponsors_count = data.get("sponsors", {}).get("totalCount", 0)
        
        # ==================== PROCESAR PLAN ====================
        plan_data = data.get("plan", {})
        plan_name = plan_data.get("name")
        plan_space = plan_data.get("space")
        plan_private_repos = plan_data.get("privateRepos")
        
        # ==================== PROCESAR SPONSORS LISTING ====================
        sponsors_listing_data = data.get("sponsorsListing")
        sponsors_listing = None
        if sponsors_listing_data:
            sponsors_listing = SponsorListing(**sponsors_listing_data)
        
        # ==================== CONSTRUIR DICCIONARIO COMPLETO ====================
        org_data = {
            **data,
            "repositories": repositories,
            "repositoriesCount": repositories_count,
            "pinnedRepositories": pinned_repositories,
            "publicReposCount": public_repos_count,
            "privateReposCount": private_repos_count,
            "members": members,
            "membersCount": members_count,
            "teams": teams,
            "teamsCount": teams_count,
            "projectsCount": projects_count,
            "packagesCount": packages_count,
            "sponsorsCount": sponsors_count,
            "planName": plan_name,
            "planSpace": plan_space,
            "planPrivateRepos": plan_private_repos,
            "sponsorsListing": sponsors_listing
        }
        
        return cls(**org_data)
