"""Create billing_anomaly.db (SQLite) from all pipeline CSV/JSON outputs.

Run after all 7 phases have completed:
    python create_db.py

Produces:
    billing_anomaly.db   — fully queryable SQLite database
    queries.sql          — 12 ready-to-run analytical SQL queries
"""

import json
import os
import sqlite3
import sys
import textwrap

# Make the section folders importable as flat modules regardless of CWD.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _sectionpath  # noqa: E402  (registers section folders on sys.path)

import pandas as pd

import dataset_config as _dc

_HERE       = os.path.dirname(os.path.abspath(__file__))
DB_FILE     = _dc.data_path("billing_anomaly.db")
SCHEMA_FILE = os.path.join(_HERE, "sql", "schema.sql")
QUERIES_FILE = os.path.join(_HERE, "sql", "queries.sql")

# ── Fee schedule (source of truth, not derived from CSV) ─────────────────────
FEE_SCHEDULE = [
    ("99213", "Office Visit Brief",           15,  85.00,  1),
    ("99214", "Office Visit Moderate",         25, 130.00,  2),
    ("99215", "Office Visit Complex",          40, 200.00,  3),
    ("99232", "Subsequent Hospital Care",      20, 110.00,  2),
    ("93000", "ECG Complete",                  20,  70.00,  2),
    ("93005", "ECG Tracing Only",              10,  35.00,  1),
    ("93010", "ECG Interpretation Only",       10,  45.00,  1),
    ("72148", "MRI Lumbar Spine",              45, 350.00,  3),
    ("70553", "MRI Brain w/ Contrast",         60, 450.00,  3),
    ("90837", "Psychotherapy 60 min",          60, 180.00,  3),
    ("90834", "Psychotherapy 45 min",          45, 140.00,  2),
    ("11100", "Skin Biopsy First Lesion",      20, 150.00,  2),
    ("11101", "Skin Biopsy Additional Lesion", 10,  75.00,  1),
    ("27447", "Total Knee Replacement",       120, 1200.00, 3),
    ("43239", "Upper GI Endoscopy w/ Biopsy", 30, 380.00,  3),
]

BUNDLE_RULES = [
    ("93005", "93010", "93000", "ECG Complete (bundle of 93005+93010)"),
]

SPECIALTY_TOP_CODES = [
    ("Family Medicine", "99215"),
    ("Cardiology",      "99215"),
    ("Radiology",       "70553"),
    ("Psychiatry",      "90837"),
    ("Dermatology",     "11100"),
    ("Surgery",         "27447"),
    ("Surgery",         "43239"),
]


def get_connection(path: str = DB_FILE) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def create_schema(conn: sqlite3.Connection):
    with open(SCHEMA_FILE) as f:
        sql = f.read()
    # SQLite doesn't support AUTOINCREMENT on non-INTEGER columns the same way;
    # strip the explicit keyword if it causes issues (it's fine in SQLite as-is)
    conn.executescript(sql)
    conn.commit()
    print("  Schema created.")


def load_reference_data(conn: sqlite3.Connection):
    cur = conn.cursor()

    # Fee schedule
    cur.executemany(
        "INSERT OR IGNORE INTO fee_schedule VALUES (?,?,?,?,?)",
        FEE_SCHEDULE,
    )

    # Bundle rules
    cur.executemany(
        "INSERT OR IGNORE INTO bundle_rules (component_1,component_2,bundle_code,bundle_description) "
        "VALUES (?,?,?,?)",
        BUNDLE_RULES,
    )

    # Specialty top codes
    cur.executemany(
        "INSERT OR IGNORE INTO specialty_top_codes VALUES (?,?)",
        SPECIALTY_TOP_CODES,
    )

    conn.commit()
    print("  Reference data loaded.")


