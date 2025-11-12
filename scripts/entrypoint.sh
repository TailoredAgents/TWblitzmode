#!/usr/bin/env bash
set -euo pipefail

# Ensure DATABASE_URL is present
if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: DATABASE_URL is not set. Refusing to start."
  exit 1
fi

echo "Running Alembic migrations..."
alembic upgrade head || {
  echo "WARNING: Alembic upgrade failed; proceeding to start app anyway." >&2
}

echo "Starting application: $*"
exec "$@"

