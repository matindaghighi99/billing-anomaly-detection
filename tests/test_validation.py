"""tests/test_validation.py — accuracy validation framework + clinical loop."""

import importlib
import os
import tempfile
import unittest


class ValidationMetricsTests(unittest.TestCase):
    def setUp(self):
        import validation
        importlib.reload(validation)
        self.v = validation

    def test_confusion_and_metrics(self):
        import pandas as pd
        labels = pd.DataFrame([
            {"provider_id": "A", "label": 1},
            {"provider_id": "B", "label": 1},
            {"provider_id": "C", "label": 0},
            {"provider_id": "D", "label": 0},
        ])
        flagged = {"A", "C"}            # A=TP, C=FP, B=FN, D=TN
        m = self.v.compute_metrics(labels, flagged)
        self.assertEqual((m["tp"], m["fp"], m["fn"], m["tn"]), (1, 1, 1, 1))
        self.assertEqual(m["precision"], 0.5)
        self.assertEqual(m["recall"], 0.5)

    def test_is_validated_gate(self):
        self.assertTrue(self.v.is_validated("ADJUDICATED_OUTCOMES"))
        self.assertFalse(self.v.is_validated("SYNTHETIC"))

    def test_recovery_calibration_needs_amounts(self):
        import pandas as pd
        labels = pd.DataFrame([{"provider_id": "A", "label": 1}])  # no recovered_amount
        self.assertIsNone(self.v.recovery_calibration(labels))


class ClinicalReviewTests(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(), "clin.db")
        os.environ["CLINICAL_DB_PATH"] = self.db
        import clinical_review
        importlib.reload(clinical_review)
        self.cr = clinical_review

    def tearDown(self):
        if os.path.exists(self.db):
            os.remove(self.db)
        os.environ.pop("CLINICAL_DB_PATH", None)

    def test_record_and_latest(self):
        self.cr.record_opinion("P1", "Upcoding (E/M complexity inflation)",
                               "not_medically_necessary", "Dr. X", "no support")
        op = self.cr.latest_opinion("P1", "Upcoding (E/M complexity inflation)")
        self.assertEqual(op["opinion"], "not_medically_necessary")

    def test_invalid_opinion_rejected(self):
        with self.assertRaises(ValueError):
            self.cr.record_opinion("P1", "c", "maybe", "Dr. X")

    def test_pending_excludes_documentary_and_reviewed(self):
        import pandas as pd
        self.cr.record_opinion("P1", "Upcoding (E/M complexity inflation)",
                               "supports_necessity", "Dr. X")
        findings = pd.DataFrame([
            {"provider_id": "P1", "scheme": "Upcoding (E/M complexity inflation)"},  # reviewed
            {"provider_id": "P2", "scheme": "Self-referral out-of-specialty imaging"},  # needs review
            {"provider_id": "P3", "scheme": "Duplicate claim resubmission"},  # documentary
        ])
        pending = self.cr.pending_reviews(findings)
        self.assertEqual({p["provider_id"] for p in pending}, {"P2"})

    def test_summary_counts(self):
        self.cr.record_opinion("P1", "c1", "not_medically_necessary", "Dr. X")
        self.cr.record_opinion("P2", "c2", "supports_necessity", "Dr. Y")
        s = self.cr.summary()
        self.assertEqual(s["not_necessary"], 1)
        self.assertEqual(s["supports"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
