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
