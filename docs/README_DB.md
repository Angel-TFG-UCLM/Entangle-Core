# 📊 Documentación de Base de Datos - MongoDB Collections

Este documento describe las colecciones de MongoDB utilizadas en el sistema de ingesta de datos desde GitHub.

---

## 📋 Índice

1. [Colección: `repositories`](#colección-repositories)
2. [Colección: `organizations`](#colección-organizations)
3. [Colección: `users`](#colección-users)
4. [Colección: `relations`](#colección-relations)
5. [Índices Recomendados](#índices-recomendados)
6. [Relaciones entre Colecciones](#relaciones-entre-colecciones)
7. [Estrategia de Reingestas](#estrategia-de-reingestas)

---

## Colección: `repositories`

### 📖 Descripción
Almacena información completa de repositorios de GitHub, incluyendo métricas, colaboradores, commits recientes, issues, PRs, y más.

### 🔑 Clave Única
- **Campo primario**: `_id` (o `id` de GitHub)
- **Clave alternativa**: `nameWithOwner` (ej: `"Qiskit/qiskit"`)

### 📊 Campos Principales

| Campo | Tipo | Descripción | Ejemplo |
|-------|------|-------------|---------|
| `id` | String | ID único de GitHub | `"MDEwOlJlcG9zaXRvcnk..."` |
| `name` | String | Nombre del repositorio | `"qiskit"` |
| `nameWithOwner` | String | Nombre completo | `"Qiskit/qiskit"` |
| `description` | String? | Descripción del repo | `"Quantum SDK"` |
| `url` | String | URL del repositorio | `"https://github.com/Qiskit/qiskit"` |
| `owner` | Object | Propietario (User u Organization) | `{id, login, avatarUrl, type}` |
| `organizationId` | String? | ID de la org (si aplica) | `"MDEyOk9yZ2..."` |
| `createdAt` | DateTime | Fecha de creación | `"2017-03-05T12:00:00Z"` |
| `updatedAt` | DateTime | Última actualización | `"2025-10-14T10:30:00Z"` |
| `pushedAt` | DateTime | Último push | `"2025-10-14T09:15:00Z"` |
| `ingestedAt` | DateTime | Fecha de ingesta | `"2025-10-15T08:00:00Z"` |

### 🎯 Métricas de Popularidad

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `stargazerCount` | Integer | Número de estrellas |
| `forkCount` | Integer | Número de forks |
| `watchersCount` | Integer | Número de watchers |
| `subscribersCount` | Integer | Número de suscriptores |

### 📦 Métricas de Contenido

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `diskUsage` | Integer | Tamaño en KB |
| `commitsCount` | Integer | Total de commits |
| `branchesCount` | Integer | Total de branches |
| `tagsCount` | Integer | Total de tags |
| `releasesCount` | Integer | Total de releases |

### 🐛 Issues y Pull Requests

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `hasIssuesEnabled` | Boolean | Si tiene issues habilitados |
| `issuesCount` | Integer | Total de issues |
| `openIssuesCount` | Integer | Issues abiertos |
| `closedIssuesCount` | Integer | Issues cerrados |
| `pullRequestsCount` | Integer | Total de PRs |
| `openPullRequestsCount` | Integer | PRs abiertos |
| `closedPullRequestsCount` | Integer | PRs cerrados |
| `mergedPullRequestsCount` | Integer | PRs mergeados |

### 💻 Lenguajes y Topics

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `primaryLanguage` | Object? | Lenguaje principal `{name, color}` |
| `languages` | Array | Lista de lenguajes con tamaño |
| `repositoryTopics` | Array | Topics/etiquetas del repo |

### 👥 Colaboradores y Commits

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `collaborators` | Array | Lista de colaboradores |
| `collaboratorsCount` | Integer | Total de colaboradores |
| `recentCommits` | Array | Últimos 10 commits |
| `lastCommitDate` | DateTime? | Fecha del último commit |

### 🔒 Estados Booleanos

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `isPrivate` | Boolean | Si es privado |
| `isFork` | Boolean | Si es un fork |
| `isArchived` | Boolean | Si está archivado |
| `isTemplate` | Boolean | Si es template |
| `isMirror` | Boolean | Si es mirror |
| `isLocked` | Boolean | Si está bloqueado |

### 🔐 Seguridad y Dependencias

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `vulnerabilityAlertsCount` | Integer | Alertas de seguridad |
| `vulnerabilities` | Array | Lista de vulnerabilidades |
| `dependencyGraphManifests` | Array | Manifiestos de dependencias |

### 📝 README y Licencia

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `readmeText` | String? | Contenido del README |
| `hasReadme` | Boolean | Si tiene README |
| `licenseInfo` | Object? | Información de licencia `{key, name, spdxId}` |

### 🔀 Fork (si aplica)

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `parentId` | String? | ID del repo padre |
| `parentNameWithOwner` | String? | Nombre del repo padre |

---

### 📄 Ejemplo de Documento

```json
{
  "_id": "MDEwOlJlcG9zaXRvcnkxOTM4MzU5MzA=",
  "name": "qiskit",
  "nameWithOwner": "Qiskit/qiskit",
  "fullName": "Qiskit/qiskit",
  "description": "Qiskit is an open-source SDK for working with quantum computers",
  "url": "https://github.com/Qiskit/qiskit",
  "homepageUrl": "https://qiskit.org",
  "owner": {
    "id": "MDEyOk9yZ2FuaXphdGlvbjQ1ODUyOTA5",
    "login": "Qiskit",
    "avatarUrl": "https://avatars.githubusercontent.com/u/45852909",
    "url": "https://github.com/Qiskit",
    "type": "Organization"
  },
  "organizationId": "MDEyOk9yZ2FuaXphdGlvbjQ1ODUyOTA5",
  "createdAt": "2019-06-24T15:00:00Z",
  "updatedAt": "2025-10-14T10:30:00Z",
  "pushedAt": "2025-10-14T09:15:00Z",
  "ingestedAt": "2025-10-15T08:00:00Z",
  "primaryLanguage": {
    "name": "Python",
    "color": "#3572A5"
  },
  "languages": [
    {
      "node": {
        "name": "Python",
        "color": "#3572A5"
      },
      "size": 15234567
    },
    {
      "node": {
        "name": "Jupyter Notebook",
        "color": "#DA5B0B"
      },
      "size": 234567
    }
  ],
  "languagesCount": 2,
  "repositoryTopics": [
    {
      "topic": {
        "name": "quantum-computing"
      }
    },
    {
      "topic": {
        "name": "qiskit"
      }
    },
    {
      "topic": {
        "name": "python"
      }
    }
  ],
  "topicsCount": 3,
  "stargazerCount": 5234,
  "forkCount": 1234,
  "watchersCount": 234,
  "subscribersCount": 123,
  "diskUsage": 50234,
  "commitsCount": 3456,
  "branchesCount": 45,
  "tagsCount": 67,
  "releasesCount": 23,
  "hasIssuesEnabled": true,
  "issuesCount": 1234,
  "openIssuesCount": 89,
  "closedIssuesCount": 1145,
  "pullRequestsCount": 2345,
  "openPullRequestsCount": 34,
  "closedPullRequestsCount": 1234,
  "mergedPullRequestsCount": 1077,
  "hasProjectsEnabled": true,
  "hasWikiEnabled": true,
  "projectsCount": 5,
  "isPrivate": false,
  "isFork": false,
  "isArchived": false,
  "isTemplate": false,
  "isLocked": false,
  "isMirror": false,
  "isSecurityPolicyEnabled": true,
  "hasDiscussionsEnabled": true,
  "discussionsCount": 123,
  "licenseInfo": {
    "key": "apache-2.0",
    "name": "Apache License 2.0",
    "spdxId": "Apache-2.0",
    "url": "https://api.github.com/licenses/apache-2.0"
  },
  "defaultBranchRefName": "main",
  "collaborators": [
    {
      "id": "MDQ6VXNlcjEyMzQ1Njc=",
      "login": "user1",
      "name": "John Doe",
      "avatarUrl": "https://avatars.githubusercontent.com/u/1234567",
      "url": "https://github.com/user1"
    }
  ],
  "collaboratorsCount": 234,
  "recentCommits": [
    {
      "oid": "abc123def456",
      "message": "Fix quantum gate implementation",
      "committedDate": "2025-10-14T09:15:00Z",
      "authorLogin": "user1"
    }
  ],
  "lastCommitDate": "2025-10-14T09:15:00Z",
  "recentIssues": [
    {
      "id": "MDU6SXNzdWUxMjM0NTY=",
      "number": 1234,
      "title": "Bug in quantum circuit",
      "state": "OPEN",
      "createdAt": "2025-10-10T12:00:00Z",
      "closedAt": null
    }
  ],
  "recentPullRequests": [
    {
      "id": "MDExOlB1bGxSZXF1ZXN0MTIzNDU=",
      "number": 567,
      "title": "Add new quantum algorithm",
      "state": "MERGED",
      "createdAt": "2025-10-08T10:00:00Z",
      "mergedAt": "2025-10-12T14:30:00Z"
    }
  ],
  "latestRelease": {
    "id": "MDc6UmVsZWFzZTEyMzQ1",
    "tagName": "v1.2.3",
    "name": "Release 1.2.3",
    "createdAt": "2025-09-01T12:00:00Z",
    "publishedAt": "2025-09-01T15:00:00Z",
    "isPrerelease": false
  },
  "releases": [],
  "readmeText": "# Qiskit\n\nQiskit is an open-source SDK...",
  "hasReadme": true,
  "vulnerabilityAlertsCount": 0,
  "vulnerabilities": [],
  "dependencyGraphManifests": [
    {
      "filename": "requirements.txt",
      "dependenciesCount": 45
    }
  ],
  "networkCount": 1234,
  "customProperties": {}
}
```

---

## Colección: `organizations`

### 📖 Descripción
Almacena información completa de organizaciones de GitHub, incluyendo repositorios, miembros, equipos, y métricas.

### 🔑 Clave Única
- **Campo primario**: `_id` (o `id` de GitHub)
- **Clave alternativa**: `login` (ej: `"Qiskit"`)

### 📊 Campos Principales

| Campo | Tipo | Descripción | Ejemplo |
|-------|------|-------------|---------|
| `id` | String | ID único de GitHub | `"MDEyOk9yZ2FuaXphdGlvbjQ1ODUy..."` |
| `login` | String | Nombre de usuario/login | `"Qiskit"` |
| `name` | String? | Nombre completo | `"Qiskit Organization"` |
| `description` | String? | Descripción | `"Open-source quantum computing"` |
| `url` | String | URL de la organización | `"https://github.com/Qiskit"` |
| `websiteUrl` | String? | Sitio web | `"https://qiskit.org"` |
| `avatarUrl` | String? | Avatar | `"https://avatars.githubusercontent.com/..."` |
| `email` | String? | Email de contacto | `"contact@qiskit.org"` |
| `location` | String? | Ubicación | `"New York, USA"` |
| `twitterUsername` | String? | Usuario de Twitter | `"Qiskit"` |
| `createdAt` | DateTime | Fecha de creación | `"2018-05-01T00:00:00Z"` |
| `updatedAt` | DateTime | Última actualización | `"2025-10-14T10:00:00Z"` |
| `ingestedAt` | DateTime | Fecha de ingesta | `"2025-10-15T08:00:00Z"` |

### 📊 Métricas

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `repositoriesCount` | Integer | Total de repositorios |
| `publicReposCount` | Integer | Repositorios públicos |
| `privateReposCount` | Integer | Repositorios privados |
| `membersCount` | Integer | Total de miembros |
| `teamsCount` | Integer | Total de equipos |
| `projectsCount` | Integer | Total de proyectos |
| `packagesCount` | Integer | Total de paquetes |

### 🏢 Estados y Configuración

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `isVerified` | Boolean | Si está verificada |
| `hasOrganizationProjectsEnabled` | Boolean | Si tiene proyectos habilitados |
| `hasRepositoryProjectsEnabled` | Boolean | Si repos tienen proyectos |

### 💳 Plan

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `planName` | String? | Nombre del plan |
| `planSpace` | Integer? | Espacio disponible |
| `planPrivateRepos` | Integer? | Repos privados permitidos |

### 📦 Repositorios

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `repositories` | Array | Lista de repositorios |
| `pinnedRepositories` | Array | Repositorios fijados |

### 👥 Miembros y Equipos

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `members` | Array | Lista de miembros |
| `teams` | Array | Lista de equipos |

### 💰 Sponsorship

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `hasSponsorshipsListing` | Boolean | Si tiene listing de sponsors |
| `sponsorsCount` | Integer | Número de sponsors |
| `sponsorsListing` | Object? | Info del listing |

---

### 📄 Ejemplo de Documento

```json
{
  "_id": "MDEyOk9yZ2FuaXphdGlvbjQ1ODUyOTA5",
  "login": "Qiskit",
  "name": "Qiskit",
  "description": "Qiskit is an open-source SDK for working with quantum computers at the level of circuits, algorithms, and application modules",
  "url": "https://github.com/Qiskit",
  "websiteUrl": "https://qiskit.org",
  "avatarUrl": "https://avatars.githubusercontent.com/u/45852909",
  "email": "hello@qiskit.org",
  "location": "New York, NY",
  "twitterUsername": "Qiskit",
  "createdAt": "2018-12-07T18:30:00Z",
  "updatedAt": "2025-10-14T10:00:00Z",
  "ingestedAt": "2025-10-15T08:00:00Z",
  "repositoriesCount": 156,
  "publicReposCount": 150,
  "privateReposCount": 6,
  "membersCount": 234,
  "teamsCount": 12,
  "projectsCount": 5,
  "packagesCount": 8,
  "isVerified": true,
  "hasOrganizationProjectsEnabled": true,
  "hasRepositoryProjectsEnabled": true,
  "planName": "enterprise",
  "planSpace": 1000000,
  "planPrivateRepos": 999,
  "repositories": [
    {
      "id": "MDEwOlJlcG9zaXRvcnkxOTM4MzU5MzA=",
      "name": "qiskit",
      "nameWithOwner": "Qiskit/qiskit",
      "description": "Qiskit SDK",
      "url": "https://github.com/Qiskit/qiskit",
      "stargazerCount": 5234,
      "forkCount": 1234,
      "watchersCount": 234,
      "isPrivate": false,
      "isFork": false,
      "isArchived": false,
      "primaryLanguage": "Python"
    }
  ],
  "pinnedRepositories": [
    {
      "id": "MDEwOlJlcG9zaXRvcnkxOTM4MzU5MzA=",
      "name": "qiskit",
      "nameWithOwner": "Qiskit/qiskit",
      "url": "https://github.com/Qiskit/qiskit"
    }
  ],
  "members": [
    {
      "id": "MDQ6VXNlcjEyMzQ1Njc=",
      "login": "user1",
      "name": "John Doe",
      "email": "john@example.com",
      "avatarUrl": "https://avatars.githubusercontent.com/u/1234567",
      "url": "https://github.com/user1",
      "bio": "Quantum software developer",
      "company": "Qiskit",
      "location": "New York",
      "createdAt": "2015-03-15T12:00:00Z",
      "followersCount": 234
    }
  ],
  "teams": [
    {
      "id": "MDQ6VGVhbTEyMzQ1",
      "name": "Core Developers",
      "slug": "core-developers",
      "description": "Main development team",
      "privacy": "SECRET",
      "createdAt": "2019-01-15T10:00:00Z",
      "updatedAt": "2025-10-01T12:00:00Z",
      "membersCount": 15,
      "repositoriesCount": 5
    }
  ],
  "hasSponsorshipsListing": true,
  "sponsorsCount": 45,
  "sponsorsListing": {
    "id": "MDM6U3BvbnNvcnNMaXN0aW5nMTIzNDU=",
    "name": "Support Qiskit",
    "fullDescription": "Help us develop quantum computing tools",
    "isPublic": true
  },
  "customProperties": {}
}
```

---

## Colección: `users`

### 📖 Descripción
Almacena información completa de usuarios de GitHub, incluyendo repositorios, organizaciones, contribuciones, y métricas sociales.

### 🔑 Clave Única
- **Campo primario**: `_id` (o `id` de GitHub)
- **Clave alternativa**: `login` (ej: `"torvalds"`)

### 📊 Campos Principales

| Campo | Tipo | Descripción | Ejemplo |
|-------|------|-------------|---------|
| `id` | String | ID único de GitHub | `"MDQ6VXNlcjEyMzQ1Njc="` |
| `login` | String | Nombre de usuario | `"torvalds"` |
| `name` | String? | Nombre completo | `"Linus Torvalds"` |
| `email` | String? | Email | `"torvalds@linux.org"` |
| `bio` | String? | Biografía | `"Creator of Linux"` |
| `company` | String? | Empresa | `"Linux Foundation"` |
| `location` | String? | Ubicación | `"Portland, OR"` |
| `pronouns` | String? | Pronombres | `"he/him"` |
| `avatarUrl` | String? | Avatar | `"https://avatars.githubusercontent.com/..."` |
| `url` | String | URL del perfil | `"https://github.com/torvalds"` |
| `websiteUrl` | String? | Sitio web personal | `"https://example.com"` |
| `twitterUsername` | String? | Usuario de Twitter | `"Linus__Torvalds"` |
| `createdAt` | DateTime | Fecha de creación | `"2011-09-03T15:26:22Z"` |
| `updatedAt` | DateTime | Última actualización | `"2025-10-14T10:00:00Z"` |
| `ingestedAt` | DateTime | Fecha de ingesta | `"2025-10-15T08:00:00Z"` |

### 📊 Métricas Sociales

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `followersCount` | Integer | Seguidores |
| `followingCount` | Integer | Siguiendo |

### 📦 Repositorios

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `repositories` | Array | Lista de repositorios |
| `repositoriesCount` | Integer | Total de repositorios |
| `publicReposCount` | Integer | Repositorios públicos |
| `privateReposCount` | Integer | Repositorios privados |
| `ownedPrivateReposCount` | Integer | Repos privados propios |
| `pinnedRepositories` | Array | Repositorios fijados |
| `starredRepositories` | Array | Repositorios con estrella |
| `starredRepositoriesCount` | Integer | Total starred |

### 🏢 Organizaciones

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `organizations` | Array | Lista de organizaciones |
| `organizationsCount` | Integer | Total de organizaciones |

### 💻 Contribuciones

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `contributions` | Object? | Colección de contribuciones |
| `contributionsByRepository` | Array | Contribuciones por repo |
| `issuesCount` | Integer | Total de issues |
| `pullRequestsCount` | Integer | Total de PRs |

### 📝 Gists y Proyectos

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `gists` | Array | Lista de gists |
| `gistsCount` | Integer | Total de gists |
| `publicGistsCount` | Integer | Gists públicos |
| `projectsCount` | Integer | Total de proyectos |
| `packagesCount` | Integer | Total de paquetes |

### 💰 Sponsorship

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `hasSponsorshipsListing` | Boolean | Si tiene listing |
| `sponsorsCount` | Integer | Sponsors recibidos |
| `sponsoringCount` | Integer | Patrocina a |
| `monthlyEstimatedSponsorsIncome` | Integer? | Ingreso estimado |

### 🏆 Estados Especiales

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `isHireable` | Boolean | Disponible para contratar |
| `isBountyHunter` | Boolean | Cazador de recompensas |
| `isCampusExpert` | Boolean | Experto campus |
| `isDeveloperProgramMember` | Boolean | Miembro programa dev |
| `isEmployee` | Boolean | Empleado de GitHub |
| `isGitHubStar` | Boolean | GitHub Star |
| `isSiteAdmin` | Boolean | Admin del sitio |

---

### 📄 Ejemplo de Documento

```json
{
  "_id": "MDQ6VXNlcjEwMzI=" ,
  "login": "torvalds",
  "name": "Linus Torvalds",
  "email": "torvalds@linux-foundation.org",
  "bio": "Creator of Linux and Git",
  "company": "@linux",
  "location": "Portland, OR",
  "pronouns": "he/him",
  "avatarUrl": "https://avatars.githubusercontent.com/u/1024767",
  "url": "https://github.com/torvalds",
  "websiteUrl": null,
  "twitterUsername": "Linus__Torvalds",
  "createdAt": "2011-09-03T15:26:22Z",
  "updatedAt": "2025-10-14T10:00:00Z",
  "ingestedAt": "2025-10-15T08:00:00Z",
  "followersCount": 234567,
  "followingCount": 0,
  "repositories": [
    {
      "id": "MDEwOlJlcG9zaXRvcnkyMzI1Mjk4",
      "name": "linux",
      "nameWithOwner": "torvalds/linux",
      "description": "Linux kernel source tree",
      "url": "https://github.com/torvalds/linux",
      "stargazerCount": 187654,
      "forkCount": 54321,
      "watchersCount": 9876,
      "isPrivate": false,
      "isFork": false,
      "isArchived": false,
      "primaryLanguage": "C"
    }
  ],
  "repositoriesCount": 6,
  "publicReposCount": 6,
  "privateReposCount": 0,
  "ownedPrivateReposCount": 0,
  "pinnedRepositories": [
    {
      "id": "MDEwOlJlcG9zaXRvcnkyMzI1Mjk4",
      "name": "linux",
      "nameWithOwner": "torvalds/linux",
      "url": "https://github.com/torvalds/linux"
    }
  ],
  "starredRepositories": [],
  "starredRepositoriesCount": 0,
  "organizations": [],
  "organizationsCount": 0,
  "contributions": {
    "totalCommitContributions": 34567,
    "totalIssueContributions": 123,
    "totalPullRequestContributions": 45,
    "totalPullRequestReviewContributions": 234,
    "totalRepositoryContributions": 6,
    "restrictedContributionsCount": 0
  },
  "contributionsByRepository": [
    {
      "repository_name": "torvalds/linux",
      "contributions_count": 28000
    }
  ],
  "issuesCount": 123,
  "pullRequestsCount": 45,
  "gists": [],
  "gistsCount": 0,
  "publicGistsCount": 0,
  "projectsCount": 0,
  "packagesCount": 0,
  "hasSponsorshipsListing": false,
  "sponsorsCount": 0,
  "sponsoringCount": 0,
  "isHireable": false,
  "isBountyHunter": false,
  "isCampusExpert": false,
  "isDeveloperProgramMember": false,
  "isEmployee": false,
  "isGitHubStar": false,
  "isSiteAdmin": false,
  "socialAccounts": [
    {
      "provider": "twitter",
      "displayName": "@Linus__Torvalds",
      "url": "https://twitter.com/Linus__Torvalds"
    }
  ],
  "status": {
    "emoji": "💻",
    "message": "Coding",
    "expires_at": null
  },
  "customProperties": {}
}
```

---

## Colección: `relations`

### 📖 Descripción
Modela las relaciones entre entidades (Users, Organizations, Repositories) para análisis de grafos y patrones de colaboración.

### 🔑 Clave Única
- **Campo primario**: `_id` (generado por MongoDB)
- **Índice compuesto**: `{sourceId, targetId, relationType}` (único)

### 📊 Campos Principales

| Campo | Tipo | Descripción | Ejemplo |
|-------|------|-------------|---------|
| `relationType` | Enum | Tipo de relación | `"contributes"`, `"member_of"`, `"follows"` |
| `sourceId` | String | ID de la entidad origen | `"MDQ6VXNlcjEyMzQ1Njc="` |
| `sourceType` | String | Tipo de origen | `"User"`, `"Organization"`, `"Repository"` |
| `sourceLogin` | String? | Login (si es User/Org) | `"torvalds"` |
| `sourceName` | String? | Nombre (si es Repo) | `"linux"` |
| `targetId` | String | ID de la entidad destino | `"MDEwOlJlcG9zaXRvcnkyMzI1Mjk4"` |
| `targetType` | String | Tipo de destino | `"User"`, `"Organization"`, `"Repository"` |
| `targetLogin` | String? | Login (si es User/Org) | `"Qiskit"` |
| `targetName` | String? | Nombre (si es Repo) | `"qiskit"` |

### 📅 Fechas

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `startedAt` | DateTime? | Inicio de la relación |
| `endedAt` | DateTime? | Fin (si aplica) |
| `lastActivityAt` | DateTime? | Última actividad |
| `ingestedAt` | DateTime | Fecha de ingesta |
| `updatedAt` | DateTime | Última actualización |

### 📊 Métricas

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `contributionMetrics` | Object? | Métricas detalladas |
| `totalContributions` | Integer | Total de contribuciones |
| `weight` | Float | Peso de la relación (0-1+) |
| `strength` | String? | Fuerza: "weak", "medium", "strong" |

### 🎭 Roles y Permisos

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `role` | String? | Rol: "member", "admin", "owner" |
| `permission` | String? | Permiso: "read", "write", "admin" |

### 🔢 Estados

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `isActive` | Boolean | Si está activa |
| `isDirect` | Boolean | Si es directa |
| `isVerified` | Boolean | Si está verificada |
| `isPublic` | Boolean | Si es pública |

---

### 🔗 Tipos de Relaciones

#### User ↔ Repository
- `owns` - Usuario es propietario
- `contributes` - Usuario contribuye
- `stars` - Usuario da estrella
- `watches` - Usuario observa
- `forks` - Usuario hace fork
- `opened_issue` - Usuario abrió issue
- `opened_pr` - Usuario abrió PR
- `merged_pr` - Usuario mergeó PR
- `committed` - Usuario hizo commit

#### User ↔ Organization
- `member_of` - Usuario es miembro
- `owner_of_org` - Usuario es owner

#### User ↔ User
- `follows` - Usuario sigue a otro
- `sponsors` - Usuario patrocina a otro

#### Organization ↔ Repository
- `org_owns` - Organización es propietaria

#### Repository ↔ Repository
- `fork_of` - Repo es fork de otro
- `depends_on` - Repo depende de otro

---

### 📄 Ejemplo de Documento (Contribución)

```json
{
  "_id": "6721a3b4c5d6e7f8a9b0c1d2",
  "relationType": "contributes",
  "sourceId": "MDQ6VXNlcjEyMzQ1Njc=",
  "sourceType": "User",
  "sourceLogin": "johndoe",
  "targetId": "MDEwOlJlcG9zaXRvcnkxOTM4MzU5MzA=",
  "targetType": "Repository",
  "targetName": "Qiskit/qiskit",
  "startedAt": "2023-01-15T10:00:00Z",
  "endedAt": null,
  "lastActivityAt": "2025-10-14T09:15:00Z",
  "isActive": true,
  "ingestedAt": "2025-10-15T08:00:00Z",
  "updatedAt": "2025-10-15T08:00:00Z",
  "contributionMetrics": {
    "commitsCount": 145,
    "additions": 12345,
    "deletions": 3456,
    "issuesOpened": 12,
    "issuesClosed": 8,
    "issuesCommented": 45,
    "pullRequestsOpened": 23,
    "pullRequestsMerged": 18,
    "pullRequestsReviewed": 34,
    "codeReviewsCount": 34
  },
  "totalContributions": 180,
  "weight": 0.85,
  "strength": "strong",
  "role": null,
  "permission": "write",
  "isDirect": true,
  "isVerified": true,
  "isPublic": true,
  "activityTimeline": [
    {
      "date": "2025-10-01T00:00:00Z",
      "count": 5
    },
    {
      "date": "2025-10-02T00:00:00Z",
      "count": 3
    }
  ],
  "metadata": {
    "first_commit_date": "2023-01-15T10:00:00Z",
    "last_commit_date": "2025-10-14T09:15:00Z",
    "primary_language": "Python"
  },
  "tags": ["active-contributor", "core-team"],
  "customProperties": {}
}
```

### 📄 Ejemplo de Documento (Membresía)

```json
{
  "_id": "6721a3b4c5d6e7f8a9b0c1d3",
  "relationType": "member_of",
  "sourceId": "MDQ6VXNlcjEyMzQ1Njc=",
  "sourceType": "User",
  "sourceLogin": "johndoe",
  "targetId": "MDEyOk9yZ2FuaXphdGlvbjQ1ODUyOTA5",
  "targetType": "Organization",
  "targetLogin": "Qiskit",
  "startedAt": "2022-06-01T00:00:00Z",
  "endedAt": null,
  "lastActivityAt": "2025-10-14T10:00:00Z",
  "isActive": true,
  "ingestedAt": "2025-10-15T08:00:00Z",
  "updatedAt": "2025-10-15T08:00:00Z",
  "role": "member",
  "permission": "write",
  "weight": 1.0,
  "strength": "strong",
  "isDirect": true,
  "isVerified": true,
  "isPublic": true,
  "metadata": {
    "teams": ["core-developers", "documentation"]
  },
  "tags": ["verified-member"],
  "customProperties": {}
}
```

---

## Índices Recomendados

### 📊 `repositories`

```javascript
// Índice único por ID
db.repositories.createIndex({ "_id": 1 }, { unique: true })

// Índice único por nameWithOwner
db.repositories.createIndex({ "nameWithOwner": 1 }, { unique: true })

// Índice por organización
db.repositories.createIndex({ "organizationId": 1 })

// Índice por owner.login
db.repositories.createIndex({ "owner.login": 1 })

// Índice por fechas (para reingestas)
db.repositories.createIndex({ "updatedAt": -1 })
db.repositories.createIndex({ "ingestedAt": -1 })

// Índice por estados
db.repositories.createIndex({ "isArchived": 1, "isPrivate": 1 })

// Índice por métricas (para búsquedas)
db.repositories.createIndex({ "stargazerCount": -1 })
db.repositories.createIndex({ "forkCount": -1 })

// Índice por lenguaje
db.repositories.createIndex({ "primaryLanguage.name": 1 })

// Índice por topics
db.repositories.createIndex({ "repositoryTopics.topic.name": 1 })

// Índice texto para búsquedas
db.repositories.createIndex(
  { 
    "name": "text", 
    "description": "text", 
    "readmeText": "text" 
  },
  { 
    name: "text_search_index",
    weights: { name: 10, description: 5, readmeText: 1 }
  }
)
```

### 🏢 `organizations`

```javascript
// Índice único por ID
db.organizations.createIndex({ "_id": 1 }, { unique: true })

// Índice único por login
db.organizations.createIndex({ "login": 1 }, { unique: true })

// Índice por fechas
db.organizations.createIndex({ "updatedAt": -1 })
db.organizations.createIndex({ "ingestedAt": -1 })

// Índice por verificación
db.organizations.createIndex({ "isVerified": 1 })

// Índice texto
db.organizations.createIndex(
  { "name": "text", "description": "text" },
  { name: "org_text_search" }
)
```

### 👤 `users`

```javascript
// Índice único por ID
db.users.createIndex({ "_id": 1 }, { unique: true })

// Índice único por login
db.users.createIndex({ "login": 1 }, { unique: true })

// Índice por fechas
db.users.createIndex({ "updatedAt": -1 })
db.users.createIndex({ "ingestedAt": -1 })

// Índice por métricas
db.users.createIndex({ "followersCount": -1 })
db.users.createIndex({ "repositoriesCount": -1 })

// Índice por empresa y ubicación
db.users.createIndex({ "company": 1 })
db.users.createIndex({ "location": 1 })

// Índice texto
db.users.createIndex(
  { "name": "text", "bio": "text", "company": "text" },
  { name: "user_text_search" }
)
```

### 🔗 `relations`

```javascript
// Índice único compuesto
db.relations.createIndex(
  { "sourceId": 1, "targetId": 1, "relationType": 1 },
  { unique: true, name: "unique_relation" }
)

// Índices para búsquedas de grafos
db.relations.createIndex({ "sourceId": 1, "relationType": 1 })
db.relations.createIndex({ "targetId": 1, "relationType": 1 })
db.relations.createIndex({ "sourceType": 1, "targetType": 1 })

// Índice por actividad
db.relations.createIndex({ "isActive": 1, "lastActivityAt": -1 })

// Índice por peso y fuerza (para análisis de grafos)
db.relations.createIndex({ "weight": -1 })
db.relations.createIndex({ "strength": 1 })

// Índice por fechas
db.relations.createIndex({ "ingestedAt": -1 })
db.relations.createIndex({ "updatedAt": -1 })

// Índice para contribuciones
db.relations.createIndex({ 
  "relationType": 1, 
  "totalContributions": -1 
})
```

---

## Relaciones entre Colecciones

```
┌──────────────────┐
│   organizations  │
│                  │
│  • id (PK)       │
│  • login (UK)    │
└────────┬─────────┘
         │
         │ organizationId (FK)
         │
         ▼
┌──────────────────┐         ┌──────────────────┐
│   repositories   │◄────────┤    relations     │
│                  │         │                  │
│  • id (PK)       │         │  • sourceId (FK) │
│  • nameWithOwner │         │  • targetId (FK) │
│  • owner.id (FK) │         │  • relationType  │
│  • parentId (FK) │         └──────────────────┘
└────────┬─────────┘                 ▲
         │                           │
         │ owner.id (FK)             │
         │                           │
         ▼                           │
┌──────────────────┐                 │
│      users       │─────────────────┘
│                  │
│  • id (PK)       │
│  • login (UK)    │
└──────────────────┘
```

### Ejemplos de Consultas

#### 1. Obtener todos los repos de una organización
```javascript
db.repositories.find({ "organizationId": "MDEyOk9yZ2FuaXphdGlvbjQ1ODUyOTA5" })
```

#### 2. Obtener todos los contribuidores de un repo
```javascript
db.relations.find({
  "targetId": "MDEwOlJlcG9zaXRvcnkxOTM4MzU5MzA=",
  "targetType": "Repository",
  "relationType": "contributes"
})
```

#### 3. Obtener organizaciones de un usuario
```javascript
db.relations.find({
  "sourceId": "MDQ6VXNlcjEyMzQ1Njc=",
  "sourceType": "User",
  "relationType": { $in: ["member_of", "owner_of_org"] }
})
```

#### 4. Repos más populares por estrellas
```javascript
db.repositories.find({ "isArchived": false })
  .sort({ "stargazerCount": -1 })
  .limit(10)
```

#### 5. Usuarios con más contribuciones a un repo
```javascript
db.relations.aggregate([
  {
    $match: {
      "targetId": "MDEwOlJlcG9zaXRvcnkxOTM4MzU5MzA=",
      "relationType": "contributes"
    }
  },
  {
    $sort: { "totalContributions": -1 }
  },
  {
    $limit: 10
  }
])
```

---

## Estrategia de Reingestas

### 🔄 Reingestas Incrementales

#### Identificación de Cambios
Usa `updatedAt` para detectar cambios:

```javascript
// Repos actualizados desde última ingesta
db.repositories.find({
  "updatedAt": { $gte: ISODate("2025-10-14T00:00:00Z") }
})
```

#### Actualización vs Inserción
```python
# Usar upsert en MongoDB
repo_dict = repository.to_mongo_dict()
db.repositories.update_one(
    {"_id": repo_dict["_id"]},
    {"$set": repo_dict},
    upsert=True
)
```

### 📅 Campos de Control

Cada modelo incluye:
- `ingestedAt`: Cuándo se ingirió por primera vez
- `updatedAt`: Última actualización del recurso en GitHub

### 🔍 Detección de Eliminaciones

```javascript
// Repos no actualizados en 6 meses (posible eliminación)
db.repositories.find({
  "updatedAt": { $lt: ISODate("2025-04-15T00:00:00Z") }
})
```

### ⚡ Estrategia Recomendada

1. **Ingesta Inicial**: Todos los repos/users/orgs
2. **Ingesta Incremental Diaria**: Solo `updatedAt` > última ingesta
3. **Ingesta Completa Semanal**: Verificar eliminaciones y cambios mayores
4. **Actualización de Relaciones**: Regenerar después de cada ingesta

---

## 📝 Notas Finales

### ✅ Ventajas del Diseño

1. **Completo**: Captura TODOS los campos de GitHub GraphQL
2. **Flexible**: Campos opcionales y personalizables
3. **Escalable**: Preparado para millones de documentos
4. **Eficiente**: Índices optimizados para consultas comunes
5. **Grafo-ready**: Modelo de relaciones para análisis de redes

### 🔐 Consideraciones de Seguridad

- Campos `email` pueden ser `null` (privacidad)
- Repos privados: `isPrivate=true`
- Permisos en relaciones: campo `permission`

### 📊 Tamaño Estimado

- **Repository**: ~15-50 KB por documento (con README)
- **Organization**: ~10-30 KB por documento
- **User**: ~8-25 KB por documento
- **Relation**: ~1-3 KB por documento

### 🚀 Optimizaciones Futuras

1. Sharding por `organizationId` o `owner.login`
2. Archivado de repos inactivos (>1 año sin updates)
3. Compresión de campos grandes (README)
4. Caché de métricas agregadas

---

**Última actualización**: 15 de octubre de 2025  
**Versión**: 1.0.0  
**Mantenido por**: TFG - Quantum Software Analysis Project
