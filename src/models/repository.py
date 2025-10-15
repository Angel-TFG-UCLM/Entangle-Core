"""
Modelo de datos para Repository (Repositorio de GitHub).
Incluye todos los campos relevantes disponibles en la API GraphQL de GitHub.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, validator


class Language(BaseModel):
    """Modelo de lenguaje de programación."""
    name: str
    color: Optional[str] = None
    
    class Config:
        populate_by_name = True


class LanguageEdge(BaseModel):
    """Modelo de lenguaje con información de tamaño (en bytes)."""
    node: Language
    size: int  # Tamaño en bytes
    
    class Config:
        populate_by_name = True


class License(BaseModel):
    """Modelo de licencia de software."""
    key: Optional[str] = None
    name: str
    spdx_id: Optional[str] = Field(None, alias="spdxId")
    url: Optional[str] = None
    nickname: Optional[str] = None
    
    class Config:
        populate_by_name = True


class Topic(BaseModel):
    """Modelo de topic/etiqueta del repositorio."""
    name: str
    
    class Config:
        populate_by_name = True


class RepositoryTopic(BaseModel):
    """Modelo de relación entre repositorio y topic."""
    topic: Topic
    
    class Config:
        populate_by_name = True


class Owner(BaseModel):
    """Modelo del propietario del repositorio (User u Organization)."""
    id: str
    login: str
    avatar_url: Optional[str] = Field(None, alias="avatarUrl")
    url: str
    type: Optional[str] = Field(None, alias="__typename")  # "User" o "Organization"
    
    class Config:
        populate_by_name = True


class Collaborator(BaseModel):
    """Modelo de colaborador del repositorio."""
    id: str
    login: str
    name: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = Field(None, alias="avatarUrl")
    url: Optional[str] = None
    
    class Config:
        populate_by_name = True


class Commit(BaseModel):
    """Modelo simplificado de commit."""
    oid: str  # SHA del commit
    message: str
    committed_date: Optional[datetime] = Field(None, alias="committedDate")
    author_login: Optional[str] = None
    
    class Config:
        populate_by_name = True


class Issue(BaseModel):
    """Modelo simplificado de issue."""
    id: str
    number: int
    title: str
    state: str  # OPEN, CLOSED
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    closed_at: Optional[datetime] = Field(None, alias="closedAt")
    
    class Config:
        populate_by_name = True


class PullRequest(BaseModel):
    """Modelo simplificado de pull request."""
    id: str
    number: int
    title: str
    state: str  # OPEN, CLOSED, MERGED
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    merged_at: Optional[datetime] = Field(None, alias="mergedAt")
    
    class Config:
        populate_by_name = True


class Release(BaseModel):
    """Modelo de release del repositorio."""
    id: str
    tag_name: str = Field(alias="tagName")
    name: Optional[str] = None
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    published_at: Optional[datetime] = Field(None, alias="publishedAt")
    is_prerelease: bool = Field(False, alias="isPrerelease")
    
    class Config:
        populate_by_name = True


class Vulnerability(BaseModel):
    """Modelo de vulnerabilidad de seguridad."""
    severity: str  # LOW, MODERATE, HIGH, CRITICAL
    advisory: Optional[Dict[str, Any]] = None
    
    class Config:
        populate_by_name = True


class DependencyGraphManifest(BaseModel):
    """Modelo de manifiesto de dependencias."""
    filename: str
    dependencies_count: int = Field(0, alias="dependenciesCount")
    
    class Config:
        populate_by_name = True


class Repository(BaseModel):
    """
    Modelo completo de datos para un repositorio de GitHub.
    Preparado para almacenamiento en MongoDB con todos los campos relevantes de GraphQL.
    """
    # ==================== IDENTIFICACIÓN ====================
    id: str  # ID único de GitHub
    node_id: Optional[str] = Field(None, alias="nodeId")
    name: str
    name_with_owner: str = Field(alias="nameWithOwner")
    full_name: Optional[str] = Field(None, alias="fullName")  # Alias alternativo
    
    # ==================== DESCRIPCIÓN Y URLs ====================
    description: Optional[str] = None
    url: str
    homepage_url: Optional[str] = Field(None, alias="homepageUrl")
    ssh_url: Optional[str] = Field(None, alias="sshUrl")
    clone_url: Optional[str] = Field(None, alias="cloneUrl")
    mirror_url: Optional[str] = Field(None, alias="mirrorUrl")
    
    # ==================== PROPIETARIO ====================
    owner: Optional[Owner] = None
    organization_id: Optional[str] = None  # Para búsquedas eficientes
    
    # ==================== FECHAS ====================
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")
    pushed_at: Optional[datetime] = Field(None, alias="pushedAt")
    ingested_at: datetime = Field(default_factory=datetime.utcnow)  # Momento de ingesta
    
    # ==================== LENGUAJES ====================
    primary_language: Optional[Language] = Field(None, alias="primaryLanguage")
    languages: List[LanguageEdge] = Field(default_factory=list)
    languages_count: int = Field(0, alias="languagesCount")
    
    # ==================== TOPICS/ETIQUETAS ====================
    repository_topics: List[RepositoryTopic] = Field(default_factory=list, alias="repositoryTopics")
    topics_count: int = Field(0, alias="topicsCount")
    
    # ==================== MÉTRICAS DE POPULARIDAD ====================
    stargazer_count: int = Field(0, alias="stargazerCount")
    fork_count: int = Field(0, alias="forkCount")
    watchers_count: int = Field(0, alias="watchersCount")
    subscribers_count: int = Field(0, alias="subscribersCount")
    
    # ==================== MÉTRICAS DE CONTENIDO ====================
    disk_usage: int = Field(0, alias="diskUsage")  # Tamaño en KB
    commits_count: int = Field(0, alias="commitsCount")
    branches_count: int = Field(0, alias="branchesCount")
    tags_count: int = Field(0, alias="tagsCount")
    releases_count: int = Field(0, alias="releasesCount")
    
    # ==================== ISSUES ====================
    has_issues_enabled: bool = Field(True, alias="hasIssuesEnabled")
    issues_count: int = Field(0, alias="issuesCount")
    open_issues_count: int = Field(0, alias="openIssuesCount")
    closed_issues_count: int = Field(0, alias="closedIssuesCount")
    
    # ==================== PULL REQUESTS ====================
    pull_requests_count: int = Field(0, alias="pullRequestsCount")
    open_pull_requests_count: int = Field(0, alias="openPullRequestsCount")
    closed_pull_requests_count: int = Field(0, alias="closedPullRequestsCount")
    merged_pull_requests_count: int = Field(0, alias="mergedPullRequestsCount")
    
    # ==================== PROYECTOS Y WIKI ====================
    has_projects_enabled: bool = Field(True, alias="hasProjectsEnabled")
    has_wiki_enabled: bool = Field(True, alias="hasWikiEnabled")
    projects_count: int = Field(0, alias="projectsCount")
    
    # ==================== ESTADOS BOOLEANOS ====================
    is_private: bool = Field(False, alias="isPrivate")
    is_fork: bool = Field(False, alias="isFork")
    is_archived: bool = Field(False, alias="isArchived")
    is_disabled: bool = Field(False, alias="isDisabled")
    is_locked: bool = Field(False, alias="isLocked")
    is_mirror: bool = Field(False, alias="isMirror")
    is_template: bool = Field(False, alias="isTemplate")
    is_security_policy_enabled: bool = Field(False, alias="isSecurityPolicyEnabled")
    
    # ==================== FUNCIONALIDADES ====================
    has_discussions_enabled: bool = Field(False, alias="hasDiscussionsEnabled")
    has_sponsorships_enabled: bool = Field(False, alias="hasSponsorshipsEnabled")
    discussions_count: int = Field(0, alias="discussionsCount")
    
    # ==================== LICENCIA ====================
    license_info: Optional[License] = Field(None, alias="licenseInfo")
    
    # ==================== BRANCH PRINCIPAL ====================
    default_branch_ref_name: Optional[str] = Field(None, alias="defaultBranchRefName")
    
    # ==================== REPOSITORIO PADRE (si es fork) ====================
    parent_id: Optional[str] = None
    parent_name_with_owner: Optional[str] = None
    
    # ==================== COLABORADORES ====================
    collaborators: List[Collaborator] = Field(default_factory=list)
    collaborators_count: int = Field(0, alias="collaboratorsCount")
    
    # ==================== COMMITS RECIENTES ====================
    recent_commits: List[Commit] = Field(default_factory=list)
    last_commit_date: Optional[datetime] = None
    
    # ==================== ISSUES Y PRS RECIENTES ====================
    recent_issues: List[Issue] = Field(default_factory=list)
    recent_pull_requests: List[PullRequest] = Field(default_factory=list)
    
    # ==================== RELEASES ====================
    latest_release: Optional[Release] = None
    releases: List[Release] = Field(default_factory=list)
    
    # ==================== SEGURIDAD ====================
    vulnerability_alerts_count: int = Field(0, alias="vulnerabilityAlertsCount")
    vulnerabilities: List[Vulnerability] = Field(default_factory=list)
    
    # ==================== DEPENDENCIAS ====================
    dependency_graph_manifests: List[DependencyGraphManifest] = Field(default_factory=list)
    
    # ==================== README ====================
    readme_text: Optional[str] = None  # Contenido del README
    has_readme: bool = False
    
    # ==================== METADATA ADICIONAL ====================
    network_count: int = Field(0, alias="networkCount")  # Total de forks en la red
    code_of_conduct: Optional[Dict[str, Any]] = None
    funding_links: List[Dict[str, Any]] = Field(default_factory=list)
    
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
    def from_graphql_response(cls, data: dict) -> "Repository":
        """
        Crea una instancia desde la respuesta de GraphQL.
        Procesa y normaliza todos los campos anidados.
        
        Args:
            data: Datos de la respuesta GraphQL
            
        Returns:
            Instancia de Repository
        """
        # ==================== PROCESAR OWNER ====================
        owner_data = data.get("owner")
        owner = Owner(**owner_data) if owner_data else None
        organization_id = owner_data.get("id") if owner_data and owner_data.get("__typename") == "Organization" else None
        
        # ==================== PROCESAR LENGUAJES ====================
        languages_data = data.get("languages", {})
        languages_edges = languages_data.get("edges", [])
        languages = [LanguageEdge(**lang) for lang in languages_edges]
        languages_count = languages_data.get("totalCount", 0)
        
        # ==================== PROCESAR TOPICS ====================
        topics_data = data.get("repositoryTopics", {})
        topics_nodes = topics_data.get("nodes", [])
        repository_topics = [RepositoryTopic(**topic) for topic in topics_nodes]
        topics_count = topics_data.get("totalCount", 0)
        
        # ==================== PROCESAR COLABORADORES ====================
        collaborators_data = data.get("collaborators", {})
        collaborators_nodes = collaborators_data.get("nodes", [])
        collaborators = [Collaborator(**collab) for collab in collaborators_nodes]
        collaborators_count = collaborators_data.get("totalCount", 0)
        
        # ==================== EXTRAER CONTADORES ====================
        watchers_count = data.get("watchers", {}).get("totalCount", 0)
        subscribers_count = data.get("subscribers", {}).get("totalCount", 0)
        
        # Issues
        issues_data = data.get("issues", {})
        issues_count = issues_data.get("totalCount", 0)
        open_issues_data = data.get("openIssues", {})
        open_issues_count = open_issues_data.get("totalCount", 0)
        closed_issues_data = data.get("closedIssues", {})
        closed_issues_count = closed_issues_data.get("totalCount", 0)
        
        # Pull Requests
        pull_requests_data = data.get("pullRequests", {})
        pull_requests_count = pull_requests_data.get("totalCount", 0)
        open_prs_data = data.get("openPullRequests", {})
        open_pull_requests_count = open_prs_data.get("totalCount", 0)
        closed_prs_data = data.get("closedPullRequests", {})
        closed_pull_requests_count = closed_prs_data.get("totalCount", 0)
        merged_prs_data = data.get("mergedPullRequests", {})
        merged_pull_requests_count = merged_prs_data.get("totalCount", 0)
        
        # Branches, Tags, Projects
        branches_count = data.get("refs", {}).get("totalCount", 0)
        tags_count = data.get("tags", {}).get("totalCount", 0)
        projects_count = data.get("projects", {}).get("totalCount", 0)
        discussions_count = data.get("discussions", {}).get("totalCount", 0)
        
        # ==================== PROCESAR COMMITS ====================
        commits_count = 0
        default_branch_name = None
        recent_commits = []
        last_commit_date = None
        
        default_branch_data = data.get("defaultBranchRef")
        if default_branch_data:
            default_branch_name = default_branch_data.get("name")
            target = default_branch_data.get("target", {})
            history = target.get("history", {})
            commits_count = history.get("totalCount", 0)
            
            # Commits recientes
            commits_edges = history.get("edges", [])
            for edge in commits_edges[:10]:  # Últimos 10 commits
                commit_node = edge.get("node", {})
                commit = Commit(
                    oid=commit_node.get("oid", ""),
                    message=commit_node.get("message", ""),
                    committedDate=commit_node.get("committedDate"),
                    author_login=commit_node.get("author", {}).get("user", {}).get("login") if commit_node.get("author") else None
                )
                recent_commits.append(commit)
            
            # Última fecha de commit
            if commits_edges:
                last_commit_date = commits_edges[0].get("node", {}).get("committedDate")
        
        # ==================== PROCESAR ISSUES RECIENTES ====================
        recent_issues = []
        issues_nodes = issues_data.get("nodes", [])
        for issue_node in issues_nodes[:5]:  # Últimos 5 issues
            issue = Issue(**issue_node)
            recent_issues.append(issue)
        
        # ==================== PROCESAR PRS RECIENTES ====================
        recent_pull_requests = []
        prs_nodes = pull_requests_data.get("nodes", [])
        for pr_node in prs_nodes[:5]:  # Últimos 5 PRs
            pr = PullRequest(**pr_node)
            recent_pull_requests.append(pr)
        
        # ==================== PROCESAR RELEASES ====================
        releases_data = data.get("releases", {})
        releases_nodes = releases_data.get("nodes", [])
        releases = [Release(**release) for release in releases_nodes]
        releases_count = releases_data.get("totalCount", 0)
        latest_release = releases[0] if releases else None
        
        # ==================== PROCESAR PARENT (si es fork) ====================
        parent_id = None
        parent_name_with_owner = None
        parent_data = data.get("parent")
        if parent_data:
            parent_id = parent_data.get("id")
            parent_name_with_owner = parent_data.get("nameWithOwner")
        
        # ==================== PROCESAR README ====================
        readme_text = None
        has_readme = False
        readme_object = data.get("object")
        if readme_object and isinstance(readme_object, dict):
            readme_text = readme_object.get("text")
            has_readme = bool(readme_text)
        
        # ==================== PROCESAR VULNERABILIDADES ====================
        vulnerability_alerts_data = data.get("vulnerabilityAlerts", {})
        vulnerability_alerts_count = vulnerability_alerts_data.get("totalCount", 0)
        vulnerabilities = []
        vuln_nodes = vulnerability_alerts_data.get("nodes", [])
        for vuln_node in vuln_nodes:
            vuln = Vulnerability(
                severity=vuln_node.get("securityVulnerability", {}).get("severity", "UNKNOWN"),
                advisory=vuln_node.get("securityAdvisory")
            )
            vulnerabilities.append(vuln)
        
        # ==================== PROCESAR DEPENDENCIAS ====================
        dependency_graph_data = data.get("dependencyGraphManifests", {})
        manifest_nodes = dependency_graph_data.get("nodes", [])
        dependency_graph_manifests = [DependencyGraphManifest(**manifest) for manifest in manifest_nodes]
        
        # ==================== CONSTRUIR DICCIONARIO COMPLETO ====================
        repo_data = {
            **data,
            "owner": owner,
            "organizationId": organization_id,
            "languages": languages,
            "languagesCount": languages_count,
            "repositoryTopics": repository_topics,
            "topicsCount": topics_count,
            "collaborators": collaborators,
            "collaboratorsCount": collaborators_count,
            "watchersCount": watchers_count,
            "subscribersCount": subscribers_count,
            "issuesCount": issues_count,
            "openIssuesCount": open_issues_count,
            "closedIssuesCount": closed_issues_count,
            "pullRequestsCount": pull_requests_count,
            "openPullRequestsCount": open_pull_requests_count,
            "closedPullRequestsCount": closed_pull_requests_count,
            "mergedPullRequestsCount": merged_pull_requests_count,
            "branchesCount": branches_count,
            "tagsCount": tags_count,
            "releasesCount": releases_count,
            "projectsCount": projects_count,
            "discussionsCount": discussions_count,
            "commitsCount": commits_count,
            "defaultBranchRefName": default_branch_name,
            "recentCommits": recent_commits,
            "lastCommitDate": last_commit_date,
            "recentIssues": recent_issues,
            "recentPullRequests": recent_pull_requests,
            "releases": releases,
            "latestRelease": latest_release,
            "parentId": parent_id,
            "parentNameWithOwner": parent_name_with_owner,
            "readmeText": readme_text,
            "hasReadme": has_readme,
            "vulnerabilityAlertsCount": vulnerability_alerts_count,
            "vulnerabilities": vulnerabilities,
            "dependencyGraphManifests": dependency_graph_manifests,
            "networkCount": data.get("networkCount", data.get("forkCount", 0))
        }
        
        return cls(**repo_data)
