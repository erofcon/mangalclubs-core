#!/bin/sh
set -eu

: "${POSTGRES_HOST:=postgres}"
: "${POSTGRES_PORT:=5432}"
: "${POSTGRES_DB:=mangalclubs}"
: "${POSTGRES_USER:=mangalclubs}"
: "${BACKUP_DIR:=/backups}"
: "${BACKUP_KEEP_DAYS:=14}"
: "${BACKUP_INTERVAL_SECONDS:=86400}"

mkdir -p "$BACKUP_DIR"

while true; do
    until pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB"; do
        echo "Waiting for postgres before backup..."
        sleep 5
    done

    now="$(date +%Y%m%d-%H%M%S)"
    db_file="$BACKUP_DIR/${POSTGRES_DB}_${now}.dump"
    media_file="$BACKUP_DIR/media_${now}.tar.gz"

    echo "Creating postgres backup: $db_file"
    if pg_dump -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$db_file"; then
        echo "Postgres backup is ready"
    else
        rm -f "$db_file"
        echo "Postgres backup failed" >&2
    fi

    if [ -d /media ]; then
        echo "Creating media backup: $media_file"
        tar -czf "$media_file" -C /media .
    fi

    find "$BACKUP_DIR" -type f \( -name "${POSTGRES_DB}_*.dump" -o -name "media_*.tar.gz" \) -mtime +"$BACKUP_KEEP_DAYS" -delete

    sleep "$BACKUP_INTERVAL_SECONDS"
done
