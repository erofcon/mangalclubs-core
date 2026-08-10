import gzip
import logging
import shutil
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from app.core.config import settings
from app.core.time import MOSCOW_TZ


LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class MoscowFormatter(logging.Formatter):
    """Render all application log timestamps in the restaurant timezone."""

    def formatTime(self, record, datefmt=None):
        value = datetime.fromtimestamp(record.created, tz=MOSCOW_TZ)
        return value.strftime(datefmt or DATE_FORMAT)


class MoscowMidnightRotatingFileHandler(TimedRotatingFileHandler):
    """Rotate daily log files at midnight in Moscow, not the host timezone."""

    def computeRollover(self, current_time):
        current = datetime.fromtimestamp(current_time, tz=MOSCOW_TZ)
        next_midnight = current.replace(hour=0, minute=0, second=0, microsecond=0)
        if next_midnight <= current:
            next_midnight += timedelta(days=1)
        return next_midnight.timestamp()


def gzip_rotated_log(source: str, destination: str) -> None:
    with open(source, "rb") as source_file, gzip.open(destination, "wb") as destination_file:
        shutil.copyfileobj(source_file, destination_file)
    Path(source).unlink(missing_ok=True)


def configure_logging() -> None:
    level_name = settings.log_level.upper()
    level = logging.getLevelName(level_name)
    if not isinstance(level, int):
        level_name = "INFO"
        level = logging.INFO

    formatter = MoscowFormatter(LOG_FORMAT, DATE_FORMAT)
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if settings.log_to_file:
        log_dir = Path(settings.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = MoscowMidnightRotatingFileHandler(
            log_dir / settings.log_file_name,
            when="midnight",
            backupCount=settings.log_retention_days,
            encoding="utf-8",
        )
        file_handler.namer = lambda name: f"{name}.gz"
        file_handler.rotator = gzip_rotated_log
        handlers.append(file_handler)

    for handler in handlers:
        handler.setFormatter(formatter)
        handler.setLevel(level)

    root_logger = logging.getLogger()
    for existing_handler in root_logger.handlers[:]:
        root_logger.removeHandler(existing_handler)
        existing_handler.close()
    root_logger.setLevel(level)
    for handler in handlers:
        root_logger.addHandler(handler)

    for noisy_logger in ("sqlalchemy.engine", "httpx", "uvicorn.access"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    logging.getLogger(__name__).info("Logging configured: level=%s file_enabled=%s", level_name, settings.log_to_file)
