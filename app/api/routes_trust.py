"""API Route for forecast data quality, freshness, and trust reporting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query

from app.api.dependencies import ProviderDep
from app.api.schemas import TrustResponse
from app.data.models import Location

router = APIRouter(prefix="", tags=["Forecast Trust"])


@router.get(
    "/forecast/trust",
    response_model=TrustResponse,
    summary="Evaluate forecast data quality and confidence",
    description=(
        "Returns data source freshness, observation availability, missing interval counts, "
        "and rule-based transparent confidence metadata for a given location."
    ),
)
async def get_forecast_trust(
    provider: ProviderDep,
    latitude: float = Query(default=21.1458, ge=-90.0, le=90.0, description="Latitude"),
    longitude: float = Query(default=79.0882, ge=-180.0, le=180.0, description="Longitude"),
    location_name: str = Query(default="Nagpur", description="Location name"),
) -> TrustResponse:
    """Evaluate trust and freshness for the active forecast provider."""
    location = Location(name=location_name, latitude=latitude, longitude=longitude)
    now = datetime.now(UTC)
    # Check 24 hours of data
    start = now
    end = now + timedelta(hours=24)

    series = await provider.get_forecast(location, start, end)
    quality = series.assess_quality(reference_time=now)

    return TrustResponse(
        location=location,
        source=quality.source,
        generated_at=quality.generated_at,
        freshness_seconds=quality.freshness_seconds,
        is_stale=quality.is_stale,
        has_station_observations=quality.has_station_observations,
        missing_intervals_count=quality.missing_intervals_count,
        confidence=quality.confidence,
        confidence_reason=quality.confidence_reason,
    )
