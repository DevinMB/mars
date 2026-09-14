# MARS console: React frontend built and served by the FastAPI backend.
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci 2>/dev/null || npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/manifests ./manifests
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY --from=frontend /build/dist ./static

# Runs unprivileged; /data holds the database and the encryption key.
RUN useradd --create-home --uid 10001 mars \
 && mkdir -p /data \
 && chown -R mars:mars /data /app
USER mars

ENV MARS_DATA_DIR=/data
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD curl -fsS http://localhost:8080/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
