from dotenv import load_dotenv; load_dotenv()
import requests, os
token = os.getenv('GITHUB_TOKEN')
headers = {'Authorization': f'token {token}'}

r = requests.get('https://api.github.com/user', headers=headers)
print(f"Token status: {r.status_code}")
if r.status_code == 200:
    print(f"User: {r.json()['login']}")

for repo in ['microsoft/Quantum', 'microsoft/QuantumKatas', 'microsoft/QuantumLibraries', 'microsoft/iqsharp']:
    r = requests.get(f'https://api.github.com/repos/{repo}', headers=headers)
    if r.status_code == 200:
        d = r.json()
        print(f"OK: {d['full_name']} stars={d['stargazers_count']} archived={d['archived']}")
    else:
        msg = r.json().get('message', '')[:80]
        print(f"{r.status_code}: {repo} - {msg}")

# GraphQL test
headers2 = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
query = '''query {
  repository(owner: "microsoft", name: "Quantum") {
    nameWithOwner
    stargazerCount
    isArchived
  }
}'''
r2 = requests.post('https://api.github.com/graphql', json={'query': query}, headers=headers2)
d2 = r2.json()
if 'errors' in d2:
    print(f"GraphQL ERROR: {d2['errors'][0].get('type','')} - {d2['errors'][0].get('message','')[:100]}")
elif d2.get('data', {}).get('repository'):
    repo = d2['data']['repository']
    print(f"GraphQL OK: {repo['nameWithOwner']} stars={repo['stargazerCount']}")
