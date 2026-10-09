"""Tests for baseline reduction and what-if calculations."""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.comparison import compare_scenarios, evaluate_baseline
from app.core.optimizer import CandidateSlot
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


def test_baseline_positive_reduction(test_location: Location, ist_tz: timezone) -> None:
    """Verify standard positive percentage reduction calculation."""
    # Usual time 17:00 has PM2.5 = 100.0 (Dose = 100 * 0.045 * 40 = 180.0 µg)
    # Recommended slot at 18:00 has dose = 90.0 µg
    # Reduction = ((180 - 90) / 180) * 100 = 50.0%
    t17 = datetime(2026, 10, 10, 17, 0, tzinfo=ist_tz)
    t18 = datetime(2026, 10, 10, 18, 0, tzinfo=ist_tz)
    series = make_series([(t17, 100.0, 25.0), (t18, 50.0, 24.0)], test_location)

    rec_slot = CandidateSlot(
        start=t18,
        end=t18 + timedelta(minutes=40),
        duration_min=40,
        dose_ug=90.0,
        avg_pm25_ug_m3=50.0,
        avg_temperature_c=24.0,
        max_temperature_c=24.0,
        is_valid=True,
    )

    baseline = evaluate_baseline(
        recommended_slot=rec_slot,
        window_start=t17,
        duration_min=40,
        activity="running",
        forecast_series=series,
        usual_time=t17,
    )

    assert baseline.is_valid is True
    assert baseline.dose_ug == pytest.approx(180.0, rel=1e-3)
    assert baseline.reduction_pct == pytest.approx(50.0, rel=1e-2)


def test_baseline_zero_dose_safe_handling(test_location: Location, ist_tz: timezone) -> None:
    """Verify zero baseline dose does not cause ZeroDivisionError."""
    t17 = datetime(2026, 10, 10, 17, 0, tzinfo=ist_tz)
    series = make_series([(t17, 0.0, 25.0)], test_location)

    rec_slot = CandidateSlot(
        start=t17,
        end=t17 + timedelta(minutes=30),
        duration_min=30,
        dose_ug=0.0,
        avg_pm25_ug_m3=0.0,
        avg_temperature_c=25.0,
        max_temperature_c=25.0,
        is_valid=True,
    )

    baseline = evaluate_baseline(
        recommended_slot=rec_slot,
        window_start=t17,
        duration_min=30,
        activity="walking",
        forecast_series=series,
    )

    assert baseline.is_valid is True
    assert baseline.dose_ug == 0.0
    assert baseline.reduction_pct == 0.0


def test_baseline_negative_reduction_not_falsified(
    test_location: Location, ist_tz: timezone
) -> None:
    """Verify negative reduction is preserved when baseline is cleaner than recommendation."""
    # Baseline at 17:00 dose = 50.0 µg, recommended slot dose = 75.0 µg
    # Reduction = ((50 - 75) / 50) * 100 = -50.0%
    t17 = datetime(2026, 10, 10, 17, 0, tzinfo=ist_tz)
    series = make_series([(t17, 25.0, 25.0)], test_location)

    rec_slot = CandidateSlot(
        start=t17,
        end=t17 + timedelta(minutes=60),
        duration_min=60,
        dose_ug=75.0,
        avg_pm25_ug_m3=35.0,
        avg_temperature_c=25.0,
        max_temperature_c=25.0,
        is_valid=True,
    )

    baseline = evaluate_baseline(
        recommended_slot=rec_slot,
        window_start=t17,
        duration_min=60,
        activity="walking",  # VE = 0.016, Dose = 25 * 0.016 * 60 = 24.0 µg
        forecast_series=series,
    )

    assert baseline.is_valid is True
    assert baseline.reduction_pct is not None
    assert baseline.reduction_pct < 0.0  # Must be negative, not clamped to 0


def test_baseline_missing_data_handled_gracefully(
    test_location: Location, ist_tz: timezone
) -> None:
    """Verify missing data at baseline produces invalid baseline result without crashing."""
    t17 = datetime(2026, 10, 10, 17, 0, tzinfo=ist_tz)
    series = make_series([(t17, None, 25.0)], test_location)

    baseline = evaluate_baseline(
        recommended_slot=None,
        window_start=t17,
        duration_min=30,
        activity="running",
        forecast_series=series,
        usual_time=t17,
    )

    assert baseline.is_valid is False
    assert baseline.dose_ug is None
    assert baseline.reduction_pct is None
    assert baseline.warning is not None


def test_whatif_comparison_calculation(ist_tz: timezone) -> None:
    """Verify what-if scenario comparison accurately computes deltas and explanation."""
    t17 = datetime(2026, 10, 10, 17, 0, tzinfo=ist_tz)
    t18 = datetime(2026, 10, 10, 18, 0, tzinfo=ist_tz)

    base = CandidateSlot(
        start=t17,
        end=t17 + timedelta(minutes=45),
        duration_min=45,
        dose_ug=120.0,
        avg_pm25_ug_m3=60.0,
        avg_temperature_c=28.0,
        max_temperature_c=28.0,
        is_valid=True,
    )

    modified = CandidateSlot(
        start=t18,
        end=t18 + timedelta(minutes=45),
        duration_min=45,
        dose_ug=60.0,
        avg_pm25_ug_m3=30.0,
        avg_temperature_c=26.0,
        max_temperature_c=26.0,
        is_valid=True,
    )

    comp = compare_scenarios(base, modified, "Original 17:00 Run", "Shifted 18:00 Run")

    assert comp.base_dose_ug == 120.0
    assert comp.modified_dose_ug == 60.0
    assert comp.dose_delta_ug == -60.0
    assert comp.reduction_pct == 50.0
    assert "reduces estimated dose" in comp.summary_explanation
