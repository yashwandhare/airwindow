"""API integration tests using FastAPI TestClient."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

IST = timezone(timedelta(hours=5, minutes=30))


def test_health_check() -> None:
    """Verify /health returns 200 and healthy status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "airwindow-core"
    assert "version" in data


def test_post_plan_success() -> None:
    """Verify POST /plan calculates optimal slot, baseline, candidates, and metadata."""
    t_start = datetime(2026, 10, 10, 17, 0, tzinfo=IST)
    t_end = datetime(2026, 10, 10, 21, 0, tzinfo=IST)
    t_usual = datetime(2026, 10, 10, 17, 0, tzinfo=IST)

    payload = {
        "location": {
            "name": "Nagpur",
            "latitude": 21.1458,
            "longitude": 79.0882,
        },
        "activity": "running",
        "duration_min": 45,
        "window_start": t_start.isoformat(),
        "window_end": t_end.isoformat(),
        "usual_time": t_usual.isoformat(),
        "step_min": 15,
    }

    response = client.post("/plan", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "ok"
    assert data["best"] is not None
    assert data["best"]["duration_min"] == 45
    assert data["best"]["activity"] == "running"
    assert data["best"]["dose_ug"] > 0
    assert "reduction_pct" in data["best"]
    assert len(data["candidates"]) > 0
    assert data["baseline"]["dose_ug"] > 0
    assert data["data_quality"]["confidence"] in ("high", "medium", "low")
    assert "Estimated inhaled PM2.5 dose is a mathematical model" in data["disclaimer"]


def test_post_plan_invalid_window() -> None:
    """Verify window_end <= window_start returns 422 error."""
    t_start = datetime(2026, 10, 10, 18, 0, tzinfo=IST)
    t_end = datetime(2026, 10, 10, 17, 0, tzinfo=IST)  # Before start!

    payload = {
        "location": {"name": "Nagpur", "latitude": 21.1458, "longitude": 79.0882},
        "activity": "walking",
        "duration_min": 30,
        "window_start": t_start.isoformat(),
        "window_end": t_end.isoformat(),
    }

    response = client.post("/plan", json=payload)
    assert response.status_code == 422


def test_post_plan_unsupported_activity() -> None:
    """Verify unsupported activity returns 422 validation error."""
    t_start = datetime(2026, 10, 10, 17, 0, tzinfo=IST)
    t_end = datetime(2026, 10, 10, 20, 0, tzinfo=IST)

    payload = {
        "location": {"name": "Nagpur", "latitude": 21.1458, "longitude": 79.0882},
        "activity": "skydiving_not_supported",
        "duration_min": 30,
        "window_start": t_start.isoformat(),
        "window_end": t_end.isoformat(),
    }

    response = client.post("/plan", json=payload)
    assert response.status_code == 422
    assert "Unsupported activity" in response.text


def test_post_plan_duration_exceeds_window() -> None:
    """Verify duration longer than available window returns no_recommendation."""
    t_start = datetime(2026, 10, 10, 17, 0, tzinfo=IST)
    t_end = datetime(2026, 10, 10, 17, 30, tzinfo=IST)  # 30 min window

    payload = {
        "location": {"name": "Nagpur", "latitude": 21.1458, "longitude": 79.0882},
        "activity": "running",
        "duration_min": 60,  # 60 min duration
        "window_start": t_start.isoformat(),
        "window_end": t_end.isoformat(),
    }

    response = client.post("/plan", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "no_recommendation"
    assert data["best"] is None
    assert any("exceeds available window" in w for w in data["warnings"])


def test_post_whatif_with_overrides() -> None:
    """Verify POST /whatif calculates comparison using overrides."""
    t_start = datetime(2026, 10, 10, 17, 0, tzinfo=IST)
    t_end = datetime(2026, 10, 10, 21, 0, tzinfo=IST)

    base_plan = {
        "location": {"name": "Nagpur", "latitude": 21.1458, "longitude": 79.0882},
        "activity": "running",
        "duration_min": 60,
        "window_start": t_start.isoformat(),
        "window_end": t_end.isoformat(),
    }

    payload = {
        "base_plan": base_plan,
        "overrides": {
            "activity": "walking",
            "duration_min": 30,
        },
    }

    response = client.post("/whatif", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "ok"
    assert data["base_recommendation"] is not None
    assert data["modified_recommendation"] is not None
    assert data["base_recommendation"]["activity"] == "running"
    assert data["modified_recommendation"]["activity"] == "walking"
    assert data["dose_delta_ug"] < 0  # walking for 30m should inhale less than running for 60m
    assert data["reduction_pct"] > 0
    assert len(data["summary_explanation"]) > 0


def test_get_forecast_trust() -> None:
    """Verify GET /forecast/trust returns data freshness and confidence."""
    response = client.get("/forecast/trust?latitude=21.1458&longitude=79.0882&location_name=Nagpur")
    assert response.status_code == 200
    data = response.json()

    assert data["location"]["name"] == "Nagpur"
    assert "source" in data
    assert data["confidence"] in ("high", "medium", "low")
    assert "confidence_reason" in data
    assert data["is_stale"] is False
    assert "disclaimer" in data


def test_plan_future_window_not_stale() -> None:
    """Verify future planning window (e.g. +48h) is not falsely marked stale (P0-1 fix)."""
    now = datetime.now(IST)
    t_start = now + timedelta(days=2)
    t_end = t_start + timedelta(hours=4)

    payload = {
        "location": {"name": "Nagpur", "latitude": 21.1458, "longitude": 79.0882},
        "activity": "running",
        "duration_min": 30,
        "window_start": t_start.isoformat(),
        "window_end": t_end.isoformat(),
    }

    response = client.post("/plan", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["data_quality"]["is_stale"] is False
    assert not any("over 24 hours old" in w for w in data["warnings"])


def test_overrides_invalid_activity_returns_422() -> None:
    """Verify invalid activity in PlanOverrides returns 422, not 500 (P0-3 fix)."""
    t_start = datetime(2026, 10, 10, 17, 0, tzinfo=IST)
    t_end = datetime(2026, 10, 10, 21, 0, tzinfo=IST)

    payload = {
        "base_plan": {
            "location": {"name": "Nagpur", "latitude": 21.1458, "longitude": 79.0882},
            "activity": "running",
            "duration_min": 30,
            "window_start": t_start.isoformat(),
            "window_end": t_end.isoformat(),
        },
        "overrides": {
            "activity": "skydiving_not_supported",
        },
    }

    response = client.post("/whatif", json=payload)
    assert response.status_code == 422


def test_plan_window_cap_422() -> None:
    """Verify window exceeding 168 hours returns 422 (P0-5 fix)."""
    t_start = datetime(2026, 10, 10, 17, 0, tzinfo=IST)
    t_end = t_start + timedelta(days=8)  # 192 hours > 168h limit

    payload = {
        "location": {"name": "Nagpur", "latitude": 21.1458, "longitude": 79.0882},
        "activity": "running",
        "duration_min": 30,
        "window_start": t_start.isoformat(),
        "window_end": t_end.isoformat(),
    }

    response = client.post("/plan", json=payload)
    assert response.status_code == 422
    assert "exceeds the maximum allowed horizon" in response.text


def test_plan_payload_trim_flags() -> None:
    """Verify include_candidates=False and include_series=False trim response payload (P0-5 fix)."""
    t_start = datetime(2026, 10, 10, 17, 0, tzinfo=IST)
    t_end = datetime(2026, 10, 10, 20, 0, tzinfo=IST)

    payload = {
        "location": {"name": "Nagpur", "latitude": 21.1458, "longitude": 79.0882},
        "activity": "running",
        "duration_min": 30,
        "window_start": t_start.isoformat(),
        "window_end": t_end.isoformat(),
        "include_candidates": False,
        "include_series": False,
        "include_intervals": False,
    }

    response = client.post("/plan", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["candidates"] == []
    assert data["series"] == []
    assert data["best"]["intervals"] == []


def test_whatif_both_overrides_and_modified_plan_rejected_422() -> None:
    """Verify providing both modified_plan and overrides returns 422 (P2-3 fix)."""
    t_start = datetime(2026, 10, 10, 17, 0, tzinfo=IST)
    t_end = datetime(2026, 10, 10, 20, 0, tzinfo=IST)

    base = {
        "location": {"name": "Nagpur", "latitude": 21.1458, "longitude": 79.0882},
        "activity": "running",
        "duration_min": 30,
        "window_start": t_start.isoformat(),
        "window_end": t_end.isoformat(),
    }

    payload = {
        "base_plan": base,
        "modified_plan": base,
        "overrides": {"activity": "walking"},
    }

    response = client.post("/whatif", json=payload)
    assert response.status_code == 422
    assert "not both" in response.text
