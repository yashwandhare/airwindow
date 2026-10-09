# AirWindow Core — Independent Code Consultancy Report

**Date:** 2026-10-09 (UTC)
**Scope:** Read-only review of `main` branch (`1aa6781`), plus one output file (this report).
**Method:** Full static read of `app/`, `tests/`, `docs/`, `data/`, `pyproject.toml`, `.env.example`; live verification with the project's own `.venv` (pytest 29/29 passing, `ruff check`, targeted `python -c` reproductions). No source files were modified.
**Verdict:** Strong hackathon MVP — clean layer separation, correct core dose math, honest handling of missing data. **Not production-ready** without fixing 6 correctness/trust issues listed as P0 below. All claims are reproducible with commands in §9.

---

## 1. Executive summary

| Area | Rating | One-line note |
|---|---|---|
| Core dose math (`app/core/exposure.py`) | ✅ Good | Formula correct, missing-data-never-zero enforced, well tested |
| Optimizer (`app/core/optimizer.py`) | ⚠️ Fix needed | Window-fit + tie-break correct, but temp warnings spam, `ValueError` escapes, temp avg unweighted |
| Baseline / what-if (`app/core/comparison.py`, `routes_whatif.py`) | ⚠️ Fix needed | Reduction math correct (incl. negative/zero), but failure-path `end` bug + hard-coded `confidence="high"` in what-if |
| Data layer (`app/data/`) | ⚠️ Fix needed | Good interface + deterministic mock, but `missing_hours` ambiguous, over-generation, hourly assumption undocumented |
| API (`app/api/`, `app/main.py`) | ❌ Needs work | Works for demo, but freshness bug makes future windows look stale, overrides unvalidated (500 risk), CORS invalid, no DoS cap |
| Config / ops | ❌ Needs work | Dead `MIN/MAX_DURATION`, silent mock fallback, no CI/Docker, no logging/rate-limit |
| Tests / docs | ✅ Good for MVP | 29/29 pass, good README/PRD/API/ARCHITECTURE, but `ruff format` dirty, transitive `anyio` dep, sample-data drift |

**If you fix only 6 things, fix these (P0):**

1. `/plan` freshness uses `window_start` as reference → future windows falsely reported stale (§4.1).
2. `/whatif` hard-codes `confidence="high"` and drops `intervals` (§4.2).
3. `PlanOverrides` has no activity/timezone validation → 500 instead of 422 (§4.3).
4. `optimize_schedule` lets `ValueError` (bad activity/rate) escape → 500 (§4.4).
5. Unbounded window → 2 014 candidates for a 7-day `step_min=5` request, no cap/pagination (§4.5).
6. CORS `allow_origins=["*"]` + `allow_credentials=True` is rejected by browsers (§4.6).

---

## 2. What is done well (keep it)

- **Pure-core guarantee is real.** `app/core/` imports only `datetime`, `dataclasses`, and `app.data.models` — verified by read. This is exactly what PRD §9 demands and makes Strands/Bedrock wrapping trivial.
- **Dose formula is correct and tested.** `Dose = Σ(C × VE × Δt)` with hourly-interval intersection (`app/core/exposure.py:200-236`). `test_constant_pm25_exposure` (90.0 µg) and `test_changing_pm25_across_hour_boundaries` (148.5 µg) match hand calculation.
- **Missing data is never zeroed.** `ExposureCalculationError` on `None` PM2.5 (`exposure.py:212-216`) + optimizer marks candidate invalid (`optimizer.py:166-180`). Covered by `test_missing_pm25_never_treated_as_zero` and `test_optimizer_handles_missing_pm25_candidate`.
- **Deterministic tie-break (earliest start)** (`optimizer.py:200-203`) + test. Good for demo reproducibility.
- **Baseline honesty.** Zero-division safe, negative reductions preserved, not clamped (`comparison.py:81-91, 152-158`). Tests cover positive/zero/negative/missing.
- **Docs are above hackathon average.** README setup/run/test/curl, `docs/API.md` with real response shapes, `docs/ARCHITECTURE.md` with provider/AWS/agent extension recipes, `.env.example` with no secrets, PRD acceptance criteria largely met.

---

## 3. Bug catalogue (verified)

Severity: **P0 = wrong answer / 500 / security / DoS. P1 = wrong metadata / silent misconfig / data corruption risk. P2 = hygiene.**

### P0-1 — `/plan` freshness reference is wrong → false “stale” warnings
**File:** `app/api/routes_plan.py:50`

