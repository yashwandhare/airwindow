"""API Route for activity schedule planning."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.dependencies import ProviderDep
from app.api.schemas import (
    BaselineResponse,
    BestSlotResponse,
    CandidateSlotResponse,
    IntervalResponse,
    PlanRequest,
    PlanResponse,
)
from app.core.comparison import evaluate_baseline
from app.core.optimizer import optimize_schedule

router = APIRouter(prefix="", tags=["Planning"])


@router.post(
    "/plan",
    response_model=PlanResponse,
    summary="Generate pollution-optimized activity schedule",
    description=(
        "Evaluates candidate time slots within the user's available window to find the "
        "lowest-dose feasible activity window, compared against the user's baseline."
    ),
)
async def create_plan(
    request: PlanRequest,
    provider: ProviderDep,
) -> PlanResponse:
    """Evaluate activity slots and return the optimal schedule with baseline comparison."""
    if request.window_end <= request.window_start:
        raise HTTPException(
            status_code=422,
            detail=f"window_end ({request.window_end.isoformat()}) must be after window_start ({request.window_start.isoformat()}).",
        )

    # 1. Fetch normalized forecast data covering the full requested window
    forecast_series = await provider.get_forecast(
        location=request.location,
        start_time=request.window_start,
        end_time=request.window_end,
    )

    # 2. Evaluate data quality and trust
    data_quality = forecast_series.assess_quality(reference_time=request.window_start)

    # 3. Run schedule optimizer across candidate slots
    opt_result = optimize_schedule(
        window_start=request.window_start,
        window_end=request.window_end,
        duration_min=request.duration_min,
        activity=request.activity,
        forecast_series=forecast_series,
        step_min=request.step_min,
        max_temperature_c=request.max_temperature_c,
        custom_rate_m3_min=request.custom_ventilation_rate_m3_min,
    )

    # 4. Evaluate baseline comparison
    baseline_eval = evaluate_baseline(
        recommended_slot=opt_result.best,
        window_start=request.window_start,
        duration_min=request.duration_min,
        activity=request.activity,
        forecast_series=forecast_series,
        usual_time=request.usual_time,
        custom_rate_m3_min=request.custom_ventilation_rate_m3_min,
    )

    # 5. Assemble candidate response items
    candidate_responses: list[CandidateSlotResponse] = [
        CandidateSlotResponse(
            start=c.start,
            end=c.end,
            duration_min=c.duration_min,
            dose_ug=c.dose_ug,
            avg_pm25_ug_m3=c.avg_pm25_ug_m3,
            avg_temperature_c=c.avg_temperature_c,
            max_temperature_c=c.max_temperature_c,
            is_valid=c.is_valid,
            reason_invalid=c.reason_invalid,
        )
        for c in opt_result.candidates
    ]

    # 6. Assemble best recommendation item if available
    best_response: BestSlotResponse | None = None
    if opt_result.best is not None and opt_result.best.dose_ug is not None:
        best_intervals = [
            IntervalResponse(
                start=inv.start,
                end=inv.end,
                duration_min=inv.duration_min,
                pm25_ug_m3=inv.pm25_ug_m3,
                dose_ug=inv.dose_ug,
                temperature_c=inv.temperature_c,
            )
            for inv in opt_result.best.intervals
        ]
        best_response = BestSlotResponse(
            start=opt_result.best.start,
            end=opt_result.best.end,
            duration_min=opt_result.best.duration_min,
            activity=request.activity,
            dose_ug=opt_result.best.dose_ug,
            reduction_pct=baseline_eval.reduction_pct,
            confidence=data_quality.confidence,
            avg_pm25_ug_m3=opt_result.best.avg_pm25_ug_m3 or 0.0,
            avg_temperature_c=opt_result.best.avg_temperature_c,
            max_temperature_c=opt_result.best.max_temperature_c,
            intervals=best_intervals,
        )

    # 7. Assemble baseline response
    baseline_response: BaselineResponse = BaselineResponse(
        start=baseline_eval.start,
        end=baseline_eval.end,
        duration_min=baseline_eval.duration_min,
        activity=baseline_eval.activity,
        dose_ug=baseline_eval.dose_ug,
        is_valid=baseline_eval.is_valid,
        warning=baseline_eval.warning,
    )

    all_warnings = list(opt_result.warnings)
    if baseline_eval.warning:
        all_warnings.append(baseline_eval.warning)
    if data_quality.is_stale:
        all_warnings.append(
            f"Forecast data source is over 24 hours old ({data_quality.freshness_seconds // 3600}h)."
        )

    return PlanResponse(
        status=opt_result.status,
        best=best_response,
        baseline=baseline_response,
        candidates=candidate_responses,
        series=forecast_series.points,
        data_quality=data_quality,
        warnings=all_warnings,
    )
