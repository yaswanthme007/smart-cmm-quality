"""Application settings, read from environment variables / .env (see .env.example)."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Smart CMM Quality"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://cmm:change-me@localhost:5432/cmm_quality"

    jwt_secret: str = Field(default="", repr=False)
    jwt_expire_hours: int = 12

    web_origin: str = "http://localhost:5173"
    app_base_url: str = "http://localhost:5173"
    data_dir: Path = Path("./data")

    demo_mode: bool = True
    demo_user_password: str = Field(default="", repr=False)
    escalation_profile: str = "demo"

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = Field(default="", repr=False)
    smtp_from: str = "cmm-alerts@demo.local"

    ai_enabled: bool = False
    ai_provider: str = ""
    ai_api_key: str = Field(default="", repr=False)
    ai_model: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
