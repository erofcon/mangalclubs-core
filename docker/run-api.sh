#!/bin/sh
set -eu

python - <<'PY'
import asyncio
import os

from sqlalchemy.ext.asyncio import create_async_engine


async def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    last_error: Exception | None = None

    for attempt in range(1, 61):
        engine = create_async_engine(database_url)
        try:
            async with engine.connect():
                print("Database is ready", flush=True)
                return
        except Exception as exc:
            last_error = exc
            print(f"Waiting for database ({attempt}/60): {exc}", flush=True)
            await asyncio.sleep(2)
        finally:
            await engine.dispose()

    raise RuntimeError("Database is not ready") from last_error


asyncio.run(main())
PY

alembic upgrade head

exec "$@"
