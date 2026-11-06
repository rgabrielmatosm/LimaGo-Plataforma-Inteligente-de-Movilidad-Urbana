# Imagen común para el backend (FastAPI) y el worker de simulación.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# Código y datos (la red vial ya descargada viaja en datos/ para no depender de Overpass)
COPY config/ config/
COPY datos/ datos/
COPY estructuras/ estructuras/
COPY algoritmos/ algoritmos/
COPY simulacion/ simulacion/
COPY visualizacion/ visualizacion/
COPY api/ api/

RUN useradd --create-home --uid 10001 limago \
    && mkdir -p /app/cache \
    && chown -R limago /app/cache /app/datos
USER limago

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/salud', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
