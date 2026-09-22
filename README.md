# Envira exposure service

Single-asset rainfall exposure endpoint with startup preparation and verified fixture tests.
The supplied candidate brief is authoritative and is kept locally, excluded from publication.

## Setup (PowerShell, Python 3.12)

Use one workflow: standard `venv` and `pip`. Install Python 3.12 if `py -3.12` is unavailable.
The development machine used the Codex bundled Python 3.12.14 executable to create the environment;
no global packages were installed. Activation is optional:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest --version
```

`pyproject.toml` declares supported Python and direct dependency ranges; `requirements.lock`
pins the resolved runtime and test dependencies from the Windows Python 3.12 environment.
It is a pip freeze snapshot, without hashes or a cross-platform solver guarantee.
To intentionally refresh it, install `.[test]`, then freeze excluding the local project.

## Candidate data

Obtain only the supplied candidate `envira-test-data.zip`, extract it locally, and place
`assets.csv`, `stations.csv`, and `observations.csv` directly under `data/`.
For the already-extracted layout on this machine:

```powershell
New-Item -ItemType Directory -Path data -Force
Copy-Item envira-test-data\data\assets.csv,envira-test-data\data\stations.csv,envira-test-data\data\observations.csv -Destination data
.\.venv\Scripts\python.exe scripts\profile_data.py data
```

Data, archives, environments and IDE files are ignored by Git.
Original supplied files are preserved. Do not package this entire working directory;
use tracked files for submission and arrange authorized candidate data separately.
The candidate brief is also excluded from published history. The `stage1-local-original` branch
preserves the original local commit containing that brief; do not publish that branch or use `git push --all`.

## Inspected data and assumptions

| Input | Rows | Unique keys | Exact duplicate extras | Keys with differing rows |
| --- | ---: | ---: | ---: | ---: |
| Assets (`asset_id`) | 5,040 | 5,000 | 0 | 40 |
| Stations (`station_id`) | 123 | 120 | 0 | 3 historical versions |
| Observations (`station_id`, `observed_at`) | 260,753 | 260,553 | 0 | 200 precipitation conflicts |

- Asset x: 471,540.51–729,590.93; y: 6,078,766.71–6,384,374.90. Station latitude:
  54.922192–57.579624; longitude: 8.633835–12.637938. No missing/nonfinite coordinate values.
- Working CRS assumption: assets ETRS89 / UTM zone 32N (EPSG:25832), stations WGS84
  (EPSG:4326). Transform with explicit longitude/latitude order (`always_xy=True`) into
  EPSG:25832 and use projected straight-line metres. Assets transformed to approximately
  8.55–12.65 E, 54.86–57.59 N, consistent with Denmark and station bounds. EPSG:32632 produces
  essentially the same bounds, so this sanity check cannot establish the datum. Source CRS is unconfirmed.
- UTC coverage: 2024-12-31 23:00 through 2026-06-30 17:00. Copenhagen local analysis dates:
  2025-01-01 through 2026-06-30 inclusive (546 days), shared across stations.
- Observations occur at 23:00, 05:00, 11:00 and 17:00 UTC. Generate expected slots in UTC,
  convert to Copenhagen, then group by date. This schedule yields four slots even on the
  three DST transition dates in the data; that is evidence from this schedule, not a 24-hour-day assumption.
  All rows are on schedule; 1,527 station/timestamp keys are absent from 262,080 expected keys
  (120 stations times 2,184 slots), before invalid rainfall and conflicts are excluded.
- Rainfall has 5,285 negative sentinel rows: 4,910 at -999 and 375 at -9999. No blank/nonfinite
  rainfall, malformed timestamps, or unknown station references were found. Negative temperatures are valid.
- Station validity dates parse successfully. The 120 blank ends mean open-ended validity.
  Three station IDs have adjacent date ranges: DK1665 (July 24/25, 2025), DK1595
  (November 3/4, 2025), DK1560 (January 21/22, 2026). Use inclusive boundaries and reject
  conflicting overlaps; select geometry valid on the final analysis date and use that ID's entire history.
- Collapse identical duplicates; conflicting assets will return HTTP 409. Conflicting rainfall keys
  become unknown, regardless of row order; differences only in temperature do not matter.
- Treat each precipitation amount as belonging to the timestamp's local date, summing without
  duration multiplication. Interval start/end semantics remain unconfirmed by the candidate brief.
- Only complete days will contribute to wet-day counts (inclusive 20 mm) and consecutive three-date
  windows. Missing days remain unknown. Return nullable metrics and explicit coverage/status, never NaN.

## Architecture

`app/main.py`: FastAPI app factory, lifespan preparation, response models and routes.
`app/data.py`: validation and prepared lookups. `app/geo.py`: CRS and nearest station with ID tie-breaks.
`app/exposure.py`: local daily aggregation and precomputed per-station summaries.
`tests/`: tiny hand-calculated fixtures and API checks.

Unknown assets return 404; conflicting asset IDs return 409; invalid asset records return 422.
No eligible station location produces 503. Insufficient weather data returns 200 with null metrics
and explicit availability statuses. Unusable files/schema or no valid source timestamps fail startup.
Prepared in-memory data is static until restart, per process; requests do not reload CSVs.
No database, shared cache, frontend or risk score is implemented.
## Run and test

From the repository root, with candidate files in `data/`:

```powershell
$env:ENVIRA_DATA_DIR = '.\data'
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
.\.venv\Scripts\python.exe -m pytest -q
```

For a JetBrains Python run configuration, register the existing `.venv\Scripts\python.exe`
as the project Python SDK, choose module `uvicorn`, and use parameters
`app.main:create_app --factory --host 127.0.0.1 --port 8000` with the repository root as the
working directory. The local `Envira` configuration is set up this way. IDE settings are
machine-local and ignored by Git. After an external SDK-settings repair, restart the IDE
to load the registration; ensure no other server already occupies port 8000.

Health returns `{"status":"ok"}` after startup prepares the three nonempty CSVs, validates rows and
precomputes station summaries and asset assignments. Individual unavailable/conflicting records
are disclosed by errors, coverage and concise startup counts. Missing/empty files or bad schemas
prevent startup. No file reads occur merely by importing `app.main` or creating the app.
`create_app(data_dir=...)` overrides `ENVIRA_DATA_DIR`; the default is `data` relative to the working
directory. Tests use temporary CSV fixtures, not candidate files.

## Example request and observed response

```powershell
Invoke-RestMethod http://127.0.0.1:8000/assets/A-200975/exposure | ConvertTo-Json -Depth 5
```

Observed against the supplied candidate CSVs:

```json
{
  "asset_id": "A-200975",
  "station_id": "DK1469",
  "distance_m": 10470.51,
  "wet_day_count": 25,
  "worst_three_day_precip_mm": 72.5,
  "wet_day_status": "available",
  "three_day_status": "available",
  "analysis_period": {"start": "2025-01-01", "end": "2026-06-30", "timezone": "Europe/Copenhagen"},
  "coverage": {"complete_days": 491, "incomplete_days": 55, "eligible_three_day_windows": 398}
}
```

Counts and maxima cover only complete days/windows; they are not estimates for missing rainfall.
No wet-day count is reported when no complete day exists; a complete dry day legitimately contributes zero.
Station geometry uses the period's final date even for earlier rainfall; any conflicting overlapping
location history excludes that ID entirely. Invalid/off-schedule observation rows are rejected and
counted; valid scheduled slots are required for completeness. A valid timezone-aware timestamp
contributes to the global period even if its rainfall or station reference is invalid.
Invalid station rows are rejected before version-conflict checks; they do not disqualify other valid
rows for that ID. Consequently, malformed records could hide a contradictory history. Review startup
quality counts before interpreting results. Temperature is unused and does not affect rainfall validity.

## Verification and limitations

Stage 4: 94 tests passed, covering DST, exact thresholds, missing dates, duplicate/conflict policies,
station histories, API errors, finite JSON numbers and absence of request-time CSV reads.
An independent calculation using standard-library CSV parsing, datetime and Decimal matched the
example's station, distance, period, wet days, maximum and coverage. Run it from the repository root:

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_example data
```

