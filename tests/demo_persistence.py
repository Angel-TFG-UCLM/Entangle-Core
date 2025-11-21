"""
Script de demostración del módulo de persistencia MongoDB.
Muestra cómo usar MongoRepository con los modelos Pydantic.
"""
import sys
from datetime import datetime
from typing import List

# Agregar path para imports
sys.path.insert(0, '.')

from src.core import db, MongoRepository, logger
from src.models import Repository, Organization, User, Relation


def print_section(title: str):
    """Imprime un título de sección."""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}\n")


def demo_connection():
    """Demuestra la conexión a MongoDB."""
    print_section("1️⃣  DEMOSTRACIÓN: Conexión a MongoDB")
    
    try:
        print("🔌 Conectando a MongoDB...")
        db.connect()
        print("✅ Conexión exitosa!")
        print(f"📊 Base de datos: {db.db.name}")
        print(f"📚 Colecciones existentes: {db.list_collections()}")
        return True
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
        print("ℹ️  Asegúrate de que MongoDB esté ejecutándose en mongodb://localhost:27017/")
        return False


def demo_repository_basic_operations():
    """Demuestra operaciones básicas con el repositorio."""
    print_section("2️⃣  DEMOSTRACIÓN: Operaciones Básicas con MongoRepository")
    
    # Crear repositorio para colección de prueba
    repo = MongoRepository("demo_repositories", unique_fields=["id"])
    print(f"✅ Repositorio creado para colección: {repo.collection_name}")
    print(f"📝 Campos únicos configurados: {repo.unique_fields}")
    
    # Limpiar colección de prueba anterior
    count = repo.delete_many({})
    print(f"🧹 Limpieza: {count} documentos eliminados de ejecuciones anteriores")
    
    # Crear documentos de prueba
    test_repos = [
        {
            "id": "repo001",
            "name": "quantum-simulator",
            "full_name": "qiskit/quantum-simulator",
            "owner_login": "qiskit",
            "stars_count": 1500,
            "forks_count": 300,
            "is_fork": False,
            "created_at": datetime(2023, 1, 15),
            "updated_at": datetime.utcnow(),
            "ingested_at": datetime.utcnow()
        },
        {
            "id": "repo002",
            "name": "quantum-algorithms",
            "full_name": "qiskit/quantum-algorithms",
            "owner_login": "qiskit",
            "stars_count": 800,
            "forks_count": 150,
            "is_fork": False,
            "created_at": datetime(2023, 3, 20),
            "updated_at": datetime.utcnow(),
            "ingested_at": datetime.utcnow()
        },
        {
            "id": "repo003",
            "name": "quantum-ml",
            "full_name": "pennylane/quantum-ml",
            "owner_login": "pennylane",
            "stars_count": 2000,
            "forks_count": 400,
            "is_fork": False,
            "created_at": datetime(2022, 6, 10),
            "updated_at": datetime.utcnow(),
            "ingested_at": datetime.utcnow()
        }
    ]
    
    # INSERT MANY
    print("\n📥 Insertando múltiples documentos...")
    result = repo.insert_many(test_repos, check_duplicates=True)
    print(f"   ✅ {result['inserted_count']} documentos insertados")
    print(f"   ⚠️  {result['duplicate_count']} duplicados omitidos")
    
    # COUNT
    print("\n📊 Contando documentos...")
    total = repo.count_documents({})
    print(f"   📈 Total de documentos: {total}")
    
    # FIND ONE
    print("\n🔍 Buscando un documento específico...")
    found = repo.find_one({"id": "repo001"})
    if found:
        print(f"   ✅ Encontrado: {found['name']} ({found['stars_count']} estrellas)")
    
    # FIND WITH FILTER
    print("\n🔍 Buscando repositorios con más de 1000 estrellas...")
    popular_repos = repo.find(
        {"stars_count": {"$gt": 1000}},
        sort=[("stars_count", -1)]
    )
    print(f"   📊 Encontrados: {len(popular_repos)} repositorios")
    for r in popular_repos:
        print(f"      • {r['name']}: {r['stars_count']} ⭐")
    
    # UPDATE ONE
    print("\n✏️  Actualizando un documento...")
    update_result = repo.update_one(
        {"id": "repo001"},
        {"$inc": {"stars_count": 50}}
    )
    print(f"   ✅ Actualizado: {update_result['modified_count']} documento(s)")
    
    # Verificar actualización
    updated = repo.find_one({"id": "repo001"})
    print(f"   📊 Nuevas estrellas: {updated['stars_count']}")
    
    # UPSERT
    print("\n🔄 Probando operación UPSERT (insertar o actualizar)...")
    new_repo = {
        "id": "repo004",
        "name": "new-quantum-lib",
        "full_name": "quantum/new-quantum-lib",
        "owner_login": "quantum",
        "stars_count": 50,
        "forks_count": 10
    }
    upsert_result = repo.upsert_one({"id": "repo004"}, new_repo)
    print(f"   ✅ Operación: {upsert_result['operation']}")
    
    # DELETE ONE
    print("\n🗑️  Eliminando el documento recién creado...")
    deleted = repo.delete_one({"id": "repo004"})
    print(f"   ✅ Eliminados: {deleted} documento(s)")
    
    return repo


