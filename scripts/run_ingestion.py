#!/usr/bin/env python3
"""
Script para ejecutar la ingesta completa de datos desde GitHub a MongoDB.
"""
import sys
from src.github.ingestion import IngestionEngine
from src.github.graphql_client import github_client
from src.core.logger import logger


def main():
    """Ejecuta la ingesta de datos."""
    print("\n" + "="*80)
    print("  🚀 INICIANDO INGESTA DE DATOS DESDE GITHUB")
    print("="*80 + "\n")
    
    try:
        # Crear motor de ingesta
        # - incremental=False: Ingesta completa
        # - batch_size=50: Tamaño de lote para operaciones bulk
        engine = IngestionEngine(
            client=github_client,
            incremental=False,
            batch_size=50
        )
        
        # Parámetros de ingesta
        max_results = None  # None = sin límite (usar con cuidado)
        
        # Preguntar al usuario cuántos repositorios quiere ingestar
        print("💡 TIP: Para pruebas, usa un número pequeño (ej: 10-50)")
        print("        Para ingesta completa, presiona Enter (sin límite)\n")
        
        user_input = input("¿Cuántos repositorios quieres ingestar? [Enter = todos]: ").strip()
        
        if user_input:
            try:
                max_results = int(user_input)
                print(f"\n✅ Ingesta limitada a {max_results} repositorios\n")
            except ValueError:
                print("\n⚠️  Entrada inválida. Usando sin límite.\n")
        else:
            print("\n⚠️  ADVERTENCIA: Ingesta sin límite puede tardar mucho tiempo.\n")
            confirm = input("¿Estás seguro? (s/n): ").strip().lower()
            if confirm != 's':
                print("❌ Ingesta cancelada")
                return
        
        # Ejecutar ingesta
        print(f"\n{'='*80}")
        print("  🔄 PROCESANDO...")
        print(f"{'='*80}\n")
        
        report = engine.run(
            max_results=max_results,
            save_to_json=True,  # Guardar resultados en JSON
            output_file="results/ingestion_results.json"
        )
        
        # Mostrar resumen final
        print("\n" + "="*80)
        print("  ✅ INGESTA COMPLETADA EXITOSAMENTE")
        print("="*80)
        print(f"\n📊 RESUMEN FINAL:")
        print(f"  • Repositorios encontrados: {report['summary']['total_found']}")
        print(f"  • Repositorios válidos: {report['summary']['total_filtered']}")
        print(f"  • Insertados en MongoDB: {report['summary']['repositories_inserted']}")
        print(f"  • Actualizados: {report['summary']['repositories_updated']}")
        print(f"  • Relaciones creadas: {report['summary']['relations_created']}")
        print(f"  • Errores de validación: {report['summary']['validation_errors']}")
        
        duration = report['summary'].get('duration_seconds')
        if duration:
            print(f"\n⏱️  Tiempo total: {duration:.2f}s")
        else:
            print(f"\n⏱️  Tiempo total: {report['timing']['total']}")
        print(f"\n📄 Resultados guardados en: results/ingestion_results.json")
        print("\n" + "="*80 + "\n")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Ingesta interrumpida por el usuario")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Error durante la ingesta: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
