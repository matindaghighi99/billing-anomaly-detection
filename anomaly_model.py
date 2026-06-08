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

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import RobustScaler
from sklearn.svm import OneClassSVM

SEED       = 42
INPUT_CSV  = "claims.csv"
METRICS_CSV = "provider_metrics.csv"
OUTPUT_CSV = "ml_scores.csv"

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


def build_feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """One row per provider with ~25 numeric features."""

    # ── Specialty encoding ───────────────────────────────────────────────────
    spec_dummies = pd.get_dummies(
        df.groupby("provider_id")["specialty"].first(), prefix="spec"
    )

    # ── Core metrics ─────────────────────────────────────────────────────────
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

    # ── Top-tier code share ──────────────────────────────────────────────────
    SPECIALTY_TOP = {
        "Family Medicine": {"99215"},
        "Cardiology":      {"99215"},
        "Radiology":       {"70553"},
        "Psychiatry":      {"90837"},
        "Dermatology":     {"11100"},
        "Surgery":         {"27447", "43239"},
    }

    def top_share(sub):
        spec = df.loc[sub.index, "specialty"].iloc[0]
        top  = SPECIALTY_TOP.get(spec, set())
        return sub.isin(top).mean() if top else 0.0

    core["top_tier_share"] = df.groupby("provider_id")["fee_code"].apply(
        top_share, include_groups=False
    )

    # ── Per-code fraction (code-mix fingerprint) ─────────────────────────────
    code_counts = (
        df.groupby(["provider_id", "fee_code"])
          .size()
          .unstack(fill_value=0)
    )
    # Normalise to fractions
    code_fractions = code_counts.div(code_counts.sum(axis=1), axis=0)
    # Keep only codes present in fee schedule; fill missing columns with 0
    for c in ALL_CODES:
        if c not in code_fractions.columns:
            code_fractions[c] = 0.0
    code_fractions = code_fractions[ALL_CODES].add_prefix("pct_")

    # ── Shannon entropy of code distribution ────────────────────────────────
    def entropy(row):
        p = row[row > 0]
        return float(-np.sum(p * np.log2(p)))

    core["code_entropy"] = code_fractions.apply(entropy, axis=1)

    # ── Duplicate rate ───────────────────────────────────────────────────────
    dup_key   = ["provider_id", "patient_id", "fee_code", "service_date"]
    dup_total = df.groupby(dup_key).size().reset_index(name="cnt")
    dup_total = dup_total[dup_total["cnt"] > 1].groupby("provider_id")["cnt"].count()
    core["dup_rate"] = (dup_total / core["total_claims"]).fillna(0)

    # ── Max daily minutes ─────────────────────────────────────────────────────
    daily_min = df.groupby(["provider_id", "service_date"])["service_minutes"].sum()
    core["max_daily_minutes"] = daily_min.groupby("provider_id").max()

    # ── Assemble ──────────────────────────────────────────────────────────────
    features = core.join(code_fractions).join(spec_dummies)
    features.fillna(0, inplace=True)
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


def run_anomaly_model(df: pd.DataFrame = None):
    if df is None:
        df = load_claims()
    features = build_feature_matrix(df)
    scores   = fit_ensemble(features)
    meta     = df[["provider_id","provider_name","specialty"]].drop_duplicates("provider_id")
    scores   = scores.merge(meta, on="provider_id")
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
