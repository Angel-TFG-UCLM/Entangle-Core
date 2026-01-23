#!/usr/bin/env python3
"""
Script para ejecutar el pipeline completo de ingesta y enriquecimiento.
Ejecuta secuencialmente todos los scripts en el orden correcto.
Si algún script falla, se detiene la ejecución.

Configuración:
    La configuración se lee desde: Backend/config/pipeline_config.json
    - auto_confirm: Auto-confirma todas las operaciones
    - enrichment.repositories.limit: Límite de repositorios (null = todos)
    - enrichment.users.limit: Límite de usuarios (null = todos)
    - enrichment.organizations.limit: Límite de organizaciones (null = todos)
    - enrichment.batch_size: Tamaño de lote para enriquecimiento
    - enrichment.force_reenrichment: Forzar re-enriquecimiento
"""

import subprocess
import sys
import os
import json
from pathlib import Path
from threading import Thread
from queue import Queue, Empty

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Definir el orden de ejecución de los scripts
SCRIPTS = [
    "run_repositories_ingestion.py",
    "run_repositories_enrichment.py",
    "run_user_ingestion.py",
    "run_user_enrichment.py",
    "run_organization_ingestion.py",
    "run_organization_enrichment.py"
]

def load_pipeline_config():
    """Carga la configuración del pipeline desde config/pipeline_config.json"""
    config_path = Path(__file__).parent.parent / "config" / "pipeline_config.json"
    
    if not config_path.exists():
        print(f"⚠️  Advertencia: No se encontró {config_path}")
        print("Usando configuración por defecto...")
        return {
            'pipeline': {
                'auto_confirm': True,
                'stop_on_error': True
            },
            'enrichment': {
                'repositories': {'limit': None},
                'users': {'limit': None},
                'organizations': {'limit': None},
                'batch_size': 5,
                'force_reenrichment': False
            }
        }
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            print(f"✓ Configuración cargada desde: {config_path.name}")
            return config
    except Exception as e:
        print(f"❌ Error al cargar configuración: {e}")
        print("Usando configuración por defecto...")
        return {
            'pipeline': {
                'auto_confirm': True,
                'stop_on_error': True
            },
            'enrichment': {
                'repositories': {'limit': None},
                'users': {'limit': None},
                'organizations': {'limit': None},
                'batch_size': 5,
                'force_reenrichment': False
            }
        }

# Cargar configuración
PIPELINE_CONFIG = load_pipeline_config()


def get_script_env_vars(script_name):
    """
    Retorna las variables de entorno específicas para cada script.
    Estas variables serán leídas por los scripts individuales.
    """
    env = os.environ.copy()
    
    # Variable global para auto-confirmar
    auto_confirm = PIPELINE_CONFIG.get('pipeline', {}).get('auto_confirm', True)
    env['AUTO_CONFIRM'] = 'true' if auto_confirm else 'false'
    
    enrichment = PIPELINE_CONFIG.get('enrichment', {})
    batch_size = enrichment.get('batch_size', 5)
    force_reenrich = enrichment.get('force_reenrichment', False)
    
    # Variables específicas por script
    if 'repositories_enrichment' in script_name:
        limit = enrichment.get('repositories', {}).get('limit')
        if limit is not None:
            env['ENRICHMENT_LIMIT'] = str(limit)
        env['BATCH_SIZE'] = str(batch_size)
        env['FORCE_REENRICHMENT'] = 'true' if force_reenrich else 'false'
    
    elif 'user_enrichment' in script_name:
        limit = enrichment.get('users', {}).get('limit')
        if limit is not None:
            env['ENRICHMENT_LIMIT'] = str(limit)
        env['BATCH_SIZE'] = str(batch_size)
        env['FORCE_REENRICHMENT'] = 'true' if force_reenrich else 'false'
    
    elif 'organization_enrichment' in script_name:
        limit = enrichment.get('organizations', {}).get('limit')
        if limit is not None:
            env['ENRICHMENT_LIMIT'] = str(limit)
        env['BATCH_SIZE'] = str(batch_size)
        env['FORCE_REENRICHMENT'] = 'true' if force_reenrich else 'false'
    
    return env

