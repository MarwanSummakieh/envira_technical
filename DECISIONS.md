Started: 2026-09-22 10:22 Europe/Copenhagen (UTC+02:00)
Stopped: in progress

## What I built
- Built a single-asset exposure API, requested browser lookup and shared CLI, with startup validation and exact rainfall totals.
- Exercise deadline: 12:22 local; reserve 12:07 onward for final verification. Review pauses count.
- AI tooling: Codex desktop agent and a verification subagent used for inspection, setup, checks and documentation.
- Agent verification: 94 tests passed; independent CSV check confirmed 1.2 + 2.9 + 68.4 = 72.5 mm; no user-confirmed checks.
- Verified UTC schedule yields four slots on DST dates; rejected coordinate magnitudes as proof of CRS.

## What I deliberately did not build, and why
- Counts/maxima use complete dates only; unresolved duplicates remain unknown rather than becoming false rainfall.
- No portfolio, database, shared cache or deployment; chose CLI over Docker because its daemon was unavailable.
- User authorized staged publication without the candidate brief; original commit preserved on a local-only branch.

## What I would do first with another day
- Confirm source CRS and observation interval semantics with the data provider.
