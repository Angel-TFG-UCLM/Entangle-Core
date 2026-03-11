"""Check Microsoft repos and top stars"""
from pymongo import MongoClient
import re

c = MongoClient("mongodb://localhost:27017/")
db = c["quantum_github"]

# Microsoft repos
ms = list(db.repositories.find(
    {"name_with_owner": re.compile("microsoft", re.IGNORECASE)},
    {"name_with_owner": 1, "_id": 0}
).limit(10))
print(f"Microsoft repos: {ms}")

# Top repos by stars
top = list(db.repositories.find(
    {},
    {"name_with_owner": 1, "stargazer_count": 1, "_id": 0}
).sort("stargazer_count", -1).limit(15))
print("Top repos by stars:")
for r in top:
    print(f"  {r.get('name_with_owner', '?')}: {r.get('stargazer_count', '?')} stars")

# Check owner types
owner_org = db.repositories.count_documents({"owner.type": "Organization"})
owner_user = db.repositories.count_documents({"owner.type": "User"})
print(f"\nOwner types: {owner_org} orgs, {owner_user} users")
