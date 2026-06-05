from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.v1.auth import router as auth_router
from app.api.v1.bookings import router as bookings_router
from app.api.v1.organizations import router as organizations_router
from app.api.v1.stories import router as stories_router
from app.core.config import settings

app = FastAPI(title=settings.app_name)

media_root = Path(settings.media_root)
media_root.mkdir(parents=True, exist_ok=True)
app.mount(settings.media_url, StaticFiles(directory=media_root), name="media")

app.include_router(auth_router, prefix="/api/v1")
app.include_router(organizations_router, prefix="/api/v1")
app.include_router(bookings_router, prefix="/api/v1")
app.include_router(stories_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}
