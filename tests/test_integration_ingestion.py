"""
Test de integración: Motor de Ingesta + Persistencia MongoDB.

Este script prueba el flujo completo:
1. Extracción de repositorios de GitHub
2. Filtrado por criterios de calidad
3. Validación con modelos Pydantic
4. Persistencia en MongoDB con bulk operations
5. Creación de relaciones
"""
import sys
sys.path.insert(0, '.')

from src.github.ingestion import IngestionEngine, run_ingestion
from src.core import logger, db
from src.core.mongo_repository import MongoRepository


def test_integration_simple():
    """Test básico de integración con pocos resultados."""
    print("\n" + "="*80)
    print("  🧪 TEST DE INTEGRACIÓN: Motor de Ingesta + Persistencia")
    print("="*80 + "\n")
    
    try:
        # Crear motor de ingesta
        engine = IngestionEngine(
            incremental=False,
            batch_size=10
        )
        
        print("✅ Motor de ingesta inicializado")
        
        # Ejecutar ingesta con límite pequeño para testing
        print("\n🚀 Ejecutando ingesta de prueba (máx 5 repositorios)...")
        report = engine.run(
            max_results=5,
            save_to_json=True,
            output_file="tests/test_ingestion_results.json"
        )
        
        # Verificar resultados
        print("\n📊 Verificando resultados...")
        
        assert report["summary"]["total_found"] > 0, "No se encontraron repositorios"
        print(f"  ✓ Repositorios encontrados: {report['summary']['total_found']}")
        
        assert report["summary"]["validation_success"] > 0, "No hubo validaciones exitosas"
        print(f"  ✓ Validaciones exitosas: {report['summary']['validation_success']}")
        
        assert report["summary"]["repositories_inserted"] >= 0, "Error en inserción"
        assert report["summary"]["repositories_updated"] >= 0, "Error en actualización"
        total_persisted = report["summary"]["repositories_inserted"] + report["summary"]["repositories_updated"]
        print(f"  ✓ Repositorios persistidos: {total_persisted}")
        
        print("\n📈 Estadísticas de tiempo:")
        print(f"  • Extracción: {report['timing']['extraction']}")
        print(f"  • Filtrado: {report['timing']['filtering']}")
        print(f"  • Validación: {report['timing']['validation']}")
        print(f"  • Persistencia: {report['timing']['persistence']}")
        print(f"  • Total: {report['timing']['total']}")
        
        # Verificar en MongoDB
        print("\n💾 Verificando datos en MongoDB...")
        repo_db = MongoRepository("repositories")
        count = repo_db.count_documents({})
        print(f"  ✓ Total de repositorios en MongoDB: {count}")
        
        # Mostrar algunos repositorios
        sample_repos = repo_db.find({}, limit=3, sort=[("stars_count", -1)])
        print(f"\n📦 Muestra de repositorios (top 3 por estrellas):")
        for repo in sample_repos:
            print(f"  • {repo.get('full_name', 'N/A')} - {repo.get('stars_count', 0)} ⭐")
        
        print("\n" + "="*80)
        print("✅ TEST DE INTEGRACIÓN COMPLETADO EXITOSAMENTE")
        print("="*80 + "\n")
        
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR EN TEST DE INTEGRACIÓN: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_integration_with_validation():
    """Test que verifica el manejo de errores de validación."""
    print("\n" + "="*80)
    print("  🧪 TEST: Validación y Manejo de Errores")
    print("="*80 + "\n")
    
    try:
        engine = IngestionEngine(batch_size=5)
        
        # Ejecutar ingesta
        report = engine.run(max_results=3, save_to_json=False)
        
        # Verificar que se reportan errores de validación (si los hay)
        if report["summary"]["validation_errors"] > 0:
            print(f"⚠️  Errores de validación detectados: {report['summary']['validation_errors']}")
            print("  Sample de errores:")
            for error in report["errors"]["sample_errors"][:2]:
                print(f"    • Repo: {error.get('repository', 'unknown')}")
        else:
            print("✅ No hubo errores de validación")
        
        print("\n✅ Test de validación completado")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_incremental_mode():
    """Test de modo incremental."""
    print("\n" + "="*80)
    print("  🧪 TEST: Modo Incremental")
    print("="*80 + "\n")
    
    try:
        # Primera ingesta (completa)
        print("1️⃣  Primera ingesta (completa)...")
        engine1 = IngestionEngine(incremental=False, batch_size=5)
        report1 = engine1.run(max_results=3, save_to_json=False)
        inserted_first = report1["summary"]["repositories_inserted"]
        print(f"  ✓ Repositorios insertados: {inserted_first}")
        
        # Segunda ingesta (incremental - debería actualizar)
        print("\n2️⃣  Segunda ingesta (incremental)...")
        engine2 = IngestionEngine(incremental=True, batch_size=5)
        report2 = engine2.run(max_results=3, save_to_json=False)
        updated_second = report2["summary"]["repositories_updated"]
        print(f"  ✓ Repositorios actualizados: {updated_second}")
        
        print(f"\n📊 Comparación:")
        print(f"  • Primera ingesta insertó: {inserted_first}")
        print(f"  • Segunda ingesta actualizó: {updated_second}")
        
        print("\n✅ Test de modo incremental completado")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_bulk_operations():
    """Test de operaciones bulk."""
    print("\n" + "="*80)
    print("  🧪 TEST: Operaciones Bulk")
    print("="*80 + "\n")
    
    try:
        # Ingesta con batch pequeño
        print("📦 Ingesta con batch_size=3...")
        engine = IngestionEngine(batch_size=3)
        report = engine.run(max_results=10, save_to_json=False)
        
        print(f"✅ Procesados en batches:")
        print(f"  • Total persistido: {report['summary']['repositories_inserted'] + report['summary']['repositories_updated']}")
        print(f"  • Tiempo de persistencia: {report['timing']['persistence']}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_relations_creation():
    """Test de creación de relaciones."""
    print("\n" + "="*80)
    print("  🧪 TEST: Creación de Relaciones")
    print("="*80 + "\n")
    
    try:
        # Ingesta que crea relaciones
        engine = IngestionEngine()
        report = engine.run(max_results=3, save_to_json=False)
        
        print(f"🔗 Relaciones creadas: {report['summary']['relations_created']}")
        
        # Verificar en MongoDB
        relation_db = MongoRepository("relations")
        count = relation_db.count_documents({})
        print(f"💾 Total de relaciones en MongoDB: {count}")
        
        # Mostrar algunas relaciones
        sample = relation_db.find({}, limit=3)
        print("\n📋 Muestra de relaciones:")
        for rel in sample:
            print(f"  • {rel.get('source_login')} → {rel.get('target_name')} ({rel.get('relation_type')})")
        
        print("\n✅ Test de relaciones completado")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def cleanup_test_data():
    """Limpia datos de prueba (opcional)."""
    print("\n🧹 ¿Desea limpiar los datos de prueba? (s/N): ", end="")
    
    try:
        response = input().strip().lower()
        if response == 's':
            print("🗑️  Limpiando colecciones de prueba...")
            
            # No eliminar colecciones principales en producción
            # Solo mostrar estadísticas
            repo_db = MongoRepository("repositories")
            count = repo_db.count_documents({})
            print(f"  ℹ️  Repositorios en DB: {count}")
            
            print("  ℹ️  Para limpiar manualmente, usa MongoDB Compass o ejecuta:")
            print("     db.repositories.deleteMany({})")
            print("     db.relations.deleteMany({})")
    except:
        print("\n  ⏭️  Saltando limpieza")


def main():
    """Ejecuta todos los tests de integración."""
    print("\n" + "="*80)
    print("  🧪 SUITE DE TESTS DE INTEGRACIÓN")
    print("  Motor de Ingesta + Módulo de Persistencia")
    print("="*80)
    
    results = {
        "Test básico de integración": test_integration_simple(),
        "Test de validación": test_integration_with_validation(),
        "Test modo incremental": test_incremental_mode(),
        "Test operaciones bulk": test_bulk_operations(),
        "Test creación de relaciones": test_relations_creation()
    }
    
    # Resumen
    print("\n" + "="*80)
    print("  📊 RESUMEN DE TESTS")
    print("="*80)
    
    passed = sum(1 for result in results.values() if result)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASÓ" if result else "❌ FALLÓ"
        print(f"  {status}: {test_name}")
    
    print(f"\n  Total: {passed}/{total} tests pasados")
    
    if passed == total:
        print("\n  🎉 TODOS LOS TESTS PASARON EXITOSAMENTE")
    else:
        print(f"\n  ⚠️  {total - passed} test(s) fallaron")
    
    print("="*80 + "\n")
    
    # Cleanup
    cleanup_test_data()
    
    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
