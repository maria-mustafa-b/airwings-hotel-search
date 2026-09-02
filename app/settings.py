from pathlib import Path

from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    hotelrack_start_url: str
    hotelrack_headless: bool = False

    airwings_markup_aed: Decimal = Decimal("100.00")

    model_config = SettingsConfigDict(
        env_file=PROJECT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
