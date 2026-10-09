"""Pure Python Schedule Optimizer for AirWindow.

Evaluates candidate outdoor activity slots across the user's available window
using a configurable step (default 15 minutes) to identify the slot with the
minimum estimated inhaled PM2.5 dose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.core.exposure import (
    ExposureCalculationError,
    IntervalDetail,
    SlotExposureResult,
    calculate_slot_exposure,
)
from app.data.models import NormalizedForecastSeries


@dataclass
class CandidateSlot:
    """Evaluated candidate activity time slot."""

    start: datetime
    end: datetime
    duration_min: int
    dose_ug: float | None
    avg_pm25_ug_m3: float | None
    avg_temperature_c: float | None
    max_temperature_c: float | None
    is_valid: bool
    reason_invalid: str | None = None
    intervals: list[IntervalDetail] = field(default_factory=list)


@dataclass
class OptimizationResult:
    """Comprehensive schedule optimization output."""

    status: str  # "ok" or "no_recommendation"
    best: CandidateSlot | None
    candidates: list[CandidateSlot]
    total_candidates: int
    valid_candidates_count: int
    warnings: list[str] = field(default_factory=list)


def optimize_schedule(
    window_start: datetime,
    window_end: datetime,
    duration_min: int,
    activity: str,
    forecast_series: NormalizedForecastSeries,
    step_min: int = 15,
    max_temperature_c: float | None = None,
    custom_rate_m3_min: float | None = None,
) -> OptimizationResult:
    """Find the lowest-dose feasible activity slot within the requested time window.

    Constraints enforced:
    1. Activity must fit entirely within [window_start, window_end]:
       start >= window_start and start + duration <= window_end.
    2. Missing PM2.5 forecast data excludes candidate (never assumed to be 0).
    3. Optional max temperature constraint excludes candidates exceeding the threshold.
    4. Deterministic tie-breaking: selects candidate with lowest dose, then earliest start.

    Returns:
        OptimizationResult with best candidate (if any), all scored candidates, and warnings.
    """
    if window_start.tzinfo is None or window_end.tzinfo is None:
        raise ValueError("window_start and window_end must be timezone-aware.")
    if window_end <= window_start:
        raise ValueError(
            f"window_end ({window_end.isoformat()}) must be after window_start ({window_start.isoformat()})."
        )
    if duration_min <= 0:
        raise ValueError(f"duration_min must be positive, got {duration_min}.")
    if step_min <= 0:
        raise ValueError(f"step_min must be positive, got {step_min}.")

    warnings: list[str] = []
    candidates: list[CandidateSlot] = []

    window_duration_min = (window_end - window_start).total_seconds() / 60.0
    if duration_min > window_duration_min:
        warnings.append(
            f"Requested activity duration ({duration_min} min) exceeds available window "
            f"({window_duration_min:.0f} min). No feasible slots exist."
        )
        return OptimizationResult(
            status="no_recommendation",
            best=None,
            candidates=[],
            total_candidates=0,
            valid_candidates_count=0,
            warnings=warnings,
        )

    duration_delta = timedelta(minutes=duration_min)
    step_delta = timedelta(minutes=step_min)
    current_start = window_start

    # Generate and evaluate candidate start times
    while current_start + duration_delta <= window_end:
        current_end = current_start + duration_delta

        try:
            exposure_result: SlotExposureResult = calculate_slot_exposure(
                start_time=current_start,
                duration_min=duration_min,
                activity=activity,
                forecast_series=forecast_series,
                custom_rate_m3_min=custom_rate_m3_min,
            )

            # Check optional temperature constraint
            temp_exceeded = False
            temp_reason = None
            if max_temperature_c is not None:
                if exposure_result.max_temperature_c is not None:
                    if exposure_result.max_temperature_c > max_temperature_c:
                        temp_exceeded = True
                        temp_reason = (
                            f"Max temperature ({exposure_result.max_temperature_c}°C) "
                            f"exceeds constraint ({max_temperature_c}°C)"
                        )
                else:
                    warnings.append(
                        f"Temperature constraint ({max_temperature_c}°C) requested but temperature data "
                        f"unavailable for slot {current_start.isoformat()}."
                    )

            if temp_exceeded:
                candidates.append(
                    CandidateSlot(
                        start=current_start,
                        end=current_end,
                        duration_min=duration_min,
                        dose_ug=exposure_result.total_dose_ug,
                        avg_pm25_ug_m3=exposure_result.avg_pm25_ug_m3,
                        avg_temperature_c=exposure_result.avg_temperature_c,
                        max_temperature_c=exposure_result.max_temperature_c,
                        is_valid=False,
                        reason_invalid=temp_reason,
                        intervals=exposure_result.intervals,
                    )
                )
            else:
                candidates.append(
                    CandidateSlot(
                        start=current_start,
                        end=current_end,
                        duration_min=duration_min,
                        dose_ug=exposure_result.total_dose_ug,
                        avg_pm25_ug_m3=exposure_result.avg_pm25_ug_m3,
                        avg_temperature_c=exposure_result.avg_temperature_c,
                        max_temperature_c=exposure_result.max_temperature_c,
                        is_valid=True,
                        reason_invalid=None,
                        intervals=exposure_result.intervals,
                    )
                )

        except ExposureCalculationError as e:
            candidates.append(
                CandidateSlot(
                    start=current_start,
                    end=current_end,
                    duration_min=duration_min,
                    dose_ug=None,
                    avg_pm25_ug_m3=None,
                    avg_temperature_c=None,
                    max_temperature_c=None,
                    is_valid=False,
                    reason_invalid=str(e),
                    intervals=[],
                )
            )

        current_start += step_delta

    valid_candidates = [c for c in candidates if c.is_valid and c.dose_ug is not None]

    if not valid_candidates:
        warnings.append("No candidates met all feasibility and constraint requirements.")
        return OptimizationResult(
            status="no_recommendation",
            best=None,
            candidates=candidates,
            total_candidates=len(candidates),
            valid_candidates_count=0,
            warnings=warnings,
        )

    # Deterministic tie-breaking:
    # 1. Minimum dose_ug (rounded to 4 decimal places for floating-point stability)
    # 2. Earliest start time
    best_candidate = min(
        valid_candidates,
        key=lambda c: (round(c.dose_ug, 4) if c.dose_ug is not None else float("inf"), c.start),
    )

    return OptimizationResult(
        status="ok",
        best=best_candidate,
        candidates=candidates,
        total_candidates=len(candidates),
        valid_candidates_count=len(valid_candidates),
        warnings=warnings,
    )
