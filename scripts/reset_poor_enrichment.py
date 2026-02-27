"""Reset poorly enriched repos so they get re-enriched properly."""
from pymongo import MongoClient

client = MongoClient('mongodb://localhost:27017/')
db = client['quantum_github']

# Find repos marked as complete but with very few enriched fields (< 12)
# These were enriched by the old process with a bad token
poorly_enriched = db.repositories.count_documents({
    "enrichment_status.is_complete": True,
    "enrichment_status.total_fields_enriched": {"$lt": 12}
})

print(f"Repos poorly enriched (<12 fields): {poorly_enriched}")

# Reset their enrichment status so they get picked up again
result = db.repositories.update_many(
    {
        "enrichment_status.is_complete": True,
        "enrichment_status.total_fields_enriched": {"$lt": 12}
    },
    {
        "$unset": {"enrichment_status": ""}
    }
)

print(f"Reset {result.modified_count} repos' enrichment_status")

# Verify
still_complete = db.repositories.count_documents({"enrichment_status.is_complete": True})
no_status = db.repositories.count_documents({"enrichment_status": {"$exists": False}})
print(f"\nAfter reset:")
print(f"  Still complete (rich enrichment): {still_complete}")
print(f"  No enrichment status (pending): {no_status}")
