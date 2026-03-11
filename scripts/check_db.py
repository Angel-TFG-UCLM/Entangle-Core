"""Check DB status"""
from pymongo import MongoClient

c = MongoClient("mongodb://localhost:27017/")
db = c["quantum_github"]

total = db.repositories.count_documents({})
enriched = db.repositories.count_documents({"enrichment_status": {"$exists": True}})
complete = db.repositories.count_documents({"enrichment_status.is_complete": True})

print(f"Total repos: {total}")
print(f"With enrichment_status: {enriched}")
print(f"Enrichment complete: {complete}")
print(f"Users: {db.users.count_documents({})}")
print(f"Orgs: {db.organizations.count_documents({})}")

# Check microsoft repo
ms = list(db.repositories.find(
    {"full_name": {"$regex": "microsoft", "$options": "i"}},
    {"full_name": 1, "stargazer_count": 1, "_id": 0}
).limit(10))
print(f"Microsoft repos: {ms}")

# Check sample enrichment
sample = db.repositories.find_one(
    {"enrichment_status": {"$exists": True}},
    {"full_name": 1, "enrichment_status": 1, "_id": 0}
)
print(f"Sample enriched repo: {sample}")
