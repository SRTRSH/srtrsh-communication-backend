#!/bin/sh
set -e

# Construct SRTRSH_DATABASE_URL from DB_PASSWORD and Cloud SQL parameters if not already explicitly set
if [ -z "${SRTRSH_DATABASE_URL:-}" ] && [ -n "${DB_PASSWORD:-}" ]; then
  DB_USER="${DB_USER:-srtrsh_app}"
  DB_NAME="${DB_NAME:-srtrsh}"
  CLOUD_SQL_INSTANCE="${CLOUD_SQL_INSTANCE:-srtrsh-stg:europe-west1:srtrsh-stg-pg16}"

  export SRTRSH_DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@/${DB_NAME}?host=/cloudsql/${CLOUD_SQL_INSTANCE}"
fi

# Fallback PORT to 8080 if not set or empty
PORT="${PORT:-8080}"

# If no arguments provided, default to starting the uvicorn server
if [ $# -eq 0 ]; then
  exec uvicorn srtrsh_communication_backend.main:app \
    --host 0.0.0.0 \
    --port "$PORT" \
    --proxy-headers \
    --forwarded-allow-ips='*'
fi

# If command starts with uvicorn, ensure --port is set to $PORT if not already present
if [ "$1" = "uvicorn" ]; then
  has_port=0
  for arg in "$@"; do
    case "$arg" in
      --port|--port=*)
        has_port=1
        ;;
    esac
  done
  if [ "$has_port" -eq 0 ]; then
    exec "$@" --port "$PORT"
  fi
fi

exec "$@"
