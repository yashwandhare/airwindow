# AirWindow Core

**AirWindow** is a pollution-aware outdoor activity scheduling engine built for hackathons and production extensions. It combines atmospheric PM2.5 forecasts, physiological minute ventilation rates, and temporal constraints to find the lowest-dose feasible time slot for outdoor activities.

---

## Features

- **Pure Python Exposure Core**: Mathematical dose estimation ($\mu\text{g}$) with documented physiological ventilation assumptions ($\dot{V}_E$ in $\text{m}^3/\text{min}$). Zero dependencies on web frameworks, AWS, databases, or LLMs in core logic.
- **15-Minute Slot Optimizer**: Evaluates configurable candidate start steps (default: 15 min), strictly enforces window bounds, and handles optional temperature thresholds.
- **Explicit Baseline & What-If Engine**: Quantifies percentage reductions against user habit (`usual_time`) or default baseline, supporting interactive what-if scenarios.
- **Deterministic Mock Provider**: Reproducible, diurnal atmospheric cycle simulations requiring zero cloud credentials or network access.
- **Data Quality & Trust**: Rule-based confidence scoring, freshness monitoring, and strict rejection of missing data (never treated as zero).
- **FastAPI Delivery**: Fully typed Pydantic v2 schemas, interactive Swagger UI (`/docs`), and CORS-enabled endpoints.

---

## Project Structure

```text
airwindow/
├── app/
│   ├── main.py                  # FastAPI application entry point & CORS
│   ├── config.py                # Application configuration & defaults
│   ├── api/
│   │   ├── schemas.py           # Pydantic request & response contracts
│   │   ├── dependencies.py      # Provider dependency injection
│   │   ├── routes_plan.py       # POST /plan endpoint
│   │   ├── routes_whatif.py     # POST /whatif endpoint
│   │   └── routes_trust.py      # GET /forecast/trust endpoint
│   ├── core/
│   │   ├── exposure.py          # Pure Python PM2.5 inhaled dose model
│   │   ├── optimizer.py         # 15-min candidate schedule optimizer
│   │   └── comparison.py        # Baseline & what-if calculations
│   └── data/
│       ├── models.py            # Normalized forecast series models
│       ├── providers.py         # ForecastProvider interface
│       ├── mock_provider.py     # Deterministic diurnal mock provider
│       └── normalization.py     # Raw JSON (Open-Meteo) parser
├── tests/
│   ├── test_exposure.py         # Dose calculation & unit tests
│   ├── test_optimizer.py        # Window bounds, constraints, tie-breaking
│   ├── test_comparison.py       # Baseline reduction & what-if tests
│   ├── test_provider.py         # Determinism & data quality tests
│   └── test_api.py              # FastAPI endpoint integration tests
├── data/
│   └── sample_forecast.json     # Pre-generated 48h sample forecast
├── docs/
│   ├── API.md                   # Complete API reference & curl examples
│   └── ARCHITECTURE.md          # Architecture & extension guide
├── .env.example                 # Non-sensitive configuration template
├── .gitignore                   # Standard Python/venv ignores
├── pyproject.toml               # Package dependencies & tool configs
└── README.md
```

---

## Setup & Running Locally

### 1. Prerequisites
- Python 3.11+
- pip

### 2. Create Virtual Environment & Install Dependencies
```bash
# Clone and enter the repository
cd airwindow

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"
```

