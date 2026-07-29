FROM python:3.11-slim
LABEL maintainer="TFG Backend"
LABEL description="API para extraer y analizar datos de GitHub"
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
COPY config/ ./config/
COPY preservation/ ./preservation/
RUN mkdir -p logs results && useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 ENVIRONMENT=production DEBUG=False PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 CMD python -c "import requests; requests.get('http://localhost:8000/api/v1/health/ready', timeout=5).raise_for_status()" || exit 1
CMD uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT:-8000}
