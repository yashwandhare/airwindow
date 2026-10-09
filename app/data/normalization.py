"""Utilities for converting raw atmospheric API/file data into normalized series.

Supports parsing raw Open-Meteo or generic JSON structures into NormalizedForecastSeries.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.data.models import Location, NormalizedForecastPoint, NormalizedForecastSeries


def parse_iso_datetime(dt_str: str, default_tz: timezone | ZoneInfo = UTC) -> datetime:
    """Parse ISO datetime string ensuring a timezone is attached."""
    clean_str = dt_str.strip()
    if clean_str.endswith("Z"):
        clean_str = clean_str[:-1] + "+00:00"

    dt = datetime.fromisoformat(clean_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_tz)
    return dt


def normalize_open_meteo_response(
    raw_data: dict[str, Any],
    location: Location,
    source_name: str = "Open-Meteo Air Quality API",
) -> NormalizedForecastSeries:
    """Transform raw Open-Meteo hourly JSON response into NormalizedForecastSeries.

    Open-Meteo format:
    {
        "hourly": {
            "time": ["2026-10-10T00:00", ...],
            "pm2_5": [45.2, ...],
            "temperature_2m": [22.1, ...]
        },
        "utc_offset_seconds": 19800
    }
    """
    hourly = raw_data.get("hourly", {})
    times = hourly.get("time", [])
    pm25_list = hourly.get("pm2_5", [])
    temp_list = hourly.get("temperature_2m", [])
    humidity_list = hourly.get("relative_humidity_2m", [])

    offset_sec = raw_data.get("utc_offset_seconds", 0)
    tz = timezone(timedelta(seconds=offset_sec)) if offset_sec else UTC

    points: list[NormalizedForecastPoint] = []
    for i, t_str in enumerate(times):
        dt = parse_iso_datetime(t_str, default_tz=tz)
        raw_pm = pm25_list[i] if i < len(pm25_list) else None

        # Clamp negative sensor/model values to 0.0
        pm = max(0.0, float(raw_pm)) if raw_pm is not None else None
        temp = float(temp_list[i]) if (i < len(temp_list) and temp_list[i] is not None) else None
        humidity = float(humidity_list[i]) if (i < len(humidity_list) and humidity_list[i] is not None) else None

        points.append(
            NormalizedForecastPoint(
                timestamp=dt,
                pm25_ug_m3=pm,
                temperature_c=temp,
                humidity_pct=humidity,
                source=source_name,
                is_observed=False,
            )
        )

    series = NormalizedForecastSeries(
        location=location,
        generated_at=datetime.now(UTC),
        source=source_name,
        points=points,
    )
    series.sort_points()
    return series
