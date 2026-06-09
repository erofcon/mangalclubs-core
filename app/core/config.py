from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MangalClubs Core"
    debug: bool = False
    database_url: str
    media_root: str = "media"
    media_url: str = "/media"

    iiko_api_base_url: str = "https://api-ru.iiko.services"
    iiko_auth_poll_seconds: int = 60
    iiko_token_refresh_margin_seconds: int = 120
    iiko_request_timeout_seconds: float = 10.0

    jwt_secret_key: str
    access_token_minutes: int = 15
    refresh_token_days: int = 60

    otp_ttl_seconds: int = 30
    otp_resend_cooldown_seconds: int = 60
    otp_max_attempts: int = 5
    otp_dev_mode: bool = False

    cookie_secure: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
