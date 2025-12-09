"""
Test simple para verificar la integración básica.
"""
import sys
sys.path.insert(0, '.')

def test_imports():
    """Test que las importaciones funcionan."""
    print("\n✓ Testing imports...")
    
    try:
        from src.github.repositories_ingestion import IngestionEngine
        print("  ✓ IngestionEngine importado")
        
        from src.core.mongo_repository import MongoRepository
        print("  ✓ MongoRepository importado")
        
        from src.models import Repository, Organization, User, Relation
        print("  ✓ Modelos Pydantic importados")
        
        from src.core import db
        print("  ✓ Database module importado")
        
        print("\n✅ Todas las importaciones OK")
        return True
        
    except Exception as e:
        print(f"\n❌ Error en importaciones: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_engine_initialization():
    """Test de inicialización del motor."""
    print("\n✓ Testing IngestionEngine initialization...")
    
    try:
        from src.github.repositories_ingestion import IngestionEngine
        
        engine = IngestionEngine(incremental=False, batch_size=10)
        print("  ✓ Motor de ingesta creado")
        
        assert hasattr(engine, 'repo_db'), "No tiene repo_db"
        assert hasattr(engine, 'org_db'), "No tiene org_db"
        assert hasattr(engine, 'user_db'), "No tiene user_db"
        assert hasattr(engine, 'relation_db'), "No tiene relation_db"
        print("  ✓ Repositorios MongoDB creados")
        
        assert engine.incremental == False, "incremental flag incorrecto"
        assert engine.batch_size == 10, "batch_size incorrecto"
        print("  ✓ Configuración correcta")
        
        print("\n✅ Inicialización OK")
        return True
        
    except Exception as e:
        print(f"\n❌ Error en inicialización: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_mongodb_connection():
    """Test de conexión a MongoDB."""
    print("\n✓ Testing MongoDB connection...")
    
    try:
        from src.core import db
        
        if not db.is_connected():
            print("  ⚠️  No conectado, intentando conectar...")
            db.connect()
        
        print("  ✓ Conectado a MongoDB")
        
        # Test básico de query
        from src.core.mongo_repository import MongoRepository
        repo_db = MongoRepository("repositories")
        count = repo_db.count_documents({})
        print(f"  ✓ Query funcionando (documentos en DB: {count})")
        
        print("\n✅ Conexión MongoDB OK")
        return True
        
    except Exception as e:
        print(f"\n❌ Error en conexión: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Ejecuta tests básicos."""
    print("\n" + "="*80)
    print("  🧪 TESTS BÁSICOS DE INTEGRACIÓN")
    print("="*80)
    
    results = {
        "Importaciones": test_imports(),
        "Inicialización del motor": test_engine_initialization(),
        "Conexión MongoDB": test_mongodb_connection()
    }
    
    print("\n" + "="*80)
    print("  📊 RESUMEN")
    print("="*80)
    
    for test_name, result in results.items():
        status = "✅ PASÓ" if result else "❌ FALLÓ"
        print(f"  {status}: {test_name}")
    
    passed = sum(1 for r in results.values() if r)
    total = len(results)
    print(f"\n  Total: {passed}/{total} tests pasados")
    
    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
