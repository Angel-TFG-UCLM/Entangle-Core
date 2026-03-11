from dotenv import load_dotenv; load_dotenv()
import requests, os
token = os.getenv('GITHUB_TOKEN')

# Test con Fine-grained token header (mismo formato)
# El truco: usar Accept header sin SAML scope
headers_no_auth = {}
headers_auth = {'Authorization': f'token {token}'}

print("=== Test: repos SAML-protected ===")
repos = ['microsoft/Quantum', 'microsoft/QuantumKatas', 'microsoft/QuantumLibraries']

print("\nSin auth (anonimo):")
for repo in repos:
    r = requests.get(f'https://api.github.com/repos/{repo}', headers=headers_no_auth)
    print(f"  {r.status_code}: {repo}")

print("\nCon PAT classic:")
for repo in repos:
    r = requests.get(f'https://api.github.com/repos/{repo}', headers=headers_auth)
    print(f"  {r.status_code}: {repo}")

# GraphQL NO funciona sin auth, asi que probar con header especial
print("\nGraphQL sin auth:")
query = '{"query":"query { repository(owner:\\"microsoft\\", name:\\"Quantum\\") { nameWithOwner stargazerCount } }"}'
r = requests.post('https://api.github.com/graphql', data=query, headers={'Content-Type': 'application/json'})
print(f"  Status: {r.status_code} (GraphQL requiere auth)")

print("\nGraphQL con PAT classic:")
r = requests.post('https://api.github.com/graphql', data=query, headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
d = r.json()
if 'errors' in d:
    print(f"  ERROR: {d['errors'][0].get('type','')} - {d['errors'][0].get('message','')[:100]}")
if d.get('data', {}).get('repository'):
    print(f"  OK: {d['data']['repository']['nameWithOwner']}")

# Verificar rate limit
r = requests.get('https://api.github.com/rate_limit', headers=headers_auth)
rl = r.json()['resources']
print(f"\nRate limit: core={rl['core']['remaining']}/{rl['core']['limit']}, graphql={rl['graphql']['remaining']}/{rl['graphql']['limit']}")
