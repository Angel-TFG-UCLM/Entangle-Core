"""
Modelo optimizado de datos para Repository (Repositorio de GitHub).
Pydantic v2 - Limpio, estructurado y eficiente.

Conserva:
  ✅ Métricas numéricas (stars, forks, watchers, etc.)
  ✅ Métricas de actividad (commits, issues, PRs, releases)
  ✅ Fechas clave (created, updated, pushed, last_commit)
  ✅ Datos cualitativos (topics, license, description, primary_language)
  ✅ Colaboradores (modelo simplificado)
  ✅ README (opcional/diferido)

Elimina:
  ❌ URLs redundantes (solo html_url)
  ❌ IDs internos sin valor (node_id, organization_id fuera de owner)
  ❌ Flags booleanos irrelevantes (is_template, has_projects, has_wiki, has_pages, is_disabled)
  ❌ Bloques de seguridad detallados (vulnerabilities, security_policy)
  ⚠️ Aplanar languages a estructura simple
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, ConfigDict


# ==================== SUB-MODELOS SIMPLIFICADOS ====================

class LanguageInfo(BaseModel):
    """Lenguaje de programación - Modelo aplanado."""
    model_config = ConfigDict(populate_by_name=True)
    
    name: str
    size: int = 0  # Bytes de código en este lenguaje
    

class LicenseInfo(BaseModel):
    """Información de licencia de software."""
    model_config = ConfigDict(populate_by_name=True)
    
    key: str  # e.g., "apache-2.0"
    name: str  # e.g., "Apache License 2.0"
    spdx_id: Optional[str] = Field(None, alias="spdxId")
    url: Optional[str] = None


class OwnerInfo(BaseModel):
    """Propietario del repositorio (User u Organization)."""
    model_config = ConfigDict(populate_by_name=True)
    
    id: str
    login: str
    url: str  # Solo URL principal de GitHub
    avatar_url: Optional[str] = Field(None, alias="avatarUrl")
    type: Optional[str] = Field(None, alias="__typename")  # "User" o "Organization"


class CollaboratorInfo(BaseModel):
    """Colaborador del repositorio - Modelo simplificado."""
    model_config = ConfigDict(populate_by_name=True)
    
    login: str
    id: str
    contributions: int = 0
    has_commits: bool = False
    is_mentionable: bool = True


class CommitInfo(BaseModel):
    """Commit reciente - Información mínima."""
    model_config = ConfigDict(populate_by_name=True)
    
    oid: str  # SHA del commit
    message: str
    committed_date: Optional[datetime] = Field(None, alias="committedDate")
    author_login: Optional[str] = Field(None, alias="authorLogin")


class IssueInfo(BaseModel):
    """Issue - Información esencial."""
    model_config = ConfigDict(populate_by_name=True)
    
    id: str
    number: int
    title: str
    state: str  # OPEN, CLOSED
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    closed_at: Optional[datetime] = Field(None, alias="closedAt")


class PullRequestInfo(BaseModel):
    """Pull Request - Información esencial."""
    model_config = ConfigDict(populate_by_name=True)
    
    id: str
    number: int
    title: str
    state: str  # OPEN, CLOSED, MERGED
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    closed_at: Optional[datetime] = Field(None, alias="closedAt")
    merged_at: Optional[datetime] = Field(None, alias="mergedAt")


class ReleaseInfo(BaseModel):
    """Release - Información clave."""
    model_config = ConfigDict(populate_by_name=True)
    
    id: str
    tag_name: str = Field(alias="tagName")
    name: Optional[str] = None
    published_at: Optional[datetime] = Field(None, alias="publishedAt")
    is_prerelease: bool = Field(False, alias="isPrerelease")
    is_draft: bool = Field(False, alias="isDraft")


# ==================== MODELO PRINCIPAL ====================

class Repository(BaseModel):
    """
    Modelo optimizado de repositorio de GitHub.
    
    Estructura limpia y eficiente para análisis estadístico.
    Elimina redundancias y conserva datos esenciales.
    """
    model_config = ConfigDict(populate_by_name=True)
    
    # ==================== IDENTIFICACIÓN ====================
    id: str  # ID único de GitHub (GraphQL)
    name: str
    name_with_owner: str = Field(alias="nameWithOwner")
    full_name: Optional[str] = Field(None, alias="fullName")  # Compatibilidad REST API
    
    # ==================== DESCRIPCIÓN ====================
    description: Optional[str] = None
    url: str  # ✅ SOLO html_url (GitHub web)
    homepage_url: Optional[str] = Field(None, alias="homepageUrl")
    
    # ==================== PROPIETARIO ====================
    owner: Optional[OwnerInfo] = None
    
    # ==================== FECHAS CLAVE ====================
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    updated_at: Optional[datetime] = Field(None, alias="updatedAt")
    pushed_at: Optional[datetime] = Field(None, alias="pushedAt")
    last_commit_date: Optional[datetime] = Field(None, alias="lastCommitDate")
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    
    # ==================== LENGUAJE PRINCIPAL ====================
    primary_language: Optional[str] = Field(None, alias="primaryLanguage")  # Solo nombre
    
    # ==================== LENGUAJES (APLANADO) ====================
    languages: List[LanguageInfo] = Field(default_factory=list)
    languages_count: int = Field(0, alias="languagesCount")
    
    # ==================== TOPICS ====================
    repository_topics: List[str] = Field(default_factory=list, alias="repositoryTopics")  # Solo nombres
    topics_count: int = Field(0, alias="topicsCount")
    
    # ==================== MÉTRICAS DE POPULARIDAD ====================
    stargazer_count: int = Field(0, alias="stargazerCount")
    fork_count: int = Field(0, alias="forkCount")
    watchers_count: int = Field(0, alias="watchersCount")
    subscribers_count: int = Field(0, alias="subscribersCount")
    network_count: int = Field(0, alias="networkCount")  # Total de forks en red
    
    # ==================== MÉTRICAS DE CONTENIDO ====================
    disk_usage: int = Field(0, alias="diskUsage")  # KB
    
    # ==================== COMMITS ====================
    commits_count: int = Field(0, alias="commitsCount")
    branches_count: int = Field(0, alias="branchesCount")
    tags_count: int = Field(0, alias="tagsCount")
    recent_commits: List[CommitInfo] = Field(default_factory=list, alias="recentCommits")
    
    # ==================== ISSUES ====================
    issues_count: int = Field(0, alias="issuesCount")
    open_issues_count: int = Field(0, alias="openIssuesCount")
    closed_issues_count: int = Field(0, alias="closedIssuesCount")
    recent_issues: List[IssueInfo] = Field(default_factory=list, alias="recentIssues")
    
    # ==================== PULL REQUESTS ====================
    pull_requests_count: int = Field(0, alias="pullRequestsCount")
    open_pull_requests_count: int = Field(0, alias="openPullRequestsCount")
    closed_pull_requests_count: int = Field(0, alias="closedPullRequestsCount")
    merged_pull_requests_count: int = Field(0, alias="mergedPullRequestsCount")
    recent_pull_requests: List[PullRequestInfo] = Field(default_factory=list, alias="recentPullRequests")
    
    # ==================== RELEASES ====================
    releases_count: int = Field(0, alias="releasesCount")
    latest_release: Optional[ReleaseInfo] = Field(None, alias="latestRelease")
    releases: List[ReleaseInfo] = Field(default_factory=list)
    
    # ==================== COLABORADORES (SIMPLIFICADO) ====================
    collaborators: List[CollaboratorInfo] = Field(default_factory=list)
    collaborators_count: int = Field(0, alias="collaboratorsCount")
    
    # ==================== ESTADOS RELEVANTES ====================
    is_fork: bool = Field(False, alias="isFork")
    is_archived: bool = Field(False, alias="isArchived")
    
    # ==================== LICENCIA ====================
    license_info: Optional[LicenseInfo] = Field(None, alias="licenseInfo")
    
    # ==================== BRANCH PRINCIPAL ====================
    default_branch_ref_name: Optional[str] = Field(None, alias="defaultBranchRefName")
    
    # ==================== PARENT (si es fork) ====================
    parent_id: Optional[str] = Field(None, alias="parentId")
    parent_name_with_owner: Optional[str] = Field(None, alias="parentNameWithOwner")
    
    # ==================== README (OPCIONAL/DIFERIDO) ====================
    readme_text: Optional[str] = Field(None, alias="readmeText")  # Puede ser pesado
    has_readme: bool = Field(False, alias="hasReadme")
    
    # ==================== SEGURIDAD (SOLO CONTADOR) ====================
    vulnerability_alerts_count: int = Field(0, alias="vulnerabilityAlertsCount")
    
    # ==================== DEPENDENCIAS (SOLO MANIFIESTOS) ====================
    dependency_graph_manifests: List[Dict[str, Any]] = Field(default_factory=list, alias="dependencyGraphManifests")
    
    # ==================== METADATA ADICIONAL ====================
    code_of_conduct: Optional[Dict[str, str]] = Field(None, alias="codeOfConduct")  # Simplificado
    funding_links: List[Dict[str, str]] = Field(default_factory=list, alias="fundingLinks")
    custom_properties: Dict[str, Any] = Field(default_factory=dict, alias="customProperties")
    
    # ==================== ENRIQUECIMIENTO ====================
    enrichment_status: Dict[str, Any] = Field(default_factory=dict, alias="enrichmentStatus")
    
    @field_validator('ingested_at', mode='before')
    @classmethod
    def set_ingested_at(cls, v):
        """Establece la fecha de ingesta si no está presente."""
        return v or datetime.utcnow()
    
    @field_validator('primary_language', mode='before')
    @classmethod
    def extract_primary_language_name(cls, v):
        """Extrae solo el nombre del lenguaje principal."""
        if isinstance(v, dict):
            return v.get('name')
        return v
    
    def to_mongo_dict(self) -> dict:
        """
        Convierte a diccionario para MongoDB.
        Usa _id en lugar de id para el índice primario.
        """
        data = self.model_dump(by_alias=True, exclude_none=True)
        if 'id' in data:
            data['_id'] = data.pop('id')
        return data
    
    @classmethod
    def from_graphql_response(cls, data: dict) -> "Repository":
        """
        Crea instancia desde respuesta GraphQL optimizada.
        Aplana estructuras anidadas y elimina redundancias.
        
        Args:
            data: Respuesta GraphQL del repositorio
            
        Returns:
            Repository: Instancia optimizada
        """
        # ==================== OWNER ====================
        owner_data = data.get("owner")
        owner = None
        if owner_data:
            owner = OwnerInfo(
                id=owner_data.get("id", ""),
                login=owner_data.get("login", ""),
                url=owner_data.get("url", ""),
                avatarUrl=owner_data.get("avatarUrl"),
                **{"__typename": owner_data.get("__typename")}
            )
        
        # ==================== LENGUAJES (APLANADO) ====================
        languages_data = data.get("languages", {})
        languages_edges = languages_data.get("edges", [])
        languages = []
        for edge in languages_edges:
            node = edge.get("node", {})
            languages.append(LanguageInfo(
                name=node.get("name", ""),
                size=edge.get("size", 0)
            ))
        languages_count = languages_data.get("totalCount", 0)
        
        # Lenguaje principal (solo nombre)
        primary_language_data = data.get("primaryLanguage")
        primary_language = primary_language_data.get("name") if primary_language_data else None
        
        # ==================== TOPICS (SOLO NOMBRES) ====================
        topics_data = data.get("repositoryTopics", {})
        topics_nodes = topics_data.get("nodes", [])
        repository_topics = [node.get("topic", {}).get("name", "") for node in topics_nodes if node.get("topic")]
        topics_count = topics_data.get("totalCount", 0)
        
        # ==================== COLABORADORES (SIMPLIFICADO) ====================
        collaborators_data = data.get("collaborators", {})
        collaborators_nodes = collaborators_data.get("nodes", [])
        collaborators = []
        for collab in collaborators_nodes:
            collaborators.append(CollaboratorInfo(
                login=collab.get("login", ""),
                id=collab.get("id", ""),
                contributions=collab.get("contributions", 0),
                has_commits=collab.get("hasCommits", False),
                is_mentionable=collab.get("isMentionable", True)
            ))
        collaborators_count = collaborators_data.get("totalCount", 0)
        
        # ==================== CONTADORES DE MÉTRICAS ====================
        watchers_count = data.get("watchers", {}).get("totalCount", 0)
        subscribers_count = data.get("subscribers", {}).get("totalCount", 0)
        network_count = data.get("networkCount", data.get("forkCount", 0))
        
        # ==================== ISSUES ====================
        issues_data = data.get("issues", {})
        issues_count = issues_data.get("totalCount", 0)
        open_issues_count = data.get("openIssues", {}).get("totalCount", 0)
        closed_issues_count = data.get("closedIssues", {}).get("totalCount", 0)
        
        recent_issues = []
        for issue_node in issues_data.get("nodes", [])[:5]:
            recent_issues.append(IssueInfo(
                id=issue_node.get("id", ""),
                number=issue_node.get("number", 0),
                title=issue_node.get("title", ""),
                state=issue_node.get("state", ""),
                createdAt=issue_node.get("createdAt"),
                closedAt=issue_node.get("closedAt")
            ))
        
        # ==================== PULL REQUESTS ====================
        pull_requests_data = data.get("pullRequests", {})
        pull_requests_count = pull_requests_data.get("totalCount", 0)
        open_pull_requests_count = data.get("openPullRequests", {}).get("totalCount", 0)
        closed_pull_requests_count = data.get("closedPullRequests", {}).get("totalCount", 0)
        merged_pull_requests_count = data.get("mergedPullRequests", {}).get("totalCount", 0)
        
        recent_pull_requests = []
        for pr_node in pull_requests_data.get("nodes", [])[:5]:
            recent_pull_requests.append(PullRequestInfo(
                id=pr_node.get("id", ""),
                number=pr_node.get("number", 0),
                title=pr_node.get("title", ""),
                state=pr_node.get("state", ""),
                createdAt=pr_node.get("createdAt"),
                closedAt=pr_node.get("closedAt"),
                mergedAt=pr_node.get("mergedAt")
            ))
        
        # ==================== COMMITS ====================
        commits_count = 0
        branches_count = data.get("refs", {}).get("totalCount", 0)
        tags_count = data.get("tags", {}).get("totalCount", 0)
        default_branch_name = None
        recent_commits = []
        last_commit_date = None
        
        default_branch_data = data.get("defaultBranchRef")
        if default_branch_data:
            default_branch_name = default_branch_data.get("name")
            target = default_branch_data.get("target", {})
            history = target.get("history", {})
            commits_count = history.get("totalCount", 0)
            
            commits_edges = history.get("edges", [])
            for edge in commits_edges[:10]:
                commit_node = edge.get("node", {})
                author_info = commit_node.get("author", {})
                author_user = author_info.get("user", {})
                
                recent_commits.append(CommitInfo(
                    oid=commit_node.get("oid", ""),
                    message=commit_node.get("message", ""),
                    committedDate=commit_node.get("committedDate"),
                    authorLogin=author_user.get("login") if author_user else None
                ))
            
            if commits_edges:
                last_commit_date = commits_edges[0].get("node", {}).get("committedDate")
        
        # ==================== RELEASES ====================
        releases_data = data.get("releases", {})
        releases_count = releases_data.get("totalCount", 0)
        releases = []
        for release_node in releases_data.get("nodes", []):
            releases.append(ReleaseInfo(
                id=release_node.get("id", ""),
                tagName=release_node.get("tagName", ""),
                name=release_node.get("name"),
                publishedAt=release_node.get("publishedAt"),
                isPrerelease=release_node.get("isPrerelease", False),
                isDraft=release_node.get("isDraft", False)
            ))
        latest_release = releases[0] if releases else None
        
        # ==================== PARENT (si es fork) ====================
        parent_id = None
        parent_name_with_owner = None
        parent_data = data.get("parent")
        if parent_data:
            parent_id = parent_data.get("id")
            parent_name_with_owner = parent_data.get("nameWithOwner")
        
        # ==================== LICENCIA ====================
        license_data = data.get("licenseInfo")
        license_info = None
        if license_data:
            license_info = LicenseInfo(
                key=license_data.get("key"),
                name=license_data.get("name", ""),
                spdxId=license_data.get("spdxId")
            )
        
        # ==================== README ====================
        readme_text = None
        has_readme = False
        readme_object = data.get("object")
        if readme_object and isinstance(readme_object, dict):
            readme_text = readme_object.get("text")
            has_readme = bool(readme_text)
        
        # ==================== SEGURIDAD (SOLO CONTADOR) ====================
        vulnerability_alerts_data = data.get("vulnerabilityAlerts", {})
        vulnerability_alerts_count = vulnerability_alerts_data.get("totalCount", 0)
        
        # ==================== DEPENDENCIAS (MANIFIESTOS) ====================
        dependency_graph_data = data.get("dependencyGraphManifests", {})
        dependency_graph_manifests = []
        for manifest_node in dependency_graph_data.get("nodes", []):
            dependency_graph_manifests.append({
                "filename": manifest_node.get("filename", ""),
                "dependenciesCount": manifest_node.get("dependenciesCount", 0)
            })
        
        # ==================== CODE OF CONDUCT Y FUNDING ====================
        code_of_conduct_data = data.get("codeOfConduct")
        code_of_conduct = None
        if code_of_conduct_data:
            code_of_conduct = {
                "key": code_of_conduct_data.get("key", ""),
                "name": code_of_conduct_data.get("name", ""),
                "url": code_of_conduct_data.get("url", "")
            }
        
        funding_links = []
        for link in data.get("fundingLinks", []):
            funding_links.append({
                "platform": link.get("platform", ""),
                "url": link.get("url", "")
            })
        
        # ==================== CONSTRUIR REPOSITORIO ====================
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            nameWithOwner=data.get("nameWithOwner", ""),
            fullName=data.get("fullName"),
            description=data.get("description"),
            url=data.get("url", ""),
            homepageUrl=data.get("homepageUrl"),
            owner=owner,
            createdAt=data.get("createdAt"),
            updatedAt=data.get("updatedAt"),
            pushedAt=data.get("pushedAt"),
            lastCommitDate=last_commit_date,
            primaryLanguage=primary_language,
            languages=languages,
            languagesCount=languages_count,
            repositoryTopics=repository_topics,
            topicsCount=topics_count,
            stargazerCount=data.get("stargazerCount", 0),
            forkCount=data.get("forkCount", 0),
            watchersCount=watchers_count,
            subscribersCount=subscribers_count,
            networkCount=network_count,
            diskUsage=data.get("diskUsage", 0),
            commitsCount=commits_count,
            branchesCount=branches_count,
            tagsCount=tags_count,
            recentCommits=recent_commits,
            issuesCount=issues_count,
            openIssuesCount=open_issues_count,
            closedIssuesCount=closed_issues_count,
            recentIssues=recent_issues,
            pullRequestsCount=pull_requests_count,
            openPullRequestsCount=open_pull_requests_count,
            closedPullRequestsCount=closed_pull_requests_count,
            mergedPullRequestsCount=merged_pull_requests_count,
            recentPullRequests=recent_pull_requests,
            releasesCount=releases_count,
            latestRelease=latest_release,
            releases=releases,
            collaborators=collaborators,
            collaboratorsCount=collaborators_count,
            isFork=data.get("isFork", False),
            isArchived=data.get("isArchived", False),
            licenseInfo=license_info,
            defaultBranchRefName=default_branch_name,
            parentId=parent_id,
            parentNameWithOwner=parent_name_with_owner,
            readmeText=readme_text,
            hasReadme=has_readme,
            vulnerabilityAlertsCount=vulnerability_alerts_count,
            dependencyGraphManifests=dependency_graph_manifests,
            codeOfConduct=code_of_conduct,
            fundingLinks=funding_links,
            customProperties=data.get("customProperties", {}),
            enrichmentStatus=data.get("enrichmentStatus", {})
        )