The largest valid window is 2026-01-13 through 2026-01-15: **1.2 + 2.9 + 68.4 = 72.5 mm**.
The projection check includes UTM32's known 500,000 m central-meridian easting at longitude 9°;
this validates coordinate ordering and projection mechanics, not the unconfirmed source datum.

One Windows in-process TestClient run measured 10.359 seconds for startup and 100 requests at
1.343 ms median / 4.841 ms maximum, with CSV reads blocked after startup. These are local measured
observations, not a network/load benchmark. All verification so far was agent-run.
Starlette emits two dependency deprecation warnings (httpx and AnyIO's BlockingPortal alias);
neither failed checks. A clean-environment install is not yet verified.

Rainfall values are interpreted as amounts assigned to the timestamp's date, with source interval
semantics unconfirmed. Missing rainfall remains unknown; station selection does not optimize for
weather completeness. Projected straight-line distance and final-date geometry simplify history.
Finite values whose sums exceed JSON float range fail preparation clearly instead of emitting Infinity.
Candidate data is required separately; it is not included in the repository.

If a restricted runner cannot access its usual temporary folder, run tests with a local temporary root:

```powershell
$env:TMP = Join-Path (Get-Location) '.test-tmp'
New-Item -ItemType Directory -Path $env:TMP -Force
$env:TEMP = $env:TMP
.\.venv\Scripts\python.exe -m pytest -q
```
