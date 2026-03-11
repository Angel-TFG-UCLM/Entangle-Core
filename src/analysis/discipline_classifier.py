"""
ENTANGLE Discipline Classifier
================================
Classifies users in the quantum computing ecosystem into disciplines
based on multi-signal heuristics: bio, top languages, organizations,
and repository topics/languages.

Disciplines:
  ◈ quantum_software   - SDK/framework developers (Qiskit, Cirq, PennyLane...)
  ◈ quantum_physics     - Theorists, physicists, simulators
  ◈ quantum_hardware    - Hardware engineers, QPU, trapped-ion, superconducting
  ◈ classical_tooling   - Classical SWE contributing to quantum ecosystem
  ◈ education_research  - Professors, researchers, tutorial authors

The classifier runs at analysis time (not ingestion) by cross-referencing
user metadata with the repos they contribute to.  Results are injected
into network_metrics so the frontend can render the "Disciplines" lens
and the interdisciplinary collaboration charts.
"""

import re
import logging
from collections import defaultdict
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# ============================================================================
# DISCIPLINE DEFINITIONS
# ============================================================================

DISCIPLINES = [
    "quantum_software",
    "quantum_physics",
    "quantum_hardware",
    "classical_tooling",
    "education_research",
    "multidisciplinary",
]

DISCIPLINE_COLORS = {
    "quantum_software":  "#6c5ce7",   # Morado
    "quantum_physics":   "#00b4d8",   # Azul
    "quantum_hardware":  "#ff6b6b",   # Rojo
    "classical_tooling": "#ffd166",   # Amarillo
    "education_research":"#00ff9f",   # Verde
    "multidisciplinary": "#e0e0ff",   # Blanco iridiscente (transiciona entre colores en frontend)
}

DISCIPLINE_LABELS = {
    "quantum_software":  "Quantum Software",
    "quantum_physics":   "Quantum Physics",
    "quantum_hardware":  "Quantum Hardware",
    "classical_tooling": "Classical Tooling",
    "education_research":"Education & Research",
    "multidisciplinary": "Multidisciplinar",
}

# ============================================================================
# SIGNAL KEYWORDS
# ============================================================================

# ── Bio keywords (case-insensitive) ──
_BIO_SIGNALS = {
    "quantum_software": [
        "software engineer", "software developer", "backend engineer",
        "full.?stack", "devops", "swe", "sdk developer",
        "quantum developer", "quantum programmer", "quantum software",
        "open.?source developer", "platform engineer",
    ],
    "quantum_physics": [
        "physicist", "physics", "phd", "postdoc", "theoretical",
        "quantum mechanics", "quantum theory", "quantum information",
        "condensed matter", "many.?body", "quantum field theory",
        "quantum optics", "atomic physics", "molecular physics",
        "quantum scientist", "research scientist",
    ],
    "quantum_hardware": [
        "hardware engineer", "experimental", "cryogenic",
        "superconducting", "trapped.?ion", "photonic",
        "fabrication", "quantum device", "quantum processor",
        "quantum hardware", "control electronics", "fpga",
        "microwave", "rf engineer", "quantum engineer",
    ],
    "education_research": [
        "professor", "lecturer", "teacher", "instructor",
        "educator", "academic", "university", "faculty",
        "researcher", "research group", "research lab",
        "phd student", "phd candidate", "doctoral",
        "master student", "graduate student",
    ],
    # classical_tooling has NO strong bio signals — it's the fallback
}

# ── Organization signals ──
_ORG_SIGNALS = {
    "quantum_software": [
        "qiskit", "cirq", "pennylane", "xanadu", "zapata",
        "unitary", "tket", "cambridge quantum", "quantinuum",
        "strangeworks", "classiq", "1qbit",
    ],
    "quantum_physics": [
        "cern", "fermilab", "max.?planck", "mit", "caltech",
        "oxford", "cambridge", "eth zurich", "perimeter institute",
        "los alamos", "argonne", "brookhaven", "optics",
    ],
    "quantum_hardware": [
        "ionq", "rigetti", "ibm quantum", "google quantum",
        "d.?wave", "pasqal", "iqm", "alice.?bob",
        "quantum motion", "psi quantum", "quera",
        "atom computing", "infleqtion", "coldquanta",
    ],
    "education_research": [
        "qworld", "quantum open source foundation",
        "qosf", "teach me quantum", "quantum computing uk",
    ],
}

