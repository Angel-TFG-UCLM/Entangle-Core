"""
Modelo de datos para Relation (Relaciones entre entidades de GitHub).
Modela las conexiones entre Users, Organizations y Repositories.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field, validator
from enum import Enum


class RelationType(str, Enum):
    """Tipos de relaciones entre entidades."""
    # Usuario <-> Repositorio
    OWNS = "owns"  # Usuario es propietario del repo
    CONTRIBUTES = "contributes"  # Usuario contribuye al repo
    STARS = "stars"  # Usuario da estrella al repo
    WATCHES = "watches"  # Usuario observa el repo
    FORKS = "forks"  # Usuario hace fork del repo
    
    # Usuario <-> Organización
    MEMBER_OF = "member_of"  # Usuario es miembro de la org
    OWNER_OF_ORG = "owner_of_org"  # Usuario es owner de la org
    
    # Usuario <-> Usuario
    FOLLOWS = "follows"  # Usuario sigue a otro usuario
    SPONSORS = "sponsors"  # Usuario patrocina a otro usuario
    
    # Organización <-> Repositorio
    ORG_OWNS = "org_owns"  # Organización es propietaria del repo
    
    # Repositorio <-> Repositorio
    FORK_OF = "fork_of"  # Repo es fork de otro repo
    DEPENDS_ON = "depends_on"  # Repo depende de otro repo
    
    # Colaboración en Issues/PRs
    OPENED_ISSUE = "opened_issue"  # Usuario abrió issue
    COMMENTED_ISSUE = "commented_issue"  # Usuario comentó issue
    CLOSED_ISSUE = "closed_issue"  # Usuario cerró issue
    OPENED_PR = "opened_pr"  # Usuario abrió PR
    REVIEWED_PR = "reviewed_pr"  # Usuario revisó PR
    MERGED_PR = "merged_pr"  # Usuario mergeó PR
    
    # Commits
    COMMITTED = "committed"  # Usuario hizo commit


class ContributionMetrics(BaseModel):
    """Métricas de contribución en una relación."""
    commits_count: int = Field(0, alias="commitsCount")
    additions: int = 0  # Líneas añadidas
    deletions: int = 0  # Líneas eliminadas
    issues_opened: int = Field(0, alias="issuesOpened")
    issues_closed: int = Field(0, alias="issuesClosed")
    issues_commented: int = Field(0, alias="issuesCommented")
    pull_requests_opened: int = Field(0, alias="pullRequestsOpened")
    pull_requests_merged: int = Field(0, alias="pullRequestsMerged")
    pull_requests_reviewed: int = Field(0, alias="pullRequestsReviewed")
    code_reviews_count: int = Field(0, alias="codeReviewsCount")
    
    class Config:
        populate_by_name = True


class TimeSeriesData(BaseModel):
    """Datos de actividad en series temporales."""
    date: datetime
    count: int
    
    class Config:
        populate_by_name = True


class Relation(BaseModel):
    """
    Modelo completo de relaciones entre entidades de GitHub.
    Permite modelar grafos de colaboración y análisis de redes sociales.
    """
    # ==================== IDENTIFICACIÓN ====================
    id: Optional[str] = None  # ID generado automáticamente por MongoDB
    
    # ==================== TIPO DE RELACIÓN ====================
    relation_type: RelationType = Field(alias="relationType")
    
    # ==================== ENTIDADES RELACIONADAS ====================
    # Source (origen de la relación)
    source_id: str = Field(alias="sourceId")
    source_type: str = Field(alias="sourceType")  # "User", "Organization", "Repository"
    source_login: Optional[str] = Field(None, alias="sourceLogin")  # login para Users/Orgs
    source_name: Optional[str] = Field(None, alias="sourceName")  # name para Repos
    
    # Target (destino de la relación)
    target_id: str = Field(alias="targetId")
    target_type: str = Field(alias="targetType")  # "User", "Organization", "Repository"
    target_login: Optional[str] = Field(None, alias="targetLogin")  # login para Users/Orgs
    target_name: Optional[str] = Field(None, alias="targetName")  # name para Repos
    
    # ==================== METADATOS DE LA RELACIÓN ====================
    started_at: Optional[datetime] = Field(None, alias="startedAt")  # Cuándo comenzó la relación
    ended_at: Optional[datetime] = Field(None, alias="endedAt")  # Cuándo terminó (si aplica)
    last_activity_at: Optional[datetime] = Field(None, alias="lastActivityAt")  # Última actividad
    is_active: bool = Field(True, alias="isActive")  # Si la relación está activa
    
    # ==================== FECHAS DE INGESTA ====================
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # ==================== MÉTRICAS DE CONTRIBUCIÓN ====================
    contribution_metrics: Optional[ContributionMetrics] = Field(None, alias="contributionMetrics")
    total_contributions: int = Field(0, alias="totalContributions")
    
    # ==================== PESO DE LA RELACIÓN ====================
    weight: float = 1.0  # Peso de la relación (para análisis de grafos)
    strength: Optional[str] = None  # "weak", "medium", "strong"
    
    # ==================== ROLES Y PERMISOS ====================
    role: Optional[str] = None  # Para relaciones Member/Owner: "member", "admin", "owner"
    permission: Optional[str] = None  # Para repos: "read", "write", "admin"
    
    # ==================== DATOS DE ACTIVIDAD TEMPORAL ====================
    activity_timeline: List[TimeSeriesData] = Field(default_factory=list)
    
    # ==================== CONTEXTO ADICIONAL ====================
    repository_context: Optional[Dict[str, Any]] = None  # Info adicional del repo (si aplica)
    organization_context: Optional[Dict[str, Any]] = None  # Info adicional de la org (si aplica)
    
    # ==================== FLAGS BOOLEANOS ====================
    is_direct: bool = Field(True, alias="isDirect")  # Si es una relación directa
    is_verified: bool = Field(True, alias="isVerified")  # Si está verificada
    is_public: bool = Field(True, alias="isPublic")  # Si es pública
    
    # ==================== METADATA ADICIONAL ====================
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)  # Etiquetas personalizadas
    
    # ==================== CAMPOS PERSONALIZADOS ====================
    custom_properties: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        populate_by_name = True
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }
    
    @validator('ingested_at', 'updated_at', pre=True, always=True)
    def set_timestamps(cls, v):
        """Establece timestamps si no están presentes."""
        return v or datetime.utcnow()
    
    @validator('weight', pre=True, always=True)
    def validate_weight(cls, v):
        """Valida que el peso esté entre 0 y 1 (o mayor si se usa escala diferente)."""
        if v is None:
            return 1.0
        return max(0.0, float(v))
    
    @validator('strength', pre=True, always=True)
    def calculate_strength(cls, v, values):
        """Calcula la fuerza de la relación basada en métricas."""
        if v:
            return v
        
        # Auto-calcular strength basado en total_contributions
        total = values.get('total_contributions', 0)
        if total == 0:
            return "weak"
        elif total < 10:
            return "weak"
        elif total < 50:
            return "medium"
        else:
            return "strong"
    
    def to_dict(self) -> dict:
        """Convierte el modelo a diccionario para MongoDB."""
        return self.model_dump(by_alias=True, exclude_none=True)
    
    def to_mongo_dict(self) -> dict:
        """
        Convierte el modelo a diccionario optimizado para MongoDB.
        Usa _id en lugar de id si está presente.
        """
        data = self.to_dict()
        if 'id' in data and data['id']:
            data['_id'] = data.pop('id')
        elif 'id' in data:
            data.pop('id')  # Elimina id=None para que MongoDB genere uno
        return data
    
    def to_graph_edge(self) -> Dict[str, Any]:
        """
        Convierte la relación a formato de arista para análisis de grafos.
        
        Returns:
            Diccionario con formato: {source, target, weight, type, ...}
        """
        return {
            "source": self.source_id,
            "target": self.target_id,
            "weight": self.weight,
            "type": self.relation_type,
            "strength": self.strength,
            "contributions": self.total_contributions,
            "last_activity": self.last_activity_at.isoformat() if self.last_activity_at else None
        }
    
    @classmethod
    def create_user_repo_contribution(
        cls,
        user_id: str,
        user_login: str,
        repo_id: str,
        repo_name: str,
        contribution_metrics: ContributionMetrics,
        started_at: Optional[datetime] = None
    ) -> "Relation":
        """
        Crea una relación de contribución Usuario -> Repositorio.
        
        Args:
            user_id: ID del usuario
            user_login: Login del usuario
            repo_id: ID del repositorio
            repo_name: Nombre del repositorio
            contribution_metrics: Métricas de contribución
            started_at: Fecha de inicio (opcional)
            
        Returns:
            Instancia de Relation
        """
        total_contributions = (
            contribution_metrics.commits_count +
            contribution_metrics.issues_opened +
            contribution_metrics.pull_requests_opened
        )
        
        return cls(
            relationType=RelationType.CONTRIBUTES,
            sourceId=user_id,
            sourceType="User",
            sourceLogin=user_login,
            targetId=repo_id,
            targetType="Repository",
            targetName=repo_name,
            startedAt=started_at,
            contributionMetrics=contribution_metrics,
            totalContributions=total_contributions,
            weight=min(total_contributions / 100.0, 1.0)  # Normalizar peso
        )
    
    @classmethod
    def create_user_org_membership(
        cls,
        user_id: str,
        user_login: str,
        org_id: str,
        org_login: str,
        role: str = "member",
        started_at: Optional[datetime] = None
    ) -> "Relation":
        """
        Crea una relación de membresía Usuario -> Organización.
        
        Args:
            user_id: ID del usuario
            user_login: Login del usuario
            org_id: ID de la organización
            org_login: Login de la organización
            role: Rol del usuario ("member", "admin", "owner")
            started_at: Fecha de inicio (opcional)
            
        Returns:
            Instancia de Relation
        """
        relation_type = RelationType.OWNER_OF_ORG if role == "owner" else RelationType.MEMBER_OF
        
        return cls(
            relationType=relation_type,
            sourceId=user_id,
            sourceType="User",
            sourceLogin=user_login,
            targetId=org_id,
            targetType="Organization",
            targetLogin=org_login,
            role=role,
            startedAt=started_at
        )
    
    @classmethod
    def create_user_follows_user(
        cls,
        follower_id: str,
        follower_login: str,
        followed_id: str,
        followed_login: str,
        started_at: Optional[datetime] = None
    ) -> "Relation":
        """
        Crea una relación de seguimiento Usuario -> Usuario.
        
        Args:
            follower_id: ID del seguidor
            follower_login: Login del seguidor
            followed_id: ID del seguido
            followed_login: Login del seguido
            started_at: Fecha de inicio (opcional)
            
        Returns:
            Instancia de Relation
        """
        return cls(
            relationType=RelationType.FOLLOWS,
            sourceId=follower_id,
            sourceType="User",
            sourceLogin=follower_login,
            targetId=followed_id,
            targetType="User",
            targetLogin=followed_login,
            startedAt=started_at
        )
    
    @classmethod
    def create_repo_fork(
        cls,
        fork_id: str,
        fork_name: str,
        parent_id: str,
        parent_name: str,
        forked_at: Optional[datetime] = None
    ) -> "Relation":
        """
        Crea una relación de fork Repositorio -> Repositorio.
        
        Args:
            fork_id: ID del fork
            fork_name: Nombre del fork
            parent_id: ID del repositorio padre
            parent_name: Nombre del repositorio padre
            forked_at: Fecha del fork (opcional)
            
        Returns:
            Instancia de Relation
        """
        return cls(
            relationType=RelationType.FORK_OF,
            sourceId=fork_id,
            sourceType="Repository",
            sourceName=fork_name,
            targetId=parent_id,
            targetType="Repository",
            targetName=parent_name,
            startedAt=forked_at
        )
