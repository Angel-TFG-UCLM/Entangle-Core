# Dockerfile para TFG Backend
FROM python:3.11-slim

# Establecer directorio de trabajo
WORKDIR /app

# Copiar requirements
COPY requirements.txt .

# Instalar dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código fuente
COPY src/ ./src/
COPY tests/ ./tests/

# Exponer puerto de la API
EXPOSE 8000

# Variables de entorno por defecto
ENV PYTHONUNBUFFERED=1
ENV ENVIRONMENT=production
ENV DEBUG=False

# Comando para ejecutar la aplicación
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