# ── Repository topic signals ──
_TOPIC_SIGNALS = {
    "quantum_software": [
        "quantum-circuit", "quantum-gate", "openqasm", "qasm",
        "quantum-sdk", "quantum-compiler", "quantum-programming",
        "transpiler", "quantum-assembly", "quantum-runtime",
        "quantum-software", "circuit-optimization", "pulse-schedule",
        "quantum-api", "quantum-cloud",
    ],
    "quantum_physics": [
        "hamiltonian", "quantum-simulation", "many-body",
        "quantum-chemistry", "density-functional", "tensor-network",
        "quantum-field-theory", "quantum-optics", "quantum-state",
        "wave-function", "variational", "vqe", "qaoa",
        "quantum-spin", "lattice-gauge", "condensed-matter",
        "quantum-dynamics", "schrodinger", "quantum-walk",
    ],
    "quantum_hardware": [
        "trapped-ion", "superconducting", "transmon",
        "quantum-hardware", "quantum-processor", "qpu",
        "quantum-control", "quantum-error-correction", "qec",
        "fault-tolerant", "surface-code", "quantum-noise",
        "quantum-tomography", "quantum-device", "cryogenics",
        "photonic-quantum", "quantum-dot",
    ],
    "education_research": [
        "tutorial", "course", "education", "learn",
        "teaching", "textbook", "lecture", "workshop",
        "quantum-education", "quantum-tutorial",
        "quantum-learning", "exercises",
    ],
}

# ── Language signals (which langs hint at which discipline) ──
_LANGUAGE_WEIGHTS = {
    "quantum_physics": {
        "Julia": 3.0, "Fortran": 4.0, "Mathematica": 3.0,
        "R": 1.5, "MATLAB": 2.5, "Jupyter Notebook": 1.5,
    },
    "quantum_hardware": {
        "Verilog": 4.0, "VHDL": 4.0, "SystemVerilog": 4.0,
        "C": 2.0, "C++": 1.5, "Assembly": 3.0,
    },
    "classical_tooling": {
        "TypeScript": 2.5, "JavaScript": 2.0, "Go": 2.5,
        "Rust": 2.0, "Java": 2.0, "C#": 2.0,
        "Kotlin": 2.5, "Swift": 2.5, "Dart": 2.5,
        "Ruby": 2.5, "PHP": 2.5,
    },
    # Python is ubiquitous — no signal value
}


# ============================================================================
# CLASSIFIER
# ============================================================================

