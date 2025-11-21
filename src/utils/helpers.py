"""
Funciones auxiliares y utilidades generales.
"""
import json
from typing import Any, Dict, List
from pathlib import Path


def save_to_json(data: Any, filepath: str, indent: int = 2):
    """
    Guarda datos en un archivo JSON.
    
    Args:
        data: Datos a guardar
        filepath: Ruta del archivo
        indent: Indentación del JSON
    """
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=indent, ensure_ascii=False, default=str)


def load_from_json(filepath: str) -> Any:
    """
    Carga datos desde un archivo JSON.
    
    Args:
        filepath: Ruta del archivo
        
    Returns:
        Datos cargados
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def flatten_dict(d: Dict, parent_key: str = '', sep: str = '_') -> Dict:
    """
    Aplana un diccionario anidado.
    
    Args:
        d: Diccionario a aplanar
        parent_key: Clave padre para recursión
        sep: Separador de claves
        
    Returns:
        Diccionario aplanado
    """
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def chunk_list(lst: List, chunk_size: int) -> List[List]:
    """
    Divide una lista en chunks de tamaño específico.
    
    Args:
        lst: Lista a dividir
        chunk_size: Tamaño de cada chunk
        
    Returns:
        Lista de chunks
    """
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


def sanitize_string(s: str) -> str:
    """
    Sanitiza una cadena eliminando caracteres problemáticos.
    
    Args:
        s: Cadena a sanitizar
        
    Returns:
        Cadena sanitizada
    """
    if not s:
        return ""
    
    # Eliminar caracteres de control
    sanitized = ''.join(char for char in s if ord(char) >= 32 or char in '\n\t')
    return sanitized.strip()


def format_bytes(bytes_size: int) -> str:
    """
    Formatea un tamaño en bytes a una representación legible.
    
    Args:
        bytes_size: Tamaño en bytes
        
    Returns:
        Tamaño formateado (ej: "1.5 MB")
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} PB"


def safe_get(d: Dict, *keys, default=None):
    """
    Obtiene un valor de un diccionario anidado de forma segura.
    
    Args:
        d: Diccionario
        keys: Claves anidadas
        default: Valor por defecto si no se encuentra
        
    Returns:
        Valor encontrado o default
    """
    for key in keys:
        if isinstance(d, dict):
            d = d.get(key)
        else:
            return default
        if d is None:
            return default
    return d


def merge_dicts(*dicts: Dict) -> Dict:
    """
    Fusiona múltiples diccionarios.
    
    Args:
        dicts: Diccionarios a fusionar
        
    Returns:
        Diccionario fusionado
    """
    result = {}
    for d in dicts:
        if d:
            result.update(d)
    return result
