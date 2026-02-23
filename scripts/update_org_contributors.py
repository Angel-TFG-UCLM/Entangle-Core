"""Quick script to populate total_unique_contributors for all orgs."""
from pymongo import MongoClient

c = MongoClient("mongodb://localhost:27017/")
db = c["quantum_github"]

for org in db.organizations.find({}, {"login": 1}):
    login = org["login"]
    repos = list(db.repositories.find({"owner.login": login}, {"collaborators": 1}))
    users = set()
    for r in repos:
        for col in (r.get("collaborators") or []):
            l = col.get("login", "")
            if l:
                users.add(l)
    db.organizations.update_one(
        {"_id": org["_id"]},
        {"$set": {"total_unique_contributors": len(users)}}
    )
    print(f"{login}: {len(users)} contributors")

print("Done!")
