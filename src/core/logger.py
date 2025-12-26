"""
Sistema de logging del proyecto.
"""
import logging
import sys
import io
from pathlib import Path

from .config import config


def setup_logger(name: str = "tfg-backend") -> logging.Logger:
    """
    Configura y retorna un logger para el proyecto.
    
    Args:
        name: Nombre del logger
        
    Returns:
        Logger configurado
    """
    logger = logging.getLogger(name)
    
    # Evitar duplicar handlers si ya está configurado
    if logger.handlers:
        return logger
    
    # Nivel de logging según configuración
    level = logging.DEBUG if config.DEBUG else logging.INFO
    logger.setLevel(level)
    
    # Formato del log con información del módulo
    # %(module)s muestra el archivo .py donde se hace el log
    # %(funcName)s muestra la función donde se hace el log
    formatter = logging.Formatter(
        fmt="%(asctime)s - [%(levelname)s] - %(module)s.%(funcName)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Formato más detallado para archivo
    file_formatter = logging.Formatter(
        fmt="%(asctime)s - [%(levelname)s] - %(name)s - %(module)s.%(funcName)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Handler para consola con soporte UTF-8 para Windows
    # Envolver stdout con UTF-8 encoding para soportar emojis en Windows
    try:
        # Intentar reconfigurar stdout para UTF-8
        if sys.stdout.encoding != 'utf-8':
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except:
        pass  # Si falla, continuar con la configuración por defecto
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Crear directorio de logs
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Handler para archivo general (INFO y superior)
    info_file_handler = logging.FileHandler(
        log_dir / "app.log", 
        encoding="utf-8",
        mode='a'  # Append mode
    )
    info_file_handler.setLevel(logging.INFO)
    info_file_handler.setFormatter(file_formatter)
    logger.addHandler(info_file_handler)
    
    # Handler para archivo de errores (solo ERROR y CRITICAL)
    error_file_handler = logging.FileHandler(
        log_dir / "errors.log",
        encoding="utf-8",
        mode='a'
    )
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(file_formatter)
    logger.addHandler(error_file_handler)
    
    # En modo DEBUG, agregar archivo separado
    if config.DEBUG:
        debug_file_handler = logging.FileHandler(
            log_dir / "debug.log",
            encoding="utf-8",
            mode='a'
        )
        debug_file_handler.setLevel(logging.DEBUG)
        debug_file_handler.setFormatter(file_formatter)
        logger.addHandler(debug_file_handler)
    
    return logger


# Logger global del proyecto
logger = setup_logger()