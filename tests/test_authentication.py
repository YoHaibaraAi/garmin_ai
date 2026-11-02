"""Authentication and token-store validation tests."""

from __future__ import annotations

import base64
import json
import stat
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from garmin_ai import auth, garmin_client
from garmin_ai.errors import AuthRequiredError
from garmin_ai.utils import GARMIN_IS_CN, SafeResult


def _jwt(exp: float) -> str:
    def encode(value: object) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    # Upstream rejects alg=none even when it only decodes expiry locally.
    # These tokens are synthetic; all HTTP in the integration tests is mocked.
    return f"{encode({'alg': 'RS256'})}.{encode({'exp': exp})}.signature"


def _token_client(connectapi: Mock | None = None, *, di_token: str | None = None) -> SimpleNamespace:
    api = SimpleNamespace(
        di_token=di_token,
        di_refresh_token="refresh-token",
        di_client_id="client-id",
        jwt_web=None,
        csrf_token=None,
        cs=SimpleNamespace(cookies=SimpleNamespace(jar=[])),
    )
    api.connectapi = connectapi or Mock()
    return SimpleNamespace(
        client=api,
        login=Mock(return_value=None),
        display_name=None,
        full_name=None,
        unit_system=None,
        garmin_connect_user_settings_url="/settings",
    )


def _write_token_store(root: Path, token: str) -> None:
    (root / "garmin_ai_tokens.json").write_text(
        json.dumps({"is_cn": GARMIN_IS_CN, "di_token": token}),
        encoding="utf-8",
    )


class InteractiveLoginTests(unittest.TestCase):
    def test_failed_login_does_not_overwrite_existing_extended_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token_dir = Path(directory)
            token_path = token_dir / "garmin_ai_tokens.json"
            token_path.write_text("old-token", encoding="utf-8")
            client = _token_client(di_token="stale-token")

            with (
                patch("garmin_ai.auth.create_client", return_value=client),
                patch("garmin_ai.auth._disable_mobile_login_for_cn"),
                patch(
                    "garmin_ai.auth.safe_call",
                    return_value=SafeResult(ok=False, error="401 Unauthorized"),
                ) as safe_call,
                self.assertRaises(RuntimeError),
            ):
                auth.login_interactive("user@example.com", "password", token_dir, lambda: "000000")

            safe_call.assert_called_once_with(client.login)
            self.assertEqual(token_path.read_text(encoding="utf-8"), "old-token")

    def test_successful_login_persists_extended_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token_dir = Path(directory)
            client = _token_client(di_token="fresh-token")

            with (
                patch("garmin_ai.auth.create_client", return_value=client),
                patch("garmin_ai.auth._disable_mobile_login_for_cn"),
                patch("garmin_ai.auth.safe_call", return_value=SafeResult(ok=True)) as safe_call,
            ):
                auth.login_interactive("user@example.com", "password", token_dir, lambda: "000000")

            safe_call.assert_called_once_with(client.login)
            stored = json.loads((token_dir / "garmin_ai_tokens.json").read_text(encoding="utf-8"))
            self.assertEqual(stored["di_token"], "fresh-token")


