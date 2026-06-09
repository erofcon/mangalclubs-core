import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.v1.auth import router as auth_router
from app.api.v1.bookings import router as bookings_router
from app.api.v1.delivery import router as delivery_router
from app.api.v1.menu import router as menu_router
from app.api.v1.organizations import router as organizations_router
from app.api.v1.stories import router as stories_router
from app.core.config import settings
from app.services.iiko import run_iiko_token_refresher
from app.services.menu import run_iiko_menu_refresher


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop_event = asyncio.Event()
    token_refresher_task = asyncio.create_task(run_iiko_token_refresher(stop_event))
    menu_refresher_task = asyncio.create_task(run_iiko_menu_refresher(stop_event))

    try:
        yield
    finally:
        stop_event.set()
        for task in (token_refresher_task, menu_refresher_task):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(title=settings.app_name, lifespan=lifespan)

media_root = Path(settings.media_root)
media_root.mkdir(parents=True, exist_ok=True)
app.mount(settings.media_url, StaticFiles(directory=media_root), name="media")

app.include_router(auth_router, prefix="/api/v1")
app.include_router(organizations_router, prefix="/api/v1")
app.include_router(bookings_router, prefix="/api/v1")
app.include_router(delivery_router, prefix="/api/v1")
app.include_router(menu_router, prefix="/api/v1")
app.include_router(stories_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}
