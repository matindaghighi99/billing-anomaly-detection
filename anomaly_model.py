"""Phase 4 -- Unsupervised anomaly detection (ENSEMBLE: IF + LOF + OC-SVM).

PHASE 5 CHANGES:
  Previously only IsolationForest.  Now three detectors run in parallel and
  their outputs are aggregated into a CONSENSUS score.

  IsolationForest (IF)  -- Global outlier tree-ensemble; fast, good at
                           volume/cost extremes.
  Local Outlier Factor (LOF)  -- Density-based; detects providers whose local
                                  neighbourhood is unusually sparse.  Better at
                                  finding moderate outliers missed by IF.
  One-Class SVM (OC-SVM)  -- Boundary-based; finds providers outside the
                              "normal" hypersphere.  Adds a third independent
                              decision surface.

  CONSENSUS SCORING:
  Each detector predicts anomaly (1) or normal (0).  The ensemble score
  combines the three normalised decision scores:
    consensus_score = 0.5 * IF_score + 0.3 * LOF_score + 0.2 * OCSVM_score

  The ml_is_anomaly flag requires agreement from at least 2 of 3 detectors,
  raising precision and reducing false positives on legitimate outliers.

Outputs ml_scores.csv with per-detector and ensemble columns.
"""

import logging
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import RobustScaler
from sklearn.svm import OneClassSVM

from validators import validate_claims_df

SEED       = 42
INPUT_CSV  = "claims.csv"

logger = logging.getLogger(__name__)
METRICS_CSV = "provider_metrics.csv"
OUTPUT_CSV = "ml_scores.csv"

# ── DuckDB helper ─────────────────────────────────────────────────────────────

def _build_core_with_duckdb(df: pd.DataFrame) -> pd.DataFrame:
    """Build per-provider core aggregates using DuckDB SQL.

    Faster than pandas groupby on larger datasets; same result.
    Falls back to pandas if duckdb is not installed.
    """
    try:
        import duckdb
    except ImportError:
        return None

    con = duckdb.connect()
    con.register("claims", df)

    core = con.execute("""
        SELECT
            provider_id,
            COUNT(*)                                         AS total_claims,
            SUM(amount_billed)                              AS total_billed,
            AVG(amount_billed)                              AS avg_billed,
            STDDEV_SAMP(amount_billed)                      AS std_billed,
            AVG(service_minutes)                            AS avg_minutes,
            COUNT(DISTINCT patient_id)                      AS unique_patients,
            COUNT(DISTINCT fee_code)                        AS unique_codes,
            MAX(amount_billed)                              AS max_billed,
            COUNT(DISTINCT service_date)                    AS billed_days
        FROM claims
        GROUP BY provider_id
    """).df()

    # Derived columns
    core["claims_per_day"]       = core["total_claims"] / core["billed_days"].clip(lower=1)
    core["services_per_patient"] = core["total_claims"] / core["unique_patients"].clip(lower=1)
    core["billed_cv"]            = core["std_billed"] / core["avg_billed"].clip(lower=0.01)

    # Max daily minutes via DuckDB
    daily_max = con.execute("""
        SELECT provider_id, MAX(daily_min) AS max_daily_minutes
        FROM (
            SELECT provider_id, service_date,
                   SUM(service_minutes) AS daily_min
            FROM claims
            GROUP BY provider_id, service_date
        ) t
        GROUP BY provider_id
    """).df()

    # Duplicate rate: rows where (provider, patient, fee_code, date) appears > once
    dup_counts = con.execute("""
        SELECT provider_id, COUNT(*) AS dup_groups
        FROM (
            SELECT provider_id, patient_id, fee_code, service_date
            FROM claims
            GROUP BY provider_id, patient_id, fee_code, service_date
            HAVING COUNT(*) > 1
        ) d
        GROUP BY provider_id
    """).df()

    con.close()

    core = core.merge(daily_max, on="provider_id", how="left")
    core = core.merge(dup_counts, on="provider_id", how="left")
    core["max_daily_minutes"] = core["max_daily_minutes"].fillna(0)
    core["dup_rate"] = (core["dup_groups"].fillna(0) / core["total_claims"]).fillna(0)
    core = core.drop(columns=["dup_groups"], errors="ignore")
    core = core.set_index("provider_id")
    return core

