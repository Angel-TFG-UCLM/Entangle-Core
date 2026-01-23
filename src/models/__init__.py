"""
Modelos de datos para las entidades del proyecto.
Incluye modelos Pydantic para MongoDB con todos los campos de GitHub GraphQL API.
"""

# Repository models v2.0 - OPTIMIZADO (Pydantic v2)
from .repository import (
    Repository,
    LanguageInfo,
    LicenseInfo,
    OwnerInfo,
    CollaboratorInfo,
    CommitInfo,
    IssueInfo,
    PullRequestInfo,
    ReleaseInfo
)

# Organization models v1.0 - INGESTA BÁSICA
from .organization import Organization

# User models v3.0 - LIMPIO (solo clases que existen)
from .user import (
    User,
    UserRepository,
    UserOrganization
)

# Relation models - DESHABILITADO: Para futura implementación de análisis de grafos
# from .relation import (
#     Relation,
#     RelationType,
#     ContributionMetrics,
#     TimeSeriesData
# )

__all__ = [
    # Repository
    "Repository",
    "Language",
    "LanguageEdge",
    "License",
    "Topic",
    "RepositoryTopic",
    "Owner",
    "Collaborator",
    "Commit",
    "Issue",
    "PullRequest",
    "Release",
    "Vulnerability",
    "DependencyGraphManifest",
    
    # Organization v1.0
    "Organization",
    
    # User v3.0
    "User",
    "UserRepository",
    "UserOrganization",
    
    # Relation
    "Relation",
    "RelationType",
    "ContributionMetrics",
    "TimeSeriesData",
]
