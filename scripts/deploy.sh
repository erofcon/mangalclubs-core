#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git pull --ff-only
fi

docker compose build --pull
docker compose up -d --remove-orphans
docker image prune -f
docker compose ps