def load_claims(conn: sqlite3.Connection):
    df = pd.read_csv(_dc.out("claims.csv"), parse_dates=["service_date"],
                     dtype={"fee_code": str, "provider_id": str,
                            "patient_id": str, "clinic_id": str})

    # Clinics
    clinics = df[["clinic_id"]].drop_duplicates()
    clinics["clinic_name"] = clinics["clinic_id"].apply(lambda c: f"Clinic {c}")
    clinics.to_sql("clinics", conn, if_exists="append", index=False)

    # Providers
    providers = (
        df[["provider_id", "provider_name", "specialty", "clinic_id"]]
          .drop_duplicates("provider_id")
    )
    providers.to_sql("providers", conn, if_exists="append", index=False)

    # Claims
    claims = df[["claim_id", "provider_id", "patient_id", "service_date",
                 "fee_code", "service_minutes", "units", "amount_billed", "clinic_id"]]
    claims = claims.copy()
    claims["service_date"] = claims["service_date"].dt.strftime("%Y-%m-%d")
    claims.to_sql("claims", conn, if_exists="append", index=False)

    conn.commit()
    print(f"  Claims loaded: {len(df):,} rows  |  "
          f"Providers: {df['provider_id'].nunique()}  |  "
          f"Clinics: {df['clinic_id'].nunique()}")


def load_rule_flags(conn: sqlite3.Connection):
    if not os.path.exists(_dc.out("rules_flags.csv")):
        return
    df = pd.read_csv(_dc.out("rules_flags.csv"), dtype={"provider_id": str})
    df = df.rename(columns={"rule": "rule_name"})
    df[["provider_id","rule_name","evidence","estimated_exposure"]].to_sql(
        "rule_flags", conn, if_exists="append", index=False)
    conn.commit()
    print(f"  Rule flags loaded: {len(df)} rows")


def load_peer_flags(conn: sqlite3.Connection):
    if not os.path.exists(_dc.out("peer_flags.csv")):
        return
    df = pd.read_csv(_dc.out("peer_flags.csv"), dtype={"provider_id": str})
    df[["provider_id","metric","provider_value","peer_median",
        "z_score","estimated_exposure"]].to_sql(
        "peer_flags", conn, if_exists="append", index=False)
    conn.commit()
    print(f"  Peer flags loaded: {len(df)} rows")


def load_provider_metrics(conn: sqlite3.Connection):
    if not os.path.exists(_dc.out("provider_metrics.csv")):
        return
    df = pd.read_csv(_dc.out("provider_metrics.csv"), dtype={"provider_id": str})
    cols = ["provider_id","total_claims","total_billed","avg_billed","avg_minutes",
            "billed_days","claims_per_day","unique_patients","services_per_patient",
            "top_tier_share","unique_codes","max_daily_minutes","dup_rate"]
    keep = [c for c in cols if c in df.columns]
    df[keep].to_sql("provider_metrics", conn, if_exists="append", index=False)
    conn.commit()
    print(f"  Provider metrics loaded: {len(df)} rows")


def load_ml_scores(conn: sqlite3.Connection):
    if not os.path.exists(_dc.out("ml_scores.csv")):
        return
    df = pd.read_csv(_dc.out("ml_scores.csv"), dtype={"provider_id": str})
    df[["provider_id","ml_raw_score","ml_score","ml_is_anomaly"]].to_sql(
        "ml_scores", conn, if_exists="append", index=False)
    conn.commit()
    print(f"  ML scores loaded: {len(df)} rows")


def load_risk_scores(conn: sqlite3.Connection):
    if not os.path.exists(_dc.out("risk_scores.csv")):
        return
    df = pd.read_csv(_dc.out("risk_scores.csv"), dtype={"provider_id": str})
    df[["provider_id","risk_score","estimated_exposure","rules_score",
        "peer_score","ml_score","ml_is_anomaly","top_reason"]].to_sql(
        "risk_scores", conn, if_exists="append", index=False)
    conn.commit()
    print(f"  Risk scores loaded: {len(df)} rows")


