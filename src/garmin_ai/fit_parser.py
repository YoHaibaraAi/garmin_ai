"""FIT parsing based on Garmin's official garmin-fit-sdk."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .errors import FitParseError
from .utils import (
    as_float,
    first_present,
    json_safe,
    pace_sec_per_km_from_speed,
    semicircles_to_degrees,
)


def parse_fit_file(fit_path: Path | str) -> dict[str, Any]:
    """Parse a FIT file and return normalized message groups."""

    path = Path(fit_path)
    try:
        from garmin_fit_sdk import Decoder, Stream

        with path.open("rb") as fit_file:
            stream = Stream(fit_file, path.stat().st_size)
            decoded = Decoder(stream).read(
                apply_scale_and_offset=True,
                convert_datetimes_to_dates=True,
                convert_types_to_strings=True,
                expand_sub_fields=True,
                expand_components=True,
            )
    except Exception as exc:  # noqa: BLE001
        raise FitParseError(f"Failed to decode FIT file {path}: {exc}") from exc

    messages = _extract_messages(decoded)
    try:
        records = normalize_records(messages)
        return {
            "messages": messages,
            "session": normalize_session(messages),
            "laps": normalize_laps(messages),
            "records": records,
            "running_dynamics": split_running_dynamics(records),
            "gps": split_gps(records),
            "events": normalize_events(messages),
            "device_info": normalize_device_info(messages),
            "developer_fields": normalize_developer_fields(messages),
        }
    except Exception as exc:  # noqa: BLE001
        raise FitParseError(f"Failed to normalize FIT file {path}: {exc}") from exc


def normalize_session(messages: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the first session message into summary-like fields."""

    session = _first_message(messages, "session_mesgs")
    speed = _value(session, ["enhanced_avg_speed", "avg_speed"])
    max_speed = _value(session, ["enhanced_max_speed", "max_speed"])
    return {
        "distance_m": as_float(_value(session, ["total_distance"])),
        "duration_seconds": as_float(_value(session, ["total_timer_time"])),
        "moving_duration_seconds": as_float(_value(session, ["total_moving_time", "total_timer_time"])),
        "elapsed_seconds": as_float(_value(session, ["total_elapsed_time"])),
        "avg_pace_sec_per_km": pace_sec_per_km_from_speed(speed),
        "best_pace_sec_per_km": pace_sec_per_km_from_speed(max_speed),
        "avg_speed_mps": as_float(speed),
        "max_speed_mps": as_float(max_speed),
        "avg_hr": as_float(_value(session, ["avg_heart_rate"])),
        "max_hr": as_float(_value(session, ["max_heart_rate"])),
        "min_hr": as_float(_value(session, ["min_heart_rate"])),
        "avg_cadence_spm": as_float(_value(session, ["avg_cadence", "avg_running_cadence"])),
        "max_cadence_spm": as_float(_value(session, ["max_cadence", "max_running_cadence"])),
        "avg_power_w": as_float(_value(session, ["avg_power"])),
        "max_power_w": as_float(_value(session, ["max_power"])),
        "normalized_power_w": as_float(_value(session, ["normalized_power"])),
        "elevation_gain_m": as_float(_value(session, ["total_ascent"])),
        "elevation_loss_m": as_float(_value(session, ["total_descent"])),
        "calories": as_float(_value(session, ["total_calories"])),
        "training_effect_aerobic": as_float(_value(session, ["total_training_effect"])),
        "training_effect_anaerobic": as_float(_value(session, ["total_anaerobic_training_effect"])),
        "sport": _value(session, ["sport"]),
        "start_time": _json_time(_value(session, ["start_time", "timestamp"])),
    }


