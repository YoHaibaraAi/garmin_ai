"""Tests for Garmin HTTP client configuration."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from garmin_ai.garmin_client import create_client


class CreateClientTests(unittest.TestCase):
    def test_system_proxy_environment_is_ignored_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            client = create_client().client

        self.assertFalse(client.cs.trust_env)
        self.assertFalse(client._api_session.trust_env)

    def test_system_proxy_environment_can_be_enabled_explicitly(self) -> None:
        with patch.dict(os.environ, {"GARMIN_AI_TRUST_ENV": "true"}, clear=True):
            client = create_client().client

        self.assertTrue(client.cs.trust_env)
        self.assertTrue(client._api_session.trust_env)


if __name__ == "__main__":
    unittest.main()
