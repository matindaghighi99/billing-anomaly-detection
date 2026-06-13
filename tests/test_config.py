"""tests/test_config.py — production config gate."""

import importlib
import os
import unittest


def _reload_config(env: dict):
    for k in ("APP_ENV", "SESSION_SECRET", "MFA_ENABLED",
              "HIDE_DEMO_CREDS", "BAAD_USERS_JSON",
              "AUTH_PROVIDER", "SSO_JWT_HEADER", "SSO_PROXY_SHARED_SECRET"):
        os.environ.pop(k, None)
    os.environ.update(env)
    import config
    importlib.reload(config)
    return config


class ConfigGateTests(unittest.TestCase):
    def tearDown(self):
        for k in ("APP_ENV", "SESSION_SECRET", "MFA_ENABLED",
                  "HIDE_DEMO_CREDS", "BAAD_USERS_JSON"):
            os.environ.pop(k, None)

    def test_demo_has_no_problems(self):
        cfg = _reload_config({"APP_ENV": "demo"})
        self.assertEqual(cfg.validate(), [])
        self.assertEqual(cfg.enforce(), [])   # never raises in demo

    def test_production_unconfigured_reports_problems(self):
        cfg = _reload_config({"APP_ENV": "production"})
        problems = cfg.validate()
        self.assertTrue(problems)
        with self.assertRaises(RuntimeError):
            cfg.enforce()

    def test_production_weak_secret_flagged(self):
        cfg = _reload_config({
            "APP_ENV": "production", "SESSION_SECRET": "short",
            "MFA_ENABLED": "1", "HIDE_DEMO_CREDS": "1", "BAAD_USERS_JSON": "{}",
        })
        self.assertTrue(any("too short" in p for p in cfg.validate()))

    def test_production_fully_configured_passes(self):
        cfg = _reload_config({
            "APP_ENV": "production",
            "SESSION_SECRET": "x" * 64,
            "MFA_ENABLED": "1", "HIDE_DEMO_CREDS": "1",
            "BAAD_USERS_JSON": '{"u":{}}',
        })
        self.assertEqual(cfg.validate(), [])
        self.assertEqual(cfg.enforce(), [])

    # ── SSO provider: network-isolation safeguard ──────────────────────────
    def test_production_sso_header_trust_requires_proxy_secret(self):
        # Header-trust SSO with no proxy secret is the dangerous misconfiguration
        # (forged identity headers if the proxy is bypassed) → must fail fast.
        cfg = _reload_config({"APP_ENV": "production", "AUTH_PROVIDER": "sso"})
        problems = cfg.validate()
        self.assertTrue(any("SSO_PROXY_SHARED_SECRET" in p for p in problems))
        with self.assertRaises(RuntimeError):
            cfg.enforce()

    def test_production_sso_with_proxy_secret_passes(self):
        cfg = _reload_config({"APP_ENV": "production", "AUTH_PROVIDER": "sso",
                              "SSO_PROXY_SHARED_SECRET": "x" * 32})
        self.assertEqual(cfg.validate(), [])

    def test_production_sso_jwt_mode_passes(self):
        # JWT mode verifies signatures in-app, so the proxy secret isn't required.
        cfg = _reload_config({"APP_ENV": "production", "AUTH_PROVIDER": "sso",
                              "SSO_JWT_HEADER": "Authorization"})
        self.assertEqual(cfg.validate(), [])

    def test_production_sso_does_not_require_local_auth_settings(self):
        # In SSO mode the local password/MFA/user settings are irrelevant and
        # must NOT be demanded.
        cfg = _reload_config({"APP_ENV": "production", "AUTH_PROVIDER": "sso",
                              "SSO_PROXY_SHARED_SECRET": "x" * 32})
        problems = " ".join(cfg.validate())
        self.assertNotIn("SESSION_SECRET", problems)
        self.assertNotIn("BAAD_USERS_JSON", problems)


if __name__ == "__main__":
    unittest.main(verbosity=2)