def normalize_laps(messages: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize FIT lap messages."""

    laps = _message_list(messages, "lap_mesgs")
    normalized: list[dict[str, Any]] = []
    for index, lap in enumerate(laps, start=1):
        speed = _value(lap, ["enhanced_avg_speed", "avg_speed"])
        max_speed = _value(lap, ["enhanced_max_speed", "max_speed"])
        normalized.append(
            {
                "lap_index": index,
                "start_time": _json_time(_value(lap, ["start_time"])),
                "end_time": _json_time(_value(lap, ["timestamp"])),
                "distance_m": as_float(_value(lap, ["total_distance"])),
                "duration_seconds": as_float(_value(lap, ["total_timer_time"])),
                "moving_duration_seconds": as_float(_value(lap, ["total_moving_time", "total_timer_time"])),
                "elapsed_seconds": as_float(_value(lap, ["total_elapsed_time"])),
                "avg_pace_sec_per_km": pace_sec_per_km_from_speed(speed),
                "avg_speed_mps": as_float(speed),
                "max_speed_mps": as_float(max_speed),
                "avg_hr": as_float(_value(lap, ["avg_heart_rate"])),
                "max_hr": as_float(_value(lap, ["max_heart_rate"])),
                "avg_cadence_spm": as_float(_value(lap, ["avg_cadence", "avg_running_cadence"])),
                "max_cadence_spm": as_float(_value(lap, ["max_cadence", "max_running_cadence"])),
                "avg_power_w": as_float(_value(lap, ["avg_power"])),
                "max_power_w": as_float(_value(lap, ["max_power"])),
                "elevation_gain_m": as_float(_value(lap, ["total_ascent"])),
                "elevation_loss_m": as_float(_value(lap, ["total_descent"])),
                "calories": as_float(_value(lap, ["total_calories"])),
                "lap_trigger": _value(lap, ["lap_trigger"]),
                "sport": _value(lap, ["sport"]),
            }
        )
    return normalized


def normalize_records(messages: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize FIT record messages into AI-friendly samples."""

    records = _message_list(messages, "record_mesgs")
    normalized: list[dict[str, Any]] = []
    first_ts = None
    for record in records:
        timestamp = _value(record, ["timestamp"])
        if first_ts is None and hasattr(timestamp, "timestamp"):
            first_ts = timestamp
        elapsed = None
        if first_ts is not None and hasattr(timestamp, "timestamp"):
            elapsed = timestamp.timestamp() - first_ts.timestamp()
        speed = _value(record, ["enhanced_speed", "speed"])
        normalized.append(
            {
                "timestamp": _json_time(timestamp),
                "elapsed_seconds": elapsed,
                "distance_m": as_float(_value(record, ["distance"])),
                "speed_mps": as_float(speed),
                "pace_sec_per_km": pace_sec_per_km_from_speed(speed),
                "heart_rate": as_float(_value(record, ["heart_rate"])),
                "cadence_spm": as_float(_value(record, ["cadence", "run_cadence"])),
                "power_w": as_float(_value(record, ["power"])),
                "altitude_m": as_float(_value(record, ["enhanced_altitude", "altitude"])),
                "temperature_c": as_float(_value(record, ["temperature"])),
                "lat": semicircles_to_degrees(_value(record, ["position_lat", "lat"])),
                "lon": semicircles_to_degrees(_value(record, ["position_long", "position_lon", "lon"])),
                "vertical_oscillation_mm": as_float(_value(record, ["vertical_oscillation"])),
                "ground_contact_time_ms": as_float(_value(record, ["stance_time", "ground_contact_time"])),
                "ground_contact_balance_left_percent": as_float(
                    _value(record, ["stance_time_balance", "ground_contact_balance"])
                ),
                "stride_length_m": as_float(_value(record, ["step_length", "stride_length"])),
                "vertical_ratio_percent": as_float(_value(record, ["vertical_ratio"])),
            }
        )
    return normalized


def split_running_dynamics(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return records containing at least one running dynamics field."""

    fields = [
        "vertical_oscillation_mm",
        "ground_contact_time_ms",
        "ground_contact_balance_left_percent",
        "stride_length_m",
        "vertical_ratio_percent",
    ]
    return [
        {"timestamp": row.get("timestamp"), "distance_m": row.get("distance_m"), **{field: row.get(field) for field in fields}}
        for row in records
        if any(row.get(field) is not None for field in fields)
    ]


def split_gps(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return GPS points from normalized records."""

    return [
        {
            "timestamp": row.get("timestamp"),
            "distance_m": row.get("distance_m"),
            "lat": row.get("lat"),
            "lon": row.get("lon"),
            "altitude_m": row.get("altitude_m"),
        }
        for row in records
        if row.get("lat") is not None and row.get("lon") is not None
    ]


def normalize_events(messages: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize FIT event messages."""

    return [json_safe(row) for row in _message_list(messages, "event_mesgs")]


def normalize_device_info(messages: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize FIT device info messages."""

    return [json_safe(row) for row in _message_list(messages, "device_info_mesgs")]


def normalize_developer_fields(messages: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Preserve developer field metadata when available."""

    fields: list[dict[str, Any]] = []
    for key in ("developer_data_id_mesgs", "field_description_mesgs"):
        for row in _message_list(messages, key):
            fields.append({"source": key, "raw": json_safe(row)})
    return fields


def _extract_messages(decoded: Any) -> dict[str, Any]:
    if isinstance(decoded, tuple):
        for item in decoded:
            if isinstance(item, dict):
                return item
    if isinstance(decoded, dict):
        return decoded
    raise FitParseError("garmin-fit-sdk returned an unsupported decode structure")


def _message_list(messages: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    value = messages.get(key) or messages.get(key.replace("_mesgs", "")) or []
    if isinstance(value, list):
        return [row for row in value if isinstance(row, Mapping)]
    return []


def _first_message(messages: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    rows = _message_list(messages, key)
    return rows[0] if rows else {}


def _value(row: Mapping[str, Any], aliases: list[str]) -> Any:
    return first_present(row, aliases)


def _json_time(value: Any) -> Any:
    return json_safe(value)
