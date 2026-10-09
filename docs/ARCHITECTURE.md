# AirWindow Core --- Architecture & Extension Guide

AirWindow is an air pollution-aware outdoor activity scheduling engine. It ingests atmospheric PM2.5 and meteorological forecast series, calculates physiologically-grounded inhaled particulate dose ($\mu\text{g}$) for user activities, and identifies the lowest-exposure feasible time slot within a user's specified availability window.

---

## 1. Architectural Philosophy & Layer Separation

```
┌────────────────────────────────────────────────────────┐
│                   FastAPI HTTP Layer                   │
│   (app/api: routes_plan, routes_whatif, routes_trust)  │
└───────────────────────────┬────────────────────────────┘
                            │ Calls pure functions & depends on provider
┌───────────────────────────▼────────────────────────────┐
│                  Pure Python Core                      │
│        (app/core: exposure, optimizer, comparison)     │
│   * Zero external API / AWS / LLM / Web dependencies   │
│   * Pure mathematical & temporal calculations          │
└───────────────────────────▲────────────────────────────┘
                            │ Consumes normalized models
┌───────────────────────────┴────────────────────────────┐
│               Normalized Data Layer                    │
│   (app/data: models, providers, mock_provider, norm)   │
│   * ForecastProvider protocol/interface                │
│   * Deterministic mock generator for offline dev       │
└────────────────────────────────────────────────────────┘
```

### Module Boundaries
1. **`app/core/` (Pure Calculation Engine)**:
   - Contains `exposure.py`, `optimizer.py`, and `comparison.py`.
   - **Guarantees**: Must never import FastAPI, AWS SDKs (boto3), requests/httpx, databases, or LLM libraries.
   - Operates entirely on standard Python datatypes and `app.data.models.NormalizedForecastSeries`.
2. **`app/data/` (Data & Provider Abstraction)**:
   - Defines `NormalizedForecastSeries` and `NormalizedForecastPoint`.
   - Defines the `ForecastProvider` abstract base class.
   - Provides `MockForecastProvider` for deterministic, credential-free local development.
   - Provides `normalization.py` for transforming third-party APIs (e.g. Open-Meteo) into normalized models.
3. **`app/api/` (API Delivery & Contracts)**:
   - Contains FastAPI routers, Pydantic request/response schemas, and dependency injection (`dependencies.py`).
   - Delegates all business logic to `app/core/`.

---

## 2. Inhaled Dose Exposure Mathematical Model

Ambient air quality indexes (AQI) indicate concentration, but actual human particulate intake depends on **minute ventilation** (breathing rate $\dot{V}_E$) and **activity duration**:

$$\text{Dose } (\mu\text{g}) = \sum_{i} \Big( C_i \,[\mu\text{g/m}^3] \times \dot{V}_E \,[\text{m}^3/\text{min}] \times \Delta t_i \,[\text{min}] \Big)$$

Where:
- $C_i$: Time-varying PM2.5 concentration in $\mu\text{g/m}^3$ during sub-interval $i$.
- $\dot{V}_E$: Minute ventilation rate in $\text{m}^3/\text{min}$ (where $1\text{ m}^3 = 1{,}000\text{ L}$).
- $\Delta t_i$: Duration in minutes spent in that atmospheric interval.

### Standard Physiological Assumptions
Minute ventilation rates are documented in [`app/core/exposure.py`](file:///home/kazuto/dev/airwindow/app/core/exposure.py) based on peer-reviewed literature (US EPA Exposure Factors Handbook 2011 Table 6-1; Adams 1993; Zuurbier et al. 2009):
- **`resting`**: $0.007\text{ m}^3/\text{min}$ ($7.0\text{ L/min}$) --- Sedentary / passive seated.
- **`walking`**: $0.016\text{ m}^3/\text{min}$ ($16.0\text{ L/min}$) --- Light exercise, brisk walk.
- **`outdoor_work`**: $0.025\text{ m}^3/\text{min}$ ($25.0\text{ L/min}$) --- Moderate manual labor / gardening.
- **`cycling`**: $0.035\text{ m}^3/\text{min}$ ($35.0\text{ L/min}$) --- Moderate commuter/fitness cycling.
- **`sports`**: $0.042\text{ m}^3/\text{min}$ ($42.0\text{ L/min}$) --- Vigorous active sports (soccer, tennis).
- **`running`**: $0.045\text{ m}^3/\text{min}$ ($45.0\text{ L/min}$) --- Vigorous jogging/running ($8\text{--}10\text{ km/h}$).

*Note: Inhaled dose is an estimated intake model and does not represent internal biological deposition fraction or clinical diagnosis.*

---

## 3. How Teammates Can Extend the System

### A. Adding a Real Forecast Provider (e.g. Open-Meteo or OpenAQ)
To connect a live atmospheric API, teammates do not touch `app/core/`:
1. Subclass `ForecastProvider` in `app/data/`:
   ```python
   from app.data.providers import ForecastProvider
   from app.data.models import Location, NormalizedForecastSeries
   from app.data.normalization import normalize_open_meteo_response
   import httpx

   class OpenMeteoProvider(ForecastProvider):
       @property
       def name(self) -> str:
           return "Open-Meteo Air Quality API"

       async def get_forecast(self, location: Location, start_time, end_time) -> NormalizedForecastSeries:
           url = (
               f"https://air-quality-api.open-meteo.com/v1/air-quality?"
               f"latitude={location.latitude}&longitude={location.longitude}&hourly=pm2_5"
           )
           async with httpx.AsyncClient() as client:
               resp = await client.get(url)
               raw_json = resp.json()
           return normalize_open_meteo_response(raw_json, location)
   ```
2. Register the provider in `app/api/dependencies.py` based on `settings.forecast_provider`.

### B. Adding AWS Integrations (S3 Caching & Scheduled Lambda)
1. **S3 Forecast Cache**:
   - Create an `S3CachedForecastProvider` that checks `s3://airwindow-forecast-cache/{lat}_{lon}_{date}.json`.
   - If present and fresh, deserialize into `NormalizedForecastSeries`.
   - If missing or stale, fetch from upstream, write to S3, and return.
2. **Lambda / EventBridge Ingestion**:
   - An AWS EventBridge hourly trigger invokes a Lambda that polls city coordinates and persists normalized JSON/Parquet snapshots into S3.

### C. Integrating with Bedrock & Strands Agents SDK
The core functions are pure and self-contained, making them ideal agent tools:
1. Define a tool function wrapping `optimize_schedule`:
   ```python
   from strands import tool  # or LangChain / Bedrock agent tool decorator
   from app.core.optimizer import optimize_schedule
   from app.api.dependencies import get_forecast_provider

   @tool
   async def plan_outdoor_activity(
       city: str,
       latitude: float,
       longitude: float,
       activity: str,
       duration_minutes: int,
       window_start_iso: str,
       window_end_iso: str,
   ) -> dict:
       """Use AirWindow to find the lowest-pollution time window for an outdoor activity."""
       # Call core engine and return JSON summary for the LLM to explain to the user.
   ```
2. The agent can use this tool to answer natural language prompts such as:
   *"When should I go for my 45-minute run this evening in Nagpur to avoid heavy smog?"*
