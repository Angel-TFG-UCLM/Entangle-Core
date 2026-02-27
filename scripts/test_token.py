"""Test rápido del fine-grained PAT"""
import requests

token = "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"
headers_rest = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
headers_gql = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Test 1: GraphQL repo query
query = '{ repository(owner: "microsoft", name: "Quantum") { name stargazerCount } }'
r = requests.post("https://api.github.com/graphql", json={"query": query}, headers=headers_gql)
print(f"1. GraphQL repo query: {r.status_code} - {r.text[:200]}")

# Test 2: REST readme
r = requests.get("https://api.github.com/repos/microsoft/Quantum/readme", headers=headers_rest)
print(f"2. REST readme: {r.status_code}")

# Test 3: REST releases
r = requests.get("https://api.github.com/repos/microsoft/Quantum/releases?per_page=5", headers=headers_rest)
print(f"3. REST releases: {r.status_code}")

# Test 4: REST contributors
r = requests.get("https://api.github.com/repos/microsoft/Quantum/contributors?per_page=5", headers=headers_rest)
print(f"4. REST contributors: {r.status_code}")

# Test 5: Rate limit
r = requests.get("https://api.github.com/rate_limit", headers=headers_rest)
rl = r.json()["resources"]
print(f"5. REST rate limit: {rl['core']['remaining']}/{rl['core']['limit']}")
print(f"   GraphQL rate limit: {rl['graphql']['remaining']}/{rl['graphql']['limit']}")
