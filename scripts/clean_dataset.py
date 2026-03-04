"""
Script para limpiar el dataset quantum_github:
1. Eliminar 71 falsos positivos claros (QuantumultX, Firefox Quantum, Non-QC)
2. Analizar y clasificar los 224 repos sospechosos
3. Eliminar los sospechosos que no sean QC legítimo
"""
import sys
import os
import re
from datetime import datetime

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pymongo import MongoClient

# ─── Configuración ─────────────────────────────────────────────────
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "quantum_github"

# ─── Patrones de falsos positivos conocidos ─────────────────────────

# Blacklist: patrones que NUNCA son computación cuántica
NON_QC_PATTERNS = [
    r"quantumult",                      # Proxy iOS (QuantumultX)
    r"firefox[\s._-]*quantum",          # Firefox Quantum
    r"quantum[\s._-]*paper",            # CSS/UI Material Design
    r"quantum[\s._-]*ui",               # UI frameworks genéricos
    r"quantumui",                       # UI framework AngularJS
]

# Repos específicos conocidos como Non-QC (por nameWithOwner)
NON_QC_REPOS = [
    "sahibzada-allahyar/YC-Killer",     # AI agents enterprise
    "joaomilho/Enterprise",             # lenguaje satírico
    "nashvail/Quttons",                 # botones CSS
    "bloomberg/quantum",                # C++ coroutine dispatcher
    "foxyproxy/firefox-extension",      # extensión Firefox proxy
    "atilafassina/quantum",             # Tauri + SolidStart
    "RafaelGoulartB/next-ecommerce",    # Quantum Ecommerce Next.js
    "rodyherrera/Quantum",              # alternativa a Vercel/Heroku
    "quantumui/quantumui",              # UI framework AngularJS
]

# Keywords QC reales para validación de relevancia
REAL_QC_KEYWORDS = [
    # Frameworks
    "qiskit", "cirq", "pennylane", "braket", "pyquil", "projectq",
    "strawberry fields", "ocean sdk", "openqasm", "qasm", "quil",
    "tket", "pytket", "stim", "quirk",
    # Conceptos core
    "qubit", "qubits", "superposition", "entanglement", "decoherence",
    "quantum gate", "quantum circuit", "quantum state", "bloch sphere",
    "hamiltonian", "unitary", "hermitian", "density matrix",
    "wave function", "wavefunction", "quantum mechanics",
    "quantum physics", "quantum theory",
    # Algoritmos
    "grover", "shor", "vqe", "qaoa", "qft", "quantum fourier",
    "quantum walk", "quantum annealing", "adiabatic",
    "variational quantum", "quantum approximate",
    # Hardware
    "quantum processor", "quantum computer", "qpu", "nisq",
    "fault.tolerant", "topological quantum", "trapped.ion",
    "superconducting qubit", "transmon", "quantum hardware",
    # Campos
    "quantum machine learning", "quantum chemistry", "quantum simulation",
    "quantum error correction", "quantum key distribution", "qkd",
    "quantum teleportation", "quantum cryptography",
    "quantum information", "quantum computing",
    "quantum programming", "quantum software",
    "quantum neural network", "qnn",
    "quantum optics", "photonic quantum",
    # Proveedores
    "ibm quantum", "google quantum", "azure quantum", "aws quantum",
    "rigetti", "ionq", "d-wave", "xanadu", "zapata",
    # Post-quantum (mantener)
    "post-quantum", "post quantum", "pqc", "lattice-based",
    "code-based cryptography", "hash-based signature",
    # Otros QC
    "quantum spin", "many-body", "quantum field",
    "quantum dynamics", "quantum control",
    "quantum sensing", "quantum metrology",
    "quantum communication", "quantum network",
    "quantum internet", "quantum channel",
]


def get_searchable_text(repo):
    """Extrae texto buscable del repo."""
    parts = []
    parts.append(repo.get("name", "").lower())
    parts.append(repo.get("full_name", "").lower())
    parts.append((repo.get("description") or "").lower())
    
    # Topics
    topics = repo.get("topics", [])
    if isinstance(topics, list):
        parts.append(" ".join(t.lower() if isinstance(t, str) else "" for t in topics))
    
    # README (primeros 2000 chars)
    readme = repo.get("readme_content", "") or repo.get("readme", "") or ""
    if isinstance(readme, str):
        parts.append(readme[:2000].lower())
    
    return " ".join(parts)


