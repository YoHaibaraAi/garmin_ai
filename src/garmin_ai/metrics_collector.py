"""Collect and normalize Garmin wellness metrics."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

from . import garmin_client
from .config import get_config_value
from .utils import as_float, calc_age_from_birth_date, extract_weight_value, find_first_number_by_keys, first_deep


PROFILE_FIELDS = {
    "height_cm": [
        "user_profile.userData.height",
        "userprofile_settings.userData.height",
        "userprofile_settings.height",
        "user_profile.height",
    ],
    "age": [
        "user_profile.userData.age",
        "userprofile_settings.userData.age",
        "user_profile.age",
        "userprofile_settings.age",
    ],
}

PROFILE_MAX_HR_KEYS = [
    "maxHeartRate",
    "userMaxHeartRate",
    "maxHR",
    "maximumHeartRate",
    "maxHr",
    "heartRateMax",
]

LACTATE_THRESHOLD_FIELDS = [
    "userprofile_settings.data.userData.lactateThresholdHeartRate",
    "userprofile_settings.userData.lactateThresholdHeartRate",
    "user_profile.data.userData.lactateThresholdHeartRate",
    "user_profile.userData.lactateThresholdHeartRate",
    "user_settings_raw.data.userData.lactateThresholdHeartRate",
    "user_settings_raw.userData.lactateThresholdHeartRate",
]

BIRTH_DATE_FIELDS = [
    "user_profile.userData.birthDate",
    "user_profile.userData.dateOfBirth",
    "user_profile.userData.birthday",
    "userprofile_settings.userData.birthDate",
    "userprofile_settings.userData.dateOfBirth",
    "userprofile_settings.userData.birthday",
    "user_profile.birthDate",
    "user_profile.dateOfBirth",
    "user_profile.birthday",
    "userprofile_settings.birthDate",
    "userprofile_settings.dateOfBirth",
    "userprofile_settings.birthday",
]

VO2_KEYS = [
    "vo2max",
    "vo2Max",
    "vo2MaxValue",
    "genericVO2Max",
    "runningVO2Max",
    "cyclingVO2Max",
    "currentVO2Max",
    "fitnessAgeVO2Max",
]

VO2MAX_DISPLAY_PATHS = [
    ("profile_sources.userprofile_settings.userData.vo2MaxRunning", "userprofile_settings.userData.vo2MaxRunning"),
    ("profile_sources.userprofile_settings.data.userData.vo2MaxRunning", "userprofile_settings.data.userData.vo2MaxRunning"),
    ("profile_sources.user_profile.userData.vo2MaxRunning", "userprofile_settings.userData.vo2MaxRunning"),
    ("profile_sources.user_profile.data.userData.vo2MaxRunning", "userprofile_settings.data.userData.vo2MaxRunning"),
    ("vo2max_sources.max_metrics.*.[0].generic.vo2MaxValue", "max_metrics[0].generic.vo2MaxValue"),
    ("vo2max_sources.training_status.*.mostRecentVO2Max.generic.vo2MaxValue", "training_status.mostRecentVO2Max.generic.vo2MaxValue"),
    (
        "vo2max_sources.training_status.*.data.mostRecentVO2Max.generic.vo2MaxValue",
        "training_status.data.mostRecentVO2Max.generic.vo2MaxValue",
    ),
]

VO2MAX_PRECISE_PATHS = [
    ("vo2max_sources.max_metrics.*.[0].generic.vo2MaxPreciseValue", "max_metrics[0].generic.vo2MaxPreciseValue"),
    (
        "vo2max_sources.training_status.*.mostRecentVO2Max.generic.vo2MaxPreciseValue",
        "training_status.mostRecentVO2Max.generic.vo2MaxPreciseValue",
    ),
    (
        "vo2max_sources.training_status.*.data.mostRecentVO2Max.generic.vo2MaxPreciseValue",
        "training_status.data.mostRecentVO2Max.generic.vo2MaxPreciseValue",
    ),
]

METRIC_FIELDS = {
    "daily_max_heart_rate": [
        "heart_rates.maxHeartRate",
        "heart_rates.maxHeartRateValue",
        "user_summary.maxHeartRate",
        "stats.maxHeartRate",
    ],
    "resting_heart_rate": [
        "heart_rates.restingHeartRate",
        "heart_rates.restingHeartRateValue",
        "user_summary.restingHeartRate",
        "stats.restingHeartRate",
    ],
    "hrv": [
        "hrv.hrvSummary.lastNightAvg",
        "hrv.hrvSummary.weeklyAvg",
        "hrv.lastNightAvg",
        "hrv.weeklyAvg",
        "stats.hrv",
    ],
    "weight_kg": [
        "body_composition.totalAverage.weight",
        "stats_and_body.weight",
        "stats.weight",
        "user_summary.weight",
    ],
    "vo2max": [
        "user_summary.vO2MaxValue",
        "user_summary.vo2MaxValue",
        "stats.vO2MaxValue",
        "stats.vo2MaxValue",
    ],
}

SLEEP_DAY_FIELDS = {
    "sleep_score": [
        "dailySleepDTO.sleepScores.overall.value",
        "sleepScores.overall.value",
        "sleepScore",
        "overallSleepScore",
    ],
    "total_sleep_seconds": [
        "dailySleepDTO.sleepTimeSeconds",
        "sleepTimeSeconds",
        "totalSleepSeconds",
        "totalSleepTimeSeconds",
    ],
    "deep_sleep_seconds": ["dailySleepDTO.deepSleepSeconds", "deepSleepSeconds"],
    "light_sleep_seconds": ["dailySleepDTO.lightSleepSeconds", "lightSleepSeconds"],
    "rem_sleep_seconds": ["dailySleepDTO.remSleepSeconds", "remSleepSeconds"],
    "awake_seconds": ["dailySleepDTO.awakeSleepSeconds", "awakeSleepSeconds", "awakeDuration"],
    "sleep_start": [
        "dailySleepDTO.sleepStartTimestampLocal",
        "sleepStartTimestampLocal",
        "sleepStartTimestampGMT",
    ],
    "sleep_end": [
        "dailySleepDTO.sleepEndTimestampLocal",
        "sleepEndTimestampLocal",
        "sleepEndTimestampGMT",
    ],
}

RECENT_WELLNESS_DAYS = 7


def collect_profile(client: Any) -> dict[str, Any]:
    """Collect user profile fields and quality markers."""

    raw = garmin_client.get_profile(client)
    profile: dict[str, Any] = {}
    quality: dict[str, Any] = {}
    for field, aliases in PROFILE_FIELDS.items():
        value = first_deep(raw, aliases)
        if field == "age" and value is None:
            value = calc_age_from_birth_date(first_deep(raw, BIRTH_DATE_FIELDS))
        profile[field] = int(value) if field == "age" and value is not None else as_float(value)
        if profile[field] is None:
            quality[field] = {"status": "missing"}
    max_hr, max_hr_source = _extract_profile_max_heart_rate(raw)
    profile["max_heart_rate"] = _profile_heart_rate(max_hr)
    if max_hr is None:
        quality["max_heart_rate"] = "missing"
    else:
        quality["max_heart_rate"] = f"ok:{max_hr_source}"

    lactate_threshold = as_float(first_deep(raw, LACTATE_THRESHOLD_FIELDS))
    profile["lactate_threshold_heart_rate"] = _profile_heart_rate(lactate_threshold)
    if lactate_threshold is None:
        quality["lactate_threshold_heart_rate"] = {"status": "missing"}
    if raw.get("_errors"):
        quality["api_errors"] = raw["_errors"]
    profile["data_quality"] = quality
    return profile


def collect_current_metrics(client: Any, sleep_days: int = 7) -> dict[str, Any]:
    """Collect today's metrics."""

    raw = garmin_client.get_current_metrics(client)
    cdate = str(raw.get("date") or date.today().isoformat())
    raw["profile_sources"] = garmin_client.get_profile(client)
    raw["weight_sources"] = garmin_client.get_weight_sources(client, cdate)
    raw["vo2max_sources"] = garmin_client.get_vo2max_sources(client, cdate)
    metrics = _normalize_metrics(raw)
    recent_metrics, recent_quality = _collect_recent_wellness_metrics(
        client,
        cdate,
        days=RECENT_WELLNESS_DAYS,
        current_raw=raw,
    )
    metrics = _insert_metrics_after(metrics, "hrv", recent_metrics)
    if recent_quality:
        metrics.setdefault("data_quality", {})["recent_7d_metrics"] = recent_quality
    sleep, sleep_quality = _collect_sleep_summary(client, cdate, days=sleep_days)
    metrics["sleep"] = sleep
    if sleep_quality:
        metrics.setdefault("data_quality", {})["sleep"] = sleep_quality
    return metrics


