"""tests/test_postgres_store.py — storage-seam regression + Postgres integration.

Two layers:

1. Static guard (always runs, even on the SQLite CI): the audit and case
   schemas must keep the reserved word `user` double-quoted. SQLite does not
   reserve `user`, so a behavioural SQLite test cannot catch an accidental
   un-quoting — but on PostgreSQL an unquoted `user` silently resolves to the
   CURRENT_USER function and the column reads back the DB role instead of the
   stored value. This guard fails fast if the quoting is ever removed.

2. PostgreSQL integration (skipped unless DATABASE_URL points at Postgres and
   psycopg is installed): exercises the audit logbook (append, RETURNING id,
   tamper detection) and the reserved-word read-back against a real instance.
   Run during the integration pass by pointing DATABASE_URL at a PostgreSQL
   connection string, then:
       python -m pytest tests/test_postgres_store.py -v
"""

import os
import importlib
import unittest


class ReservedWordQuotingGuard(unittest.TestCase):
    """Catches accidental un-quoting of the `user` column in plain (SQLite) CI."""

    def test_audit_schema_quotes_user(self):
        import audit_log
        self.assertIn('"user"', audit_log._SCHEMA)
        self.assertNot_regex_bare_user(audit_log._SCHEMA)

    def test_case_schema_quotes_user(self):
        import case_management
        self.assertIn('"user"', case_management._SCHEMA)
        self.assertNot_regex_bare_user(case_management._SCHEMA)

    # helper
    def assertNot_regex_bare_user(self, schema: str):
        import re
        # No column definition line of the form `<ws>user<ws>TYPE` (unquoted).
        self.assertIsNone(
            re.search(r'(?im)^\s*user\s+\w', schema),
            "found an UNQUOTED `user` column — quote it as \"user\" for PostgreSQL",
        )


_PG = os.environ.get("DATABASE_URL", "").startswith(("postgres://", "postgresql://"))
try:
    import psycopg  # noqa: F401
    _HAS_PSYCOPG = True
except Exception:
    _HAS_PSYCOPG = False


@unittest.skipUnless(_PG and _HAS_PSYCOPG,
                     "set DATABASE_URL=postgresql://… and install psycopg to run")
class PostgresAuditIntegration(unittest.TestCase):
    """End-to-end logbook checks against a real PostgreSQL instance."""

    def setUp(self):
        import db
        importlib.reload(db)
        self.url = os.environ["DATABASE_URL"]
        # Clean slate for deterministic row counts.
        import psycopg
        with psycopg.connect(self.url) as c:
            c.execute("DROP TABLE IF EXISTS audit_log")
            c.commit()
        import audit_log
        importlib.reload(audit_log)
        self.audit_log = audit_log

    def test_append_returning_verify_and_tamper(self):
        import psycopg
        for i in range(3):
            rid = self.audit_log.append_event(
                event_type="action_taken", provider_id=f"PRV{i}",
                user="auditor1", action_taken="confirmed", reasoning="pg test")
            self.assertIsInstance(rid, int)   # RETURNING id works on Postgres

        clean = self.audit_log.verify_integrity()
        self.assertTrue(clean["ok"])
        self.assertEqual(clean["total_rows"], 3)

        # Reserved-word read-back: the quoted column returns the stored value.
        with psycopg.connect(self.url) as c:
            stored = c.execute('SELECT "user" FROM audit_log ORDER BY id LIMIT 1').fetchone()[0]
        self.assertEqual(stored, "auditor1")

        # Tamper a row; the hash chain must catch it.
        with psycopg.connect(self.url) as c:
            c.execute("UPDATE audit_log SET action_taken='clear' WHERE id=2")
            c.commit()
        bad = self.audit_log.verify_integrity()
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["first_bad_id"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
