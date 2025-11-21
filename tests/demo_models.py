"""
Script de demostración del uso de los modelos Pydantic para MongoDB.
Muestra cómo crear instancias, validar datos y convertir a MongoDB.
"""

from datetime import datetime
from src.models import (
    Repository,
    Organization,
    User,
    Relation,
    RelationType,
    ContributionMetrics,
    Language,
    Owner
)


def demo_repository_model():
    """Demuestra el uso del modelo Repository."""
    print("\n" + "="*80)
    print("🗂️  DEMO: Repository Model")
    print("="*80)
    
    # Simular datos de GraphQL
    graphql_data = {
        "id": "MDEwOlJlcG9zaXRvcnkxOTM4MzU5MzA=",
        "name": "qiskit",
        "nameWithOwner": "Qiskit/qiskit",
        "description": "Qiskit is an open-source SDK for working with quantum computers",
        "url": "https://github.com/Qiskit/qiskit",
        "owner": {
            "id": "MDEyOk9yZ2FuaXphdGlvbjQ1ODUyOTA5",
            "login": "Qiskit",
            "avatarUrl": "https://avatars.githubusercontent.com/u/45852909",
            "url": "https://github.com/Qiskit",
            "__typename": "Organization"
        },
        "createdAt": "2019-06-24T15:00:00Z",
        "updatedAt": "2025-10-14T10:30:00Z",
        "pushedAt": "2025-10-14T09:15:00Z",
        "primaryLanguage": {
            "name": "Python",
            "color": "#3572A5"
        },
        "stargazerCount": 5234,
        "forkCount": 1234,
        "watchers": {"totalCount": 234},
        "diskUsage": 50234,
        "defaultBranchRef": {
            "name": "main",
            "target": {
                "history": {
                    "totalCount": 3456
                }
            }
        },
        "issues": {"totalCount": 1234},
        "openIssues": {"totalCount": 89},
        "closedIssues": {"totalCount": 1145},
        "pullRequests": {"totalCount": 2345},
        "isPrivate": False,
        "isFork": False,
        "isArchived": False,
        "licenseInfo": {
            "key": "apache-2.0",
            "name": "Apache License 2.0",
            "spdxId": "Apache-2.0",
            "url": "https://api.github.com/licenses/apache-2.0"
        }
    }
    
    # Crear instancia usando el parser
    repo = Repository.from_graphql_response(graphql_data)
    
    print(f"\n✅ Repository creado desde GraphQL:")
    print(f"   ID: {repo.id}")
    print(f"   Nombre: {repo.name_with_owner}")
    print(f"   Descripción: {repo.description[:50]}...")
    print(f"   Owner: {repo.owner.login if repo.owner else 'N/A'}")
    print(f"   Lenguaje: {repo.primary_language.name if repo.primary_language else 'N/A'}")
    print(f"   Estrellas: {repo.stargazer_count}")
    print(f"   Forks: {repo.fork_count}")
    print(f"   Commits: {repo.commits_count}")
    print(f"   Issues: {repo.issues_count} (abiertos: {repo.open_issues_count})")
    print(f"   Archivado: {repo.is_archived}")
    print(f"   Licencia: {repo.license_info.name if repo.license_info else 'N/A'}")
    
    # Convertir a diccionario MongoDB
    mongo_dict = repo.to_mongo_dict()
    print(f"\n✅ Convertido a MongoDB dict:")
    print(f"   Tiene _id: {'_id' in mongo_dict}")
    print(f"   Campos: {len(mongo_dict)} campos")
    print(f"   Fecha de ingesta: {mongo_dict.get('ingestedAt', 'N/A')}")
    
    return repo