def load_explanations(conn: sqlite3.Connection):
    if not os.path.exists(_dc.out("explanations.json")):
        return
    with open(_dc.out("explanations.json")) as f:
        data = json.load(f)
    rows = [
        (pid, v["risk_score"], v["estimated_exposure"], v["explanation"], "template")
        for pid, v in data.items()
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO explanations "
        "(provider_id,risk_score,estimated_exposure,explanation_text,generated_by) "
        "VALUES (?,?,?,?,?)",
        rows,
    )
    conn.commit()
    print(f"  Explanations loaded: {len(rows)} rows")


# ── Analytical queries file ───────────────────────────────────────────────────

QUERIES = textwrap.dedent("""\
-- ============================================================
-- Analytical SQL Queries — Physician Billing Anomaly Detection
-- Run against billing_anomaly.db (SQLite) or adapt for
-- PostgreSQL / MySQL.
-- ============================================================

-- ── Q1: Full ranked audit worklist ─────────────────────────────────────────
-- Top 20 providers by combined risk score x dollar exposure.

SELECT
    rs.provider_id,
    p.provider_name,
    p.specialty,
    rs.risk_score,
    printf('$%,.2f', rs.estimated_exposure)  AS estimated_exposure,
    rs.rules_score,
    rs.peer_score,
    ROUND(rs.ml_score, 1)                    AS ml_score,
    rs.top_reason
FROM risk_scores rs
JOIN providers p USING (provider_id)
ORDER BY rs.risk_score * LOG(1 + rs.estimated_exposure / 1000.0) DESC
LIMIT 20;


-- ── Q2: Impossible-day violations ──────────────────────────────────────────
-- Providers + dates where total billed minutes exceed 24 hours (1 440 min).

SELECT
    c.provider_id,
    p.provider_name,
    p.specialty,
    c.service_date,
    SUM(c.service_minutes)                   AS total_minutes,
    COUNT(*)                                 AS n_claims,
    printf('$%,.2f', SUM(c.amount_billed))  AS total_billed
FROM claims c
JOIN providers p USING (provider_id)
GROUP BY c.provider_id, c.service_date
HAVING SUM(c.service_minutes) > 1440
ORDER BY total_minutes DESC;


-- ── Q3: Duplicate claims ────────────────────────────────────────────────────
-- Identical provider + patient + fee_code + service_date submitted > once.

SELECT
    c.provider_id,
    p.provider_name,
    p.specialty,
    c.patient_id,
    c.fee_code,
    fs.fee_description,
    c.service_date,
    COUNT(*)                                  AS n_submissions,
    printf('$%,.2f', SUM(c.amount_billed))   AS total_billed,
    printf('$%,.2f', MIN(c.amount_billed))   AS unit_amount
FROM claims c
JOIN providers p  USING (provider_id)
JOIN fee_schedule fs USING (fee_code)
GROUP BY c.provider_id, c.patient_id, c.fee_code, c.service_date
HAVING COUNT(*) > 1
ORDER BY n_submissions DESC, total_billed DESC;


-- ── Q4: Unbundling detection ────────────────────────────────────────────────
-- Patient-dates where component codes are billed instead of the bundle.

SELECT
    c1.provider_id,
    p.provider_name,
    p.specialty,
    c1.patient_id,
    c1.service_date,
    c1.fee_code                                        AS component_1,
    c2.fee_code                                        AS component_2,
    br.bundle_code,
    printf('$%,.2f', c1.amount_billed + c2.amount_billed)  AS billed_as_components,
    printf('$%,.2f', fs.standard_amount)               AS bundle_price,
    printf('$%,.2f',
        c1.amount_billed + c2.amount_billed - fs.standard_amount
    )                                                  AS overcharge
FROM claims c1
JOIN claims c2
  ON  c1.provider_id  = c2.provider_id
  AND c1.patient_id   = c2.patient_id
  AND c1.service_date = c2.service_date
  AND c1.fee_code     < c2.fee_code
JOIN bundle_rules br
  ON  c1.fee_code = br.component_1
  AND c2.fee_code = br.component_2
JOIN fee_schedule fs ON br.bundle_code = fs.fee_code
JOIN providers p USING (provider_id)
ORDER BY overcharge DESC;


-- ── Q5: Top-tier code share by provider vs specialty median ─────────────────
-- Upcoders bill the most expensive codes far more often than peers.

WITH top_share AS (
    SELECT
        c.provider_id,
        p.specialty,
        ROUND(
            1.0 * SUM(CASE WHEN stc.fee_code IS NOT NULL THEN 1 ELSE 0 END)
            / COUNT(*), 4
        ) AS top_tier_share
    FROM claims c
    JOIN providers p USING (provider_id)
    LEFT JOIN specialty_top_codes stc
      ON p.specialty = stc.specialty AND c.fee_code = stc.fee_code
    GROUP BY c.provider_id, p.specialty
),
specialty_median AS (
    SELECT specialty,
           AVG(top_tier_share) AS avg_share   -- approximation; SQLite has no MEDIAN()
    FROM top_share
    GROUP BY specialty
)
SELECT
    ts.provider_id,
    p.provider_name,
    ts.specialty,
    ROUND(ts.top_tier_share * 100, 1)          AS pct_top_tier,
    ROUND(sm.avg_share * 100, 1)               AS specialty_avg_pct,
    ROUND((ts.top_tier_share - sm.avg_share) * 100, 1) AS pct_above_avg
FROM top_share ts
JOIN providers p USING (provider_id)
JOIN specialty_median sm USING (specialty)
WHERE ts.top_tier_share > sm.avg_share * 1.5   -- 50% above specialty average
ORDER BY pct_above_avg DESC;


-- ── Q6: Claims volume per provider per day ──────────────────────────────────
-- Volume outliers bill many more claims per day than peers.

SELECT
    c.provider_id,
    p.provider_name,
    p.specialty,
    c.service_date,
    COUNT(*)                                   AS n_claims,
    SUM(c.service_minutes)                     AS total_minutes,
    printf('$%,.2f', SUM(c.amount_billed))    AS daily_billed
FROM claims c
JOIN providers p USING (provider_id)
GROUP BY c.provider_id, c.service_date
ORDER BY n_claims DESC
LIMIT 30;


-- ── Q7: Provider summary — billing behaviour overview ───────────────────────

SELECT
    pm.provider_id,
    p.provider_name,
    p.specialty,
    pm.total_claims,
    printf('$%,.2f', pm.total_billed)          AS total_billed,
    printf('$%,.2f', pm.avg_billed)            AS avg_per_claim,
    ROUND(pm.claims_per_day, 2)                AS claims_per_day,
    pm.unique_patients,
    ROUND(pm.services_per_patient, 2)          AS svc_per_patient,
    ROUND(pm.top_tier_share * 100, 1)          AS top_tier_pct,
    pm.max_daily_minutes
FROM provider_metrics pm
JOIN providers p USING (provider_id)
ORDER BY pm.total_billed DESC;


-- ── Q8: ML + peer anomaly overlap ──────────────────────────────────────────
-- Providers flagged by both the ML model AND peer stats — highest confidence.

SELECT
    ml.provider_id,
    p.provider_name,
    p.specialty,
    ROUND(ml.ml_score, 1)                      AS ml_score,
    COUNT(pf.flag_id)                          AS n_peer_flags,
    GROUP_CONCAT(pf.metric, ' | ')             AS flagged_metrics,
    printf('$%,.2f', pm.total_billed)          AS total_billed
FROM ml_scores ml
JOIN providers p USING (provider_id)
JOIN peer_flags pf USING (provider_id)
JOIN provider_metrics pm USING (provider_id)
WHERE ml.ml_is_anomaly = 1
GROUP BY ml.provider_id
ORDER BY ml.ml_score DESC;


-- ── Q9: Monthly billing trend per specialty ─────────────────────────────────

SELECT
    STRFTIME('%Y-%m', service_date)            AS month,
    p.specialty,
    COUNT(*)                                   AS n_claims,
    COUNT(DISTINCT c.provider_id)              AS active_providers,
    printf('$%,.2f', SUM(c.amount_billed))    AS total_billed,
    printf('$%,.2f', AVG(c.amount_billed))    AS avg_billed
FROM claims c
JOIN providers p USING (provider_id)
GROUP BY month, p.specialty
ORDER BY month, p.specialty;


-- ── Q10: Fee code utilisation across specialties ────────────────────────────

SELECT
    c.fee_code,
    fs.fee_description,
    fs.standard_amount,
    p.specialty,
    COUNT(*)                                    AS n_claims,
    ROUND(100.0 * COUNT(*) /
        SUM(COUNT(*)) OVER (PARTITION BY p.specialty), 2) AS pct_of_specialty
FROM claims c
JOIN fee_schedule fs USING (fee_code)
JOIN providers p USING (provider_id)
GROUP BY c.fee_code, p.specialty
ORDER BY p.specialty, pct_of_specialty DESC;


-- ── Q11: Rule flags summary with provider details ───────────────────────────

SELECT
    rf.rule_name,
    rf.provider_id,
    p.provider_name,
    p.specialty,
    COUNT(rf.flag_id)                           AS n_flag_events,
    printf('$%,.2f', SUM(rf.estimated_exposure)) AS total_exposure,
    rf.evidence
FROM rule_flags rf
JOIN providers p USING (provider_id)
GROUP BY rf.rule_name, rf.provider_id
ORDER BY rf.rule_name, total_exposure DESC;


-- ── Q12: Audit review outcomes (populated once auditors add their findings) ──

SELECT
    ar.outcome,
    COUNT(*)                                    AS n_reviews,
    GROUP_CONCAT(ar.provider_id, ', ')          AS providers,
    printf('$%,.2f',
        SUM(rs.estimated_exposure))             AS total_exposure_reviewed
FROM audit_reviews ar
LEFT JOIN risk_scores rs USING (provider_id)
GROUP BY ar.outcome
ORDER BY n_reviews DESC;
""")


