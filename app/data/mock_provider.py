"""Deterministic mock forecast provider.

Generates realistic, physically-grounded diurnal atmospheric PM2.5 and temperature
cycles without requiring network calls or cloud credentials.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from app.data.models import Location, NormalizedForecastPoint, NormalizedForecastSeries
from app.data.providers import ForecastProvider


class MockForecastProvider(ForecastProvider):
    """Deterministic forecast provider simulating realistic diurnal atmospheric cycles."""

    def __init__(
        self,
        base_pm25: float = 35.0,
        base_temp_c: float = 27.0,
        stale_hours: float = 0.0,
        missing_hours: set[int] | None = None,
        has_station_observations: bool = False,
    ) -> None:
        self._name = "AirWindow Deterministic Mock Provider v1.0"
        self.base_pm25 = base_pm25
        self.base_temp_c = base_temp_c
        self.stale_hours = stale_hours
        self.missing_hours = missing_hours or set()
        self.has_station_observations = has_station_observations

    @property
    def name(self) -> str:
        return self._name

    def _calculate_point(self, dt: datetime) -> tuple[float | None, float, float]:
        """Calculate deterministic PM2.5 (µg/m³), Temp (°C), and Humidity (%) for a given local hour.

        Uses a double-Gaussian model for urban PM2.5 diurnal variation:
        - Morning traffic & inversion peak ~08:00
        - Midday boundary-layer convective dilution dip ~14:00
        - Evening traffic & nocturnal cooling peak ~20:00
        """
        hour = dt.hour + dt.minute / 60.0

        # Morning rush peak at 08:30 (stddev ~1.5h)
        morning_peak = 35.0 * math.exp(-0.5 * ((hour - 8.5) / 1.5) ** 2)

        # Evening rush peak at 20:00 (stddev ~2.0h)
        evening_peak = 45.0 * math.exp(-0.5 * ((hour - 20.0) / 2.0) ** 2)

        # Midday boundary layer dispersion reduction
        midday_clearing = -12.0 * math.exp(-0.5 * ((hour - 14.0) / 2.5) ** 2)

        pm25 = max(5.0, self.base_pm25 + morning_peak + evening_peak + midday_clearing)
        # Round to 1 decimal place for clean deterministic outputs
        pm25 = round(pm25, 1)

        # Diurnal temperature cycle: min at 06:00, max at 15:00
        # temp = base + amplitude * sin(2*pi*(hour - 9)/24)
        temp_amplitude = 7.0
        temp_c = self.base_temp_c + temp_amplitude * math.sin(2 * math.pi * (hour - 9.0) / 24.0)
        temp_c = round(temp_c, 1)

        # Relative humidity inversely correlates with temperature
        humidity = max(20.0, min(95.0, 60.0 - 15.0 * math.sin(2 * math.pi * (hour - 9.0) / 24.0)))
        humidity = round(humidity, 1)

        return pm25, temp_c, humidity

    async def get_forecast(
        self,
        location: Location,
        start_time: datetime,
        end_time: datetime,
    ) -> NormalizedForecastSeries:
        """Generate a series of hourly forecast points covering [start_time, end_time]."""
        # Ensure start and end are timezone aware
        if start_time.tzinfo is None or end_time.tzinfo is None:
            raise ValueError("start_time and end_time must be timezone-aware.")

        # Floor start_time to the beginning of the hour
        current = start_time.replace(minute=0, second=0, microsecond=0)
        # Ceiling end_time to ensure full hour coverage
        limit = end_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

        points: list[NormalizedForecastPoint] = []
        hour_index = 0

        while current <= limit:
            pm25, temp_c, humidity = self._calculate_point(current)

            # Check if this hour is designated as missing
            if hour_index in self.missing_hours or current.hour in self.missing_hours:
                point_pm25 = None
            else:
                point_pm25 = pm25

            points.append(
                NormalizedForecastPoint(
                    timestamp=current,
                    pm25_ug_m3=point_pm25,
                    temperature_c=temp_c,
                    humidity_pct=humidity,
                    source=self.name,
                    is_observed=self.has_station_observations and current <= start_time,
                )
            )
            current += timedelta(hours=1)
            hour_index += 1

        ref_tz = start_time.tzinfo or UTC
        generated_at = (start_time - timedelta(hours=self.stale_hours)).astimezone(ref_tz)

        series = NormalizedForecastSeries(
            location=location,
            generated_at=generated_at,
            source=self.name,
            points=points,
        )
        series.sort_points()
        return series
