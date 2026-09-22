# Envira exposure service

Stage 2: runnable health endpoint and startup CSV/schema loading. Exposure calculations are not implemented yet.
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

## Smallest planned implementation

`app/main.py`: FastAPI app factory, lifespan preparation, response models and routes.
`app/data.py`: validation and prepared lookups. `app/geo.py`: CRS and nearest station with ID tie-breaks.
`app/exposure.py`: local daily aggregation and precomputed per-station summaries.
`tests/`: tiny hand-calculated fixtures and API checks.

Unknown assets will return 404; insufficient data will produce a documented unavailable result.
Unusable files/schema will fail startup clearly. Prepared in-memory data is static until restart,
per process, and requests will not reload CSVs. No database, shared cache, frontend or risk score is planned.
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

Health returns `{"status":"ok"}` after startup loads the three nonempty CSVs and validates required
columns. It does not yet certify row quality or exposure availability. Missing/empty files or bad
schemas prevent startup. No file reads occur merely by importing `app.main` or creating the app.
`create_app(data_dir=...)` overrides `ENVIRA_DATA_DIR`; the default is `data` relative to the working
directory. Tests use temporary CSV fixtures, not candidate files.

`ExposureResponse` in `app/main.py` defines the upcoming response: asset/station IDs, distance,
nullable wet-day count and three-day precipitation, separate availability statuses, inclusive
analysis dates, timezone and complete/incomplete day/window counts. No exposure route is registered
yet: `/assets/{asset_id}/exposure` currently returns 404 rather than invented data.

Stage 2 verification: four tests passed and the documented Uvicorn command returned the health
response using the supplied data. Starlette emits two dependency deprecation warnings (httpx and
AnyIO's BlockingPortal alias); neither failed the checks. A clean-environment install is not yet verified.
If a restricted runner cannot access its usual temporary folder, run tests with a local temporary root:

```powershell
$env:TMP = Join-Path (Get-Location) '.test-tmp'
New-Item -ItemType Directory -Path $env:TMP -Force
$env:TEMP = $env:TMP
.\.venv\Scripts\python.exe -m pytest -q
```