def collect_day_metrics(client: Any, cdate: str) -> dict[str, Any]:
    """Collect metrics for a specific date."""

    raw = garmin_client.get_day_metrics(client, cdate)
    raw["profile_sources"] = garmin_client.get_profile(client)
    raw["weight_sources"] = garmin_client.get_weight_sources(client, cdate)
    raw["vo2max_sources"] = garmin_client.get_vo2max_sources(client, cdate)
    metrics = _normalize_metrics(raw)
    sleep, sleep_quality = _collect_sleep_day(client, cdate)
    metrics["sleep"] = sleep
    if sleep_quality:
        metrics.setdefault("data_quality", {})["sleep"] = sleep_quality
    return metrics


def collect_sleep_day(client: Any, cdate: str) -> dict[str, Any]:
    """Collect a compact sleep summary for one date."""

    sleep, _quality = _collect_sleep_day(client, cdate)
    return sleep


def collect_sleep_summary(client: Any, end_date: str, days: int = 7) -> dict[str, Any]:
    """Collect compact sleep summaries for a date range ending at end_date."""

    sleep, _quality = _collect_sleep_summary(client, end_date, days=days)
    return sleep


def _collect_sleep_summary(client: Any, end_date: str, days: int = 7) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Collect compact sleep summaries and quality metadata."""

    safe_days = max(1, int(days or 7))
    end = _parse_date_value(end_date) or date.today()
    start = end - timedelta(days=safe_days - 1)
    items: list[dict[str, Any]] = []
    quality_items: list[dict[str, Any]] = []

    for offset in range(safe_days):
        cdate = (start + timedelta(days=offset)).isoformat()
        item, quality = _collect_sleep_day(client, cdate)
        items.append(item)
        if quality:
            quality_items.append({"date": cdate, **quality})

    summary = _summarize_sleep_items(items)
    result: dict[str, Any] = {"days": safe_days, "items": items, "summary": summary}
    if quality_items:
        return result, {
            "status": "partial" if summary["valid_days"] else "missing",
            "items": quality_items,
        }
    return result, None


def _collect_recent_wellness_metrics(
    client: Any,
    end_date: str,
    *,
    days: int,
    current_raw: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    safe_days = max(1, int(days or RECENT_WELLNESS_DAYS))
    end = _parse_date_value(end_date) or date.today()
    start = end - timedelta(days=safe_days - 1)
    hrv_values: list[float] = []
    resting_values: list[float] = []
    quality_items: list[dict[str, Any]] = []

    for offset in range(safe_days):
        cdate = (start + timedelta(days=offset)).isoformat()
        raw = current_raw if cdate == end.isoformat() and current_raw is not None else garmin_client.get_day_metrics(client, cdate)
        hrv = _extract_metric_number(raw, "hrv")
        resting = _extract_metric_number(raw, "resting_heart_rate")
        if hrv is not None:
            hrv_values.append(hrv)
        if resting is not None:
            resting_values.append(resting)

        item_quality: dict[str, Any] = {}
        if hrv is None:
            item_quality["hrv"] = "missing"
        if resting is None:
            item_quality["resting_heart_rate"] = "missing"
        if isinstance(raw.get("_errors"), Mapping) and raw["_errors"]:
            item_quality["api_errors"] = raw["_errors"]
        if item_quality:
            quality_items.append({"date": cdate, **item_quality})

    metrics = {
        "hrv_7d_avg": _compact_number(_avg(hrv_values)),
        "resting_heart_rate_7d_avg": _compact_number(_avg(resting_values)),
    }
    quality: dict[str, Any] = {
        "days": safe_days,
        "hrv_valid_days": len(hrv_values),
        "resting_heart_rate_valid_days": len(resting_values),
    }
    if quality_items:
        quality["status"] = "partial" if hrv_values or resting_values else "missing"
        quality["items"] = quality_items
    return metrics, quality if quality_items else None


def _extract_metric_number(raw: Mapping[str, Any], field: str) -> float | None:
    return as_float(first_deep(raw, METRIC_FIELDS[field]))


def _insert_metrics_after(metrics: dict[str, Any], after_key: str, additions: Mapping[str, Any]) -> dict[str, Any]:
    inserted = False
    ordered: dict[str, Any] = {}
    for key, value in metrics.items():
        ordered[key] = value
        if key == after_key:
            ordered.update(additions)
            inserted = True
    if not inserted:
        ordered.update(additions)
    return ordered


def _normalize_metrics(raw: Mapping[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {"date": raw.get("date")}
    quality: dict[str, Any] = {}
    vo2_values = _extract_vo2_values(raw)
    for field, aliases in METRIC_FIELDS.items():
        if field == "weight_kg":
            value = _extract_latest_weight_kg(raw.get("weight_sources")) or first_deep(raw, aliases)
        elif field == "vo2max":
            value = vo2_values.get("vo2max") or first_deep(raw, aliases)
        else:
            value = first_deep(raw, aliases)
        metrics[field] = value if field == "sleep" else as_float(value)
        if field == "vo2max" and metrics[field] is not None:
            metrics[field] = round(float(metrics[field]), 1)
        if metrics[field] is None:
            quality[field] = {"status": "missing_from_api" if field == "vo2max" else "missing"}
        elif field == "vo2max" and vo2_values.get("vo2max_source"):
            quality[field] = f"ok:{vo2_values['vo2max_source']}"
    metrics["vo2max_precise"] = vo2_values.get("vo2max_precise")
    if metrics["vo2max_precise"] is not None:
        metrics["vo2max_precise"] = round(float(metrics["vo2max_precise"]), 1)
        quality["vo2max_precise"] = f"ok:{vo2_values['vo2max_precise_source']}"
    else:
        quality["vo2max_precise"] = {"status": "missing_from_api"}
    if metrics.get("vo2max") is None and metrics.get("vo2max_precise") is not None:
        metrics["vo2max"] = round(float(metrics["vo2max_precise"]))
        quality["vo2max"] = "ok:round(vo2max_precise)"
    if raw.get("_errors"):
        quality["api_errors"] = raw["_errors"]
    _merge_source_errors(quality, "weight_kg", raw.get("weight_sources"))
    _merge_source_errors(quality, "vo2max", raw.get("vo2max_sources"))
    metrics["data_quality"] = quality
    return metrics


def _collect_sleep_day(client: Any, cdate: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        raw = client.get_sleep_data(cdate)
    except Exception as exc:  # noqa: BLE001
        return _missing_sleep_day(cdate), {"status": "error", "message": str(exc)}

    if not raw:
        return _missing_sleep_day(cdate), {"status": "missing"}

    item = _missing_sleep_day(cdate)
    for field, paths in SLEEP_DAY_FIELDS.items():
        value = first_deep(raw, paths)
        if field.endswith("_seconds") or field == "sleep_score":
            item[field] = _compact_number(as_float(value))
        else:
            item[field] = str(value) if value is not None else None
    item["total_sleep_hours"] = _seconds_to_hours(item.get("total_sleep_seconds"))
    item["missing"] = not any(
        item.get(field) is not None
        for field in (
            "sleep_score",
            "total_sleep_seconds",
            "deep_sleep_seconds",
            "light_sleep_seconds",
            "rem_sleep_seconds",
            "awake_seconds",
            "sleep_start",
            "sleep_end",
        )
    )
    if item["missing"]:
        return item, {"status": "missing"}
    return item, None


def _missing_sleep_day(cdate: str) -> dict[str, Any]:
    return {
        "date": cdate,
        "sleep_score": None,
        "total_sleep_seconds": None,
        "total_sleep_hours": None,
        "deep_sleep_seconds": None,
        "light_sleep_seconds": None,
        "rem_sleep_seconds": None,
        "awake_seconds": None,
        "sleep_start": None,
        "sleep_end": None,
        "missing": True,
    }


def _summarize_sleep_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    valid_days = sum(1 for item in items if not item.get("missing"))
    missing_days = len(items) - valid_days
    return {
        "avg_sleep_score": _avg([item.get("sleep_score") for item in items]),
        "avg_total_sleep_hours": _avg([item.get("total_sleep_hours") for item in items]),
        "avg_deep_sleep_hours": _avg_seconds_as_hours([item.get("deep_sleep_seconds") for item in items]),
        "avg_light_sleep_hours": _avg_seconds_as_hours([item.get("light_sleep_seconds") for item in items]),
        "avg_rem_sleep_hours": _avg_seconds_as_hours([item.get("rem_sleep_seconds") for item in items]),
        "avg_awake_minutes": _avg_seconds_as_minutes([item.get("awake_seconds") for item in items]),
        "valid_days": valid_days,
        "missing_days": missing_days,
    }


def _seconds_to_hours(value: Any) -> float | None:
    seconds = as_float(value)
    return round(seconds / 3600, 2) if seconds is not None else None


def _avg(values: list[Any]) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    return round(sum(numbers) / len(numbers), 2) if numbers else None


def _avg_seconds_as_hours(values: list[Any]) -> float | None:
    numbers = [float(value) / 3600 for value in values if value is not None]
    return round(sum(numbers) / len(numbers), 2) if numbers else None


def _avg_seconds_as_minutes(values: list[Any]) -> float | None:
    numbers = [float(value) / 60 for value in values if value is not None]
    return round(sum(numbers) / len(numbers), 2) if numbers else None


def _compact_number(value: float | None) -> int | float | None:
    if value is None:
        return None
    return int(value) if float(value).is_integer() else value


def _extract_profile_max_heart_rate(raw: Mapping[str, Any]) -> tuple[float | None, str | None]:
    for source in (
        "device_settings",
        "device_last_used",
        "primary_training_device",
        "devices",
        "user_settings_raw",
        "userprofile_settings",
        "user_profile",
    ):
        value = find_first_number_by_keys(raw.get(source), PROFILE_MAX_HR_KEYS)
        if value is not None:
            return value, source
    fallback = as_float(get_config_value("max_heart_rate"))
    if fallback is not None:
        return fallback, "config.max_heart_rate"
    return None, None


def _profile_heart_rate(value: float | None) -> int | float | None:
    if value is None:
        return None
    return int(value) if float(value).is_integer() else value


def _extract_vo2_values(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Extract Garmin display VO2max and precise VO2max separately."""

    display_value, display_source = _first_number_from_paths(raw, VO2MAX_DISPLAY_PATHS)
    precise_value, precise_source = _first_number_from_paths(raw, VO2MAX_PRECISE_PATHS)

    if display_value is None:
        display_value = _extract_vo2max(raw.get("vo2max_sources"))
        display_source = "recursive_vo2_fallback" if display_value is not None else None

    return {
        "vo2max": round(display_value, 1) if display_value is not None else None,
        "vo2max_source": display_source,
        "vo2max_precise": round(precise_value, 1) if precise_value is not None else None,
        "vo2max_precise_source": precise_source,
    }


