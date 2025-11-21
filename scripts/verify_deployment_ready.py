"""
Script de verificación pre-despliegue.
Verifica que todo está listo para desplegar en Azure.
"""
import os
import sys
from pathlib import Path

def check_file_exists(file_path: str, description: str) -> bool:
    """Verifica si un archivo existe."""
    if Path(file_path).exists():
        print(f"✅ {description}: {file_path}")
        return True
    else:
        print(f"❌ {description} NO ENCONTRADO: {file_path}")
        return False

def check_env_file() -> bool:
    """Verifica que existe .env con las variables necesarias."""
    env_path = Path(".env")
    
    if not env_path.exists():
        print("❌ Archivo .env NO ENCONTRADO")
        print("   Copia .env.example a .env y configura las variables")
        return False
    
    # Leer y verificar variables críticas
    required_vars = ["GITHUB_TOKEN", "MONGO_URI", "MONGO_DB_NAME"]
    env_content = env_path.read_text()
    
    missing_vars = []
    for var in required_vars:
        if var not in env_content or f"{var}=your_" in env_content or f"{var}=tu_" in env_content:
            missing_vars.append(var)
    
    if missing_vars:
        print(f"❌ Variables de entorno sin configurar: {', '.join(missing_vars)}")
        print("   Edita .env con valores reales")
        return False
    
    print("✅ Archivo .env configurado correctamente")
    return True

def check_docker() -> bool:
    """Verifica que Docker está instalado y funcionando."""
    import subprocess
    
    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            text=True,
            check=True
        )
        print(f"✅ Docker instalado: {result.stdout.strip()}")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ Docker no está instalado o no está funcionando")
        print("   Instala Docker Desktop: https://www.docker.com/products/docker-desktop")
        return False

def check_azure_cli() -> bool:
    """Verifica que Azure CLI está instalado."""
    import subprocess
    
    try:
        result = subprocess.run(
            ["az", "--version"],
            capture_output=True,
            text=True,
            check=True
        )
        print("✅ Azure CLI instalado")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("⚠️  Azure CLI no está instalado (opcional)")
        print("   Instala con: winget install Microsoft.AzureCLI")
        return True  # No es crítico

def check_azd() -> bool:
    """Verifica que Azure Developer CLI está instalado."""
    import subprocess
    
    try:
        result = subprocess.run(
            ["azd", "version"],
            capture_output=True,
            text=True,
            check=True
        )
        print(f"✅ Azure Developer CLI instalado")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ Azure Developer CLI (azd) no está instalado")
        print("   Instala con: winget install microsoft.azd")
        return False

def main():
    """Ejecuta todas las verificaciones."""
    print("=" * 60)
    print("VERIFICACIÓN PRE-DESPLIEGUE EN AZURE")
    print("=" * 60)
    print()
    
    checks = []
    
    # Verificar archivos esenciales
    print("📁 Verificando archivos...")
    checks.append(check_file_exists("Dockerfile", "Dockerfile"))
    checks.append(check_file_exists("requirements.txt", "Requirements"))
    checks.append(check_file_exists("azure.yaml", "Configuración Azure"))
    checks.append(check_file_exists("infra/main.bicep", "Infraestructura Bicep"))
    checks.append(check_file_exists(".env.example", "Ejemplo de variables"))
    print()
    
    # Verificar .env
    print("🔑 Verificando variables de entorno...")
    checks.append(check_env_file())
    print()
    
    # Verificar herramientas
    print("🛠️  Verificando herramientas...")
    checks.append(check_docker())
    checks.append(check_azd())
    check_azure_cli()  # No crítico
    print()
    
    # Resumen
    print("=" * 60)
    if all(checks):
        print("✅ TODO LISTO PARA DESPLEGAR")
        print()
        print("Siguiente paso:")
        print("  azd auth login")
        print("  azd up")
        print()
        return 0
    else:
        print("❌ HAY PROBLEMAS QUE RESOLVER")
        print()
        print("Por favor, corrige los errores marcados con ❌")
        print()
        return 1

if __name__ == "__main__":
    sys.exit(main())
