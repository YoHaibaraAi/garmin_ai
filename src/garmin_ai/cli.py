"""Typer CLI entrypoint for garmin-ai."""

from __future__ import annotations

import json
import shutil
from enum import Enum
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from .auth import login_interactive
from . import garmin_client
from .chart_builder import build_activity_charts
from .config import CONFIG_PATH, load_config, set_config_value
from .errors import AuthRequiredError, FitDownloadError, FitParseError, GarminAIError
from .exporter import (
    compact_base_context,
    export_activity_basic,
    export_activity_full,
    export_activity_html,
    export_base_context,
    export_compact_activity_html,
    export_compact_html_index,
    export_compact_json,
    export_html_index,
    write_json,
)
from .fit_downloader import download_or_get_cached_fit
from .fit_parser import parse_fit_file
from .metrics_collector import collect_current_metrics, collect_day_metrics, collect_profile
from .models import normalize_activity_summary, normalize_connect_split
from .split_calculator import calculate_km_splits
from .utils import EXPORTS_DIR, FIT_DIR, TOKEN_DIR, json_safe, now_iso


app = typer.Typer(help="Local Garmin Connect CLI for AI-friendly analysis.")
config_app = typer.Typer(help="Manage local garmin-ai config.")
app.add_typer(config_app, name="config")
console = Console()


class ExportMode(str, Enum):
    BASIC = "basic"
    FULL = "full"
    HTML = "html"
    COMPACT = "compact"


class ChartX(str, Enum):
    DISTANCE = "distance"
    TIME = "time"


class CompactFormat(str, Enum):
    HTML = "html"
    JSON = "json"


@app.command()
def auth() -> None:
    """Login to Garmin Connect and initialize the token store."""

    try:
        email = typer.prompt("Garmin email")
        password = typer.prompt("Garmin password", hide_input=True)
        login_interactive(email, password, TOKEN_DIR, prompt_mfa=lambda: typer.prompt("Garmin MFA code"))
        console.print("Garmin China token saved to ~/.garminconnect")
    except Exception as exc:  # noqa: BLE001
        _print_error("UNKNOWN_ERROR", str(exc), json_output=True)
        raise typer.Exit(code=1) from exc


