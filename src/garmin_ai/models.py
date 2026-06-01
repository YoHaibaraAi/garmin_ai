"""Normalization helpers for Garmin activity-shaped data."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .utils import as_float, as_int, first_deep, pace_sec_per_km_from_speed


SUMMARY_FIELDS: dict[str, list[str]] = {
    "activity_id": ["activityId", "activity_id", "activityUUID"],
    "activity_name": ["activityName", "activity_name", "name"],
    "activity_type": ["activityType.typeKey", "activityTypeDTO.typeKey", "activity_type", "eventType.typeKey"],
    "start_time_local": ["startTimeLocal", "start_time_local", "startTimeGMT"],
    "date": ["startTimeLocal", "start_time_local", "startTimeGMT"],
    "distance_m": ["distance", "distance_m", "summaryDTO.distance"],
    "duration_seconds": ["duration", "duration_seconds", "summaryDTO.duration"],
    "moving_duration_seconds": ["movingDuration", "moving_duration_seconds", "summaryDTO.movingDuration"],
    "elapsed_seconds": ["elapsedDuration", "elapsed_seconds", "summaryDTO.elapsedDuration"],
    "avg_speed_mps": ["averageSpeed", "avg_speed_mps", "summaryDTO.averageSpeed"],
    "max_speed_mps": ["maxSpeed", "max_speed_mps", "summaryDTO.maxSpeed"],
    "avg_hr": ["averageHR", "averageHr", "avg_hr", "summaryDTO.averageHR"],
    "max_hr": ["maxHR", "maxHr", "max_hr", "summaryDTO.maxHR"],
    "min_hr": ["minHR", "minHr", "min_hr"],
    "avg_cadence_spm": ["averageRunningCadenceInStepsPerMinute", "averageRunCadence", "avg_cadence_spm"],
    "max_cadence_spm": ["maxRunningCadenceInStepsPerMinute", "maxRunCadence", "max_cadence_spm"],
    "avg_power_w": ["avgPower", "averagePower", "avg_power_w"],
    "max_power_w": ["maxPower", "max_power_w"],
    "normalized_power_w": ["normalizedPower", "normalized_power_w"],
    "elevation_gain_m": ["elevationGain", "elevation_gain_m", "summaryDTO.elevationGain"],
    "elevation_loss_m": ["elevationLoss", "elevation_loss_m", "summaryDTO.elevationLoss"],
    "min_altitude_m": ["minElevation", "minAltitude", "min_altitude_m"],
    "max_altitude_m": ["maxElevation", "maxAltitude", "max_altitude_m"],
    "calories": ["calories", "summaryDTO.calories"],
    "training_effect_aerobic": ["aerobicTrainingEffect", "trainingEffect", "training_effect_aerobic"],
    "training_effect_anaerobic": ["anaerobicTrainingEffect", "training_effect_anaerobic"],
    "training_load": ["trainingLoad", "training_load"],
    "vo2max_from_activity": ["vO2MaxValue", "vo2MaxValue", "vo2max_from_activity"],
    "recovery_time_hours": ["recoveryTime", "recovery_time_hours"],
    "avg_stride_length_m": ["avgStrideLength", "averageStrideLength", "avg_stride_length_m"],
    "avg_vertical_oscillation_mm": ["avgVerticalOscillation", "averageVerticalOscillation", "avg_vertical_oscillation_mm"],
    "avg_ground_contact_time_ms": ["avgGroundContactTime", "averageGroundContactTime", "avg_ground_contact_time_ms"],
    "avg_ground_contact_balance_left_percent": [
        "avgGroundContactBalance",
        "averageGroundContactBalance",
        "avg_ground_contact_balance_left_percent",
    ],
    "avg_vertical_ratio_percent": ["avgVerticalRatio", "averageVerticalRatio", "avg_vertical_ratio_percent"],
    "temperature_avg_c": ["avgTemperature", "averageTemperature", "temperature_avg_c"],
    "temperature_min_c": ["minTemperature", "temperature_min_c"],
    "temperature_max_c": ["maxTemperature", "temperature_max_c"],
    "device_name": ["deviceName", "manufacturer", "metadataDTO.deviceApplicationInstallationId"],
    "manufacturer": ["manufacturer", "deviceManufacturer"],
}


NUMERIC_SUMMARY_FIELDS = {
    "distance_m",
    "distance_km",
    "duration_seconds",
    "moving_duration_seconds",
    "elapsed_seconds",
    "avg_pace_sec_per_km",
    "best_pace_sec_per_km",
    "avg_speed_mps",
    "max_speed_mps",
    "avg_hr",
    "max_hr",
    "min_hr",
    "avg_cadence_spm",
    "max_cadence_spm",
    "avg_power_w",
    "max_power_w",
    "normalized_power_w",
    "elevation_gain_m",
    "elevation_loss_m",
    "min_altitude_m",
    "max_altitude_m",
    "calories",
    "training_effect_aerobic",
    "training_effect_anaerobic",
    "training_load",
    "vo2max_from_activity",
    "recovery_time_hours",
    "avg_stride_length_m",
    "avg_vertical_oscillation_mm",
    "avg_ground_contact_time_ms",
    "avg_ground_contact_balance_left_percent",
    "avg_vertical_ratio_percent",
    "temperature_avg_c",
    "temperature_min_c",
    "temperature_max_c",
}


def normalize_activity_summary(activity: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize a Garmin Connect activity summary for AI-friendly output."""

    summary: dict[str, Any] = {}
    for field, aliases in SUMMARY_FIELDS.items():
        value = first_deep(activity, aliases)
        if field in NUMERIC_SUMMARY_FIELDS:
            value = as_float(value)
        summary[field] = value

    distance = as_float(summary.get("distance_m"))
    speed = as_float(summary.get("avg_speed_mps"))
    max_speed = as_float(summary.get("max_speed_mps"))
    summary["distance_km"] = distance / 1000 if distance is not None else None
    summary["avg_pace_sec_per_km"] = pace_sec_per_km_from_speed(speed)
    summary["best_pace_sec_per_km"] = pace_sec_per_km_from_speed(max_speed)

    if summary.get("date") and isinstance(summary["date"], str):
        summary["date"] = summary["date"][:10]

    activity_id = summary.get("activity_id")
    if activity_id is not None:
        summary["activity_id"] = str(activity_id)

    return summary


