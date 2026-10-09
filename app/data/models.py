"""Normalized forecast data models.

Provides standardized, source-agnostic data structures for PM2.5,
temperature, and meteorological forecast series.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field, field_validator, model_validator


class Location(BaseModel):
    """Geographic location specification."""

    name: str = Field(default="Nagpur", description="Human-readable location name")
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitude in decimal degrees")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitude in decimal degrees")


class NormalizedForecastPoint(BaseModel):
    """Normalized single-point atmospheric forecast or observation record.

    Timestamps represent the beginning of the hourly interval [timestamp, timestamp + 1hr).
    All timestamps MUST be timezone-aware.
    """

    timestamp: datetime = Field(..., description="Timezone-aware timestamp of the interval start")
    pm25_ug_m3: float | None = Field(
        default=None,
        ge=0.0,
        description="Fine particulate matter (PM2.5) concentration in µg/m³. None if missing/unavailable.",
    )
    temperature_c: float | None = Field(
        default=None,
        description="Ambient 2m air temperature in degrees Celsius.",
    )
    humidity_pct: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Relative humidity percentage (0-100).",
    )
    source: str | None = Field(
        default=None,
        description="Originating source name (e.g. CPCB, Open-Meteo, Mock).",
    )
    is_observed: bool = Field(
        default=False,
        description="True if ground-station observation, False if atmospheric forecast model.",
    )

    @field_validator("timestamp")
    @classmethod
    def ensure_timezone_aware(cls, v: datetime) -> datetime:
        """Validate that the timestamp is timezone-aware."""
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError(
                "Timestamp must be timezone-aware (e.g., '2026-10-10T17:00:00+05:30' or '2026-10-10T17:00:00Z')."
            )
        return v


class ForecastDataQuality(BaseModel):
    """Summary metadata regarding forecast freshness, completeness, and trust."""

    source: str = Field(..., description="Data provider or model source")
    generated_at: datetime = Field(..., description="Timestamp when the forecast was generated")
    freshness_seconds: int = Field(..., ge=0, description="Age of the forecast in seconds")
    is_stale: bool = Field(..., description="Whether the forecast is considered stale (> 24 hours)")
    has_station_observations: bool = Field(..., description="Whether station observations are included")
    missing_intervals_count: int = Field(default=0, description="Number of missing PM2.5 intervals")
    confidence: str = Field(
        ...,
        description="Rule-based confidence assessment: 'high', 'medium', or 'low'",
    )
    confidence_reason: str = Field(..., description="Explainable reason for confidence rating")


class NormalizedForecastSeries(BaseModel):
    """Normalized time-series of atmospheric forecasts for a given location."""

    location: Location
    generated_at: datetime = Field(..., description="Generation/fetch timestamp of this series")
    source: str = Field(..., description="Name of the forecast provider")
    points: list[NormalizedForecastPoint] = Field(
        default_factory=list,
        description="Chronologically sorted hourly forecast records",
    )

    @field_validator("generated_at")
    @classmethod
    def ensure_generated_at_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("generated_at must be timezone-aware.")
        return v

    def sort_points(self) -> None:
        """Sort points chronologically in-place."""
        self.points.sort(key=lambda p: p.timestamp)

    @model_validator(mode="after")
    def sort_and_validate_points(self) -> NormalizedForecastSeries:
        """Ensure points are sorted and reject duplicate timestamps."""
        self.points.sort(key=lambda p: p.timestamp)
        for i in range(len(self.points) - 1):
            if self.points[i].timestamp == self.points[i + 1].timestamp:
                raise ValueError(f"Duplicate forecast timestamp detected at {self.points[i].timestamp.isoformat()}.")
        return self

    def get_points_in_range(self, start: datetime, end: datetime) -> list[NormalizedForecastPoint]:
        """Return points whose intervals overlap with [start, end].

        Since points represent hourly intervals [p.timestamp, p.timestamp + 1hr):
        A point overlaps if p.timestamp < end and p.timestamp + 1hr > start.
        """
        overlapping: list[NormalizedForecastPoint] = []
        one_hour = timedelta(hours=1)
        for p in self.points:
            pt_end = p.timestamp + one_hour
            if p.timestamp < end and pt_end > start:
                overlapping.append(p)
        return overlapping

    def assess_quality(self, reference_time: datetime | None = None) -> ForecastDataQuality:
        """Evaluate data freshness and confidence."""
        ref = reference_time or datetime.now(UTC)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=UTC)

        # Calculate freshness
        gen_utc = self.generated_at.astimezone(UTC)
        ref_utc = ref.astimezone(UTC)
        freshness_sec = max(0, int((ref_utc - gen_utc).total_seconds()))
        is_stale = freshness_sec > (24 * 3600)  # stale if older than 24h

        has_observations = any(p.is_observed for p in self.points)
        missing_count = sum(1 for p in self.points if p.pm25_ug_m3 is None)
        total_count = len(self.points)

        # Rule-based transparent confidence evaluation
        if total_count == 0 or (total_count > 0 and missing_count / total_count > 0.4):
            confidence = "low"
            reason = f"High missing data rate ({missing_count}/{total_count} points missing PM2.5)."
        elif is_stale:
            confidence = "medium"
            reason = f"Forecast data is over 24 hours old ({freshness_sec // 3600} hours old)."
        elif missing_count > 0:
            confidence = "medium"
            reason = f"Minor data gaps detected ({missing_count} missing intervals)."
        elif has_observations:
            confidence = "high"
            reason = "Fresh forecast validated with local ground-station observations."
        else:
            confidence = "high"
            reason = "Fresh, uninterrupted deterministic hourly forecast data."

        return ForecastDataQuality(
            source=self.source,
            generated_at=self.generated_at,
            freshness_seconds=freshness_sec,
            is_stale=is_stale,
            has_station_observations=has_observations,
            missing_intervals_count=missing_count,
            confidence=confidence,
            confidence_reason=reason,
        )
