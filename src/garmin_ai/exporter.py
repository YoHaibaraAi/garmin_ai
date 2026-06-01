"""Export JSON, CSV, Parquet, FIT, and activity context files."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd

from .utils import json_safe


def write_json(path: Path | str, data: Any) -> Path:
    """Write JSON with stable UTF-8 formatting."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(json_safe(data), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path


def export_base_context(output_dir: Path | str, context: dict[str, Any]) -> Path:
    """Export the top-level base context."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "base_context.json", context)
    write_json(output / "recent_runs.json", context.get("recent_runs", []))
    return output / "base_context.json"


def export_activity_basic(
    activity_dir: Path | str,
    context: dict[str, Any],
    connect_splits: list[dict[str, Any]],
    fit_laps: list[dict[str, Any]],
    km_splits: list[dict[str, Any]],
) -> dict[str, str]:
    """Export basic per-activity files."""

    output = Path(activity_dir)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "context.json", context)
    write_json(output / "summary.json", context.get("summary", {}))
    write_json(output / "connect_splits.json", connect_splits)
    _write_csv(output / "fit_laps.csv", fit_laps)
    _write_csv(output / "km_splits.csv", km_splits)
    return {
        "context_file": str(output / "context.json"),
        "summary_file": str(output / "summary.json"),
        "connect_splits_file": str(output / "connect_splits.json"),
        "fit_laps_file": str(output / "fit_laps.csv"),
        "km_splits_file": str(output / "km_splits.csv"),
    }


def export_activity_full(
    activity_dir: Path | str,
    fit_path: Path | str,
    context: dict[str, Any],
    records: list[dict[str, Any]],
    running_dynamics: list[dict[str, Any]],
    gps: list[dict[str, Any]],
    events: list[dict[str, Any]],
    device_info: list[dict[str, Any]],
    developer_fields: list[dict[str, Any]],
    charts_path: Path | str | None = None,
) -> dict[str, str]:
    """Export full per-activity data files."""

    output = Path(activity_dir)
    output.mkdir(parents=True, exist_ok=True)
    records_csv = _write_csv(output / "records.csv", records)
    records_parquet = _write_parquet(output / "records.parquet", records)
    running_dynamics_file = _write_csv(output / "running_dynamics.csv", running_dynamics)
    gps_file = _write_csv(output / "gps.csv", gps)
    events_file = _write_csv(output / "events.csv", events)
    device_info_file = write_json(output / "device_info.json", device_info)
    developer_fields_file = write_json(output / "developer_fields.json", developer_fields)
    original_fit = output / "original.fit"
    shutil.copyfile(fit_path, original_fit)

    export_activity_basic(
        output,
        context,
        context.get("connect_splits", []),
        context.get("fit_laps", []),
        context.get("km_splits", []),
    )

    return {
        "fit_file": str(original_fit),
        "records_file": str(records_csv),
        "records_parquet_file": str(records_parquet),
        "running_dynamics_file": str(running_dynamics_file),
        "gps_file": str(gps_file),
        "events_file": str(events_file),
        "device_info_file": str(device_info_file),
        "developer_fields_file": str(developer_fields_file),
        "charts_file": str(charts_path) if charts_path else None,
    }


def export_activity_html(
    activity_dir: Path | str,
    context: dict[str, Any],
    charts_path: Path | str | None = None,
) -> dict[str, str | None]:
    """Export a human-readable HTML report for one activity."""

    output = Path(activity_dir)
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "index.html"
    summary = context.get("summary", {})
    title = str(summary.get("activity_name") or context.get("activity_id") or "Activity")
    charts_file = Path(charts_path).name if charts_path else None
    charts_section = (
        f'<section><h2>Charts</h2><p><a href="{escape(charts_file)}">Open full chart</a></p>'
        f'<iframe src="{escape(charts_file)}" title="Activity charts"></iframe></section>'
        if charts_file
        else ""
    )

    html = _html_page(
        title=f"garmin-ai activity {context.get('activity_id') or ''}",
        body=(
            f"<header><h1>{escape(title)}</h1>"
            f"<p>{escape(str(context.get('date') or ''))} "
            f"Activity {escape(str(context.get('activity_id') or ''))}</p></header>"
            "<main>"
            f"{_summary_cards(summary)}"
            f"{charts_section}"
            f"<section><h2>Summary</h2>{_mapping_table(summary)}</section>"
            f"<section><h2>Km Splits</h2>{_rows_table(context.get('km_splits', []), _KM_SPLIT_COLUMNS)}</section>"
            f"<section><h2>FIT Laps</h2>{_rows_table(context.get('fit_laps', []), _FIT_LAP_COLUMNS)}</section>"
            f"<section><h2>Connect Splits</h2>{_rows_table(context.get('connect_splits', []), _CONNECT_SPLIT_COLUMNS)}</section>"
            f"<section><h2>Day Metrics</h2>{_mapping_table(context.get('day_metrics', {}), exclude_keys={'sleep'})}</section>"
            f"{_sleep_section(context.get('day_metrics', {}).get('sleep'))}"
            f"{_data_quality_section(context.get('data_quality', {}))}"
            "</main>"
        ),
    )
    report_path.write_text(html, encoding="utf-8")
    return {"html_file": str(report_path), "charts_file": str(charts_path) if charts_path else None}


def compact_activity_context(context: dict[str, Any]) -> dict[str, Any]:
    """Return the small per-activity payload used by compact exports."""

    compact = {
        "activity_id": context.get("activity_id"),
        "date": context.get("date"),
        "summary": context.get("summary", {}),
        "connect_splits": context.get("connect_splits", []),
    }
    data_quality = context.get("data_quality")
    if data_quality:
        compact["data_quality"] = data_quality
    return compact


def compact_base_context(context: dict[str, Any]) -> dict[str, Any]:
    """Return the small top-level payload used by compact exports."""

    return {
        "ok": context.get("ok"),
        "mode": context.get("mode"),
        "export_dir": context.get("export_dir"),
        "export_archive": context.get("export_archive"),
        "sleep_days": context.get("sleep_days"),
        "generated_at": context.get("generated_at"),
        "profile": context.get("profile", {}),
        "current_metrics": context.get("current_metrics", {}),
        "recent_runs": [compact_activity_context(run) for run in context.get("recent_runs", [])],
        "data_quality": context.get("data_quality", {}),
    }


def export_compact_json(output_dir: Path | str, context: dict[str, Any]) -> Path:
    """Export compact JSON files for all activities."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    compact = compact_base_context(context)
    write_json(output / "base_context.json", compact)
    write_json(output / "recent_runs.json", compact.get("recent_runs", []))
    for run in compact.get("recent_runs", []):
        activity_dir = output / str(run.get("activity_id") or "")
        activity_dir.mkdir(parents=True, exist_ok=True)
        write_json(activity_dir / "context.json", run)
        write_json(activity_dir / "summary.json", run.get("summary", {}))
        write_json(activity_dir / "connect_splits.json", run.get("connect_splits", []))
    return output / "base_context.json"