# All 15 fee codes — for encoding code-mix features
ALL_CODES = [
    "99213","99214","99215","99232",
    "93000","93005","93010",
    "72148","70553",
    "90837","90834",
    "11100","11101",
    "27447","43239",
]


def load_claims() -> pd.DataFrame:
    return pd.read_csv(INPUT_CSV, parse_dates=["service_date"],
                       dtype={"fee_code": str, "provider_id": str,
                              "patient_id": str, "clinic_id": str})


_ANOMALY_REQUIRED = [
    "claim_id", "provider_id", "provider_name", "specialty",
    "fee_code", "service_date", "service_minutes", "amount_billed", "patient_id",
]

_EMPTY_FEATURES = pd.DataFrame()


def build_feature_matrix(df: pd.DataFrame,
                          provider_subset: list = None) -> pd.DataFrame:
    """One row per provider with ~25 numeric features.

    provider_subset: optional list of provider_ids to score (two-stage funnel).
    Uses DuckDB for core aggregations when available; falls back to pandas.
    """
    try:
        df = validate_claims_df(df, _ANOMALY_REQUIRED, caller="anomaly_model")
    except (ValueError, TypeError) as exc:
        raise ValueError(f"[anomaly_model] Validation failed: {exc}") from exc

    if df.empty:
        return _EMPTY_FEATURES.copy()

    # Coerce numeric columns before passing to DuckDB
    df = df.copy()
    df["service_minutes"] = pd.to_numeric(df["service_minutes"], errors="coerce").fillna(0)
    df["amount_billed"]   = pd.to_numeric(df["amount_billed"],   errors="coerce").fillna(0)

    if provider_subset is not None:
        df = df[df["provider_id"].isin(provider_subset)].copy()

    # ── Specialty encoding ───────────────────────────────────────────────────
    spec_dummies = pd.get_dummies(
        df.groupby("provider_id")["specialty"].first(), prefix="spec"
    )

    # ── Core metrics (DuckDB fast path) ──────────────────────────────────────
    core = _build_core_with_duckdb(df)
    if core is None:
        # Pandas fallback
        billed_days = df.groupby("provider_id")["service_date"].nunique().rename("billed_days")
        core = df.groupby("provider_id").agg(
            total_claims    =("claim_id",        "count"),
            total_billed    =("amount_billed",   "sum"),
            avg_billed      =("amount_billed",   "mean"),
            std_billed      =("amount_billed",   "std"),
            avg_minutes     =("service_minutes", "mean"),
            unique_patients =("patient_id",      "nunique"),
            unique_codes    =("fee_code",        "nunique"),
            max_billed      =("amount_billed",   "max"),
        ).join(billed_days)
        core["claims_per_day"]       = core["total_claims"] / core["billed_days"].clip(lower=1)
        core["services_per_patient"] = core["total_claims"] / core["unique_patients"].clip(lower=1)
        core["billed_cv"]            = core["std_billed"] / core["avg_billed"].clip(lower=0.01)
        dup_key   = ["provider_id", "patient_id", "fee_code", "service_date"]
        dup_total = df.groupby(dup_key).size().reset_index(name="cnt")
        dup_total = dup_total[dup_total["cnt"] > 1].groupby("provider_id")["cnt"].count()
        core["dup_rate"] = (dup_total / core["total_claims"]).fillna(0)
        daily_min = df.groupby(["provider_id", "service_date"])["service_minutes"].sum()
        core["max_daily_minutes"] = daily_min.groupby("provider_id").max()

    # ── Top-tier code share (vectorized) ────────────────────────────────────
    SPECIALTY_TOP = {
        "Family Medicine": {"99215"},
        "Cardiology":      {"99215"},
        "Radiology":       {"70553"},
        "Psychiatry":      {"90837"},
        "Dermatology":     {"11100"},
        "Surgery":         {"27447", "43239"},
    }

    # Build a per-row boolean: is this claim's fee_code a top-tier code for
    # its provider's specialty?  Then aggregate per provider — no Python loop.
    prov_spec = df.groupby("provider_id")["specialty"].first()
    top_codes_for_provider = prov_spec.map(
        lambda s: SPECIALTY_TOP.get(s, set())
    )
    # Expand back to claim-level: map provider_id -> set of top codes
    claim_top_set = df["provider_id"].map(top_codes_for_provider)
    is_top = pd.Series(
        [code in (tops if isinstance(tops, set) else set())
         for code, tops in zip(df["fee_code"], claim_top_set)],
        index=df.index,
        dtype=float,
    )
    core["top_tier_share"] = is_top.groupby(df["provider_id"]).mean()

    # ── Per-code fraction (code-mix fingerprint) ─────────────────────────────
    code_counts = (
        df.groupby(["provider_id", "fee_code"])
          .size()
          .unstack(fill_value=0)
    )
    code_fractions = code_counts.div(code_counts.sum(axis=1), axis=0)
    for c in ALL_CODES:
        if c not in code_fractions.columns:
            code_fractions[c] = 0.0
    code_fractions = code_fractions[ALL_CODES].add_prefix("pct_")

    # ── Shannon entropy (vectorized — no per-row Python apply) ──────────────
    pct_vals = code_fractions.values.astype(float)
    # Avoid log(0): replace 0 with 1 (log(1)=0, so those terms vanish)
    safe_p = np.where(pct_vals > 0, pct_vals, 1.0)
    entropy_vals = -np.sum(np.where(pct_vals > 0, pct_vals * np.log2(safe_p), 0.0), axis=1)
    core["code_entropy"] = pd.Series(entropy_vals, index=code_fractions.index)

    # ── Assemble ──────────────────────────────────────────────────────────────
    features = core.join(code_fractions).join(spec_dummies)
    features = features.fillna(0)
    return features