```python
data_quality = forecast_series.assess_quality(reference_time=request.window_start)
```

`assess_quality` computes `freshness = ref - generated_at` (`app/data/models.py:125-129`). For a **future** planning window (the normal case) with a fresh provider (`generated_at=now`), `ref=window_start` inflates age by the horizon:

Reproduction (project `.venv`, read-only):

```python
# gen=now, window 2 days in future
# ref=window_start → 172800s, is_stale=True   (what /plan does)
# ref=now         →      0s, is_stale=False  (correct)
```

The trust endpoint does it correctly (`routes_trust.py:39` uses `now`). `/plan` should too. Impact: every future plan carries a bogus “over 24 hours old” warning (`routes_plan.py:133-136`), eroding trust in the `confidence` field.

**Fix:** `assess_quality(reference_time=datetime.now(UTC))` in `/plan`; optionally also return `window_coverage` separately from `freshness`.

### P0-2 — `/whatif` hard-codes `confidence="high"`, drops intervals
**File:** `app/api/routes_whatif.py:121-149`

Both `base_resp` and `mod_resp` set `confidence="high"` unconditionally and `intervals=[]`, while `/plan` computes real `assess_quality(...).confidence` and full interval breakdown. A what-if over stale/gappy data therefore claims “high” confidence with no evidence.

**Fix:** call `base_series.assess_quality()` / `modified_series.assess_quality()` and propagate; include intervals (or explicitly document omission + add `include_intervals` flag to bound payload).

### P0-3 — `PlanOverrides` skips all validation → 500s
**File:** `app/api/schemas.py:165-175`

`PlanRequest.activity` has a validator (`schemas.py:63-73`), `PlanRequest` datetimes have tz validators (`75-82`). `PlanOverrides` has **neither**:

```python
class PlanOverrides(BaseModel):
    activity: str | None = None   # no validator
    window_start: datetime | None = None  # no tz validator
```

Verified:

```python
PlanOverrides(activity='skydiving_not_supported')  # PASSES schema (should 422)
PlanOverrides(window_start=datetime(2026,10,10,17,0))  # naive PASSES (should 422)
```

Invalid overrides then crash inside `optimize_schedule` as unhandled `ValueError` → FastAPI 500 + stack trace, instead of 422.

**Fix:** factor shared `validate_activity_name` / `validate_tz_aware` helpers and apply to both models.

### P0-4 — `optimize_schedule` does not handle `ValueError` → 500 on bad activity/rate
**File:** `app/core/optimizer.py:109-116,166-180`

The `try` catches only `ExposureCalculationError`. `calculate_slot_exposure` raises `ValueError` for unsupported activity (`exposure.py:143-149`), bad custom rate (`136-140`), or naive timestamps (`174-175`). First candidate then bubbles out of the loop:

```python
optimize_schedule(t17, t19, 60, 'skydiving', series)
# ValueError: Unsupported activity 'skydiving' ... (verified)
```

API is shielded for `base_plan` (Pydantic), but not for overrides (P0-3), and direct library/agent use crashes instead of returning `no_recommendation`.

**Fix:** validate `activity`/`custom_rate_m3_min` once up front (fail fast with `ValueError`), or catch `ValueError` per-candidate and mark invalid. Pick one and document.

### P0-5 — No window-size / candidate / payload cap → DoS + huge responses
**Files:** `app/api/schemas.py:28-55`, `app/core/optimizer.py:101-182`, `app/api/routes_plan.py:76-89,143-146`

No max on `window_end - window_start`. Verified with the shipped mock:

```python
POST /plan  7-day window, step_min=5 → 200 candidates? No: 2014 candidates, 200 OK in 0.08s
```

`candidates` + `series` are returned unbounded. A year-long window at `step_min=5` is ~105k loop iterations with per-slot exposure objects — CPU + multi-MB JSON. No pagination, no `include_candidates`/`include_series` flags, no `MAX_WINDOW_HOURS`.

**Fix (MVP-safe):** add `MAX_WINDOW_HOURS` (e.g. 168) + `MAX_CANDIDATES` (e.g. 500) validation in schema or route (422 with clear message); add `include_candidates: bool = True`, `include_series: bool = True`, `include_intervals: bool = True` query/body flags. Document limits in `docs/API.md`.

### P0-6 — CORS wildcard + credentials is invalid
**File:** `app/main.py:29-35`

```python
allow_origins=["*"], allow_credentials=True
```