class TokenValidationTests(unittest.TestCase):
    def test_expired_extended_token_is_rejected_without_profile_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token_dir = Path(directory)
            _write_token_store(token_dir, _jwt(time.time() - 1))
            connectapi = Mock()
            client = _token_client(connectapi, di_token=None)

            self.assertFalse(garmin_client._load_extended_tokens(client, token_dir))
            connectapi.assert_not_called()

    def test_valid_extended_token_requires_profile_display_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token_dir = Path(directory)
            _write_token_store(token_dir, _jwt(time.time() + 3600))
            connectapi = Mock(return_value={"fullName": "No display name"})
            client = _token_client(connectapi)

            self.assertFalse(garmin_client._load_extended_tokens(client, token_dir))
            connectapi.assert_called_once_with("/userprofile-service/socialProfile")

    def test_valid_extended_token_with_profile_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token_dir = Path(directory)
            _write_token_store(token_dir, _jwt(time.time() + 3600))
            connectapi = Mock(
                side_effect=[
                    {"displayName": "runner", "fullName": "Runner"},
                    {"userData": {"measurementSystem": "metric"}},
                ]
            )
            client = _token_client(connectapi)

            self.assertTrue(garmin_client._load_extended_tokens(client, token_dir))
            self.assertEqual(client.display_name, "runner")
            self.assertEqual(client.unit_system, "metric")

    def test_invalid_extended_token_returns_auth_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token_dir = Path(directory)
            _write_token_store(token_dir, _jwt(time.time() - 1))
            client = _token_client()

            with patch("garmin_ai.garmin_client.create_client", return_value=client):
                with self.assertRaises(AuthRequiredError):
                    garmin_client.login_with_token(token_dir)

    def test_fallback_login_requires_loaded_display_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token_dir = Path(directory)
            client = SimpleNamespace(
                display_name=None,
                client=SimpleNamespace(di_token=_jwt(time.time() + 3600), jwt_web=None),
                login=Mock(return_value=None),
            )

            with patch("garmin_ai.garmin_client.create_client", return_value=client):
                with self.assertRaises(AuthRequiredError):
                    garmin_client.login_with_token(token_dir)

            client.login.assert_called_once_with(str(token_dir))

    def test_fallback_login_rejects_expired_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token_dir = Path(directory)
            client = SimpleNamespace(
                display_name="runner",
                client=SimpleNamespace(di_token=_jwt(time.time() - 1), jwt_web=None),
                login=Mock(return_value=None),
            )

            with patch("garmin_ai.garmin_client.create_client", return_value=client):
                with self.assertRaises(AuthRequiredError):
                    garmin_client.login_with_token(token_dir)


