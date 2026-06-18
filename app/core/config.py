import json

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MangalClubs Core"
    debug: bool = False
    database_url: str
    media_root: str = "media"
    media_url: str = "/media"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    iiko_api_base_url: str = "https://api-ru.iiko.services"
    iiko_auth_poll_seconds: int = 60
    iiko_menu_poll_seconds: int = 300
    iiko_token_refresh_margin_seconds: int = 120
    iiko_request_timeout_seconds: float = 10.0
    iiko_terminal_timezone: str = "Europe/Moscow"
    iiko_order_dispatch_poll_seconds: int = 30
    iiko_order_status_poll_seconds: int = 15

    public_api_base_url: str | None = None
    tbank_api_base_url: str = "https://securepay.tinkoff.ru/v2"
    tbank_request_timeout_seconds: float = 10.0
    tbank_state_poll_seconds: int = 60
    tbank_default_terminal_key: str | None = None
    tbank_default_password: str | None = None
    tbank_notification_url: str | None = None
    tbank_success_url: str | None = None
    tbank_fail_url: str | None = None
    tbank_paid_statuses: str = "CONFIRMED"
    order_unpaid_payment_deadline_minutes: int = 20
    order_unpaid_payment_ttl_minutes: int = 30
    delivery_area_geojson: str | None = None
    geoapify_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GEOAPIFY_API_KEY", "EXPO_PUBLIC_GEOAPIFY_KEY"),
    )
    geoapify_request_timeout_seconds: float = 3.0
    expo_push_request_timeout_seconds: float = 5.0

    jwt_secret_key: str
    access_token_minutes: int = 15
    refresh_token_days: int = 60

    otp_ttl_seconds: int = 30
    otp_resend_cooldown_seconds: int = 60
    otp_max_attempts: int = 5
    otp_dev_mode: bool = False
    otp_phone_cooldown_schedule_seconds: str = "30,60,900"
    otp_phone_window_seconds: int = 24 * 60 * 60
    otp_global_cooldown_seconds: int = 30
    otp_ip_window_seconds: int = 60 * 60
    otp_ip_max_requests_per_window: int = 10

    cookie_secure: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", populate_by_name=True)

    @property
    def cors_origin_list(self) -> list[str]:
        value = self.cors_origins.strip()
        if not value:
            return []

        if value.startswith("["):
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(origin).strip() for origin in parsed if str(origin).strip()]

        return [origin.strip() for origin in value.split(",") if origin.strip()]

    @property
    def tbank_paid_status_set(self) -> set[str]:
        return {status.strip().upper() for status in self.tbank_paid_statuses.split(",") if status.strip()}

    @property
    def otp_phone_cooldown_schedule(self) -> list[int]:
        values: list[int] = []
        for raw_value in self.otp_phone_cooldown_schedule_seconds.split(","):
            raw_value = raw_value.strip()
            if raw_value:
                values.append(max(0, int(raw_value)))

        return values or [self.otp_resend_cooldown_seconds]

    @property
    def resolved_tbank_notification_url(self) -> str | None:
        if self.tbank_notification_url:
            return self.tbank_notification_url.rstrip("/")
        if self.public_api_base_url:
            return f"{self.public_api_base_url.rstrip('/')}/api/v1/orders/payments/tbank/webhook"
        return None


settings = Settings()