Browsers reject `Access-Control-Allow-Origin: *` when `credentials: include`. Starlette does not stop you configuring it, but frontend teammates will see opaque CORS failures. Either enumerate dev origins or set `allow_credentials=False` for the wildcard demo.

---

### P1-1 — Baseline failure path returns zero-length `end`
**File:** `app/core/comparison.py:104-114` — verified:

```python
evaluate_baseline(...)  # missing PM2.5
# start == end == 17:00, duration_min=30 → contradictory
```

Success path uses `baseline_exp.end` (`93-95`); failure path uses `end=baseline_start`. Consumers validating `end == start + duration` will break; `BaselineResponse` will show a 30-min activity with identical start/end.

**Fix:** `end = baseline_start + timedelta(minutes=duration_min)` on the error path (import `timedelta`).

### P1-2 — Temperature average is unweighted, PM2.5 is weighted (inconsistent)
**File:** `app/core/exposure.py:223-224,245-247` — verified:

```python
# 45 min @30°C + 15 min @20°C → got 25.0°C (mean of points), want 27.5°C (time-weighted)
# avg_pm25 is correctly time-weighted (weighted_pm25_sum / duration_min)
```

`temp_values.append(p.temperature_c)` once per overlapping hour regardless of overlap minutes. `max_temperature_c` has the same edge (1-min tail dictates max) — defensible for a constraint, but average must be weighted.

**Fix:** accumulate `temp_weighted_sum += temp * sub_min`, divide by covered minutes with temp present; note weighting in docstring.

### P1-3 — Temperature-missing warning spams once per candidate
**File:** `app/core/optimizer.py:130-133` — verified: 5 candidates → 5 identical warnings.

```python
warnings.append(f"Temperature constraint ... unavailable for slot {current_start...}")
```

**Fix:** emit once (boolean flag) or aggregate: `"Temperature constraint requested but unavailable for N/M slots; constraint skipped."`

### P1-4 — `MockForecastProvider` over-generates + `missing_hours` is ambiguous
**File:** `app/data/mock_provider.py:84-92,96`

- Window `[17:00, 21:00]` yields **6 points** (`17…22:00`), verified. `limit = floor(end)+1h` + `while current <= limit` always adds one trailing hour. Harmless for correctness (extra point never overlaps), but wastes bandwidth in `series` and confuses “coverage” reasoning. Use `while current < limit` and unit-test exact count.
- `if hour_index in missing_hours or current.hour in missing_hours` conflates *offset index* with *wall-clock hour*. Verified: `missing_hours={0}` blanks `17:00` (index 0) and would also blank every midnight. The existing test passes only because start `08:00` + `{10,11}` aligns both meanings. Split into `missing_indices` vs `missing_wall_hours`, or document + rename + test a non-aligned start (e.g. start 17:00, `missing_hours={10}` must blank 10:00 next day, not index 10).

### P1-5 — `avg_pm25 or 0.0` masks missing data as clean air
**Files:** `app/api/routes_plan.py:113`, `app/api/routes_whatif.py:129,145`

```python
avg_pm25_ug_m3=opt_result.best.avg_pm25_ug_m3 or 0.0
```

Valid candidates always have a float, so the fallback is dead code — except it converts a future `None` bug into `0.0` (clean air). Use explicit `if x is None: raise/log` instead of `or`.

### P1-6 — Silent fallback to mock on misconfigured provider
**File:** `app/api/dependencies.py:20-29`, `.env.example:12`

```python
if settings.forecast_provider == "mock": ... else: # Fallback to mock
```

Any typo (`MOCK`, `open-meteo`, `file`) silently runs mock data with no warning. `.env.example` advertises `"file"` which does not exist. Fail fast (`raise RuntimeError`) for unknown values; log provider selection at startup.

### P1-7 — Dead config + crash-prone parsing
**File:** `app/config.py:13-23`

`MIN_DURATION_MINUTES` / `MAX_DURATION_MINUTES` / `DEFAULT_STEP_MINUTES` are read but **never used** — schemas hard-code `ge=5, le=360` / `default=15`. `int(os.getenv(...))` raises bare `ValueError` at import on bad env. No `FORECAST_PROVIDER` allowlist, no `MAX_WINDOW_HOURS`.

**Fix:** use `pydantic-settings` (already on Pydantic v2) or a tiny validated `Settings` with `@property` checks; wire `settings.*` into schema defaults/validators or delete the dead keys.

### P1-8 — `NormalizedForecastSeries` assumes hourly cadence without enforcing it
**Files:** `app/data/models.py:105-117`, `app/core/exposure.py:195,201-202`