def classify_user(
    user_doc: Dict[str, Any],
    user_repo_topics: List[List[str]],
    user_repo_languages: List[Optional[str]],
) -> Dict[str, Any]:
    """
    Classify a single user into a discipline.

    Args:
        user_doc: User document from MongoDB (bio, company, top_languages,
                  organizations, quantum_expertise_score, etc.)
        user_repo_topics: List of topic-lists from repos this user contributes to
        user_repo_languages: List of primary_language strings from those repos

    Returns:
        {
            "discipline": str,
            "discipline_color": str,
            "discipline_label": str,
            "discipline_confidence": float,  # 0..1
            "discipline_signals": [str, ...]
        }
    """
    scores: Dict[str, float] = {d: 0.0 for d in DISCIPLINES}
    signals: Dict[str, List[str]] = {d: [] for d in DISCIPLINES}

    bio = (user_doc.get("bio") or "").lower()
    company = (user_doc.get("company") or "").lower()
    top_languages = user_doc.get("top_languages") or []
    orgs = user_doc.get("organizations") or []
    quantum_score = user_doc.get("quantum_expertise_score") or 0

    # ── Signal 1: Bio analysis (high weight) ──
    for disc, patterns in _BIO_SIGNALS.items():
        for pattern in patterns:
            if re.search(pattern, bio, re.IGNORECASE):
                scores[disc] += 5.0
                signals[disc].append(f"bio: '{pattern}'")
                break  # One match per discipline in bio is enough

    # Also check company field with org signals
    for disc, patterns in _ORG_SIGNALS.items():
        for pattern in patterns:
            if re.search(pattern, company, re.IGNORECASE):
                scores[disc] += 3.0
                signals[disc].append(f"company: '{pattern}'")
                break

    # ── Signal 2: Organization affiliations (medium weight) ──
    org_text = " ".join(
        ((o.get("login") or "") + " " + (o.get("name") or "") + " " + (o.get("description") or ""))
        for o in orgs
    ).lower()
    for disc, patterns in _ORG_SIGNALS.items():
        matched = 0
        for pattern in patterns:
            if re.search(pattern, org_text, re.IGNORECASE):
                matched += 1
        if matched:
            scores[disc] += matched * 3.0
            signals[disc].append(f"orgs: {matched} matches")

    # ── Signal 3: Repository topics (high weight, aggregated) ──
    all_topics = set()
    for topics in user_repo_topics:
        if topics:
            all_topics.update(t.lower() for t in topics)

    for disc, topic_keywords in _TOPIC_SIGNALS.items():
        matched_topics = [t for t in topic_keywords if t in all_topics]
        if matched_topics:
            scores[disc] += len(matched_topics) * 2.0
            signals[disc].append(f"topics: {', '.join(matched_topics[:3])}")

    # ── Signal 4: Languages (low-medium weight) ──
    # From user's top_languages
    for disc, lang_weights in _LANGUAGE_WEIGHTS.items():
        for lang in top_languages:
            w = lang_weights.get(lang, 0)
            if w > 0:
                scores[disc] += w
                signals[disc].append(f"lang: {lang}")

    # From repos' primary languages (lower weight — indirect signal)
    repo_lang_counts: Dict[str, int] = defaultdict(int)
    for lang in user_repo_languages:
        if lang:
            repo_lang_counts[lang] += 1
    for disc, lang_weights in _LANGUAGE_WEIGHTS.items():
        for lang, count in repo_lang_counts.items():
            w = lang_weights.get(lang, 0)
            if w > 0:
                scores[disc] += w * 0.5 * min(count, 3)  # Cap at 3 repos

    # ── Signal 5: Quantum expertise score modifier ──
    # High quantum score → boost quantum_software if no other strong signal
    if quantum_score and quantum_score > 30:
        scores["quantum_software"] += quantum_score * 0.05
        # But don't add as explicit signal (it's indirect)

    # ── Determine winner ──
    total = sum(scores.values())
    if total == 0:
        # No signals at all → classical_tooling (default for ecosystem participants)
        return {
            "discipline": "classical_tooling",
            "discipline_color": DISCIPLINE_COLORS["classical_tooling"],
            "discipline_label": DISCIPLINE_LABELS["classical_tooling"],
            "discipline_confidence": 0.0,
            "discipline_signals": [],
        }

    # Check for multidisciplinary profile: 2+ disciplines with meaningful scores
    # where no single discipline clearly dominates
    significant = sorted(
        [(d, s) for d, s in scores.items() if d != "multidisciplinary" and s >= 1.5],
        key=lambda x: x[1], reverse=True,
    )
    if len(significant) >= 2:
        top_score = significant[0][1]
        second_score = significant[1][1]
        # Second discipline has ≥ 35% of top → spread is wide enough
        if second_score / top_score >= 0.35:
            # Multidisciplinary user!
            # Confidence = how evenly spread (higher = more balanced)
            top2_sum = top_score + second_score
            balance = second_score / top_score  # 0.35..1.0
            confidence = min(0.4 + balance * 0.6, 1.0)  # 0.61..1.0
            # Collect the top discipline colors for frontend cycling
            top_colors = [
                {
                    "discipline": d,
                    "color": DISCIPLINE_COLORS[d],
                    "label": DISCIPLINE_LABELS[d],
                    "score_pct": round(s / total * 100, 1),
                }
                for d, s in significant[:4]  # Up to 4 disciplines
            ]
            all_signals = []
            for d, _ in significant[:4]:
                all_signals.extend(signals.get(d, [])[:2])
            return {
                "discipline": "multidisciplinary",
                "discipline_color": DISCIPLINE_COLORS["multidisciplinary"],
                "discipline_label": DISCIPLINE_LABELS["multidisciplinary"],
                "discipline_confidence": round(confidence, 2),
                "discipline_signals": all_signals[:6],
                "discipline_top_colors": top_colors,
            }

    best_disc = max(
        [(d, s) for d, s in scores.items() if d != "multidisciplinary"],
        key=lambda x: x[1],
    )
    best_disc, best_score = best_disc
    confidence = min(best_score / max(total, 1), 1.0)

    # If confidence is very low (< 0.25) and best score < 3, classify as classical_tooling
    if confidence < 0.25 and best_score < 3.0:
        best_disc = "classical_tooling"
        confidence = 1.0 - (total / 20.0)  # Higher total → lower confidence in default
        confidence = max(0.1, min(confidence, 0.5))

    return {
        "discipline": best_disc,
        "discipline_color": DISCIPLINE_COLORS[best_disc],
        "discipline_label": DISCIPLINE_LABELS[best_disc],
        "discipline_confidence": round(confidence, 2),
        "discipline_signals": signals.get(best_disc, [])[:5],
    }


