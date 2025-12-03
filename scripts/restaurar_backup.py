import time
import os
import sys
from pymongo import MongoClient, UpdateOne
from pymongo.errors import BulkWriteError
from bson import json_util  # <--- EL CAMBIO CLAVE: Usamos las herramientas de Mongo, no las de Python
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# Configuración - Usar ruta absoluta relativa al script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
JSON_FILE = os.path.join(PROJECT_ROOT, "backups", "repositories.json")
BATCH_SIZE = 50 

def restore_data():
    uri = os.getenv("MONGO_URI")
    if not uri:
        print("❌ Error: No se encontró MONGO_URI en el archivo .env")
        return

    print(f"🔌 Conectando a: {uri.split('@')[1] if '@' in uri else 'MongoDB'}...")
    
    try:
        client = MongoClient(uri)
        # Forzamos una llamada para verificar conexión
        client.admin.command('ping')
    except Exception as e:
        print(f"❌ Error conectando a la base de datos: {e}")
        return

    db = client[os.getenv("MONGO_DB_NAME", "quantum_github")]
    collection = db["repositories"]

    # Cargar el JSON usando json_util (Soporta $oid, $date, etc.)
    print(f"📂 Leyendo archivo {JSON_FILE}...")
    try:
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            file_content = f.read()
            # json_util.loads convierte automáticamente {"$oid": "..."} en objetos ObjectId reales
            data = json_util.loads(file_content)
            
            # Gestionar si es lista directa o diccionario envuelto
            repos_list = data.get('repositories', []) if isinstance(data, dict) else data
            
        print(f"📦 Cargados {len(repos_list)} repositorios correctamente.")
    except FileNotFoundError:
        print(f"❌ No encuentro el archivo {JSON_FILE}")
        return
    except Exception as e:
        print(f"❌ Error leyendo el JSON: {e}")
        return

    # Preparar operaciones
    print("🚀 Iniciando importación controlada...")
    total_processed = 0
    batch = []
    
    for i, repo in enumerate(repos_list):
        # Asegurar que _id existe (si viene como id)
        if '_id' not in repo and 'id' in repo:
            repo['_id'] = repo['id']
            
        # Limpieza extra: Si por algún motivo siguen quedando claves con $, las quitamos
        # (Esto es un seguro de vida contra el error 57)
        clean_repo = {k: v for k, v in repo.items() if not k.startswith('$')}
            
        operation = UpdateOne({'_id': clean_repo['_id']}, {'$set': clean_repo}, upsert=True)
        batch.append(operation)

        if len(batch) >= BATCH_SIZE:
            _execute_batch(collection, batch)
            total_processed += len(batch)
            print(f"   Progreso: {total_processed}/{len(repos_list)}...", end='\r')
            batch = []
            time.sleep(0.5) 

    if batch:
        _execute_batch(collection, batch)
        total_processed += len(batch)

    print(f"\n✅ Importación completada. Total: {total_processed} repositorios.")

def _execute_batch(collection, batch):
    try:
        collection.bulk_write(batch, ordered=False)
    except Exception as e:
        if "16500" in str(e) or "429" in str(e):
            print("\n⚠️  Azure pide calma (429). Esperando 2 segundos...")
            time.sleep(2)
            _execute_batch(collection, batch)
        else:
            # Si hay un error, mostramos el detalle pero intentamos seguir
            print(f"\n❌ Error en lote: {e}")

if __name__ == "__main__":
    restore_data()