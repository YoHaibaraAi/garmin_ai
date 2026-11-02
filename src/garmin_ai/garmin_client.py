"""Thin, safe wrapper around python-garminconnect."""

from __future__ import annotations

import base64
import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .errors import AuthRequiredError
from .utils import GARMIN_IS_CN, SafeResult, extract_weight_value, find_first_number_by_keys, safe_call, today_str

_VO2_KEYS = [
    "vo2max",
    "vo2Max",
    "vo2MaxValue",
    "genericVO2Max",
    "runningVO2Max",
    "cyclingVO2Max",
    "currentVO2Max",
    "fitnessAgeVO2Max",
]


def create_client(**kwargs: Any) -> Any:
    """Create a Garmin client without doing network work at import time."""

    from garminconnect import Garmin

    garmin = Garmin(is_cn=GARMIN_IS_CN, **kwargs)
    _configure_requests_sessions(garmin)
    return garmin


def _configure_requests_sessions(garmin: Any) -> None:
    """Keep local OS proxies from intercepting Garmin TLS by default.

    Requests reads macOS System Configuration proxies when ``trust_env`` is
    enabled, even when no HTTP(S)_PROXY environment variable is present. A
    local HTTPS inspection proxy can then replace Garmin's valid certificate
    with an untrusted self-signed certificate. Users who intentionally require
    their system proxy can opt back in with ``GARMIN_AI_TRUST_ENV=1``.
    """

    trust_env = os.getenv("GARMIN_AI_TRUST_ENV", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    client = getattr(garmin, "client", None)
    if client is None:
        return
    for session_name in ("cs", "_api_session"):
        session = getattr(client, session_name, None)
        if session is not None and hasattr(session, "trust_env"):
            session.trust_env = trust_env


def login_with_token(token_dir: Path) -> Any:
    """Authenticate using the local Garmin token store."""

    client = create_client()
    extended_token_path = token_dir / "garmin_ai_tokens.json"
    if extended_token_path.exists():
        if _load_extended_tokens(client, token_dir):
            return client
        raise AuthRequiredError(
            "Garmin token is missing, expired, or profile validation failed. "
            "Run: garmin-ai auth"
        )

    result = safe_call(client.login, str(token_dir))
    if (
        not result.ok
        or not _has_valid_expiry(_active_auth_token(client))
        or not has_display_name(client)
    ):
        raise AuthRequiredError(
            "Garmin token is missing, expired, or profile validation failed. "
            "Run: garmin-ai auth"
        )
    return client


def _load_extended_tokens(garmin: Any, token_dir: Path) -> bool:
    """Load and validate garmin-ai extended token state."""

    token_path = token_dir / "garmin_ai_tokens.json"
    if not token_path.exists():
        return False
    try:
        data = json.loads(token_path.read_text(encoding="utf-8"))
        if data.get("is_cn") != GARMIN_IS_CN:
            return False
        di_token = data.get("di_token")
        jwt_web = data.get("jwt_web")
        active_token = di_token or jwt_web
        if not isinstance(active_token, str) or not active_token:
            return False
        client = garmin.client
        client.di_token = di_token
        client.di_refresh_token = data.get("di_refresh_token")
        client.di_client_id = data.get("di_client_id")
        client.jwt_web = jwt_web
        client.csrf_token = data.get("csrf_token")
        _restore_cookies(client, data)
        _patch_cookie_header(client, data.get("cookie_header"))
        _configure_token_persistence(garmin, token_dir)
        if not _has_valid_expiry(active_token):
            # Access-token expiry is recoverable while refresh credentials or
            # a saved browser session remain usable. Never prompt for MFA here.
            can_refresh = (
                bool(client.di_refresh_token and client.di_client_id)
                if di_token
                else bool(data.get("cookies"))
            )
            if not can_refresh:
                return False
            result = safe_call(client._refresh_session)
            if not result.ok or not _has_valid_expiry(_active_auth_token(garmin)):
                return False
        if not _hydrate_profile(garmin) or not _has_valid_expiry(_active_auth_token(garmin)):
            return False
        client.dump(str(token_path))
        return True
    except Exception:
        return False


def _configure_token_persistence(garmin: Any, token_dir: Path) -> None:
    """Keep upstream refreshes from overwriting our extended token schema."""

    # Imported here because interactive auth uses create_client from this module.
    from .auth import _save_extended_tokens

    def dump_extended_tokens(_path: str) -> None:
        if not _save_extended_tokens(garmin, token_dir):
            raise RuntimeError("No usable Garmin token to save")

    garmin.client.dump = dump_extended_tokens
    garmin.client._tokenstore_path = str(token_dir / "garmin_ai_tokens.json")


def _has_valid_expiry(token: Any) -> bool:
    """Return whether a JWT token has a parseable, future expiration time."""

    if not isinstance(token, str) or not token:
        return False
    parts = token.split(".")
    if len(parts) < 2:
        return False
    try:
        encoded_payload = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded_payload).decode())
        expires_at = float(payload["exp"])
    except Exception:
        return False
    return expires_at > time.time()


