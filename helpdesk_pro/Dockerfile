# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/home/appuser/.local/bin:${PATH}" \
    FLASK_ENV=production \
    GUNICORN_CMD_ARGS="--workers=1 --threads=8 --timeout=120"

WORKDIR /app

# System deps (psycopg2 + build tools) + supervisor for multi-proc
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev supervisor curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Ensure instance & upload dirs exist (and persist via a volume in compose)
RUN useradd --create-home --shell /bin/bash appuser \
 && mkdir -p /app/logs \
    /app/instance/knowledge_uploads \
    /app/instance/tickets_uploads \
 && chown -R appuser:appuser /app

# Supervisor config to run Flask app (5000) + MCP service (8081)
COPY deploy/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

USER appuser
EXPOSE 5000 8081
CMD ["/usr/bin/supervisord","-c","/etc/supervisor/conf.d/supervisord.conf"]