# ============================================================================
# BATCH CLASSIFIER — works with the graph + MongoDB
# ============================================================================

def classify_all_users(
    graph,
    users_collection,
    repos_collection,
) -> Tuple[Dict[str, Dict], Dict[str, Any]]:
    """
    Classify all user nodes in the graph by discipline.

    Reads additional metadata from MongoDB (bio, organizations, top_languages)
    and cross-references each user's contributed repos (from the graph edges)
    with repo metadata (topics, primary_language).

    Args:
        graph: NetworkX graph with user_, repo_, org_ nodes
        users_collection: pymongo collection for users
        repos_collection: pymongo collection for repositories

    Returns:
        (node_disciplines, discipline_analysis)

        node_disciplines: { "user_login": { discipline, color, confidence, signals } }
        discipline_analysis: {
            "distribution": { disc: count },
            "distribution_pct": { disc: pct },
            "mixing_matrix": { disc_a: { disc_b: edge_count } },
            "cross_discipline_index": float,
            "bridge_profiles": [ { login, disciplines, repos_per_disc, confidence } ],
        }
    """
    # ── 1. Gather all user logins in graph ──
    user_nodes = [
        n for n in graph.nodes
        if graph.nodes[n].get("type") == "user"
        and not graph.nodes[n].get("is_bot", False)
    ]
    user_logins = [n.replace("user_", "", 1) for n in user_nodes]

    if not user_logins:
        return {}, _empty_analysis()

    logger.info(f"[DisciplineClassifier] Classifying {len(user_logins)} users...")

    # ── 2. Bulk-load user metadata from MongoDB ──
    user_docs = {}
    for doc in users_collection.find(
        {"login": {"$in": user_logins}},
        {
            "_id": 0, "login": 1, "bio": 1, "company": 1,
            "top_languages": 1, "organizations": 1,
            "quantum_expertise_score": 1,
        }
    ):
        user_docs[doc["login"]] = doc

    # ── 3. Bulk-load repo metadata (topics, primary_language) ──
    # Get all repo full_names from graph
    repo_nodes = [
        n for n in graph.nodes
        if graph.nodes[n].get("type") == "repo"
    ]
    repo_full_names = [n.replace("repo_", "", 1) for n in repo_nodes]

    repo_meta = {}
    if repo_full_names:
        for doc in repos_collection.find(
            {"full_name": {"$in": repo_full_names}},
            {
                "_id": 0, "full_name": 1,
                "repository_topics": 1, "topics": 1,
                "primary_language": 1, "description": 1,
            }
        ):
            fn = doc["full_name"]
            # Topics: try repository_topics first, fallback to topics
            topics = doc.get("repository_topics") or doc.get("topics") or []
            lang = doc.get("primary_language")
            if isinstance(lang, dict):
                lang = lang.get("name")
            repo_meta[fn] = {"topics": topics, "language": lang, "description": doc.get("description", "")}

    # ── 4. Build user → repos mapping from graph edges ──
    user_repos_map: Dict[str, List[str]] = defaultdict(list)
    for u, v, data in graph.edges(data=True):
        if data.get("type") == "contributed_to":
            login = u.replace("user_", "", 1)
            full_name = v.replace("repo_", "", 1)
            user_repos_map[login].append(full_name)

    # ── 5. Classify each user ──
    node_disciplines: Dict[str, Dict] = {}
    discipline_counts: Dict[str, int] = {d: 0 for d in DISCIPLINES}

    for login in user_logins:
        user_doc = user_docs.get(login, {"login": login})
        repos = user_repos_map.get(login, [])

        # Gather repo topics and languages
        repo_topics = []
        repo_languages = []
        for fn in repos:
            meta = repo_meta.get(fn, {})
            repo_topics.append(meta.get("topics", []))
            repo_languages.append(meta.get("language"))

        result = classify_user(user_doc, repo_topics, repo_languages)
        node_id = f"user_{login}"
        node_disciplines[node_id] = result
        discipline_counts[result["discipline"]] += 1

    # ── 6. Compute discipline analysis metrics ──
    total_classified = sum(discipline_counts.values())
    distribution_pct = {
        d: round(c / max(total_classified, 1) * 100, 1)
        for d, c in discipline_counts.items()
    }

    # Mixing matrix: count edges between disciplines
    # Optimized O(R × D²): for each repo, count contributors per discipline,
    # then compute pairwise counts arithmetically instead of iterating C² pairs.
    # D=5 disciplines, so inner loop is only 5×5=25 iterations per repo.
    mixing_matrix = {d: {d2: 0 for d2 in DISCIPLINES} for d in DISCIPLINES}
    cross_edges = 0
    total_edges = 0

    # Build repo → discipline counts (not individual contributors)
    repo_disc_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: {d: 0 for d in DISCIPLINES})
    for login in user_logins:
        node_id = f"user_{login}"
        disc = node_disciplines.get(node_id, {}).get("discipline")
        if not disc:
            continue
        for fn in user_repos_map.get(login, []):
            repo_disc_counts[fn][disc] += 1

    # For each repo, compute discipline pair counts arithmetically
    for fn, disc_counts in repo_disc_counts.items():
        total_in_repo = sum(disc_counts.values())
        if total_in_repo < 2:
            continue
        disc_list = DISCIPLINES  # Fixed order
        for i, d_i in enumerate(disc_list):
            c_i = disc_counts[d_i]
            if c_i == 0:
                continue
            # Same-discipline pairs: C(c_i, 2)
            same_pairs = c_i * (c_i - 1) // 2
            mixing_matrix[d_i][d_i] += same_pairs
            total_edges += same_pairs
            # Cross-discipline pairs
            for j in range(i + 1, len(disc_list)):
                d_j = disc_list[j]
                c_j = disc_counts[d_j]
                if c_j == 0:
                    continue
                cross_pairs = c_i * c_j
                mixing_matrix[d_i][d_j] += cross_pairs
                mixing_matrix[d_j][d_i] += cross_pairs
                total_edges += cross_pairs
                cross_edges += cross_pairs

    cross_discipline_index = round(
        cross_edges / max(total_edges, 1) * 100, 1
    )

    # Bridge profiles: users contributing to repos across ≥2 disciplines
    bridge_profiles = _find_bridge_profiles(
        user_logins, user_repos_map, repo_meta, node_disciplines
    )

    analysis = {
        "distribution": discipline_counts,
        "distribution_pct": distribution_pct,
        "mixing_matrix": mixing_matrix,
        "cross_discipline_index": cross_discipline_index,
        "total_classified": total_classified,
        "bridge_profiles": bridge_profiles[:20],  # Top 20
        "discipline_colors": DISCIPLINE_COLORS,
        "discipline_labels": DISCIPLINE_LABELS,
    }

    logger.info(
        f"[DisciplineClassifier] Classification complete: "
        f"{total_classified} users classified, "
        f"cross-discipline index={cross_discipline_index}%, "
        f"{len(bridge_profiles)} bridge profiles found"
    )
    for d in DISCIPLINES:
        logger.info(f"  {DISCIPLINE_LABELS[d]}: {discipline_counts[d]} ({distribution_pct[d]}%)")

    return node_disciplines, analysis


