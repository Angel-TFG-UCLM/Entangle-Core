"""
Script de prueba para el motor de ingesta (IngestionEngine).

Prueba el flujo completo:
1. Búsqueda de repositorios
2. Filtrado por criterios
3. Almacenamiento de resultados
"""

import sys
from pathlib import Path

# Agregar el directorio raíz al path
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from src.github.ingestion import IngestionEngine, run_ingestion
from src.core.logger import logger


def test_ingestion_engine_initialization():
    """Prueba 1: Inicialización del motor"""
    print("\n" + "=" * 80)
    print("TEST 1: Inicialización del IngestionEngine")
    print("=" * 80)
    
    try:
        engine = IngestionEngine()
        
        print("✓ Motor de ingesta inicializado correctamente")
        print(f"  - Cliente GraphQL: {engine.client is not None}")
        print(f"  - Configuración: {engine.config is not None}")
        print(f"  - Base de datos: {engine.db is not None}")
        print(f"  - Estadísticas inicializadas: {len(engine.stats)} campos")
        
        return True
        
    except Exception as e:
        print(f"✗ Error en inicialización: {e}")
        return False


def test_ingestion_search_only():
    """Prueba 2: Solo búsqueda (sin filtrado ni guardado)"""
    print("\n" + "=" * 80)
    print("TEST 2: Búsqueda de repositorios (máx. 10)")
    print("=" * 80)
    
    try:
        engine = IngestionEngine()
        
        # Buscar solo 10 repos para prueba rápida
        repositories = engine._search_repositories(max_results=10)
        
        print(f"✓ Búsqueda completada")
        print(f"  - Repositorios encontrados: {len(repositories)}")
        
        if repositories:
            first_repo = repositories[0]
            print(f"\nPrimer repositorio:")
            print(f"  - Nombre: {first_repo.get('nameWithOwner')}")
            print(f"  - Estrellas: {first_repo.get('stargazerCount')}")
            print(f"  - Lenguaje: {first_repo.get('primaryLanguage', {}).get('name')}")
            print(f"  - Fork: {first_repo.get('isFork')}")
        
        return True
        
    except Exception as e:
        print(f"✗ Error en búsqueda: {e}")
        logger.error(f"Error en búsqueda: {e}", exc_info=True)
        return False


def test_ingestion_with_filtering():
    """Prueba 3: Búsqueda + Filtrado (sin guardado)"""
    print("\n" + "=" * 80)
    print("TEST 3: Búsqueda + Filtrado (máx. 20)")
    print("=" * 80)
    
    try:
        engine = IngestionEngine()
        
        # Buscar
        repositories = engine._search_repositories(max_results=20)
        print(f"Repositorios encontrados: {len(repositories)}")
        
        # Filtrar
        filtered = engine.filter_repositories(repositories)
        print(f"Repositorios después de filtrado: {len(filtered)}")
        
        # Mostrar estadísticas de filtrado
        print(f"\nEstadísticas de filtrado:")
        print(f"  - Rechazados por fork: {engine.stats['filtered_by_fork']}")
        print(f"  - Rechazados por estrellas: {engine.stats['filtered_by_stars']}")
        print(f"  - Rechazados por lenguaje: {engine.stats['filtered_by_language']}")
        print(f"  - Rechazados por inactividad: {engine.stats['filtered_by_inactivity']}")
        print(f"  - Rechazados por keywords: {engine.stats['filtered_by_keywords']}")
        
        if filtered:
            print(f"\nRepositorios que pasaron filtros:")
            for i, repo in enumerate(filtered[:5], 1):
                print(f"  {i}. {repo.get('nameWithOwner')} "
                      f"({repo.get('stargazerCount')} ⭐)")
        
        return True
        
    except Exception as e:
        print(f"✗ Error en filtrado: {e}")
        logger.error(f"Error en filtrado: {e}", exc_info=True)
        return False


def test_ingestion_full_flow_json_only():
    """Prueba 4: Flujo completo (solo guardado en JSON)"""
    print("\n" + "=" * 80)
    print("TEST 4: Flujo completo con guardado JSON (máx. 15)")
    print("=" * 80)
    
    try:
        engine = IngestionEngine()
        
        # Ejecutar flujo completo
        report = engine.run(
            max_results=15,
            save_to_db=False,  # No guardar en MongoDB para prueba rápida
            save_to_json=True,
            output_file="tests/test_ingestion_results.json"
        )
        
        print(f"\n✓ Flujo completo ejecutado correctamente")
        print(f"\nResumen:")
        print(f"  - Encontrados: {report['summary']['total_found']}")
        print(f"  - Válidos: {report['summary']['total_filtered']}")
        print(f"  - Guardados: {report['summary']['total_saved']}")
        print(f"  - Tasa de éxito: {report['summary']['success_rate']}")
        print(f"  - Duración: {report['summary']['duration_seconds']:.2f}s")
        
        print(f"\nDistribución por lenguaje:")
        for lang, count in sorted(
            report['statistics']['languages'].items(),
            key=lambda x: x[1],
            reverse=True
        ):
            print(f"  - {lang}: {count}")
        
        print(f"\nEstadísticas de estrellas:")
        print(f"  - Promedio: {report['statistics']['average_stars']}")
        print(f"  - Máximo: {report['statistics']['max_stars']}")
        print(f"  - Mínimo: {report['statistics']['min_stars']}")
        
        return True
        
    except Exception as e:
        print(f"✗ Error en flujo completo: {e}")
        logger.error(f"Error en flujo completo: {e}", exc_info=True)
        return False