def _active_auth_token(garmin: Any) -> Any:
    """Return the token the Garmin client will use for API requests."""

    client = getattr(garmin, "client", None)
    return getattr(client, "di_token", None) or getattr(client, "jwt_web", None)


def _restore_cookies(client: Any, data: dict[str, Any]) -> None:
    """Restore saved login cookies for JWT_WEB fallback auth."""

    cookies = data.get("cookies")
    if not isinstance(cookies, list):
        return

    import requests

    for cookie in cookies:
        if not isinstance(cookie, dict) or not cookie.get("name"):
            continue
        restored = requests.cookies.create_cookie(
            name=str(cookie.get("name")),
            value=str(cookie.get("value") or ""),
            domain=str(cookie.get("domain") or ""),
            path=str(cookie.get("path") or "/"),
            secure=bool(cookie.get("secure")),
            expires=cookie.get("expires"),
        )
        client.cs.cookies.set_cookie(restored)


def _patch_cookie_header(client: Any, cookie_header: Any) -> None:
    """Use the full saved browser cookie header when JWT_WEB is the auth path."""

    if not isinstance(cookie_header, str) or not cookie_header:
        return
    original_get_api_headers = client.get_api_headers

    def get_api_headers_with_saved_cookies() -> dict[str, str]:
        headers = original_get_api_headers()
        if getattr(client, "jwt_web", None) and not getattr(client, "di_token", None):
            # Keep other browser cookies, but use the current JWT after refresh.
            from .auth import _cookie_header

            cookies: dict[str, str] = {}
            for source in (cookie_header, _cookie_header(client) or ""):
                for item in source.split(";"):
                    name, separator, value = item.strip().partition("=")
                    if name and separator:
                        cookies[name] = value
            cookies["JWT_WEB"] = client.jwt_web
            headers["Cookie"] = "; ".join(f"{name}={value}" for name, value in cookies.items())
        return headers

    client.get_api_headers = get_api_headers_with_saved_cookies


def _hydrate_profile(garmin: Any) -> bool:
    """Hydrate and validate the profile after token-only login."""

    profile_result = safe_call(garmin.client.connectapi, "/userprofile-service/socialProfile")
    if not profile_result.ok or not isinstance(profile_result.value, dict):
        return False
    display_name = profile_result.value.get("displayName")
    if not display_name:
        return False
    garmin.display_name = display_name
    garmin.full_name = profile_result.value.get("fullName") or garmin.full_name

    settings_result = safe_call(garmin.client.connectapi, garmin.garmin_connect_user_settings_url)
    if settings_result.ok and isinstance(settings_result.value, dict):
        user_data = settings_result.value.get("userData")
        if isinstance(user_data, dict):
            garmin.unit_system = user_data.get("measurementSystem") or garmin.unit_system
    return True


def has_display_name(client: Any) -> bool:
    """Return whether the Garmin wrapper has a display name loaded."""

    return bool(getattr(client, "display_name", None))


def safe_garmin_call(client: Any, method_name: str, *args: Any, **kwargs: Any) -> SafeResult:
    """Call a Garmin client method and return a structured result."""

    method = getattr(client, method_name, None)
    if method is None:
        return SafeResult(ok=False, error=f"Garmin client has no method {method_name}")
    return safe_call(method, *args, **kwargs)