def demo_pydantic_integration():
    """Demuestra la integración con modelos Pydantic."""
    print_section("3️⃣  DEMOSTRACIÓN: Integración con Modelos Pydantic")
    
    repo = MongoRepository("demo_pydantic", unique_fields=["id"])
    
    # Limpiar colección
    repo.delete_many({})
    
    # Crear modelo Pydantic
    print("📝 Creando modelo Pydantic Repository...")
    pydantic_repo = Repository(
        id="MDEwOlJlcG9zaXRvcnkxOTM4MzU5MzA=",
        name="qiskit",
        full_name="Qiskit/qiskit",
        nameWithOwner="Qiskit/qiskit",
        url="https://github.com/Qiskit/qiskit",
        description="Qiskit is an open-source SDK for quantum computing",
        owner_login="Qiskit",
        stars_count=5234,
        forks_count=1234,
        watchers_count=320,
        open_issues_count=89,
        is_private=False,
        is_fork=False,
        is_archived=False,
        primary_language="Python",
        license_name="Apache License 2.0",
        created_at=datetime(2019, 3, 14),
        updated_at=datetime.utcnow()
    )
    
    print(f"   ✅ Modelo creado: {pydantic_repo.name}")
    print(f"   📊 Estrellas: {pydantic_repo.stars_count}")
    print(f"   📅 Fecha de ingesta: {pydantic_repo.ingested_at}")
    
    # Insertar modelo Pydantic directamente
    print("\n📥 Insertando modelo Pydantic en MongoDB...")
    inserted_id = repo.insert_one(pydantic_repo, check_duplicates=False)
    print(f"   ✅ Insertado con ID: {inserted_id}")
    
    # Recuperar y verificar
    retrieved = repo.find_one({"id": pydantic_repo.id})
    print(f"   ✅ Recuperado: {retrieved['name']} ({retrieved['stars_count']} estrellas)")
    
    # Limpiar
    repo.delete_many({})


def demo_bulk_operations():
    """Demuestra operaciones bulk (masivas)."""
    print_section("4️⃣  DEMOSTRACIÓN: Operaciones Bulk (Masivas)")
    
    repo = MongoRepository("demo_bulk", unique_fields=["id"])
    
    # Limpiar colección
    repo.delete_many({})
    
    # Crear muchos documentos
    print("📝 Creando 100 documentos de prueba...")
    bulk_docs = [
        {
            "id": f"repo{i:03d}",
            "name": f"quantum-project-{i}",
            "full_name": f"org/quantum-project-{i}",
            "stars_count": i * 10,
            "forks_count": i * 2,
            "created_at": datetime.utcnow()
        }
        for i in range(1, 101)
    ]
    
    # Bulk upsert
    print("\n🔄 Ejecutando bulk upsert...")
    import time
    start = time.time()
    
    result = repo.bulk_upsert(bulk_docs, unique_field="id")
    
    elapsed = time.time() - start
    print(f"   ✅ {result['upserted_count']} documentos insertados")
    print(f"   ✏️  {result['modified_count']} documentos modificados")
    print(f"   ⏱️  Tiempo: {elapsed:.3f} segundos")
    print(f"   📊 Velocidad: {len(bulk_docs)/elapsed:.0f} docs/segundo")
    
    # Verificar
    count = repo.count_documents({})
    print(f"\n📈 Total en colección: {count} documentos")
    
    # Ejecutar bulk upsert nuevamente (debería actualizar)
    print("\n🔄 Ejecutando bulk upsert nuevamente (para actualizar)...")
    
    # Modificar algunos documentos
    for doc in bulk_docs[:10]:
        doc["stars_count"] += 100
    
    start = time.time()
    result = repo.bulk_upsert(bulk_docs, unique_field="id")
    elapsed = time.time() - start
    
    print(f"   ✅ {result['upserted_count']} documentos insertados")
    print(f"   ✏️  {result['modified_count']} documentos modificados")
    print(f"   ⏱️  Tiempo: {elapsed:.3f} segundos")
    
    # Limpiar
    deleted = repo.delete_many({})
    print(f"\n🧹 Limpieza: {deleted} documentos eliminados")


