FROM python:3.12-slim

WORKDIR /app
COPY src/ /app/
ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-m", "recorder.health"]

CMD ["python", "-m", "recorder"]
