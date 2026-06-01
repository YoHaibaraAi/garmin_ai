"""Static Plotly chart generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def build_activity_charts(
    activity_dir: Path | str,
    records: list[dict[str, Any]],
    km_splits: list[dict[str, Any]],
    running_dynamics: list[dict[str, Any]],
    gps: list[dict[str, Any]],
    chart_x: str = "distance",
) -> Path:
    """Build a self-contained HTML chart report for one activity."""

    output = Path(activity_dir)
    output.mkdir(parents=True, exist_ok=True)
    charts_path = output / "charts.html"
    records_df = pd.DataFrame(records)
    if "distance_m" in records_df.columns:
        records_df["distance_km"] = pd.to_numeric(records_df["distance_m"], errors="coerce") / 1000
    if "pace_sec_per_km" in records_df.columns:
        records_df["pace_min_per_km"] = pd.to_numeric(records_df["pace_sec_per_km"], errors="coerce") / 60
    km_df = pd.DataFrame(km_splits)
    dynamics_df = pd.DataFrame(running_dynamics)
    if "distance_m" in dynamics_df.columns:
        dynamics_df["distance_km"] = pd.to_numeric(dynamics_df["distance_m"], errors="coerce") / 1000
    gps_df = pd.DataFrame(gps)

    include_dynamics = not dynamics_df.empty
    rows = 4
    specs = [[{"secondary_y": True}], [{"secondary_y": True}], [{}]]
    titles = ["Heart Rate + Pace", "Cadence + Power", "Altitude", "Km Splits"]
    if include_dynamics:
        rows += 1
        specs.append([{"secondary_y": True}])
        titles.insert(-1, "Running Dynamics")
    if not gps_df.empty:
        rows += 1
        specs.insert(3, [{}])
        titles.insert(3, "GPS Track")
    specs.append([{"type": "table"}])

    fig = make_subplots(rows=rows, cols=1, specs=specs, subplot_titles=titles, vertical_spacing=0.08)
    x, x_label = _select_x_axis(records_df, chart_x)

    if not records_df.empty:
        fig.add_trace(go.Scatter(x=x, y=records_df.get("heart_rate"), name="Heart rate"), row=1, col=1)
        fig.add_trace(
            go.Scatter(x=x, y=records_df.get("pace_min_per_km"), name="Pace min/km"),
            row=1,
            col=1,
            secondary_y=True,
        )
        fig.add_trace(go.Scatter(x=x, y=records_df.get("cadence_spm"), name="Cadence"), row=2, col=1)
        fig.add_trace(go.Scatter(x=x, y=records_df.get("power_w"), name="Power"), row=2, col=1, secondary_y=True)
        fig.add_trace(go.Scatter(x=x, y=records_df.get("altitude_m"), name="Altitude"), row=3, col=1)
        fig.update_yaxes(title_text="Heart rate (bpm)", row=1, col=1)
        fig.update_yaxes(title_text="Pace (min/km)", row=1, col=1, secondary_y=True)
        fig.update_yaxes(title_text="Cadence (spm)", row=2, col=1)
        fig.update_yaxes(title_text="Power (W)", row=2, col=1, secondary_y=True)
        fig.update_yaxes(title_text="Altitude (m)", row=3, col=1)

    next_row = 4
    if not gps_df.empty:
        fig.add_trace(go.Scatter(x=gps_df.get("lon"), y=gps_df.get("lat"), mode="lines", name="GPS"), row=next_row, col=1)
        fig.update_xaxes(title_text="Longitude", row=next_row, col=1)
        fig.update_yaxes(title_text="Latitude", row=next_row, col=1)
        next_row += 1

    if include_dynamics:
        dynamics_x, dynamics_x_label = _select_x_axis(dynamics_df, chart_x)
        if "vertical_oscillation_mm" in dynamics_df.columns:
            fig.add_trace(
                go.Scatter(x=dynamics_x, y=dynamics_df.get("vertical_oscillation_mm"), name="Vertical oscillation mm"),
                row=next_row,
                col=1,
            )
        if "ground_contact_time_ms" in dynamics_df.columns:
            fig.add_trace(
                go.Scatter(x=dynamics_x, y=dynamics_df.get("ground_contact_time_ms"), name="Ground contact ms"),
                row=next_row,
                col=1,
                secondary_y=True,
            )
        if "stride_length_m" in dynamics_df.columns:
            fig.add_trace(
                go.Scatter(x=dynamics_x, y=dynamics_df.get("stride_length_m"), name="Stride length m"),
                row=next_row,
                col=1,
            )
        if "vertical_ratio_percent" in dynamics_df.columns:
            fig.add_trace(
                go.Scatter(x=dynamics_x, y=dynamics_df.get("vertical_ratio_percent"), name="Vertical ratio %"),
                row=next_row,
                col=1,
                secondary_y=True,
            )
        fig.update_xaxes(title_text=dynamics_x_label, row=next_row, col=1)
        next_row += 1

    if not km_df.empty:
        table_columns = [
            "km_index",
            "distance_m",
            "duration_seconds",
            "pace_sec_per_km",
            "avg_hr",
            "avg_cadence_spm",
            "avg_power_w",
        ]
        table_columns = [column for column in table_columns if column in km_df.columns]
        fig.add_trace(
            go.Table(
                header={"values": [_label_for(column) for column in table_columns]},
                cells={"values": [_format_table_column(column, km_df[column]) for column in table_columns]},
            ),
            row=next_row,
            col=1,
        )

    for row in (1, 2, 3):
        fig.update_xaxes(title_text=x_label, row=row, col=1)
    fig.update_layout(height=max(900, rows * 300), title_text="Garmin Activity Analysis", showlegend=True)
    fig.write_html(charts_path, include_plotlyjs="cdn", full_html=True)
    return charts_path


def _select_x_axis(df: pd.DataFrame, chart_x: str) -> tuple[Any, str]:
    chart_x = chart_x.lower()
    has_distance = "distance_km" in df.columns and df["distance_km"].notna().any()
    has_time = "elapsed_seconds" in df.columns and df["elapsed_seconds"].notna().any()

    if chart_x == "time":
        if has_time:
            return df["elapsed_seconds"], "Time (s)"
        if has_distance:
            return df["distance_km"], "Distance (km)"
    else:
        if has_distance:
            return df["distance_km"], "Distance (km)"
        if has_time:
            return df["elapsed_seconds"], "Time (s)"

    return df.index if not df.empty else [], "Record index"


def _format_table_column(column: str, values: pd.Series) -> list[str]:
    return [_format_table_value(column, value) for value in values]


def _format_table_value(column: str, value: Any) -> str:
    if pd.isna(value):
        return ""
    if column == "distance_m":
        return _format_number(float(value) / 1000, " km")
    if column == "duration_seconds":
        return _format_duration(value)
    if column == "pace_sec_per_km":
        return _format_pace(value)
    if column in {"avg_hr", "avg_cadence_spm", "avg_power_w"}:
        suffix = {"avg_hr": " bpm", "avg_cadence_spm": " spm", "avg_power_w": " W"}[column]
        return _format_number(value, suffix, decimals=0)
    return _format_number(value, "") if isinstance(value, float) else str(value)


def _format_number(value: Any, suffix: str = "", *, decimals: int = 2) -> str:
    number = float(value)
    text = f"{number:.{decimals}f}".rstrip("0").rstrip(".")
    return f"{text}{suffix}"


def _format_duration(value: Any) -> str:
    seconds = int(round(float(value)))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _format_pace(value: Any) -> str:
    seconds = int(round(float(value)))
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}:{secs:02d}/km"


def _label_for(column: str) -> str:
    return {
        "km_index": "Km",
        "distance_m": "Distance",
        "duration_seconds": "Duration",
        "pace_sec_per_km": "Pace",
        "avg_hr": "Avg HR",
        "avg_cadence_spm": "Avg Cadence",
        "avg_power_w": "Avg Power",
    }.get(column, column.replace("_", " ").title())
