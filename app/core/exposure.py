"""Pure Python PM2.5 Inhaled Dose Exposure Engine.

Calculates estimated inhaled PM2.5 particulate mass (µg) for outdoor activities.
Independent of web frameworks, AWS SDKs, external APIs, and LLMs.

Units:
- PM2.5 concentration: µg/m³
- Minute ventilation rate (VE): m³/min (1 m³/min = 1,000 L/min)
- Duration: minutes
- Inhaled Dose: µg (micrograms) = Σ (Concentration × VE × Duration)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.data.models import NormalizedForecastSeries


@dataclass(frozen=True)
class ActivityProfile:
    """Documented minute ventilation rate assumptions and literature citations."""

    name: str
    ventilation_rate_m3_min: float  # m³/min
    ventilation_rate_l_min: float  # L/min for human readability
    intensity_description: str
    citation: str


# Literature-grounded default adult inhalation rates
# Sources:
# 1. US EPA Exposure Factors Handbook (2011 Edition, Chapter 6: Inhalation Rates)
# 2. Adams (1993) "Measurement of breathing rate and volume in routinely performed daily activities", CARB
# 3. Zuurbier et al. (2009) "Minute ventilation of cyclists, car and bus passengers, and pedestrians", Environ Health
ACTIVITY_PROFILES: dict[str, ActivityProfile] = {
    "resting": ActivityProfile(
        name="resting",
        ventilation_rate_m3_min=0.007,
        ventilation_rate_l_min=7.0,
        intensity_description="Sedentary / resting seated (VE ~6-8 L/min)",
        citation="US EPA Exposure Factors Handbook (2011), Table 6-1",
    ),
    "walking": ActivityProfile(
        name="walking",
        ventilation_rate_m3_min=0.016,
        ventilation_rate_l_min=16.0,
        intensity_description="Light activity: brisk walking 4-5 km/h (VE ~14-18 L/min)",
        citation="US EPA (2011) Table 6-1; Zuurbier et al. (2009)",
    ),
    "cycling": ActivityProfile(
        name="cycling",
        ventilation_rate_m3_min=0.035,
        ventilation_rate_l_min=35.0,
        intensity_description="Moderate-to-vigorous activity: commuter/fitness cycling (VE ~30-40 L/min)",
        citation="Zuurbier et al. (2009); Adams (1993)",
    ),
    "running": ActivityProfile(
        name="running",
        ventilation_rate_m3_min=0.045,
        ventilation_rate_l_min=45.0,
        intensity_description="Vigorous activity: running/jogging 8-10 km/h (VE ~40-55 L/min)",
        citation="US EPA (2011) Table 6-1; Adams (1993)",
    ),
    "sports": ActivityProfile(
        name="sports",
        ventilation_rate_m3_min=0.042,
        ventilation_rate_l_min=42.0,
        intensity_description="Vigorous activity: soccer, basketball, tennis (VE ~40-50 L/min)",
        citation="US EPA (2011) Table 6-1",
    ),
    "outdoor_work": ActivityProfile(
        name="outdoor_work",
        ventilation_rate_m3_min=0.025,
        ventilation_rate_l_min=25.0,
        intensity_description="Moderate manual labor / gardening (VE ~22-28 L/min)",
        citation="US EPA (2011) Table 6-1",
    ),
}

EXPOSURE_DISCLAIMER: str = (
    "Estimated inhaled PM2.5 dose is a mathematical model based on ambient forecast "
    "concentrations and standard physiological ventilation assumptions. It is NOT a direct "
    "measurement of personal exposure or internal biological uptake, and does NOT constitute "
    "medical advice."
)


class ExposureCalculationError(Exception):
    """Raised when exposure cannot be calculated due to missing data or invalid parameters."""

    pass


@dataclass
class IntervalDetail:
    """Breakdown of calculated exposure for a single sub-interval."""

    start: datetime
    end: datetime
    duration_min: float
    pm25_ug_m3: float
    ventilation_rate_m3_min: float
    dose_ug: float
    temperature_c: float | None = None


@dataclass
class SlotExposureResult:
    """Comprehensive calculated exposure result for an activity slot."""

    start: datetime
    end: datetime
    duration_min: int
    activity: str
    ventilation_rate_m3_min: float
    total_dose_ug: float
    avg_pm25_ug_m3: float
    avg_temperature_c: float | None
    max_temperature_c: float | None
    intervals: list[IntervalDetail]
    disclaimer: str = EXPOSURE_DISCLAIMER


def get_activity_ventilation_rate(
    activity: str,
    custom_rate_m3_min: float | None = None,
) -> tuple[float, str]:
    """Retrieve ventilation rate for an activity or validate custom rate.

    Returns:
        tuple of (ventilation_rate_m3_min, source_citation)
    """
    if custom_rate_m3_min is not None:
        if custom_rate_m3_min <= 0.0 or custom_rate_m3_min > 0.200:
            raise ValueError(
                f"Custom ventilation rate {custom_rate_m3_min} m³/min is outside plausible physiological "
                f"range (0.001 - 0.200 m³/min)."
            )
        return custom_rate_m3_min, "Caller-specified custom ventilation rate"

    key = activity.strip().lower()
    if key not in ACTIVITY_PROFILES:
        supported = ", ".join(sorted(ACTIVITY_PROFILES.keys()))
        raise ValueError(
            f"Unsupported activity '{activity}'. Supported activities are: {supported}. "
            f"Or provide a custom_ventilation_rate_m3_min."
        )

    profile = ACTIVITY_PROFILES[key]
    return profile.ventilation_rate_m3_min, profile.citation


def calculate_slot_exposure(
    start_time: datetime,
    duration_min: int,
    activity: str,
    forecast_series: NormalizedForecastSeries,
    custom_rate_m3_min: float | None = None,
) -> SlotExposureResult:
    """Calculate the estimated inhaled PM2.5 dose across one candidate time slot.

    Formula:
        Dose (µg) = Σ (PM2.5 [µg/m³] × VE [m³/min] × duration [min])

    Handles time-varying concentrations by intersecting the activity window with
    each hourly forecast interval [T, T + 1 hour).

    Raises:
        ValueError: If timestamps are not timezone-aware or duration is invalid.
        ExposureCalculationError: If forecast data is missing, discontinuous, or insufficient.
    """
    if start_time.tzinfo is None:
        raise ValueError("start_time must be timezone-aware.")
    if duration_min <= 0:
        raise ValueError(f"duration_min must be positive, got {duration_min}.")

    end_time = start_time + timedelta(minutes=duration_min)
    ve_rate, _ = get_activity_ventilation_rate(activity, custom_rate_m3_min)

    # Find overlapping forecast points
    points = forecast_series.get_points_in_range(start_time, end_time)
    if not points:
        raise ExposureCalculationError(
            f"No forecast data available for the slot {start_time.isoformat()} to {end_time.isoformat()}."
        )

    intervals: list[IntervalDetail] = []
    total_dose_ug = 0.0
    weighted_pm25_sum = 0.0
    covered_minutes = 0.0

    temp_values: list[float] = []
    temp_weighted_sum = 0.0
    temp_covered_minutes = 0.0
    one_hour = timedelta(hours=1)

    # Sort points chronologically
    sorted_points = sorted(points, key=lambda p: p.timestamp)

    for p in sorted_points:
        pt_start = p.timestamp
        pt_end = pt_start + one_hour

        # Find overlap between [start_time, end_time] and [pt_start, pt_end]
        overlap_start = max(start_time, pt_start)
        overlap_end = min(end_time, pt_end)

        if overlap_end > overlap_start:
            sub_min = (overlap_end - overlap_start).total_seconds() / 60.0

            # Strict rule: missing PM2.5 data cannot be treated as zero!
            if p.pm25_ug_m3 is None:
                raise ExposureCalculationError(
                    f"Forecast interval [{pt_start.isoformat()}, {pt_end.isoformat()}) has missing PM2.5 data. "
                    f"Cannot estimate dose without complete data."
                )

            sub_dose = p.pm25_ug_m3 * ve_rate * sub_min
            total_dose_ug += sub_dose
            weighted_pm25_sum += p.pm25_ug_m3 * sub_min
            covered_minutes += sub_min

            if p.temperature_c is not None:
                temp_values.append(p.temperature_c)
                temp_weighted_sum += p.temperature_c * sub_min
                temp_covered_minutes += sub_min

            intervals.append(
                IntervalDetail(
                    start=overlap_start,
                    end=overlap_end,
                    duration_min=round(sub_min, 2),
                    pm25_ug_m3=p.pm25_ug_m3,
                    ventilation_rate_m3_min=ve_rate,
                    dose_ug=round(sub_dose, 3),
                    temperature_c=p.temperature_c,
                )
            )

    # Verify complete temporal coverage of the requested duration
    if abs(covered_minutes - duration_min) > 0.01:
        raise ExposureCalculationError(
            f"Incomplete forecast coverage: covered {covered_minutes:.1f} min of requested {duration_min} min "
            f"for window [{start_time.isoformat()} - {end_time.isoformat()}]."
        )

    avg_pm25 = weighted_pm25_sum / duration_min
    avg_temp = (temp_weighted_sum / temp_covered_minutes) if temp_covered_minutes > 0 else None
    max_temp = max(temp_values) if temp_values else None

    return SlotExposureResult(
        start=start_time,
        end=end_time,
        duration_min=duration_min,
        activity=activity,
        ventilation_rate_m3_min=ve_rate,
        total_dose_ug=round(total_dose_ug, 2),
        avg_pm25_ug_m3=round(avg_pm25, 2),
        avg_temperature_c=round(avg_temp, 1) if avg_temp is not None else None,
        max_temperature_c=round(max_temp, 1) if max_temp is not None else None,
        intervals=intervals,
    )