def enqueue_output(stream, queue):
    """Lee la salida del proceso línea por línea y la pone en una cola."""
    for line in stream:
        queue.put(line)
    stream.close()

def run_script(script_name):
    """
    Ejecuta un script y retorna una tupla (éxito, salida capturada).
    """
    print(f"\n{'='*80}")
    print(f"EJECUTANDO: {script_name}")
    print(f"{'='*80}\n")
    
    script_path = Path(__file__).parent / script_name
    output_lines = []
    process = None
    
    try:
        # Obtener variables de entorno para este script
        script_env = get_script_env_vars(script_name)
        
        # Forzar UTF-8 en Windows
        script_env['PYTHONIOENCODING'] = 'utf-8'
        
        # Ejecutar el script con las variables de entorno
        process = subprocess.Popen(
            [sys.executable, '-u', str(script_path)],  # -u para unbuffered output
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',  # Reemplazar caracteres no decodificables
            bufsize=1,
            universal_newlines=True,
            env=script_env
        )
        
        # Cola para la salida
        output_queue = Queue()
        
        # Thread para leer la salida sin bloquear
        output_thread = Thread(target=enqueue_output, args=(process.stdout, output_queue))
        output_thread.daemon = True
        output_thread.start()
        
        # Procesar la salida en tiempo real y auto-responder si es necesario
        while process.poll() is None or not output_queue.empty():
            try:
                line = output_queue.get(timeout=0.1)
                print(line, end='')
                output_lines.append(line)
                
                # Si detectamos una pregunta y auto_confirm está activado, enviar 's'
                if PIPELINE_CONFIG.get('pipeline', {}).get('auto_confirm', True):
                    line_lower = line.lower().strip()
                    if ('?' in line or ':' in line) and ('s/n' in line_lower or '[s/n]' in line_lower or 'continuar' in line_lower):
                        try:
                            process.stdin.write('s\n')
                            process.stdin.flush()
                        except:
                            pass
                    # Para preguntas que esperan Enter, enviar \n
                    elif line.strip().endswith(':') and 'enter' in line_lower:
                        try:
                            process.stdin.write('\n')
                            process.stdin.flush()
                        except:
                            pass
                
            except Empty:
                continue
        
        # Esperar a que termine el proceso
        return_code = process.wait()
        
        # Asegurarse de cerrar stdin
        try:
            process.stdin.close()
        except:
            pass
        
        if return_code == 0:
            print(f"\n✓ {script_name} completado exitosamente\n")
            return True, ''.join(output_lines)
        else:
            print(f"\n✗ {script_name} falló con código de salida {return_code}\n")
            return False, ''.join(output_lines)
    
    except KeyboardInterrupt:
        print(f"\n\n⚠️  Interrupción del usuario detectada en {script_name}")
        if process:
            try:
                process.terminate()
                process.wait(timeout=5)
            except:
                process.kill()
        raise  # Re-lanzar para que el main lo capture
            
    except Exception as e:
        print(f"\n✗ Error al ejecutar {script_name}: {str(e)}\n")
        if process:
            try:
                process.terminate()
            except:
                pass
        return False, str(e)

def extract_summary(output, script_name):
    """
    Extrae información relevante del output de cada script.
    """
    lines = output.split('\n')
    summary_info = {
        'total_lines': len(lines),
        'errors': [],
        'warnings': [],
        'completions': [],
        'statistics': []
    }
    
    for line in lines:
        line_lower = line.lower()
        
        # Buscar errores
        if 'error' in line_lower and 'error' not in line_lower.find('0 error'):
            summary_info['errors'].append(line.strip())
        
        # Buscar advertencias
        if 'warning' in line_lower or 'advertencia' in line_lower:
            summary_info['warnings'].append(line.strip())
        
        # Buscar mensajes de completado
        if any(word in line_lower for word in ['completado', 'completed', 'finalizado', 'finished', 'éxito', 'success']):
            summary_info['completions'].append(line.strip())
        
        # Buscar estadísticas (líneas con números)
        if any(word in line_lower for word in ['total', 'procesados', 'ingested', 'enriched', 'guardados', 'saved']):
            summary_info['statistics'].append(line.strip())
    
    return summary_info

