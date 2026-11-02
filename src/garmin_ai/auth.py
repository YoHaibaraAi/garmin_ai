"""Interactive Garmin authentication helpers."""

from __future__ import annotations

from collections.abc import Callable
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .garmin_client import create_client
from .utils import GARMIN_IS_CN, safe_call


def login_interactive(
    email: str,
    password: str,
    token_dir: Path,
    prompt_mfa: Callable[[], str],
) -> None:
    """Login to Garmin Connect and save tokens to the token directory."""

    token_dir.mkdir(parents=True, exist_ok=True)
    client = create_client(email=email, password=password, prompt_mfa=prompt_mfa)
    if GARMIN_IS_CN:
        _disable_mobile_login_for_cn(client)
    # ``Garmin.login(tokenstore=...)`` loads an existing token before trying
    # the supplied credentials.  Authentication is an explicit fresh-login
    # command, so do not let an old token short-circuit it.
    tokenstore = os.environ.pop("GARMINTOKENS", None)
    try:
        result = safe_call(client.login)
    finally:
        if tokenstore is not None:
            os.environ["GARMINTOKENS"] = tokenstore
    if not result.ok:
        raise RuntimeError(result.error or "Garmin login failed")
    if not _save_extended_tokens(client, token_dir):
        raise RuntimeError("Garmin login succeeded but no usable token was returned")


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
    token_path = token_dir / "garmin_ai_tokens.json"
    # Replace atomically so an interrupted write cannot truncate the token store.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=token_dir, delete=False) as handle:
        temporary_path = Path(handle.name)
        try:
            json.dump(token_data, handle)
            handle.close()
            os.replace(temporary_path, token_path)
        finally:
            temporary_path.unlink(missing_ok=True)
    return True


def _serialize_cookies(client: Any) -> list[dict[str, Any]]:
    """Serialize the login session cookie jar without logging values."""

    cookies: list[dict[str, Any]] = []
    session = getattr(client, "cs", None)
    jar = getattr(session, "cookies", None)
    for cookie in getattr(jar, "jar", jar if jar is not None else []):
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
    jwt_web = getattr(client, "jwt_web", None)
    values = [
        f"{cookie['name']}={cookie['value']}"
        for cookie in cookies
        if not jwt_web or cookie["name"] != "JWT_WEB"
    ]
    if jwt_web:
        values.append(f"JWT_WEB={jwt_web}")
    return "; ".join(values)
