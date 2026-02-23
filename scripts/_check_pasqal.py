"""Analyze centrality and connectivity distributions per entity type for data-driven classification."""
import requests

r = requests.get("http://localhost:8000/api/v1/collaboration/network-metrics")
data = r.json()
nodes = data.get("node_metrics", {})

for entity_type in ['org', 'repo', 'user']:
    prefix = entity_type + '_'
    cent = []
    conn = []
    for nid, v in nodes.items():
        if not nid.startswith(prefix):
            continue
        c = v.get('collab_centrality_raw', 0)
        cn = v.get('collab_connectivity_raw', 0)
        if c > 0 or cn > 0:
            cent.append(c)
            conn.append(cn)
    
    if not cent:
        print(f"\n=== {entity_type}: no active entities ===")
        continue
    
    cent = sorted(cent, reverse=True)
    conn = sorted(conn, reverse=True)
    total_type = sum(1 for k in nodes if k.startswith(prefix))
    
    print(f"\n=== {entity_type.upper()} ({len(cent)} active / {total_type} total) ===")
    print(f"  Centrality:    min={min(cent)}, max={max(cent)}, median={cent[len(cent)//2]}, mean={sum(cent)/len(cent):.1f}")
    print(f"  Connectivity:  min={min(conn)}, max={max(conn)}, median={conn[len(conn)//2]}, mean={sum(conn)/len(conn):.1f}")
    print(f"  Top 10 cent: {cent[:10]}")
    print(f"  Top 10 conn: {conn[:10]}")
