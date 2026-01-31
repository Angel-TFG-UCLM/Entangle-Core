"""
Definición de queries GraphQL para GitHub.
"""


# Query para obtener información de una organización
ORGANIZATION_QUERY = """
query GetOrganization($login: String!) {
    organization(login: $login) {
        id
        login
        name
        description
        url
        avatarUrl
        createdAt
        location
        email
        websiteUrl
        twitterUsername
        repositories(first: 100) {
            totalCount
            nodes {
                id
                name
                description
                url
                createdAt
                updatedAt
                pushedAt
                primaryLanguage {
                    name
                    color
                }
                stargazerCount
                forkCount
                isPrivate
                isFork
                isArchived
            }
            pageInfo {
                hasNextPage
                endCursor
            }
        }
        membersWithRole(first: 100) {
            totalCount
            nodes {
                id
                login
                name
                email
                avatarUrl
                bio
                company
                location
                createdAt
            }
            pageInfo {
                hasNextPage
                endCursor
            }
        }
    }
}
"""


# Query para obtener información de un repositorio
REPOSITORY_QUERY = """
query GetRepository($owner: String!, $name: String!) {
    repository(owner: $owner, name: $name) {
        id
        name
        nameWithOwner
        description
        url
        createdAt
        updatedAt
        pushedAt
        homepageUrl
        primaryLanguage {
            name
            color
        }
        languages(first: 10) {
            edges {
                node {
                    name
                    color
                }
                size
            }
        }
        stargazerCount
        forkCount
        watchers {
            totalCount
        }
        issues {
            totalCount
        }
        pullRequests {
            totalCount
        }
        isPrivate
        isFork
        isArchived
        isTemplate
        licenseInfo {
            name
            spdxId
        }
        defaultBranchRef {
            name
            target {
                ... on Commit {
                    history {
                        totalCount
                    }
                }
            }
        }
        collaborators(first: 100) {
            totalCount
            nodes {
                id
                login
                name
                avatarUrl
            }
        }
    }
}
"""


# Query para obtener información de un usuario
USER_QUERY = """
query GetUser($login: String!) {
    user(login: $login) {
        id
        login
        name
        email
        bio
        company
        location
        avatarUrl
        websiteUrl
        twitterUsername
        createdAt
        updatedAt
        followers {
            totalCount
        }
        following {
            totalCount
        }
        repositories(first: 100, ownerAffiliations: OWNER) {
            totalCount
            nodes {
                id
                name
                description
                url
                stargazerCount
                forkCount
                primaryLanguage {
                    name
                }
                createdAt
                updatedAt
            }
            pageInfo {
                hasNextPage
                endCursor
            }
        }
        organizations(first: 100) {
            totalCount
            nodes {
                id
                login
                name
                avatarUrl
            }
        }
        contributionsCollection {
            totalCommitContributions
            totalIssueContributions
            totalPullRequestContributions
            totalPullRequestReviewContributions
        }
    }
}
"""


# Query para búsqueda de repositorios
SEARCH_REPOSITORIES_QUERY = """
query SearchRepositories($query: String!, $first: Int!, $after: String) {
    search(query: $query, type: REPOSITORY, first: $first, after: $after) {
        repositoryCount
        edges {
            node {
                ... on Repository {
                    id
                    name
                    nameWithOwner
                    description
                    url
                    stargazerCount
                    forkCount
                    createdAt
                    updatedAt
                    primaryLanguage {
                        name
                        color
                    }
                    owner {
                        login
                        avatarUrl
                    }
                }
            }
        }
        pageInfo {
            hasNextPage
            endCursor
        }
    }
}
"""


# Query para el rate limit
RATE_LIMIT_QUERY = """
query {
    rateLimit {
        limit
        remaining
        resetAt
        used
    }
}
"""