def write_queries_file():
    with open(QUERIES_FILE, "w", encoding="utf-8") as f:
        f.write(QUERIES)
    print(f"  Analytical queries written to {QUERIES_FILE}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print("Building SQLite database from pipeline outputs")
    print("=" * 60)

    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        print(f"  Removed existing {DB_FILE}")

    conn = get_connection()

    print("\n  Creating schema ...")
    create_schema(conn)

    print("  Loading reference data ...")
    load_reference_data(conn)

    print("  Loading claims ...")
    load_claims(conn)

    print("  Loading pipeline outputs ...")
    load_rule_flags(conn)
    load_peer_flags(conn)
    load_provider_metrics(conn)
    load_ml_scores(conn)
    load_risk_scores(conn)
    load_explanations(conn)

    # Quick row counts — table names are a hardcoded whitelist; SQLite does not
    # support parameterized identifiers, so we validate against the literal set.
    _SUMMARY_TABLES = (
        "clinics", "providers", "fee_schedule", "bundle_rules",
        "claims", "rule_flags", "peer_flags", "provider_metrics",
        "ml_scores", "risk_scores", "explanations",
    )
    print("\n  Database summary:")
    print("  " + "-" * 40)
    for table in _SUMMARY_TABLES:
        if table not in _SUMMARY_TABLES:
            raise ValueError(f"Unexpected table name: {table!r}")
        # `table` is validated against a hardcoded tuple above (never user input).
        n = conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]  # nosec B608
        print(f"  {table:<25}: {n:>8,} rows")

    conn.close()

    print(f"\n  Database saved to: {DB_FILE}")
    write_queries_file()

    print("\n  Quick-start:")
    print(f"    sqlite3 {DB_FILE}")
    print(f"    .read {QUERIES_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
