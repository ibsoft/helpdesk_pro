# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/home/appuser/.local/bin:${PATH}" \
    FLASK_ENV=production \
    GUNICORN_CMD_ARGS="--workers=2 --threads=4 --timeout=120" \
    MCP_CMD="python -m app.mcp.main"

WORKDIR /app

# psycopg2 build deps + supervisor + curl + psql client
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev supervisor curl postgresql-client && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --shell /bin/bash appuser \
 && mkdir -p /app/logs \
            /app/instance/knowledge_uploads \
            /app/instance/tickets_uploads \
 && chown -R appuser:appuser /app

COPY deploy/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER appuser
EXPOSE 5000 8081
ENTRYPOINT ["/entrypoint.sh"]