`get_points_in_range` + `pt_end = pt_start + 1h` assume hourly steps. Nothing validates sort order, duplicates, gaps, or cadence. Duplicate timestamps would double-count dose; 15-min data would over-count 4×. `sort_points()` is manual (callers can forget).

**Fix:** add `model_validator` ensuring strictly increasing timestamps, warn on non-hourly gaps, document “hourly `[T, T+1h)` contract” in `ForecastProvider.get_forecast` docstring; consider an explicit `interval_minutes` field for future-proofing.

### P1-9 — `normalize_open_meteo_response` is brittle on real payloads
**File:** `app/data/normalization.py:23-74`

- Negative `pm2_5` passes through to Pydantic `ge=0.0` → raw `ValidationError` → 500. Coerce/clamp with warning or raise domain error.
- Length-mismatched `time`/`pm2_5`/`temperature_2m` silently yields `None` gaps (later `no_recommendation`). Emit a warning count.
- `datetime.fromisoformat` “Z” handling is version-sensitive (worked on the test 3.11.9, fails on older 3.11/3.10). Normalize trailing `Z` → `+00:00` explicitly.
- `generated_at=datetime.now(UTC)` loses the provider’s own timestamp if present.

---

## 4. P2 — Quality, testing, docs, ops

1. **`ruff format --check` fails on 3 files** (`routes_plan.py:134`, `routes_whatif.py:153`, `schemas.py:141+`). `ruff check` passes. Run `ruff format` + add pre-commit/CI check.
2. **Undeclared test dep.** `tests/test_provider.py` uses `pytest.mark.anyio` but `pyproject.toml` declares only `pytest/httpx/ruff`. It passes today because `anyio` rides along with `httpx/starlette` (`.venv` has `anyio-4.15.1`). Declare `anyio` (+ `pytest-asyncio` or `anyio` config) explicitly; otherwise a fresh resolver may drop it.
3. **Ambiguous what-if precedence.** If both `modified_plan` and `overrides` are sent, `modified_plan` silently wins (`routes_whatif.py:20-34`, verified `both → cycling`). 422 on “both provided” or document merge order.
4. **No observability.** No logging, no request-id, no provider-latency metric, no structured error handler — provider `ValueError`/`ValidationError` return default 500 HTML/JSON. Add `try/except` → 502 with `detail`, plus startup log of `settings`.
5. **Response-shape nits.** `BestSlotResponse.intervals` present in `/plan`, absent in `/whatif`; `reduction_pct=None` vs `0.0` semantics undocumented; `BaselineResponse.end` bug (§P1-1) compounds this. Freeze contracts with golden-file tests.
6. **Health leaks config.** `/health` returns `environment` + `provider` — fine for hackathon, flag for prod (enumerate, don’t expose internals).
7. **Sample data drift.** `data/sample_forecast.json` (hand-made, `is_observed=true` for 00–06) does not match default `MockForecastProvider()` output (`has_station_observations=False`, different PM2.5 curve) and is never loaded by code/tests. Either generate it from the mock + pin a script, or delete to avoid “which is truth?” confusion.
8. **Version drift.** PRD suggests 3.12, README/pyproject say 3.11+. `ARCHITECTURE.md:58` embeds an absolute `file:///...` link to a teammate’s homedir — replace with relative path.
9. **Single-commit history, no CI.** One commit `1aa6781`, no GitHub workflow, no Dockerfile, no coverage gate. Add minimal CI (`pytest + ruff check + ruff format --check`) before inviting frontend/AWS teammates.

---

## 5. Security & abuse notes (no secrets found)

- No secrets in repo (`.env.example` clean, no `.env` committed). Good.
- Missing: rate limiting, auth (correctly out of scope per PRD non-goals, but state it), max-body/window limits (§P0-5), Pydantic strictness on `humidity_pct`/`temperature_c` ranges (only `humidity`/`pm25` bounded — extreme temps accepted, fine for MVP but note).
- `location_name` free-text flows into responses unescaped — safe under JSON, but frontend must not `innerHTML` it.
- Error messages echo raw exception text (`reason_invalid=str(e)`) — fine for MVP, sanitize before exposing upstream provider errors in prod.

---

## 6. Recommended roadmap (ordered, MVP-safe)

