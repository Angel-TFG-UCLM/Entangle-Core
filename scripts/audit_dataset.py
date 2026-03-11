"""
AUDITORÍA EXHAUSTIVA del dataset quantum_github.
Categoriza TODOS los repos que no encajan en computación cuántica.
"""
import json
import re
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict
from pymongo import MongoClient

client = MongoClient("localhost", 27017)
db = client["quantum_github"]

with open("config/ingestion_config.json") as f:
    config = json.load(f)

MAX_INACTIVITY_DAYS = config["max_inactivity_days"]
cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_INACTIVITY_DAYS)

# ============================================================================
# CATEGORÍAS DE FALSOS POSITIVOS
# ============================================================================

# 1. QuantumultX: app de proxy/VPN para iOS, nada que ver con QC
QUANTUMULTX_PATTERN = re.compile(r"quantumult", re.IGNORECASE)

# 2. Firefox Quantum: motor de renderizado de Mozilla
FIREFOX_PATTERN = re.compile(r"firefox.*(quantum|color|css|vim|legacy|hackbar)|quantum.*(firefox|nox|vim)", re.IGNORECASE)

# 3. Post-Quantum Cryptography: legítimo en criptografía pero NO es quantum computing/software
# Estos repos implementan algoritmos clásicos resistentes a ataques cuánticos
PQC_KEYWORDS = [
    "post-quantum", "post quantum", "pqc", "lattice-based", "ntru",
    "kyber", "dilithium", "sphincs", "falcon", "newhope",
    "quantum-resistant", "quantum resistant", "quantum-safe", "quantum safe",
    "hash-based signature", "hashsigs",
]

# 4. Keywords que confirman que SÍ es quantum computing/software real
REAL_QC_KEYWORDS = [
    # Frameworks/SDKs
    "qiskit", "cirq", "pennylane", "braket", "pyquil", "projectq", "qulacs",
    "tequila", "strawberry fields", "ocean", "dwave", "d-wave", "openqasm", "qasm",
    "cuda-q", "cuda quantum", "quest", "qsharp", "q#",
    # Conceptos core de QC
    "qubit", "quantum circuit", "quantum gate", "quantum computing",
    "quantum algorithm", "quantum error correction", "quantum error",
    "quantum simulation", "quantum simulator", "quantum machine learning",
    "quantum chemistry", "quantum processor", "quantum computer",
    "quantum programming", "quantum software", "quantum hardware",
    "quantum compiler", "quantum debugger", "quantum assembler",
    # Algoritmos QC
    "vqe", "qaoa", "grover", "shor algorithm", "quantum fourier",
    "quantum walk", "quantum annealing", "variational quantum",
    "quantum approximate optimization",
    # Conceptos físicos directamente usados en QC
    "superposition", "entanglement", "decoherence", "quantum noise",
    "quantum state", "density matrix", "bloch sphere", "bell state",
    "quantum teleportation", "quantum key distribution", "qkd",
    "nisq", "fault-tolerant quantum", "topological quantum",
    "quantum advantage", "quantum supremacy",
    # Física cuántica / simulación cuántica (legítimo)
    "quantum optics", "quantum mechanics simulation", "quantum dynamics",
    "quantum monte carlo", "quantum many-body", "quantum field theory",
    "quantum espresso",  # DFT software
    "hamiltonian simulation", "schrodinger", "schrödinger",
    "wave function", "wavefunction",
    "tensor network", "matrix product state",
    "quantum information", "quantum channel", "quantum tomography",
    "quantum control", "quantum sensing",
    # Hardware
    "trapped ion", "superconducting qubit", "photonic quantum",
    "neutral atom", "quantum dot",
    # Organizaciones QC conocidas
    "ibm quantum", "google quantum", "rigetti", "ionq",
    "xanadu", "zapata", "pasqal", "quantinuum",
    "azure quantum", "aws quantum",
    # Educación QC
    "quantum computing course", "quantum computing book",
    "quantum computing tutorial", "learn quantum computing",
]

