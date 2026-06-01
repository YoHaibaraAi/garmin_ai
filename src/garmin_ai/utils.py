"""Small shared helpers for normalization, JSON output, and safe calls."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, TypeVar


T = TypeVar("T")


TOKEN_DIR = Path.home() / ".garminconnect"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
FIT_DIR = DATA_DIR / "fit"
EXPORTS_DIR = DATA_DIR / "exports"
GARMIN_IS_CN = True


@dataclass(slots=True)
class SafeResult:
    """Result wrapper for third-party API calls."""

    ok: bool
    value: Any = None
    error: str | None = None


def now_iso() -> str:
    """Return a timezone-aware timestamp for generated JSON."""

    return datetime.now(timezone.utc).astimezone().isoformat()


def today_str() -> str:
    """Return today's date in Garmin API format."""

    return date.today().isoformat()


def safe_call(func: Callable[..., T], *args: Any, **kwargs: Any) -> SafeResult:
    """Call a Garmin or parser function and capture failures as data."""

    try:
        return SafeResult(ok=True, value=func(*args, **kwargs))
    except Exception as exc:  # noqa: BLE001 - third-party clients raise broad exceptions
        return SafeResult(ok=False, error=str(exc) or exc.__class__.__name__)


def json_safe(value: Any) -> Any:
    """Recursively convert values into JSON-serializable primitives."""

    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:  # noqa: BLE001
            pass
    return value


def as_float(value: Any) -> float | None:
    """Best-effort numeric conversion."""

    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_int(value: Any) -> int | None:
    """Best-effort integer conversion."""

    number = as_float(value)
    return int(number) if number is not None else None


def first_present(data: Mapping[str, Any] | None, aliases: Iterable[str]) -> Any:
    """Return the first non-null value for a list of flat aliases."""

    if not isinstance(data, Mapping):
        return None
    for key in aliases:
        if key in data and data[key] is not None:
            return data[key]
    return None


def deep_get(data: Mapping[str, Any] | None, path: str) -> Any:
    """Read a dotted path from nested dictionaries."""

    current: Any = data
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def first_deep(data: Mapping[str, Any] | None, aliases: Iterable[str]) -> Any:
    """Return the first non-null flat or dotted-path value."""

    for alias in aliases:
        value = deep_get(data, alias) if "." in alias else first_present(data, [alias])
        if value is not None:
            return value
    return None


def find_first_number_by_keys(obj: Any, keys: Iterable[str]) -> float | None:
    """Recursively find the first numeric value whose key matches any alias."""

    wanted = {key.lower() for key in keys}
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            if str(key).lower() in wanted:
                number = as_float(value)
                if number is not None:
                    return number
        for value in obj.values():
            found = find_first_number_by_keys(value, wanted)
            if found is not None:
                return found
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            found = find_first_number_by_keys(item, wanted)
            if found is not None:
                return found
    return None


def extract_weight_value(obj: Any) -> float | None:
    """Extract a Garmin weight value and normalize grams to kilograms."""

    value = find_first_number_by_keys(
        obj,
        ["weight", "weightKg", "weight_kg", "bodyWeight", "value"],
    )
    if value is None:
        return None
    if value > 300:
        value = value / 1000.0
    return value


def calc_age_from_birth_date(birth_date: Any) -> int | None:
    """Calculate age from a Garmin birth date value without exposing the date."""

    parsed = _parse_date_like(birth_date)
    if parsed is None:
        return None
    today = date.today()
    years = today.year - parsed.year
    if (today.month, today.day) < (parsed.month, parsed.day):
        years -= 1
    return years if 0 <= years <= 130 else None


def pace_sec_per_km_from_speed(speed_mps: Any) -> float | None:
    """Convert speed in m/s to seconds per kilometer."""

    speed = as_float(speed_mps)
    if speed is None or speed <= 0:
        return None
    return 1000.0 / speed


def semicircles_to_degrees(value: Any) -> float | None:
    """Convert FIT semicircle coordinates to decimal degrees when needed."""

    coord = as_float(value)
    if coord is None:
        return None
    if abs(coord) <= 180:
        return coord
    return coord * (180.0 / 2**31)


def _parse_date_like(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).date()
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    for candidate in (text, text[:10]):
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            pass
    return None


def average(values: Iterable[Any]) -> float | None:
    """Average numeric values, ignoring nulls."""

    numbers = [v for v in (as_float(value) for value in values) if v is not None]
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def maximum(values: Iterable[Any]) -> float | None:
    """Maximum numeric value, ignoring nulls."""

    numbers = [v for v in (as_float(value) for value in values) if v is not None]
    return max(numbers) if numbers else None


def minimum(values: Iterable[Any]) -> float | None:
    """Minimum numeric value, ignoring nulls."""

    numbers = [v for v in (as_float(value) for value in values) if v is not None]
    return min(numbers) if numbers else None