def demo_organization_model():
    """Demuestra el uso del modelo Organization."""
    print("\n" + "="*80)
    print("🏢  DEMO: Organization Model")
    print("="*80)
    
    graphql_data = {
        "id": "MDEyOk9yZ2FuaXphdGlvbjQ1ODUyOTA5",
        "login": "Qiskit",
        "name": "Qiskit",
        "description": "Open-source quantum computing framework",
        "url": "https://github.com/Qiskit",
        "websiteUrl": "https://qiskit.org",
        "avatarUrl": "https://avatars.githubusercontent.com/u/45852909",
        "email": "hello@qiskit.org",
        "location": "New York, NY",
        "twitterUsername": "Qiskit",
        "createdAt": "2018-12-07T18:30:00Z",
        "updatedAt": "2025-10-14T10:00:00Z",
        "repositories": {
            "totalCount": 156,
            "nodes": [
                {
                    "id": "MDEwOlJlcG9zaXRvcnkxOTM4MzU5MzA=",
                    "name": "qiskit",
                    "nameWithOwner": "Qiskit/qiskit",
                    "description": "Qiskit SDK",
                    "url": "https://github.com/Qiskit/qiskit",
                    "stargazerCount": 5234,
                    "forkCount": 1234,
                    "watchers": {"totalCount": 234},
                    "isPrivate": False,
                    "isFork": False,
                    "isArchived": False
                }
            ]
        },
        "membersWithRole": {
            "totalCount": 234,
            "nodes": [
                {
                    "id": "MDQ6VXNlcjEyMzQ1Njc=",
                    "login": "johndoe",
                    "name": "John Doe",
                    "avatarUrl": "https://avatars.githubusercontent.com/u/1234567",
                    "url": "https://github.com/johndoe",
                    "followers": {"totalCount": 123}
                }
            ]
        },
        "isVerified": True,
        "hasOrganizationProjectsEnabled": True
    }
    
    org = Organization.from_graphql_response(graphql_data)
    
    print(f"\n✅ Organization creada desde GraphQL:")
    print(f"   ID: {org.id}")
    print(f"   Login: {org.login}")
    print(f"   Nombre: {org.name}")
    print(f"   Descripción: {org.description}")
    print(f"   Website: {org.website_url}")
    print(f"   Verificada: {org.is_verified}")
    print(f"   Repositorios: {org.repositories_count}")
    print(f"   Miembros: {org.members_count}")
    print(f"   Repos cargados: {len(org.repositories)}")
    print(f"   Miembros cargados: {len(org.members)}")
    
    mongo_dict = org.to_mongo_dict()
    print(f"\n✅ Convertido a MongoDB dict:")
    print(f"   Tiene _id: {'_id' in mongo_dict}")
    print(f"   Campos: {len(mongo_dict)} campos")
    
    return org


def demo_user_model():
    """Demuestra el uso del modelo User."""
    print("\n" + "="*80)
    print("👤  DEMO: User Model")
    print("="*80)
    
    graphql_data = {
        "id": "MDQ6VXNlcjEyMzQ1Njc=",
        "login": "johndoe",
        "name": "John Doe",
        "email": "john@example.com",
        "bio": "Quantum software developer",
        "company": "Qiskit",
        "location": "New York, NY",
        "avatarUrl": "https://avatars.githubusercontent.com/u/1234567",
        "url": "https://github.com/johndoe",
        "websiteUrl": "https://johndoe.dev",
        "twitterUsername": "johndoe",
        "createdAt": "2015-03-15T12:00:00Z",
        "updatedAt": "2025-10-14T10:00:00Z",
        "followers": {"totalCount": 234},
        "following": {"totalCount": 56},
        "repositories": {
            "totalCount": 45,
            "nodes": [
                {
                    "id": "MDEwOlJlcG9zaXRvcnkxMjM0NTY=",
                    "name": "quantum-lib",
                    "nameWithOwner": "johndoe/quantum-lib",
                    "description": "A quantum computing library",
                    "url": "https://github.com/johndoe/quantum-lib",
                    "stargazerCount": 123,
                    "forkCount": 23,
                    "watchers": {"totalCount": 12},
                    "isPrivate": False,
                    "isFork": False,
                    "isArchived": False
                }
            ]
        },
        "organizations": {
            "totalCount": 2,
            "nodes": [
                {
                    "id": "MDEyOk9yZ2FuaXphdGlvbjQ1ODUyOTA5",
                    "login": "Qiskit",
                    "name": "Qiskit",
                    "avatarUrl": "https://avatars.githubusercontent.com/u/45852909",
                    "url": "https://github.com/Qiskit"
                }
            ]
        },
        "contributionsCollection": {
            "totalCommitContributions": 1234,
            "totalIssueContributions": 45,
            "totalPullRequestContributions": 67,
            "totalPullRequestReviewContributions": 89,
            "totalRepositoryContributions": 12,
            "restrictedContributionsCount": 0
        },
        "issues": {"totalCount": 45},
        "pullRequests": {"totalCount": 67},
        "isHireable": True
    }
    
    user = User.from_graphql_response(graphql_data)
    
    print(f"\n✅ User creado desde GraphQL:")
    print(f"   ID: {user.id}")
    print(f"   Login: {user.login}")
    print(f"   Nombre: {user.name}")
    print(f"   Bio: {user.bio}")
    print(f"   Empresa: {user.company}")
    print(f"   Ubicación: {user.location}")
    print(f"   Seguidores: {user.followers_count}")
    print(f"   Siguiendo: {user.following_count}")
    print(f"   Repositorios: {user.repositories_count}")
    print(f"   Organizaciones: {user.organizations_count}")
    if user.contributions:
        print(f"   Commits: {user.contributions.total_commit_contributions}")
        print(f"   Issues: {user.contributions.total_issue_contributions}")
        print(f"   PRs: {user.contributions.total_pull_request_contributions}")
    print(f"   Disponible para contratar: {user.is_hireable}")
    
    mongo_dict = user.to_mongo_dict()
    print(f"\n✅ Convertido a MongoDB dict:")
    print(f"   Tiene _id: {'_id' in mongo_dict}")
    print(f"   Campos: {len(mongo_dict)} campos")
    
    return user


