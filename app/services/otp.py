import hashlib
import hmac
import random
from datetime import timedelta

import phonenumbers

from app.core.config import settings
from app.security.tokens import now_utc


class InvalidPhoneNumberError(ValueError):
    pass


def normalize_phone(raw_phone: str) -> str:
    try:
        parsed = phonenumbers.parse(raw_phone, "RU")
    except phonenumbers.NumberParseException as exc:
        raise InvalidPhoneNumberError("Invalid phone number") from exc

    if not phonenumbers.is_valid_number(parsed):
        raise InvalidPhoneNumberError("Invalid phone number")

    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def generate_otp_code() -> str:
    return f"{random.SystemRandom().randint(0, 999999):06d}"


def hash_otp(phone: str, code: str) -> str:
    value = f"{phone}:{code}"
    return hmac.new(settings.jwt_secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()


def verify_otp(phone: str, code: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(phone, code), expected_hash)


def print_fake_sms(phone: str, code: str) -> None:
    if settings.otp_dev_mode:
        print(f"[DEV SMS] OTP for {phone}: {code}")


def otp_expires_at():
    return now_utc() + timedelta(seconds=settings.otp_ttl_seconds)


def otp_resend_available_at():
    return now_utc() + timedelta(seconds=settings.otp_resend_cooldown_seconds)
