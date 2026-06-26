#!/bin/bash
set -euo pipefail

cd /app

if [[ -f /app/.env ]]; then
    set -a
    source /app/.env
    set +a
fi

if [[ -z "${OCI_COMPANION_SSL_CERT_FILE:-}" && -f /app/certs/localhost-cert.pem ]]; then
    export OCI_COMPANION_SSL_CERT_FILE=/app/certs/localhost-cert.pem
fi

if [[ -z "${OCI_COMPANION_SSL_KEY_FILE:-}" && -f /app/certs/localhost-key.pem ]]; then
    export OCI_COMPANION_SSL_KEY_FILE=/app/certs/localhost-key.pem
fi

exec python3 ./app.py "$@"
