#!/usr/bin/env sh
set -e
cd /app

# Optional DB reset (dangerous in prod) — controlled by env
# Uses psql to drop schema and recreate it in-place.
if [ "${DB_RESET:-false}" = "true" ]; then
  echo ">> DB_RESET=true: dropping and recreating schema on ${DB_HOST:-db}/${DB_NAME:-helpdesk}"
  PGPASSWORD="${DB_PASSWORD:-helpdesk}" psql \
    -h "${DB_HOST:-db}" -p "${DB_PORT:-5432}" \
    -U "${DB_USER:-helpdesk}" -d "${DB_NAME:-helpdesk}" \
    -v ON_ERROR_STOP=1 \
    -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
fi

# Run Alembic migrations
export FLASK_APP=wsgi.py
if [ -d "/app/migrations" ]; then
  flask db upgrade
fi

# Start services (Gunicorn + MCP)
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