def test_ingestion_helper_function():
    """Prueba 5: Función helper run_ingestion()"""
    print("\n" + "=" * 80)
    print("TEST 5: Función helper run_ingestion() (máx. 10)")
    print("=" * 80)
    
    try:
        # Usar función helper
        report = run_ingestion(
            max_results=10,
            save_to_db=False,
            save_to_json=True,
            output_file="tests/test_helper_results.json"
        )
        
        print(f"✓ Función helper ejecutada correctamente")
        print(f"  - Repositorios válidos: {report['summary']['total_filtered']}")
        print(f"  - Archivo generado: tests/test_helper_results.json")
        
        return True
        
    except Exception as e:
        print(f"✗ Error en función helper: {e}")
        logger.error(f"Error en función helper: {e}", exc_info=True)
        return False


def test_individual_filters():
    """Prueba 6: Prueba de filtros individuales"""
    print("\n" + "=" * 80)
    print("TEST 6: Prueba de filtros individuales")
    print("=" * 80)
    
    try:
        engine = IngestionEngine()
        
        # Repositorio de prueba con todos los campos
        test_repo = {
            "id": "test123",
            "nameWithOwner": "test/quantum-repo",
            "name": "quantum-repo",
            "description": "A quantum computing library",
            "isFork": False,
            "stargazerCount": 50,
            "primaryLanguage": {"name": "Python"},
            "updatedAt": "2024-01-15T10:00:00Z",
            "repositoryTopics": {
                "nodes": [
                    {"topic": {"name": "quantum"}}
                ]
            }
        }
        
        # Probar cada filtro
        print("\nRepositorio de prueba:")
        print(f"  - Nombre: {test_repo['nameWithOwner']}")
        print(f"  - Fork: {test_repo['isFork']}")
        print(f"  - Estrellas: {test_repo['stargazerCount']}")
        print(f"  - Lenguaje: {test_repo['primaryLanguage']['name']}")
        
        print("\nResultados de filtros:")
        print(f"  - Filtro fork: {'✓ PASA' if engine._filter_by_fork(test_repo) else '✗ RECHAZA'}")
        print(f"  - Filtro stars: {'✓ PASA' if engine._filter_by_stars(test_repo) else '✗ RECHAZA'}")
        print(f"  - Filtro language: {'✓ PASA' if engine._filter_by_language(test_repo) else '✗ RECHAZA'}")
        print(f"  - Filtro inactivity: {'✓ PASA' if engine._filter_by_inactivity(test_repo) else '✗ RECHAZA'}")
        print(f"  - Filtro keywords: {'✓ PASA' if engine._filter_by_keywords(test_repo) else '✗ RECHAZA'}")
        
        # Probar repo que debería ser rechazado
        rejected_repo = {
            "id": "test456",
            "nameWithOwner": "test/random-repo",
            "name": "random-repo",
            "description": "A random library",
            "isFork": True,
            "stargazerCount": 5,
            "primaryLanguage": {"name": "Go"},
            "updatedAt": "2020-01-15T10:00:00Z",
            "repositoryTopics": {"nodes": []}
        }
        
        print("\n\nRepositorio que debería ser rechazado:")
        print(f"  - Nombre: {rejected_repo['nameWithOwner']}")
        print(f"  - Fork: {rejected_repo['isFork']}")
        print(f"  - Estrellas: {rejected_repo['stargazerCount']}")
        print(f"  - Lenguaje: {rejected_repo['primaryLanguage']['name']}")
        
        print("\nResultados de filtros:")
        print(f"  - Filtro fork: {'✓ PASA' if engine._filter_by_fork(rejected_repo) else '✗ RECHAZA'}")
        print(f"  - Filtro stars: {'✓ PASA' if engine._filter_by_stars(rejected_repo) else '✗ RECHAZA'}")
        print(f"  - Filtro language: {'✓ PASA' if engine._filter_by_language(rejected_repo) else '✗ RECHAZA'}")
        print(f"  - Filtro inactivity: {'✓ PASA' if engine._filter_by_inactivity(rejected_repo) else '✗ RECHAZA'}")
        print(f"  - Filtro keywords: {'✓ PASA' if engine._filter_by_keywords(rejected_repo) else '✗ RECHAZA'}")
        
        return True
        
    except Exception as e:
        print(f"✗ Error en prueba de filtros: {e}")
        logger.error(f"Error en prueba de filtros: {e}", exc_info=True)
        return False


def main():
    """Ejecuta todas las pruebas"""
    print("\n" + "=" * 80)
    print("PRUEBAS DEL MOTOR DE INGESTA (IngestionEngine)")
    print("=" * 80)
    
    tests = [
        ("Inicialización", test_ingestion_engine_initialization),
        ("Búsqueda", test_ingestion_search_only),
        ("Filtrado", test_ingestion_with_filtering),
        ("Flujo completo JSON", test_ingestion_full_flow_json_only),
        ("Función helper", test_ingestion_helper_function),
        ("Filtros individuales", test_individual_filters)
    ]
    
    results = []
    
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ Error crítico en test '{name}': {e}")
            logger.error(f"Error crítico en test '{name}': {e}", exc_info=True)
            results.append((name, False))
    
    # Resumen final
    print("\n" + "=" * 80)
    print("RESUMEN DE PRUEBAS")
    print("=" * 80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status} - {name}")
    
    print(f"\nResultado: {passed}/{total} pruebas pasadas")
    print(f"Tasa de éxito: {(passed/total*100):.1f}%")
    print("=" * 80)
    
    return passed == total


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nPruebas interrumpidas por el usuario")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error fatal: {e}")
        logger.error(f"Error fatal en pruebas: {e}", exc_info=True)
        sys.exit(1)
