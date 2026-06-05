import asyncio
from logging.config import fileConfig

from sqlalchemy import pool

from alembic import context

from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.models import (
    Booking,
    BookingCategory,
    BookingImage,
    Customer,
    DeliveryZone,
    Organization,
    OrganizationWorkingHour,
    OtpChallenge,
    RefreshSession,
    StaffUser,
    Story,
    StorySlide,
)
from app.models.base import Base

# Keep model imports referenced so Base.metadata is populated for autogenerate.
_registered_models = (
    Booking,
    BookingCategory,
    BookingImage,
    Customer,
    DeliveryZone,
    Organization,
    OrganizationWorkingHour,
    OtpChallenge,
    RefreshSession,
    StaffUser,
    Story,
    StorySlide,
)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
