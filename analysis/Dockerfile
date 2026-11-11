FROM python:3.12-slim

RUN pip install --no-cache-dir "psycopg[binary]==3.2.3" "PyYAML==6.0.2" \
 && useradd -u 1000 -m analysis

WORKDIR /app
COPY analysis/src/ /app/
ENV PYTHONUNBUFFERED=1

USER analysis
HEALTHCHECK --interval=60s --timeout=15s --start-period=180s --retries=3 \
  CMD ["python", "-m", "analysis", "health"]
CMD ["python", "-m", "analysis", "run"]