def get_recent_running_activities(client: Any, limit: int = 1) -> dict[str, Any]:
    """Return recent running activities with local fallback filtering."""

    first = safe_garmin_call(client, "get_activities", 0, limit, activitytype="running")
    if first.ok:
        activities = first.value if isinstance(first.value, list) else []
        return {"activities": activities[:limit], "data_quality": {}}

    fallback_limit = max(limit * 5, limit, 20)
    fallback = safe_garmin_call(client, "get_activities", 0, fallback_limit)
    if not fallback.ok:
        return {
            "activities": [],
            "data_quality": {"recent_runs": {"status": "error", "message": fallback.error or first.error}},
        }

    activities = fallback.value if isinstance(fallback.value, list) else []
    running = [activity for activity in activities if _is_running_activity(activity)]
    return {
        "activities": running[:limit],
        "data_quality": {
            "recent_runs": {
                "status": "partial",
                "message": f"activitytype filter failed: {first.error}",
            }
        },
    }


def get_profile(client: Any) -> dict[str, Any]:
    """Fetch profile-shaped Garmin data using safe calls."""

    data: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for key, method in {
        "user_profile": "get_user_profile",
        "userprofile_settings": "get_userprofile_settings",
    }.items():
        result = safe_garmin_call(client, method)
        if result.ok:
            data[key] = result.value
        else:
            data[key] = None
            errors[key] = result.error or "unknown error"
    result = safe_call(client.client.connectapi, "/userprofile-service/userprofile/user-settings")
    if result.ok:
        data["user_settings_raw"] = result.value
    else:
        data["user_settings_raw"] = None
        errors["user_settings_raw"] = result.error or "unknown error"

    device_sources = get_device_setting_sources(client)
    data.update(device_sources)
    if device_sources.get("_errors"):
        errors.update({f"device_sources.{key}": value for key, value in device_sources["_errors"].items()})
    data["_errors"] = errors
    return data


def get_device_setting_sources(client: Any) -> dict[str, Any]:
    """Fetch Garmin device/settings payloads that may contain profile limits."""

    data: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for key, method in (
        ("devices", "get_devices"),
        ("device_last_used", "get_device_last_used"),
        ("primary_training_device", "get_primary_training_device"),
    ):
        result = safe_garmin_call(client, method)
        if result.ok:
            data[key] = result.value
        else:
            data[key] = None
            errors[key] = result.error or "unknown error"

    settings: dict[str, Any] = {}
    settings_errors: dict[str, str] = {}
    method = getattr(client, "get_device_settings", None)
    if method is None:
        errors["device_settings"] = "Garmin client has no method get_device_settings"
    else:
        for device_id in _collect_device_ids(data):
            result = safe_call(method, device_id)
            if result.ok:
                settings[str(device_id)] = result.value
            else:
                settings_errors[str(device_id)] = result.error or "unknown error"

    data["device_settings"] = settings
    if settings_errors:
        errors["device_settings"] = f"{len(settings_errors)} device settings calls failed"
        data["_device_settings_errors"] = settings_errors
    data["_errors"] = errors
    return data


def get_current_metrics(client: Any) -> dict[str, Any]:
    """Fetch today's body and wellness metrics."""

    return get_day_metrics(client, today_str())


def get_day_metrics(client: Any, cdate: str) -> dict[str, Any]:
    """Fetch metrics for a specific date, never raising on individual failures."""

    data: dict[str, Any] = {"date": cdate}
    errors: dict[str, str] = {}
    calls: dict[str, tuple[str, tuple[Any, ...], bool]] = {
        "user_summary": ("get_user_summary", (cdate,), True),
        "stats": ("get_stats", (cdate,), True),
        "stats_and_body": ("get_stats_and_body", (cdate,), True),
        "heart_rates": ("get_heart_rates", (cdate,), True),
        "hrv": ("get_hrv_data", (cdate,), False),
        "body_composition": ("get_body_composition", (cdate, cdate), False),
    }
    for key, (method, args, needs_display_name) in calls.items():
        if needs_display_name and not has_display_name(client):
            data[key] = None
            errors[key] = (
                "Display name is not loaded from Garmin profile; this endpoint "
                "requires Garmin displayName. Check Garmin China profile visibility "
                "or token permissions."
            )
            continue
        result = safe_garmin_call(client, method, *args)
        if result.ok:
            data[key] = result.value
        else:
            data[key] = None
            errors[key] = result.error or "unknown error"
    data["_errors"] = errors
    return data


