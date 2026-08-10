#!/usr/bin/env bash

set -Eeuo pipefail

cd "$(dirname "$0")/.."

HOST="127.0.0.1"
POSTGRES_WAIT_SECONDS=60
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.dev.yml)

"${COMPOSE[@]}" --profile tools up -d postgres adminer

echo "Waiting for PostgreSQL to become ready..."
for ((second = 1; second <= POSTGRES_WAIT_SECONDS; second++)); do
    if "${COMPOSE[@]}" exec -T postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then
        echo "PostgreSQL is ready."
        break
    fi

    if (( second == POSTGRES_WAIT_SECONDS )); then
        echo "PostgreSQL did not become ready within ${POSTGRES_WAIT_SECONDS} seconds." >&2
        exit 1
    fi

    sleep 1
done

alembic upgrade head
exec uvicorn app.main:app --reload --host "$HOST" --port 8000