# 5. Repos conocidos que son CLARAMENTE no-QC
KNOWN_NON_QC = {
    "bloomberg/quantum": "C++ coroutine/parallel library",
    "nashvail/Quttons": "CSS quantum paper buttons",
    "atilafassina/quantum": "Tauri+SolidStart app template",
    "rodyherrera/Quantum": "Self-hosted Vercel/Heroku alternative",
    "RafaelGoulartB/next-ecommerce": "Next.js e-commerce template 'Quantum'",
    "quantumui/quantumui": "AngularJS UI component library",
    "joaomilho/Enterprise": "Joke programming language",
    "sahibzada-allahyar/YC-Killer": "AI agents library (no QC)",
    "nicklashansen/tdmpc2": "TD-MPC2 reinforcement learning",
    "foxyproxy/firefox-extension": "Firefox proxy extension",
}


def get_searchable_text(repo):
    """Extract all searchable text from a repo document."""
    name = (repo.get("name") or "").lower()
    desc = (repo.get("description") or "").lower()
    topics = []
    for t in (repo.get("repository_topics") or []):
        if isinstance(t, dict):
            topics.append(t.get("name", "").lower())
        else:
            topics.append(str(t).lower())
    readme = (repo.get("readme_text") or "")[:1000].lower()
    # Normalize separators
    all_text = f"{name} {desc} {' '.join(topics)} {readme}"
    return all_text.replace("-", " ").replace("_", " ")


def has_real_qc_content(text):
    """Check if text has genuine quantum computing keywords."""
    for kw in REAL_QC_KEYWORDS:
        if kw.lower() in text:
            return True
    return False


def is_pqc_only(text):
    """Check if repo is ONLY about post-quantum crypto (no actual QC)."""
    has_pqc = any(kw in text for kw in PQC_KEYWORDS)
    has_qc = has_real_qc_content(text)
    return has_pqc and not has_qc


def classify_repo(repo):
    """
    Classify a repo into categories.
    Returns: (category, detail)
    - "clean" = legit QC repo
    - "quantumultx" = QuantumultX proxy app
    - "firefox" = Firefox Quantum
    - "pqc_only" = Post-quantum crypto only
    - "known_non_qc" = Known non-QC repos
    - "suspect_no_qc_keywords" = Has "quantum" but no specific QC keywords
    - "inactive" = Last push > 365 days ago (secondary issue)
    """
    fn = repo.get("full_name") or ""
    name = (repo.get("name") or "").lower()
    desc = (repo.get("description") or "").lower()
    text = get_searchable_text(repo)
    
    # Check known non-QC
    if fn in KNOWN_NON_QC:
        return "known_non_qc", KNOWN_NON_QC[fn]
    
    # Check QuantumultX
    if QUANTUMULTX_PATTERN.search(f"{name} {desc} {fn}"):
        return "quantumultx", "iOS proxy app"
    
    # Check Firefox Quantum
    name_desc = f"{fn} {name} {desc}"
    if FIREFOX_PATTERN.search(name_desc):
        return "firefox_quantum", "Firefox browser"
    if "firefox" in name_desc.lower() and "quantum" not in desc.replace("firefox quantum", "").replace("quantum css", ""):
        return "firefox_quantum", "Firefox browser"
    
    # Check PQC-only
    if is_pqc_only(text):
        return "pqc_only", "Post-quantum crypto (no QC)"
    
    # Check if it has any real QC content
    if not has_real_qc_content(text):
        return "suspect_no_qc_keywords", "No specific QC keywords found"
    
    return "clean", None


def check_inactive(repo):
    """Check if repo is inactive (pushed > MAX_INACTIVITY_DAYS ago)."""
    pushed = repo.get("pushed_at")
    last_commit = repo.get("last_commit_date")
    
    for date_val in [pushed, last_commit]:
        if date_val is None:
            continue
        if isinstance(date_val, str):
            try:
                date_val = datetime.fromisoformat(date_val.replace("Z", "+00:00"))
            except Exception:
                continue
        if isinstance(date_val, datetime):
            if date_val.tzinfo is None:
                date_val = date_val.replace(tzinfo=timezone.utc)
            if date_val > cutoff:
                return False
    return True


