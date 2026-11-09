FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends rsync openssh-client \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir "psycopg[binary]==3.2.3" \
 && useradd -u 1000 -m ingest \
 && mkdir -p /work /archive && chown ingest:ingest /work /archive

WORKDIR /app
COPY ingest/src/ /app/
COPY database/migrations/ /app/migrations/
ENV PYTHONUNBUFFERED=1 INGEST_MIGRATIONS_DIR=/app/migrations

USER ingest
HEALTHCHECK --interval=60s --timeout=10s --start-period=120s --retries=3 \
  CMD ["python", "-m", "ingest", "health"]
CMD ["python", "-m", "ingest", "run"]
