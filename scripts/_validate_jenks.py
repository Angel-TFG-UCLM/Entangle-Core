"""Validacion del algoritmo de Jenks Natural Breaks con datos reales."""
import sys, math
sys.path.insert(0, "src")
from core.db import get_database
from analysis.network_metrics import CollaborationNetworkAnalyzer


def jenks_natural_breaks(data, n_classes):
    """Replica exacta del algoritmo implementado en el frontend."""
    sorted_data = sorted(data)
    n = len(sorted_data)
    if n <= n_classes:
        step = (sorted_data[-1] - sorted_data[0]) / n_classes if n > 1 else sorted_data[0]
        return {
            'boundaries': [sorted_data[0] + step * (i + 1) for i in range(n_classes - 1)],
            'class_starts': list(range(min(n, n_classes))),
            'sorted': sorted_data
        }
    lower = [[0] * (n_classes + 1) for _ in range(n + 1)]
    vari = [[float('inf')] * (n_classes + 1) for _ in range(n + 1)]
    for j in range(1, n_classes + 1):
        lower[1][j] = 1
        vari[1][j] = 0
    for l in range(2, n + 1):
        s = 0; s2 = 0; w = 0
        for m in range(1, l + 1):
            i3 = l - m + 1
            val = sorted_data[i3 - 1]
            w += 1; s += val; s2 += val * val
            v = s2 - (s * s) / w
            if i3 > 1:
                for j in range(2, n_classes + 1):
                    cost = v + vari[i3 - 1][j - 1]
                    if cost < vari[l][j]:
                        lower[l][j] = i3
                        vari[l][j] = cost
        lower[l][1] = 1
        vari[l][1] = s2 - (s * s) / w
    class_starts = [0] * n_classes
    class_starts[0] = 0
    k = n
    for j in range(n_classes, 1, -1):
        class_starts[j - 1] = lower[k][j] - 1
        k = lower[k][j] - 1
    boundaries = []
    for c in range(1, n_classes):
        boundaries.append((sorted_data[class_starts[c] - 1] + sorted_data[class_starts[c]]) / 2)
    return {'boundaries': boundaries, 'class_starts': class_starts, 'sorted': sorted_data}


