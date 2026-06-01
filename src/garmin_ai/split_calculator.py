"""Fixed-distance split calculations from FIT records."""

from __future__ import annotations

import math
from typing import Any

from .utils import as_float, average, maximum, minimum


def calculate_km_splits(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Calculate stable 1 km splits from normalized FIT records.

    This first version uses records that fall inside each kilometer bucket and
    does not interpolate exact boundary points.
    """

    usable = [row for row in records if as_float(row.get("distance_m")) is not None]
    if not usable:
        return []
    usable.sort(key=lambda row: as_float(row.get("distance_m")) or 0)
    max_distance = as_float(usable[-1].get("distance_m")) or 0
    if max_distance <= 0:
        return []

    splits: list[dict[str, Any]] = []
    total_buckets = max(1, math.ceil(max_distance / 1000.0))
    for bucket in range(total_buckets):
        start_distance = bucket * 1000.0
        end_distance = min((bucket + 1) * 1000.0, max_distance)
        rows = [
            row
            for row in usable
            if (as_float(row.get("distance_m")) or 0) > start_distance
            and (as_float(row.get("distance_m")) or 0) <= end_distance
        ]
        if not rows:
            continue
        split_distance = end_distance - start_distance
        duration = _duration_seconds(rows)
        avg_speed = split_distance / duration if duration and duration > 0 else average(row.get("speed_mps") for row in rows)
        splits.append(
            {
                "km_index": bucket + 1,
                "partial": split_distance < 999.0,
                "start_distance_m": start_distance,
                "end_distance_m": end_distance,
                "distance_m": split_distance,
                "start_time": rows[0].get("timestamp"),
                "end_time": rows[-1].get("timestamp"),
                "duration_seconds": duration,
                "pace_sec_per_km": (duration / split_distance * 1000.0) if duration and split_distance > 0 else None,
                "avg_speed_mps": avg_speed,
                "max_speed_mps": maximum(row.get("speed_mps") for row in rows),
                "avg_hr": average(row.get("heart_rate") for row in rows),
                "max_hr": maximum(row.get("heart_rate") for row in rows),
                "min_hr": minimum(row.get("heart_rate") for row in rows),
                "avg_cadence_spm": average(row.get("cadence_spm") for row in rows),
                "max_cadence_spm": maximum(row.get("cadence_spm") for row in rows),
                "avg_power_w": average(row.get("power_w") for row in rows),
                "max_power_w": maximum(row.get("power_w") for row in rows),
                "avg_stride_length_m": average(row.get("stride_length_m") for row in rows),
                "avg_vertical_oscillation_mm": average(row.get("vertical_oscillation_mm") for row in rows),
                "avg_ground_contact_time_ms": average(row.get("ground_contact_time_ms") for row in rows),
                "avg_ground_contact_balance_left_percent": average(
                    row.get("ground_contact_balance_left_percent") for row in rows
                ),
                "avg_vertical_ratio_percent": average(row.get("vertical_ratio_percent") for row in rows),
                "elevation_gain_m": _elevation_change(rows, gain=True),
                "elevation_loss_m": _elevation_change(rows, gain=False),
                "start_lat": rows[0].get("lat"),
                "start_lon": rows[0].get("lon"),
                "end_lat": rows[-1].get("lat"),
                "end_lon": rows[-1].get("lon"),
            }
        )
    return splits


def _duration_seconds(rows: list[dict[str, Any]]) -> float | None:
    start = as_float(rows[0].get("elapsed_seconds"))
    end = as_float(rows[-1].get("elapsed_seconds"))
    if start is not None and end is not None and end >= start:
        return end - start
    return None


def _elevation_change(rows: list[dict[str, Any]], *, gain: bool) -> float | None:
    values = [as_float(row.get("altitude_m")) for row in rows]
    values = [value for value in values if value is not None]
    if len(values) < 2:
        return None
    total = 0.0
    for before, after in zip(values, values[1:]):
        delta = after - before
        if gain and delta > 0:
            total += delta
        if not gain and delta < 0:
            total += abs(delta)
    return total
