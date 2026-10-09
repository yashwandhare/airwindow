"""Tests for schedule optimizer constraints and behavior."""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.optimizer import optimize_schedule
from app.data.models import Location, NormalizedForecastPoint, NormalizedForecastSeries


@pytest.fixture
def ist_tz() -> timezone:
    return timezone(timedelta(hours=5, minutes=30))


@pytest.fixture
def test_location() -> Location:
    return Location(name="Nagpur", latitude=21.1458, longitude=79.0882)


def make_series(
    hourly_specs: list[tuple[datetime, float | None, float | None]],
    location: Location,
) -> NormalizedForecastSeries:
    points = [
        NormalizedForecastPoint(
            timestamp=dt,
            pm25_ug_m3=pm,
            temperature_c=temp,
            source="test",
        )
        for dt, pm, temp in hourly_specs
    ]
    return NormalizedForecastSeries(
        location=location,
        generated_at=hourly_specs[0][0],
        source="test",
        points=points,
    )


def test_optimizer_15min_stepping_and_window_fit(test_location: Location, ist_tz: timezone) -> None:
    """Verify candidate generation uses 15-minute steps and fits strictly within window."""
    # Window: 17:00 to 19:00 (120 mins). Duration: 45 min. Step: 15 min.
    # Candidate starts: 17:00, 17:15, 17:30, 17:45, 18:00, 18:15 (total 6)
    # 18:30 is NOT generated because 18:30 + 45 min = 19:15 > 19:00
    t17 = datetime(2026, 10, 10, 17, 0, tzinfo=ist_tz)
    t18 = datetime(2026, 10, 10, 18, 0, tzinfo=ist_tz)
    t19 = datetime(2026, 10, 10, 19, 0, tzinfo=ist_tz)
    series = make_series([(t17, 50.0, 25.0), (t18, 30.0, 24.0), (t19, 40.0, 23.0)], test_location)

    res = optimize_schedule(
        window_start=t17,
        window_end=t19,
        duration_min=45,
        activity="running",
        forecast_series=series,
        step_min=15,
    )

    assert res.status == "ok"
    assert res.total_candidates == 6
    assert res.valid_candidates_count == 6
    assert len(res.candidates) == 6

    # Verify all candidate end times <= window_end
    for c in res.candidates:
        assert c.start >= t17
        assert c.end <= t19
        assert (c.end - c.start).total_seconds() / 60.0 == 45


def test_optimizer_picks_lowest_dose(test_location: Location, ist_tz: timezone) -> None:
    """Verify optimizer selects the candidate slot with minimum estimated dose."""
    # Hour 17:00 -> 80 µg/m³ (high pollution)
    # Hour 18:00 -> 20 µg/m³ (clean air window)
    # Hour 19:00 -> 60 µg/m³
    t17 = datetime(2026, 10, 10, 17, 0, tzinfo=ist_tz)
    t18 = datetime(2026, 10, 10, 18, 0, tzinfo=ist_tz)
    t19 = datetime(2026, 10, 10, 19, 0, tzinfo=ist_tz)
    t20 = datetime(2026, 10, 10, 20, 0, tzinfo=ist_tz)
    series = make_series(
        [(t17, 80.0, 25.0), (t18, 20.0, 24.0), (t19, 60.0, 23.0), (t20, 70.0, 22.0)],
        test_location,
    )

    res = optimize_schedule(
        window_start=t17,
        window_end=t20,
        duration_min=60,
        activity="cycling",  # VE = 0.035
        forecast_series=series,
        step_min=15,
    )

    assert res.status == "ok"
    assert res.best is not None
    # Best slot should start at 18:00 (where PM2.5 is 20 µg/m³ for the full hour)
    assert res.best.start == t18
    assert res.best.end == t19
    # Dose = 20 * 0.035 * 60 = 42.0 µg
    assert res.best.dose_ug == pytest.approx(42.0, rel=1e-3)


