"""
Configuración del proyecto.
Carga variables de entorno y configuración global.
"""
import os
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()


class Config:
    """Configuración general del proyecto."""
    
    # GitHub
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
    GITHUB_API_URL = "https://api.github.com/graphql"
    
    # MongoDB
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "quantum_github")
    
    # API Configuration
    # Azure Container Apps uses PORT environment variable
    API_HOST = os.getenv("API_HOST", "0.0.0.0")
    API_PORT = int(os.getenv("PORT", os.getenv("API_PORT", "8000")))
    
    # Entorno
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
    DEBUG = os.getenv("DEBUG", "True").lower() == "true"
    
    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    
    @classmethod
    def validate(cls):
        """Valida que las configuraciones críticas estén presentes."""
        if not cls.GITHUB_TOKEN:
            raise ValueError("GITHUB_TOKEN no está configurado")
        if not cls.MONGO_URI:
            raise ValueError("MONGO_URI no está configurado")


class IngestionConfig:
    """
    Configuración de criterios de ingesta para repositorios de software cuántico.
    Carga los criterios desde un archivo JSON externo.
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Inicializa la configuración de ingesta.
        
        Args:
            config_path: Ruta al archivo de configuración JSON. 
                        Si es None, usa la ruta por defecto.
        """
        if config_path is None:
            # Ruta por defecto: config/ingestion_config.json
            base_dir = Path(__file__).parent.parent.parent
            config_path = base_dir / "config" / "ingestion_config.json"
        else:
            config_path = Path(config_path)
        
        self.config_path = config_path
        self._config_data: Dict[str, Any] = {}
        self._load_config()
    
    def _load_config(self):
        """Carga y valida el archivo de configuración."""
        # Importar logger aquí para evitar importación circular
        from .logger import logger
        
        try:
            if not self.config_path.exists():
                raise FileNotFoundError(
                    f"Archivo de configuración no encontrado: {self.config_path}"
                )
            
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self._config_data = json.load(f)
            
            logger.info(f"Configuración de ingesta cargada desde: {self.config_path}")
            self._validate_config()
            
        except FileNotFoundError as e:
            logger.error(f"Error: {e}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Error al parsear JSON: {e}")
            raise ValueError(f"Archivo JSON inválido: {self.config_path}")
        except Exception as e:
            logger.error(f"Error inesperado al cargar configuración: {e}")
            raise
    
    def _validate_config(self):
        """Valida que los parámetros requeridos estén presentes y sean del tipo correcto."""
        from .logger import logger
        
        required_fields = {
            "keywords": list,
            "languages": list,
            "min_stars": int,
            "max_inactivity_days": int,
            "exclude_forks": bool
        }
        
        # Validar campos requeridos
        for field, expected_type in required_fields.items():
            if field not in self._config_data:
                error_msg = f"Campo requerido ausente en configuración: {field}"
                logger.error(error_msg)
                raise ValueError(error_msg)
            
            value = self._config_data[field]
            if not isinstance(value, expected_type):
                error_msg = (
                    f"Tipo incorrecto para '{field}': "
                    f"esperado {expected_type.__name__}, "
                    f"obtenido {type(value).__name__}"
                )
                logger.error(error_msg)
                raise TypeError(error_msg)
        
        # Validar que las listas no estén vacías
        if not self._config_data["keywords"]:
            logger.warning("La lista de keywords está vacía")
        
        if not self._config_data["languages"]:
            logger.warning("La lista de languages está vacía")
        
        # Validar valores numéricos
        if self._config_data["min_stars"] < 0:
            error_msg = "min_stars no puede ser negativo"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        if self._config_data["max_inactivity_days"] < 0:
            error_msg = "max_inactivity_days no puede ser negativo"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        logger.info("Configuración de ingesta validada exitosamente")
    
    # Propiedades para acceder a los criterios de filtrado
    
    @property
    def keywords(self) -> List[str]:
        """Lista de palabras clave para identificar repositorios cuánticos."""
        return self._config_data.get("keywords", [])
    
    @property
    def languages(self) -> List[str]:
        """Lista de lenguajes de programación permitidos."""
        return self._config_data.get("languages", [])
    
    @property
    def min_stars(self) -> int:
        """Número mínimo de estrellas requeridas."""
        return self._config_data.get("min_stars", 0)
    
    @property
    def max_inactivity_days(self) -> int:
        """Máximo número de días de inactividad permitidos."""
        return self._config_data.get("max_inactivity_days", 365)
    
    @property
    def exclude_forks(self) -> bool:
        """Si se deben excluir los repositorios que son forks."""
        return self._config_data.get("exclude_forks", True)
    
    @property
    def min_contributors(self) -> int:
        """Número mínimo de contribuidores (opcional)."""
        return self._config_data.get("min_contributors", 1)
    
    @property
    def additional_filters(self) -> Dict[str, Any]:
        """Filtros adicionales opcionales."""
        return self._config_data.get("additional_filters", {})
    
    @property
    def description(self) -> str:
        """Descripción de la configuración."""
        return self._config_data.get("description", "")
    
    @property
    def version(self) -> str:
        """Versión de la configuración."""
        return self._config_data.get("version", "1.0")
    
    @property
    def segmentation(self) -> Optional[Dict[str, Any]]:
        """
        Configuración de segmentación para superar el límite de 1000 resultados.
        
        Returns:
            Dict con 'stars' (lista de rangos [min, max]) y 'created_years' (lista de años)
            o None si no está configurada la segmentación
        """
        return self._config_data.get("segmentation", None)
    
    @property
    def enable_segmentation(self) -> bool:
        """Si está habilitada la segmentación dinámica."""
        return self.segmentation is not None and self._config_data.get("enable_segmentation", False)
    
    def get_all_config(self) -> Dict[str, Any]:
        """
        Retorna toda la configuración como diccionario.
        
        Returns:
            Diccionario con toda la configuración cargada
        """
        return self._config_data.copy()
    
    def reload(self):
        """Recarga la configuración desde el archivo."""
        from .logger import logger
        logger.info("Recargando configuración de ingesta...")
        self._load_config()
    
    def __repr__(self) -> str:
        """Representación en string de la configuración."""
        return (
            f"IngestionConfig("
            f"keywords={len(self.keywords)}, "
            f"languages={len(self.languages)}, "
            f"min_stars={self.min_stars}, "
            f"max_inactivity_days={self.max_inactivity_days}"
            f")"
        )


# Instancia global de configuración
config = Config()

# Instancia global de configuración de ingesta
ingestion_config = IngestionConfig()


def load_ingestion_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Carga y retorna la configuración de ingesta completa.
    
    Args:
        config_path: Ruta opcional al archivo de configuración
        
    Returns:
        Diccionario con toda la configuración
    """
    if config_path:
        config_instance = IngestionConfig(config_path)
    else:
        config_instance = ingestion_config
    
    return config_instance.get_all_config()