def _first_number_from_paths(raw: Mapping[str, Any], paths: list[tuple[str, str]]) -> tuple[float | None, str | None]:
    for path, label in paths:
        value = _path_value(raw, path)
        number = as_float(value)
        if number is not None:
            return number, label
    return None, None


def _path_value(obj: Any, path: str) -> Any:
    return _path_parts_value(obj, path.split("."))


def _path_parts_value(obj: Any, parts: list[str]) -> Any:
    current = obj
    for index, part in enumerate(parts):
        if part == "*":
            if isinstance(current, Mapping):
                for value in current.values():
                    found = _path_parts_value(value, parts[index + 1 :])
                    if found is not None:
                        return found
            return None
        if part.startswith("[") and part.endswith("]"):
            if not isinstance(current, list):
                return None
            try:
                current = current[int(part[1:-1])]
            except (IndexError, ValueError):
                return None
        elif isinstance(current, Mapping):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current


def _extract_latest_weight_kg(source: Any) -> float | None:
    """Extract the latest weight from prioritized Garmin weight payloads."""

    if not isinstance(source, Mapping):
        return None
    for key in ("weigh_ins", "body_composition_range", "daily_weigh_ins"):
        candidates = _collect_weight_candidates(source.get(key))
        if candidates:
            candidates.sort(key=lambda item: item[0] or date.min, reverse=True)
            return round(candidates[0][1], 1)
    return None


