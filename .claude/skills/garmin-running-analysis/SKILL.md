---
name: garmin-running-analysis
description: Fetch, export, and analyze local Garmin Connect running and wellness data through the garmin-ai CLI. Use when Codex or Claude needs to answer questions about recent runs, pacing, heart rate, cadence, power, training load or effect, VO2max, HRV, resting heart rate, sleep, recovery, Garmin splits or laps, FIT records, route or GPS data, or when the user asks for AI-friendly Garmin JSON, CSV, Parquet, HTML, or chart exports. Also use to diagnose garmin-ai authentication and data-quality failures.
---

# Garmin Running Analysis

Use the local `garmin-ai` project through the bundled wrapper. Keep credentials, tokens, health data, and location data on the user's machine.

## Collect the request

Infer these inputs from the request:

- Analysis goal: summary, comparison, pacing, heart rate, running dynamics, sleep/recovery, route, or export.
- Run count: interpret `--limit N` as the most recent N running activities, not N days. Default to `1` when the user does not specify N.
- Sleep window: default to `7` days; pass `--sleep-days N` when specified.
- Detail mode: default to compact HTML; select another mode only when the request requires it.
- Output location: default to `./data/exports/compact`; use a user-provided path when specified.
- Chart x-axis: default to `distance`; use `time` only when requested or materially more useful.

Do not ask for fields that can be inferred safely.

## Locate and check the project

Resolve `SKILL_DIR` as the directory containing this `SKILL.md`, then run:

```bash
python3 "$SKILL_DIR/scripts/garmin_ai.py" --doctor
```

The wrapper discovers the project in this order:

1. `--project-root PATH`
2. `GARMIN_AI_PROJECT_ROOT`
3. the current directory or one of its parents
4. the repository containing this skill
5. `~/github.com/garmin_ai`

If discovery fails, ask for the repository path and pass `--project-root PATH`, or have the user set `GARMIN_AI_PROJECT_ROOT`.

If dependencies are missing, tell the user to run:

```bash
python3 "$SKILL_DIR/scripts/garmin_ai.py" --setup
```

Setup requires `uv`, Python 3.12 is recommended, and network access may be needed on the first run.

## Authenticate safely

If the CLI returns `AUTH_REQUIRED`, tell the user to run this themselves in an interactive terminal:

```bash
python3 "$SKILL_DIR/scripts/garmin_ai.py" auth
```

Never ask the user to paste a Garmin password, MFA code, token, or the contents of `~/.garminconnect` into chat. Do not run `auth` non-interactively. Authentication targets Garmin China because the project configures `is_cn=True`.

## Select the mode

| Need | Mode | Command shape |
| --- | --- | --- |
| Default recent-run report | compact HTML | `base --limit N --mode compact --compact-format html --output ./data/exports/compact` |
| JSON-only low-token context without FIT download | compact JSON | `base --limit N --mode compact --compact-format json` |
| Normal run analysis with summary, FIT laps, and calculated km splits | basic | `base --limit N --mode basic --json` |
| Human-readable reports and charts without raw record exports | html | `base --limit N --mode html --output DIR` |
| Per-record data, running dynamics, GPS, Parquet, or original FIT | full | `base --limit N --mode full --output DIR` |

Use this default command. Replace `1` with the requested recent-run count when the user specifies N:

```bash
python3 "$SKILL_DIR/scripts/garmin_ai.py" base --limit 1 --mode compact --compact-format html --output ./data/exports/compact
```

This is equivalent to running the following from the project root:

```bash
uv run garmin-ai base --limit 1 --mode compact --compact-format html --output ./data/exports/compact
```

Keep compact HTML as the default. Use compact JSON only when the user explicitly wants JSON-only or no HTML files. Use basic when FIT laps and calculated kilometer splits are needed. Use HTML for detailed charts. Use full only when the user explicitly needs raw or route-level detail.

Run commands through the wrapper:

```bash
python3 "$SKILL_DIR/scripts/garmin_ai.py" base --limit 1 --mode compact --compact-format html --output ./data/exports/compact
python3 "$SKILL_DIR/scripts/garmin_ai.py" base --limit 5 --mode compact --compact-format json
python3 "$SKILL_DIR/scripts/garmin_ai.py" base --limit 1 --mode basic --json
python3 "$SKILL_DIR/scripts/garmin_ai.py" base --limit 3 --mode html --output OUTPUT_DIR
python3 "$SKILL_DIR/scripts/garmin_ai.py" base --limit 1 --mode full --output OUTPUT_DIR
```

Read [references/output-contract.md](references/output-contract.md) before consuming exported files or interpreting similarly named fields. Read [references/analysis-guidance.md](references/analysis-guidance.md) before producing a training, recovery, or trend analysis.

## Analyze the result

1. Confirm top-level `ok`.
2. Inspect top-level and per-run `data_quality` before drawing conclusions.
3. Start with `profile`, `current_metrics`, `recent_runs[].summary`, and `recent_runs[].day_metrics`.
4. Use `km_splits` for fixed-kilometer pacing trends, `fit_laps` for watch-recorded laps, and `connect_splits` to match Garmin Connect.
5. Read `records.csv` or `running_dynamics.csv` only for explicit per-record or detailed dynamics requests.
6. Read `gps.csv` only for explicit route, map, GPS, climb-location, or route-performance requests.
7. Separate observed facts from interpretations. State missing or partial data rather than estimating it.
8. Answer with the requested conclusion first, then supporting metrics, caveats, and a practical next step when useful.

Treat `data_quality` entries as scoped failures. A failed FIT download can coexist with valid Garmin Connect summaries; do not discard valid data.

## Expected outputs

- Default task: create a compact HTML export under `./data/exports/compact/<run_id>/`, create the sibling `<run_id>.zip`, and return a concise evidence-based analysis.
- Treat `--limit N` as the maximum number of most recent running activities returned; fewer can be returned when Garmin has fewer matching activities.
- `basic` or unexported compact task: consume JSON from standard output.
- Export task: report `export_dir` and `export_archive` from returned JSON instead of guessing the timestamped directory.
- Compact HTML task: start at the exported top-level `index.html`; activity pages contain Summary and Connect Splits and intentionally omit charts and FIT-derived files.
- Detailed HTML task: start at the exported top-level `index.html`, then inspect activity reports and charts.
- Full task: use only the smallest required files; raw outputs can be large.
- Error: handle JSON shaped like `{"ok": false, "error_code": "...", "message": "..."}` and preserve the error code in the explanation.

## Protect sensitive data

- Treat all exports as private health data.
- Treat FIT and GPS files as potentially identifying location data.
- Do not upload or transmit exports unless the user explicitly requests and authorizes it.
- Do not expose token-store contents in logs or diagnostics.
- Prefer cached FIT files unless the user asks to refresh with `--no-cache`.
