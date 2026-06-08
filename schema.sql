-- ============================================================
-- Physician Billing Anomaly Detection — Database Schema
-- Compatible with: SQLite 3, PostgreSQL 13+, MySQL 8+
-- ============================================================
-- NOTE: All data is SYNTHETIC. This schema is for demonstration
-- and decision-support tooling only. No real patient data.
-- ============================================================

-- ── Reference tables ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS clinics (
    clinic_id       VARCHAR(10)  PRIMARY KEY,
    clinic_name     VARCHAR(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS fee_schedule (
    fee_code        VARCHAR(10)     PRIMARY KEY,
    fee_description VARCHAR(100)    NOT NULL,
    standard_minutes INT            NOT NULL,
    standard_amount  DECIMAL(10,2)  NOT NULL,
    tier             SMALLINT       NOT NULL   -- 1=low  2=mid  3=high
);

CREATE TABLE IF NOT EXISTS bundle_rules (
    bundle_id       INTEGER      PRIMARY KEY AUTOINCREMENT,   -- use SERIAL in Postgres
    component_1     VARCHAR(10)  NOT NULL,
    component_2     VARCHAR(10)  NOT NULL,
    bundle_code     VARCHAR(10)  NOT NULL,
    bundle_description VARCHAR(100),
    FOREIGN KEY (component_1)  REFERENCES fee_schedule(fee_code),
    FOREIGN KEY (component_2)  REFERENCES fee_schedule(fee_code),
    FOREIGN KEY (bundle_code)  REFERENCES fee_schedule(fee_code)
);

CREATE TABLE IF NOT EXISTS specialty_top_codes (
    specialty       VARCHAR(50)  NOT NULL,
    fee_code        VARCHAR(10)  NOT NULL,
    PRIMARY KEY (specialty, fee_code),
    FOREIGN KEY (fee_code) REFERENCES fee_schedule(fee_code)
);

-- ── Core entity tables ────────────────────────────────────────

CREATE TABLE IF NOT EXISTS providers (
    provider_id     VARCHAR(10)  PRIMARY KEY,
    provider_name   VARCHAR(100) NOT NULL,
    specialty       VARCHAR(50)  NOT NULL,
    clinic_id       VARCHAR(10)  NOT NULL,
    FOREIGN KEY (clinic_id) REFERENCES clinics(clinic_id)
);

-- ── Fact table ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS claims (
    claim_id        VARCHAR(15)    PRIMARY KEY,
    provider_id     VARCHAR(10)    NOT NULL,
    patient_id      VARCHAR(10)    NOT NULL,
    service_date    DATE           NOT NULL,
    fee_code        VARCHAR(10)    NOT NULL,
    service_minutes INTEGER        NOT NULL,
    units           SMALLINT       NOT NULL DEFAULT 1,
    amount_billed   DECIMAL(10,2)  NOT NULL,
    clinic_id       VARCHAR(10)    NOT NULL,
    FOREIGN KEY (provider_id) REFERENCES providers(provider_id),
    FOREIGN KEY (fee_code)    REFERENCES fee_schedule(fee_code),
    FOREIGN KEY (clinic_id)   REFERENCES clinics(clinic_id)
);

CREATE INDEX IF NOT EXISTS idx_claims_provider   ON claims(provider_id);
CREATE INDEX IF NOT EXISTS idx_claims_date       ON claims(service_date);
CREATE INDEX IF NOT EXISTS idx_claims_patient    ON claims(patient_id);
CREATE INDEX IF NOT EXISTS idx_claims_prov_date  ON claims(provider_id, service_date);
CREATE INDEX IF NOT EXISTS idx_claims_fee_code   ON claims(fee_code);

-- ── Pipeline output tables ────────────────────────────────────

CREATE TABLE IF NOT EXISTS rule_flags (
    flag_id             INTEGER      PRIMARY KEY AUTOINCREMENT,
    provider_id         VARCHAR(10)  NOT NULL,
    rule_name           VARCHAR(50)  NOT NULL,   -- impossible_day | duplicate_billing | unbundling
    evidence            TEXT,
    estimated_exposure  DECIMAL(12,2),
    created_at          TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (provider_id) REFERENCES providers(provider_id)
);

CREATE TABLE IF NOT EXISTS peer_flags (
    flag_id             INTEGER      PRIMARY KEY AUTOINCREMENT,
    provider_id         VARCHAR(10)  NOT NULL,
    metric              VARCHAR(50)  NOT NULL,
    provider_value      DECIMAL(12,4),
    peer_median         DECIMAL(12,4),
    z_score             DECIMAL(8,2),
    estimated_exposure  DECIMAL(12,2),
    created_at          TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (provider_id) REFERENCES providers(provider_id)
);

CREATE TABLE IF NOT EXISTS provider_metrics (
    provider_id          VARCHAR(10)  PRIMARY KEY,
    total_claims         INTEGER,
    total_billed         DECIMAL(12,2),
    avg_billed           DECIMAL(10,2),
    avg_minutes          DECIMAL(8,2),
    billed_days          INTEGER,
    claims_per_day       DECIMAL(8,2),
    unique_patients      INTEGER,
    services_per_patient DECIMAL(8,2),
    top_tier_share       DECIMAL(6,4),
    unique_codes         INTEGER,
    max_daily_minutes    INTEGER,
    dup_rate             DECIMAL(8,4),
    FOREIGN KEY (provider_id) REFERENCES providers(provider_id)
);

CREATE TABLE IF NOT EXISTS ml_scores (
    provider_id     VARCHAR(10)  PRIMARY KEY,
    ml_raw_score    DECIMAL(10,4),
    ml_score        DECIMAL(6,2),   -- 0-100 normalised
    ml_is_anomaly   SMALLINT,       -- 1 = anomaly, 0 = normal
    FOREIGN KEY (provider_id) REFERENCES providers(provider_id)
);

CREATE TABLE IF NOT EXISTS risk_scores (
    provider_id          VARCHAR(10)    PRIMARY KEY,
    risk_score           DECIMAL(5,1),
    estimated_exposure   DECIMAL(12,2),
    rules_score          DECIMAL(5,1),
    peer_score           DECIMAL(5,1),
    ml_score             DECIMAL(5,1),
    ml_is_anomaly        SMALLINT,
    top_reason           TEXT,
    FOREIGN KEY (provider_id) REFERENCES providers(provider_id)
);

CREATE TABLE IF NOT EXISTS explanations (
    provider_id          VARCHAR(10)  PRIMARY KEY,
    risk_score           DECIMAL(5,1),
    estimated_exposure   DECIMAL(12,2),
    explanation_text     TEXT,
    generated_by         VARCHAR(20)  DEFAULT 'template',  -- 'template' or 'anthropic_api'
    created_at           TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (provider_id) REFERENCES providers(provider_id)
);

-- ── Audit trail (optional — track human reviewer actions) ─────

CREATE TABLE IF NOT EXISTS audit_reviews (
    review_id       INTEGER      PRIMARY KEY AUTOINCREMENT,
    provider_id     VARCHAR(10)  NOT NULL,
    reviewer_name   VARCHAR(100),
    review_date     DATE,
    outcome         VARCHAR(30),   -- confirmed_fraud | false_positive | needs_more_info | cleared
    notes           TEXT,
    FOREIGN KEY (provider_id) REFERENCES providers(provider_id)
);
