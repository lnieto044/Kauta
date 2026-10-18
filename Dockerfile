# syntax=docker/dockerfile:1.7
# Etapa 1: compila la pantalla (React + TypeScript + Tailwind)
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# Etapa 2: servidor Python mínimo, sin herramientas de compilación, con usuario sin privilegios
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 KAUTA_VAR=/var/kauta
RUN useradd --create-home --uid 10001 kauta && mkdir -p /var/kauta && chown kauta:kauta /var/kauta
# Lector local: Tesseract con español e inglés (el documento nunca sale del contenedor)
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-servidor.txt .
RUN pip install -r requirements-servidor.txt
COPY kauta/ kauta/
COPY servidor/ servidor/
COPY data/ data/
COPY --from=web /web/dist web/dist
USER kauta
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/salud')"
CMD ["uvicorn", "servidor.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]