def get_weight_sources(client: Any, cdate: str, days: int = 90) -> dict[str, Any]:
    """Fetch raw weight sources with 90-day fallbacks."""

    end_date = _parse_date(cdate)
    start_date = end_date - timedelta(days=days - 1)
    start = start_date.isoformat()
    end = end_date.isoformat()
    data: dict[str, Any] = {"start_date": start, "end_date": end}
    errors: dict[str, str] = {}

    for key, method, args in (
        ("weigh_ins", "get_weigh_ins", (start, end)),
        ("body_composition_range", "get_body_composition", (start, end)),
    ):
        result = safe_garmin_call(client, method, *args)
        if result.ok:
            data[key] = result.value
            if extract_weight_value(result.value) is not None:
                data["_errors"] = errors
                return data
        else:
            data[key] = None
            errors[key] = result.error or "unknown error"

    daily: dict[str, Any] = {}
    daily_errors: dict[str, str] = {}
    for day in _date_strings(start_date, end_date):
        result = safe_garmin_call(client, "get_daily_weigh_ins", day)
        if result.ok:
            daily[day] = result.value
        else:
            daily_errors[day] = result.error or "unknown error"
    data["daily_weigh_ins"] = daily
    if daily_errors:
        errors["daily_weigh_ins"] = f"{len(daily_errors)} daily calls failed"
        data["_daily_errors"] = daily_errors

    data["_errors"] = errors
    return data


def get_vo2max_sources(client: Any, cdate: str, days: int = 60) -> dict[str, Any]:
    """Fetch raw VO2max sources with ordered fallbacks."""

    end_date = _parse_date(cdate)
    start_date = end_date - timedelta(days=days - 1)
    data: dict[str, Any] = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "max_metrics": {},
        "training_status": {},
        "fitnessage": {},
    }
    errors: dict[str, Any] = {}

    for key, method in (
        ("max_metrics", "get_max_metrics"),
        ("training_status", "get_training_status"),
        ("fitnessage", "get_fitnessage_data"),
    ):
        per_day: dict[str, Any] = {}
        per_errors: dict[str, str] = {}
        for day in reversed(list(_date_strings(start_date, end_date))):
            result = safe_garmin_call(client, method, day)
            if result.ok:
                per_day[day] = result.value
                if find_first_number_by_keys(result.value, _VO2_KEYS) is not None:
                    data[key] = per_day
                    data["_errors"] = errors
                    return data
            else:
                per_errors[day] = result.error or "unknown error"
        data[key] = per_day
        if per_errors:
            errors[key] = f"{len(per_errors)} daily calls failed"
            data[f"_{key}_errors"] = per_errors

    activities = get_recent_running_activities(client, 20)
    data["recent_running_activities"] = activities.get("activities", [])
    if activities.get("data_quality"):
        errors["recent_running_activities"] = activities["data_quality"]

    data["_errors"] = errors
    return data


def get_debug_metrics_raw(client: Any, cdate: str) -> dict[str, Any]:
    """Collect raw metric debug payloads, isolating every interface failure."""

    target = _parse_date(cdate)
    start = (target - timedelta(days=89)).isoformat()
    end = target.isoformat()
    debug: dict[str, Any] = {"date": end, "start_90_days": start, "end_90_days": end}
    debug["client_methods_filtered"] = [
        name
        for name in dir(client)
        if any(keyword in name.lower() for keyword in ("device", "settings", "zone", "heart"))
    ]

    debug["userprofile_settings"] = _debug_call(
        "connectapi:/userprofile-service/userprofile/user-settings",
        client.client.connectapi,
        "/userprofile-service/userprofile/user-settings",
    )
    debug["user_settings"] = debug["userprofile_settings"]
    debug["social_profile"] = _debug_call(
        "connectapi:/userprofile-service/socialProfile",
        client.client.connectapi,
        "/userprofile-service/socialProfile",
    )
    debug["devices"] = _debug_method_call(client, "get_devices")
    debug["device_last_used"] = _debug_method_call(client, "get_device_last_used")
    debug["primary_training_device"] = _debug_method_call(client, "get_primary_training_device")
    debug["device_settings"] = _debug_device_settings(client, debug)
    for key, method, args in (
        ("user_summary", "get_user_summary", (end,)),
        ("heart_rates", "get_heart_rates", (end,)),
        ("rhr_day", "get_rhr_day", (end,)),
        ("hrv_data", "get_hrv_data", (end,)),
        ("daily_weigh_ins", "get_daily_weigh_ins", (end,)),
        ("weigh_ins_last_90_days", "get_weigh_ins", (start, end)),
        ("body_composition_last_90_days", "get_body_composition", (start, end)),
        ("max_metrics", "get_max_metrics", (end,)),
        ("training_status", "get_training_status", (end,)),
        ("fitnessage_data", "get_fitnessage_data", (end,)),
        ("race_predictions", "get_race_predictions", ()),
    ):
        func = getattr(client, method, None)
        debug[key] = _debug_call(method, func, *args) if func else {"ok": False, "error": f"missing method {method}"}
    return debug


