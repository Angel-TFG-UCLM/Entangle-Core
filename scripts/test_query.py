"""Test exact combined query that enrichment uses"""
import requests

token = "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"
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Same super-query the enrichment uses
query = """
query GetRepoEnrichmentAll($owner: String!, $name: String!) {
    repository(owner: $owner, name: $name) {
        defaultBranchRef {
            target {
                ... on Commit {
                    history(first: 10) {
                        nodes {
                            oid
                            message
                            committedDate
                            author { user { login } }
                        }
                    }
                }
            }
        }
        issues(first: 10, orderBy: {field: CREATED_AT, direction: DESC}) {
            nodes { id number title state createdAt closedAt }
        }
        pullRequests(first: 10, orderBy: {field: CREATED_AT, direction: DESC}) {
            nodes { id number title state createdAt closedAt mergedAt }
        }
        codeOfConduct { name url }
        fundingLinks { platform url }
        discussionCategories(first: 1) { totalCount }
        hasProjectsEnabled
        vulnerabilityAlerts(first: 1) { totalCount }
        isSecurityPolicyEnabled
        mergedPullRequests: pullRequests(states: MERGED) { totalCount }
    }
}
"""

# Test with qutech/qupulse (was failing with 401)
variables = {"owner": "qutech", "name": "qupulse"}
r = requests.post("https://api.github.com/graphql", json={"query": query, "variables": variables}, headers=headers)
print(f"qutech/qupulse: {r.status_code}")
if r.status_code != 200:
    print(f"  Response: {r.text[:500]}")
else:
    data = r.json()
    if "errors" in data:
        print(f"  GraphQL errors: {data['errors']}")
    else:
        print(f"  OK - has data: {bool(data.get('data', {}).get('repository'))}")

# Test without vulnerabilityAlerts
query2 = """
query GetRepoBasic($owner: String!, $name: String!) {
    repository(owner: $owner, name: $name) {
        name stargazerCount
        defaultBranchRef { target { ... on Commit { history(first: 1) { nodes { oid message committedDate } } } } }
    }
}
"""
r2 = requests.post("https://api.github.com/graphql", json={"query": query2, "variables": variables}, headers=headers)
print(f"\nqutech/qupulse (basic): {r2.status_code}")
if r2.status_code == 200:
    print(f"  Data: {r2.json().get('data', {}).get('repository', {}).get('name')}")
