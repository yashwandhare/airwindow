"""FastAPI dependencies for AirWindow.

Allows injection and swapping of forecast providers (e.g. Mock, Open-Meteo, AWS S3).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.config import settings
from app.data.mock_provider import MockForecastProvider
from app.data.providers import ForecastProvider

# Singleton or factory instance
_provider_instance: ForecastProvider | None = None


def get_forecast_provider() -> ForecastProvider:
    """Dependency provider returning the configured ForecastProvider implementation."""
    global _provider_instance
    if _provider_instance is None:
        p_name = settings.forecast_provider.strip().lower()
        if p_name == "mock":
            _provider_instance = MockForecastProvider()
        else:
            raise RuntimeError(
                f"Unsupported FORECAST_PROVIDER: '{settings.forecast_provider}'. Supported options: 'mock'."
            )
    return _provider_instance


def set_forecast_provider(provider: ForecastProvider) -> None:
    """Override provider instance (useful for testing or dynamic provider registration)."""
    global _provider_instance
    _provider_instance = provider


ProviderDep = Annotated[ForecastProvider, Depends(get_forecast_provider)]
