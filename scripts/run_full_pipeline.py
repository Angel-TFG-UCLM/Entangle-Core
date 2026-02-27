#!/usr/bin/env python3
"""
Script para ejecutar el pipeline completo de ingesta y enriquecimiento - v3.0

MEJORA v3.0: Ejecución paralela por fases con dependencias correctas.
- Fase 1: repos_ingestion (base de datos de repos)
- Fase 2: repos_enrichment (enriquece repos con collaborators, stats, etc.)
- Fase 3: user_ingestion + org_ingestion (en paralelo, dependen de datos de enrichment)
- Fase 4: user_enrichment + org_enrichment (en paralelo)

NOTA: user_ingestion lee el campo 'collaborators' de los repos, que se llena 
en la Estrategia 18 del enrichment. Por tanto, DEBE ejecutarse DESPUÉS del 
enriquecimiento de repos, no en paralelo con él.

Configuración:
    La configuración se lee desde: Backend/config/pipeline_config.json
    - auto_confirm: Auto-confirma todas las operaciones
    - parallel_phases: Ejecutar fases independientes en paralelo (default: true)
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
import time
from pathlib import Path
from threading import Thread
from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ==================== DEFINICIÓN DE FASES ====================
# Las fases se ejecutan secuencialmente, pero los scripts DENTRO de cada fase
# pueden ejecutarse en paralelo si parallel_phases=true.
#
# Dependencias reales:
#   repos_ingestion → repos_enrichment → user_ingestion (usa campo 'collaborators')
#   repos_ingestion → repos_enrichment → org_ingestion (mejor datos de owner)
#   user_ingestion → user_enrichment
#   org_ingestion → org_enrichment
#
# NOTA IMPORTANTE: user_ingestion lee 'collaborators' de repos, que se popula
# en la Estrategia 18 del enrichment. DEBE ejecutarse DESPUÉS del enrichment.

PIPELINE_PHASES = [
    {
        "name": "Fase 1: Ingesta de Repositorios",
        "description": "Base de datos de repos (todo depende de esto)",
        "scripts": ["run_repositories_ingestion.py"]
    },
    {
        "name": "Fase 2: Enriquecimiento de Repositorios",
        "description": "Enriquece repos con collaborators, stats, releases, etc.",
        "scripts": ["run_repositories_enrichment.py"]
    },
    {
        "name": "Fase 3: Ingesta de Usuarios y Organizaciones",
        "description": "Extraen datos desde repos enriquecidos (en paralelo)",
        "scripts": [
            "run_user_ingestion.py",
            "run_organization_ingestion.py"
        ]
    },
    {
        "name": "Fase 4: Enriquecimiento de Usuarios y Organizaciones",
        "description": "Enriquecen usuarios y organizaciones ya ingestados (en paralelo)",
        "scripts": [
            "run_user_enrichment.py",
            "run_organization_enrichment.py"
        ]
    }
]

# Lista plana para compatibilidad (modo secuencial)
ALL_SCRIPTS = [script for phase in PIPELINE_PHASES for script in phase["scripts"]]

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
                'batch_size': 100,  # ✅ OPTIMIZADO para vCore M30
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
    
    # Modo de ingesta (incremental o from_scratch)
    ingestion_mode = PIPELINE_CONFIG.get('pipeline', {}).get('mode', 'incremental')
    max_workers = str(PIPELINE_CONFIG.get('pipeline', {}).get('max_workers', 4))
    
    # Propagar modo a todos los scripts de ingesta
    if 'ingestion' in script_name:
        env['INGESTION_MODE'] = ingestion_mode
        env['MAX_WORKERS'] = max_workers
    
    enrichment = PIPELINE_CONFIG.get('enrichment', {})
    batch_size = enrichment.get('batch_size', 100)  # ✅ OPTIMIZADO para vCore M30
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

def run_script(script_name, quiet=False):
    """
    Ejecuta un script y retorna una tupla (éxito, salida capturada, duración_segundos).
    
    Args:
        script_name: Nombre del script a ejecutar
        quiet: Si True, captura output sin imprimir en tiempo real (para ejecución paralela)
    """
    if not quiet:
        print(f"\n{'='*80}")
        print(f"EJECUTANDO: {script_name}")
        print(f"{'='*80}\n")
    
    script_path = Path(__file__).parent / script_name
    output_lines = []
    process = None
    start_time = time.time()
    
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
                if not quiet:
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
        elapsed = time.time() - start_time
        
        # Asegurarse de cerrar stdin
        try:
            process.stdin.close()
        except:
            pass
        
        if return_code == 0:
            if not quiet:
                print(f"\n✓ {script_name} completado exitosamente ({elapsed:.1f}s)\n")
            return True, ''.join(output_lines), elapsed
        else:
            if not quiet:
                print(f"\n✗ {script_name} falló con código de salida {return_code} ({elapsed:.1f}s)\n")
            return False, ''.join(output_lines), elapsed
    
    except KeyboardInterrupt:
        elapsed = time.time() - start_time
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
        elapsed = time.time() - start_time
        return False, str(e), elapsed


def run_phase_parallel(phase_scripts):
    """
    Ejecuta múltiples scripts en paralelo usando ThreadPoolExecutor.
    Captura output de cada uno y lo muestra al finalizar.
    
    Args:
        phase_scripts: Lista de nombres de scripts a ejecutar en paralelo
        
    Returns:
        Lista de tuplas (script_name, success, output, elapsed)
    """
    results = []
    
    with ThreadPoolExecutor(max_workers=len(phase_scripts)) as executor:
        futures = {
            executor.submit(run_script, script, quiet=True): script
            for script in phase_scripts
        }
        
        for future in as_completed(futures):
            script_name = futures[future]
            try:
                success, output, elapsed = future.result()
                results.append((script_name, success, output, elapsed))
            except KeyboardInterrupt:
                raise
            except Exception as e:
                results.append((script_name, False, str(e), 0))
    
    return results

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
        
        # Buscar errores (excluir líneas con "0 error")
        if 'error' in line_lower and '0 error' not in line_lower:
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
    Función principal que ejecuta el pipeline por fases.
    Fases con múltiples scripts se ejecutan en paralelo si parallel_phases=true.
    """
    try:
        enrichment = PIPELINE_CONFIG.get('enrichment', {})
        pipeline_cfg = PIPELINE_CONFIG.get('pipeline', {})
        parallel_enabled = pipeline_cfg.get('parallel_phases', True)
        stop_on_error = pipeline_cfg.get('stop_on_error', True)
        
        print("\n" + "="*80)
        print("PIPELINE COMPLETO DE INGESTA Y ENRIQUECIMIENTO v3.0")
        print("="*80)
        print("\n📋 CONFIGURACIÓN:")
        print(f"  • Ejecución paralela por fases: {'Sí' if parallel_enabled else 'No (secuencial)'}")
        print(f"  • Auto-confirmar operaciones: {pipeline_cfg.get('auto_confirm', True)}")
        print(f"  • Modo: {pipeline_cfg.get('mode', 'incremental')}")
        print(f"  • Límite repositorios: {enrichment.get('repositories', {}).get('limit') or 'Todos'}")
        print(f"  • Límite usuarios: {enrichment.get('users', {}).get('limit') or 'Todos'}")
        print(f"  • Límite organizaciones: {enrichment.get('organizations', {}).get('limit') or 'Todos'}")
        print(f"  • Tamaño de lote: {enrichment.get('batch_size', 100)}")
        print(f"  • Forzar re-enriquecimiento: {enrichment.get('force_reenrichment', False)}")
        
        if parallel_enabled:
            print(f"\n  📊 FASES:")
            for phase in PIPELINE_PHASES:
                mode = "paralelo" if len(phase["scripts"]) > 1 else "secuencial"
                print(f"    • {phase['name']} ({len(phase['scripts'])} scripts, {mode})")
        
        print("="*80)
        print("\n💡 Tip: Presiona Ctrl+C para detener el pipeline de forma segura\n")
        
        successful_scripts = []
        script_outputs = {}
        script_timings = {}
        failed_script = None
        pipeline_start = time.time()
        
        for phase_idx, phase in enumerate(PIPELINE_PHASES):
            phase_name = phase["name"]
            phase_scripts = phase["scripts"]
            
            # Filtrar scripts según entities configuradas
            entities = pipeline_cfg.get('entities')
            if entities:
                phase_scripts = _filter_scripts_by_entities(phase_scripts, entities)
            
            if not phase_scripts:
                print(f"\n⏭️  {phase_name}: Sin scripts a ejecutar (filtrado por entities)")
                continue
            
            print(f"\n{'='*80}")
            print(f"🚀 {phase_name}")
            print(f"   {phase['description']}")
            print(f"{'='*80}")
            
            phase_start = time.time()
            
            if parallel_enabled and len(phase_scripts) > 1:
                # ==================== EJECUCIÓN PARALELA ====================
                print(f"\n⚡ Ejecutando {len(phase_scripts)} scripts en PARALELO:")
                for s in phase_scripts:
                    print(f"   🔄 {s}")
                print()
                
                results = run_phase_parallel(phase_scripts)
                
                # Procesar resultados
                phase_failed = False
                for script_name, success, output, elapsed in results:
                    script_timings[script_name] = elapsed
                    
                    if success:
                        successful_scripts.append(script_name)
                        script_outputs[script_name] = output
                        print(f"  ✅ {script_name} ({elapsed:.1f}s)")
                    else:
                        print(f"  ❌ {script_name} FALLÓ ({elapsed:.1f}s)")
                        # Mostrar últimas líneas de output del script fallido
                        error_lines = output.strip().split('\n')[-5:]
                        for line in error_lines:
                            print(f"     {line}")
                        
                        if stop_on_error:
                            failed_script = script_name
                            phase_failed = True
                
                phase_elapsed = time.time() - phase_start
                print(f"\n  ⏱️  {phase_name}: {phase_elapsed:.1f}s")
                
                if phase_failed:
                    break
                    
            else:
                # ==================== EJECUCIÓN SECUENCIAL ====================
                for script in phase_scripts:
                    success, output, elapsed = run_script(script)
                    script_timings[script] = elapsed
                    
                    if success:
                        successful_scripts.append(script)
                        script_outputs[script] = output
                    else:
                        failed_script = script
                        break
                
                if failed_script:
                    break
                
                phase_elapsed = time.time() - phase_start
                print(f"\n  ⏱️  {phase_name}: {phase_elapsed:.1f}s")
        
        # ==================== RESUMEN FINAL ====================
        pipeline_elapsed = time.time() - pipeline_start
        
        print("\n" + "="*80)
        print("RESUMEN DE EJECUCIÓN")
        print("="*80)
        
        if successful_scripts:
            print(f"\n✅ Scripts completados ({len(successful_scripts)}/{len(ALL_SCRIPTS)}):")
            for script in successful_scripts:
                t = script_timings.get(script, 0)
                print(f"  ✓ {script} ({t:.1f}s)")
        
        if failed_script:
            print(f"\n❌ Pipeline detenido en: {failed_script}")
        else:
            print(f"\n✅ PIPELINE COMPLETO EJECUTADO EXITOSAMENTE")
        
        # Timing summary
        print(f"\n⏱️  TIEMPOS:")
        print(f"  • Tiempo total pipeline: {pipeline_elapsed:.1f}s ({pipeline_elapsed/60:.1f} min)")
        
        if parallel_enabled:
            sequential_total = sum(script_timings.values())
            saved = sequential_total - pipeline_elapsed
            if saved > 0:
                print(f"  • Tiempo secuencial estimado: {sequential_total:.1f}s ({sequential_total/60:.1f} min)")
                print(f"  • ⚡ Tiempo ahorrado por paralelismo: {saved:.1f}s ({saved/60:.1f} min)")
        
        # Mostrar resúmenes detallados
        if script_outputs:
            print_summary(script_outputs)
        
        sys.exit(0 if not failed_script else 1)
    
    except KeyboardInterrupt:
        pipeline_elapsed = time.time() - pipeline_start if 'pipeline_start' in dir() else 0
        print("\n\n" + "="*80)
        print("⚠️  PIPELINE INTERRUMPIDO POR EL USUARIO")
        print("="*80)
        print("\n✓ Interrupción limpia completada")
        if 'successful_scripts' in dir():
            print(f"  Scripts ejecutados: {len(successful_scripts)}/{len(ALL_SCRIPTS)}")
            if successful_scripts:
                for script in successful_scripts:
                    print(f"    ✓ {script}")
        sys.exit(130)


def _filter_scripts_by_entities(scripts, entities):
    """Filtra scripts según las entities configuradas."""
    entity_map = {
        "repositories": ["run_repositories_ingestion.py", "run_repositories_enrichment.py"],
        "users": ["run_user_ingestion.py", "run_user_enrichment.py"],
        "organizations": ["run_organization_ingestion.py", "run_organization_enrichment.py"]
    }
    
    allowed = set()
    for entity in entities:
        allowed.update(entity_map.get(entity, []))
    
    return [s for s in scripts if s in allowed]

if __name__ == "__main__":
    main()
