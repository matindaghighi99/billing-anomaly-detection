"""tests/test_case_management.py — persistent case workflow + letters."""

import datetime
import importlib
import os
import tempfile
import unittest


class CaseManagementTests(unittest.TestCase):
    def setUp(self):
        # Point the store at a throwaway DB per test.
        self.db = os.path.join(tempfile.mkdtemp(), "cases.db")
        os.environ["CASE_DB_PATH"] = self.db
        import case_management
        importlib.reload(case_management)
        self.cm = case_management

    def tearDown(self):
        if os.path.exists(self.db):
            os.remove(self.db)
        os.environ.pop("CASE_DB_PATH", None)

    def test_default_case_is_initial_action(self):
        c = self.cm.get_case("PRV0001")
        self.assertEqual(c["stage"], "Initial Action")

    def test_full_audit_sets_ack_clock(self):
        c = self.cm.set_stage("PRV0001", "Full Audit Review", user="auditor1")
        self.assertTrue(c["records_requested_date"])
        self.assertTrue(c["ack_due_date"])
        # ack due is ~14 days after records requested
        req = datetime.date.fromisoformat(c["records_requested_date"])
        due = datetime.date.fromisoformat(c["ack_due_date"])
        self.assertEqual((due - req).days, self.cm.ACK_DAYS)

    def test_persistence_across_reload(self):
        self.cm.set_stage("PRV0002", "Board Hearing", user="admin1")
        importlib.reload(self.cm)            # simulate a restart
        self.assertEqual(self.cm.get_case("PRV0002")["stage"], "Board Hearing")

    def test_invalid_stage_rejected(self):
        with self.assertRaises(ValueError):
            self.cm.set_stage("PRV0003", "Nonsense")

    def test_overdue_detection(self):
        self.cm.set_stage("PRV0004", "Full Audit Review")
        # Force an overdue ack window.
        self.cm.mark_date("PRV0004", "ack_due_date",
                          (datetime.date.today() - datetime.timedelta(days=1)).isoformat())
        self.assertTrue(self.cm.overdue(self.cm.get_case("PRV0004")))
        self.cm.mark_date("PRV0004", "ack_received_date")
        self.assertFalse(self.cm.overdue(self.cm.get_case("PRV0004")))

    def test_correspondence_log(self):
        self.cm.record_correspondence("PRV0005", "records_request", "RFI sent",
                                      user="auditor1")
        log = self.cm.get_correspondence("PRV0005")
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["kind"], "records_request")

    def test_letters_generate(self):
        for kind, marker in [
            ("records_request", "Request for Records and Information"),
            ("billing_education", "Billing Education Letter"),
            ("gm_opinion", "General Manager's Opinion"),
            ("review_complete", "Review Complete"),
        ]:
            txt = self.cm.generate_letter("PRV0006", kind, specialty="Cardiology",
                                          concerns=["Unbundling"], recoverable=12345.0)
            self.assertIn(marker, txt)
            self.assertIn("PRV0006", txt)

    def test_gm_letter_marks_indicative(self):
        txt = self.cm.generate_letter("PRV0007", "gm_opinion", recoverable=1000.0,
                                      figure_status="INDICATIVE")
        self.assertIn("INDICATIVE", txt)
        txt2 = self.cm.generate_letter("PRV0007", "gm_opinion", recoverable=1000.0,
                                       figure_status="DEFENSIBLE")
        self.assertNotIn("INDICATIVE", txt2)

    def test_unknown_letter_kind(self):
        with self.assertRaises(ValueError):
            self.cm.generate_letter("PRV0008", "bogus")


if __name__ == "__main__":
    unittest.main(verbosity=2)
