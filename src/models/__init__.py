"""
Modelos de datos para las entidades del proyecto.
Incluye modelos Pydantic para MongoDB con todos los campos de GitHub GraphQL API.
"""

# Repository models
from .repository import (
    Repository,
    Language,
    LanguageEdge,
    License,
    Topic,
    RepositoryTopic,
    Owner,
    Collaborator,
    Commit,
    Issue,
    PullRequest,
    Release,
    Vulnerability,
    DependencyGraphManifest
)

# Organization models
from .organization import (
    Organization,
    OrganizationRepository,
    Member,
    Team,
    SponsorListing
)

# User models
from .user import (
    User,
    UserRepository,
    UserOrganization,
    ContributionsCollection,
    CommitContributionsByRepository,
    StarredRepository,
    Gist,
    SocialAccount
)

# Relation models
from .relation import (
    Relation,
    RelationType,
    ContributionMetrics,
    TimeSeriesData
)

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
    
    # Organization
    "Organization",
    "OrganizationRepository",
    "Member",
    "Team",
    "SponsorListing",
    
    # User
    "User",
    "UserRepository",
    "UserOrganization",
    "ContributionsCollection",
    "CommitContributionsByRepository",
    "StarredRepository",
    "Gist",
    "SocialAccount",
    
    # Relation
    "Relation",
    "RelationType",
    "ContributionMetrics",
    "TimeSeriesData",
]
