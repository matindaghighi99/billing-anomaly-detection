"""case_management.py — Persistent 3-stage audit case state + correspondence.

The MOH post-payment process is a case lifecycle, not a one-shot score:
Initial Action → Full Audit Review → Board Hearing, with statutory SLA dates,
physician correspondence, and written submissions. This module persists that
state (SQLite, path configurable for managed storage) and generates the actual
letters the Provider Audit Unit sends, so the workflow survives restarts and an
auditor can drive a case end-to-end.

Tables:
  audit_cases          one row per physician — current stage/status + key dates
  case_correspondence  append-only log of letters/submissions/notes

Letters generated (MOH-style, dates pre-filled from the SLA calendar):
  records_request | billing_education | review_complete | gm_opinion
"""

import datetime
import os
import sqlite3

import db   # storage backend seam (SQLite default; PostgreSQL via DATABASE_URL)

try:
    from config import CASE_DB_PATH as DB_PATH
except Exception:
    DB_PATH = os.environ.get("CASE_DB_PATH", "audit_cases.db")

STAGES = ["Initial Action", "Full Audit Review", "Board Hearing", "Closed"]

# SLA calendar (days) from the published process.
ACK_DAYS          = 14          # physician acknowledgement window (2 weeks)
RECORDS_DAYS      = 180         # records request → review (up to 6 months)
REVIEW_DAYS       = 180         # records review (up to 6 months)
GM_OPINION_DAYS   = 90          # GM's Opinion (up to 3 months)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_cases (
    provider_id            TEXT PRIMARY KEY,
    stage                  TEXT NOT NULL DEFAULT 'Initial Action',
    status                 TEXT,
    review_request_date    TEXT,
    records_requested_date TEXT,
    ack_due_date           TEXT,
    ack_received_date      TEXT,
    findings_date          TEXT,
    gm_opinion_date        TEXT,
    assigned_to            TEXT,
    updated_utc            TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS case_correspondence (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id   TEXT NOT NULL,
    utc_timestamp TEXT NOT NULL,
    direction     TEXT,    -- outbound | inbound
    kind          TEXT,    -- records_request | billing_education | gm_opinion | submission | note
    summary       TEXT,
    user          TEXT
);
"""

_CASE_COLS = ["provider_id", "stage", "status", "review_request_date",
              "records_requested_date", "ack_due_date", "ack_received_date",
              "findings_date", "gm_opinion_date", "assigned_to", "updated_utc"]


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _today() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date()


def _open():
    # Resolve the path at call time so a runtime CASE_DB_PATH (managed volume,
    # or per-test override) is always honoured.
    return db.connect(os.environ.get("CASE_DB_PATH", DB_PATH), _SCHEMA)


# ── Case state ──────────────────────────────────────────────────────────────

def get_case(provider_id: str) -> dict:
    """Return the case row (creating a default Initial-Action row if absent)."""
    conn = _open()
    try:
        row = conn.execute(
            f"SELECT {','.join(_CASE_COLS)} FROM audit_cases WHERE provider_id=?",
            (provider_id,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO audit_cases (provider_id, stage, status, updated_utc) "
                "VALUES (?,?,?,?)",
                (provider_id, "Initial Action", "preliminary_review", _now()))
            conn.commit()
            row = conn.execute(
                f"SELECT {','.join(_CASE_COLS)} FROM audit_cases WHERE provider_id=?",
                (provider_id,)).fetchone()
        return dict(zip(_CASE_COLS, row))
    finally:
        conn.close()


def set_stage(provider_id: str, stage: str, user: str = "system") -> dict:
    """Advance/return a case to *stage*, auto-filling the statutory SLA dates."""
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {STAGES}, got {stage!r}")
    case = get_case(provider_id)
    today = _today()
    updates = {"stage": stage, "updated_utc": _now()}

    if stage == "Full Audit Review" and not case.get("records_requested_date"):
        updates["records_requested_date"] = today.isoformat()
        updates["ack_due_date"] = (today + datetime.timedelta(days=ACK_DAYS)).isoformat()
        updates["status"] = "records_requested"
    elif stage == "Board Hearing":
        updates["status"] = "hsarb_referred"
        if not case.get("gm_opinion_date"):
            updates["gm_opinion_date"] = today.isoformat()
    elif stage == "Closed":
        updates["status"] = "closed"
    elif stage == "Initial Action":
        updates["status"] = "preliminary_review"

    conn = _open()
    try:
        sets = ", ".join(f"{k}=?" for k in updates)
        conn.execute(f"UPDATE audit_cases SET {sets} WHERE provider_id=?",
                     (*updates.values(), provider_id))
        conn.commit()
    finally:
        conn.close()
    return get_case(provider_id)


def mark_date(provider_id: str, field: str, value: str | None = None) -> None:
    """Set a date field (defaults to today) — e.g. ack_received_date, findings_date."""
    allowed = {"review_request_date", "records_requested_date", "ack_due_date",
               "ack_received_date", "findings_date", "gm_opinion_date"}
    if field not in allowed:
        raise ValueError(f"field must be one of {sorted(allowed)}")
    value = value or _today().isoformat()
    conn = _open()
    try:
        conn.execute(f"UPDATE audit_cases SET {field}=?, updated_utc=? WHERE provider_id=?",
                     (value, _now(), provider_id))
        conn.commit()
    finally:
        conn.close()


def record_correspondence(provider_id: str, kind: str, summary: str,
                          direction: str = "outbound", user: str = "system") -> None:
    conn = _open()
    try:
        conn.execute(
            "INSERT INTO case_correspondence "
            "(provider_id, utc_timestamp, direction, kind, summary, user) "
            "VALUES (?,?,?,?,?,?)",
            (provider_id, _now(), direction, kind, summary, user))
        conn.commit()
    finally:
        conn.close()


def get_correspondence(provider_id: str) -> list[dict]:
    conn = _open()
    try:
        rows = conn.execute(
            "SELECT utc_timestamp, direction, kind, summary, user "
            "FROM case_correspondence WHERE provider_id=? ORDER BY id DESC",
            (provider_id,)).fetchall()
        cols = ["utc_timestamp", "direction", "kind", "summary", "user"]
        return [dict(zip(cols, r)) for r in rows]
    finally:
        conn.close()


def overdue(case: dict) -> bool:
    """True if the physician acknowledgement window has lapsed without a response."""
    due = case.get("ack_due_date")
    if not due or case.get("ack_received_date"):
        return False
    try:
        return _today() > datetime.date.fromisoformat(due)
    except ValueError:
        return False


# ── Letter generation ─────────────────────────────────────────────────────────

def generate_letter(provider_id: str, kind: str, *, specialty: str = "",
                    concerns: list | None = None, recoverable: float = 0.0,
                    figure_status: str = "INDICATIVE") -> str:
    """Return a MOH-style letter (Markdown), with SLA dates pre-filled."""
    case = get_case(provider_id)
    today = _today().isoformat()
    concerns = concerns or []
    concern_lines = "\n".join(f"  - {c}" for c in concerns) or "  - (see case file)"

    if kind == "records_request":
        ack_due = case.get("ack_due_date") or \
            (_today() + datetime.timedelta(days=ACK_DAYS)).isoformat()
        return f"""# Request for Records and Information

