#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Fail2Pay container startup entrypoint.
#
# 1. Runs pending database migrations (alembic upgrade head)
# 2. Starts the FastAPI backend server
#
# Set FAIL2PAY_SKIP_MIGRATIONS=1 to skip the migration step (e.g. for the
# tests or when migrations are run externally).
# -----------------------------------------------------------------------------
set -euo pipefail

cd /app/backend

if [[ "${FAIL2PAY_SKIP_MIGRATIONS:-0}" != "1" ]]; then
    echo "==> Running database migrations (alembic upgrade head)..."
    alembic upgrade head
    echo "==> Migrations complete."
fi

echo "==> Starting Fail2Pay backend on ${HOST:-0.0.0.0}:${PORT:-8000}..."
exec uvicorn app.main:app \
    --host "${HOST:-0.0.0.0}" \
    --port "${PORT:-8000}" \
    --workers "${WORKERS:-1}"
