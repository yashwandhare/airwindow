"""API Route for what-if scenario comparison."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.dependencies import ProviderDep
from app.api.schemas import (
    BestSlotResponse,
    PlanRequest,
    WhatIfRequest,
    WhatIfResponse,
)
from app.core.comparison import compare_scenarios
from app.core.optimizer import optimize_schedule

router = APIRouter(prefix="", tags=["What-If Scenarios"])


def _apply_overrides(base: PlanRequest, req: WhatIfRequest) -> PlanRequest:
    """Build modified PlanRequest by using modified_plan or applying overrides."""
    if req.modified_plan is not None:
        return req.modified_plan

    if req.overrides is None:
        raise HTTPException(
            status_code=422,
            detail="Either 'modified_plan' or 'overrides' must be provided in what-if request.",
        )

    base_data = base.model_dump()
    override_data = {k: v for k, v in req.overrides.model_dump().items() if v is not None}
    merged_data = {**base_data, **override_data}
    return PlanRequest(**merged_data)


@router.post(
    "/whatif",
    response_model=WhatIfResponse,
    summary="Compare schedule scenarios",
    description=(
        "Compares a base activity plan against an alternative (e.g. changing activity, "
        "duration, or window) and calculates dose differences and percentage changes."
    ),
)
async def evaluate_whatif(
    request: WhatIfRequest,
    provider: ProviderDep,
) -> WhatIfResponse:
    """Execute before/after scenario comparison."""
    base_plan = request.base_plan
    modified_plan = _apply_overrides(base_plan, request)

    # Validate windows
    if base_plan.window_end <= base_plan.window_start:
        raise HTTPException(
            status_code=422,
            detail="Base plan window_end must be after window_start.",
        )
    if modified_plan.window_end <= modified_plan.window_start:
        raise HTTPException(
            status_code=422,
            detail="Modified plan window_end must be after window_start.",
        )

    # Fetch forecast for base window
    base_series = await provider.get_forecast(
        location=base_plan.location,
        start_time=base_plan.window_start,
        end_time=base_plan.window_end,
    )

    # Fetch forecast for modified window (if same location and window, can reuse)
    if (
        modified_plan.location == base_plan.location
        and modified_plan.window_start == base_plan.window_start
        and modified_plan.window_end == base_plan.window_end
    ):
        modified_series = base_series
    else:
        modified_series = await provider.get_forecast(
            location=modified_plan.location,
            start_time=modified_plan.window_start,
            end_time=modified_plan.window_end,
        )

    # Optimize both
    base_opt = optimize_schedule(
        window_start=base_plan.window_start,
        window_end=base_plan.window_end,
        duration_min=base_plan.duration_min,
        activity=base_plan.activity,
        forecast_series=base_series,
        step_min=base_plan.step_min,
        max_temperature_c=base_plan.max_temperature_c,
        custom_rate_m3_min=base_plan.custom_ventilation_rate_m3_min,
    )

    modified_opt = optimize_schedule(
        window_start=modified_plan.window_start,
        window_end=modified_plan.window_end,
        duration_min=modified_plan.duration_min,
        activity=modified_plan.activity,
        forecast_series=modified_series,
        step_min=modified_plan.step_min,
        max_temperature_c=modified_plan.max_temperature_c,
        custom_rate_m3_min=modified_plan.custom_ventilation_rate_m3_min,
    )

    # Compare
    comparison = compare_scenarios(
        base_slot=base_opt.best,
        modified_slot=modified_opt.best,
        base_label=f"Base ({base_plan.activity}, {base_plan.duration_min}m)",
        modified_label=f"Modified ({modified_plan.activity}, {modified_plan.duration_min}m)",
    )

    # Format response recommendations
    base_resp: BestSlotResponse | None = None
    if base_opt.best is not None and base_opt.best.dose_ug is not None:
        base_resp = BestSlotResponse(
            start=base_opt.best.start,
            end=base_opt.best.end,
            duration_min=base_opt.best.duration_min,
            activity=base_plan.activity,
            dose_ug=base_opt.best.dose_ug,
            reduction_pct=None,
            confidence="high",
            avg_pm25_ug_m3=base_opt.best.avg_pm25_ug_m3 or 0.0,
            avg_temperature_c=base_opt.best.avg_temperature_c,
            max_temperature_c=base_opt.best.max_temperature_c,
            intervals=[],
        )

    mod_resp: BestSlotResponse | None = None
    if modified_opt.best is not None and modified_opt.best.dose_ug is not None:
        mod_resp = BestSlotResponse(
            start=modified_opt.best.start,
            end=modified_opt.best.end,
            duration_min=modified_opt.best.duration_min,
            activity=modified_plan.activity,
            dose_ug=modified_opt.best.dose_ug,
            reduction_pct=comparison.reduction_pct,
            confidence="high",
            avg_pm25_ug_m3=modified_opt.best.avg_pm25_ug_m3 or 0.0,
            avg_temperature_c=modified_opt.best.avg_temperature_c,
            max_temperature_c=modified_opt.best.max_temperature_c,
            intervals=[],
        )

    all_warnings = list(base_opt.warnings) + list(modified_opt.warnings) + list(comparison.warnings)

    overall_status = (
        "ok" if (base_opt.status == "ok" and modified_opt.status == "ok") else "no_recommendation"
    )

    return WhatIfResponse(
        status=overall_status,
        base_recommendation=base_resp,
        modified_recommendation=mod_resp,
        dose_delta_ug=comparison.dose_delta_ug,
        reduction_pct=comparison.reduction_pct,
        summary_explanation=comparison.summary_explanation,
        warnings=all_warnings,
    )