def demo_statistics():
    """Demuestra las estadísticas de colección."""
    print_section("5️⃣  DEMOSTRACIÓN: Estadísticas de Colección")
    
    # Usar colección de demo anterior
    repo = MongoRepository("demo_repositories", unique_fields=["id"])
    
    print("📊 Obteniendo estadísticas de la colección...")
    stats = repo.get_statistics()
    
    if stats:
        print(f"\n   📚 Colección: {stats['collection']}")
        print(f"   📄 Documentos: {stats['count']}")
        print(f"   💾 Tamaño: {stats['size_mb']} MB")
        print(f"   📏 Tamaño promedio por documento: {stats['avg_doc_size_bytes']} bytes")
        print(f"   🔍 Índices: {stats['indexes']}")
        print(f"   💿 Tamaño de índices: {stats['total_index_size_mb']} MB")
    else:
        print("   ⚠️  No se pudieron obtener estadísticas")


def demo_cleanup():
    """Limpia las colecciones de demostración."""
    print_section("6️⃣  LIMPIEZA: Eliminando Colecciones de Demo")
    
    collections_to_drop = ["demo_repositories", "demo_pydantic", "demo_bulk"]
    
    for coll_name in collections_to_drop:
        try:
            db.drop_collection(coll_name)
            print(f"   🗑️  Colección '{coll_name}' eliminada")
        except Exception as e:
            print(f"   ⚠️  Error al eliminar '{coll_name}': {e}")
    
    print("\n✅ Limpieza completada")


def main():
    """Función principal."""
    print("\n" + "="*80)
    print("  🎯 DEMOSTRACIÓN DEL MÓDULO DE PERSISTENCIA MONGODB")
    print("="*80)
    print("\nEste script demuestra el uso del módulo de persistencia MongoDB")
    print("con los modelos Pydantic del proyecto TFG.\n")
    
    # Conectar a MongoDB
    if not demo_connection():
        print("\n❌ No se pudo conectar a MongoDB. Abortando demo.")
        return
    
    try:
        # Ejecutar demos
        demo_repository_basic_operations()
        demo_pydantic_integration()
        demo_bulk_operations()
        demo_statistics()
        
        # Limpieza
        demo_cleanup()
        
        # Resumen final
        print_section("✅ DEMO COMPLETADA EXITOSAMENTE")
        print("🎉 El módulo de persistencia MongoDB está funcionando correctamente!")
        print("\n📝 Funcionalidades demostradas:")
        print("   • Conexión a MongoDB")
        print("   • Operaciones CRUD (Create, Read, Update, Delete)")
        print("   • Inserción y actualización masiva (bulk operations)")
        print("   • Integración con modelos Pydantic")
        print("   • Validación de duplicados")
        print("   • Operaciones upsert (insert or update)")
        print("   • Estadísticas de colección")
        print("   • Logging y manejo de errores")
        
        print("\n💡 Próximos pasos:")
        print("   • Integrar con el motor de ingesta (IngestionEngine)")
        print("   • Crear índices en las colecciones principales")
        print("   • Implementar reingestas incrementales")
        print("   • Agregar más tests de integración")
        
    finally:
        # Desconectar
        print("\n🔌 Desconectando de MongoDB...")
        db.disconnect()
        print("✅ Desconexión exitosa")


if __name__ == "__main__":
    main()
