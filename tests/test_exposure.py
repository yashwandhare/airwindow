"""Tests for pure Python PM2.5 exposure calculations."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.core.exposure import (
    ExposureCalculationError,
    calculate_slot_exposure,
    get_activity_ventilation_rate,
)
from app.data.models import Location, NormalizedForecastPoint, NormalizedForecastSeries


@pytest.fixture
def test_location() -> Location:
    return Location(name="Nagpur", latitude=21.1458, longitude=79.0882)


@pytest.fixture
def ist_tz() -> timezone:
    return timezone(timedelta(hours=5, minutes=30))


def create_series(
    points_data: list[tuple[datetime, float | None, float | None]],
    location: Location,
) -> NormalizedForecastSeries:
    """Helper to build NormalizedForecastSeries from simple tuples."""
    points = [
        NormalizedForecastPoint(
            timestamp=dt,
            pm25_ug_m3=pm,
            temperature_c=temp,
            source="test",
        )
        for dt, pm, temp in points_data
    ]
    ref_time = points_data[0][0] if points_data else datetime.now(UTC)
    return NormalizedForecastSeries(
        location=location,
        generated_at=ref_time,
        source="test-provider",
        points=points,
    )


def test_constant_pm25_exposure(test_location: Location, ist_tz: timezone) -> None:
    """Verify dose calculation with constant PM2.5 across single interval."""
    # Start: 17:00, Duration: 40 min, Running VE: 0.045 m³/min, PM2.5: 50.0 µg/m³
    # Expected dose = 50.0 µg/m³ * 0.045 m³/min * 40 min = 90.0 µg
    t0 = datetime(2026, 10, 10, 17, 0, tzinfo=ist_tz)
    series = create_series([(t0, 50.0, 25.0)], test_location)

    result = calculate_slot_exposure(
        start_time=t0,
        duration_min=40,
        activity="running",
        forecast_series=series,
    )

    assert result.total_dose_ug == pytest.approx(90.0, rel=1e-3)
    assert result.duration_min == 40
    assert result.avg_pm25_ug_m3 == 50.0
    assert result.ventilation_rate_m3_min == 0.045
    assert len(result.intervals) == 1
    assert result.intervals[0].dose_ug == pytest.approx(90.0, rel=1e-3)


def test_changing_pm25_across_hour_boundaries(test_location: Location, ist_tz: timezone) -> None:
    """Verify multi-interval split calculation spanning across hour boundaries."""
    # Start: 17:15, Duration: 60 min (ends at 18:15)
    # Hour 17:00 -> 60.0 µg/m³ (covers 17:15 - 18:00 = 45 min)
    # Hour 18:00 -> 40.0 µg/m³ (covers 18:00 - 18:15 = 15 min)
    # Running VE = 0.045 m³/min
    # Dose 1: 60.0 * 0.045 * 45 = 121.5 µg
    # Dose 2: 40.0 * 0.045 * 15 = 27.0 µg
    # Total = 148.5 µg
    # Weighted avg PM2.5 = (60*45 + 40*15) / 60 = 55.0 µg/m³
    t17 = datetime(2026, 10, 10, 17, 0, tzinfo=ist_tz)
    t18 = datetime(2026, 10, 10, 18, 0, tzinfo=ist_tz)
    series = create_series(
        [(t17, 60.0, 28.0), (t18, 40.0, 26.0)],
        test_location,
    )

    start = datetime(2026, 10, 10, 17, 15, tzinfo=ist_tz)
    result = calculate_slot_exposure(
        start_time=start,
        duration_min=60,
        activity="running",
        forecast_series=series,
    )

    assert result.total_dose_ug == pytest.approx(148.5, rel=1e-3)
    assert result.avg_pm25_ug_m3 == pytest.approx(55.0, rel=1e-3)
    assert len(result.intervals) == 2
    assert result.intervals[0].duration_min == 45.0
    assert result.intervals[0].dose_ug == pytest.approx(121.5, rel=1e-3)
    assert result.intervals[1].duration_min == 15.0
    assert result.intervals[1].dose_ug == pytest.approx(27.0, rel=1e-3)


def test_missing_pm25_never_treated_as_zero(test_location: Location, ist_tz: timezone) -> None:
    """Verify that None/missing PM2.5 strictly raises ExposureCalculationError and is never zeroed."""
    t17 = datetime(2026, 10, 10, 17, 0, tzinfo=ist_tz)
    # PM2.5 is None (missing observation or model failure)
    series = create_series([(t17, None, 25.0)], test_location)

    with pytest.raises(ExposureCalculationError, match="missing PM2.5 data"):
        calculate_slot_exposure(
            start_time=t17,
            duration_min=30,
            activity="walking",
            forecast_series=series,
        )


def test_incomplete_coverage_raises_error(test_location: Location, ist_tz: timezone) -> None:
    """Verify that insufficient forecast coverage across the window raises ExposureCalculationError."""
    # Only 1 hour provided (17:00-18:00), but activity requires 90 minutes (17:00-18:30)
    t17 = datetime(2026, 10, 10, 17, 0, tzinfo=ist_tz)
    series = create_series([(t17, 50.0, 25.0)], test_location)

    with pytest.raises(ExposureCalculationError, match="Incomplete forecast coverage"):
        calculate_slot_exposure(
            start_time=t17,
            duration_min=90,
            activity="cycling",
            forecast_series=series,
        )


def test_unsupported_activity_rejected() -> None:
    """Verify unsupported activities fail with a helpful error."""
    with pytest.raises(ValueError, match="Unsupported activity 'underwater_basket_weaving'"):
        get_activity_ventilation_rate("underwater_basket_weaving")


def test_custom_ventilation_rate(test_location: Location, ist_tz: timezone) -> None:
    """Verify custom ventilation rate overrides default activity lookup."""
    t0 = datetime(2026, 10, 10, 17, 0, tzinfo=ist_tz)
    series = create_series([(t0, 100.0, 20.0)], test_location)

    # Custom rate: 0.020 m³/min, duration 30 min, PM2.5: 100 µg/m³
    # Expected dose = 100 * 0.020 * 30 = 60.0 µg
    result = calculate_slot_exposure(
        start_time=t0,
        duration_min=30,
        activity="custom",
        forecast_series=series,
        custom_rate_m3_min=0.020,
    )
    assert result.total_dose_ug == pytest.approx(60.0, rel=1e-3)
    assert result.ventilation_rate_m3_min == 0.020


def test_timezone_naive_timestamp_rejected(test_location: Location) -> None:
    """Verify that naive datetimes without timezone raise ValueError."""
    naive_dt = datetime(2026, 10, 10, 17, 0)
    series = create_series([(datetime(2026, 10, 10, 17, 0, tzinfo=UTC), 50.0, 25.0)], test_location)

    with pytest.raises(ValueError, match="timezone-aware"):
        calculate_slot_exposure(
            start_time=naive_dt,
            duration_min=30,
            activity="running",
            forecast_series=series,
        )


def test_temperature_time_weighted(test_location: Location, ist_tz: timezone) -> None:
    """Verify that average temperature is time-weighted across sub-intervals (P1-2 fix)."""
    # 45 min at 30.0°C and 15 min at 20.0°C -> time-weighted average is 27.5°C
    t17 = datetime(2026, 10, 10, 17, 0, tzinfo=ist_tz)
    t18 = datetime(2026, 10, 10, 18, 0, tzinfo=ist_tz)
    series = create_series([(t17, 40.0, 30.0), (t18, 40.0, 20.0)], test_location)

    start = datetime(2026, 10, 10, 17, 15, tzinfo=ist_tz)
    result = calculate_slot_exposure(
        start_time=start,
        duration_min=60,
        activity="running",
        forecast_series=series,
    )

    # 45m * 30 + 15m * 20 = 1350 + 300 = 1650 / 60 = 27.5°C
    assert result.avg_temperature_c == pytest.approx(27.5, rel=1e-2)
    assert result.max_temperature_c == 30.0
