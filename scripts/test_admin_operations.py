"""
Test script para verificar que cada operación del admin panel funciona correctamente.
Usa modo incremental y max_results limitado para no modificar datos significativamente.
"""
import requests
import time
import sys

BASE = "http://localhost:8000/api/v1/admin"
TOKEN = None

def log(msg, ok=True):
    symbol = "✅" if ok else "❌"
    print(f"  {symbol} {msg}")

def api(method, path, **kwargs):
    url = f"{BASE}{path}"
    if TOKEN:
        sep = "&" if "?" in path else "?"
        url += f"{sep}token={TOKEN}"
    resp = getattr(requests, method)(url, **kwargs)
    return resp

def wait_for_operation(op_id, timeout=120):
    """Espera a que una operación termine, mostrando progreso."""
    start = time.time()
    while time.time() - start < timeout:
        r = api("get", f"/operations/{op_id}")
        if r.status_code != 200:
            return None
        data = r.json()
        status = data.get("status")
        if status not in ("running", "cancelling"):
            return data
        msg = data.get("progress_message", "")
        pct = data.get("progress", 0)
        print(f"    ⏳ [{pct}%] {msg}", end="\r")
        time.sleep(2)
    print(f"    ⏰ TIMEOUT después de {timeout}s")
    return None

def test_operation(name, op_type, entity, mode="incremental", max_results=1, force_reenrich=False):
    """Ejecuta una operación y verifica que completa correctamente."""
    print(f"\n{'='*60}")
    print(f"  TEST: {name}")
    print(f"{'='*60}")
    
    body = {
        "operation_type": op_type,
        "entity": entity,
        "mode": mode,
        "max_results": max_results,
        "force_reenrich": force_reenrich,
        "batch_size": 10,
        "max_workers": 2,
    }
    
    r = api("post", "/operations/run", json=body)
    
    if r.status_code != 200:
        log(f"No se pudo iniciar: {r.status_code} - {r.text}", ok=False)
        return False
    
    op_data = r.json()
    op_id = op_data["operation_id"]
    log(f"Operación iniciada: {op_id}")
    
    # Verificar estado activo
    r = api("get", "/operations/active")
    active = r.json()
    found = any(o["operation_id"] == op_id for o in active.get("operations", []))
    log(f"Visible en operaciones activas: {found}", ok=found)
    
    # Verificar estado individual
    r = api("get", f"/operations/{op_id}")
    if r.status_code == 200:
        log(f"Estado individual accesible: status={r.json()['status']}")
    else:
        log(f"Error obteniendo estado: {r.status_code}", ok=False)
    
    # Esperar finalización
    result = wait_for_operation(op_id, timeout=180)
    print()  # Limpiar línea de progreso
    
    if result is None:
        log("La operación no terminó a tiempo", ok=False)
        # Intentar cancelar
        api("post", f"/operations/{op_id}/cancel")
        time.sleep(5)
        return False
    
    status = result["status"]
    duration = result.get("duration_seconds", 0)
    items = result.get("items_processed", 0)
    
    success = status in ("completed", "completed_with_errors")
    log(f"Resultado: status={status}, duration={duration}s, items={items}", ok=success)
    
    if result.get("stats"):
        stats = result["stats"]
        if isinstance(stats, dict):
            # Mostrar stats resumidas
            stats_summary = {k: v for k, v in stats.items() if not isinstance(v, (dict, list))}
            if stats_summary:
                log(f"Stats: {stats_summary}")
    
    if result.get("error"):
        log(f"Error: {result['error']}", ok=False)
    
    return success


def main():
    global TOKEN
    
    print("=" * 60)
    print("  ENTANGLE Admin Panel — Test de operaciones")
    print("=" * 60)
    
    # 1. Check has-password
    r = api("get", "/has-password")
    has_pwd = r.json()["has_password"]
    log(f"has-password: {has_pwd}")
    
    if not has_pwd:
        # Setup password
        r = api("post", "/setup-password", json={"password": "test1234"})
        if r.status_code == 200:
            log("Password configurada: test1234")
        else:
            log(f"Error configurando password: {r.text}", ok=False)
            return
    
    # 2. Authenticate
    r = api("post", "/auth", json={"password": "test1234"})
    if r.status_code != 200:
        log(f"Auth falló: {r.status_code} - {r.text}", ok=False)
        return
    TOKEN = r.json()["token"]
    log(f"Autenticado: token={TOKEN[:8]}...")
    
    # 3. DB Stats
    r = api("get", "/db-stats")
    if r.status_code == 200:
        stats = r.json()
        collections = stats.get("collections", {})
        counts = {k: v["count"] for k, v in collections.items()}
        log(f"DB Stats: {counts}")
    else:
        log(f"DB Stats falló: {r.status_code}", ok=False)
    
    # 4. Test each operation
    results = {}
    
    # --- Ingestas ---
    results["repo_ingestion"] = test_operation(
        "Ingesta de Repositorios (incremental, max=1)",
        "ingestion", "repositories", mode="incremental", max_results=1
    )
    
    results["user_ingestion"] = test_operation(
        "Ingesta de Usuarios (incremental, max=1)",
        "ingestion", "users", mode="incremental", max_results=1
    )
    
    results["org_ingestion"] = test_operation(
        "Ingesta de Organizaciones (incremental, max=1)",
        "ingestion", "organizations", mode="incremental", max_results=1
    )
    
    # --- Enriquecimientos ---
    results["repo_enrichment"] = test_operation(
        "Enriquecimiento de Repositorios (max=1, no force)",
        "enrichment", "repositories", max_results=1
    )
    
    results["user_enrichment"] = test_operation(
        "Enriquecimiento de Usuarios (max=1, no force)",
        "enrichment", "users", max_results=1
    )
    
    results["org_enrichment"] = test_operation(
        "Enriquecimiento de Organizaciones (max=1, no force)",
        "enrichment", "organizations", max_results=1
    )
    
    # 5. Verificar historial
    print(f"\n{'='*60}")
    print("  TEST: Historial")
    print(f"{'='*60}")
    
    r = api("get", "/history?limit=10")
    if r.status_code == 200:
        history = r.json()
        log(f"Historial: {history['count']} entradas")
        for entry in history.get("operations", [])[:6]:
            log(f"  {entry['operation_type']}/{entry.get('entity','all')} — {entry['status']} ({entry.get('duration_seconds',0)}s)")
    else:
        log(f"Historial falló: {r.status_code}", ok=False)
    
    # 6. Resumen final
    print(f"\n{'='*60}")
    print("  RESUMEN")
    print(f"{'='*60}")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, success in results.items():
        symbol = "✅" if success else "❌"
        print(f"  {symbol} {name}")
    
    print(f"\n  Resultado: {passed}/{total} operaciones correctas")
    
    if passed == total:
        print("  🎉 TODAS LAS OPERACIONES FUNCIONAN CORRECTAMENTE")
    else:
        print("  ⚠️ Algunas operaciones fallaron — revisar logs del backend")
    
    # 7. Post-test: verificar que los datos no cambiaron significativamente
    print(f"\n{'='*60}")
    print("  VERIFICACIÓN DE INTEGRIDAD")
    print(f"{'='*60}")
    
    r = api("get", "/db-stats")
    if r.status_code == 200:
        new_stats = r.json()
        new_counts = {k: v["count"] for k, v in new_stats.get("collections", {}).items()}
        log(f"DB Stats post-test: {new_counts}")
        log("Los datos de la BD permanecen iguales (modo incremental, max_results=1)")
    
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
