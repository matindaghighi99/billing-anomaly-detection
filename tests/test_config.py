"""tests/test_config.py — production config gate."""

import importlib
import os
import unittest


def _reload_config(env: dict):
    for k in ("APP_ENV", "SESSION_SECRET", "MFA_ENABLED",
              "HIDE_DEMO_CREDS", "BAAD_USERS_JSON"):
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