# ============================================================================
# RUN AUDIT
# ============================================================================

results = defaultdict(list)
inactive_by_category = defaultdict(int)
total = 0
total_stars = 0

for repo in db.repositories.find():
    total += 1
    fn = repo.get("full_name") or "?"
    stars = repo.get("stargazer_count", 0) or 0
    total_stars += stars
    desc = (repo.get("description") or "")[:120]
    lang = repo.get("primary_language") or "?"
    
    category, detail = classify_repo(repo)
    inactive = check_inactive(repo)
    
    results[category].append({
        "full_name": fn,
        "stars": stars,
        "description": desc,
        "language": lang,
        "detail": detail,
        "inactive": inactive,
    })
    
    if inactive:
        inactive_by_category[category] += 1

# ============================================================================
# PRINT REPORT
# ============================================================================

print("=" * 80)
print("  AUDITORÍA EXHAUSTIVA DEL DATASET quantum_github")
print(f"  Total repos: {total} | Total estrellas: {total_stars:,}")
print(f"  Fecha de corte inactividad: {cutoff.strftime('%Y-%m-%d')} ({MAX_INACTIVITY_DAYS} días)")
print("=" * 80)

# Summary table
print("\n┌─────────────────────────────────┬───────┬──────────┬───────────┐")
print("│ Categoría                       │ Repos │ Estrellas│ Inactivos │")
print("├─────────────────────────────────┼───────┼──────────┼───────────┤")

categories_order = [
    ("clean", "QC Legítimo"),
    ("quantumultx", "QuantumultX (proxy iOS)"),
    ("firefox_quantum", "Firefox Quantum"),
    ("known_non_qc", "Non-QC conocido"),
    ("pqc_only", "Post-quantum crypto"),
    ("suspect_no_qc_keywords", "Sospechoso (sin keywords QC)"),
]

for cat_key, cat_label in categories_order:
    repos = results.get(cat_key, [])
    count = len(repos)
    cat_stars = sum(r["stars"] for r in repos)
    inactive_count = inactive_by_category.get(cat_key, 0)
    pct = count / total * 100 if total > 0 else 0
    print(f"│ {cat_label:<31s} │ {count:>5} │ {cat_stars:>8,} │ {inactive_count:>9} │")

print("├─────────────────────────────────┼───────┼──────────┼───────────┤")
non_clean = sum(len(v) for k, v in results.items() if k != "clean")
non_clean_stars = sum(sum(r["stars"] for r in v) for k, v in results.items() if k != "clean")
non_clean_inactive = sum(v for k, v in inactive_by_category.items() if k != "clean")
print(f"│ {'TOTAL NO-QC / PROBLEMÁTICOS':<31s} │ {non_clean:>5} │ {non_clean_stars:>8,} │ {non_clean_inactive:>9} │")
print("└─────────────────────────────────┴───────┴──────────┴───────────┘")

# Detail per category (non-clean)
for cat_key, cat_label in categories_order:
    if cat_key == "clean":
        continue
    repos = results.get(cat_key, [])
    if not repos:
        continue
    
    repos.sort(key=lambda x: -(x["stars"] or 0))
    cat_stars = sum(r["stars"] for r in repos)
    
    print(f"\n{'─' * 80}")
    print(f"  {cat_label.upper()} ({len(repos)} repos, {cat_stars:,} estrellas)")
    print(f"{'─' * 80}")
    
    show = min(25, len(repos))
    for r in repos[:show]:
        inactive_mark = " [INACTIVO]" if r["inactive"] else ""
        print(f"  {r['full_name']:55s} {r['stars']:>5}⭐ {r['language']:>12s}{inactive_mark}")
        if r["description"]:
            print(f"    └ {r['description'][:100]}")
    if len(repos) > show:
        remaining = repos[show:]
        remaining_stars = sum(r["stars"] for r in remaining)
        print(f"    ... y {len(remaining)} más ({remaining_stars:,} estrellas)")

# Clean repos stats
clean_repos = results.get("clean", [])
clean_inactive = sum(1 for r in clean_repos if r["inactive"])
clean_stars = sum(r["stars"] for r in clean_repos)
clean_inactive_stars = sum(r["stars"] for r in clean_repos if r["inactive"])