def _normalise(scores: np.ndarray) -> np.ndarray:
    """Invert-and-scale anomaly scores to 0-100 (100 = most anomalous)."""
    inverted = -scores
    lo, hi   = inverted.min(), inverted.max()
    return (inverted - lo) / (hi - lo + 1e-9) * 100


def fit_ensemble(features: pd.DataFrame) -> pd.DataFrame:
    """Fit IF + LOF + OC-SVM, return per-provider consensus scores."""
    provider_ids = features.index.tolist()
    X = features.values.astype(float)

    scaler   = RobustScaler()
    X_scaled = scaler.fit_transform(X)

    CONTAM = 0.10

    # ── Isolation Forest ─────────────────────────────────────────────────────
    iforest = IsolationForest(
        n_estimators=300, max_samples="auto",
        contamination=CONTAM, random_state=SEED, n_jobs=-1,
    )
    iforest.fit(X_scaled)
    if_raw    = iforest.decision_function(X_scaled)
    if_scores = _normalise(if_raw)
    if_labels = (iforest.predict(X_scaled) == -1).astype(int)

    # ── Local Outlier Factor ──────────────────────────────────────────────────
    lof = LocalOutlierFactor(
        n_neighbors=min(20, len(X_scaled) - 1),
        contamination=CONTAM,
        novelty=False,
    )
    lof_labels = (lof.fit_predict(X_scaled) == -1).astype(int)
    # negative_outlier_factor_: more negative => more anomalous
    lof_scores = _normalise(lof.negative_outlier_factor_)

    # ── One-Class SVM ─────────────────────────────────────────────────────────
    # nu ~ contamination fraction; use rbf kernel, auto-scaled
    ocsvm = OneClassSVM(nu=CONTAM, kernel="rbf", gamma="auto")
    ocsvm.fit(X_scaled)
    ocsvm_raw    = ocsvm.decision_function(X_scaled)
    ocsvm_scores = _normalise(ocsvm_raw)
    ocsvm_labels = (ocsvm.predict(X_scaled) == -1).astype(int)

    # ── Consensus ────────────────────────────────────────────────────────────
    # Weighted average of normalised scores
    ensemble_scores = (
        0.50 * if_scores +
        0.30 * lof_scores +
        0.20 * ocsvm_scores
    )

    # Majority vote (>= 2 of 3 detectors) for binary flag
    vote_sum = if_labels + lof_labels + ocsvm_labels
    consensus_flag = (vote_sum >= 2).astype(int)

    return pd.DataFrame({
        "provider_id":        provider_ids,
        # Ensemble
        "ml_score":           ensemble_scores.round(2),
        "ml_is_anomaly":      consensus_flag,
        "vote_count":         vote_sum,
        # Per-detector
        "if_score":           if_scores.round(2),
        "if_flag":            if_labels,
        "lof_score":          lof_scores.round(2),
        "lof_flag":           lof_labels,
        "ocsvm_score":        ocsvm_scores.round(2),
        "ocsvm_flag":         ocsvm_labels,
    })


