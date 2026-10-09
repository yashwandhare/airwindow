"""Forecast provider interface definition."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.data.models import Location, NormalizedForecastSeries


class ForecastProvider(ABC):
    """Abstract interface for forecast data providers.

    Teammates can implement this interface to connect real providers such as
    Open-Meteo, OpenAQ, CPCB APIs, or AWS S3 buckets without modifying core logic.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the provider name."""
        pass

    @abstractmethod
    async def get_forecast(
        self,
        location: Location,
        start_time: datetime,
        end_time: datetime,
    ) -> NormalizedForecastSeries:
        """Retrieve a normalized forecast series covering [start_time, end_time].

        Args:
            location: Target geographic coordinates and name.
            start_time: Window beginning (timezone-aware).
            end_time: Window ending (timezone-aware).

        Returns:
            NormalizedForecastSeries with chronological hourly records.
        """
        pass
