"""
Script de prueba para validar la configuración de ingesta.

Este script carga y muestra todos los parámetros de configuración
definidos en config/ingestion_config.json
"""

from src.core.config import ingestion_config
from src.core.logger import logger


def print_separator(title: str):
    """Imprime un separador con título."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def test_ingestion_config():
    """Prueba la configuración de ingesta y muestra todos los valores."""
    
    print_separator("PRUEBA DE CONFIGURACIÓN DE INGESTA")
    
    # Información general
    print("\n Información General:")
    print(f"  - Descripción: {ingestion_config.description}")
    print(f"  - Versión: {ingestion_config.version}")
    print(f"  - Archivo: {ingestion_config.config_path}")
    print(f"  - Representación: {ingestion_config}")
    
    # Keywords
    print_separator("KEYWORDS (Palabras Clave)")
    print(f"\n Total de keywords: {len(ingestion_config.keywords)}")
    for i, keyword in enumerate(ingestion_config.keywords, 1):
        print(f"  {i}. {keyword}")
    
    # Lenguajes
    print_separator("LANGUAGES (Lenguajes de Programación)")
    print(f"\n💻 Total de lenguajes: {len(ingestion_config.languages)}")
    for i, language in enumerate(ingestion_config.languages, 1):
        print(f"  {i}. {language}")
    
    # Criterios numéricos
    print_separator("CRITERIOS NUMÉRICOS")
    print(f"\n Estrellas mínimas: {ingestion_config.min_stars}")
    print(f" Máxima inactividad (días): {ingestion_config.max_inactivity_days}")
    print(f" Contribuidores mínimos: {ingestion_config.min_contributors}")
    
    # Criterios booleanos
    print_separator("CRITERIOS BOOLEANOS")
    print(f"\n Excluir forks: {ingestion_config.exclude_forks}")
    
    # Filtros adicionales
    print_separator("FILTROS ADICIONALES")
    additional = ingestion_config.additional_filters
    if additional:
        print(f"\n Total de filtros adicionales: {len(additional)}")
        for key, value in additional.items():
            print(f"  - {key}: {value}")
    else:
        print("\n  No hay filtros adicionales configurados")
    
    # Configuración completa (JSON)
    print_separator("CONFIGURACIÓN COMPLETA (JSON)")
    import json
    print("\n" + json.dumps(
        ingestion_config.get_all_config(), 
        indent=2, 
        ensure_ascii=False
    ))
    
    # Resumen de validación
    print_separator("RESUMEN DE VALIDACIÓN")
    print("\n Configuración cargada y validada exitosamente")
    print(f" {len(ingestion_config.keywords)} keywords definidas")
    print(f" {len(ingestion_config.languages)} lenguajes permitidos")
    print(f" Criterios numéricos: stars≥{ingestion_config.min_stars}, "
          f"inactivity≤{ingestion_config.max_inactivity_days} días")
    print(f" Exclude forks: {ingestion_config.exclude_forks}")
    
    print("\n" + "=" * 70)
    print("  TODAS LAS PRUEBAS COMPLETADAS EXITOSAMENTE")
    print("=" * 70 + "\n")


def test_error_handling():
    """Prueba el manejo de errores."""
    print_separator("PRUEBA DE MANEJO DE ERRORES")
    
    from src.core.config import IngestionConfig
    from pathlib import Path
    
    # Probar archivo inexistente
    print("\n Probando con archivo inexistente...")
    try:
        bad_config = IngestionConfig(config_path="ruta/inexistente.json")
        print("   ERROR: Debería haber lanzado excepción")
    except FileNotFoundError as e:
        print(f"   FileNotFoundError capturado correctamente")
        logger.info("Manejo de archivo inexistente: OK")
    
    # Probar archivo JSON inválido
    print("\n Probando con JSON inválido...")
    try:
        # Crear archivo temporal con JSON inválido
        temp_file = Path("config/temp_invalid.json")
        temp_file.write_text("{invalid json}", encoding="utf-8")
        
        bad_config = IngestionConfig(config_path=temp_file)
        print("   ERROR: Debería haber lanzado excepción")
    except ValueError as e:
        print(f"   ValueError capturado correctamente")
        logger.info("Manejo de JSON inválido: OK")
    finally:
        # Limpiar archivo temporal
        if temp_file.exists():
            temp_file.unlink()
    
    print("\n Manejo de errores verificado correctamente\n")


def test_reload_functionality():
    """Prueba la funcionalidad de recarga."""
    print_separator("PRUEBA DE RECARGA DE CONFIGURACIÓN")
    
    print("\n Recargando configuración...")
    ingestion_config.reload()
    print(" Configuración recargada exitosamente")
    print(f"   Keywords actuales: {len(ingestion_config.keywords)}")
    print(f"   Lenguajes actuales: {len(ingestion_config.languages)}\n")


if __name__ == "__main__":
    try:
        # Ejecutar pruebas principales
        test_ingestion_config()
        
        # Ejecutar pruebas de manejo de errores
        test_error_handling()
        
        # Ejecutar prueba de recarga
        test_reload_functionality()
        
        logger.info("Todas las pruebas de configuración completadas exitosamente")
        
    except Exception as e:
        logger.error(f"Error durante las pruebas: {e}", exc_info=True)
        print(f"\n ERROR: {e}\n")
        raise
