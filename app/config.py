"""Application configuration settings for AirWindow."""

from __future__ import annotations

import os


def _get_int(key: str, default: int) -> int:
    val = os.getenv(key)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


class Settings:
    """Core application settings with environment variable fallbacks."""

    def __init__(self) -> None:
        self.app_name: str = "AirWindow Core"
        self.version: str = "0.1.0"
        self.environment: str = os.getenv("ENVIRONMENT", "development")
        self.host: str = os.getenv("HOST", "0.0.0.0")
        self.port: int = _get_int("PORT", 8000)
        self.debug: bool = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")

        # Provider configuration
        self.forecast_provider: str = os.getenv("FORECAST_PROVIDER", "mock").strip().lower()

        # Optimizer & boundary defaults
        self.default_step_minutes: int = _get_int("DEFAULT_STEP_MINUTES", 15)
        self.min_duration_minutes: int = _get_int("MIN_DURATION_MINUTES", 5)
        self.max_duration_minutes: int = _get_int("MAX_DURATION_MINUTES", 360)
        self.max_window_hours: int = _get_int("MAX_WINDOW_HOURS", 168)
        self.max_candidate_slots: int = _get_int("MAX_CANDIDATE_SLOTS", 1000)


settings = Settings()
