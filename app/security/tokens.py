import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt

from app.core.config import settings


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(*, subject_id: UUID, subject_type: str, role: str | None = None) -> str:
    payload = {
        "sub": str(subject_id),
        "typ": "access",
        "subject_type": subject_type,
        "role": role,
        "exp": now_utc() + timedelta(minutes=settings.access_token_minutes),
        "iat": now_utc(),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(64)


def hash_token(token: str) -> str:
    return hmac.new(settings.jwt_secret_key.encode(), token.encode(), hashlib.sha256).hexdigest()