def _find_bridge_profiles(
    user_logins: List[str],
    user_repos_map: Dict[str, List[str]],
    repo_meta: Dict[str, Dict],
    node_disciplines: Dict[str, Dict],
) -> List[Dict[str, Any]]:
    """
    Find users who span multiple disciplines through their repo contributions.
    A bridge user contributes to repos whose *contributors* come from ≥2 disciplines.
    """
    bridges = []

    for login in user_logins:
        node_id = f"user_{login}"
        user_disc_info = node_disciplines.get(node_id, {})
        user_disc = user_disc_info.get("discipline", "classical_tooling")

        repos = user_repos_map.get(login, [])
        if len(repos) < 2:
            continue

        # Classify repos by their dominant topic discipline
        repo_disc_set = set()
        repos_per_disc: Dict[str, int] = defaultdict(int)

        for fn in repos:
            meta = repo_meta.get(fn, {})
            topics = meta.get("topics", [])
            topic_text = " ".join(t.lower() for t in topics)
            desc = (meta.get("description") or "").lower()
            combined = topic_text + " " + desc

            # Quick repo-discipline classification
            repo_disc = _classify_repo_discipline(combined, meta.get("language"))
            repo_disc_set.add(repo_disc)
            repos_per_disc[repo_disc] += 1

        if len(repo_disc_set) >= 2:
            bridges.append({
                "login": login,
                "discipline": user_disc,
                "discipline_label": DISCIPLINE_LABELS.get(user_disc, user_disc),
                "discipline_color": DISCIPLINE_COLORS.get(user_disc, "#888"),
                "disciplines_spanned": len(repo_disc_set),
                "repos_per_discipline": dict(repos_per_disc),
                "total_repos": len(repos),
                "confidence": user_disc_info.get("discipline_confidence", 0),
            })

    # Sort by number of disciplines spanned (desc), then total repos (desc)
    bridges.sort(key=lambda b: (b["disciplines_spanned"], b["total_repos"]), reverse=True)
    return bridges


def _classify_repo_discipline(text: str, language: Optional[str]) -> str:
    """Quick discipline classification for a repo based on topics+description text."""
    scores = {d: 0 for d in DISCIPLINES}

    for disc, keywords in _TOPIC_SIGNALS.items():
        for kw in keywords:
            if kw in text:
                scores[disc] += 1

    # Language hint
    if language:
        for disc, lang_weights in _LANGUAGE_WEIGHTS.items():
            if language in lang_weights:
                scores[disc] += 1

    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "quantum_software"  # Default for repos in quantum ecosystem
    return best


def _empty_analysis() -> Dict[str, Any]:
    """Return empty analysis structure."""
    return {
        "distribution": {d: 0 for d in DISCIPLINES},
        "distribution_pct": {d: 0.0 for d in DISCIPLINES},
        "mixing_matrix": {d: {d2: 0 for d2 in DISCIPLINES} for d in DISCIPLINES},
        "cross_discipline_index": 0.0,
        "total_classified": 0,
        "bridge_profiles": [],
        "discipline_colors": DISCIPLINE_COLORS,
        "discipline_labels": DISCIPLINE_LABELS,
    }