def demo_relation_model():
    """Demuestra el uso del modelo Relation."""
    print("\n" + "="*80)
    print("🔗  DEMO: Relation Model")
    print("="*80)
    
    # 1. Crear relación de contribución usando factory method
    metrics = ContributionMetrics(
        commitsCount=145,
        additions=12345,
        deletions=3456,
        issuesOpened=12,
        issuesClosed=8,
        issuesCommented=45,
        pullRequestsOpened=23,
        pullRequestsMerged=18,
        pullRequestsReviewed=34,
        codeReviewsCount=34
    )
    
    contribution = Relation.create_user_repo_contribution(
        user_id="MDQ6VXNlcjEyMzQ1Njc=",
        user_login="johndoe",
        repo_id="MDEwOlJlcG9zaXRvcnkxOTM4MzU5MzA=",
        repo_name="Qiskit/qiskit",
        contribution_metrics=metrics,
        started_at=datetime(2023, 1, 15)
    )
    
    print(f"\n✅ Relación de CONTRIBUCIÓN creada:")
    print(f"   Tipo: {contribution.relation_type}")
    print(f"   Source: {contribution.source_type} - {contribution.source_login}")
    print(f"   Target: {contribution.target_type} - {contribution.target_name}")
    print(f"   Inicio: {contribution.started_at}")
    print(f"   Activa: {contribution.is_active}")
    print(f"   Total contribuciones: {contribution.total_contributions}")
    print(f"   Peso: {contribution.weight}")
    print(f"   Fuerza: {contribution.strength}")
    if contribution.contribution_metrics:
        print(f"   Commits: {contribution.contribution_metrics.commits_count}")
        print(f"   Issues: {contribution.contribution_metrics.issues_opened}")
        print(f"   PRs: {contribution.contribution_metrics.pull_requests_opened}")
    
    # Convertir a formato de grafo
    graph_edge = contribution.to_graph_edge()
    print(f"\n✅ Formato de GRAFO:")
    print(f"   Source: {graph_edge['source']}")
    print(f"   Target: {graph_edge['target']}")
    print(f"   Weight: {graph_edge['weight']}")
    print(f"   Type: {graph_edge['type']}")
    print(f"   Strength: {graph_edge['strength']}")
    
    # 2. Crear relación de membresía
    membership = Relation.create_user_org_membership(
        user_id="MDQ6VXNlcjEyMzQ1Njc=",
        user_login="johndoe",
        org_id="MDEyOk9yZ2FuaXphdGlvbjQ1ODUyOTA5",
        org_login="Qiskit",
        role="member",
        started_at=datetime(2022, 6, 1)
    )
    
    print(f"\n✅ Relación de MEMBRESÍA creada:")
    print(f"   Tipo: {membership.relation_type}")
    print(f"   Source: {membership.source_type} - {membership.source_login}")
    print(f"   Target: {membership.target_type} - {membership.target_login}")
    print(f"   Rol: {membership.role}")
    print(f"   Inicio: {membership.started_at}")
    
    # 3. Crear relación de follow
    follow = Relation.create_user_follows_user(
        follower_id="MDQ6VXNlcjEyMzQ1Njc=",
        follower_login="johndoe",
        followed_id="MDQ6VXNlcjk4NzY1NDM=",
        followed_login="janedoe",
        started_at=datetime(2024, 3, 10)
    )
    
    print(f"\n✅ Relación de FOLLOW creada:")
    print(f"   Tipo: {follow.relation_type}")
    print(f"   Source: {follow.source_type} - {follow.source_login}")
    print(f"   Target: {follow.target_type} - {follow.target_login}")
    
    # Convertir a MongoDB
    mongo_dict = contribution.to_mongo_dict()
    print(f"\n✅ Relación convertida a MongoDB dict:")
    print(f"   No tiene id (MongoDB generará _id): {'id' not in mongo_dict or mongo_dict.get('id') is None}")
    print(f"   Campos: {len(mongo_dict)} campos")
    
    return contribution, membership, follow


