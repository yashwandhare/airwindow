# AirWindow Core --- Product Requirements Document

**Project:** AirWindow\
**Purpose:** Build the reliable, testable core of AirWindow so teammates
can add AWS services, the AI agent, the frontend, and additional
features without rewriting core logic.\
**Status:** Hackathon MVP\
**Owner scope:** Core engine, normalized data interface, FastAPI
contracts, tests, local demo setup.

## 1. Product summary

AirWindow helps people choose a lower-pollution time for an outdoor
activity they need to do. It uses hourly PM2.5 forecast data, an
activity and duration to estimate inhaled PM2.5 dose, then recommends
the lowest-dose feasible time slot within the user's available window.

The system must explain that its result is an estimate. It must not
present the estimate as a direct measurement of a person's actual
exposure or as medical advice.

## 2. Problem

Air-quality apps commonly show pollution levels, but users also need
help deciding when to do an outdoor activity. AirWindow turns forecast
data into a practical scheduling recommendation.

## 3. Goals

-   Implement an explainable PM2.5 inhaled-dose calculation.
-   Find the lowest-dose feasible activity window within user
    constraints.
-   Compare a recommended plan with a clearly defined baseline.
-   Provide stable FastAPI endpoints and documented request/response
    schemas.
-   Run end-to-end with deterministic mock data and no cloud
    credentials.
-   Keep core calculations independent of external APIs, AWS, and LLMs.
-   Make the code straightforward for teammates to extend.

## 4. Non-goals for this task

-   Implementing AWS infrastructure or deploying the application.
-   Implementing Bedrock or the Strands Agents SDK.
-   Training a forecast-correction ML model.
-   User authentication, accounts, notifications, or calendar
    integration.
-   A complete school/group planner.
-   Medical advice, diagnosis, or claims about individual health
    outcomes.
-   Guaranteeing that a forecast represents street-level pollution.

These can be added later without changing the core engine's public
interfaces.

## 5. Primary user flow

1.  User provides a location, activity, duration, and available time
    window.
2.  A forecast provider supplies normalized hourly PM2.5 and optional
    weather data.
3.  The exposure engine estimates dose for each candidate activity slot.
4.  The optimizer selects the lowest-dose feasible slot.
5.  The API returns the recommendation, candidate results, baseline
    comparison, and data-quality warnings.
6.  The user may change activity or duration and request a what-if
    comparison.

## 6. Scope and priorities

### Must have

-   Activity planner request schema.
-   Normalized forecast data model.
-   Deterministic mock forecast provider.
-   Exposure calculation across changing PM2.5 values.
-   Schedule optimizer with configurable slot step (default 15 minutes).
-   Explicit baseline and percentage-reduction calculation.
-   FastAPI `POST /plan` and `POST /whatif` endpoints.
-   Input validation and useful error responses.
-   Tests for calculations, optimization constraints, and API behavior.
-   README with setup, run, test, example requests, assumptions, and
    limitations.

### Should have

-   Optional temperature constraint when temperature data exists.
-   Forecast freshness and confidence metadata.
-   `GET /forecast/trust` endpoint.
-   A provider interface that can later be implemented using Open-Meteo,
    OpenAQ, S3, or another source.

### Not required for the first version

-   Live external API integration.
-   Database persistence.
-   AWS services.
-   Agent endpoint.
-   Group planner.
-   Frontend.

## 7. Functional requirements

### FR-1: Forecast data contract

The core engine must consume a normalized data structure independent of
where the data came from.

Each time-series record should include: - Timestamp with timezone. -
PM2.5 concentration in µg/m³. - Optional temperature in °C. - Optional
source and observation/forecast metadata.

Validate units and timestamps. Do not silently treat missing PM2.5
values as zero. If coverage is insufficient for a candidate window, mark
it invalid or return a clear insufficient-data response.

### FR-2: Exposure engine

Estimate inhaled PM2.5 dose using:

`Dose (µg) = Σ(PM2.5 concentration (µg/m³) × minute ventilation (m³/min) × duration (min))`

For changing concentrations, split the activity into time intervals and
sum the dose for each interval.

Requirements: - Keep activity breathing-rate assumptions in one
configurable, documented place. - Clearly identify these values as
estimates and document their sources before using them as evidence. - Do
not hard-code illustrative UI values as measured results. - Return dose
in µg and retain enough detail to explain the calculation. - Reject
unsupported activities or invalid inputs with useful errors.

### FR-3: Schedule optimizer

Inputs: - Location identifier/coordinates supplied by the caller. -
Activity. - Duration in minutes. - Available window start and end. -
Forecast series. - Optional constraints, such as maximum temperature.

Behavior: - Evaluate candidate start times using a configurable step,
defaulting to 15 minutes. - Ensure each activity fits completely inside
the available window. - Exclude candidates that violate explicit
constraints or have insufficient forecast coverage. - Select the valid
candidate with the lowest estimated dose. - Return candidate scores so
the frontend can display a chart. - If no valid candidate exists, return
a clear no-recommendation result rather than inventing one. - Use
deterministic tie-breaking.

### FR-4: Baseline and reduction

The API must define the baseline explicitly. Prefer a caller-supplied
`usual_time` or a documented default baseline slot within the available
window.

Calculate:

`reduction_pct = ((baseline_dose - recommended_dose) / baseline_dose) × 100`

Handle a zero or unavailable baseline safely. Do not claim a reduction
when no valid baseline can be calculated. Reductions may be negative if
the selected baseline is lower than the recommended candidate; do not
falsify results to force a positive percentage.

### FR-5: What-if comparison

