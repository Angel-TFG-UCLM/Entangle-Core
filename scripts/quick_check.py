"""Quick enrichment progress check."""
from pymongo import MongoClient

c = MongoClient('mongodb://localhost:27017/')
db = c['quantum_github']

total = db.repositories.count_documents({})
is_complete = db.repositories.count_documents({"enrichment_status.is_complete": True})
not_complete = db.repositories.count_documents({"enrichment_status.is_complete": False})
no_status = total - is_complete - not_complete

# Distribution by total_fields_enriched
buckets = {
    ">=25": db.repositories.count_documents({"enrichment_status.total_fields_enriched": {"$gte": 25}}),
    "15-24": db.repositories.count_documents({"enrichment_status.total_fields_enriched": {"$gte": 15, "$lt": 25}}),
    "8-14": db.repositories.count_documents({"enrichment_status.total_fields_enriched": {"$gte": 8, "$lt": 15}}),
    "<8": db.repositories.count_documents({"enrichment_status.total_fields_enriched": {"$lt": 8}}),
}

print(f"Total repos: {total}")
print(f"Enrichment complete: {is_complete}")
print(f"Enrichment incomplete: {not_complete}")
print(f"No enrichment status: {no_status}")
print(f"\nField count distribution:")
for label, count in buckets.items():
    print(f"  {label} fields: {count} repos")
print(f"\nUsers: {db.users.count_documents({})}")
print(f"Orgs: {db.organizations.count_documents({})}")