### 3. Start the API Server
```bash
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Once started, open:
- API Swagger UI: http://localhost:8000/docs
- Health check: http://localhost:8000/health

---

## Running Automated Tests

Run the full test suite with pytest:
```bash
source .venv/bin/activate
pytest -v
```

Linting and code formatting with Ruff:
```bash
ruff check app tests
ruff format app tests
```

---

## Inhaled Dose Model & Activity Assumptions

### Dose Formula
$$\text{Dose } (\mu\text{g}) = \sum_{i} \Big( C_i \,[\mu\text{g/m}^3] \times \dot{V}_E \,[\text{m}^3/\text{min}] \times \Delta t_i \,[\text{min}] \Big)$$

Units cancel cleanly:
$$(\mu\text{g/m}^3) \times (\text{m}^3/\text{min}) \times \text{min} = \mu\text{g}$$

### Documented Minute Ventilation Rates ($\dot{V}_E$)
Sources: *US EPA Exposure Factors Handbook (2011 Table 6-1)*; *Adams (1993)*; *Zuurbier et al. (2009)*:

| Activity | $\dot{V}_E$ ($\text{m}^3/\text{min}$) | $\dot{V}_E$ ($\text{L/min}$) | Intensity Level | Citation |
|---|---|---|---|---|
| `resting` | 0.007 | 7.0 | Sedentary / seated | US EPA (2011) Table 6-1 |
| `walking` | 0.016 | 16.0 | Light exercise (brisk walk) | US EPA (2011); Zuurbier et al. (2009) |
| `outdoor_work` | 0.025 | 25.0 | Moderate manual labor | US EPA (2011) |
| `cycling` | 0.035 | 35.0 | Moderate/vigorous commute | Zuurbier et al. (2009); Adams (1993) |
| `sports` | 0.042 | 42.0 | Vigorous active sports | US EPA (2011) |
| `running` | 0.045 | 45.0 | Vigorous jogging (8-10 km/h) | US EPA (2011); Adams (1993) |

*Disclaimer: Estimated inhaled dose is a mathematical model based on ambient forecast concentrations. It is NOT a direct measurement of personal exposure or internal biological uptake, and does NOT constitute medical advice.*

---

## API Examples (cURL)

### 1. Plan Activity (`POST /plan`)
Find the lowest-pollution 45-minute running window between 17:00 and 21:00:
```bash
curl -X POST http://localhost:8000/plan \
  -H "Content-Type: application/json" \
  -d '{
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
  }'
```

### 2. What-If Comparison (`POST /whatif`)
Compare a 60-minute run with a 30-minute walk:
```bash
curl -X POST http://localhost:8000/whatif \
  -H "Content-Type: application/json" \
  -d '{
    "base_plan": {
      "location": {"name": "Nagpur", "latitude": 21.1458, "longitude": 79.0882},
      "activity": "running",
      "duration_min": 60,
      "window_start": "2026-10-10T17:00:00+05:30",
      "window_end": "2026-10-10T21:00:00+05:30"
    },
    "overrides": {
      "activity": "walking",
      "duration_min": 30
    }
  }'
```

### 3. Forecast Trust & Quality (`GET /forecast/trust`)
```bash
curl "http://localhost:8000/forecast/trust?latitude=21.1458&longitude=79.0882&location_name=Nagpur"
```

---

## Instructions for Teammates Extending AirWindow

### 1. Adding Live Forecast Providers (Open-Meteo, OpenAQ, CPCB)
1. Subclass `ForecastProvider` in `app/data/`:
   ```python
   from app.data.providers import ForecastProvider
   from app.data.models import Location, NormalizedForecastSeries
   from app.data.normalization import normalize_open_meteo_response

   class OpenMeteoProvider(ForecastProvider):
       @property
       def name(self) -> str:
           return "Open-Meteo Provider"

       async def get_forecast(self, location: Location, start_time, end_time) -> NormalizedForecastSeries:
           # Call API, parse with normalize_open_meteo_response
           ...
   ```
2. In `app/api/dependencies.py`, register the provider in `get_forecast_provider()` based on `settings.forecast_provider`.

### 2. Adding AWS Integrations (S3, Lambda, EventBridge)
- **S3 Cache Provider**: Wrap your provider to check `s3://bucket/forecasts/...` before fetching from upstream APIs.
- **EventBridge + Lambda Ingestion**: Use a scheduled Lambda to populate S3 forecast files periodically.

### 3. Adding AI Agent Tools (Strands / Bedrock)
The pure Python core functions (`optimize_schedule`, `compare_scenarios`) take standard Python objects and return dataclasses. You can wrap them directly as agent tools:
```python
from app.core.optimizer import optimize_schedule
from app.data.mock_provider import MockForecastProvider

# Use directly inside your Bedrock Agent / Strands SDK tool registry
```

---

## Known Limitations & Non-Goals

1. **Micro-environments & Indoor Transfer**: Ambient forecasts reflect regional 2m atmospheric grid boxes, not indoor or micro-climate conditions.
2. **Deterministic Mock Data**: Offline demo uses an urban diurnal simulation model. For production deployments, activate the Open-Meteo or station provider.
3. **Biological Deposition**: Dose reflects mass inhaled, not pulmonary retention fraction or clinical diagnosis.
