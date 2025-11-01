# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/home/appuser/.local/bin:${PATH}"

WORKDIR /app

# System packages required by psycopg2 and other Python deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create an unprivileged user and ensure writable dirs exist
RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /app/logs /app/instance /app/uploads \
    && chown -R appuser:appuser /app
USER appuser

ENV FLASK_ENV=production \
    GUNICORN_CMD_ARGS="--workers=1 --threads=4"
EXPOSE 5000

CMD ["gunicorn", "-b", "0.0.0.0:5000", "wsgi:app"]