def matches_blacklist(repo):
    """Verifica si un repo coincide con patrones de blacklist."""
    text = get_searchable_text(repo)
    name = repo.get("full_name", "").lower()
    
    # Verificar nameWithOwner contra lista de repos conocidos
    for known_fp in NON_QC_REPOS:
        if known_fp.lower() == name:
            return True, f"Non-QC conocido: {known_fp}"
    
    # Verificar patrones regex
    for pattern in NON_QC_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True, f"Patrón blacklist: {pattern}"
    
    return False, None


def has_qc_keywords(repo):
    """Verifica si el repo tiene keywords de QC real."""
    text = get_searchable_text(repo)
    found = []
    for kw in REAL_QC_KEYWORDS:
        pattern = kw.replace(".", r"[\s._-]?")  # Flexibilizar puntos
        if re.search(pattern, text, re.IGNORECASE):
            found.append(kw)
    return found


def classify_repo(repo):
    """
    Clasifica un repositorio.
    Returns: (category, reason, qc_keywords_found)
    """
    is_blacklisted, bl_reason = matches_blacklist(repo)
    if is_blacklisted:
        return "FALSE_POSITIVE", bl_reason, []
    
    qc_keywords = has_qc_keywords(repo)
    if qc_keywords:
        return "QC_LEGÍTIMO", f"Keywords QC: {', '.join(qc_keywords[:5])}", qc_keywords
    
    return "SOSPECHOSO", "Sin keywords QC específicas", []


