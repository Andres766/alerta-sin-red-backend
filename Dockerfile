# syntax=docker/dockerfile:1
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY ml ./ml
COPY models ./models

# El proceso no corre como root dentro del contenedor.
RUN useradd --create-home --uid 10001 appuser
USER appuser

# Render (y otras plataformas) indican el puerto en la variable PORT.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "python -m app.cli init-db && python -m app.cli seed && exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
