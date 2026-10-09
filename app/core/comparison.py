"""Baseline reduction and what-if scenario comparison calculations.

Provides pure Python calculation of percentage exposure reduction against
user baselines and scenario comparisons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.core.exposure import (
    ExposureCalculationError,
    SlotExposureResult,
    calculate_slot_exposure,
)
from app.core.optimizer import CandidateSlot
from app.data.models import NormalizedForecastSeries


@dataclass
class BaselineEvaluation:
    """Calculated baseline evaluation result."""

    start: datetime
    end: datetime
    duration_min: int
    activity: str
    dose_ug: float | None
    reduction_pct: float | None
    is_valid: bool
    warning: str | None = None


@dataclass
class WhatIfComparisonResult:
    """Outcome of comparing a modified plan against a base plan."""

    base_slot: CandidateSlot | None
    modified_slot: CandidateSlot | None
    base_dose_ug: float | None
    modified_dose_ug: float | None
    dose_delta_ug: float | None  # modified - base (negative means reduction)
    reduction_pct: float | None  # ((base - modified) / base) * 100
    summary_explanation: str
    warnings: list[str] = field(default_factory=list)


def evaluate_baseline(
    recommended_slot: CandidateSlot | None,
    window_start: datetime,
    duration_min: int,
    activity: str,
    forecast_series: NormalizedForecastSeries,
    usual_time: datetime | None = None,
    custom_rate_m3_min: float | None = None,
) -> BaselineEvaluation:
    """Calculate the baseline dose and relative percentage reduction.

    Formula:
        reduction_pct = ((baseline_dose - recommended_dose) / baseline_dose) × 100

    Handles zero, missing, and negative reductions safely without falsifying results.
    """
    baseline_start = usual_time if usual_time is not None else window_start

    try:
        baseline_exp: SlotExposureResult = calculate_slot_exposure(
            start_time=baseline_start,
            duration_min=duration_min,
            activity=activity,
            forecast_series=forecast_series,
            custom_rate_m3_min=custom_rate_m3_min,
        )
        baseline_dose = baseline_exp.total_dose_ug

        # Calculate percentage reduction if recommended slot is valid
        reduction_pct: float | None = None
        warning: str | None = None

        if recommended_slot is not None and recommended_slot.dose_ug is not None:
            if baseline_dose > 0:
                reduction_pct = round(((baseline_dose - recommended_slot.dose_ug) / baseline_dose) * 100.0, 1)
            elif baseline_dose == 0.0 and recommended_slot.dose_ug == 0.0:
                reduction_pct = 0.0
            else:
                warning = "Baseline dose is 0.0 µg; percentage reduction cannot be computed."
        else:
            warning = "No valid recommendation available to compute reduction against baseline."

        return BaselineEvaluation(
            start=baseline_start,
            end=baseline_exp.end,
            duration_min=duration_min,
            activity=activity,
            dose_ug=baseline_dose,
            reduction_pct=reduction_pct,
            is_valid=True,
            warning=warning,
        )

    except (ExposureCalculationError, ValueError) as e:
        return BaselineEvaluation(
            start=baseline_start,
            end=baseline_start + timedelta(minutes=duration_min),
            duration_min=duration_min,
            activity=activity,
            dose_ug=None,
            reduction_pct=None,
            is_valid=False,
            warning=f"Baseline exposure could not be evaluated: {str(e)}",
        )


def compare_scenarios(
    base_slot: CandidateSlot | None,
    modified_slot: CandidateSlot | None,
    base_label: str = "Base Plan",
    modified_label: str = "Modified Plan",
) -> WhatIfComparisonResult:
    """Compare two activity schedules (e.g. changing activity, duration, or time window)."""
    warnings: list[str] = []

    if base_slot is None or base_slot.dose_ug is None:
        warnings.append(f"{base_label} has no valid recommendation.")
    if modified_slot is None or modified_slot.dose_ug is None:
        warnings.append(f"{modified_label} has no valid recommendation.")

    if base_slot is None or base_slot.dose_ug is None or modified_slot is None or modified_slot.dose_ug is None:
        return WhatIfComparisonResult(
            base_slot=base_slot,
            modified_slot=modified_slot,
            base_dose_ug=base_slot.dose_ug if base_slot else None,
            modified_dose_ug=modified_slot.dose_ug if modified_slot else None,
            dose_delta_ug=None,
            reduction_pct=None,
            summary_explanation="Cannot compare scenarios because one or both plans could not find a feasible slot.",
            warnings=warnings,
        )

    base_dose = base_slot.dose_ug
    mod_dose = modified_slot.dose_ug
    delta_ug = round(mod_dose - base_dose, 2)

    reduction_pct: float | None = None
    if base_dose > 0:
        reduction_pct = round(((base_dose - mod_dose) / base_dose) * 100.0, 1)
    elif base_dose == 0.0 and mod_dose == 0.0:
        reduction_pct = 0.0
    else:
        warnings.append("Base dose is 0.0 µg; percentage reduction cannot be computed.")

    # Formulate human-readable explanation
    if delta_ug < 0:
        pct_str = f" ({abs(reduction_pct)}% reduction)" if reduction_pct is not None else ""
        explanation = (
            f"{modified_label} reduces estimated dose from {base_dose:.1f} µg to {mod_dose:.1f} µg, "
            f"saving {abs(delta_ug):.1f} µg{pct_str}."
        )
    elif delta_ug > 0:
        pct_str = f" ({abs(reduction_pct)}% increase)" if reduction_pct is not None else ""
        explanation = (
            f"{modified_label} increases estimated dose from {base_dose:.1f} µg to {mod_dose:.1f} µg "
            f"(+{delta_ug:.1f} µg{pct_str})."
        )
    else:
        explanation = f"{modified_label} has the identical estimated dose ({base_dose:.1f} µg) as {base_label}."

    return WhatIfComparisonResult(
        base_slot=base_slot,
        modified_slot=modified_slot,
        base_dose_ug=base_dose,
        modified_dose_ug=mod_dose,
        dose_delta_ug=delta_ug,
        reduction_pct=reduction_pct,
        summary_explanation=explanation,
        warnings=warnings,
    )