def export_compact_activity_html(activity_dir: Path | str, context: dict[str, Any]) -> dict[str, str]:
    """Export a compact per-activity HTML report."""

    output = Path(activity_dir)
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "index.html"
    summary = context.get("summary", {})
    title = str(summary.get("activity_name") or context.get("activity_id") or "Activity")
    html = _html_page(
        title=f"garmin-ai compact activity {context.get('activity_id') or ''}",
        body=(
            f"<header><h1>{escape(title)}</h1>"
            f"<p>{escape(str(context.get('date') or ''))} "
            f"Activity {escape(str(context.get('activity_id') or ''))}</p></header>"
            "<main>"
            f"{_summary_cards(summary)}"
            f"<section><h2>Summary</h2>{_mapping_table(summary)}</section>"
            f"<section><h2>Connect Splits</h2>{_rows_table(context.get('connect_splits', []), _CONNECT_SPLIT_COLUMNS)}</section>"
            "</main>"
        ),
    )
    report_path.write_text(html, encoding="utf-8")
    return {"html_file": str(report_path)}


def export_html_index(output_dir: Path | str, context: dict[str, Any]) -> Path:
    """Export a human-readable HTML index for all activities."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    index_path = output / "index.html"
    rows = []
    for run in context.get("recent_runs", []):
        activity_id = str(run.get("activity_id") or "")
        summary = run.get("summary", {})
        report_link = f"{activity_id}/index.html"
        charts_link = f"{activity_id}/charts.html"
        row = {
            "date": run.get("date"),
            "activity": summary.get("activity_name") or activity_id,
            "distance_km": summary.get("distance_km"),
            "duration": summary.get("duration_seconds"),
            "pace": summary.get("avg_pace_sec_per_km"),
            "avg_hr": summary.get("avg_hr"),
            "avg_power_w": summary.get("avg_power_w"),
            "charts": f'<a href="{escape(charts_link)}">Charts</a>',
        }
        if context.get("mode") in {"html", "full"}:
            row["report"] = f'<a href="{escape(report_link)}">Report</a>'
        rows.append(row)

    html = _html_page(
        title="garmin-ai export",
        body=(
            "<header><h1>garmin-ai export</h1>"
            f"<p>Mode: {escape(str(context.get('mode') or ''))} "
            f"Generated: {escape(str(context.get('generated_at') or ''))}</p></header>"
            "<main>"
            f"<section><h2>Current Metrics</h2>{_mapping_table(context.get('current_metrics', {}), exclude_keys={'sleep'})}</section>"
            f"{_sleep_section(context.get('current_metrics', {}).get('sleep'))}"
            f"<section><h2>Recent Runs</h2>{_rows_table(rows, _INDEX_COLUMNS, raw_html_columns={'report', 'charts'})}</section>"
            f"{_data_quality_section(context.get('data_quality', {}))}"
            "</main>"
        ),
    )
    index_path.write_text(html, encoding="utf-8")
    return index_path


def export_compact_html_index(output_dir: Path | str, context: dict[str, Any]) -> Path:
    """Export a compact HTML index without the sleep trend chart."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    index_path = output / "index.html"
    rows = []
    for run in context.get("recent_runs", []):
        activity_id = str(run.get("activity_id") or "")
        summary = run.get("summary", {})
        report_link = f"{activity_id}/index.html"
        rows.append(
            {
                "date": run.get("date"),
                "activity": summary.get("activity_name") or activity_id,
                "distance_km": summary.get("distance_km"),
                "duration": summary.get("duration_seconds"),
                "pace": summary.get("avg_pace_sec_per_km"),
                "avg_hr": summary.get("avg_hr"),
                "avg_power_w": summary.get("avg_power_w"),
                "report": f'<a href="{escape(report_link)}">Report</a>',
            }
        )

    html = _html_page(
        title="garmin-ai compact export",
        body=(
            "<header><h1>garmin-ai compact export</h1>"
            f"<p>Mode: {escape(str(context.get('mode') or ''))} "
            f"Generated: {escape(str(context.get('generated_at') or ''))}</p></header>"
            "<main>"
            f"<section><h2>Current Metrics</h2>{_mapping_table(context.get('current_metrics', {}), exclude_keys={'sleep'})}</section>"
            f"{_sleep_section(context.get('current_metrics', {}).get('sleep'), include_chart=False)}"
            f"<section><h2>Recent Runs</h2>{_rows_table(rows, _COMPACT_INDEX_COLUMNS, raw_html_columns={'report'})}</section>"
            f"{_data_quality_section(context.get('data_quality', {}))}"
            "</main>"
        ),
    )
    index_path.write_text(html, encoding="utf-8")
    return index_path


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(json_safe(rows)).to_csv(path, index=False)
    return path