def main():
    db = get_database()
    analyzer = CollaborationNetworkAnalyzer()
    analyzer.build_from_mongodb(db["repositories"], db["users"], db["organizations"])
    scores = analyzer.compute_collaboration_scores()

    org_scores = {}
    for node_id, data in scores.items():
        if analyzer.G.nodes[node_id].get("type") == "org":
            raw = data.get("collab_centrality_raw", 0)
            name = node_id.replace("org_", "")
            org_scores[name] = raw

    non_zero = {k: v for k, v in org_scores.items() if v > 0}
    sorted_orgs = sorted(non_zero.items(), key=lambda x: -x[1])

    print(f"\n{'='*70}")
    print(f"VALIDACION JENKS NATURAL BREAKS - DATOS REALES")
    print(f"{'='*70}")
    print(f"Total orgs: {len(org_scores)}, con raw>0: {len(non_zero)}")

    max_score = sorted_orgs[0][1] if sorted_orgs else 1
    PERIPHERY_MAX = 900 * math.sqrt(1122 / 200)

    all_radii = []
    org_target_r = {}
    for name, score in sorted_orgs:
        normalized = math.log(1 + score) / math.log(1 + max_score)
        curved = normalized ** 0.7
        tr = PERIPHERY_MAX * (1 - curved)
        org_target_r[name] = tr
        all_radii.append(tr)

    result = jenks_natural_breaks(all_radii, 3)
    CORE_BOUNDARY = result['boundaries'][0]
    MID_BOUNDARY = result['boundaries'][1]
    cs = result['class_starts']

    c1 = cs[1]
    c2 = cs[2] - cs[1]
    c3 = len(all_radii) - cs[2]

    print(f"\n--- RESULTADO JENKS ---")
    print(f"CORE_BOUNDARY:  {CORE_BOUNDARY:.1f}  (core < este radio)")
    print(f"MID_BOUNDARY:   {MID_BOUNDARY:.1f}  (mid < este radio)")
    print(f"PERIPHERY_MAX:  {PERIPHERY_MAX:.1f}  (escala visual)")
    print(f"\nDistribucion: core={c1}, mid={c2}, peripheral={c3}")

    print(f"\n--- CORE ({c1} orgs, radio < {CORE_BOUNDARY:.0f}) ---")
    for name, score in sorted_orgs:
        if org_target_r[name] <= CORE_BOUNDARY:
            print(f"  {name:30s}  raw={score:5.0f}  targetR={org_target_r[name]:.0f}")

    print(f"\n--- MID ({c2} orgs, radio {CORE_BOUNDARY:.0f}-{MID_BOUNDARY:.0f}) ---")
    for name, score in sorted_orgs:
        r = org_target_r[name]
        if CORE_BOUNDARY < r <= MID_BOUNDARY:
            print(f"  {name:30s}  raw={score:5.0f}  targetR={r:.0f}")

    print(f"\n--- PERIPHERAL ({c3} orgs, radio > {MID_BOUNDARY:.0f}) ---")
    count = 0
    for name, score in sorted_orgs:
        r = org_target_r[name]
        if r > MID_BOUNDARY:
            if count < 15:
                print(f"  {name:30s}  raw={score:5.0f}  targetR={r:.0f}")
            count += 1
    if count > 15:
        print(f"  ... y {count - 15} mas")

    print(f"\n--- VERIFICACION ORGS CLAVE ---")
    for key_org in ['Qiskit', 'microsoft', 'NVIDIA', 'sebastienrousseau']:
        if key_org in org_target_r:
            r = org_target_r[key_org]
            score = non_zero[key_org]
            zone = 'CORE' if r <= CORE_BOUNDARY else ('MID' if r <= MID_BOUNDARY else 'PERIPH')
            print(f"  {key_org:25s}  raw={score:5.0f}  targetR={r:7.1f}  -> {zone}")

    OLD_CORE = 200 * math.sqrt(1122 / 200)
    OLD_MID = 500 * math.sqrt(1122 / 200)
    print(f"\n--- COMPARACION vs CONSTANTES ANTERIORES ---")
    print(f"  ANTERIOR: CORE_RADIUS={OLD_CORE:.0f}, PERIPHERY_MIN={OLD_MID:.0f} (arbitrarias)")
    print(f"  JENKS:    CORE_BOUNDARY={CORE_BOUNDARY:.0f}, MID_BOUNDARY={MID_BOUNDARY:.0f} (data-driven)")
    print(f"  Diferencia core: {CORE_BOUNDARY - OLD_CORE:+.0f} ({(CORE_BOUNDARY/OLD_CORE - 1)*100:+.1f}%)")
    print(f"  Diferencia mid:  {MID_BOUNDARY - OLD_MID:+.0f} ({(MID_BOUNDARY/OLD_MID - 1)*100:+.1f}%)")

    # GVF (Goodness of Variance Fit)
    sorted_radii = result['sorted']
    total_mean = sum(sorted_radii) / len(sorted_radii)
    total_var = sum((x - total_mean)**2 for x in sorted_radii)
    within_var = 0
    class_ends = cs[1:] + [len(sorted_radii)]
    class_begins = [0] + cs[1:]
    for i in range(3):
        cls = sorted_radii[class_begins[i]:class_ends[i]]
        if cls:
            cls_mean = sum(cls) / len(cls)
            within_var += sum((x - cls_mean)**2 for x in cls)
    gvf = 1 - (within_var / total_var) if total_var > 0 else 0
    print(f"\n--- CALIDAD DE CLASIFICACION (GVF) ---")
    print(f"  GVF = {gvf:.4f}  (1.0 = perfecta, >0.8 = excelente)")


if __name__ == '__main__':
    main()