def _debug_method_call(client: Any, method: str) -> dict[str, Any]:
    func = getattr(client, method, None)
    if func is None:
        return {"ok": False, "error": f"missing method {method}"}
    return _debug_call(method, func)


def _debug_device_settings(client: Any, debug: dict[str, Any]) -> dict[str, Any]:
    func = getattr(client, "get_device_settings", None)
    if func is None:
        return {"ok": False, "error": "missing method get_device_settings", "data": {}}

    ids = _collect_device_ids(
        {
            "devices": _debug_data(debug.get("devices")),
            "device_last_used": _debug_data(debug.get("device_last_used")),
            "primary_training_device": _debug_data(debug.get("primary_training_device")),
        }
    )
    results: dict[str, Any] = {}
    for device_id in ids:
        results[str(device_id)] = _debug_call("get_device_settings", func, device_id)
    return {"ok": True, "data": results}


def _debug_data(payload: Any) -> Any:
    return payload.get("data") if isinstance(payload, dict) and payload.get("ok") else None


def get_connect_splits(client: Any, activity_id: str) -> dict[str, Any]:
    """Fetch all known Garmin Connect split endpoints."""

    response: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for key, method in {
        "splits": "get_activity_splits",
        "typed_splits": "get_activity_typed_splits",
        "split_summaries": "get_activity_split_summaries",
    }.items():
        result = safe_garmin_call(client, method, str(activity_id))
        if result.ok:
            response[key] = result.value
        else:
            response[key] = None
            errors[key] = result.error or "unknown error"
    response["_errors"] = errors
    return response


def _debug_call(name: str, func: Any, *args: Any) -> dict[str, Any]:
    result = safe_call(func, *args)
    if result.ok:
        return {"ok": True, "data": result.value}
    return {"ok": False, "error": result.error or f"{name} failed"}


def _collect_device_ids(obj: Any) -> list[str]:
    """Return stable candidate device IDs from Garmin device payloads."""

    ids: list[str] = []
    id_keys = {
        "deviceId",
        "device_id",
        "deviceIdPk",
        "deviceIdPK",
        "unitId",
        "unitID",
        "id",
        "activityTrackerDeviceId",
    }

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in id_keys:
                    normalized = _normalize_device_id(child)
                    if normalized is not None and normalized not in ids:
                        ids.append(normalized)
                if isinstance(child, (dict, list, tuple)):
                    visit(child)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    visit(obj)
    return ids


def _normalize_device_id(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = int(float(text))
    except ValueError:
        return None
    if number <= 0:
        return None
    return str(number)


def _parse_date(value: str) -> date:
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


def _date_strings(start: date, end: date) -> list[str]:
    days = (end - start).days
    return [(start + timedelta(days=offset)).isoformat() for offset in range(days + 1)]


def download_original_activity(client: Any, activity_id: str, output_dir: Path) -> bytes:
    """Download original activity bytes from Garmin Connect."""

    output_dir.mkdir(parents=True, exist_ok=True)
    from garminconnect import Garmin

    result = safe_garmin_call(client, "download_activity", str(activity_id), Garmin.ActivityDownloadFormat.ORIGINAL)
    if not result.ok or not isinstance(result.value, bytes):
        raise RuntimeError(result.error or "download_activity did not return bytes")
    return result.value


def _is_running_activity(activity: Any) -> bool:
    if not isinstance(activity, dict):
        return False
    activity_type = activity.get("activityType") or activity.get("activityTypeDTO") or {}
    type_key = activity_type.get("typeKey") if isinstance(activity_type, dict) else activity_type
    text = str(type_key or activity.get("activity_type") or activity.get("activityName") or "").lower()
    return "run" in text or "running" in text
