"""
ENTANGLE Network Analysis Engine
=================================
Computes graph-theory metrics on the collaboration network using NetworkX.

Métricas implementadas:
  ◈ Betweenness Centrality  - ¿Quién es el puente más crítico?
  ◈ Degree Centrality       - ¿Quién tiene más conexiones directas?
  ◈ Community Detection     - ¿Existen clusters naturales? (Louvain)
  ◈ Bus Factor              - ¿Cuál es el riesgo si un contributor se va?
  ◈ Collaboration Intensity - ¿Cuán fuerte es cada conexión?
  ◈ Shortest Path           - Quantum Tunneling entre dos entidades
  ◈ Global Graph Metrics    - Densidad, clustering, modularidad, diámetro

Node IDs use the same scheme as /collaboration/discover:
  org_{login}, repo_{full_name}, user_{login}
"""

import re
import networkx as nx
import colorsys
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# PALETTE - Generación programática con máxima separación visual
# ============================================================================
# En vez de 20 colores estáticos que se repiten cada 20 comunidades,
# usamos el ángulo áureo (137.508°) para distribuir hues de forma
# que colores consecutivos estén lo más separados posible.
# Se combinan 3 tiers de saturación/luminosidad para triplicar
# la variedad efectiva antes de repetir un color perceptualmente similar.

GOLDEN_ANGLE = 137.508  # grados


def _hsl_to_hex(h: float, s: float, l: float) -> str:
    """Convert HSL (h: 0-360, s: 0-100, l: 0-100) to hex."""
    r, g, b = colorsys.hls_to_rgb(h / 360.0, l / 100.0, s / 100.0)
    return f'#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}'


# 3 tiers (sat%, lum%) - optimizados para fondo oscuro (#0a0a1a)
_TIERS = [
    (85, 62),  # Vivid medium   - saturados, luminosidad media
    (92, 50),  # Vivid dark     - muy saturados, más oscuros
    (72, 74),  # Soft bright    - suaves, más claros
]


def community_color(idx: int) -> str:
    """
    Generate a deterministic, visually distinct color for community `idx`.
    
    Uses golden-angle hue spacing (137.508°) with 3 saturation/lightness
    tiers, producing ~1080 visually distinct colors before any near-repeat.
    """
    tier = _TIERS[idx % len(_TIERS)]
    hue = (idx * GOLDEN_ANGLE) % 360.0
    return _hsl_to_hex(hue, tier[0], tier[1])


def _are_sibling_orgs(login_a: str, login_b: str) -> bool:
    """
    Return True if two org logins belong to the same parent entity.
    E.g. 'qiskit' ↔ 'qiskit-community', 'microsoft' ↔ 'MicrosoftDocs'.
    """
    if not login_a or not login_b:
        return False
    la, lb = login_a.lower(), login_b.lower()
    if la == lb:
        return True
    # PRONG 1 — Token-based: split by separators, match first token (≥4 chars).
    # Require ONE name to be a single token (the brand itself) to avoid
    # "quantum-X ↔ quantum-Y" false positives in this domain.
    toks_a = [t for t in re.split(r'[-_.\s]+', la) if t]
    toks_b = [t for t in re.split(r'[-_.\s]+', lb) if t]
    if toks_a and toks_b and len(toks_a[0]) >= 4 and toks_a[0] == toks_b[0]:
        if len(toks_a) == 1 or len(toks_b) == 1:
            return True
    # PRONG 2 — Prefix-based: shorter normalised name must be PREFIX of
    # longer, ≥ 4 chars, and ratio ≤ 3.0 (rejects intel→intelligentquantum).
    a = re.sub(r'[-_\s.]+', '', la)
    b = re.sub(r'[-_\s.]+', '', lb)
    if not a or not b:
        return False
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return bool(len(short) >= 4 and long_.startswith(short) and len(long_) / len(short) <= 3.0)