_EMPTY_SCORES_DF = pd.DataFrame(columns=[
    "provider_id", "provider_name", "specialty",
    "ml_score", "ml_is_anomaly", "vote_count",
    "if_score", "if_flag", "lof_score", "lof_flag", "ocsvm_score", "ocsvm_flag",
])


def run_anomaly_model(df: pd.DataFrame = None,
                      provider_subset: list = None):
    """Score all providers (or a subset for the two-stage funnel).

    provider_subset: if given, only these providers are scored; all others
    receive ml_score=0, ml_is_anomaly=0 in the final CSV.
    """
    if df is None:
        df = load_claims()
    features = build_feature_matrix(df, provider_subset=provider_subset)
    if features.empty:
        _EMPTY_SCORES_DF.to_csv(OUTPUT_CSV, index=False)
        return _EMPTY_SCORES_DF.copy()
    scores   = fit_ensemble(features)
    meta     = df[["provider_id","provider_name","specialty"]].drop_duplicates("provider_id")
    scores   = scores.merge(meta, on="provider_id")

    if provider_subset is not None:
        # Pad unscored providers with zero scores so downstream joins work
        all_meta  = df[["provider_id","provider_name","specialty"]].drop_duplicates("provider_id")
        unscored  = all_meta[~all_meta["provider_id"].isin(scores["provider_id"])]
        if not unscored.empty:
            zero_cols = {c: 0 for c in scores.columns if c not in ("provider_id","provider_name","specialty")}
            pad = unscored.assign(**zero_cols)
            scores = pd.concat([scores, pad], ignore_index=True)

    scores.to_csv(OUTPUT_CSV, index=False)
    return scores


def main():
    print("Phase 4 - Ensemble Anomaly Detection (IF + LOF + OC-SVM)")
    print("=" * 60)
    df     = load_claims()
    scores = run_anomaly_model(df)

    n_any      = scores["ml_is_anomaly"].sum()
    n_all3     = (scores["vote_count"] == 3).sum()
    n_two      = (scores["vote_count"] == 2).sum()
    print(f"  Providers scored   : {len(scores)}")
    print(f"  Consensus flag (>=2/3) : {n_any}")
    print(f"    All 3 agree        : {n_all3}")
    print(f"    Exactly 2 agree    : {n_two}")
    print()
    print(f"  Top 15 ensemble anomaly scores:")
    print(f"  {'Provider':<12} {'Specialty':<18} {'Ensemble':>9}  {'IF':>7}  {'LOF':>7}  "
          f"{'OC-SVM':>7}  {'Votes':>5}  Flag")
    print("  " + "-" * 74)
    for _, row in scores.nlargest(15, "ml_score").iterrows():
        flag = "YES" if row["ml_is_anomaly"] else "no"
        print(f"  {row['provider_id']:<12} {row['specialty']:<18} "
              f"{row['ml_score']:>9.2f}  {row['if_score']:>7.2f}  "
              f"{row['lof_score']:>7.2f}  {row['ocsvm_score']:>7.2f}  "
              f"{int(row['vote_count']):>5}  {flag}")
    print(f"\n  Saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
