"""
Modelo de datos para User (Usuario de GitHub).
Incluye todos los campos relevantes disponibles en la API GraphQL de GitHub.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, validator


class UserRepository(BaseModel):
    """Modelo simplificado de repositorio de un usuario."""
    id: str
    name: str
    name_with_owner: str = Field(alias="nameWithOwner")
    description: Optional[str] = None
    url: str
    stargazer_count: int = Field(0, alias="stargazerCount")
    fork_count: int = Field(0, alias="forkCount")
    watchers_count: int = Field(0, alias="watchersCount")
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")
    is_private: bool = Field(False, alias="isPrivate")
    is_fork: bool = Field(False, alias="isFork")
    is_archived: bool = Field(False, alias="isArchived")
    primary_language: Optional[str] = None
    
    class Config:
        populate_by_name = True


class UserOrganization(BaseModel):
    """Modelo simplificado de organización de un usuario."""
    id: str
    login: str
    name: Optional[str] = None
    avatar_url: Optional[str] = Field(None, alias="avatarUrl")
    url: str
    description: Optional[str] = None
    
    class Config:
        populate_by_name = True


class ContributionsCollection(BaseModel):
    """Modelo de colección de contribuciones del usuario."""
    total_commit_contributions: int = Field(0, alias="totalCommitContributions")
    total_issue_contributions: int = Field(0, alias="totalIssueContributions")
    total_pull_request_contributions: int = Field(0, alias="totalPullRequestContributions")
    total_pull_request_review_contributions: int = Field(0, alias="totalPullRequestReviewContributions")
    total_repository_contributions: int = Field(0, alias="totalRepositoryContributions")
    restricted_contributions_count: int = Field(0, alias="restrictedContributionsCount")
    
    class Config:
        populate_by_name = True


class CommitContributionsByRepository(BaseModel):
    """Modelo de contribuciones por repositorio."""
    repository_name: str
    contributions_count: int = 0
    
    class Config:
        populate_by_name = True


class StarredRepository(BaseModel):
    """Modelo de repositorio con estrella."""
    id: str
    name: str
    name_with_owner: str = Field(alias="nameWithOwner")
    starred_at: Optional[datetime] = Field(None, alias="starredAt")
    
    class Config:
        populate_by_name = True


class Gist(BaseModel):
    """Modelo de Gist del usuario."""
    id: str
    name: str
    description: Optional[str] = None
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")
    is_public: bool = Field(True, alias="isPublic")
    
    class Config:
        populate_by_name = True


class SocialAccount(BaseModel):
    """Modelo de cuenta social vinculada."""
    provider: str
    display_name: Optional[str] = Field(None, alias="displayName")
    url: str
    
    class Config:
        populate_by_name = True


class User(BaseModel):
    """
    Modelo completo de datos para un usuario de GitHub.
    Preparado para almacenamiento en MongoDB con todos los campos relevantes de GraphQL.
    """
    # ==================== IDENTIFICACIÓN ====================
    id: str  # ID único de GitHub
    login: str
    name: Optional[str] = None
    
    # ==================== INFORMACIÓN PERSONAL ====================
    email: Optional[str] = None
    bio: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    pronouns: Optional[str] = None
    
    # ==================== URLs Y AVATARES ====================
    avatar_url: Optional[str] = Field(None, alias="avatarUrl")
    url: str
    website_url: Optional[str] = Field(None, alias="websiteUrl")
    
    # ==================== REDES SOCIALES ====================
    twitter_username: Optional[str] = Field(None, alias="twitterUsername")
    social_accounts: Optional[List[SocialAccount]] = None
    
    # ==================== FECHAS ====================
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    
    # ==================== MÉTRICAS SOCIALES ====================
    followers_count: int = Field(0, alias="followersCount")
    following_count: int = Field(0, alias="followingCount")
    
    # ==================== REPOSITORIOS ====================
    repositories: Optional[List[UserRepository]] = None
    public_repos_count: int = Field(0, alias="publicReposCount")
    private_repos_count: int = Field(0, alias="privateReposCount")
    owned_private_repos_count: int = Field(0, alias="ownedPrivateReposCount")
    pinned_repositories: Optional[List[UserRepository]] = None
    
    # ==================== REPOSITORIOS STARRED ====================
    starred_repositories: Optional[List[StarredRepository]] = None
    starred_repos_count: Optional[int] = Field(None, alias="starredReposCount")
    
    # ==================== ORGANIZACIONES ====================
    organizations: Optional[List[UserOrganization]] = None
    organizations_count: int = Field(0, alias="organizationsCount")
    
    # ==================== CONTRIBUCIONES ====================
    contributions: Optional[ContributionsCollection] = Field(None, alias="contributionsCollection")
    contributions_by_repository: Optional[List[CommitContributionsByRepository]] = None
    total_commit_contributions: Optional[int] = Field(None, alias="totalCommitContributions")
    total_issue_contributions: Optional[int] = Field(None, alias="totalIssueContributions")
    total_pr_contributions: Optional[int] = Field(None, alias="totalPrContributions")
    total_pr_review_contributions: Optional[int] = Field(None, alias="totalPrReviewContributions")
    watching_count: Optional[int] = Field(None, alias="watchingCount")
    
    # ==================== GISTS ====================
    gists: Optional[List[Gist]] = None
    public_gists_count: Optional[int] = Field(None, alias="publicGistsCount")
    
    # ==================== PACKAGES ====================
    packages_count: int = Field(0, alias="packagesCount")
    
    # ==================== PROYECTOS ====================
    projects_count: int = Field(0, alias="projectsCount")
    
    # ==================== SPONSORS ====================
    is_sponsoring_viewer: bool = Field(False, alias="isSponsoringViewer")
    has_sponsors_listing: bool = Field(False, alias="hasSponsorshipsListing")
    sponsors_count: int = Field(0, alias="sponsorsCount")
    sponsoring_count: int = Field(0, alias="sponsoringCount")
    monthly_estimated_sponsors_income: Optional[int] = Field(None, alias="monthlyEstimatedSponsorsIncome")
    
    # ==================== ESTADOS ====================
    is_hireable: bool = Field(False, alias="isHireable")
    is_bounty_hunter: bool = Field(False, alias="isBountyHunter")
    is_campus_expert: bool = Field(False, alias="isCampusExpert")
    is_developer_program_member: bool = Field(False, alias="isDeveloperProgramMember")
    is_employee: bool = Field(False, alias="isEmployee")
    is_github_star: bool = Field(False, alias="isGitHubStar")
    is_site_admin: bool = Field(False, alias="isSiteAdmin")
    is_viewer: bool = Field(False, alias="isViewer")
    viewing_user_can_follow: bool = Field(False, alias="viewerCanFollow")
    viewing_user_is_following: bool = Field(False, alias="viewerIsFollowing")
    
    # ==================== CONFIGURACIÓN ====================
    can_receive_organization_emails_when_notifications_restricted: bool = Field(
        False, 
        alias="canReceiveOrganizationEmailsWhenNotificationsRestricted"
    )
    has_sponsorships_featuring_enabled: bool = Field(False, alias="hasSponsorshipsFeaturesEnabled")
    interaction_ability: Optional[Dict[str, Any]] = None
    
    # ==================== STATUS ====================
    status: Optional[Dict[str, Any]] = None  # Emoji status del usuario
    
    # ==================== METADATA ADICIONAL ====================
    estimated_next_sponsors_payout_in_cents: Optional[int] = Field(
        None, 
        alias="estimatedNextSponsorsPayoutInCents"
    )
    
    # ==================== ENRIQUECIMIENTO - CAMPOS ADICIONALES ====================
    # Perfil social enriquecido
    social_profile_enriched: bool = Field(False)
    status_message: Optional[str] = None
    status_emoji: Optional[str] = None
    
    # Sponsors detallados
    sponsors: Optional[List[Dict[str, Any]]] = None
    
    # Gists quantum
    quantum_gists: Optional[List[Dict[str, Any]]] = None
    quantum_gists_count: int = Field(0)
    
    # Lenguajes detallados con bytes
    languages_detailed: Optional[List[Dict[str, Any]]] = None
    
    # Top repositorios por contribución
    top_contributed_repos: Optional[List[Dict[str, Any]]] = None
    
    # Issues y PRs notables
    notable_issues_prs: Optional[Dict[str, Any]] = None
    
    # Paquetes
    packages: Optional[List[Dict[str, Any]]] = None
    
    # Proyectos
    projects: Optional[List[Dict[str, Any]]] = None
    
    # Red social (muestra)
    social_network_sample: Optional[Dict[str, Any]] = None
    
    # Repositorios quantum relacionados
    quantum_repositories: Optional[List[Dict[str, Any]]] = None
    is_quantum_contributor: bool = Field(False)
    
    # Top lenguajes
    top_languages: Optional[List[Dict[str, Any]]] = None
    
    # Actividad reciente (30 días)
    recent_commits_30d: Optional[int] = None
    recent_issues_30d: Optional[int] = None
    recent_prs_30d: Optional[int] = None
    recent_reviews_30d: Optional[int] = None
    
    # Métricas sociales calculadas
    follower_following_ratio: Optional[float] = None
    stars_per_repo: Optional[float] = None
    
    # Quantum expertise score (0-100)
    quantum_expertise_score: Optional[float] = None
    
    # Referencias a colección de repositorios
    repository_references: Optional[Dict[str, Any]] = None
    
    # Flags de detección
    is_bot: bool = Field(False)
    extracted_from: List[Dict[str, Any]] = Field(default_factory=list)  # Mantener: siempre tiene al menos 1 elemento
    
    # ==================== CAMPOS PERSONALIZADOS ====================
    custom_properties: Dict[str, Any] = Field(default_factory=dict)
    
    # ==================== TRACKING DE ENRIQUECIMIENTO ====================
    enrichment_status: Optional[Dict[str, Any]] = None  # {is_complete, last_enriched, fields_enriched, fields_missing, total_fields_enriched}
    
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
    def from_graphql_response(cls, data: dict) -> "User":
        """
        Crea una instancia desde la respuesta de GraphQL.
        Procesa y normaliza todos los campos anidados.
        
        Args:
            data: Datos de la respuesta GraphQL
            
        Returns:
            Instancia de User
        """
        # ==================== PROCESAR REPOSITORIOS ====================
        repos_data = data.get("repositories", {})
        repos_nodes = repos_data.get("nodes", [])
        repositories = [UserRepository(**repo) for repo in repos_nodes]
        
        # Repositorios públicos/privados
        public_repos_count = data.get("publicRepositories", {}).get("totalCount", 0)
        private_repos_count = data.get("privateRepositories", {}).get("totalCount", 0)
        owned_private_repos_count = data.get("ownedPrivateRepositories", {}).get("totalCount", 0)
        
        # Repositorios fijados
        pinned_repos_data = data.get("pinnedItems", {})
        pinned_repos_nodes = pinned_repos_data.get("nodes", [])
        pinned_repositories = [UserRepository(**repo) for repo in pinned_repos_nodes if repo.get("__typename") == "Repository"]
        
        # ==================== PROCESAR STARRED REPOSITORIES ====================
        starred_data = data.get("starredRepositories", {})
        starred_nodes = starred_data.get("edges", [])
        starred_repositories = []
        for edge in starred_nodes:
            node = edge.get("node", {})
            starred_repo = StarredRepository(
                id=node.get("id", ""),
                name=node.get("name", ""),
                nameWithOwner=node.get("nameWithOwner", ""),
                starredAt=edge.get("starredAt")
            )
            starred_repositories.append(starred_repo)
        starred_repos_count = starred_data.get("totalCount", 0)
        
        # ==================== PROCESAR ORGANIZACIONES ====================
        orgs_data = data.get("organizations", {})
        orgs_nodes = orgs_data.get("nodes", [])
        organizations = [UserOrganization(**org) for org in orgs_nodes]
        organizations_count = orgs_data.get("totalCount", 0)
        
        # ==================== PROCESAR CONTADORES SOCIALES ====================
        followers_count = data.get("followers", {}).get("totalCount", 0)
        following_count = data.get("following", {}).get("totalCount", 0)
        
        # ==================== PROCESAR CONTRIBUCIONES ====================
        contributions_data = data.get("contributionsCollection")
        contributions = None
        contributions_by_repository = []
        
        if contributions_data:
            contributions = ContributionsCollection(**contributions_data)
            
            # Contribuciones por repositorio
            commit_contrib_repos = contributions_data.get("commitContributionsByRepository", [])
            for repo_contrib in commit_contrib_repos:
                repository = repo_contrib.get("repository", {})
                contributions_count = repo_contrib.get("contributions", {}).get("totalCount", 0)
                
                contrib_by_repo = CommitContributionsByRepository(
                    repository_name=repository.get("nameWithOwner", ""),
                    contributions_count=contributions_count
                )
                contributions_by_repository.append(contrib_by_repo)
        
        # ==================== PROCESAR GISTS ====================
        gists_data = data.get("gists", {})
        gists_nodes = gists_data.get("nodes", [])
        gists = [Gist(**gist) for gist in gists_nodes]
        public_gists_count = data.get("publicGists", {}).get("totalCount", 0)
        
        # ==================== PROCESAR CONTADORES ADICIONALES ====================
        packages_count = data.get("packages", {}).get("totalCount", 0)
        projects_count = data.get("projects", {}).get("totalCount", 0)
        sponsors_count = data.get("sponsors", {}).get("totalCount", 0)
        sponsoring_count = data.get("sponsoring", {}).get("totalCount", 0)
        
        # ==================== PROCESAR CUENTAS SOCIALES ====================
        social_accounts_data = data.get("socialAccounts", {})
        social_accounts_nodes = social_accounts_data.get("nodes", [])
        social_accounts = [SocialAccount(**account) for account in social_accounts_nodes]
        
        # ==================== PROCESAR STATUS ====================
        status_data = data.get("status")
        status = None
        if status_data:
            status = {
                "emoji": status_data.get("emoji"),
                "message": status_data.get("message"),
                "expires_at": status_data.get("expiresAt")
            }
        
        # ==================== PROCESAR INTERACTION ABILITY ====================
        interaction_ability_data = data.get("interactionAbility")
        interaction_ability = None
        if interaction_ability_data:
            interaction_ability = {
                "limit": interaction_ability_data.get("limit"),
                "origin": interaction_ability_data.get("origin"),
                "expires_at": interaction_ability_data.get("expiresAt")
            }
        
        # ==================== CONSTRUIR DICCIONARIO COMPLETO ====================
        user_data = {
            **data,
            "repositories": repositories,
            "publicReposCount": public_repos_count,
            "privateReposCount": private_repos_count,
            "ownedPrivateReposCount": owned_private_repos_count,
            "pinnedRepositories": pinned_repositories,
            "starredRepositories": starred_repositories,
            "starredReposCount": starred_repos_count,
            "organizations": organizations,
            "organizationsCount": organizations_count,
            "followersCount": followers_count,
            "followingCount": following_count,
            "contributionsCollection": contributions,
            "contributionsByRepository": contributions_by_repository,
            "gists": gists,
            "publicGistsCount": public_gists_count,
            "packagesCount": packages_count,
            "projectsCount": projects_count,
            "sponsorsCount": sponsors_count,
            "sponsoringCount": sponsoring_count,
            "socialAccounts": social_accounts,
            "status": status,
            "interactionAbility": interaction_ability
        }
        
        return cls(**user_data)