def _collect_weight_candidates(obj: Any, inherited_date: date | None = None) -> list[tuple[date | None, float]]:
    candidates: list[tuple[date | None, float]] = []
    if isinstance(obj, Mapping):
        current_date = _extract_date_from_mapping(obj) or inherited_date
        weight = extract_weight_value(obj)
        if weight is not None:
            candidates.append((current_date, weight))
        for key, value in obj.items():
            if key == "totalAverage":
                candidates.extend(_collect_weight_candidates(value, current_date))
            elif key == "dateWeightList":
                candidates.extend(_collect_weight_candidates(value, current_date))
            elif isinstance(value, (Mapping, list, tuple)):
                child_date = _parse_date_value(key) or current_date
                candidates.extend(_collect_weight_candidates(value, child_date))
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            candidates.extend(_collect_weight_candidates(item, inherited_date))
    return candidates


def _extract_vo2max(source: Any) -> float | None:
    """Extract VO2max from ordered Garmin VO2 source payloads."""

    if not isinstance(source, Mapping):
        return None
    for key in ("max_metrics", "training_status", "fitnessage"):
        payload = source.get(key)
        if isinstance(payload, Mapping):
            for value in payload.values():
                found = find_first_number_by_keys(value, VO2_KEYS)
                if found is not None:
                    return round(found, 1)
    return round(found, 1) if (found := find_first_number_by_keys(source.get("recent_running_activities"), VO2_KEYS)) else None


def _merge_source_errors(quality: dict[str, Any], field: str, source: Any) -> None:
    if isinstance(source, Mapping) and source.get("_errors") and field in quality:
        if not isinstance(quality[field], dict):
            return
        quality[field]["api_errors"] = source["_errors"]


def _extract_date_from_mapping(obj: Mapping[str, Any]) -> date | None:
    for key in ("date", "calendarDate", "samplePk", "measurementDate", "weightDate", "dateTimestamp"):
        parsed = _parse_date_value(obj.get(key))
        if parsed is not None:
            return parsed
    return None


def _parse_date_value(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError:
        return None
