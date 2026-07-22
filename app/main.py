from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.app_config import router as app_config_router
from app.api.v1.auth import router as auth_router
from app.api.v1.bookings import router as bookings_router
from app.api.v1.customers import router as customers_router
from app.api.v1.delivery import router as delivery_router
from app.api.v1.menu import router as menu_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.orders import router as orders_router
from app.api.v1.organizations import router as organizations_router
from app.api.v1.stories import router as stories_router
from app.core.config import settings
from app.core.logging import configure_logging

configure_logging()

app = FastAPI(
    title=settings.app_name,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

media_root = Path(settings.media_root)
media_root.mkdir(parents=True, exist_ok=True)
app.mount(settings.media_url, StaticFiles(directory=media_root), name="media")

app.include_router(auth_router, prefix="/api/v1")
app.include_router(app_config_router, prefix="/api/v1")
app.include_router(customers_router, prefix="/api/v1")
app.include_router(organizations_router, prefix="/api/v1")
app.include_router(bookings_router, prefix="/api/v1")
app.include_router(delivery_router, prefix="/api/v1")
app.include_router(menu_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")
app.include_router(orders_router, prefix="/api/v1")
app.include_router(stories_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}