def _write_parquet(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(json_safe(rows)).to_parquet(path, index=False)
    return path


_INDEX_COLUMNS = ["date", "activity", "distance_km", "duration", "pace", "avg_hr", "avg_power_w", "report", "charts"]
_COMPACT_INDEX_COLUMNS = ["date", "activity", "distance_km", "duration", "pace", "avg_hr", "avg_power_w", "report"]
_KM_SPLIT_COLUMNS = [
    "km_index",
    "distance_m",
    "duration_seconds",
    "pace_sec_per_km",
    "avg_hr",
    "avg_cadence_spm",
    "avg_power_w",
    "elevation_gain_m",
]
_FIT_LAP_COLUMNS = [
    "lap_index",
    "distance_m",
    "duration_seconds",
    "avg_pace_sec_per_km",
    "avg_hr",
    "avg_cadence_spm",
    "avg_power_w",
    "lap_trigger",
]
_CONNECT_SPLIT_COLUMNS = [
    "source",
    "split_index",
    "distance_m",
    "duration_seconds",
    "avg_pace_sec_per_km",
    "avg_hr",
    "max_hr",
    "avg_cadence_spm",
    "avg_power_w",
]


def _html_page(*, title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #17202a;
      --muted: #667085;
      --line: #d9dee7;
      --accent: #146c5f;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }}
    header, main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 24px;
    }}
    header {{
      padding-top: 32px;
      padding-bottom: 8px;
    }}
    h1, h2 {{
      margin: 0 0 8px;
      letter-spacing: 0;
    }}
    h1 {{
      font-size: 32px;
    }}
    h2 {{
      font-size: 20px;
    }}
    p {{
      margin: 0 0 16px;
      color: var(--muted);
    }}
    section {{
      margin: 16px 0;
      padding: 18px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow-x: auto;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 12px;
      margin: 16px 0;
    }}
    .card {{
      padding: 14px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .label {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
    }}
    .value {{
      margin-top: 4px;
      font-size: 22px;
      font-weight: 650;
    }}
    .sleep-summary .cards {{
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      margin-bottom: 18px;
    }}
    .sleep-summary .value {{
      font-size: 20px;
    }}
    .sleep-chart {{
      width: 100%;
      min-width: 720px;
      height: auto;
      margin: 4px 0 18px;
      display: block;
    }}
    .sleep-table {{
      font-size: 13px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    th, td {{
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      white-space: nowrap;
    }}
    th {{
      color: var(--muted);
      font-weight: 600;
      background: #fbfcfe;
    }}
    th.num, td.num {{
      text-align: right;
    }}
    a {{
      color: var(--accent);
      font-weight: 600;
      text-decoration: none;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    iframe {{
      width: 100%;
      min-height: 900px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #ffffff;
    }}
    @media (max-width: 720px) {{
      header, main {{
        padding: 16px;
      }}
      h1 {{
        font-size: 26px;
      }}
      section {{
        padding: 12px;
      }}
      iframe {{
        min-height: 680px;
      }}
    }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""


def _summary_cards(summary: dict[str, Any]) -> str:
    cards = [
        ("Distance", _format_cell("distance_km", summary.get("distance_km"))),
        ("Duration", _format_duration(summary.get("duration_seconds"))),
        ("Pace", _format_pace(summary.get("avg_pace_sec_per_km"))),
        ("Avg HR", _format_cell("avg_hr", summary.get("avg_hr"))),
        ("Avg Power", _format_cell("avg_power_w", summary.get("avg_power_w"))),
        ("Training Load", _format_value(summary.get("training_load"))),
    ]
    return "<div class='cards'>" + "".join(
        f"<div class='card'><div class='label'>{escape(label)}</div><div class='value'>{escape(value)}</div></div>"
        for label, value in cards
    ) + "</div>"


def _mapping_table(mapping: Any, *, exclude_keys: set[str] | None = None) -> str:
    if not isinstance(mapping, dict) or not mapping:
        return "<p>No data</p>"
    exclude_keys = exclude_keys or set()
    rows = [
        {"field": _label_for(key), "value": _format_cell(key, value)}
        for key, value in mapping.items()
        if key not in exclude_keys and not _is_empty(value)
    ]
    return _rows_table(rows, ["field", "value"])


def _sleep_section(sleep: Any, *, include_chart: bool = True) -> str:
    items = _sleep_items(sleep)
    if not items:
        return "<section class='sleep-summary'><h2>Sleep Summary</h2><p>No sleep data available.</p></section>"

    summary = sleep.get("summary") if isinstance(sleep, dict) and isinstance(sleep.get("summary"), dict) else _summarize_sleep_items(items)
    days = sleep.get("days") if isinstance(sleep, dict) else None
    days = days if days is not None else len(items)
    cards = [
        ("days", _format_sleep_count(days)),
        ("valid_days", _format_sleep_count(summary.get("valid_days"))),
        ("missing_days", _format_sleep_count(summary.get("missing_days"))),
        ("avg_sleep_score", _format_sleep_number(summary.get("avg_sleep_score"))),
        ("avg_total_sleep_hours", _format_sleep_hours(summary.get("avg_total_sleep_hours"))),
        ("avg_deep_sleep_hours", _format_sleep_hours(summary.get("avg_deep_sleep_hours"))),
        ("avg_light_sleep_hours", _format_sleep_hours(summary.get("avg_light_sleep_hours"))),
        ("avg_rem_sleep_hours", _format_sleep_hours(summary.get("avg_rem_sleep_hours"))),
        ("avg_awake_minutes", _format_sleep_minutes(summary.get("avg_awake_minutes"))),
    ]
    cards_html = "".join(
        "<div class='card'>"
        f"<div class='label'>{escape(_label_for(label))}</div>"
        f"<div class='value'>{escape(value)}</div>"
        "</div>"
        for label, value in cards
    )
    return (
        "<section class='sleep-summary'><h2>Sleep Summary</h2>"
        f"<div class='cards'>{cards_html}</div>"
        f"{_sleep_trend_chart(items) if include_chart else ''}"
        f"{_sleep_table(items)}"
        "</section>"
    )


def _sleep_items(sleep: Any) -> list[dict[str, Any]]:
    if not isinstance(sleep, dict):
        return []
    items = sleep.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    if any(key in sleep for key in _SLEEP_DAY_COLUMNS):
        return [sleep]
    return []


def _sleep_table(items: list[dict[str, Any]]) -> str:
    head = "".join(
        f"<th class='{_sleep_column_class(column)}'>{escape(_label_for(column))}</th>" for column in _SLEEP_TABLE_COLUMNS
    )
    rows = []
    for item in items:
        values = {
            "date": _sleep_text(item.get("date")),
            "sleep_score": _format_sleep_number(item.get("sleep_score")),
            "total_sleep_seconds": format_duration(item.get("total_sleep_seconds")),
            "deep_sleep_seconds": format_duration(item.get("deep_sleep_seconds")),
            "light_sleep_seconds": format_duration(item.get("light_sleep_seconds")),
            "rem_sleep_seconds": format_duration(item.get("rem_sleep_seconds")),
            "awake_seconds": format_duration(item.get("awake_seconds")),
            "sleep_start": format_time(item.get("sleep_start")),
            "sleep_end": format_time(item.get("sleep_end")),
            "status": _sleep_status(item),
        }
        cells = "".join(
            f"<td class='{_sleep_column_class(column)}'>{escape(values[column])}</td>" for column in _SLEEP_TABLE_COLUMNS
        )
        rows.append(f"<tr>{cells}</tr>")
    return f"<table class='sleep-table'><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _sleep_trend_chart(items: list[dict[str, Any]]) -> str:
    points = []
    for item in items:
        total_seconds = _to_float(item.get("total_sleep_seconds"))
        score = _to_float(item.get("sleep_score"))
        points.append(
            {
                "date": str(item.get("date") or ""),
                "hours": total_seconds / 3600 if total_seconds is not None else None,
                "score": score,
            }
        )
    if not any(point["hours"] is not None for point in points):
        return ""

    width = 900
    height = 280
    left = 54
    right = 54
    top = 34
    bottom = 52
    chart_width = width - left - right
    chart_height = height - top - bottom
    max_hours = max([point["hours"] or 0 for point in points] + [8])
    step = chart_width / max(len(points), 1)
    bar_width = min(44, step * 0.58)
    bars = []
    labels = []
    line_points = []
    for index, point in enumerate(points):
        center_x = left + step * index + step / 2
        hours = point["hours"] or 0
        bar_height = 0 if max_hours <= 0 else hours / max_hours * chart_height
        x = center_x - bar_width / 2
        y = top + chart_height - bar_height
        bars.append(
            f"<rect x='{x:.1f}' y='{y:.1f}' width='{bar_width:.1f}' height='{bar_height:.1f}' "
            "fill='#146c5f' opacity='0.82'><title>"
            f"{escape(point['date'])}: {_format_sleep_hours(hours)}"
            "</title></rect>"
        )
        labels.append(
            f"<text x='{center_x:.1f}' y='{height - 24}' text-anchor='middle' font-size='11' fill='#667085'>"
            f"{escape(_short_date(point['date']))}</text>"
        )
        if point["score"] is not None:
            score_y = top + chart_height - max(0, min(point["score"], 100)) / 100 * chart_height
            line_points.append((center_x, score_y))

    line = ""
    if line_points:
        path = " ".join(("M" if index == 0 else "L") + f"{x:.1f},{y:.1f}" for index, (x, y) in enumerate(line_points))
        dots = "".join(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='3.5' fill='#b42318'></circle>" for x, y in line_points)
        line = f"<path d='{path}' fill='none' stroke='#b42318' stroke-width='2.5'></path>{dots}"

    grid = []
    for tick in range(0, 5):
        y = top + chart_height - chart_height * tick / 4
        hours_label = max_hours * tick / 4
        score_label = 100 * tick / 4
        grid.append(f"<line x1='{left}' y1='{y:.1f}' x2='{width - right}' y2='{y:.1f}' stroke='#d9dee7'></line>")
        grid.append(
            f"<text x='{left - 8}' y='{y + 4:.1f}' text-anchor='end' font-size='11' fill='#667085'>"
            f"{hours_label:.0f}h</text>"
        )
        grid.append(
            f"<text x='{width - right + 8}' y='{y + 4:.1f}' text-anchor='start' font-size='11' fill='#667085'>"
            f"{score_label:.0f}</text>"
        )

    return (
        "<svg class='sleep-chart' viewBox='0 0 900 280' role='img' aria-label='Sleep trend'>"
        "<text x='54' y='20' font-size='16' font-weight='650' fill='#17202a'>Sleep trend</text>"
        "<text x='54' y='270' font-size='12' fill='#667085'>Sleep hours</text>"
        "<text x='846' y='270' text-anchor='end' font-size='12' fill='#667085'>Sleep score</text>"
        f"{''.join(grid)}"
        f"{''.join(bars)}"
        f"{line}"
        f"{''.join(labels)}"
        "</svg>"
    )


def _summarize_sleep_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    valid_items = [item for item in items if not item.get("missing")]
    return {
        "valid_days": len(valid_items),
        "missing_days": len(items) - len(valid_items),
        "avg_sleep_score": _avg_value(item.get("sleep_score") for item in items),
        "avg_total_sleep_hours": _avg_seconds_as_hours(item.get("total_sleep_seconds") for item in items),
        "avg_deep_sleep_hours": _avg_seconds_as_hours(item.get("deep_sleep_seconds") for item in items),
        "avg_light_sleep_hours": _avg_seconds_as_hours(item.get("light_sleep_seconds") for item in items),
        "avg_rem_sleep_hours": _avg_seconds_as_hours(item.get("rem_sleep_seconds") for item in items),
        "avg_awake_minutes": _avg_seconds_as_minutes(item.get("awake_seconds") for item in items),
    }


def _avg_value(values: Any) -> float | None:
    numbers = [_to_float(value) for value in values]
    numbers = [number for number in numbers if number is not None]
    return round(sum(numbers) / len(numbers), 2) if numbers else None


def _avg_seconds_as_hours(values: Any) -> float | None:
    numbers = [_to_float(value) for value in values]
    numbers = [number / 3600 for number in numbers if number is not None]
    return round(sum(numbers) / len(numbers), 2) if numbers else None


def _avg_seconds_as_minutes(values: Any) -> float | None:
    numbers = [_to_float(value) for value in values]
    numbers = [number / 60 for number in numbers if number is not None]
    return round(sum(numbers) / len(numbers), 2) if numbers else None


def _rows_table(
    rows: Any,
    columns: list[str],
    *,
    raw_html_columns: set[str] | None = None,
    limit: int = 200,
) -> str:
    if not isinstance(rows, list) or not rows:
        return "<p>No data</p>"
    visible_columns = [column for column in columns if any(isinstance(row, dict) and column in row for row in rows)]
    if not visible_columns:
        return "<p>No data</p>"
    raw_html_columns = raw_html_columns or set()
    head = "".join(f"<th>{escape(_label_for(column))}</th>" for column in visible_columns)
    body_rows = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        cells = []
        for column in visible_columns:
            value = _format_cell(column, row.get(column))
            cells.append(f"<td>{value if column in raw_html_columns else escape(value)}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    extra = f"<p>Showing first {limit} rows.</p>" if len(rows) > limit else ""
    return f"{extra}<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def _data_quality_section(data_quality: Any) -> str:
    if not data_quality:
        return ""
    text = json.dumps(json_safe(data_quality), ensure_ascii=False, indent=2)
    return f"<section><h2>Data Quality</h2><pre>{escape(text)}</pre></section>"


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if isinstance(value, (dict, list)):
        return json.dumps(json_safe(value), ensure_ascii=False)
    return str(value)


def _format_cell(column: str, value: Any) -> str:
    if _is_empty(value):
        return ""
    if column == "value":
        return _format_value(value)
    if column.endswith("_pace_sec_per_km") or column == "pace_sec_per_km" or column == "pace":
        return _format_pace(value)
    if column.endswith("duration_seconds") or column in {"duration_seconds", "moving_duration_seconds", "elapsed_seconds", "duration"}:
        return _format_duration(value)
    if column == "distance_m" or column in {"start_distance_m", "end_distance_m"}:
        return _format_number(_to_float(value) / 1000 if _to_float(value) is not None else None, " km")
    if column == "distance_km":
        return _format_number(value, " km")
    if column in {
        "avg_hr",
        "max_hr",
        "min_hr",
        "heart_rate",
        "max_heart_rate",
        "daily_max_heart_rate",
        "resting_heart_rate",
        "resting_heart_rate_7d_avg",
    }:
        return _format_number(value, " bpm", decimals=0)
    if column.endswith("_cadence_spm") or column == "cadence_spm":
        return _format_number(value, " spm", decimals=0)
    if column.endswith("_power_w") or column == "power_w" or column == "normalized_power_w":
        return _format_number(value, " W", decimals=0)
    if column.endswith("_altitude_m") or column in {"altitude_m", "elevation_gain_m", "elevation_loss_m"}:
        return _format_number(value, " m")
    if column.endswith("_mm") or column == "vertical_oscillation_mm":
        return _format_number(value, " mm")
    if column.endswith("_ms") or column == "ground_contact_time_ms":
        return _format_number(value, " ms", decimals=0)
    if column.endswith("_percent") or column in {"avg_vertical_ratio_percent", "vertical_ratio_percent"}:
        return _format_number(value, "%")
    if column.endswith("_c") or column == "temperature_c":
        return _format_number(value, " C")
    if column.endswith("_mps") or column == "speed_mps":
        return _format_number(value, " m/s")
    if column.endswith("_hours") or column == "recovery_time_hours":
        return _format_number(value, " h")
    return _format_value(value)


def _format_number(value: Any, suffix: str = "", *, decimals: int = 2) -> str:
    number = _to_float(value)
    if number is None:
        return ""
    text = f"{number:.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text}{suffix}"


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_duration(value: Any) -> str:
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return ""
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _format_pace(value: Any) -> str:
    try:
        seconds = int(round(float(value)))
    except (TypeError, ValueError):
        return ""
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}:{secs:02d}/km"


def format_duration(seconds: Any) -> str:
    """Format sleep durations as compact hours and minutes."""

    number = _to_float(seconds)
    if number is None or number < 0:
        return "-"
    total_minutes = int(round(number / 60))
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m"


def format_time(value: Any) -> str:
    """Format ISO-like datetimes as HH:mm."""

    if value is None or value == "":
        return "-"
    text = str(value)
    if text.isdigit():
        timestamp = int(text)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%H:%M")
    if "T" in text:
        time_part = text.split("T", 1)[1]
    elif " " in text:
        time_part = text.split(" ", 1)[1]
    else:
        time_part = text
    if len(time_part) >= 5 and time_part[2] == ":":
        return time_part[:5]
    return "-"


def _format_sleep_number(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "-"
    return f"{number:.1f}".rstrip("0").rstrip(".")


def _format_sleep_count(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "-"
    return str(int(number)) if number.is_integer() else _format_sleep_number(number)


def _format_sleep_hours(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "-"
    return format_duration(number * 3600)


def _format_sleep_minutes(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "-"
    return format_duration(number * 60)


def _sleep_text(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return str(value)


def _sleep_status(item: dict[str, Any]) -> str:
    if item.get("missing") is True:
        return "Missing"
    score = _to_float(item.get("sleep_score"))
    if score is None:
        return "Unknown"
    if score >= 80:
        return "Good"
    if score >= 70:
        return "Fair"
    return "Low"


def _sleep_column_class(column: str) -> str:
    return "num" if column in _SLEEP_NUMERIC_COLUMNS else ""


def _short_date(value: str) -> str:
    return value[5:] if len(value) >= 10 else value


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _label_for(column: str) -> str:
    return _COLUMN_LABELS.get(column, column.replace("_", " ").title())


_COLUMN_LABELS = {
    "field": "Field",
    "value": "Value",
    "date": "Date",
    "activity": "Activity",
    "report": "Report",
    "charts": "Charts",
    "activity_id": "Activity ID",
    "activity_name": "Activity",
    "activity_type": "Type",
    "start_time_local": "Start Time",
    "distance_m": "Distance",
    "distance_km": "Distance",
    "duration": "Duration",
    "duration_seconds": "Duration",
    "moving_duration_seconds": "Moving Time",
    "elapsed_seconds": "Elapsed Time",
    "pace": "Pace",
    "pace_sec_per_km": "Pace",
    "avg_pace_sec_per_km": "Avg Pace",
    "best_pace_sec_per_km": "Best Pace",
    "avg_hr": "Avg HR",
    "max_hr": "Max HR",
    "max_heart_rate": "Max HR",
    "min_hr": "Min HR",
    "avg_cadence_spm": "Avg Cadence",
    "max_cadence_spm": "Max Cadence",
    "avg_power_w": "Avg Power",
    "max_power_w": "Max Power",
    "normalized_power_w": "Normalized Power",
    "elevation_gain_m": "Elevation Gain",
    "elevation_loss_m": "Elevation Loss",
    "altitude_m": "Altitude",
    "min_altitude_m": "Min Altitude",
    "max_altitude_m": "Max Altitude",
    "temperature_c": "Temperature",
    "temperature_avg_c": "Avg Temperature",
    "temperature_min_c": "Min Temperature",
    "temperature_max_c": "Max Temperature",
    "km_index": "Km",
    "lap_index": "Lap",
    "split_index": "Split",
    "source": "Source",
    "lap_trigger": "Trigger",
    "training_load": "Training Load",
    "training_effect_aerobic": "Aerobic TE",
    "training_effect_anaerobic": "Anaerobic TE",
    "recovery_time_hours": "Recovery Time",
    "vo2max": "VO2max",
    "vo2max_precise": "VO2max Precise",
    "avg_stride_length_m": "Avg Stride",
    "avg_vertical_oscillation_mm": "Avg Vertical Oscillation",
    "avg_ground_contact_time_ms": "Avg Ground Contact",
    "avg_ground_contact_balance_left_percent": "Avg GCT Balance Left",
    "avg_vertical_ratio_percent": "Avg Vertical Ratio",
    "daily_max_heart_rate": "Daily Max HR",
    "resting_heart_rate": "Resting HR",
    "resting_heart_rate_7d_avg": "Resting HR 7d Avg",
    "hrv": "HRV",
    "hrv_7d_avg": "HRV 7d Avg",
    "weight_kg": "Weight",
    "days": "Days",
    "valid_days": "Valid Days",
    "missing_days": "Missing Days",
    "avg_sleep_score": "Avg Sleep Score",
    "avg_total_sleep_hours": "Avg Total Sleep",
    "avg_deep_sleep_hours": "Avg Deep Sleep",
    "avg_light_sleep_hours": "Avg Light Sleep",
    "avg_rem_sleep_hours": "Avg REM Sleep",
    "avg_awake_minutes": "Avg Awake",
    "sleep_score": "Score",
    "total_sleep_seconds": "Total",
    "deep_sleep_seconds": "Deep",
    "light_sleep_seconds": "Light",
    "rem_sleep_seconds": "REM",
    "awake_seconds": "Awake",
    "sleep_start": "Start",
    "sleep_end": "End",
    "status": "Status",
}

_SLEEP_DAY_COLUMNS = {
    "date",
    "sleep_score",
    "total_sleep_seconds",
    "deep_sleep_seconds",
    "light_sleep_seconds",
    "rem_sleep_seconds",
    "awake_seconds",
    "sleep_start",
    "sleep_end",
    "missing",
}
_SLEEP_TABLE_COLUMNS = [
    "date",
    "sleep_score",
    "total_sleep_seconds",
    "deep_sleep_seconds",
    "light_sleep_seconds",
    "rem_sleep_seconds",
    "awake_seconds",
    "sleep_start",
    "sleep_end",
    "status",
]
_SLEEP_NUMERIC_COLUMNS = {
    "sleep_score",
    "total_sleep_seconds",
    "deep_sleep_seconds",
    "light_sleep_seconds",
    "rem_sleep_seconds",
    "awake_seconds",
}
