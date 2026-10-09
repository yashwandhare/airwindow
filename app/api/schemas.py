"""Pydantic schemas for AirWindow API contracts.

Defines stable, documented request and response structures for activity
planning, what-if scenarios, and forecast trust reporting.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.core.exposure import ACTIVITY_PROFILES, EXPOSURE_DISCLAIMER
from app.data.models import ForecastDataQuality, Location, NormalizedForecastPoint


class PlanRequest(BaseModel):
    """Activity scheduling request payload."""

    location: Location = Field(
        default_factory=lambda: Location(name="Nagpur", latitude=21.1458, longitude=79.0882),
        description="Target geographic location",
    )
    activity: str = Field(
        default="running",
        description=f"Activity type. Supported: {', '.join(sorted(ACTIVITY_PROFILES.keys()))}",
    )
    duration_min: int = Field(
        default=45,
        ge=5,
        le=360,
        description="Continuous activity duration in minutes (5 - 360)",
    )
    window_start: datetime = Field(
        ...,
        description="Earliest acceptable activity start time (timezone-aware ISO 8601)",
    )
    window_end: datetime = Field(
        ...,
        description="Latest acceptable activity completion time (timezone-aware ISO 8601)",
    )
    usual_time: datetime | None = Field(
        default=None,
        description="User's usual start time for baseline comparison (optional, timezone-aware)",
    )
    max_temperature_c: float | None = Field(
        default=None,
        description="Optional maximum temperature threshold in °C",
    )
    step_min: int = Field(
        default=15,
        ge=5,
        le=60,
        description="Candidate evaluation interval step in minutes (default: 15)",
    )
    custom_ventilation_rate_m3_min: float | None = Field(
        default=None,
        ge=0.001,
        le=0.200,
        description="Optional override for breathing ventilation rate (m³/min)",
    )

    @field_validator("activity")
    @classmethod
    def validate_activity(cls, v: str) -> str:
        key = v.strip().lower()
        if key not in ACTIVITY_PROFILES:
            supported = ", ".join(sorted(ACTIVITY_PROFILES.keys()))
            raise ValueError(
                f"Unsupported activity '{v}'. Supported activities are: {supported}. "
                f"Or specify a custom_ventilation_rate_m3_min."
            )
        return key

    @field_validator("window_start", "window_end", "usual_time")
    @classmethod
    def validate_tz(cls, v: datetime | None) -> datetime | None:
        if v is not None and (v.tzinfo is None or v.tzinfo.utcoffset(v) is None):
            raise ValueError(
                "Datetime must be timezone-aware (e.g., '2026-10-10T17:00:00+05:30' or '2026-10-10T17:00:00Z')."
            )
        return v


class IntervalResponse(BaseModel):
    """Sub-interval exposure breakdown."""

    start: datetime
    end: datetime
    duration_min: float
    pm25_ug_m3: float
    dose_ug: float
    temperature_c: float | None = None


class CandidateSlotResponse(BaseModel):
    """Candidate activity slot score."""

    start: datetime
    end: datetime
    duration_min: int
    dose_ug: float | None
    avg_pm25_ug_m3: float | None
    avg_temperature_c: float | None
    max_temperature_c: float | None
    is_valid: bool
    reason_invalid: str | None = None


class BestSlotResponse(BaseModel):
    """Recommended optimal activity slot."""

    start: datetime
    end: datetime
    duration_min: int
    activity: str
    dose_ug: float
    reduction_pct: float | None
    confidence: str
    avg_pm25_ug_m3: float
    avg_temperature_c: float | None
    max_temperature_c: float | None
    intervals: list[IntervalResponse] = Field(default_factory=list)


class BaselineResponse(BaseModel):
    """Baseline slot calculation result."""

    start: datetime
    end: datetime
    duration_min: int
    activity: str
    dose_ug: float | None
    is_valid: bool
    warning: str | None = None


class PlanResponse(BaseModel):
    """Comprehensive plan response."""

    status: str = Field(
        ..., description="'ok' if recommendation found, 'no_recommendation' otherwise"
    )
    best: BestSlotResponse | None = Field(
        default=None, description="Lowest-dose feasible time slot"
    )
    baseline: BaselineResponse | None = Field(default=None, description="Evaluated baseline slot")
    candidates: list[CandidateSlotResponse] = Field(
        default_factory=list, description="All evaluated candidate slots for charting"
    )
    series: list[NormalizedForecastPoint] = Field(
        default_factory=list, description="Hourly forecast time-series for the window"
    )
    data_quality: ForecastDataQuality = Field(
        ..., description="Forecast freshness and confidence metadata"
    )
    warnings: list[str] = Field(
        default_factory=list, description="Actionable warnings or boundary notices"
    )
    disclaimer: str = Field(
        default=EXPOSURE_DISCLAIMER, description="Model explanation and non-medical disclaimer"
    )


class PlanOverrides(BaseModel):
    """Optional modifications applied to a base plan for what-if exploration."""

    activity: str | None = None
    duration_min: int | None = Field(default=None, ge=5, le=360)
    window_start: datetime | None = None
    window_end: datetime | None = None
    usual_time: datetime | None = None
    max_temperature_c: float | None = None
    step_min: int | None = Field(default=None, ge=5, le=60)


class WhatIfRequest(BaseModel):
    """What-if scenario comparison request."""

    base_plan: PlanRequest
    modified_plan: PlanRequest | None = None
    overrides: PlanOverrides | None = None


class WhatIfResponse(BaseModel):
    """What-if scenario comparison response."""

    status: str
    base_recommendation: BestSlotResponse | None
    modified_recommendation: BestSlotResponse | None
    dose_delta_ug: float | None = Field(
        default=None,
        description="Modified dose - Base dose (negative value indicates lower pollution dose)",
    )
    reduction_pct: float | None = Field(
        default=None,
        description="Percentage reduction achieved by modified scenario",
    )
    summary_explanation: str
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = Field(default=EXPOSURE_DISCLAIMER)


class TrustResponse(BaseModel):
    """Forecast data trust and freshness report."""

    location: Location
    source: str
    generated_at: datetime
    freshness_seconds: int
    is_stale: bool
    has_station_observations: bool
    missing_intervals_count: int
    confidence: str
    confidence_reason: str
    disclaimer: str = Field(default=EXPOSURE_DISCLAIMER)