def test_optimizer_duration_exceeds_window(test_location: Location, ist_tz: timezone) -> None:
    """Verify no recommendation is returned when requested duration exceeds available window."""
    t17 = datetime(2026, 10, 10, 17, 0, tzinfo=ist_tz)
    t18 = datetime(2026, 10, 10, 18, 0, tzinfo=ist_tz)
    series = make_series([(t17, 40.0, 25.0), (t18, 40.0, 25.0)], test_location)

    # Window is 60 minutes, requested duration is 90 minutes
    res = optimize_schedule(
        window_start=t17,
        window_end=t18,
        duration_min=90,
        activity="walking",
        forecast_series=series,
    )

    assert res.status == "no_recommendation"
    assert res.best is None
    assert len(res.warnings) > 0


def test_optimizer_temperature_constraint(test_location: Location, ist_tz: timezone) -> None:
    """Verify candidate slots exceeding max_temperature_c are marked invalid and excluded."""
    # Slot 1: 17:00-18:00 (PM2.5=10.0, Temp=36.0°C) -> would be lowest dose, but exceeds 32°C!
    # Slot 2: 18:00-19:00 (PM2.5=30.0, Temp=31.0°C) -> satisfies Temp <= 32°C
    t17 = datetime(2026, 10, 10, 17, 0, tzinfo=ist_tz)
    t18 = datetime(2026, 10, 10, 18, 0, tzinfo=ist_tz)
    t19 = datetime(2026, 10, 10, 19, 0, tzinfo=ist_tz)
    series = make_series([(t17, 10.0, 36.0), (t18, 30.0, 31.0)], test_location)

    res = optimize_schedule(
        window_start=t17,
        window_end=t19,
        duration_min=60,
        activity="running",
        forecast_series=series,
        step_min=60,
        max_temperature_c=32.0,
    )

    assert res.status == "ok"
    assert res.best is not None
    # Slot at 17:00 violated temp; best must be 18:00
    assert res.best.start == t18
    assert res.candidates[0].is_valid is False
    assert "exceeds constraint" in (res.candidates[0].reason_invalid or "")


def test_optimizer_handles_missing_pm25_candidate(
    test_location: Location, ist_tz: timezone
) -> None:
    """Verify candidate with missing PM2.5 is marked invalid, while valid ones are kept."""
    # Hour 17: PM2.5=None (missing)
    # Hour 18: PM2.5=35.0
    t17 = datetime(2026, 10, 10, 17, 0, tzinfo=ist_tz)
    t18 = datetime(2026, 10, 10, 18, 0, tzinfo=ist_tz)
    t19 = datetime(2026, 10, 10, 19, 0, tzinfo=ist_tz)
    series = make_series([(t17, None, 25.0), (t18, 35.0, 24.0)], test_location)

    res = optimize_schedule(
        window_start=t17,
        window_end=t19,
        duration_min=60,
        activity="walking",
        forecast_series=series,
        step_min=60,
    )

    assert res.status == "ok"
    assert res.best is not None
    assert res.best.start == t18
    assert res.candidates[0].is_valid is False
    assert res.candidates[0].dose_ug is None


def test_optimizer_tie_breaking_earlier_start(test_location: Location, ist_tz: timezone) -> None:
    """Verify deterministic tie-breaking picks the earlier start time when doses are identical."""
    t17 = datetime(2026, 10, 10, 17, 0, tzinfo=ist_tz)
    t18 = datetime(2026, 10, 10, 18, 0, tzinfo=ist_tz)
    t19 = datetime(2026, 10, 10, 19, 0, tzinfo=ist_tz)
    # Identical PM2.5 = 40.0 in both hours
    series = make_series([(t17, 40.0, 25.0), (t18, 40.0, 25.0)], test_location)

    res = optimize_schedule(
        window_start=t17,
        window_end=t19,
        duration_min=60,
        activity="running",
        forecast_series=series,
        step_min=60,
    )

    assert res.status == "ok"
    assert res.best is not None
    # Both have same dose, tie-breaker picks earlier slot (17:00)
    assert res.best.start == t17
