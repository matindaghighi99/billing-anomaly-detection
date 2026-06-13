"""tests/test_observability_logging.py — structured audit/SIEM logging."""

import json
import logging
import unittest


class ActionEventTests(unittest.TestCase):
    def setUp(self):
        import observability
        self.obs = observability

    def test_action_event_payload(self):
        ev = self.obs.action_event("export_audit_log", target="full_log",
                                   outcome="ok", rows=42)
        self.assertEqual(ev["event"], "user_action")
        self.assertEqual(ev["action"], "export_audit_log")
        self.assertEqual(ev["target"], "full_log")
        self.assertEqual(ev["rows"], 42)
        self.assertIn("actor", ev)
        self.assertIn("correlation_id", ev)

    def test_json_formatter_promotes_extra_fields(self):
        # Build the same JSON formatter configure_logging() installs and verify
        # structured extras surface as top-level keys for SIEM querying.
        self.obs.configure_logging()
        root = logging.getLogger()
        fmt = root.handlers[0].formatter
        rec = logging.makeLogRecord({
            "name": "baad.audit", "levelno": logging.INFO, "levelname": "INFO",
            "msg": "take_action",
        })
        rec.action = "take_action"
        rec.actor = "auditor1"
        line = fmt.format(rec)
        obj = json.loads(line)
        self.assertEqual(obj["action"], "take_action")
        self.assertEqual(obj["actor"], "auditor1")
        self.assertEqual(obj["level"], "INFO")

    def test_log_action_emits_record(self):
        self.obs.configure_logging()
        with self.assertLogs("baad.audit", level="INFO") as cm:
            self.obs.log_action("verify_integrity", target="audit_log")
        self.assertTrue(any("verify_integrity" in m for m in cm.output))


if __name__ == "__main__":
    unittest.main(verbosity=2)