**Sprint 1 — Correctness & trust (1–2 days, no contract breaks except where noted):**
1. Fix freshness reference (§P0-1) + add regression test (fresh provider, future window → `is_stale is False`).
2. Propagate real confidence + intervals in `/whatif` (§P0-2).
3. Validate `PlanOverrides` (activity + tz) (§P0-3) + test 422s.
4. Handle `ValueError` in optimizer (§P0-4) + test `no_recommendation` vs raise contract.
5. Fix baseline `end` (§P1-1) + golden test.
6. Weight temperature average (§P1-2) + fix warning spam (§P1-3).
7. Fix CORS (§P0-6).

**Sprint 2 — Hardening (2–3 days, one minor contract addition):**
8. Window/candidate caps + `include_*` flags (§P0-5); document in `docs/API.md`; add 413/422 tests.
9. Strict provider selection (no silent mock) + wire or remove `file` option (§P1-6); validated `Settings` (§P1-7).
10. Series cadence validator + mock fixes (count, `missing_hours` split) (§P1-4, §P1-8); pin `sample_forecast.json` generation.
11. Normalization guards (§P1-9); `ruff format`; declare `anyio` test dep; add CI workflow.
12. Structured errors + logging (provider 502, request-id middleware).

**Later (explicit non-goals today, per PRD):** S3 cache provider, Open-Meteo/OpenAQ live provider with retry/timeout/circuit-breaker, auth/rate-limit, persistence for plan-IDs, Bedrock/Strands tool schemas, frontend chart contract (`candidates` sampling for large windows).

---

## 7. Suggested tests to add (each maps to a bug above)

- `test_plan_future_window_not_stale` — fresh mock, window +48h → `is_stale is False`, no stale warning.
- `test_whatif_confidence_matches_quality` — stale mock (`stale_hours=30`) → both recommendations carry `confidence != "high"`.
- `test_overrides_invalid_activity_422` / `test_overrides_naive_datetime_422`.
- `test_optimizer_invalid_activity_no_crash` — define expected: raise vs `no_recommendation`.
- `test_plan_window_cap_422` — 30-day window rejected; `test_plan_candidate_cap` — flags trim payload.
- `test_baseline_failure_end` — `end == start + duration` even when invalid.
- `test_temperature_time_weighted` — 45 min @30 + 15 min @20 → `27.5`.
- `test_temp_warning_single` — N candidates, 1 warning.
- `test_mock_point_count` — `[17:00,21:00]` → exact expected count; `test_missing_hours_index_vs_wall` — non-aligned start.
- `test_normalize_negative_pm25` / `mismatched_lengths` / `zulu_time`.

---

## 8. Files reviewed

`app/main.py`, `app/config.py`, `app/core/exposure.py`, `app/core/optimizer.py`, `app/core/comparison.py`, `app/data/models.py`, `app/data/providers.py`, `app/data/mock_provider.py`, `app/data/normalization.py`, `app/api/schemas.py`, `app/api/dependencies.py`, `app/api/routes_plan.py`, `app/api/routes_whatif.py`, `app/api/routes_trust.py`, `tests/test_{api,comparison,exposure,optimizer,provider}.py`, `docs/API.md`, `docs/ARCHITECTURE.md`, `data/sample_forecast.json`, `prd.md`, `README.md`, `pyproject.toml`, `.env.example`, `.gitignore`.

---

## 9. Verification appendix (reproduce without editing the repo)

```bash
source .venv/bin/activate
pytest -v                          # 29 passed (anyio via transitive dep)
ruff check app tests                # All checks passed
ruff format --check app tests       # 3 files would reformat (see §4.1)
```

Targeted reproductions used for this report (read-only `python -c` against `.venv`):

- Temp weighting: 45 min@30°C + 15 min@20°C → `avg_temperature_c == 25.0` (want `27.5`).
- Baseline failure: `start == end`, `duration_min=30`.
- Mock `[17:00,21:00]` → 6 points ending `22:00`; `missing_hours={0}` blanks `17:00`.
- Overrides: invalid activity + naive datetime both pass schema.
- Optimizer: `optimize_schedule(..., 'skydiving', ...)` raises `ValueError`.
- Freshness: `gen=now`, window +2d → `ref=window_start: 172800s stale`, `ref=now: 0s fresh`.
- Temp-missing: 5 candidates → 5 identical warnings.
- What-if both `modified_plan` + `overrides` → `modified_plan` wins silently.
- 7-day `step_min=5` plan → `2014` candidates, `200 OK`.

---

*End of report. Overall: ship Sprint 1 before any production or health-adjacent claims; the core math and layering are worth keeping.*
