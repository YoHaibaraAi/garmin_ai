"""Tests for auth credentials loaded from local config."""

from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from garmin_ai import cli, config


class AuthConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_auth_uses_email_and_password_from_config_without_prompting(self) -> None:
        with (
            patch.object(cli, "load_config", return_value={"email": " runner@example.com ", "password": "secret"}),
            patch.object(cli, "login_interactive") as login_interactive,
            patch.object(cli.typer, "prompt") as prompt,
        ):
            result = self.runner.invoke(cli.app, ["auth"])

        self.assertEqual(result.exit_code, 0, result.output)
        prompt.assert_not_called()
        args = login_interactive.call_args.args
        self.assertEqual(args[:3], ("runner@example.com", "secret", cli.TOKEN_DIR))

    def test_auth_prompts_only_for_missing_password(self) -> None:
        with (
            patch.object(cli, "load_config", return_value={"email": "runner@example.com"}),
            patch.object(cli, "login_interactive") as login_interactive,
            patch.object(cli.typer, "prompt", return_value="prompted-secret") as prompt,
        ):
            result = self.runner.invoke(cli.app, ["auth"])

        self.assertEqual(result.exit_code, 0, result.output)
        prompt.assert_called_once_with("Garmin password", hide_input=True)
        self.assertEqual(login_interactive.call_args.args[:2], ("runner@example.com", "prompted-secret"))

    def test_config_show_redacts_password(self) -> None:
        with patch.object(
            cli,
            "load_config",
            return_value={"email": "runner@example.com", "password": "secret"},
        ):
            result = self.runner.invoke(cli.app, ["config", "show"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("********", result.output)
        self.assertNotIn("secret", result.output)

    def test_config_set_password_prompts_without_echoing_secret(self) -> None:
        with (
            patch.object(cli.typer, "prompt", return_value="secret") as prompt,
            patch.object(cli, "set_config_value", return_value=Path("/tmp/config.json")) as set_value,
        ):
            result = self.runner.invoke(cli.app, ["config", "set", "password"])

        self.assertEqual(result.exit_code, 0, result.output)
        prompt.assert_called_once_with("Garmin password", hide_input=True)
        set_value.assert_called_once_with("password", "secret")
        self.assertIn("********", result.output)
        self.assertNotIn("secret", result.output)

    def test_save_config_restricts_file_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / ".garmin-ai" / "config.json"
            with patch.object(config, "CONFIG_PATH", config_path):
                config.save_config({"email": "runner@example.com", "password": "secret"})

            mode = stat.S_IMODE(config_path.stat().st_mode)
            self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