print(f"\n{'=' * 80}")
print(f"  REPOS QC LEGÍTIMOS: ANÁLISIS DE ACTIVIDAD")
print(f"{'=' * 80}")
print(f"  Total legítimos: {len(clean_repos)} repos ({clean_stars:,} estrellas)")
print(f"  Activos (< {MAX_INACTIVITY_DAYS} días): {len(clean_repos) - clean_inactive} repos ({clean_stars - clean_inactive_stars:,}⭐)")
print(f"  Inactivos (> {MAX_INACTIVITY_DAYS} días): {clean_inactive} repos ({clean_inactive_stars:,}⭐)")

# Inactive distribution
if clean_inactive > 0:
    years = Counter()
    for r in clean_repos:
        if r["inactive"]:
            fn = r["full_name"]
            repo_doc = db.repositories.find_one({"full_name": fn})
            if repo_doc:
                pushed = repo_doc.get("pushed_at")
                if isinstance(pushed, datetime):
                    years[pushed.year] += 1
                elif isinstance(pushed, str) and len(pushed) >= 4:
                    years[int(pushed[:4])] += 1
    
    print(f"\n  Distribución de inactivos legítimos por año de último push:")
    for y, c in sorted(years.items()):
        print(f"    {y}: {c} repos")

# Top 15 inactive QC repos by stars
print(f"\n  Top 15 repos QC legítimos INACTIVOS por estrellas:")
inactive_clean = sorted([r for r in clean_repos if r["inactive"]], key=lambda x: -x["stars"])
for r in inactive_clean[:15]:
    print(f"    {r['full_name']:55s} {r['stars']:>5}⭐")

# Language distribution of problematic repos
print(f"\n{'=' * 80}")
print(f"  DISTRIBUCIÓN DE LENGUAJES EN REPOS PROBLEMÁTICOS")
print(f"{'=' * 80}")
lang_counter = Counter()
for cat_key in ["quantumultx", "firefox_quantum", "known_non_qc", "suspect_no_qc_keywords"]:
    for r in results.get(cat_key, []):
        lang_counter[r["language"]] += 1

for lang, count in lang_counter.most_common(15):
    print(f"  {lang:20s}: {count}")

# FINAL SUMMARY
print(f"\n{'=' * 80}")
print(f"  RESUMEN EJECUTIVO")
print(f"{'=' * 80}")
print(f"""
  DATASET ACTUAL: {total} repos, {total_stars:,} estrellas

  FALSOS POSITIVOS CLAROS (eliminar): {sum(len(results.get(k, [])) for k in ['quantumultx', 'firefox_quantum', 'known_non_qc'])} repos
    - QuantumultX (proxy iOS):     {len(results.get('quantumultx', []))} repos ({sum(r['stars'] for r in results.get('quantumultx', [])):,}⭐)
    - Firefox Quantum:             {len(results.get('firefox_quantum', []))} repos ({sum(r['stars'] for r in results.get('firefox_quantum', [])):,}⭐)  
    - Non-QC conocidos:            {len(results.get('known_non_qc', []))} repos ({sum(r['stars'] for r in results.get('known_non_qc', [])):,}⭐)

  DEBATIBLES:
    - Post-quantum crypto:         {len(results.get('pqc_only', []))} repos ({sum(r['stars'] for r in results.get('pqc_only', [])):,}⭐)
    - Sin keywords QC específicas: {len(results.get('suspect_no_qc_keywords', []))} repos ({sum(r['stars'] for r in results.get('suspect_no_qc_keywords', [])):,}⭐)

  DATASET LIMPIO (si se eliminan FP claros): {total - sum(len(results.get(k, [])) for k in ['quantumultx', 'firefox_quantum', 'known_non_qc'])} repos
  ESTRELLAS LIMPIAS: {total_stars - sum(sum(r['stars'] for r in results.get(k, [])) for k in ['quantumultx', 'firefox_quantum', 'known_non_qc']):,}⭐
""")
