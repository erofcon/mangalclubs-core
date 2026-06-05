from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MangalClubs Core"
    debug: bool = False
    database_url: str
    media_root: str = "media"
    media_url: str = "/media"

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
