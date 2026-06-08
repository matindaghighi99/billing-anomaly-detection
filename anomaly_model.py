"""Phase 4 — Unsupervised anomaly detection with IsolationForest.

Builds a per-provider feature vector from billing behaviour metrics (including
cross-specialty code diversity), fits a scikit-learn IsolationForest, and
outputs an anomaly score per provider.  The model is intentionally
specialty-agnostic so it can surface the 'novel' biller whose out-of-specialty
code mix doesn't trigger any hand-written rule.

Outputs ml_scores.csv.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler

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


def fit_isolation_forest(features: pd.DataFrame) -> pd.DataFrame:
    provider_ids = features.index.tolist()
    X = features.values.astype(float)

    scaler = RobustScaler()
    X_scaled = scaler.fit_transform(X)

    model = IsolationForest(
        n_estimators=300,
        max_samples="auto",
        contamination=0.10,      # ~10% expected anomalies
        random_state=SEED,
        n_jobs=-1,
    )
    model.fit(X_scaled)

    # decision_function: lower (more negative) = more anomalous
    raw_scores = model.decision_function(X_scaled)

    # Invert and normalise to 0–100 (100 = most anomalous)
    inverted   = -raw_scores
    lo, hi     = inverted.min(), inverted.max()
    norm_scores = (inverted - lo) / (hi - lo + 1e-9) * 100

    return pd.DataFrame({
        "provider_id": provider_ids,
        "ml_raw_score": raw_scores.round(4),
        "ml_score":     norm_scores.round(2),
        "ml_is_anomaly": (model.predict(X_scaled) == -1).astype(int),
    })


def run_anomaly_model(df: pd.DataFrame = None):
    if df is None:
        df = load_claims()
    features = build_feature_matrix(df)
    scores   = fit_isolation_forest(features)
    # Attach provider name + specialty
    meta = df[["provider_id","provider_name","specialty"]].drop_duplicates("provider_id")
    scores = scores.merge(meta, on="provider_id")
    scores.to_csv(OUTPUT_CSV, index=False)
    return scores


def main():
    print("Phase 4 - Isolation Forest Anomaly Detection")
    print("=" * 60)
    df     = load_claims()
    scores = run_anomaly_model(df)

    n_anomaly = scores["ml_is_anomaly"].sum()
    print(f"  Providers scored   : {len(scores)}")
    print(f"  Flagged as anomaly : {n_anomaly} (contamination=10%)")
    print()
    print(f"  Top 15 most anomalous providers:")
    print(f"  {'Provider':<12} {'Specialty':<18} {'ML Score':>10}  {'Anomaly?':>9}")
    print("  " + "-" * 52)
    top15 = scores.nlargest(15, "ml_score")
    for _, row in top15.iterrows():
        flag = "YES" if row["ml_is_anomaly"] else "no"
        print(f"  {row['provider_id']:<12} {row['specialty']:<18} {row['ml_score']:>10.2f}  {flag:>9}")

    print(f"\n  Saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
