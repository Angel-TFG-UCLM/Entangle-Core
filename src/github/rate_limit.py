"""
Control de rate limit y reintentos automáticos para la API de GitHub.
"""
import time
from datetime import datetime
from typing import Callable, Any, Optional
from functools import wraps

from .graphql_client import github_client
from ..core.logger import logger


def get_rate_limit_info() -> dict:
    """
    Obtiene información del rate limit actual.
    
    Returns:
        Información del rate limit
    """
    rate_limit = github_client.get_rate_limit()
    logger.info(
        f"Rate limit - Remaining: {rate_limit.get('remaining')}/{rate_limit.get('limit')}, "
        f"Reset at: {rate_limit.get('resetAt')}"
    )
    return rate_limit


def wait_for_rate_limit_reset(reset_at: str):
    """
    Espera hasta que se resetee el rate limit.
    
    Args:
        reset_at: Timestamp ISO 8601 del reset
    """
    reset_time = datetime.fromisoformat(reset_at.replace('Z', '+00:00'))
    now = datetime.now(reset_time.tzinfo)
    
    if reset_time > now:
        wait_seconds = (reset_time - now).total_seconds() + 5  # 5 segundos extra de margen
        logger.warning(f"Rate limit alcanzado. Esperando {wait_seconds:.0f} segundos...")
        time.sleep(wait_seconds)
        logger.info("Rate limit reseteado. Continuando...")


def check_rate_limit_before_request():
    """
    Verifica el rate limit antes de hacer una petición.
    Si quedan pocos requests, espera al reset.
    """
    rate_limit = get_rate_limit_info()
    remaining = rate_limit.get("remaining", 0)
    
    # Si quedan menos de 10 requests, esperar al reset
    if remaining < 10:
        logger.warning(f"Quedan solo {remaining} requests. Esperando reset...")
        wait_for_rate_limit_reset(rate_limit.get("resetAt"))


def with_rate_limit_handling(max_retries: int = 3):
    """
    Decorador para manejar automáticamente el rate limit.
    
    Args:
        max_retries: Número máximo de reintentos
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            retries = 0
            
            while retries <= max_retries:
                try:
                    # Verificar rate limit antes de ejecutar
                    check_rate_limit_before_request()
                    
                    # Ejecutar la función
                    return func(*args, **kwargs)
                    
                except Exception as e:
                    error_msg = str(e).lower()
                    
                    # Si es un error de rate limit, esperar y reintentar
                    if "rate limit" in error_msg or "api rate limit exceeded" in error_msg:
                        logger.warning(f"Error de rate limit detectado: {e}")
                        
                        rate_limit = get_rate_limit_info()
                        wait_for_rate_limit_reset(rate_limit.get("resetAt"))
                        
                        retries += 1
                        if retries <= max_retries:
                            logger.info(f"Reintentando... (intento {retries}/{max_retries})")
                        continue
                    
                    # Si es otro tipo de error, propagarlo
                    raise
            
            # Si se agotaron los reintentos
            raise Exception(f"Se agotaron los {max_retries} reintentos por rate limit")
        
        return wrapper
    return decorator


class RateLimitMonitor:
    """Monitor para seguimiento del rate limit."""
    
    def __init__(self):
        self.last_check = None
        self.last_remaining = None
    
    def update(self):
        """Actualiza el estado del rate limit."""
        rate_limit = get_rate_limit_info()
        self.last_check = datetime.now()
        self.last_remaining = rate_limit.get("remaining")
        return rate_limit
    
    def get_status(self) -> dict:
        """Obtiene el estado actual del monitor."""
        return {
            "last_check": self.last_check,
            "last_remaining": self.last_remaining
        }


# Instancia global del monitor
rate_limit_monitor = RateLimitMonitor()
