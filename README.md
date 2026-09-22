# Envira exposure service

Look up an asset's nearest weather station, wet-day count and highest three-day rainfall through a web page, API or CLI.

## Quick start

Use **Python 3.12** and PowerShell from the repository root. If `.venv` already exists, skip the first command. If `py` is unavailable, install Python 3.12 first.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
```

Extract the supplied candidate data archive. Place its three CSVs directly in `data/`:

```text
data/
  assets.csv
  stations.csv
  observations.csv
```

Data is supplied separately. To use another folder, set `$env:ENVIRA_DATA_DIR = 'C:\path\to\data'`.

Start the server:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

Open [the app](http://127.0.0.1:8000/) and click **Check exposure**, or enter another asset ID. [API docs](http://127.0.0.1:8000/docs) and [health status](http://127.0.0.1:8000/health) are also available. Stop with **Ctrl+C**.

### WebStorm / JetBrains

Create a Python run configuration with these settings:

| Setting | Value |
| --- | --- |
| Python SDK / interpreter | Select the existing `.venv\Scripts\python.exe` |
| Run type | Module |
| Module name | `uvicorn` |
| Parameters | `app.main:create_app --factory --host 127.0.0.1 --port 8000` |
| Working directory | Repository root, not `app/` |
| Environment variables | Optional: `ENVIRA_DATA_DIR=C:\path\to\data` |

For “Please select a module with a valid Python SDK,” register that interpreter as the project's Python SDK. Stop any existing server before using port 8000 again.

## Tests and CLI

Neither command needs a running server. Tests use temporary fixtures, not candidate data.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m app.cli A-200975 --data-dir data
```

The CLI returns the same JSON as the API: exit `0` on success, `2` on input/data errors, diagnostics on stderr. Without `--data-dir`, it uses `ENVIRA_DATA_DIR` or `data`.

Check the supplied data and independently verify the example:

```powershell
.\.venv\Scripts\python.exe scripts\profile_data.py data
.\.venv\Scripts\python.exe -m scripts.verify_example data
```

If pytest cannot access its temporary folder:

```powershell
$env:TMP = Join-Path (Get-Location) '.test-tmp'
New-Item -ItemType Directory -Path $env:TMP -Force
$env:TEMP = $env:TMP
.\.venv\Scripts\python.exe -m pytest -q
```

## API example

With the server running:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/assets/A-200975/exposure | ConvertTo-Json -Depth 5
```

Observed response with the supplied CSVs:

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

| Condition | HTTP response |
| --- | --- |
| Unknown asset | `404` |
| Conflicting asset records | `409` |
| Invalid asset record | `422` |
| No eligible station | `503` |
| Insufficient weather data | `200`, affected metrics are `null` with availability statuses |

Missing/empty CSVs, invalid schemas or no valid timestamps prevent startup. Review startup quality counts before interpreting results.

## Calculation rules

- **Distance:** assume assets use EPSG:25832 and stations use WGS84 (EPSG:4326). Transform longitude/latitude to EPSG:25832; choose the shortest projected distance in metres, breaking ties by station ID. Source CRS remains unconfirmed.
- **Station history:** use geometry valid on the final analysis date and that station ID's full rainfall history. Validity boundaries are inclusive; blank ends are open. Conflicting overlapping locations exclude the ID. Invalid station rows are discarded first, so malformed records can hide contradictory history.
- **Dates:** use Europe/Copenhagen local dates and expected observations at 23:00, 05:00, 11:00 and 17:00 UTC. Generate slots across timezone changes; do not assume every local day lasts 24 hours.
- **Missing data:** identical readings count once. Missing, negative, invalid or conflicting rainfall is unknown; temperature is unused. A day is complete only when every expected slot is valid.
- **Metrics:** use exact decimal sums. Wet days have at least **20 mm**. Three-day windows require three consecutive complete local dates. `null` means unavailable; `0` means an observed zero result. Coverage shows excluded days/windows.
- **Period:** all valid source timestamps define the shared date range, even when their rainfall or station reference is rejected. A stray timestamp can extend it. Rainfall amounts belong to the timestamp's local date; interval start/end semantics remain unconfirmed.

These metrics describe observed rainfall, not flood probability or estimates for missing periods.

## Where to change code

| File | Responsibility |
| --- | --- |
| [app/main.py](app/main.py) | Routes, response schema and startup |
| [app/data.py](app/data.py) | CSV validation and prepared lookups |
| [app/geo.py](app/geo.py) | Coordinates, station history and nearest station |
| [app/exposure.py](app/exposure.py) | Daily totals and rainfall metrics |
| [app/cli.py](app/cli.py) | Command-line interface |
| [app/static/index.html](app/static/index.html) | Browser form; no frontend build step |
| [tests/](tests/) | Small fixtures and API checks |

Data is prepared once per server process and stays fixed until restart. Requests do not reread CSVs; each CLI invocation prepares data again. `create_app(data_dir=...)` overrides the environment setting.

To change a calculation, update its module and a small fixture test, then run pytest. Update the response schema and browser form when adding output fields.

## Verification and limits

The original implementation passed **102 tests**, fresh Windows Python 3.12 installation, installed-wheel/API/CLI checks and desktop/mobile browser checks. Accessibility scanning found zero violations. Two dependency deprecation warnings remain; other operating systems were not tested. `requirements.lock` is a pinned Windows dependency snapshot.

The independent example check matched **1.2 + 2.9 + 68.4 = 72.5 mm** for 13–15 January 2026. All checks were agent-run. See [DECISIONS.md](DECISIONS.md) for scope and next steps.

Keep candidate data, briefs, environments and IDE settings out of publication. They are ignored locally. The local `stage1-local-original` branch contains the original brief; do not publish it or use `git push --all`.
