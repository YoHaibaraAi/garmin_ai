"""Interactive Garmin authentication helpers."""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from typing import Any

from .utils import GARMIN_IS_CN, safe_call


def login_interactive(
    email: str,
    password: str,
    token_dir: Path,
    prompt_mfa: Callable[[], str],
) -> None:
    """Login to Garmin Connect and save tokens to the token directory."""

    from garminconnect import Garmin

    token_dir.mkdir(parents=True, exist_ok=True)
    client = Garmin(email=email, password=password, is_cn=GARMIN_IS_CN, prompt_mfa=prompt_mfa)
    if GARMIN_IS_CN:
        _disable_mobile_login_for_cn(client)
    result = safe_call(client.login, str(token_dir))
    if result.ok:
        _save_extended_tokens(client, token_dir)
        return
    if _save_extended_tokens(client, token_dir):
        return
    if not result.ok:
        raise RuntimeError(result.error or "Garmin login failed")


def _disable_mobile_login_for_cn(garmin: object) -> None:
    """Force Garmin China auth to use web/portal login instead of mobile login.

    garminconnect v0.3.4 uses a domain-aware `garmin.cn` client, but the mobile
    MFA ticket-consumption URL is still hard-coded to `mobile.integration.garmin.com`.
    The widget strategy can also land on a CN page title it does not recognize.
    CN auth should therefore skip mobile/widget and fall through to portal.
    """

    from garminconnect.exceptions import GarminConnectConnectionError

    client = getattr(garmin, "client", None)
    if client is None:
        return

    def _skip_mobile(*_args: object, **_kwargs: object) -> None:
        raise GarminConnectConnectionError("Skipping mobile login for Garmin China")

    def _skip_widget(*_args: object, **_kwargs: object) -> None:
        raise GarminConnectConnectionError("Skipping widget login for Garmin China")

    client._mobile_login_cffi = _skip_mobile  # type: ignore[attr-defined]
    client._mobile_login_requests = _skip_mobile  # type: ignore[attr-defined]
    client._widget_web_login = _skip_widget  # type: ignore[attr-defined]


def _save_extended_tokens(garmin: object, token_dir: Path) -> bool:
    """Persist DI or JWT_WEB auth state.

    garminconnect v0.3.4 dumps DI tokens. Garmin China login can still fall back
    to JWT_WEB and then fail while fetching social profile, even though the
    JWT_WEB session itself was established. This project stores that JWT_WEB
    token separately so later CLI commands can still authenticate.
    """

    client: Any = getattr(garmin, "client", None)
    if client is None:
        return False

    token_data = {
        "di_token": getattr(client, "di_token", None),
        "di_refresh_token": getattr(client, "di_refresh_token", None),
        "di_client_id": getattr(client, "di_client_id", None),
        "jwt_web": getattr(client, "jwt_web", None),
        "csrf_token": getattr(client, "csrf_token", None),
        "cookies": _serialize_cookies(client),
        "cookie_header": _cookie_header(client),
        "is_cn": GARMIN_IS_CN,
    }
    if not any(token_data.get(key) for key in ("di_token", "jwt_web")):
        return False

    token_dir.mkdir(parents=True, exist_ok=True)
    (token_dir / "garmin_ai_tokens.json").write_text(json.dumps(token_data), encoding="utf-8")
    return True


def _serialize_cookies(client: Any) -> list[dict[str, Any]]:
    """Serialize the login session cookie jar without logging values."""

    cookies: list[dict[str, Any]] = []
    session = getattr(client, "cs", None)
    jar = getattr(session, "cookies", None)
    for cookie in getattr(jar, "jar", []):
        cookies.append(
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
                "secure": cookie.secure,
                "expires": cookie.expires,
            }
        )
    return cookies


def _cookie_header(client: Any) -> str | None:
    """Build a browser-like Cookie header from the login session."""

    cookies = _serialize_cookies(client)
    if not cookies:
        jwt_web = getattr(client, "jwt_web", None)
        return f"JWT_WEB={jwt_web}" if jwt_web else None
    return "; ".join(f"{cookie['name']}={cookie['value']}" for cookie in cookies)
