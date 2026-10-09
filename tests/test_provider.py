"""Tests for forecast provider and normalization."""

from datetime import datetime, timedelta, timezone

import pytest

from app.data.mock_provider import MockForecastProvider
from app.data.models import Location


@pytest.fixture
def ist_tz() -> timezone:
    return timezone(timedelta(hours=5, minutes=30))


@pytest.fixture
def location() -> Location:
    return Location(name="Nagpur", latitude=21.1458, longitude=79.0882)


@pytest.mark.anyio
async def test_mock_provider_determinism(location: Location, ist_tz: timezone) -> None:
    """Verify mock provider generates identical, reproducible numbers for identical inputs."""
    provider1 = MockForecastProvider()
    provider2 = MockForecastProvider()

    t_start = datetime(2026, 10, 10, 8, 0, tzinfo=ist_tz)
    t_end = datetime(2026, 10, 10, 20, 0, tzinfo=ist_tz)

    series1 = await provider1.get_forecast(location, t_start, t_end)
    series2 = await provider2.get_forecast(location, t_start, t_end)

    assert len(series1.points) == len(series2.points)
    for p1, p2 in zip(series1.points, series2.points):
        assert p1.timestamp == p2.timestamp
        assert p1.pm25_ug_m3 == p2.pm25_ug_m3
        assert p1.temperature_c == p2.temperature_c


@pytest.mark.anyio
async def test_mock_provider_missing_hours(location: Location, ist_tz: timezone) -> None:
    """Verify that simulated missing hours produce None PM2.5 points."""
    provider = MockForecastProvider(missing_hours={10, 11})

    t_start = datetime(2026, 10, 10, 8, 0, tzinfo=ist_tz)
    t_end = datetime(2026, 10, 10, 14, 0, tzinfo=ist_tz)

    series = await provider.get_forecast(location, t_start, t_end)

    # Hour 10 and 11 should have None pm25
    h10 = next(p for p in series.points if p.timestamp.hour == 10)
    h11 = next(p for p in series.points if p.timestamp.hour == 11)
    h8 = next(p for p in series.points if p.timestamp.hour == 8)

    assert h10.pm25_ug_m3 is None
    assert h11.pm25_ug_m3 is None
    assert h8.pm25_ug_m3 is not None


@pytest.mark.anyio
async def test_mock_provider_quality_assessment(location: Location, ist_tz: timezone) -> None:
    """Verify assessment of freshness and confidence."""
    provider = MockForecastProvider()
    t_start = datetime(2026, 10, 10, 8, 0, tzinfo=ist_tz)
    t_end = datetime(2026, 10, 10, 14, 0, tzinfo=ist_tz)

    series = await provider.get_forecast(location, t_start, t_end)
    quality = series.assess_quality(reference_time=t_start)

    assert quality.source == provider.name
    assert quality.confidence in ("high", "medium", "low")
    assert quality.missing_intervals_count == 0
    assert quality.is_stale is False


def test_normalize_open_meteo_payload(location: Location) -> None:
    """Verify raw Open-Meteo dictionary parsing into NormalizedForecastSeries."""
    from app.data.normalization import normalize_open_meteo_response

    raw_payload = {
        "utc_offset_seconds": 19800,  # +05:30
        "hourly": {
            "time": ["2026-10-10T17:00", "2026-10-10T18:00"],
            "pm2_5": [45.0, 55.0],
            "temperature_2m": [30.0, 28.5],
            "relative_humidity_2m": [50.0, 55.0],
        },
    }

    series = normalize_open_meteo_response(raw_payload, location)
    assert len(series.points) == 2
    assert series.points[0].pm25_ug_m3 == 45.0
    assert series.points[1].pm25_ug_m3 == 55.0
    assert series.points[0].timestamp.tzinfo is not None
