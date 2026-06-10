"""audit_log.py — Append-only, tamper-evident audit trail.

Backing store: SQLite (audit_log.db).
Why SQLite over JSONL:
  - Queryable without parsing the entire file
  - Transaction-safe concurrent writes (no torn appends)
  - Single portable binary alongside the existing billing_anomaly.db
  - Trivial CSV export via the csv module

Hash chain: each row stores
    row_hash = SHA256(prev_row_hash || this_row_content_json)
verify_integrity() recomputes the full chain and pinpoints the first
record that was altered or deleted.

There are NO UPDATE or DELETE statements anywhere in this module.
The only write path is append_event(), which uses INSERT only.
"""

import csv
import hashlib
import json
import os
import sqlite3
import datetime
from typing import Optional

DB_PATH = "audit_log.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    utc_timestamp  TEXT    NOT NULL,
    event_type     TEXT    NOT NULL,
    user           TEXT    NOT NULL DEFAULT 'system',
    provider_id    TEXT,
    model_version  TEXT,
    signals_shown  TEXT,
    action_taken   TEXT,
    reasoning      TEXT,
    row_hash       TEXT    NOT NULL,
    prev_hash      TEXT    NOT NULL
);
"""

# Genesis hash — used as prev_hash for the very first row
_GENESIS = "0" * 64

# Leading characters that spreadsheet apps treat as the start of a formula.
# Audit fields such as 'user'/'reasoning' can contain attacker-influenced text,
# so we neutralise them on CSV export to prevent formula (CSV) injection when
# the export is opened in Excel/Sheets.
_CSV_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value):
    """Prefix a single quote to any value that could be parsed as a formula."""
    if isinstance(value, str) and value and value[0] in _CSV_INJECTION_PREFIXES:
        return "'" + value
    return value

# Ordered list of fields included in the content hash (never includes hash fields).
# id is intentionally excluded: it is auto-assigned by SQLite after INSERT, so
# including it would require a pre-INSERT SELECT MAX(id) that is not atomic and
# would allow two concurrent writers to corrupt the chain.
_CONTENT_FIELDS = [
    "utc_timestamp", "event_type", "user", "provider_id",
    "model_version", "signals_shown", "action_taken", "reasoning",
]


def _open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def _content_str(record: dict) -> str:
    """Deterministic JSON of the fields that should be immutable."""
    return json.dumps({k: record.get(k) for k in _CONTENT_FIELDS}, sort_keys=True)


def _sha256(prev_hash: str, content: str) -> str:
    return hashlib.sha256(f"{prev_hash}{content}".encode("utf-8")).hexdigest()


def _last_hash(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT row_hash FROM audit_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else _GENESIS


# ── Public API ────────────────────────────────────────────────────────────────

def append_event(
    event_type: str,
    *,
    provider_id: Optional[str] = None,
    user: str = "system",
    model_version: Optional[str] = None,
    signals_shown: Optional[list] = None,
    action_taken: Optional[str] = None,
    reasoning: Optional[str] = None,
) -> int:
    """Append one event to the audit log and return its row id.

    event_type must be one of:
      flag_generated | flag_viewed | action_taken | model_updated

    This function uses INSERT only; no UPDATE or DELETE code paths exist.
    """
    valid = {"flag_generated", "flag_viewed", "action_taken", "model_updated"}
    if event_type not in valid:
        raise ValueError(f"event_type must be one of {valid}, got {event_type!r}")

    conn = _open_db()
    ts   = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    sigs = json.dumps(signals_shown) if signals_shown is not None else None

    # BEGIN IMMEDIATE acquires a write lock before we read the previous hash,
    # so two concurrent callers cannot both read the same tail hash and then
    # each insert a row that claims a different predecessor — which would
    # silently fork the chain and make verify_integrity() report a false break.
    conn.execute("BEGIN IMMEDIATE")
    try:
        prev = _last_hash(conn)

        record = {
            "utc_timestamp": ts,
            "event_type":    event_type,
            "user":          user,
            "provider_id":   provider_id,
            "model_version": model_version,
            "signals_shown": sigs,
            "action_taken":  action_taken,
            "reasoning":     reasoning,
        }
        row_hash = _sha256(prev, _content_str(record))

        cur = conn.execute(
            "INSERT INTO audit_log "
            "(utc_timestamp, event_type, user, provider_id, model_version, "
            " signals_shown, action_taken, reasoning, row_hash, prev_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, event_type, user, provider_id, model_version,
             sigs, action_taken, reasoning, row_hash, prev),
        )
        new_id = cur.lastrowid
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return new_id


def verify_integrity() -> dict:
    """Recompute the hash chain and report the first tampered record.

    Returns:
        ok          (bool)     — True if every record is unaltered
        total_rows  (int)      — total records in the log
        first_bad_id (int|None) — row id of the first failure, or None
        message     (str)      — human-readable verdict
    """
    conn = _open_db()
    rows = conn.execute(
        "SELECT id, utc_timestamp, event_type, user, provider_id, model_version, "
        "signals_shown, action_taken, reasoning, row_hash, prev_hash "
        "FROM audit_log ORDER BY id ASC"
    ).fetchall()
    conn.close()

    if not rows:
        return {
            "ok": True, "total_rows": 0, "first_bad_id": None,
            "message": "Audit log is empty — nothing to verify.",
        }

    cols = [
        "id", "utc_timestamp", "event_type", "user", "provider_id",
        "model_version", "signals_shown", "action_taken", "reasoning",
        "row_hash", "prev_hash",
    ]

    expected_prev = _GENESIS
    for raw in rows:
        r = dict(zip(cols, raw))

        # Check that this row correctly references the previous hash
        if r["prev_hash"] != expected_prev:
            return {
                "ok": False, "total_rows": len(rows),
                "first_bad_id": r["id"],
                "message": (
                    f"Chain break at row id={r['id']}: stored prev_hash does not "
                    f"match the preceding row's hash. A record may have been "
                    f"deleted or inserted out of order."
                ),
            }

        # Recompute this row's own hash and compare
        expected_hash = _sha256(r["prev_hash"], _content_str(r))
        if r["row_hash"] != expected_hash:
            return {
                "ok": False, "total_rows": len(rows),
                "first_bad_id": r["id"],
                "message": (
                    f"Tampered record at row id={r['id']}: recomputed hash "
                    f"differs from stored hash. The record content has been altered."
                ),
            }

        expected_prev = r["row_hash"]

    return {
        "ok": True, "total_rows": len(rows), "first_bad_id": None,
        "message": f"Integrity verified — all {len(rows)} records are unaltered.",
    }


def export_to_csv(path: str = "audit_log_export.csv") -> int:
    """Export the full audit log to a CSV file for auditors. Returns row count."""
    conn = _open_db()
    rows = conn.execute(
        "SELECT id, utc_timestamp, event_type, user, provider_id, model_version, "
        "signals_shown, action_taken, reasoning, row_hash, prev_hash "
        "FROM audit_log ORDER BY id ASC"
    ).fetchall()
    conn.close()

    headers = [
        "id", "utc_timestamp", "event_type", "user", "provider_id",
        "model_version", "signals_shown", "action_taken", "reasoning",
        "row_hash", "prev_hash",
    ]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(headers)
        for row in rows:
            w.writerow([_csv_safe(cell) for cell in row])
    return len(rows)


def get_recent(n: int = 100) -> list:
    """Return the n most recent log entries as a list of dicts (no hash fields)."""
    conn = _open_db()
    rows = conn.execute(
        "SELECT id, utc_timestamp, event_type, user, provider_id, model_version, "
        "signals_shown, action_taken, reasoning "
        "FROM audit_log ORDER BY id DESC LIMIT ?",
        (n,),
    ).fetchall()
    conn.close()
    cols = [
        "id", "utc_timestamp", "event_type", "user", "provider_id",
        "model_version", "signals_shown", "action_taken", "reasoning",
    ]
    return [dict(zip(cols, r)) for r in rows]


# ── Self-test ─────────────────────────────────────────────────────────────────

def _selftest():
    """Write records, tamper one row in the DB, confirm verify_integrity() catches it."""
    import audit_log as _m

    test_db = "audit_log_selftest.db"
    orig_db = _m.DB_PATH
    _m.DB_PATH = test_db

    try:
        if os.path.exists(test_db):
            os.remove(test_db)

        # --- Write 3 clean records ---
        _m.append_event(
            "flag_generated",
            provider_id="PRV0001",
            signals_shown=["impossible_day", "peer_stats"],
            reasoning="Billed 1,800 service-minutes on 2024-03-15",
        )
        _m.append_event(
            "flag_viewed",
            provider_id="PRV0001",
            user="auditor1",
        )
        _m.append_event(
            "action_taken",
            provider_id="PRV0001",
            user="auditor1",
            action_taken="confirmed",
            reasoning="Duplicate billing pattern is clear",
        )

        result = _m.verify_integrity()
        assert result["ok"], f"Clean chain failed verification: {result['message']}"
        assert result["total_rows"] == 3
        print(f"    [PASS] Clean chain ({result['total_rows']} rows): {result['message']}")

        # --- Tamper: directly modify row 2's reasoning ---
        conn = sqlite3.connect(test_db)
        conn.execute("UPDATE audit_log SET reasoning = 'TAMPERED' WHERE id = 2")
        conn.commit()
        conn.close()

        result = _m.verify_integrity()
        assert not result["ok"], "Expected integrity failure — none detected"
        assert result["first_bad_id"] == 2, (
            f"Expected first_bad_id=2, got {result['first_bad_id']}"
        )
        print(
            f"    [PASS] Tamper detected at row id={result['first_bad_id']}: "
            f"{result['message']}"
        )

        # --- Export ---
        export_path = "audit_log_selftest_export.csv"
        n = _m.export_to_csv(export_path)
        assert n == 3
        os.remove(export_path)
        print(f"    [PASS] export_to_csv wrote {n} rows and deleted cleanly")

    finally:
        _m.DB_PATH = orig_db
        for f in [test_db]:
            if os.path.exists(f):
                os.remove(f)


if __name__ == "__main__":
    print("audit_log.py — Self-test")
    print("=" * 60)
    _selftest()
    print("=" * 60)
    print("  All Phase 1 audit_log tests passed.")