class TokenRefreshIntegrationTests(unittest.TestCase):
    """Exercise the installed Garmin request/refresh code with mocked HTTP only."""

    def _response(self, payload: dict, status: int = 200) -> Mock:
        return Mock(status_code=status, ok=status < 400, json=Mock(return_value=payload), text="")

    def _client(self):
        garmin = garmin_client.create_client()
        garmin.client._api_session.request = Mock(
            side_effect=lambda *args, **kwargs: self._response(
                {"displayName": "runner", "fullName": "Runner"}
                if "socialProfile" in args[1]
                else {"userData": {"measurementSystem": "metric"}}
            )
        )
        return garmin

    def _store(self, token_dir: Path, token: str) -> Path:
        token_path = token_dir / "garmin_ai_tokens.json"
        token_path.write_text(json.dumps({
            "is_cn": GARMIN_IS_CN,
            "di_token": token,
            "di_refresh_token": "old-refresh",
            "di_client_id": "client-id",
            "jwt_web": None,
            "csrf_token": None,
            "cookies": [],
            "cookie_header": None,
        }))
        return token_path

    def _refresh_response(self, garmin, fresh_token: str) -> Mock:
        post = Mock(return_value=self._response({
            "access_token": fresh_token, "refresh_token": "rotated-refresh",
        }))
        garmin.client._http_post = post
        return post

    def test_expired_access_token_refreshes_and_survives_next_process(self) -> None:
        for remaining_seconds in (-60, 60):
            with self.subTest(remaining_seconds=remaining_seconds), tempfile.TemporaryDirectory() as directory:
                token_dir = Path(directory)
                token_path = self._store(token_dir, _jwt(time.time() + remaining_seconds))
                fresh_token = _jwt(time.time() + 7200)
                garmin = self._client()
                post = self._refresh_response(garmin, fresh_token)

                with patch.object(garmin_client, "create_client", return_value=garmin):
                    self.assertIs(garmin_client.login_with_token(token_dir), garmin)

                post.assert_called_once()
                self.assertIn("diauth.garmin.cn/", post.call_args.args[0])
                self.assertEqual(post.call_args.kwargs["data"]["refresh_token"], "old-refresh")
                stored = json.loads(token_path.read_text())
                self.assertEqual(stored["di_token"], fresh_token)
                self.assertEqual(stored["di_refresh_token"], "rotated-refresh")
                self.assertEqual(stored["is_cn"], GARMIN_IS_CN)
                self.assertIn("cookies", stored)
                self.assertIn("jwt_web", stored)
                self.assertEqual(stat.S_IMODE(token_path.stat().st_mode), 0o600)

                next_client = self._client()
                next_client.client._http_post = Mock(side_effect=AssertionError("Unnecessary refresh"))
                with patch.object(garmin_client, "create_client", return_value=next_client):
                    self.assertIs(garmin_client.login_with_token(token_dir), next_client)
                next_client.client._http_post.assert_not_called()
                self.assertEqual(next_client.client.di_refresh_token, "rotated-refresh")

    def test_failed_refresh_requires_auth_and_preserves_token_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token_dir = Path(directory)
            token_path = self._store(token_dir, _jwt(time.time() - 60))
            original = token_path.read_text()
            garmin = self._client()
            garmin.client._http_post = Mock(return_value=self._response({}, 400))
            garmin.login = Mock(side_effect=AssertionError("Must not attempt credential login"))

            with patch.object(garmin_client, "create_client", return_value=garmin):
                with self.assertRaises(AuthRequiredError):
                    garmin_client.login_with_token(token_dir)

            self.assertEqual(token_path.read_text(), original)
            garmin.client._api_session.request.assert_not_called()
            garmin.login.assert_not_called()

    def test_runtime_401_refresh_keeps_extended_schema_and_rotated_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token_dir = Path(directory)
            token_path = self._store(token_dir, _jwt(time.time() + 7200))
            garmin = self._client()
            self.assertTrue(garmin_client._load_extended_tokens(garmin, token_dir))
            fresh_token = _jwt(time.time() + 14400)
            post = self._refresh_response(garmin, fresh_token)
            garmin.client._api_session.request.side_effect = [
                self._response({}, 401), self._response({"activities": []}),
            ]

            self.assertEqual(garmin.client.connectapi("/activities"), {"activities": []})

            post.assert_called_once()
            stored = json.loads(token_path.read_text())
            self.assertEqual(stored["is_cn"], GARMIN_IS_CN)
            self.assertEqual(stored["di_refresh_token"], "rotated-refresh")
            self.assertEqual(stored["di_token"], fresh_token)
            self.assertEqual(
                garmin.client._api_session.request.call_args.kwargs["headers"]["Authorization"],
                f"Bearer {fresh_token}",
            )

    def test_region_mismatch_never_uses_saved_refresh_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token_dir = Path(directory)
            token_path = self._store(token_dir, _jwt(time.time() - 60))
            data = json.loads(token_path.read_text())
            data["is_cn"] = not GARMIN_IS_CN
            token_path.write_text(json.dumps(data))
            garmin = self._client()
            garmin.client._http_post = Mock()

            self.assertFalse(garmin_client._load_extended_tokens(garmin, token_dir))
            garmin.client._http_post.assert_not_called()
            garmin.client._api_session.request.assert_not_called()

    def test_legacy_cookie_header_retains_other_cookies_after_jwt_rotation(self) -> None:
        garmin = self._client()
        garmin.client.jwt_web = "new-jwt"
        garmin_client._patch_cookie_header(
            garmin.client, "JWT_WEB=old-jwt; browser-session=session=value",
        )
        self.assertEqual(
            garmin.client.get_api_headers()["Cookie"],
            "JWT_WEB=new-jwt; browser-session=session=value",
        )

    def test_jwt_web_refresh_uses_current_cookie_and_keeps_browser_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token_dir = Path(directory)
            old_token = _jwt(time.time() - 60)
            fresh_token = _jwt(time.time() + 7200)
            token_path = token_dir / "garmin_ai_tokens.json"
            token_path.write_text(json.dumps({
                "is_cn": GARMIN_IS_CN,
                "jwt_web": old_token,
                "cookies": [
                    {"name": "JWT_WEB", "value": old_token, "domain": ".garmin.cn"},
                    {"name": "browser-session", "value": "session", "domain": ".garmin.cn"},
                ],
                "cookie_header": f"JWT_WEB={old_token}; browser-session=session",
            }))
            garmin = self._client()

            def refresh():
                garmin.client.jwt_web = fresh_token
                garmin.client.dump(str(token_path))

            garmin.client._refresh_session = Mock(side_effect=refresh)
            self.assertTrue(garmin_client._load_extended_tokens(garmin, token_dir))
            header = garmin.client.get_api_headers()["Cookie"]
            self.assertIn(f"JWT_WEB={fresh_token}", header)
            self.assertNotIn(old_token, header)
            self.assertIn("browser-session=session", header)
            stored = json.loads(token_path.read_text())
            self.assertEqual(stored["jwt_web"], fresh_token)
            self.assertEqual(len(stored["cookies"]), 2)
            self.assertIn(f"JWT_WEB={fresh_token}", stored["cookie_header"])


if __name__ == "__main__":
    unittest.main()