@app.command()
def base(
    limit: int = typer.Option(1, "--limit", min=1, help="Number of recent running activities."),
    mode: ExportMode = typer.Option(
        ExportMode.BASIC,
        "--mode",
        case_sensitive=False,
        help="Export mode: basic, full, html, or compact.",
    ),
    full: bool = typer.Option(False, "--full/--no-full", help="Shortcut for --mode full."),
    compact_format: CompactFormat = typer.Option(
        CompactFormat.HTML,
        "--compact-format",
        case_sensitive=False,
        help="Compact mode output format: html or json.",
    ),
    chart_x: ChartX = typer.Option(
        ChartX.DISTANCE,
        "--chart-x",
        case_sensitive=False,
        help="Chart x-axis: distance or time.",
    ),
    sleep_days: int = typer.Option(7, "--sleep-days", min=1, help="Number of recent sleep days in current metrics."),
    output: Path | None = typer.Option(None, "--output", help="Output directory or JSON file path."),
    json_output: bool = typer.Option(True, "--json/--no-json", help="Print JSON output."),
    cache: bool = typer.Option(True, "--cache/--no-cache", help="Reuse cached FIT files."),
) -> None:
    """Build a local Garmin context for recent running activities."""

    try:
        client = _login_or_raise()
        export_mode = ExportMode.FULL.value if full else mode.value
        context = _build_base_context(
            client,
            limit=limit,
            mode=export_mode,
            output=output,
            cache=cache,
            chart_x=chart_x.value,
            sleep_days=sleep_days,
            compact_format=compact_format.value,
        )
        if output is not None:
            _write_requested_output(output, context, mode=export_mode, compact_format=compact_format.value)
        if json_output:
            payload = compact_base_context(context) if export_mode == ExportMode.COMPACT.value else context
            console.print_json(json.dumps(json_safe(payload), ensure_ascii=False))
        else:
            _print_human(context)
    except AuthRequiredError as exc:
        _print_error("AUTH_REQUIRED", "Garmin token missing or expired. Run: garmin-ai auth", json_output=True)
        raise typer.Exit(code=1) from exc
    except FitDownloadError as exc:
        _print_error("FIT_DOWNLOAD_ERROR", str(exc), json_output=True)
        raise typer.Exit(code=1) from exc
    except FitParseError as exc:
        _print_error("FIT_PARSE_ERROR", str(exc), json_output=True)
        raise typer.Exit(code=1) from exc
    except GarminAIError as exc:
        _print_error(exc.error_code, str(exc), json_output=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:  # noqa: BLE001
        _print_error("UNKNOWN_ERROR", str(exc), json_output=True)
        raise typer.Exit(code=1) from exc


@app.command("debug-metrics")
def debug_metrics(
    date: str = typer.Option(..., "--date", help="Date in YYYY-MM-DD format."),
    output: Path = typer.Option(..., "--output", help="JSON output path."),
) -> None:
    """Save raw Garmin metric API payloads for debugging."""

    try:
        client = _login_or_raise()
        payload = garmin_client.get_debug_metrics_raw(client, date)
        write_json(output, payload)
        console.print_json(json.dumps(json_safe({"ok": True, "output": str(output)}), ensure_ascii=False))
    except AuthRequiredError as exc:
        _print_error("AUTH_REQUIRED", "Garmin token missing or expired. Run: garmin-ai auth", json_output=True)
        raise typer.Exit(code=1) from exc
    except Exception as exc:  # noqa: BLE001
        _print_error("UNKNOWN_ERROR", str(exc), json_output=True)
        raise typer.Exit(code=1) from exc


@config_app.command("show")
def config_show() -> None:
    """Show local garmin-ai config."""

    console.print_json(json.dumps(json_safe({"config_path": CONFIG_PATH, "config": load_config()}), ensure_ascii=False))


@config_app.command("set")
def config_set(key: str = typer.Argument(...), value: str = typer.Argument(...)) -> None:
    """Set a local config value."""

    normalized_key = key.replace("-", "_")
    parsed: Any = value
    if normalized_key == "max_heart_rate":
        parsed_float = float(value)
        parsed = int(parsed_float) if parsed_float.is_integer() else parsed_float
    path = set_config_value(normalized_key, parsed)
    console.print_json(
        json.dumps(
            json_safe({"ok": True, "config_path": path, "key": normalized_key, "value": parsed}),
            ensure_ascii=False,
        )
    )


def _login_or_raise() -> Any:
    try:
        return garmin_client.login_with_token(TOKEN_DIR)
    except Exception as exc:  # noqa: BLE001
        raise AuthRequiredError("Garmin token missing or expired. Run: garmin-ai auth") from exc


def _build_base_context(
    client: Any,
    *,
    limit: int,
    mode: str,
    output: Path | None,
    cache: bool,
    chart_x: str,
    sleep_days: int,
    compact_format: str,
) -> dict[str, Any]:
    generated_at = now_iso()
    directory_output = _uses_directory_output(output, mode=mode, compact_format=compact_format)
    export_dir = _resolve_export_dir(output, generated_at) if directory_output else EXPORTS_DIR / "latest"
    profile = collect_profile(client)
    profile_quality = profile.pop("data_quality", {})
    current_metrics = collect_current_metrics(client, sleep_days=sleep_days)
    current_quality = current_metrics.pop("data_quality", {})
    current_metrics = _include_profile_max_heart_rate(current_metrics, profile)

    activities_result = garmin_client.get_recent_running_activities(client, limit)
    activities = activities_result.get("activities", [])
    data_quality: dict[str, Any] = {
        "profile": profile_quality,
        "current_metrics": current_quality,
        **activities_result.get("data_quality", {}),
    }

    recent_runs = []
    for activity in activities:
        recent_runs.append(
            _build_activity_context(
                client,
                activity,
                mode=mode,
                export_dir=export_dir,
                cache=cache,
                chart_x=chart_x,
                compact_format=compact_format,
            )
        )

    context = {
        "ok": True,
        "mode": mode,
        "chart_x": chart_x,
        "sleep_days": sleep_days,
        "generated_at": generated_at,
        "profile": profile,
        "current_metrics": current_metrics,
        "recent_runs": recent_runs,
        "data_quality": data_quality,
    }
    if directory_output:
        context["export_dir"] = str(export_dir)
        context["export_archive"] = str(_export_archive_path(export_dir))

    if mode in {ExportMode.FULL.value, ExportMode.HTML.value}:
        export_base_context(export_dir, context)
        export_html_index(export_dir, context)
    elif mode == ExportMode.COMPACT.value and not _is_compact_json_file_output(output, compact_format):
        if compact_format == CompactFormat.JSON.value:
            export_compact_json(export_dir, context)
        else:
            export_compact_json(export_dir, context)
            export_compact_html_index(export_dir, context)
    if directory_output:
        _create_export_archive(export_dir)

    return context


def _include_profile_max_heart_rate(current_metrics: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    max_heart_rate = profile.get("max_heart_rate")
    if "max_heart_rate" in current_metrics:
        return current_metrics

    metrics: dict[str, Any] = {}
    inserted = False
    for key, value in current_metrics.items():
        metrics[key] = value
        if key == "date":
            metrics["max_heart_rate"] = max_heart_rate
            inserted = True
    if not inserted:
        metrics["max_heart_rate"] = max_heart_rate
    return metrics


def _uses_directory_output(output: Path | None, *, mode: str, compact_format: str) -> bool:
    if mode in {ExportMode.FULL.value, ExportMode.HTML.value}:
        return True
    if mode == ExportMode.COMPACT.value:
        return not _is_compact_json_file_output(output, compact_format)
    if output is not None and output.suffix.lower() == ".json":
        return False
    return output is not None


def _resolve_export_dir(output: Path | None, generated_at: str) -> Path:
    root = output if output is not None else EXPORTS_DIR / "latest"
    run_name = _export_run_name(generated_at)
    for index in range(100):
        candidate = root / run_name if index == 0 else root / f"{run_name}-{index + 1:02d}"
        try:
            candidate.mkdir(parents=True, exist_ok=False)
            return candidate
        except FileExistsError:
            continue
    raise GarminAIError(f"Could not create a unique export directory under {root}")


def _export_run_name(generated_at: str) -> str:
    timestamp = generated_at.split("+", 1)[0].split("Z", 1)[0].split(".", 1)[0]
    return timestamp.replace("-", "").replace(":", "").replace("T", "-")


def _export_archive_path(export_dir: Path) -> Path:
    return export_dir.with_suffix(".zip")


def _create_export_archive(export_dir: Path) -> Path:
    archive_path = _export_archive_path(export_dir)
    shutil.make_archive(str(export_dir), "zip", root_dir=export_dir.parent, base_dir=export_dir.name)
    return archive_path


def _build_activity_context(
    client: Any,
    activity: dict[str, Any],
    *,
    mode: str,
    export_dir: Path,
    cache: bool,
    chart_x: str,
    compact_format: str,
) -> dict[str, Any]:
    summary = normalize_activity_summary(activity)
    activity_id = str(summary.get("activity_id") or activity.get("activityId") or "")
    data_quality: dict[str, Any] = {}

    day_metrics = collect_day_metrics(client, str(summary.get("date") or "")[:10]) if summary.get("date") else {}
    day_quality = day_metrics.pop("data_quality", {})
    if day_quality:
        data_quality["day_metrics"] = day_quality

    connect_raw = garmin_client.get_connect_splits(client, activity_id)
    connect_splits = _normalize_connect_splits(connect_raw)
    if connect_raw.get("_errors"):
        data_quality["connect_splits"] = {"status": "partial" if connect_splits else "error", "errors": connect_raw["_errors"]}

    fit_laps: list[dict[str, Any]] = []
    km_splits: list[dict[str, Any]] = []
    fit_payload: dict[str, Any] = {
        "records": [],
        "running_dynamics": [],
        "gps": [],
        "events": [],
        "device_info": [],
        "developer_fields": [],
    }
    fit_path: Path | None = None
    if mode != ExportMode.COMPACT.value:
        try:
            fit_path = download_or_get_cached_fit(client, activity_id, FIT_DIR, use_cache=cache)
            fit_payload = parse_fit_file(fit_path)
            fit_laps = fit_payload.get("laps", [])
            km_splits = calculate_km_splits(fit_payload.get("records", []))
        except FitDownloadError as exc:
            data_quality["fit_download"] = {"status": "error", "message": str(exc)}
        except FitParseError as exc:
            data_quality["fit_parse"] = {"status": "error", "message": str(exc)}

    context = {
        "activity_id": activity_id,
        "date": summary.get("date"),
        "summary": summary,
        "day_metrics": day_metrics,
        "connect_splits": connect_splits,
        "fit_laps": fit_laps,
        "km_splits": km_splits,
        "data_quality": data_quality,
    }

    if mode == ExportMode.COMPACT.value:
        activity_dir = export_dir / activity_id
        if compact_format == CompactFormat.HTML.value:
            exported = export_compact_activity_html(activity_dir, context)
            context["compact_data"] = {
                **exported,
                "format": "html",
            }
        else:
            context["compact_data"] = {"format": "json"}
    elif mode in {ExportMode.FULL.value, ExportMode.HTML.value}:
        activity_dir = export_dir / activity_id
        charts_path = build_activity_charts(
            activity_dir,
            fit_payload.get("records", []),
            km_splits,
            fit_payload.get("running_dynamics", []),
            fit_payload.get("gps", []),
            chart_x=chart_x,
        )
        records = fit_payload.get("records", [])
        gps = fit_payload.get("gps", [])
        dynamics = fit_payload.get("running_dynamics", [])
        if mode == ExportMode.HTML.value:
            exported = export_activity_html(activity_dir, context, charts_path=charts_path)
            context["html_data"] = {
                **exported,
                "record_count": len(records),
                "gps_point_count": len(gps),
                "has_power": any(row.get("power_w") is not None for row in records),
                "has_running_dynamics": bool(dynamics),
            }
            write_json(activity_dir / "context.json", context)
        else:
            if fit_path is not None and fit_path.exists():
                exported = export_activity_full(
                    activity_dir,
                    fit_path,
                    context,
                    records,
                    dynamics,
                    gps,
                    fit_payload.get("events", []),
                    fit_payload.get("device_info", []),
                    fit_payload.get("developer_fields", []),
                    charts_path=charts_path,
                )
            else:
                export_activity_basic(activity_dir, context, connect_splits, fit_laps, km_splits)
                exported = {
                    "fit_file": None,
                    "records_file": None,
                    "records_parquet_file": None,
                    "running_dynamics_file": None,
                    "gps_file": None,
                    "events_file": None,
                    "device_info_file": None,
                    "developer_fields_file": None,
                    "charts_file": str(charts_path),
                }
            html_exported = export_activity_html(activity_dir, context, charts_path=charts_path)
            context["full_data"] = {
                **exported,
                "html_file": html_exported["html_file"],
                "record_count": len(records),
                "gps_point_count": len(gps),
                "has_power": any(row.get("power_w") is not None for row in records),
                "has_running_dynamics": bool(dynamics),
            }
            write_json(activity_dir / "context.json", context)
    elif export_dir:
        # In basic mode only export when the caller supplied --output.
        pass

    return context


def _normalize_connect_splits(raw: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for source in ("splits", "typed_splits", "split_summaries"):
        payload = raw.get(source)
        rows = _extract_rows(payload)
        for index, row in enumerate(rows, start=1):
            normalized.append(normalize_connect_split(source, index, row))
    return normalized


def _extract_rows(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("splits", "activitySplits", "lapDTOs", "summaries", "splitSummaries", "typedSplits"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return [payload]
    return []


def _write_requested_output(output: Path, context: dict[str, Any], *, mode: str, compact_format: str) -> None:
    if mode in {ExportMode.FULL.value, ExportMode.HTML.value}:
        return
    if mode == ExportMode.COMPACT.value:
        if compact_format == CompactFormat.JSON.value and output.suffix.lower() == ".json":
            write_json(output, compact_base_context(context))
        return
    if output.suffix.lower() == ".json":
        write_json(output, context)
        return
    export_dir = Path(context.get("export_dir") or output)
    export_dir.mkdir(parents=True, exist_ok=True)
    write_json(export_dir / "base_context.json", context)
    for run in context.get("recent_runs", []):
        activity_dir = export_dir / str(run.get("activity_id"))
        export_activity_basic(activity_dir, run, run.get("connect_splits", []), run.get("fit_laps", []), run.get("km_splits", []))


def _is_compact_json_file_output(output: Path | None, compact_format: str) -> bool:
    return compact_format == CompactFormat.JSON.value and output is not None and output.suffix.lower() == ".json"


def _write_index(output: Path, context: dict[str, Any]) -> None:
    links = []
    for run in context.get("recent_runs", []):
        activity_id = run.get("activity_id")
        links.append(f'<li><a href="{activity_id}/charts.html">{activity_id}</a></li>')
    html = (
        "<!doctype html><html><head><meta charset='utf-8'><title>garmin-ai export</title></head>"
        "<body><h1>garmin-ai export</h1><ul>"
        + "".join(links)
        + "</ul></body></html>"
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / "index.html").write_text(html, encoding="utf-8")


def _print_error(error_code: str, message: str, *, json_output: bool) -> None:
    payload = {"ok": False, "error_code": error_code, "message": message}
    if json_output:
        console.print_json(json.dumps(payload, ensure_ascii=False))
    else:
        console.print(f"[red]{error_code}[/red]: {message}")


def _print_human(context: dict[str, Any]) -> None:
    console.print(f"mode: {context['mode']}")
    if context.get("export_dir"):
        console.print(f"export dir: {context['export_dir']}")
    if context.get("export_archive"):
        console.print(f"export archive: {context['export_archive']}")
    console.print(f"recent runs: {len(context.get('recent_runs', []))}")
    for run in context.get("recent_runs", []):
        summary = run.get("summary", {})
        console.print(
            f"- {summary.get('date')} {summary.get('activity_name') or run.get('activity_id')} "
            f"{summary.get('distance_km') or 0:.2f} km"
        )
