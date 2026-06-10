"""tests/test_production_guard.py — Production preflight / config-gate tests.

Verifies that config.production_issues()/production_preflight() correctly:
  • report insecure demo defaults,
  • only HARD-FAIL when APP_ENV=production,
  • pass cleanly once real credentials, salt, and model HMAC key are provided.

auth_mock imports streamlit, so we install a minimal stub before importing it
(same pattern as test_auth_bypass).
"""

import importlib
import os
import sys
import types
import unittest
from unittest.mock import MagicMock


class _SessionState(dict):
    def clear(self):
        super().clear()


_st_stub = types.ModuleType("streamlit")
_st_stub.session_state = _SessionState()
for _name in ("stop", "rerun", "error", "warning", "markdown",
              "text_input", "form", "form_submit_button"):
    setattr(_st_stub, _name, MagicMock())
sys.modules["streamlit"] = _st_stub

import auth_mock   # noqa: E402  (after stub install)
import config      # noqa: E402

_ENV_KEYS = ["APP_ENV", "AUTH_USERS_JSON", "AUTH_PWD_SALT", "MODEL_REGISTRY_HMAC_KEY"]


class _EnvIsolated(unittest.TestCase):
    """Save/restore the env vars the guard reads, and reset auth_mock state."""

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in _ENV_KEYS}
        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        importlib.reload(auth_mock)   # rebuild user store under cleared env

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        importlib.reload(auth_mock)


class TestEnvHelpers(_EnvIsolated):
    def test_default_env_is_not_production(self):
        self.assertEqual(config.app_env(), "development")
        self.assertFalse(config.is_production())

    def test_production_env_detected(self):
        os.environ["APP_ENV"] = "production"
        self.assertTrue(config.is_production())
        os.environ["APP_ENV"] = "PROD"   # case-insensitive
        self.assertTrue(config.is_production())


class TestDemoDefaults(_EnvIsolated):
    def test_demo_defaults_report_all_issues(self):
        issues = config.production_issues()
        joined = " ".join(issues).lower()
        self.assertIn("demo", joined)
        self.assertIn("salt", joined)
        self.assertIn("hmac", joined)
        self.assertGreaterEqual(len(issues), 3)

    def test_preflight_warns_but_does_not_raise_in_dev(self):
        # development env: issues returned, no exception
        issues = config.production_preflight()
        self.assertTrue(issues)

    def test_preflight_raises_in_production_with_demo_defaults(self):
        os.environ["APP_ENV"] = "production"
        with self.assertRaises(RuntimeError) as ctx:
            config.production_preflight()
        self.assertIn("Refusing to start", str(ctx.exception))


class TestFullyConfigured(_EnvIsolated):
    def test_no_issues_when_properly_configured(self):
        os.environ["AUTH_USERS_JSON"] = (
            '{"realadmin": {"password": "s3cret", "role": "admin", "display": "Real Admin"}}'
        )
        os.environ["AUTH_PWD_SALT"] = "a-unique-deployment-salt"
        os.environ["MODEL_REGISTRY_HMAC_KEY"] = "a-secret-hmac-key"
        importlib.reload(auth_mock)   # rebuild under the configured env

        self.assertFalse(auth_mock.using_demo_credentials())
        self.assertFalse(auth_mock.using_default_salt())
        self.assertEqual(config.production_issues(), [])

        # Even in production, a properly-configured deployment must not raise.
        os.environ["APP_ENV"] = "production"
        self.assertEqual(config.production_preflight(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