class CollaborationNetworkAnalyzer:
    """
    Builds and analyzes a collaboration network from MongoDB data.
    
    Supports:
    - Full heterogeneous graph (users + repos + orgs)
    - All standard network metrics
    - Cached results via MongoDB metrics collection
    """

    def __init__(self):
        self.G = nx.Graph()
        self._repos_data = {}  # full_name -> repo doc

    # ========================================================================
    # GRAPH CONSTRUCTION
    # ========================================================================

    def build_from_mongodb(self, repos_collection, users_collection, orgs_collection, year_from=None, year_to=None):
        """
        Build networkx graph from MongoDB collections.
        
        Nodes: org_{login}, repo_{full_name}, user_{login}
        Edges: owns (org→repo), contributed_to (user→repo)
        Weights: contribution count (higher = stronger connection)
        
        Args:
            year_from: Optional[int] - filter repos with pushed_at >= Jan 1 of this year
            year_to: Optional[int] - filter repos with pushed_at <= Dec 31 of this year
        """
        from datetime import datetime as dt
        
        # 1. Load all repos with collaborators
        all_repos = list(repos_collection.find(
            {"collaborators": {"$exists": True, "$ne": []}},
            {
                "_id": 0, "name": 1, "full_name": 1, "owner": 1,
                "stargazer_count": 1, "primary_language": 1,
                "collaborators": 1, "fork_count": 1,
                "collaborators_count": 1, "pushed_at": 1
            }
        ))
        
        # Apply temporal filter if specified
        has_temporal = year_from is not None or year_to is not None
        if has_temporal:
            total_before = len(all_repos)
            def _in_range(repo):
                pushed = repo.get("pushed_at")
                if not pushed:
                    return False
                if isinstance(pushed, str):
                    try:
                        pushed = dt.fromisoformat(pushed.replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        return False
                y = pushed.year
                if year_from is not None and y < year_from:
                    return False
                return not (year_to is not None and y > year_to)
            all_repos = [r for r in all_repos if _in_range(r)]
            logger.info(f"[NetworkAnalyzer] Temporal filter: {total_before} → {len(all_repos)} repos")

        logger.info(f"[NetworkAnalyzer] Building graph from {len(all_repos)} repos")

        # 2. Add repo nodes + user→repo edges
        for repo in all_repos:
            full_name = repo.get("full_name")
            if not full_name:
                continue

            repo_id = f"repo_{full_name}"
            org_login = repo.get("owner", {}).get("login", "")
            lang = repo.get("primary_language")
            language = lang.get("name") if isinstance(lang, dict) else lang

            self.G.add_node(repo_id,
                type="repo",
                name=repo.get("name"),
                full_name=full_name,
                stars=repo.get("stargazer_count", 0),
                language=language,
                org=org_login
            )
            self._repos_data[full_name] = repo

            for collab in repo.get("collaborators", []):
                login = collab.get("login")
                if not login:
                    continue

                user_id = f"user_{login}"
                contributions = max(collab.get("contributions", 1), 1)

                if not self.G.has_node(user_id):
                    # Detectar bots por login (heurística rápida)
                    is_bot = self._detect_bot_by_login(login)
                    self.G.add_node(user_id, type="user", login=login, is_bot=is_bot)

                self.G.add_edge(user_id, repo_id,
                    weight=contributions,
                    contributions=collab.get("contributions", 0),
                    has_commits=collab.get("has_commits", False),
                    type="contributed_to"
                )

            # 3. Add org→repo edge
            if org_login:
                org_id = f"org_{org_login}"
                if not self.G.has_node(org_id):
                    self.G.add_node(org_id, type="org", login=org_login)
                self.G.add_edge(org_id, repo_id, weight=1, type="owns")

        # 4. Enrich user nodes from users collection (including is_bot flag)
        user_logins = [
            n.replace("user_", "") for n in self.G.nodes
            if self.G.nodes[n].get("type") == "user"
        ]
        if user_logins:
            for doc in users_collection.find(
                {"login": {"$in": user_logins}},
                {
                    "_id": 0, "login": 1, "name": 1, "avatar_url": 1,
                    "quantum_expertise_score": 1, "is_bot": 1
                }
            ):
                uid = f"user_{doc['login']}"
                if self.G.has_node(uid):
                    # is_bot from DB takes precedence, fallback to login heuristic
                    db_is_bot = doc.get("is_bot", False)
                    self.G.nodes[uid].update({
                        "name": doc.get("name"),
                        "avatar_url": doc.get("avatar_url"),
                        "quantum_expertise_score": doc.get("quantum_expertise_score", 0),
                        "is_bot": db_is_bot or self.G.nodes[uid].get("is_bot", False)
                    })

        # 5. Enrich org nodes from orgs collection
        org_logins = [
            n.replace("org_", "") for n in self.G.nodes
            if self.G.nodes[n].get("type") == "org"
        ]
        if org_logins:
            for doc in orgs_collection.find(
                {"login": {"$in": org_logins}},
                {
                    "_id": 0, "login": 1, "name": 1, "avatar_url": 1,
                    "quantum_focus_score": 1, "is_quantum_focused": 1
                }
            ):
                oid = f"org_{doc['login']}"
                if self.G.has_node(oid):
                    self.G.nodes[oid].update({
                        "name": doc.get("name"),
                        "avatar_url": doc.get("avatar_url"),
                        "quantum_focus_score": doc.get("quantum_focus_score", 0),
                        "is_quantum_focused": doc.get("is_quantum_focused", False)
                    })

        logger.info(
            f"[NetworkAnalyzer] Graph: {self.G.number_of_nodes()} nodes, "
            f"{self.G.number_of_edges()} edges"
        )
        return self

    # ========================================================================
    # CENTRALITY METRICS
    # ========================================================================

    def compute_centrality(self):
        """
        Compute betweenness and degree centrality for all nodes.
        Betweenness is normalized to [0,1] for consistent UI scaling.
        For large graphs (>5K nodes), uses a small k sample for speed.
        """
        n = self.G.number_of_nodes()
        if n == 0:
            return {}

        # Betweenness: approximate with small k for large graphs
        # k=50 gives ~4x speedup over k=200 with acceptable accuracy
        k = min(50, n) if n > 5000 else min(200, n)
        logger.info(f"[NetworkAnalyzer] Computing betweenness centrality (k={k}, n={n})...")
        try:
            betweenness = nx.betweenness_centrality(
                self.G, weight='weight', k=k, seed=42
            )
        except Exception:
            betweenness = dict.fromkeys(self.G.nodes, 0)

        # Degree centrality
        degree = nx.degree_centrality(self.G)

        # Normalize betweenness to [0, 1]
        max_bc = max(betweenness.values()) if betweenness else 1
        if max_bc > 0:
            betweenness = {k: v / max_bc for k, v in betweenness.items()}

        return {
            node_id: {
                "betweenness": round(betweenness.get(node_id, 0), 6),
                "degree": round(degree.get(node_id, 0), 6),
            }
            for node_id in self.G.nodes
        }

    # ========================================================================
    # COLLABORATION SCORES - Meaningful centrality & connectivity per type
    # ========================================================================

    def compute_collaboration_scores(self):
        """
        Compute intuitive collaboration metrics for each node, normalized
        to [0..100] using percentile rank within each node type.

        Centralidad (collab_centrality):
          - User: nº de orgs distintas a las que contribuye (cross-org reach)
          - Repo: nº de orgs distintas de sus contributors (org diversity)
          - Org:  suma de contributors compartidos con otras orgs (inter-org bridges)

        Conectividad (collab_connectivity):
          - User: nº de repos a los que contribuye
          - Repo: nº de contributors
          - Org:  nº de orgs vecinas (comparten ≥1 contributor)

        Both are percentile-ranked within each type so distribution is
        uniform and visually meaningful (no power-law compression).
        """
        logger.info("[NetworkAnalyzer] Computing collaboration scores...")

        # ── Step 1: Pre-compute per-repo org and per-user org mappings ──
        # repo → set of orgs of its contributors
        repo_contributor_orgs = {}
        # repo → set of contributors
        repo_contributors = {}
        # user → set of orgs they contribute to
        user_orgs = {}
        # user → set of repos they contribute to
        user_repos = {}
        # org → set of repos it owns
        org_repos = {}

        for u, v, data in self.G.edges(data=True):
            edge_type = data.get("type")

            if edge_type == "contributed_to":
                user_id, repo_id = u, v
                # user → repos
                if user_id not in user_repos:
                    user_repos[user_id] = set()
                user_repos[user_id].add(repo_id)
                # repo → contributors
                if repo_id not in repo_contributors:
                    repo_contributors[repo_id] = set()
                repo_contributors[repo_id].add(user_id)

            elif edge_type == "owns":
                org_id, repo_id = u, v
                if org_id not in org_repos:
                    org_repos[org_id] = set()
                org_repos[org_id].add(repo_id)

        # Map repo → owner org
        repo_owner_org = {}
        for org_id, repos in org_repos.items():
            for repo_id in repos:
                repo_owner_org[repo_id] = org_id

        # user → set of orgs they contribute to
        for user_id, repos in user_repos.items():
            orgs = set()
            for repo_id in repos:
                org = repo_owner_org.get(repo_id)
                if org:
                    orgs.add(org)
            user_orgs[user_id] = orgs

        # repo → set of distinct orgs of its contributors
        for repo_id, contributors in repo_contributors.items():
            orgs = set()
            for user_id in contributors:
                for repo2 in user_repos.get(user_id, set()):
                    org = repo_owner_org.get(repo2)
                    if org:
                        orgs.add(org)
            repo_contributor_orgs[repo_id] = orgs

        # ── Step 2: Org collaboration graph ──
        # org → { neighbor_org: shared_contributor_count }
        org_neighbors = {}
        sibling_pairs_skipped = 0
        for user_id, orgs in user_orgs.items():
            if len(orgs) < 2:
                continue
            org_list = list(orgs)
            for i in range(len(org_list)):
                for j in range(i + 1, len(org_list)):
                    a, b = org_list[i], org_list[j]
                    # Skip sibling orgs (e.g. qiskit / qiskit-community)
                    login_a = a.replace("org_", "", 1)
                    login_b = b.replace("org_", "", 1)
                    if _are_sibling_orgs(login_a, login_b):
                        sibling_pairs_skipped += 1
                        continue
                    if a not in org_neighbors:
                        org_neighbors[a] = {}
                    if b not in org_neighbors:
                        org_neighbors[b] = {}
                    org_neighbors[a][b] = org_neighbors[a].get(b, 0) + 1
                    org_neighbors[b][a] = org_neighbors[b].get(a, 0) + 1
        if sibling_pairs_skipped:
            logger.info(f"[NetworkAnalyzer] Skipped {sibling_pairs_skipped} sibling org pairs in org_neighbors")

        # ── Step 3: Raw scores ──
        raw_scores = {}  # node_id → (centrality_raw, connectivity_raw)

        for node_id in self.G.nodes:
            node_type = self.G.nodes[node_id].get("type")

            if node_type == "user":
                centrality_raw = len(user_orgs.get(node_id, set()))
                connectivity_raw = len(user_repos.get(node_id, set()))
            elif node_type == "repo":
                centrality_raw = len(repo_contributor_orgs.get(node_id, set()))
                connectivity_raw = len(repo_contributors.get(node_id, set()))
            elif node_type == "org":
                neighbors = org_neighbors.get(node_id, {})
                raw_collab = sum(neighbors.values())  # total shared contributors
                connectivity_raw = len(neighbors)  # number of org neighbors

                # ── Quantum relevance weighting ──
                # The "Quantum Universe" should center quantum-focused orgs.
                # Without weighting, mega-orgs like Microsoft dominate by
                # sheer contributor volume despite not being quantum-focused.
                qf = self.G.nodes[node_id].get("quantum_focus_score", 0)
                is_q = self.G.nodes[node_id].get("is_quantum_focused", False)

                if is_q:
                    # Quantum orgs: full weight + bonus from focus score
                    quantum_factor = 1.0 + (qf / 100)   # range [1.0 .. 2.0]
                else:
                    # Non-quantum orgs: heavily dampened
                    quantum_factor = max(0.05, qf / 200)  # range [0.05 .. 0.5]

                centrality_raw = int(raw_collab * quantum_factor)
            else:
                centrality_raw = 0
                connectivity_raw = 0

            raw_scores[node_id] = (centrality_raw, connectivity_raw)

        # ── Step 4: Percentile rank per type ──
        def percentile_rank(values):
            """Convert raw values to [0..100] percentile ranks."""
            if not values:
                return {}
            sorted_vals = sorted(set(values.values()))
            if len(sorted_vals) <= 1:
                return {k: (100 if v > 0 else 0) for k, v in values.items()}
            rank_map = {v: i for i, v in enumerate(sorted_vals)}
            max_rank = len(sorted_vals) - 1
            return {
                k: round(rank_map[v] / max_rank * 100)
                for k, v in values.items()
            }

        # Group by type
        by_type = {"user": {}, "repo": {}, "org": {}}
        for node_id, (c, _) in raw_scores.items():
            t = self.G.nodes[node_id].get("type")
            if t in by_type:
                by_type[t][node_id] = c
        centrality_pct = {}
        for t, vals in by_type.items():
            centrality_pct.update(percentile_rank(vals))

        by_type2 = {"user": {}, "repo": {}, "org": {}}
        for node_id, (_, conn) in raw_scores.items():
            t = self.G.nodes[node_id].get("type")
            if t in by_type2:
                by_type2[t][node_id] = conn
        connectivity_pct = {}
        for t, vals in by_type2.items():
            connectivity_pct.update(percentile_rank(vals))

        # ── Step 5: Build result ──
        result = {}
        for node_id, (c_raw, conn_raw) in raw_scores.items():
            result[node_id] = {
                "collab_centrality": centrality_pct.get(node_id, 0),
                "collab_connectivity": connectivity_pct.get(node_id, 0),
                "collab_centrality_raw": c_raw,
                "collab_connectivity_raw": conn_raw,
            }

        # Log stats
        for t in ["org", "repo", "user"]:
            nodes_of_type = [n for n in result if self.G.nodes[n].get("type") == t]
            if nodes_of_type:
                avg_c = sum(result[n]["collab_centrality"] for n in nodes_of_type) / len(nodes_of_type)
                avg_conn = sum(result[n]["collab_connectivity"] for n in nodes_of_type) / len(nodes_of_type)
                logger.info(
                    f"[CollabScores] {t}: {len(nodes_of_type)} nodes, "
                    f"avg centrality={avg_c:.1f}%, avg connectivity={avg_conn:.1f}%"
                )

        return result

    # ========================================================================
    # COMMUNITY DETECTION (Louvain)
    # ========================================================================

    def detect_communities(self):
        """
        Detect communities using Louvain algorithm.
        Returns: (community_list, node_community_map)
        """
        if self.G.number_of_nodes() < 2:
            return [], {}

        try:
            communities_gen = nx.community.louvain_communities(
                self.G, weight='weight', resolution=1.0, seed=42
            )
            communities = [list(c) for c in communities_gen]
        except Exception as e:
            logger.warning(f"[NetworkAnalyzer] Louvain failed: {e}, using components")
            communities = [list(c) for c in nx.connected_components(self.G)]

        communities.sort(key=len, reverse=True)

        node_community = {}
        community_list = []

        for idx, members in enumerate(communities):
            color = community_color(idx)

            # Key members: highest degree in this community
            member_degrees = [
                (m, self.G.degree(m)) for m in members if self.G.has_node(m)
            ]
            member_degrees.sort(key=lambda x: x[1], reverse=True)
            key_members = [m for m, _ in member_degrees[:3]]

            # Generate label from key members
            key_names = []
            for m in key_members:
                data = self.G.nodes.get(m, {})
                name = (
                    data.get("name") or data.get("login")
                    or data.get("full_name", m)
                )
                key_names.append(name)

            label = f"Cluster {idx + 1}"
            if key_names:
                label += f": {', '.join(key_names[:2])}"

            community_info = {
                "id": idx,
                "color": color,
                "size": len(members),
                "label": label,
                "key_members": key_members[:5],
                "types": {
                    "orgs": sum(1 for m in members if self.G.nodes.get(m, {}).get("type") == "org"),
                    "repos": sum(1 for m in members if self.G.nodes.get(m, {}).get("type") == "repo"),
                    "users": sum(1 for m in members if self.G.nodes.get(m, {}).get("type") == "user"),
                }
            }
            community_list.append(community_info)

            for member in members:
                node_community[member] = {
                    "community_id": idx,
                    "community_color": color,
                    "community_label": label
                }

        return community_list, node_community

    # ========================================================================
    # BUS FACTOR
    # ========================================================================

    def compute_bus_factor(self):
        """
        Compute bus factor for each repository.
        Bus factor = minimum contributors to cover 50% of total contributions.
        """
        bus_factors = {}

        for full_name, repo in self._repos_data.items():
            repo_id = f"repo_{full_name}"
            collabs = repo.get("collaborators", [])

            if not collabs:
                bus_factors[repo_id] = {
                    "bus_factor": 0, "risk": "critical",
                    "total_contributions": 0, "total_contributors": 0,
                    "top_contributors": []
                }
                continue

            sorted_contribs = sorted(
                collabs,
                key=lambda c: c.get("contributions", 0),
                reverse=True
            )

            total = sum(c.get("contributions", 0) for c in sorted_contribs)
            if total == 0:
                risk = "low" if len(sorted_contribs) > 3 else "medium"
                bus_factors[repo_id] = {
                    "bus_factor": len(sorted_contribs), "risk": risk,
                    "total_contributions": 0,
                    "total_contributors": len(sorted_contribs),
                    "top_contributors": [
                        {"login": c.get("login"), "contributions": 0, "percentage": 0}
                        for c in sorted_contribs[:5]
                    ]
                }
                continue

            # Count contributors needed for 50%
            threshold = total * 0.5
            cumulative = 0
            bus_factor = 0
            top_contribs = []

            for c in sorted_contribs:
                contributions = c.get("contributions", 0)
                cumulative += contributions
                bus_factor += 1
                top_contribs.append({
                    "login": c.get("login"),
                    "contributions": contributions,
                    "percentage": round(contributions / total * 100, 1)
                })
                if cumulative >= threshold:
                    break

            # Risk assessment
            if bus_factor <= 1:
                risk = "critical"
            elif bus_factor <= 2:
                risk = "high"
            elif bus_factor <= 4:
                risk = "medium"
            else:
                risk = "low"

            bus_factors[repo_id] = {
                "bus_factor": bus_factor,
                "risk": risk,
                "total_contributions": total,
                "total_contributors": len(sorted_contribs),
                "top_contributors": top_contribs[:5]
            }

        return bus_factors

    # ========================================================================
    # COLLABORATION INTENSITY
    # ========================================================================

    def compute_collaboration_intensity(self):
        """Compute normalized intensity for each contributed_to edge."""
        intensities = {}
        max_weight = 1

        # First pass: find max
        for u, v, data in self.G.edges(data=True):
            if data.get("type") == "contributed_to":
                w = data.get("contributions", data.get("weight", 1))
                if w > max_weight:
                    max_weight = w

        # Second pass: normalize
        for u, v, data in self.G.edges(data=True):
            if data.get("type") == "contributed_to":
                w = data.get("contributions", data.get("weight", 1))
                edge_key = f"{u}->{v}"
                intensities[edge_key] = {
                    "contributions": w,
                    "intensity": round(w / max(max_weight, 1), 4),
                    "has_commits": data.get("has_commits", False)
                }

        return intensities

    # ========================================================================
    # GLOBAL GRAPH METRICS
    # ========================================================================

    def compute_global_metrics(self):
        """Compute graph-level metrics for the entire network.
        For large graphs (>5K nodes), skips expensive computations
        (avg_clustering, diameter, avg_path_length) that would take >30s.
        """
        if self.G.number_of_nodes() == 0:
            return {}

        num_nodes = self.G.number_of_nodes()
        num_edges = self.G.number_of_edges()
        density = nx.density(self.G)

        components = list(nx.connected_components(self.G))
        num_components = len(components)
        largest_size = len(max(components, key=len)) if components else 0

        # avg_clustering is O(n) but slow for large graphs
        avg_clustering = 0
        if num_nodes < 10000:
            try:
                avg_clustering = nx.average_clustering(self.G)
            except Exception:
                pass

        # diameter and avg_path_length are very expensive - skip for large components
        diameter = 0
        avg_path_length = 0
        if largest_size > 1 and largest_size < 2000:
            largest = self.G.subgraph(max(components, key=len)).copy()
            try:
                diameter = nx.diameter(largest)
                avg_path_length = nx.average_shortest_path_length(largest)
            except Exception:
                pass

        type_counts = defaultdict(int)
        for _, d in self.G.nodes(data=True):
            type_counts[d.get("type", "unknown")] += 1

        return {
            "num_nodes": num_nodes,
            "num_edges": num_edges,
            "density": round(density, 4),
            "avg_clustering": round(avg_clustering, 4),
            "num_components": num_components,
            "largest_component_size": largest_size,
            "diameter": diameter,
            "avg_path_length": round(avg_path_length, 2),
            "node_types": dict(type_counts)
        }

    # ========================================================================
    # BOT DETECTION (heuristic by login name)
    # ========================================================================

    @staticmethod
    def _detect_bot_by_login(login: str) -> bool:
        """Quick heuristic bot detection by login name."""
        low = login.lower()
        if low.endswith("[bot]"):
            return True
        bot_patterns = [
            "dependabot", "renovate", "greenkeeper", "snyk",
            "codecov", "github-actions", "automation", "auto-",
            "mergify", "stale", "allcontributors",
        ]
        return any(p in low for p in bot_patterns)

    # ========================================================================
    # SHORTEST PATH - Quantum Tunneling
    # ========================================================================

    def find_path(self, source_id, target_id):
        """
        Find shortest path between two nodes.
        Avoids bot nodes as intermediaries (bots can still be source/target).
        Falls back to full graph if no bot-free path exists.
        """
        if not self.G.has_node(source_id):
            return {"found": False, "error": f"Nodo origen '{source_id}' no encontrado"}
        if not self.G.has_node(target_id):
            return {"found": False, "error": f"Nodo destino '{target_id}' no encontrado"}

        try:
            # Build subgraph excluding bots (but keep source/target even if bots)
            non_bot_nodes = [
                n for n in self.G.nodes
                if n in (source_id, target_id) or not self.G.nodes[n].get("is_bot", False)
            ]
            G_no_bots = self.G.subgraph(non_bot_nodes)

            # Try bot-free path first
            try:
                path_nodes = nx.shortest_path(G_no_bots, source_id, target_id)
            except nx.NetworkXNoPath:
                # Fallback to full graph if no bot-free path exists
                path_nodes = nx.shortest_path(self.G, source_id, target_id)

            path_details = []
            for node_id in path_nodes:
                data = self.G.nodes[node_id]
                path_details.append({
                    "id": node_id,
                    "type": data.get("type", "unknown"),
                    "name": (
                        data.get("name") or data.get("login")
                        or data.get("full_name", node_id)
                    ),
                    "avatar_url": data.get("avatar_url")
                })

            edges = []
            for i in range(len(path_nodes) - 1):
                edge_data = self.G.edges[path_nodes[i], path_nodes[i + 1]]
                edges.append({
                    "source": path_nodes[i],
                    "target": path_nodes[i + 1],
                    "type": edge_data.get("type", "unknown"),
                    "contributions": edge_data.get("contributions", 0)
                })

            # Human-readable description
            icons = {"org": "🏢", "repo": "📦", "user": "👤"}
            desc_parts = [
                f"{icons.get(p['type'], '•')} {p['name']}" for p in path_details
            ]
            description = " → ".join(desc_parts)

            return {
                "found": True,
                "source": path_details[0],
                "target": path_details[-1],
                "path": path_details,
                "edges": edges,
                "length": len(path_nodes) - 1,
                "description": description
            }

        except nx.NetworkXNoPath:
            return {
                "found": False,
                "error": "No existe canal cuántico entre estas entidades",
                "source": source_id,
                "target": target_id
            }
        except Exception as e:
            return {"found": False, "error": str(e)}

    # ========================================================================
    # SEARCHABLE NODES - For autocomplete in Quantum Tunneling UI
    # ========================================================================

    def get_searchable_nodes(self):
        """Get all nodes formatted for autocomplete search."""
        nodes = []
        type_labels = {"org": "Org", "repo": "Repo", "user": "User"}
        for node_id, data in self.G.nodes(data=True):
            ntype = data.get("type", "unknown")
            name = (
                data.get("name") or data.get("login")
                or data.get("full_name", node_id)
            )
            nodes.append({
                "id": node_id,
                "type": ntype,
                "name": name,
                "label": f"{name} ({type_labels.get(ntype, ntype)})"
            })
        nodes.sort(key=lambda n: (n["name"] or "").lower())
        return nodes

    # ========================================================================
    # FULL ANALYSIS - Runs everything and returns combined result
    # ========================================================================

    def get_full_analysis(self, users_collection=None, repos_collection=None):
        """
        Run ALL analyses and return combined results.
        This is what the /collaboration/network-metrics endpoint returns.
        
        Args:
            users_collection: Optional pymongo collection for discipline classification
            repos_collection: Optional pymongo collection for discipline classification
        """
        logger.info("[NetworkAnalyzer] Computing full network analysis...")

        centrality = self.compute_centrality()
        collab_scores = self.compute_collaboration_scores()
        communities, node_community = self.detect_communities()
        bus_factors = self.compute_bus_factor()
        intensity = self.compute_collaboration_intensity()
        global_metrics = self.compute_global_metrics()
        searchable = self.get_searchable_nodes()

        # Discipline classification (requires MongoDB collections)
        node_disciplines = {}
        discipline_analysis = None
        if users_collection is not None and repos_collection is not None:
            try:
                from .discipline_classifier import classify_all_users
                node_disciplines, discipline_analysis = classify_all_users(
                    self.G, users_collection, repos_collection
                )
                logger.info(
                    f"[NetworkAnalyzer] Discipline classification: "
                    f"{len(node_disciplines)} users classified"
                )
            except Exception as e:
                logger.error(f"[NetworkAnalyzer] Discipline classification failed: {e}", exc_info=True)
                node_disciplines = {}
                discipline_analysis = None

        # Merge per-node metrics into a single dict
        node_metrics = {}
        for node_id in self.G.nodes:
            node_data = self.G.nodes[node_id]
            metrics = {
                **centrality.get(node_id, {}),
                **collab_scores.get(node_id, {}),
                **node_community.get(node_id, {}),
            }
            # Add bus factor for repos
            if node_data.get("type") == "repo":
                bf = bus_factors.get(node_id, {})
                metrics["bus_factor"] = bf.get("bus_factor", 0)
                metrics["bus_factor_risk"] = bf.get("risk", "unknown")
                metrics["top_contributors"] = bf.get("top_contributors", [])
                metrics["total_contributors"] = bf.get("total_contributors", 0)

            # Add discipline for users
            if node_id in node_disciplines:
                metrics.update(node_disciplines[node_id])

            node_metrics[node_id] = metrics

        # Compute modularity from communities
        modularity = 0
        if communities:
            try:
                community_sets = []
                for c in communities:
                    members = [
                        m for m in self.G.nodes
                        if node_community.get(m, {}).get("community_id") == c["id"]
                    ]
                    if members:
                        community_sets.append(set(members))
                if community_sets:
                    modularity = round(
                        nx.community.modularity(self.G, community_sets), 4
                    )
            except Exception:
                pass

        global_metrics["modularity"] = modularity
        global_metrics["num_communities"] = len(communities)

        result = {
            "node_metrics": node_metrics,
            "edge_metrics": intensity,
            "communities": communities,
            "bus_factors": bus_factors,
            "global_metrics": global_metrics,
            "searchable_nodes": searchable
        }

        # Add discipline analysis if available
        if discipline_analysis:
            result["discipline_analysis"] = discipline_analysis

        logger.info(
            f"[NetworkAnalyzer] Analysis complete: "
            f"{len(node_metrics)} nodes, {len(communities)} communities, "
            f"{len(bus_factors)} repos, modularity={modularity}"
        )
        return result
