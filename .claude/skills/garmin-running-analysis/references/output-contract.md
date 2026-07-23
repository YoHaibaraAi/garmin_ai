# Output Contract

Use this reference to choose files and distinguish field semantics.

## Mode outputs

| Mode | FIT download/parse | Primary output | Exported files |
| --- | --- | --- | --- |
| `compact` | No | Reduced JSON or compact HTML | Summary, current metrics, sleep, Connect splits |
| `basic` | Yes when available | Full context JSON on stdout | Optional basic JSON/CSV directory |
| `html` | Yes when available | Context JSON plus paths | Overview, activity reports, Plotly charts |
| `full` | Yes when available | Context JSON plus paths | HTML, JSON, CSV, Parquet, original FIT |

Directory exports create a unique `<run_id>/` directory and a sibling `<run_id>.zip`. Trust returned `export_dir` and `export_archive`; do not infer their names.

## Core JSON shape

Top-level fields:

- `ok`: success boolean.
- `mode`, `chart_x`, `sleep_days`, `generated_at`: request/result metadata.
- `profile`: height, age, configured or Garmin-sourced personal maximum heart rate, and lactate-threshold heart rate when available.
- `current_metrics`: current/day-level wellness metrics plus compact sleep history.
- `recent_runs`: activities ordered by recency.
- `data_quality`: partial, missing, or failed sources.
- `export_dir`, `export_archive`: present for directory exports.

Each `recent_runs[]` item can contain:

- `activity_id`, `date`
- `summary`
- `day_metrics`
- `connect_splits`
- `fit_laps`
- `km_splits`
- `data_quality`
- mode-specific `compact_data`, `html_data`, or `full_data`

## Similar fields that must remain distinct

- `profile.max_heart_rate`: the user's personal max-HR setting, from Garmin device/settings when possible and local config as fallback.
- `current_metrics.daily_max_heart_rate`: highest all-day heart rate for the metric date.
- `recent_runs[].summary.max_hr`: peak heart rate within one activity.
- `current_metrics.vo2max`: Garmin display value.
- `current_metrics.vo2max_precise`: more precise Garmin value; prefer it for trend comparisons when present.
- `connect_splits`: Garmin Connect backend splits; not necessarily one kilometer.
- `fit_laps`: watch-recorded automatic/manual/workout laps; not necessarily one kilometer.
- `km_splits`: fixed one-kilometer splits calculated from FIT records; the last split can be partial.

Pace fields such as `avg_pace_sec_per_km` and `pace_sec_per_km` are seconds per kilometer. Durations are seconds, distances are meters unless a `_km` suffix is present, heart rate is bpm, cadence is steps/minute, and power is watts.

## Export selection

| Question | Prefer |
| --- | --- |
| Overall run or wellness summary | top-level JSON and `summary` |
| Fixed-kilometer pacing/HR/cadence/power | `km_splits` or `km_splits.csv` |
| What the watch recorded as laps | `fit_laps` or `fit_laps.csv` |
| What Garmin Connect displays | `connect_splits` or `connect_splits.json` |
| Per-record trend | `records.csv` or `records.parquet` |
| Running dynamics | `running_dynamics.csv` |
| Route/location relationship | `gps.csv` |
| Pauses and activity events | `events.csv` |
| Device/sensor provenance | `device_info.json` |
| Manual validation or re-parsing | `original.fit` |

HTML exports begin at top-level `index.html`. Activity `index.html` contains a readable report; `charts.html` contains Plotly charts when generated.

## Missing and failed data

Never replace absent fields with estimates. Check both top-level and activity-level `data_quality`.

- `missing` or `missing_from_api`: Garmin did not supply a usable value.
- `partial`: some source calls or dates failed but other data remains usable.
- `fit_download` or `fit_parse` error: summary and Connect data may still be valid; FIT-derived laps, km splits, or records may be absent.
- Empty running dynamics or GPS can be legitimate for unsupported devices or indoor activities.

The CLI emits failures as:

```json
{"ok": false, "error_code": "AUTH_REQUIRED", "message": "..."}
```

Known codes include `AUTH_REQUIRED`, `FIT_DOWNLOAD_ERROR`, `FIT_PARSE_ERROR`, domain-specific `GarminAIError` codes, and `UNKNOWN_ERROR`.
