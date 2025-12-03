"""
Script para eliminar campos duplicados e innecesarios de la colección de usuarios.
Solo elimina campos que son duplicados exactos de otros campos.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.db import Database

def main():
    database = Database()
    database.connect()
    db = database.db
    users_collection = db["users"]
    
    # Campos duplicados a eliminar
    fields_to_remove = [
        "node_id",                      # Duplicado de "id"
        "repositories_count",           # Duplicado de "public_repos_count"
        "gists_count",                  # Duplicado de "public_gists_count"
        "issues_count",                 # Duplicado de "total_issue_contributions"
        "pull_requests_count",          # Duplicado de "total_pr_contributions"
        "any_pinnable_items",           # Redundante (tenemos pinned_repositories)
        "starred_repositories_count",   # Duplicado de "starred_repos_count"
        "quantum_repos_count",          # Redundante (usar len(quantum_repositories))
    ]
    
    print("🔍 Analizando campos duplicados...\n")
    
    # Contar cuántos documentos tienen cada campo
    for field in fields_to_remove:
        count = users_collection.count_documents({field: {"$exists": True}})
        print(f"   • {field}: {count} usuarios")
    
    print(f"\n📊 Total de campos a eliminar: {len(fields_to_remove)}")
    
    # Eliminar campos
    print("\n🗑️  Eliminando campos duplicados...\n")
    
    unset_dict = {field: "" for field in fields_to_remove}
    result = users_collection.update_many(
        {},
        {"$unset": unset_dict}
    )
    
    print(f"✅ Operación completada:")
    print(f"   • Usuarios actualizados: {result.modified_count}")
    print(f"   • Campos eliminados por usuario: {len(fields_to_remove)}")
    print(f"   • Ahorro estimado: ~{len(fields_to_remove) * 0.3:.1f}KB por usuario")
    print(f"   • Ahorro total: ~{result.modified_count * len(fields_to_remove) * 0.3 / 1024:.1f}MB")
    
    # Verificar que se eliminaron
    print("\n🔍 Verificando eliminación...\n")
    
    all_clean = True
    for field in fields_to_remove:
        remaining = users_collection.count_documents({field: {"$exists": True}})
        if remaining > 0:
            print(f"   ❌ {field}: {remaining} documentos todavía tienen el campo")
            all_clean = False
        else:
            print(f"   ✅ {field}: eliminado completamente")
    
    if all_clean:
        print("\n✅ Todos los campos duplicados eliminados correctamente")
    else:
        print("\n⚠️  Algunos campos no se eliminaron completamente")

if __name__ == "__main__":
    main()
