#!/usr/bin/env sh
set -eu

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
APP="${APP_MODULE:-app.main:app}"

if [ -n "${TLS_CERT_FILE:-}" ] && [ -n "${TLS_KEY_FILE:-}" ] && [ -f "${TLS_CERT_FILE}" ] && [ -f "${TLS_KEY_FILE}" ]; then
  echo "Starting with application TLS on ${HOST}:${PORT}"
  exec uvicorn "$APP" --host "$HOST" --port "$PORT" --ssl-certfile "$TLS_CERT_FILE" --ssl-keyfile "$TLS_KEY_FILE"
fi

echo "Starting without application TLS on ${HOST}:${PORT}"
exec uvicorn "$APP" --host "$HOST" --port "$PORT"
