"""
Utilidades para manejo de fechas y tiempo.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional


def now_utc() -> datetime:
    """
    Obtiene la fecha y hora actual en UTC.
    
    Returns:
        Datetime en UTC
    """
    return datetime.now(timezone.utc)


def parse_iso_datetime(dt_string: str) -> Optional[datetime]:
    """
    Parsea una cadena de fecha en formato ISO 8601.
    
    Args:
        dt_string: Cadena de fecha
        
    Returns:
        Objeto datetime o None si falla el parseo
    """
    if not dt_string:
        return None
    
    try:
        # GitHub usa formato ISO 8601 con Z
        if dt_string.endswith('Z'):
            dt_string = dt_string.replace('Z', '+00:00')
        return datetime.fromisoformat(dt_string)
    except (ValueError, AttributeError):
        return None


def format_datetime(dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    Formatea un datetime a string.
    
    Args:
        dt: Objeto datetime
        format_str: Formato de salida
        
    Returns:
        Fecha formateada como string
    """
    if not dt:
        return ""
    return dt.strftime(format_str)


def time_ago(dt: datetime) -> str:
    """
    Calcula cuánto tiempo ha pasado desde una fecha.
    
    Args:
        dt: Fecha a comparar
        
    Returns:
        Descripción del tiempo transcurrido
    """
    if not dt:
        return "Desconocido"
    
    # Asegurar que ambas fechas tengan timezone
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    now = now_utc()
    diff = now - dt
    
    seconds = diff.total_seconds()
    
    if seconds < 60:
        return f"Hace {int(seconds)} segundos"
    elif seconds < 3600:
        return f"Hace {int(seconds / 60)} minutos"
    elif seconds < 86400:
        return f"Hace {int(seconds / 3600)} horas"
    elif seconds < 604800:
        return f"Hace {int(seconds / 86400)} días"
    elif seconds < 2592000:
        return f"Hace {int(seconds / 604800)} semanas"
    elif seconds < 31536000:
        return f"Hace {int(seconds / 2592000)} meses"
    else:
        return f"Hace {int(seconds / 31536000)} años"


def add_days(dt: datetime, days: int) -> datetime:
    """
    Añade días a una fecha.
    
    Args:
        dt: Fecha base
        days: Número de días a añadir
        
    Returns:
        Nueva fecha
    """
    return dt + timedelta(days=days)


def add_hours(dt: datetime, hours: int) -> datetime:
    """
    Añade horas a una fecha.
    
    Args:
        dt: Fecha base
        hours: Número de horas a añadir
        
    Returns:
        Nueva fecha
    """
    return dt + timedelta(hours=hours)


def get_date_range(start: datetime, end: datetime) -> int:
    """
    Calcula la diferencia en días entre dos fechas.
    
    Args:
        start: Fecha de inicio
        end: Fecha de fin
        
    Returns:
        Número de días de diferencia
    """
    diff = end - start
    return diff.days


def is_recent(dt: datetime, days: int = 7) -> bool:
    """
    Verifica si una fecha es reciente (dentro de los últimos N días).
    
    Args:
        dt: Fecha a verificar
        days: Número de días para considerar reciente
        
    Returns:
        True si es reciente, False en caso contrario
    """
    if not dt:
        return False
    
    # Asegurar timezone
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    now = now_utc()
    diff = now - dt
    return diff.days <= days


def to_timestamp(dt: datetime) -> int:
    """
    Convierte un datetime a timestamp Unix.
    
    Args:
        dt: Objeto datetime
        
    Returns:
        Timestamp Unix
    """
    return int(dt.timestamp())


def from_timestamp(timestamp: int) -> datetime:
    """
    Convierte un timestamp Unix a datetime.
    
    Args:
        timestamp: Timestamp Unix
        
    Returns:
        Objeto datetime en UTC
    """
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)
