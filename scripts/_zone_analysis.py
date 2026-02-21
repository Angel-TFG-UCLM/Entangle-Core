"""Analisis de impacto de CORE_RADIUS en clasificacion de orgs."""
import math

# Datos REALES del backend (top 30 orgs por raw score) + stats
data = [
    ("Qiskit", 486), ("qiskit-community", 354), ("PennyLaneAI", 312),
    ("unitaryfoundation", 270), ("quantumlib", 257), ("qosf", 232),
    ("openqasm", 180), ("amazon-braket", 180), ("XanaduAI", 162),
    ("Quantinuum", 144), ("qBraid", 138), ("rigetti", 137),
    ("munich-quantum-toolkit", 130), ("qutip", 123), ("NVIDIA", 115),
    ("microsoft", 113), ("qojulia", 106), ("ProjectQ-Framework", 105),
    ("QuantumSavory", 96), ("QuEraComputing", 95), ("tqec", 89),
    ("qir-alliance", 85), ("pasqal-io", 84), ("JuliaQuantumControl", 79),
    ("qilimanjaro-tech", 76), ("qiboteam", 75), ("netket", 74),
    ("entropicalabs", 72), ("gdsfactory", 68), ("qulacs", 64),
]
# Stats: 1224 orgs total, 127 con raw > 0, mediana de non-zero = 16
maxScore = 486
scaleFactor = math.sqrt(1122 / 200)  # 2.368
PERIPHERY_MAX = 900 * scaleFactor

print("=== IMPACTO DE CORE_RADIUS EN ZONA DE ORGS ===")
print(f"scaleFactor = {scaleFactor:.3f}, PERIPHERY_MAX = {PERIPHERY_MAX:.0f}")
print(f"Orgs totales: 1224, con raw > 0: 127, mediana non-zero: 16")
print()

for cr_base in [150, 180, 200, 220, 250]:
    cr = cr_base * scaleFactor
    thresh_curved = 1 - cr / PERIPHERY_MAX
    thresh_norm = thresh_curved ** (1.0 / 0.7)
    thresh_score = math.exp(thresh_norm * math.log(1 + maxScore)) - 1
    
    in_core = [(n, s) for n, s in data if s >= thresh_score]
    first_mid = next((n for n, s in data if s < thresh_score and s > 0), "-")
    
    ms_zone = "CORE" if 113 >= thresh_score else "MID"
    nv_zone = "CORE" if 115 >= thresh_score else "MID"
    
    print(f"  CORE_RADIUS = {cr_base} ({cr:.0f}px)")
    print(f"    Umbral raw >= {thresh_score:.0f}")
    print(f"    Orgs en core: {len(in_core)}")
    print(f"    Ultimo core: {in_core[-1][0] if in_core else '-'} (raw={in_core[-1][1] if in_core else 0})")
    print(f"    Primero mid: {first_mid}")
    print(f"    Microsoft: {ms_zone}, NVIDIA: {nv_zone}")
    print()

# Analisis de gaps en la distribucion
print("=== GAPS ENTRE ORGS CONSECUTIVAS (buscar cortes naturales) ===")
for i in range(1, len(data)):
    prev_name, prev_score = data[i-1]
    curr_name, curr_score = data[i]
    gap_pct = (prev_score - curr_score) / prev_score * 100
    marker = " <<<" if gap_pct > 15 else ""
    print(f"  {i:2d}→{i+1:2d}: {prev_name:25s}({prev_score}) → {curr_name:25s}({curr_score})  gap={gap_pct:.1f}%{marker}")

print()
print("=== CONCLUSION ===")
print("El corte entre rank 14 (qutip=123) y rank 15 (NVIDIA=115) tiene gap 6.5%")
print("El corte entre rank 6 (qosf=232) y rank 7 (openqasm=180) tiene gap 22.4%")
print("NO hay un corte natural en rank 14-15. Es artefacto de CORE_RADIUS=150")
print("Un CORE_RADIUS=200 incluiria top 26 orgs (hasta qiboteam=75), con gap de 1.3%")
print("Solo hay UN salto claro: ranks 1-6 (>230) vs ranks 7+ (<180) = 22% gap")
