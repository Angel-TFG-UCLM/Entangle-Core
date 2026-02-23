#!/usr/bin/env python3
"""
Analiza datos reales ejecutando CollaborationNetworkAnalyzer
y reproduciendo los cálculos del worker del frontend (logScale, etc.)
para verificar coherencia y escalas del radar de colaboración.
"""

import sys
import os
import math
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.core.db import Database
from src.analysis.network_metrics import CollaborationNetworkAnalyzer


def log_scale(val, max_val):
    """Misma logScale que el worker del frontend."""
    if max_val <= 0:
        return 0
    return min(math.log(1 + val) / math.log(1 + max_val), 1.0)


def pct(vals, p):
    """Percentile p de una lista ordenada."""
    if not vals:
        return 0
    idx = int(len(vals) * p / 100)
    return vals[min(idx, len(vals) - 1)]


def analyze():
    db = Database()
    db.connect()

    try:
        repos_col = db.get_collection("repositories")
        users_col = db.get_collection("users")
        orgs_col  = db.get_collection("organizations")

        print("Construyendo grafo de colaboración (puede tardar)...")
        analyzer = CollaborationNetworkAnalyzer()
        analyzer.build_from_mongodb(repos_col, users_col, orgs_col)
        full = analyzer.get_full_analysis()

        node_metrics = full.get("node_metrics", {})
        print(f"Nodos analizados: {len(node_metrics)}")

        # ── Clasificar nodos por tipo (prefijo en el ID) ──
        users_nm, repos_nm, orgs_nm = {}, {}, {}
        for nid, m in node_metrics.items():
            if nid.startswith("user_"):
                users_nm[nid] = m
            elif nid.startswith("repo_"):
                repos_nm[nid] = m
            elif nid.startswith("org_"):
                orgs_nm[nid] = m

        print(f"  Users: {len(users_nm)}, Repos: {len(repos_nm)}, Orgs: {len(orgs_nm)}")

        # ── Reconstruir relaciones (como universeData) ──
        # El grafo usa: repo_{full_name}, user_{login}, org_{login}
        # Los repos se basan en "collaborators", no "contributors"
        repo_contributors = defaultdict(set)   # repo_X → set of user_X
        user_repos_map = defaultdict(set)       # user_X → set of repo_X
        repo_to_org = {}                        # repo_X → org_X
        org_repos_map = defaultdict(list)        # org_X → [repo doc]
        repo_objects = {}                        # repo_X → repo doc

        for repo in repos_col.find({}, {"_id": 0}):
            fn = repo.get("full_name")
            if not fn:
                continue
            rid = f"repo_{fn}"
            repo_objects[rid] = repo

            org_login = repo.get("owner", {}).get("login", "")
            if org_login:
                oid = f"org_{org_login}"
                repo_to_org[rid] = oid
                org_repos_map[oid].append(repo)

            for c in repo.get("collaborators", []):
                login = c.get("login")
                if login:
                    uid = f"user_{login}"
                    repo_contributors[rid].add(uid)
                    user_repos_map[uid].add(rid)

        print(f"  Relaciones: {len(user_repos_map)} users->repos, "
              f"{len(repo_contributors)} repos->contribs")

        # ══════════════════════════════════════════════════════════════
        # USUARIOS
        # ══════════════════════════════════════════════════════════════
        print(f"\n{'='*80}")
        print("ANÁLISIS DE USUARIOS")
        print(f"{'='*80}")

        user_data = []
        for uid, m in users_nm.items():
            cent = m.get("collab_centrality", 0)
            conn = m.get("collab_connectivity", 0)
            cent_raw = m.get("collab_centrality_raw", 0)
            conn_raw = m.get("collab_connectivity_raw", 0)

            repos = user_repos_map.get(uid, set())
            u_orgs = set()
            for rid in repos:
                oid = repo_to_org.get(rid)
                if oid:
                    u_orgs.add(oid)

            co_contribs = set()
            for rid in repos:
                for other in repo_contributors.get(rid, set()):
                    if other != uid:
                        co_contribs.add(other)

            u_langs = set()
            for rid in repos:
                robj = repo_objects.get(rid)
                if robj and robj.get("language"):
                    u_langs.add(robj["language"])

            user_data.append({
                "id": uid,
                "cent": cent, "conn": conn,
                "cent_raw": cent_raw, "conn_raw": conn_raw,
                "org_span_raw": len(u_orgs),
                "colab_raw": len(co_contribs),
                "langs_raw": len(u_langs),
                "r_cent": cent / 100,
                "r_conn": conn / 100,
                "r_org_span": log_scale(len(u_orgs), 15),
                "r_colab": log_scale(len(co_contribs), 150),
                "r_versatility": log_scale(len(u_langs), 12),
            })

        if not user_data:
            print("  No hay users con métricas.")
        else:
            print(f"  Total: {len(user_data)} users")

            axes = [
                ("Centralidad",   "r_cent",       "cent_raw",      None),
                ("Conectividad",  "r_conn",       "conn_raw",      None),
                ("Org Span",      "r_org_span",   "org_span_raw",  15),
                ("Colaboración",  "r_colab",      "colab_raw",     150),
                ("Versatilidad",  "r_versatility","langs_raw",     12),
            ]
            for label, scaled_key, raw_key, max_val in axes:
                s = sorted([u[scaled_key] for u in user_data])
                r = sorted([u[raw_key] for u in user_data])
                sat = sum(1 for v in s if v >= 0.95)
                print(f"\n  {label}"
                      f" (logMax={max_val})" if max_val else "")
                print(f"    Escalado: min={s[0]:.3f}  p25={pct(s,25):.3f}"
                      f"  p50={pct(s,50):.3f}  p75={pct(s,75):.3f}"
                      f"  p90={pct(s,90):.3f}  p95={pct(s,95):.3f}"
                      f"  max={s[-1]:.3f}")
                print(f"    Raw:      min={r[0]}  p25={pct(r,25)}"
                      f"  p50={pct(r,50)}  p75={pct(r,75)}"
                      f"  p90={pct(r,90)}  p95={pct(r,95)}  max={r[-1]}")
                print(f"    Saturados (>=95%): {sat} ({sat/len(s)*100:.1f}%)")

            # Casos: alta colaboración + baja centralidad
            print(f"\n  ── CASOS: Colaboración>=80% + Centralidad<60% ──")
            suspects = sorted(
                [u for u in user_data
                 if u["r_colab"] >= 0.80 and u["r_cent"] < 0.60],
                key=lambda u: u["r_colab"], reverse=True
            )
            if suspects:
                for s in suspects[:15]:
                    print(f"    {s['id'][:32]:34s} "
                          f"cent={s['r_cent']:.0%}(raw={s['cent_raw']}) "
                          f"colab={s['r_colab']:.0%}(raw={s['colab_raw']}) "
                          f"orgs={s['org_span_raw']} langs={s['langs_raw']}")
            else:
                print("    Ninguno")

            # Top co-contributors
            print(f"\n  ── Top 15 co-contributors (raw) ──")
            top = sorted(user_data, key=lambda u: u["colab_raw"], reverse=True)
            for u in top[:15]:
                print(f"    co={u['colab_raw']:>5d}  "
                      f"logScale(150)={u['r_colab']:.3f}  "
                      f"cent={u['r_cent']:.0%} orgs={u['org_span_raw']}  "
                      f"id={u['id'][:30]}")

            # Recomendación de escalas
            print(f"\n  ── RECOMENDACIÓN DE ESCALAS ──")
            for label, raw_key, current_max in [
                ("Org Span", "org_span_raw", 15),
                ("Colaboración", "colab_raw", 150),
                ("Versatilidad", "langs_raw", 12),
            ]:
                vals = sorted([u[raw_key] for u in user_data])
                p90 = pct(vals, 90)
                p95 = pct(vals, 95)
                p99 = pct(vals, 99)
                mx = vals[-1]
                sat_pct = (sum(1 for v in vals
                           if log_scale(v, current_max) >= 0.95)
                          / len(vals) * 100)
                print(f"\n    {label} (logMax={current_max}):")
                print(f"      p90={p90}  p95={p95}  p99={p99}  max={mx}")
                print(f"      Saturados: {sat_pct:.1f}%")
                if sat_pct > 15:
                    suggested = max(current_max, int(p99 * 2))
                    print(f"      ⚠️  Demasiada saturación -> sugerir max={suggested}")
                elif sat_pct > 5:
                    print(f"      ⚡ Moderada saturación -> evaluar subir max")
                else:
                    print(f"      ✅ Escala correcta")

        # ══════════════════════════════════════════════════════════════
        # REPOS
        # ══════════════════════════════════════════════════════════════
        print(f"\n{'='*80}")
        print("ANÁLISIS DE REPOS")
        print(f"{'='*80}")

        repo_data = []
        for rid, m in repos_nm.items():
            cent = m.get("collab_centrality", 0)
            conn = m.get("collab_connectivity", 0)
            contribs = repo_contributors.get(rid, set())

            org_div = set()
            for uid in contribs:
                for ur in user_repos_map.get(uid, set()):
                    oid = repo_to_org.get(ur)
                    if oid:
                        org_div.add(oid)

            bridge_count = 0
            for uid in contribs:
                u_org_set = set()
                for r in user_repos_map.get(uid, set()):
                    if r in repo_to_org:
                        u_org_set.add(repo_to_org[r])
                if len(u_org_set) >= 2:
                    bridge_count += 1
            bridge_ratio = bridge_count / max(len(contribs), 1)

            repo_data.append({
                "id": rid,
                "r_cent": cent / 100,
                "r_conn": conn / 100,
                "r_diversity": log_scale(len(org_div), 15),
                "diversity_raw": len(org_div),
                "r_bridge": bridge_ratio,
                "bridge_raw": bridge_count,
                "r_reach": log_scale(len(contribs), 80),
                "reach_raw": len(contribs),
            })

        if repo_data:
            print(f"  Total: {len(repo_data)} repos")
            r_axes = [
                ("Centralidad",           "r_cent",      None),
                ("Conectividad",          "r_conn",      None),
                ("Diversidad(logMax=15)",  "r_diversity", "diversity_raw"),
                ("Puente",                "r_bridge",    "bridge_raw"),
                ("Alcance(logMax=80)",    "r_reach",     "reach_raw"),
            ]
            for label, sk, rk in r_axes:
                s = sorted([r[sk] for r in repo_data])
                sat = sum(1 for v in s if v >= 0.95)
                line = (f"  {label}: p50={pct(s,50):.3f}  p90={pct(s,90):.3f}  "
                        f"p95={pct(s,95):.3f}  max={s[-1]:.3f}  "
                        f"sat>95%={sat}({sat/len(s)*100:.1f}%)")
                if rk:
                    r = sorted([d[rk] for d in repo_data])
                    line += (f"  raw: p90={pct(r,90)} "
                             f"p95={pct(r,95)} max={r[-1]}")
                print(line)

            # Recomendación repos
            print(f"\n  ── RECOMENDACIÓN DE ESCALAS REPOS ──")
            for label, raw_key, current_max in [
                ("Diversidad", "diversity_raw", 15),
                ("Alcance", "reach_raw", 80),
            ]:
                vals = sorted([d[raw_key] for d in repo_data])
                p90 = pct(vals, 90)
                p95 = pct(vals, 95)
                mx = vals[-1]
                sat_pct = (sum(1 for v in vals
                           if log_scale(v, current_max) >= 0.95)
                          / len(vals) * 100)
                print(f"    {label} (logMax={current_max}): "
                      f"p90={p90} p95={p95} max={mx} sat={sat_pct:.1f}%")
                if sat_pct > 10:
                    print(f"      ⚠️  Ajustar max")
                else:
                    print(f"      ✅ OK")

        # ══════════════════════════════════════════════════════════════
        # ORGS
        # ══════════════════════════════════════════════════════════════
        print(f"\n{'='*80}")
        print("ANÁLISIS DE ORGS")
        print(f"{'='*80}")

        org_data = []
        for oid, m in orgs_nm.items():
            cent = m.get("collab_centrality", 0)
            conn = m.get("collab_connectivity", 0)

            o_repos = org_repos_map.get(oid, [])
            o_users = set()
            for repo in o_repos:
                r_id = repo.get("id") or repo.get("node_id")
                if r_id:
                    o_users |= repo_contributors.get(r_id, set())

            bridge_ct = 0
            cross_ct = 0
            for uid in o_users:
                u_org_set = set()
                for ur in user_repos_map.get(uid, set()):
                    o2 = repo_to_org.get(ur)
                    if o2:
                        u_org_set.add(o2)
                if len(u_org_set) >= 2:
                    bridge_ct += 1
                if any(o != oid for o in u_org_set):
                    cross_ct += 1

            bridge_pct = (bridge_ct / max(len(o_users), 1)) * 100
            cross_poll = (cross_ct / max(len(o_users), 1)) * 100
            influence_raw = len(o_users) * len(o_repos)

            org_data.append({
                "id": oid,
                "r_cent": cent / 100,
                "r_conn": conn / 100,
                "r_diversity": min(cross_poll / 100, 1.0),
                "cross_poll": cross_poll,
                "r_bridge": log_scale(bridge_pct, 80),
                "bridge_pct": bridge_pct,
                "r_influence": log_scale(influence_raw, 2000),
                "influence_raw": influence_raw,
                "users": len(o_users),
                "repos": len(o_repos),
            })

        if org_data:
            print(f"  Total: {len(org_data)} orgs")
            o_axes = [
                ("Centralidad",            "r_cent",      None),
                ("Conectividad",           "r_conn",      None),
                ("Diversidad",             "r_diversity", "cross_poll"),
                ("Puente(logMax=80)",       "r_bridge",    "bridge_pct"),
                ("Influencia(logMax=2000)", "r_influence", "influence_raw"),
            ]
            for label, sk, rk in o_axes:
                s = sorted([o[sk] for o in org_data])
                sat = sum(1 for v in s if v >= 0.95)
                line = (f"  {label}: p50={pct(s,50):.3f}  p90={pct(s,90):.3f}  "
                        f"p95={pct(s,95):.3f}  max={s[-1]:.3f}  "
                        f"sat>95%={sat}({sat/len(s)*100:.1f}%)")
                if rk:
                    r = sorted([o[rk] for o in org_data])
                    line += (f"  raw: p90={pct(r,90):.0f} "
                             f"p95={pct(r,95):.0f} max={r[-1]:.0f}")
                print(line)

            # Recomendación orgs
            print(f"\n  ── RECOMENDACIÓN DE ESCALAS ORGS ──")
            for label, raw_key, current_max in [
                ("Puente", "bridge_pct", 80),
                ("Influencia", "influence_raw", 2000),
            ]:
                vals = sorted([o[raw_key] for o in org_data])
                p90 = pct(vals, 90)
                p95 = pct(vals, 95)
                mx = vals[-1]
                sat_pct = (sum(1 for v in vals
                           if log_scale(v, current_max) >= 0.95)
                          / len(vals) * 100)
                print(f"    {label} (logMax={current_max}): "
                      f"p90={p90:.0f} p95={p95:.0f} max={mx:.0f} "
                      f"sat={sat_pct:.1f}%")
                if sat_pct > 10:
                    print(f"      ⚠️  Ajustar max")
                else:
                    print(f"      ✅ OK")

        # ══════════════════════════════════════════════════════════════
        # RESUMEN
        # ══════════════════════════════════════════════════════════════
        print(f"\n{'='*80}")
        print("COHERENCIA: cent=55% + colab=100%?")
        print(f"{'='*80}")
        print("""
  Centralidad = percentil de "# orgs distintas" -> ALCANCE CROSS-ORG
  Colaboración = logScale(# co-contributors, 150) -> TAMAÑO RED PERSONAL

  Son conceptos DIFERENTES:
    - Un user puede contribuir a repos MUY populares de 2-3 orgs
      -> pocas orgs (centrality moderada ~55%)
      -> MUCHOS co-contributors en esos repos (collaboration alta)

  Si muchos users superan logScale max -> subir el max.
""")

    finally:
        db.disconnect()


if __name__ == "__main__":
    analyze()
