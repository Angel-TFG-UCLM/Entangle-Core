"""Verificar distribución de scores de orgs para layout."""
import sys, statistics
sys.path.insert(0, "src")
from core.db import get_database
from analysis.network_metrics import CollaborationNetworkAnalyzer

db = get_database()
analyzer = CollaborationNetworkAnalyzer()
analyzer.build_from_mongodb(db["repositories"], db["users"], db["organizations"])
scores = analyzer.compute_collaboration_scores()

# Get org scores only
org_scores = {}
for node_id, data in scores.items():
    if analyzer.G.nodes[node_id].get("type") == "org":
        org_scores[node_id] = data

sorted_orgs = sorted(org_scores.items(), key=lambda x: x[1]["collab_centrality_raw"], reverse=True)

non_zero = sum(1 for _, d in sorted_orgs if d["collab_centrality_raw"] > 0)
print(f"Total orgs: {len(sorted_orgs)}")
print(f"Orgs with raw > 0: {non_zero}")
print()
print("TOP 30 by collab_centrality_raw:")
for i, (oid, d) in enumerate(sorted_orgs[:30]):
    name = oid.replace("org_", "")
    print(f"  {i+1:3d}. {name:30s} raw={d['collab_centrality_raw']:6d}  pct={d['collab_centrality']:3d}  conn_raw={d['collab_connectivity_raw']:3d}  conn_pct={d['collab_connectivity']:3d}")

# Find specific orgs
for search in ["microsoft", "qiskit", "google", "ibm", "aws", "sebastienrousseau"]:
    keys = [k for k in org_scores if search.lower() in k.lower()]
    if keys:
        print(f"\n{search.upper()}:")
        for k in keys:
            d = org_scores[k]
            rank = next(i for i, (oid, _) in enumerate(sorted_orgs) if oid == k) + 1
            print(f"  {k}: raw={d['collab_centrality_raw']}, pct={d['collab_centrality']}, conn_raw={d['collab_connectivity_raw']}, conn_pct={d['collab_connectivity']}, rank={rank}/{len(sorted_orgs)}")

# Distribution stats
raw_vals = [d["collab_centrality_raw"] for _, d in sorted_orgs if d["collab_centrality_raw"] > 0]
if raw_vals:
    print(f"\nDistribution of raw (non-zero, n={len(raw_vals)}):")
    print(f"  min={min(raw_vals)}, max={max(raw_vals)}, median={statistics.median(raw_vals)}, mean={statistics.mean(raw_vals):.1f}")
    quantiles = statistics.quantiles(raw_vals, n=10)
    print(f"  p10={quantiles[0]:.0f}, p25={quantiles[1]:.0f}, p50={quantiles[4]:.0f}, p75={quantiles[6]:.0f}, p90={quantiles[8]:.0f}")

# Show how the log mapping would distribute
import math
max_raw = sorted_orgs[0][1]["collab_centrality_raw"] if sorted_orgs else 1
PERIPHERY_MAX = 900 * math.sqrt(1122 / 200)  # scaleFactor for 1122 repos

print(f"\nLog mapping simulation (maxScore={max_raw}, PERIPHERY_MAX={PERIPHERY_MAX:.0f}):")
for i, (oid, d) in enumerate(sorted_orgs[:30]):
    raw = d["collab_centrality_raw"]
    name = oid.replace("org_", "")
    if raw > 0:
        normalized = math.log(1 + raw) / math.log(1 + max_raw)
        curved = normalized ** 0.7
        targetR = PERIPHERY_MAX * (1 - curved)
        zone = "CORE" if targetR <= 150 * math.sqrt(1122/200) else ("MID" if targetR <= 500 * math.sqrt(1122/200) else "ISO")
        print(f"  {i+1:3d}. {name:30s} raw={raw:6d}  norm={normalized:.3f}  curved={curved:.3f}  radius={targetR:.0f}  zone={zone}")
    else:
        print(f"  {i+1:3d}. {name:30s} raw=0  zone=ISO")