Allow the caller to change supported fields such as activity, duration,
or time window. Recalculate the plan and return before/after estimated
dose and percentage difference. Do not mutate the original request or
rely on an in-memory plan ID unless persistence is deliberately added.

### FR-6: Data quality and confidence

Return data-quality metadata such as: - Data source. - Latest data
timestamp / data age where known. - Missing time intervals. - Whether
station observations are available. - Confidence level and a concise
reason.

Confidence must be rule-based and transparent in the first version. Do
not label confidence as a calibrated probability. If data is stale or
sparse, show a warning. If there is not enough data to recommend a slot,
return that status clearly.

### FR-7: API

Implement: - `GET /health` --- basic service health. - `POST /plan` ---
calculate a plan. - `POST /whatif` --- compare an updated plan with a
supplied baseline plan/input. - `GET /forecast/trust` --- return data
freshness and quality information if practical for the first version.

Use Pydantic schemas. Keep response fields stable and document them. The
API layer must call the core functions rather than duplicating
calculation logic.

## 8. Suggested API contracts

These are initial contracts and may be refined before implementation,
but document any changes.

### `POST /plan` request

``` json
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
  "usual_time": "2026-10-10T17:00:00+05:30"
}
```

### `POST /plan` response shape

``` json
{
  "status": "ok",
  "best": {
    "start": "2026-10-10T18:30:00+05:30",
    "end": "2026-10-10T19:15:00+05:30",
    "dose_ug": 240.0,
    "reduction_pct": 27.3,
    "confidence": "medium"
  },
  "baseline": {
    "start": "2026-10-10T17:00:00+05:30",
    "dose_ug": 330.0
  },
  "candidates": [],
  "series": [],
  "warnings": []
}
```

**All values above are illustrative examples, not real forecast
outputs.** The implementation must calculate all returned numbers. Use
timezone-aware timestamps and a documented convention for interval
boundaries.

### `POST /whatif`

Accept the original plan inputs plus the requested changes, or accept a
baseline request and a modified request. Return the two calculated
doses, absolute/percentage difference where valid, and warnings. Keep
the contract stateless for the MVP.

## 9. Technical design

Suggested stack: - Python 3.12 or a compatible installed Python
version. - FastAPI. - Pydantic. - Pytest. - Ruff for linting/formatting
if time allows.

Suggested layout:

``` text
airwindow/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── schemas.py
│   │   ├── routes_plan.py
│   │   ├── routes_whatif.py
│   │   └── routes_trust.py
│   ├── core/
│   │   ├── exposure.py
│   │   ├── optimizer.py
│   │   └── comparison.py
│   ├── data/
│   │   ├── providers.py
│   │   ├── mock_provider.py
│   │   └── normalization.py
│   └── config.py
├── tests/
├── data/
│   └── sample_forecast.json
├── docs/
│   ├── API.md
│   └── ARCHITECTURE.md
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

Keep pure calculations in `app/core/`. They must not import FastAPI, AWS
SDKs, external API clients, or LLM libraries. Keep provider
implementations behind a small interface. Use dependency injection or a
simple configuration setting to choose the mock provider now and a real
provider later.

## 10. Future integration points

Teammates should be able to add these without rewriting the core: -
Open-Meteo forecast provider. - OpenAQ observation/station provider. -
AWS S3 storage and ingestion. - EventBridge + Lambda scheduled data
ingestion. - Bedrock + Strands agent calling the core through explicit
tools. - Forecast-correction model. - Frontend and group planner.

Do not implement all these in the core task. The provider interface, API
schemas, and documented functions are the integration boundary.

## 11. Testing and acceptance criteria

The task is complete when:

1.  A fresh setup can install dependencies using the documented
    commands.
2.  The app starts locally without AWS credentials or network access.
3.  A sample `/plan` request returns a calculated recommendation using
    mock data.
4.  Dose calculation is correct for constant and changing
    concentrations.
5.  The optimizer never returns a slot outside the available window.
6.  The selected slot has the lowest dose among valid candidates.
7.  Duration and activity changes recalculate the result.
8.  Missing, stale, or insufficient data produces warnings or a
    no-result status, never a fabricated dose.
9.  Baseline reduction is calculated correctly, including
    zero/unavailable baselines.
10. Invalid input returns a useful validation error.
11. Automated tests pass.
12. README explains setup, run commands, endpoints, data assumptions,
    limitations, and how to add a provider.

## 12. Safety, accuracy, and limitations

-   This is a planning aid, not medical advice.
-   Estimated inhaled dose is not a direct measurement of personal
    exposure or absorbed dose.
-   Breathing rates vary by person, age, fitness, and activity; expose
    assumptions and cite sources.
-   Forecasts and fixed monitoring stations can miss local conditions.
-   Do not promise that a recommended time is safe. Describe it as the
    lowest estimated exposure among valid candidate windows.
-   Do not present mock data as live or measured data.

## 13. Implementation order

1.  Create project skeleton and environment setup.
2.  Define schemas and normalized forecast format.
3.  Implement pure exposure calculation with tests.
4.  Implement optimizer and baseline comparison with tests.
5.  Add deterministic mock forecast provider.
6.  Expose `/health`, `/plan`, and `/whatif`.
7.  Add data-quality metadata and `/forecast/trust` if time permits.
8.  Write API examples, architecture notes, and teammate integration
    instructions.
9.  Run all tests and verify a full local demo.

## 14. Handoff deliverables

-   Working repository.
-   Deterministic local demo.
-   Passing automated tests.
-   Documented API contracts.
-   Architecture and extension notes.
-   `.env.example` with no secrets.
-   Clear list of implemented features, limitations, and remaining
    tasks.
