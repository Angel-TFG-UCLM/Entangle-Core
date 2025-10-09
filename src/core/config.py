"""
Configuración del proyecto.
Carga variables de entorno y configuración global.
"""
import os
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
    
    # API
    #API_HOST = os.getenv("API_HOST", "0.0.0.0")
    #API_PORT = int(os.getenv("API_PORT", "8000"))
    
    # Entorno
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
    DEBUG = os.getenv("DEBUG", "True").lower() == "true"
    
    @classmethod
    def validate(cls):
        """Valida que las configuraciones críticas estén presentes."""
        if not cls.GITHUB_TOKEN:
            raise ValueError("GITHUB_TOKEN no está configurado")
        if not cls.MONGO_URI:
            raise ValueError("MONGO_URI no está configurado")


# Instancia global de configuración
config = Config()
