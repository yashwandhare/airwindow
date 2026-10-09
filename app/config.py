"""Application configuration settings for AirWindow."""

import os


class Settings:
    """Core application settings with environment variable fallbacks."""

    def __init__(self) -> None:
        self.app_name: str = "AirWindow Core"
        self.version: str = "0.1.0"
        self.environment: str = os.getenv("ENVIRONMENT", "development")
        self.host: str = os.getenv("HOST", "0.0.0.0")
        self.port: int = int(os.getenv("PORT", "8000"))
        self.debug: bool = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")

        # Provider configuration
        self.forecast_provider: str = os.getenv("FORECAST_PROVIDER", "mock")

        # Optimizer defaults
        self.default_step_minutes: int = int(os.getenv("DEFAULT_STEP_MINUTES", "15"))
        self.min_duration_minutes: int = int(os.getenv("MIN_DURATION_MINUTES", "15"))
        self.max_duration_minutes: int = int(os.getenv("MAX_DURATION_MINUTES", "360"))


settings = Settings()
