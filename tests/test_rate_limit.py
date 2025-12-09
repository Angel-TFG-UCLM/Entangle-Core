"""
Script de prueba para verificar el manejo correcto del rate limit.
"""
import os
import sys
from datetime import datetime

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from src.github.graphql_client import GitHubGraphQLClient
from src.core.logger import logger

load_dotenv()

def test_rate_limit_rest():
    """Prueba el método _get_rate_limit_rest()"""
    logger.info("=" * 80)
    logger.info("🧪 TEST: Obteniendo rate limit con REST API")
    logger.info("=" * 80)
    
    client = GitHubGraphQLClient()
    
    try:
        rate_info = client._get_rate_limit_rest()
        
        # Mostrar información de todos los recursos
        resources = rate_info.get('resources', {})
        
        logger.info("\n📊 Rate Limit Status:")
        logger.info("-" * 80)
        
        for resource_name, resource_data in resources.items():
            limit = resource_data.get('limit', 0)
            remaining = resource_data.get('remaining', 0)
            reset_timestamp = resource_data.get('reset', 0)
            used = limit - remaining
            
            if reset_timestamp > 0:
                reset_time = datetime.fromtimestamp(reset_timestamp)
                reset_str = reset_time.strftime('%Y-%m-%d %H:%M:%S')
                now = datetime.now()
                wait_seconds = max(0, (reset_time - now).total_seconds())
                
                percentage = (remaining / limit * 100) if limit > 0 else 0
                
                logger.info(f"\n🔹 {resource_name.upper()}:")
                logger.info(f"   Límite: {limit} requests/hora")
                logger.info(f"   Usados: {used}")
                logger.info(f"   Restantes: {remaining} ({percentage:.1f}%)")
                logger.info(f"   Reset: {reset_str}")
                
                if wait_seconds > 0:
                    logger.info(f"   ⏳ Resetea en: {wait_seconds:.0f}s ({wait_seconds/60:.1f} min)")
                else:
                    logger.info(f"   ✅ Ya reseteado")
        
        logger.info("\n" + "=" * 80)
        logger.info("✅ Test completado exitosamente")
        
    except Exception as e:
        logger.error(f"❌ Error en el test: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    test_rate_limit_rest()
