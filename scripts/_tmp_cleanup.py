"""Remove AI-created favorites (org_quantumlib, org_amazon-braket, etc.)."""
from pymongo import MongoClient

c = MongoClient("mongodb://localhost:27017/")
db = c["quantum_github"]
prefs = db["user_preferences"]

# Remove the 4 favorites added by the chat action
to_remove = ["org_quantumlib", "org_amazon-braket"]
for fid in to_remove:
    r = prefs.update_one({"type": "favorites"}, {"$pull": {"items": {"id": fid}}})
    print(f"Removed '{fid}': {r.modified_count}")

doc = prefs.find_one({"type": "favorites"})
items = doc.get("items", []) if doc else []
print(f"\nFavoritos restantes: {len(items)}")
for i in items:
    print(f"  {i['id']} | {i.get('name', '?')}")

c.close()