**Date:** {today}
**Re:** Physician {provider_id} ({specialty})
**Stage:** Full Audit Review — *Potential Billing Concern under review*

Dear Doctor,

The Ministry of Health is reviewing claims you submitted to OHIP. This letter
is to advise you that a Potential Billing Concern has been identified and to
request medical records and related practice information to support the review.
**No determination has been made.**

Concern(s) under review:
{concern_lines}

Please confirm by **{ack_due}** (within {ACK_DAYS} days) that the requested
records will be provided, and indicate whether the submission timeline is
achievable; reasonable extension requests will be approved. Records are
requested under the Health Insurance Act; refusal to provide records may have
serious consequences including suspension of payments and/or a court order.

This is one of several opportunities for you to provide any information you
believe the Ministry should consider. You may retain legal counsel at any time.

Sincerely,
Provider Audit Unit, OHIP Division
"""

    if kind == "billing_education":
        return f"""# Billing Education Letter

**Date:** {today}
**Re:** Physician {provider_id} ({specialty})
**Stage:** {case.get('stage', 'Initial Action')}

Dear Doctor,

Following a review of your OHIP claims, the Ministry is providing billing
education to support accurate future claim submissions. The review identified
the following pattern(s) for your attention:
{concern_lines}

No recovery is sought at this time. Please review the relevant provisions of the
Schedule of Benefits and ensure future submissions reflect the services
rendered. Further review of claims may occur.

Sincerely,
Provider Audit Unit, OHIP Division
"""

    if kind == "gm_opinion":
        amt = (f"${recoverable:,.0f}" if recoverable else "$0")
        note = ("" if figure_status == "DEFENSIBLE" else
                "\n> Note: the amount below is INDICATIVE — derived from a "
                "demonstration fee schedule and not yet validated against "
                "adjudicated outcomes. It is not a final determination.\n")
        return f"""# Notice of the General Manager's Opinion

**Date:** {today}
**Re:** Physician {provider_id} ({specialty})
**Stage:** {case.get('stage', 'Full Audit Review')}
{note}
Dear Doctor,

Having reviewed the Ministry's claims data, the medical records you provided,
and your submissions, the General Manager has formed an Opinion regarding the
following Potential Billing Concern(s):
{concern_lines}

Estimated amount at issue (subject to the statutory 24-month / 5-year limit):
**{amt}**.

You may resolve this matter by negotiated settlement, or the General Manager may
refer it to the Health Services Appeal and Review Board (HSARB). Recovery can be
ordered only by the HSARB (or by your voluntary repayment). You may make written
and oral submissions to the Board and retain legal counsel.

Sincerely,
General Manager, OHIP (per Provider Audit Unit)
"""

    if kind == "review_complete":
        return f"""# Review Complete — No Further Action

**Date:** {today}
**Re:** Physician {provider_id} ({specialty})

Dear Doctor,

The Ministry has completed its review of the Potential Billing Concern and is
satisfied that the claims reviewed were appropriate for the services rendered.
No further action will be taken at this time. Thank you for your cooperation.

Sincerely,
Provider Audit Unit, OHIP Division
"""

    raise ValueError(f"unknown letter kind: {kind!r}")


# ── Self-test ─────────────────────────────────────────────────────────────────

def _selftest():
    import tempfile
    global DB_PATH
    orig = DB_PATH
    DB_PATH = os.path.join(tempfile.gettempdir(), "case_selftest.db")
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    try:
        c = get_case("PRV0001")
        assert c["stage"] == "Initial Action"
        c2 = set_stage("PRV0001", "Full Audit Review", user="auditor1")
        assert c2["records_requested_date"] and c2["ack_due_date"]
        record_correspondence("PRV0001", "records_request", "RFI sent", user="auditor1")
        assert len(get_correspondence("PRV0001")) == 1
        letter = generate_letter("PRV0001", "records_request",
                                 specialty="Cardiology", concerns=["Unbundling"])
        assert "Request for Records and Information" in letter
        print("    [PASS] case lifecycle, correspondence, and letter generation")
    finally:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        DB_PATH = orig


if __name__ == "__main__":
    print("case_management.py — Self-test")
    print("=" * 60)
    _selftest()
    print("=" * 60)
    print("  All case-management tests passed.")
