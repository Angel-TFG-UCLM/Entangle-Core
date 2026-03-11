"""Check enrichment progress."""
from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017/')
db = client['quantum_github']

total = db.repositories.count_documents({})
print(f"Total repos: {total}")

# Check what fields exist in enriched repos
sample = db.repositories.find_one({"full_name": "ixian-platform/Spixi"})
if sample:
    enrichment_keys = [k for k in sample.keys() if 'enrich' in k.lower() or 'history' in k.lower()]
    print(f"Enrichment fields: {enrichment_keys}")
    for k in enrichment_keys:
        v = sample[k]
        if isinstance(v, list):
            print(f"  {k}: list of {len(v)} items")
            if v:
                print(f"    Last item: complete={v[-1].get('is_complete')}, fields={v[-1].get('total_fields_enriched')}")
        else:
            print(f"  {k}: {v}")

# Count repos with enrichment data
has_enrichment = db.repositories.count_documents({"enrichment_history": {"$exists": True}})
has_complete = db.repositories.count_documents({"enrichment_history.is_complete": True})
print(f"\nWith enrichment_history: {has_enrichment}")
print(f"With is_complete=True in history: {has_complete}")

# Check repos with many fields (proxy for enrichment)
pipeline = [
    {"$project": {"full_name": 1, "num_fields": {"$size": {"$objectToArray": "$$ROOT"}}}},
    {"$sort": {"num_fields": -1}},
    {"$limit": 5}
]
print("\nTop 5 repos by field count:")
for doc in db.repositories.aggregate(pipeline):
    print(f"  {doc['full_name']}: {doc['num_fields']} fields")

# Count repos with collaborators field (only from enrichment)
has_collabs = db.repositories.count_documents({"collaborators": {"$exists": True}})
has_commits = db.repositories.count_documents({"recent_commits": {"$exists": True}})
print(f"\nWith collaborators: {has_collabs}")
print(f"With recent_commits: {has_commits}")

# Users and orgs
print(f"\nUsers: {db.users.count_documents({})}")
print(f"Orgs: {db.organizations.count_documents({})}")

# Check latest enrichment timestamp
pipeline2 = [
    {"$match": {"enrichment_history": {"$exists": True}}},
    {"$project": {"last_enriched": {"$arrayElemAt": ["$enrichment_history.last_enriched", -1]}}},
    {"$sort": {"last_enriched": -1}},
    {"$limit": 3}
]
results = list(db.repositories.aggregate(pipeline2))
if results:
    print(f"\nLatest enrichment timestamps:")
    for r in results:
        print(f"  {r.get('last_enriched')}")
