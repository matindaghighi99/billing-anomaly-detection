"""clinical_review.py — Medical-consultant review loop (HIA s.18(8)(e)).

The post-payment process requires consulting a physician before concluding that
a service was not medically necessary. Several detectors (upcoding, self-
referral imaging, modifier-25, unit inflation, …) raise medical-necessity
concerns flagged `needs_medical_consult` in the concern taxonomy. This module
routes those to a clinical reviewer, captures their opinion, and persists it
(append-only) so the opinion (a) drives the case, (b) becomes a label for
accuracy validation, and (c) gates whether a recovery position is supportable.

Opinions:
  supports_necessity     service was medically necessary → concern not supported
  not_medically_necessary service was not necessary       → concern supported
  insufficient_info      cannot determine on records provided

Store: SQLite (CLINICAL_DB_PATH, configurable for managed storage).
"""

import datetime
import os
import sqlite3

try:
    from config import CLINICAL_DB_PATH as DB_PATH
except Exception:
    DB_PATH = os.environ.get("CLINICAL_DB_PATH", "clinical_reviews.db")

OPINIONS = ("supports_necessity", "not_medically_necessary", "insufficient_info")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS clinical_reviews (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    utc_timestamp TEXT NOT NULL,
    provider_id   TEXT NOT NULL,
    concern       TEXT NOT NULL,
    opinion       TEXT NOT NULL,
    consultant    TEXT NOT NULL,
    rationale     TEXT
);
"""


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _open() -> sqlite3.Connection:
    # Resolve the path at call time so a runtime CLINICAL_DB_PATH (managed
    # volume, or per-test override) is always honoured.
    conn = sqlite3.connect(os.environ.get("CLINICAL_DB_PATH", DB_PATH))
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def record_opinion(provider_id: str, concern: str, opinion: str,
                   consultant: str, rationale: str = "") -> None:
    if opinion not in OPINIONS:
        raise ValueError(f"opinion must be one of {OPINIONS}, got {opinion!r}")
    conn = _open()
    try:
        conn.execute(
            "INSERT INTO clinical_reviews "
            "(utc_timestamp, provider_id, concern, opinion, consultant, rationale) "
            "VALUES (?,?,?,?,?,?)",
            (_now(), provider_id, concern, opinion, consultant, rationale))
        conn.commit()
    finally:
        conn.close()


def get_opinions(provider_id: str | None = None) -> list[dict]:
    conn = _open()
    try:
        if provider_id:
            rows = conn.execute(
                "SELECT utc_timestamp, provider_id, concern, opinion, consultant, "
                "rationale FROM clinical_reviews WHERE provider_id=? ORDER BY id DESC",
                (provider_id,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT utc_timestamp, provider_id, concern, opinion, consultant, "
                "rationale FROM clinical_reviews ORDER BY id DESC").fetchall()
        cols = ["utc_timestamp", "provider_id", "concern", "opinion",
                "consultant", "rationale"]
        return [dict(zip(cols, r)) for r in rows]
    finally:
        conn.close()


def latest_opinion(provider_id: str, concern: str) -> dict | None:
    for o in get_opinions(provider_id):
        if o["concern"] == concern:
            return o
    return None


def pending_reviews(findings) -> list[dict]:
    """Concerns needing s.18(8)(e) review that have no opinion yet.

    `findings` is the fraud_evidence DataFrame (provider_id, scheme, ...).
    """
    from moh_audit import classify
    pending = []
    for _, f in findings.iterrows():
        cls = classify(f["scheme"])
        if not cls.get("needs_medical_consult"):
            continue
        if latest_opinion(f["provider_id"], f["scheme"]) is None:
            pending.append({"provider_id": f["provider_id"], "concern": f["scheme"]})
    return pending


def summary() -> dict:
    ops = get_opinions()
    return {
        "total": len(ops),
        "reviewed": len({(o["provider_id"], o["concern"]) for o in ops}),
        "supports": sum(o["opinion"] == "supports_necessity" for o in ops),
        "not_necessary": sum(o["opinion"] == "not_medically_necessary" for o in ops),
        "insufficient": sum(o["opinion"] == "insufficient_info" for o in ops),
    }


def _selftest():
    import tempfile
    global DB_PATH
    orig = DB_PATH
    DB_PATH = os.path.join(tempfile.gettempdir(), "clinical_selftest.db")
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    try:
        import pandas as pd
        record_opinion("PRV0001", "Upcoding (E/M complexity inflation)",
                       "not_medically_necessary", "Dr. Reviewer", "Records do not support 99215")
        assert latest_opinion("PRV0001", "Upcoding (E/M complexity inflation)")
        findings = pd.DataFrame([
            {"provider_id": "PRV0001", "scheme": "Upcoding (E/M complexity inflation)"},
            {"provider_id": "PRV0002", "scheme": "Self-referral out-of-specialty imaging"},
            {"provider_id": "PRV0003", "scheme": "Duplicate claim resubmission"},  # documentary
        ])
        pend = pending_reviews(findings)
        # PRV0001 reviewed; PRV0002 needs review; PRV0003 documentary (no consult)
        ids = {p["provider_id"] for p in pend}
        assert ids == {"PRV0002"}, ids
        assert summary()["not_necessary"] == 1
        print("    [PASS] record/pending/summary clinical review loop")
    finally:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        DB_PATH = orig


if __name__ == "__main__":
    print("clinical_review.py — Self-test")
    print("=" * 60)
    _selftest()
    print("=" * 60)
    print("  All clinical-review tests passed.")
