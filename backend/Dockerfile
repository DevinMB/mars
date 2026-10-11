# MARS console: React frontend built and served by the FastAPI backend.
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY LICENSE ./LICENSE

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/manifests ./manifests
# Seeded once, on a fresh install, so the first screen is not a dead end.
COPY examples ./examples
# The template the console renders when someone adds a cluster on another machine.
COPY remote-target/docker-compose.yml ./remote-target/docker-compose.yml
COPY remote-target/conf/config.yaml ./remote-target/conf/config.yaml
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY --from=frontend /build/dist ./static

# Runs unprivileged; /data holds the database and the encryption key.
RUN useradd --create-home --uid 10001 mars \
 && mkdir -p /data \
 && chown -R mars:mars /data /app
USER mars

ENV MARS_DATA_DIR=/data
# Without this, Python block-buffers stdout when it is a pipe, which is exactly
# what Docker gives it. The first administrator's generated password is printed
# once at startup and then sits in that buffer indefinitely -- so on a fresh
# install "docker logs mars-console | grep administrator" returned nothing and
# there was no way in except resetting the password. Found by installing from a
# clean clone rather than by reading the code.
ENV PYTHONUNBUFFERED=1
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD curl -fsS http://localhost:8080/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