def normalize_connect_split(source: str, index: int, raw: Any) -> dict[str, Any]:
    """Normalize one Garmin Connect split item while preserving raw data."""

    raw_map = raw if isinstance(raw, Mapping) else {}
    speed = first_deep(raw_map, ["averageSpeed", "avgSpeed", "avg_speed_mps"])
    return {
        "source": source,
        "raw": raw,
        "split_index": as_int(first_deep(raw_map, ["splitIndex", "lapIndex", "splitNumber"])) or index,
        "distance_m": as_float(first_deep(raw_map, ["distance", "totalDistance", "distance_m"])),
        "duration_seconds": as_float(first_deep(raw_map, ["duration", "movingDuration", "elapsedDuration", "time"])),
        "avg_pace_sec_per_km": pace_sec_per_km_from_speed(speed),
        "avg_hr": as_float(first_deep(raw_map, ["averageHR", "averageHr", "avg_hr"])),
        "max_hr": as_float(first_deep(raw_map, ["maxHR", "maxHr", "max_hr"])),
        "avg_cadence_spm": as_float(
            first_deep(raw_map, ["averageRunningCadenceInStepsPerMinute", "averageRunCadence", "avg_cadence_spm"])
        ),
        "avg_power_w": as_float(first_deep(raw_map, ["avgPower", "averagePower", "avg_power_w"])),
    }