def demo_validation():
    """Demuestra las validaciones de los modelos."""
    print("\n" + "="*80)
    print("✔️  DEMO: Validaciones")
    print("="*80)
    
    # Validación automática de ingested_at
    repo_data = {
        "id": "test123",
        "name": "test-repo",
        "nameWithOwner": "user/test-repo",
        "url": "https://github.com/user/test-repo",
        "stargazerCount": 10,
        "forkCount": 2
    }
    
    repo = Repository(**repo_data)
    
    print(f"\n✅ Validación de ingested_at:")
    print(f"   ingested_at auto-generado: {repo.ingested_at is not None}")
    print(f"   Valor: {repo.ingested_at}")
    
    # Validación de peso en Relation
    relation = Relation(
        relationType=RelationType.CONTRIBUTES,
        sourceId="user1",
        sourceType="User",
        sourceLogin="user1",
        targetId="repo1",
        targetType="Repository",
        targetName="org/repo",
        totalContributions=25
    )
    
    print(f"\n✅ Validación de weight y strength:")
    print(f"   Weight auto-asignado: {relation.weight}")
    print(f"   Strength auto-calculado: {relation.strength}")
    print(f"   (basado en totalContributions={relation.total_contributions})")


def main():
    """Ejecuta todas las demos."""
    print("\n" + "🎉 "*30)
    print("DEMOSTRACIÓN DE MODELOS PYDANTIC PARA MONGODB")
    print("🎉 "*30)
    
    # Demo de cada modelo
    repo = demo_repository_model()
    org = demo_organization_model()
    user = demo_user_model()
    contribution, membership, follow = demo_relation_model()
    demo_validation()
    
    # Resumen final
    print("\n" + "="*80)
    print("📊  RESUMEN")
    print("="*80)
    print(f"\n✅ Se crearon exitosamente:")
    print(f"   • 1 Repository")
    print(f"   • 1 Organization")
    print(f"   • 1 User")
    print(f"   • 3 Relations (contribución, membresía, follow)")
    print(f"\n✅ Todos los modelos incluyen:")
    print(f"   • Validación automática de campos")
    print(f"   • Conversión a diccionario MongoDB")
    print(f"   • Parser desde GraphQL response")
    print(f"   • Tipado estricto con Type hints")
    print(f"   • Campo ingested_at automático")
    print(f"\n✅ Sistema listo para:")
    print(f"   • Ingesta completa de datos desde GitHub")
    print(f"   • Reingestas incrementales")
    print(f"   • Análisis de grafos de colaboración")
    print(f"   • Búsquedas y agregaciones en MongoDB")
    
    print("\n" + "🎉 "*30)
    print("DEMO COMPLETADA EXITOSAMENTE")
    print("🎉 "*30 + "\n")


if __name__ == "__main__":
    main()