def print_summary(script_outputs):
    """
    Imprime un resumen detallado de todas las operaciones completadas.
    """
    print("\n" + "="*80)
    print("RESÚMENES DE OPERACIONES COMPLETADAS")
    print("="*80)
    
    for script_name, output in script_outputs.items():
        summary = extract_summary(output, script_name)
        
        print(f"\n{'─'*80}")
        print(f"📊 {script_name}")
        print(f"{'─'*80}")
        
        # Mostrar estadísticas
        if summary['statistics']:
            print("\n  📈 Estadísticas:")
            for stat in summary['statistics'][:10]:  # Limitar a las primeras 10
                if stat:
                    print(f"    • {stat}")
        
        # Mostrar mensajes de completado
        if summary['completions']:
            print("\n  ✅ Estado:")
            for completion in summary['completions'][:5]:  # Limitar a los primeros 5
                if completion:
                    print(f"    • {completion}")
        
        # Mostrar advertencias si las hay
        if summary['warnings']:
            print("\n  ⚠️  Advertencias:")
            for warning in summary['warnings'][:5]:
                if warning:
                    print(f"    • {warning}")
    
    print("\n" + "="*80)

def main():
    """
    Función principal que ejecuta todos los scripts en secuencia.
    """
    try:
        enrichment = PIPELINE_CONFIG.get('enrichment', {})
        
        print("\n" + "="*80)
        print("PIPELINE COMPLETO DE INGESTA Y ENRIQUECIMIENTO")
        print("="*80)
        print("\n📋 CONFIGURACIÓN:")
        print(f"  • Auto-confirmar operaciones: {PIPELINE_CONFIG.get('pipeline', {}).get('auto_confirm', True)}")
        print(f"  • Límite repositorios (enriquecimiento): {enrichment.get('repositories', {}).get('limit') or 'Todos'}")
        print(f"  • Límite usuarios (enriquecimiento): {enrichment.get('users', {}).get('limit') or 'Todos'}")
        print(f"  • Límite organizaciones (enriquecimiento): {enrichment.get('organizations', {}).get('limit') or 'Todos'}")
        print(f"  • Tamaño de lote: {enrichment.get('batch_size', 5)}")
        print(f"  • Forzar re-enriquecimiento: {enrichment.get('force_reenrichment', False)}")
        print("="*80)
        print("\n💡 Tip: Presiona Ctrl+C para detener el pipeline de forma segura\n")
        
        successful_scripts = []
        script_outputs = {}
        failed_script = None
        
        for script in SCRIPTS:
            success, output = run_script(script)
            
            if success:
                successful_scripts.append(script)
                script_outputs[script] = output
            else:
                failed_script = script
                break
        
        # Resumen final
        print("\n" + "="*80)
        print("RESUMEN DE EJECUCIÓN")
        print("="*80)
        
        if successful_scripts:
            print(f"\n✓ Scripts completados exitosamente ({len(successful_scripts)}):")
            for script in successful_scripts:
                print(f"  - {script}")
        
        if failed_script:
            print(f"\n✗ Pipeline detenido en: {failed_script}")
            print(f"  Total ejecutados: {len(successful_scripts)}/{len(SCRIPTS)}")
            sys.exit(1)
        else:
            print(f"\n✓ PIPELINE COMPLETO EJECUTADO EXITOSAMENTE")
            print(f"  Total ejecutados: {len(SCRIPTS)}/{len(SCRIPTS)}")
            
            # Mostrar resúmenes detallados de cada operación
            if script_outputs:
                print_summary(script_outputs)
            
            sys.exit(0)
    
    except KeyboardInterrupt:
        print("\n\n" + "="*80)
        print("⚠️  PIPELINE INTERRUMPIDO POR EL USUARIO")
        print("="*80)
        print("\n✓ Interrupción limpia completada")
        print(f"  Scripts ejecutados antes de la interrupción: {len(successful_scripts)}/{len(SCRIPTS)}")
        if successful_scripts:
            print("\n  Scripts completados:")
            for script in successful_scripts:
                print(f"    - {script}")
        sys.exit(130)  # Código de salida estándar para Ctrl+C

if __name__ == "__main__":
    main()
