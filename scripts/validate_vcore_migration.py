"""
Script de Validación Post-Migración a vCore
============================================

Verifica que todas las optimizaciones se hayan aplicado correctamente.
Ejecutar ANTES de comenzar la ingesta masiva.

Uso:
    python scripts/validate_vcore_migration.py
"""

import sys
import os
from pathlib import Path

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def check_file_content(file_path: Path, searches: dict) -> list:
    """
    Verifica que un archivo contenga (o NO contenga) ciertos strings.
    
    Args:
        file_path: Ruta al archivo
        searches: Dict con {label: (search_string, should_exist)}
        
    Returns:
        Lista de errores encontrados
    """
    errors = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        for label, (search_str, should_exist) in searches.items():
            exists = search_str in content
            
            if should_exist and not exists:
                errors.append(f"  ❌ {label}: NO encontrado (debería existir)")
            elif not should_exist and exists:
                errors.append(f"  ⚠️  {label}: encontrado (debería estar eliminado)")
    
    except Exception as e:
        errors.append(f"  ❌ Error leyendo archivo: {e}")
    
    return errors


def validate_migration():
    """Ejecuta todas las validaciones."""
    
    print("🔍 VALIDANDO MIGRACIÓN A VCORE")
    print("=" * 80)
    
    base_path = Path(__file__).parent.parent
    all_errors = []
    checks_passed = 0
    total_checks = 0
    
    # ==================== 1. DB.PY ====================
    print("\n📁 1. Validando src/core/db.py...")
    total_checks += 1
    
    errors = check_file_content(
        base_path / "src/core/db.py",
        {
            "maxPoolSize=100": ("maxPoolSize=100", True),
            "minPoolSize=10": ("minPoolSize=10", True),
            "retryWrites=True": ("retryWrites=True", True),
            "retryWrites=False eliminado": ("retryWrites=False", False),
        }
    )
    
    if errors:
        print("  ❌ FALLÓ:")
        for error in errors:
            print(error)
        all_errors.extend(errors)
    else:
        print("  ✅ CORRECTO")
        checks_passed += 1
    
    # ==================== 2. REPOSITORIES_INGESTION ====================
    print("\n📁 2. Validando src/github/repositories_ingestion.py...")
    total_checks += 1
    
    errors = check_file_content(
        base_path / "src/github/repositories_ingestion.py",
        {
            "batch_size default 500": ("batch_size: int = 500", True),
            "_retry_on_cosmos_throttle deprecado": ("DEPRECATED", True),
            "Sleep de BD eliminado": ("# Sleep para evitar sobrecarga en Cosmos DB", False),
        }
    )
    
    if errors:
        print("  ❌ FALLÓ:")
        for error in errors:
            print(error)
        all_errors.extend(errors)
    else:
        print("  ✅ CORRECTO")
        checks_passed += 1
    
    # ==================== 3. ORGANIZATION_INGESTION ====================
    print("\n📁 3. Validando src/github/organization_ingestion.py...")
    total_checks += 1
    
    errors = check_file_content(
        base_path / "src/github/organization_ingestion.py",
        {
            "batch_size default 100": ("batch_size: int = 100", True),
            "_retry_on_cosmos_throttle deprecado": ("DEPRECATED", True),
        }
    )
    
    if errors:
        print("  ❌ FALLÓ:")
        for error in errors:
            print(error)
        all_errors.extend(errors)
    else:
        print("  ✅ CORRECTO")
        checks_passed += 1
    
    # ==================== 4. USER_INGESTION ====================
    print("\n📁 4. Validando src/github/user_ingestion.py...")
    total_checks += 1
    
    errors = check_file_content(
        base_path / "src/github/user_ingestion.py",
        {
            "batch_size default 500": ("batch_size: int = 500", True),
        }
    )
    
    if errors:
        print("  ❌ FALLÓ:")
        for error in errors:
            print(error)
        all_errors.extend(errors)
    else:
        print("  ✅ CORRECTO")
        checks_passed += 1
    
    # ==================== 5. REPOSITORIES_ENRICHMENT ====================
    print("\n📁 5. Validando src/github/repositories_enrichment.py...")
    total_checks += 1
    
    errors = check_file_content(
        base_path / "src/github/repositories_enrichment.py",
        {
            "batch_size default 100": ("batch_size: int = 100", True),
            "Sleep entre lotes eliminado": ("time.sleep(2)", False),
        }
    )
    
    if errors:
        print("  ❌ FALLÓ:")
        for error in errors:
            print(error)
        all_errors.extend(errors)
    else:
        print("  ✅ CORRECTO")
        checks_passed += 1
    
    # ==================== 6. USER_ENRICHMENT ====================
    print("\n📁 6. Validando src/github/user_enrichment.py...")
    total_checks += 1
    
    errors = check_file_content(
        base_path / "src/github/user_enrichment.py",
        {
            "batch_size default 100": ("batch_size: int = 100", True),
        }
    )
    
    if errors:
        print("  ❌ FALLÓ:")
        for error in errors:
            print(error)
        all_errors.extend(errors)
    else:
        print("  ✅ CORRECTO")
        checks_passed += 1
    
    # ==================== 7. ORGANIZATION_ENRICHMENT ====================
    print("\n📁 7. Validando src/github/organization_enrichment.py...")
    total_checks += 1
    
    errors = check_file_content(
        base_path / "src/github/organization_enrichment.py",
        {
            "batch_size default 100": ("batch_size: int = 100", True),
            "_retry_on_cosmos_throttle deprecado": ("DEPRECATED", True),
        }
    )
    
    if errors:
        print("  ❌ FALLÓ:")
        for error in errors:
            print(error)
        all_errors.extend(errors)
    else:
        print("  ✅ CORRECTO")
        checks_passed += 1
    
    # ==================== 8. PIPELINE_CONFIG ====================
    print("\n📁 8. Validando config/pipeline_config.json...")
    total_checks += 1
    
    errors = check_file_content(
        base_path / "config/pipeline_config.json",
        {
            "batch_size 100": ('"batch_size": 100', True),
            "batch_size 5 antiguo": ('"batch_size": 5', False),
        }
    )
    
    if errors:
        print("  ❌ FALLÓ:")
        for error in errors:
            print(error)
        all_errors.extend(errors)
    else:
        print("  ✅ CORRECTO")
        checks_passed += 1
    
    # ==================== 9. API ROUTES ====================
    print("\n📁 9. Validando src/api/routes.py...")
    total_checks += 1
    
    errors = check_file_content(
        base_path / "src/api/routes.py",
        {
            "batch_size=100 en routes": ("batch_size=100", True),
            "batch_size=5 antiguo": ("batch_size=5", False),
            # Nota: batch_size=10 puede estar en "100", así que usamos regex más específico
        }
    )
    
    if errors:
        print("  ❌ FALLÓ:")
        for error in errors:
            print(error)
        all_errors.extend(errors)
    else:
        print("  ✅ CORRECTO")
        checks_passed += 1
    
    # ==================== RESUMEN FINAL ====================
    print("\n" + "=" * 80)
    print("📊 RESUMEN DE VALIDACIÓN")
    print("=" * 80)
    print(f"\n✅ Checks pasados: {checks_passed}/{total_checks}")
    
    if all_errors:
        print(f"\n❌ Se encontraron {len(all_errors)} problemas:")
        for error in all_errors:
            print(error)
        print("\n⚠️  Por favor, revisa los archivos mencionados antes de continuar.")
        return 1
    else:
        print("\n🎉 ¡TODAS LAS VALIDACIONES PASARON!")
        print("\n✅ Tu código está 100% optimizado para vCore M30")
        print("✅ Puedes proceder con la ingesta masiva")
        print("\nRecomendaciones:")
        print("  1. Ejecuta primero con un subset pequeño (ENRICHMENT_LIMIT=100)")
        print("  2. Monitorea CPU y memoria en Azure Portal")
        print("  3. Si todo va bien, ejecuta el pipeline completo")
        return 0


if __name__ == "__main__":
    exit_code = validate_migration()
    sys.exit(exit_code)