def main():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    repos_collection = db["repositories"]
    
    total = repos_collection.count_documents({})
    print(f"\n{'='*80}")
    print(f"LIMPIEZA DEL DATASET quantum_github")
    print(f"{'='*80}")
    print(f"Total repos en BD: {total}")
    
    # ─── FASE 1: Identificar y eliminar FP claros ──────────────────
    print(f"\n{'─'*60}")
    print("FASE 1: Identificar Falsos Positivos Claros")
    print(f"{'─'*60}")
    
    all_repos = list(repos_collection.find({}))
    
    fps_to_delete = []
    suspicious = []
    legitimate = []
    
    for repo in all_repos:
        category, reason, qc_kws = classify_repo(repo)
        repo_info = {
            "full_name": repo.get("full_name", "unknown"),
            "stars": repo.get("stars", 0),
            "description": (repo.get("description") or "")[:80],
            "reason": reason,
            "qc_keywords": qc_kws,
            "_id": repo["_id"],
        }
        
        if category == "FALSE_POSITIVE":
            fps_to_delete.append(repo_info)
        elif category == "SOSPECHOSO":
            suspicious.append(repo_info)
        else:
            legitimate.append(repo_info)
    
    # Ordenar por estrellas
    fps_to_delete.sort(key=lambda x: x["stars"], reverse=True)
    suspicious.sort(key=lambda x: x["stars"], reverse=True)
    
    print(f"\n  QC Legítimo: {len(legitimate)} repos")
    print(f"  Falsos Positivos: {len(fps_to_delete)} repos")
    print(f"  Sospechosos: {len(suspicious)} repos")
    
    # Mostrar FPs
    print(f"\n  Falsos Positivos a ELIMINAR:")
    total_fp_stars = 0
    for fp in fps_to_delete:
        print(f"    ❌ {fp['full_name']} ({fp['stars']}⭐) — {fp['reason']}")
        total_fp_stars += fp["stars"]
    print(f"\n  Total FP: {len(fps_to_delete)} repos, {total_fp_stars:,} estrellas")
    
    # ─── FASE 2: Analizar Sospechosos ──────────────────────────────
    print(f"\n{'─'*60}")
    print("FASE 2: Analizar Sospechosos")
    print(f"{'─'*60}")
    
    print(f"\n  Total sospechosos: {len(suspicious)} repos")
    total_susp_stars = sum(s["stars"] for s in suspicious)
    print(f"  Total estrellas: {total_susp_stars:,}")
    
    # Mostrar los 30 más populares para revisión
    print(f"\n  Top 30 sospechosos por estrellas:")
    for i, s in enumerate(suspicious[:30], 1):
        print(f"    {i:2d}. {s['full_name']} ({s['stars']}⭐)")
        print(f"        Desc: {s['description']}")
    
    if len(suspicious) > 30:
        print(f"\n    ...y {len(suspicious) - 30} más")
    
    # ─── FASE 3: Eliminar FPs ─────────────────────────────────────
    print(f"\n{'─'*60}")
    print("FASE 3: Eliminar Falsos Positivos")
    print(f"{'─'*60}")
    
    if fps_to_delete:
        fp_ids = [fp["_id"] for fp in fps_to_delete]
        fp_names = [fp["full_name"] for fp in fps_to_delete]
        
        result = repos_collection.delete_many({"_id": {"$in": fp_ids}})
        print(f"\n  ✅ Eliminados {result.deleted_count} falsos positivos de 'repositories'")
        
        # También limpiar de users y organizations si hay referencias huérfanas
        # (no eliminamos users/orgs porque pueden tener otros repos legítimos)
        
        # Resumen final
        remaining = repos_collection.count_documents({})
        print(f"\n  Repos restantes en BD: {remaining}")
        print(f"  Reducción: {total} → {remaining} ({total - remaining} eliminados)")
    else:
        print("  No se encontraron falsos positivos para eliminar.")
    
    # ─── FASE 4: Eliminar los sospechosos que claramente no son QC ──
    # Estos son repos que:
    # - No tienen NINGUNA keyword QC
    # - Y cuyo contexto sugiere que 'quantum' es marca/nombre
    print(f"\n{'─'*60}")
    print("FASE 4: Filtrar Sospechosos No-QC")
    print(f"{'─'*60}")
    
    # Patrones adicionales que indican que no es QC
    SUSPICIOUS_NON_QC_PATTERNS = [
        r"minecraft",
        r"launcher",
        r"drum.machine",
        r"ecommerce|e-commerce",
        r"react.*quantum|quantum.*react",
        r"electron.*alternative",
        r"p2p.*protocol|protocol.*p2p",
        r"vpn|proxy",
        r"nsa|hackbar|quantuminsert",
        r"game.*engine|engine.*game",
        r"quantum.*leap",           # TV show references
        r"quantum.*break",          # Video game
        r"quantum.*realm",          # Marvel references
    ]
    
    susp_to_delete = []
    susp_to_keep = []
    
    for s in suspicious:
        repo = repos_collection.find_one({"_id": s["_id"]})
        if not repo:
            continue
        
        text = get_searchable_text(repo)
        is_non_qc = False
        non_qc_reason = None
        
        for pattern in SUSPICIOUS_NON_QC_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                is_non_qc = True
                non_qc_reason = f"Patrón sospechoso: {pattern}"
                break
        
        if is_non_qc:
            susp_to_delete.append({**s, "reason": non_qc_reason})
        else:
            susp_to_keep.append(s)
    
    print(f"\n  Sospechosos a eliminar: {len(susp_to_delete)}")
    for sd in susp_to_delete:
        print(f"    ❌ {sd['full_name']} ({sd['stars']}⭐) — {sd['reason']}")
    
    print(f"\n  Sospechosos a mantener (beneficio de la duda): {len(susp_to_keep)}")
    for sk in susp_to_keep[:20]:
        print(f"    ✓ {sk['full_name']} ({sk['stars']}⭐) — {sk['description'][:60]}")
    if len(susp_to_keep) > 20:
        print(f"    ...y {len(susp_to_keep) - 20} más")
    
    if susp_to_delete:
        susp_ids = [sd["_id"] for sd in susp_to_delete]
        result = repos_collection.delete_many({"_id": {"$in": susp_ids}})
        print(f"\n  ✅ Eliminados {result.deleted_count} sospechosos no-QC")
    
    # ─── Resumen Final ─────────────────────────────────────────────
    final_count = repos_collection.count_documents({})
    print(f"\n{'='*80}")
    print("RESUMEN FINAL")
    print(f"{'='*80}")
    print(f"  Repos iniciales:          {total}")
    print(f"  FPs eliminados:           {len(fps_to_delete)}")
    print(f"  Sospechosos eliminados:   {len(susp_to_delete)}")
    print(f"  Repos finales:            {final_count}")
    print(f"  Sospechosos mantenidos:   {len(susp_to_keep)} (sin evidencia clara de no-QC)")
    print(f"{'='*80}\n")
    
    client.close()


if __name__ == "__main__":
    main()
