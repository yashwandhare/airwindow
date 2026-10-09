# AirWindow Core --- API Specification

Base URL: `http://localhost:8000`  
Interactive Swagger UI: `http://localhost:8000/docs`  
ReDoc: `http://localhost:8000/redoc`

---

## 1. System Endpoints

### `GET /health`
Returns service operational health and configuration metadata.

#### Response `200 OK`
```json
{
  "status": "healthy",
  "service": "airwindow-core",
  "version": "0.1.0",
  "environment": "development",
  "provider": "mock"
}
```

---

## 2. Planning Endpoints

### `POST /plan`
Evaluates candidate 15-minute start time slots within an available window to find the slot that minimizes estimated inhaled PM2.5 dose. Compares against a user-specified or default baseline slot.

#### Request Body
```json
{
  "location": {
    "name": "Nagpur",
    "latitude": 21.1458,
    "longitude": 79.0882
  },
  "activity": "running",
  "duration_min": 45,
  "window_start": "2026-10-10T17:00:00+05:30",
  "window_end": "2026-10-10T21:00:00+05:30",
  "usual_time": "2026-10-10T17:00:00+05:30",
  "max_temperature_c": 35.0,
  "step_min": 15
}
```

#### Key Fields:
- `activity` *(string, required)*: `resting`, `walking`, `cycling`, `running`, `sports`, `outdoor_work`.
- `duration_min` *(int, required)*: Continuous duration in minutes (5 to 360).
- `window_start` / `window_end` *(ISO 8601 string, required)*: Timezone-aware window bounds.
- `usual_time` *(ISO 8601 string, optional)*: User's habitual start time for baseline comparison.
- `max_temperature_c` *(float, optional)*: Maximum allowable temperature in °C.
- `step_min` *(int, optional, default: 15)*: Evaluation stepping granularity.

#### Response `200 OK`
```json
{
  "status": "ok",
  "best": {
    "start": "2026-10-10T17:00:00+05:30",
    "end": "2026-10-10T17:45:00+05:30",
    "duration_min": 45,
    "activity": "running",
    "dose_ug": 88.69,
    "reduction_pct": 0.0,
    "confidence": "high",
    "avg_pm25_ug_m3": 43.8,
    "avg_temperature_c": 33.1,
    "max_temperature_c": 33.1,
    "intervals": [
      {
        "start": "2026-10-10T17:00:00+05:30",
        "end": "2026-10-10T17:45:00+05:30",
        "duration_min": 45.0,
        "pm25_ug_m3": 43.8,
        "dose_ug": 88.695,
        "temperature_c": 33.1
      }
    ]
  },
  "baseline": {
    "start": "2026-10-10T17:00:00+05:30",
    "end": "2026-10-10T17:45:00+05:30",
    "duration_min": 45,
    "activity": "running",
    "dose_ug": 88.69,
    "is_valid": true,
    "warning": null
  },
  "candidates": [
    {
      "start": "2026-10-10T17:00:00+05:30",
      "end": "2026-10-10T17:45:00+05:30",
      "duration_min": 45,
      "dose_ug": 88.69,
      "avg_pm25_ug_m3": 43.8,
      "avg_temperature_c": 33.1,
      "max_temperature_c": 33.1,
      "is_valid": true,
      "reason_invalid": null
    }
  ],
  "series": [ ... ],
  "data_quality": {
    "source": "AirWindow Deterministic Mock Provider v1.0",
    "generated_at": "2026-10-10T06:00:00+05:30",
    "freshness_seconds": 39600,
    "is_stale": false,
    "has_station_observations": false,
    "missing_intervals_count": 0,
    "confidence": "high",
    "confidence_reason": "Fresh, uninterrupted deterministic hourly forecast data."
  },
  "warnings": [],
  "disclaimer": "Estimated inhaled PM2.5 dose is a mathematical model based on ambient forecast concentrations and standard physiological ventilation assumptions. It is NOT a direct measurement of personal exposure or internal biological uptake, and does NOT constitute medical advice."
}
```

---

## 3. What-If Comparison Endpoints

### `POST /whatif`
Compares a base activity plan against modified parameters (e.g., changing from running to walking, shortening duration, or shifting the availability window).

#### Request Body
```json
{
  "base_plan": {
    "location": {
      "name": "Nagpur",
      "latitude": 21.1458,
      "longitude": 79.0882
    },
    "activity": "running",
    "duration_min": 60,
    "window_start": "2026-10-10T17:00:00+05:30",
    "window_end": "2026-10-10T21:00:00+05:30"
  },
  "overrides": {
    "activity": "walking",
    "duration_min": 30
  }
}
```

#### Response `200 OK`
```json
{
  "status": "ok",
  "base_recommendation": {
    "start": "2026-10-10T17:00:00+05:30",
    "end": "2026-10-10T18:00:00+05:30",
    "duration_min": 60,
    "activity": "running",
    "dose_ug": 118.26,
    "reduction_pct": null,
    "confidence": "high",
    "avg_pm25_ug_m3": 43.8,
    "avg_temperature_c": 33.1,
    "max_temperature_c": 33.1,
    "intervals": []
  },
  "modified_recommendation": {
    "start": "2026-10-10T17:00:00+05:30",
    "end": "2026-10-10T17:30:00+05:30",
    "duration_min": 30,
    "activity": "walking",
    "dose_ug": 21.02,
    "reduction_pct": 82.2,
    "confidence": "high",
    "avg_pm25_ug_m3": 43.8,
    "avg_temperature_c": 33.1,
    "max_temperature_c": 33.1,
    "intervals": []
  },
  "dose_delta_ug": -97.24,
  "reduction_pct": 82.2,
  "summary_explanation": "Modified (walking, 30m) reduces estimated dose from 118.3 µg to 21.0 µg, saving 97.2 µg (82.2% reduction).",
  "warnings": [],
  "disclaimer": "Estimated inhaled PM2.5 dose is a mathematical model based on ambient forecast concentrations and standard physiological ventilation assumptions. It is NOT a direct measurement of personal exposure or internal biological uptake, and does NOT constitute medical advice."
}
```

---

## 4. Trust & Freshness Endpoints

### `GET /forecast/trust`
Inspects data quality, observation availability, staleness, and rule-based confidence for a location.

#### Query Parameters:
- `latitude` *(float, default: 21.1458)*
- `longitude` *(float, default: 79.0882)*
- `location_name` *(string, default: "Nagpur")*

#### Response `200 OK`
```json
{
  "location": {
    "name": "Nagpur",
    "latitude": 21.1458,
    "longitude": 79.0882
  },
  "source": "AirWindow Deterministic Mock Provider v1.0",
  "generated_at": "2026-10-10T06:00:00+05:30",
  "freshness_seconds": 120,
  "is_stale": false,
  "has_station_observations": false,
  "missing_intervals_count": 0,
  "confidence": "high",
  "confidence_reason": "Fresh, uninterrupted deterministic hourly forecast data.",
  "disclaimer": "Estimated inhaled PM2.5 dose is a mathematical model based on ambient forecast concentrations and standard physiological ventilation assumptions. It is NOT a direct measurement of personal exposure or internal biological uptake, and does NOT constitute medical advice."
}
```
