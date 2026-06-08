"""Phase 3 — Peer-group benchmarking.

Groups providers by specialty, computes per-provider metrics, then scores each
metric within its specialty peer group using the MODIFIED z-score (median + MAD)
rather than plain mean/std z-scores.

WHY MAD INSTEAD OF PLAIN Z:
Plain z-scores compute (x - mean) / std.  When the peer group contains even one
extreme bad actor the mean inflates and the std balloons, compressing every other
provider toward zero and masking moderate outliers.  The modified z-score uses
the median and Median Absolute Deviation (MAD) instead:

    modified_z = 0.6745 * (x - median) / MAD

Both the median and the MAD are breakdown-point-50% estimators — half the sample
can be arbitrarily extreme without corrupting the score.  The 0.6745 constant
makes the scale equivalent to a std-based z-score for a normal distribution.

Flags |modified_z| > 3.5  (slightly wider than the classical 3.0 threshold to
account for heavier tails; equivalent literature cutoff is 3.5).

Outputs peer_flags.csv.
"""

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

INPUT_CSV  = "claims.csv"
OUTPUT_CSV = "peer_flags.csv"
METRICS_CSV = "provider_metrics.csv"

# Top-tier codes per specialty (same as in data_gen)
SPECIALTY_TOP_TIER = {
    "Family Medicine": {"99215"},
    "Cardiology":      {"99215"},
    "Radiology":       {"70553"},
    "Psychiatry":      {"90837"},
    "Dermatology":     {"11100"},
    "Surgery":         {"27447", "43239"},
}

ZSCORE_THRESHOLD = 3.5   # slightly wider than 3.0 because MAD tails are heavier


def load_claims() -> pd.DataFrame:
    return pd.read_csv(INPUT_CSV, parse_dates=["service_date"],
                       dtype={"fee_code": str, "provider_id": str,
                              "patient_id": str, "clinic_id": str})


def build_provider_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """One row per provider with billing behaviour metrics."""

    # Days billed per provider
    billed_days = (
        df.groupby("provider_id")["service_date"]
          .nunique()
          .rename("billed_days")
    )

    # Core aggregates
    agg = df.groupby(["provider_id", "provider_name", "specialty"]).agg(
        total_claims   =("claim_id",        "count"),
        total_billed   =("amount_billed",   "sum"),
        avg_billed     =("amount_billed",   "mean"),
        avg_minutes    =("service_minutes", "mean"),
        unique_patients=("patient_id",      "nunique"),
        unique_codes   =("fee_code",        "nunique"),
    ).reset_index()
    agg = agg.join(billed_days, on="provider_id")

    # Claims per billed day
    agg["claims_per_day"] = agg["total_claims"] / agg["billed_days"].clip(lower=1)

    # Services per unique patient
    agg["services_per_patient"] = agg["total_claims"] / agg["unique_patients"].clip(lower=1)

    # Top-tier code share per provider
    def top_tier_share(sub: pd.DataFrame) -> float:
        spec   = sub["specialty"].iloc[0]
        top    = SPECIALTY_TOP_TIER.get(spec, set())
        if not top:
            return 0.0
        return (sub["fee_code"].isin(top)).mean()

    top_shares = (
        df.groupby("provider_id")
          .apply(top_tier_share, include_groups=False)
          .rename("top_tier_share")
    )
    agg = agg.join(top_shares, on="provider_id")

    return agg


def _modified_zscore(x: pd.Series) -> pd.Series:
    """Modified z-score: 0.6745 * (x - median) / MAD.

    Robust to outliers because both the median and the MAD have a 50%
    breakdown point.  Falls back to plain z-score if MAD == 0 (constant group).
    """
    med = x.median()
    mad = (x - med).abs().median()
    if mad == 0:
        return pd.Series(scipy_stats.zscore(x, ddof=1, nan_policy="omit"),
                         index=x.index)
    return 0.6745 * (x - med) / mad


def zscore_within_specialty(metrics: pd.DataFrame) -> pd.DataFrame:
    """Add modified-z-score columns for each numeric metric, per specialty."""
    numeric_cols = [
        "avg_billed", "claims_per_day", "top_tier_share",
        "services_per_patient", "avg_minutes",
    ]
    for col in numeric_cols:
        z_col = f"z_{col}"
        metrics[z_col] = metrics.groupby("specialty")[col].transform(
            _modified_zscore
        )
    return metrics


def build_flags(metrics: pd.DataFrame) -> pd.DataFrame:
    """One row per (provider, metric) where |z| > threshold."""
    numeric_cols = [
        "avg_billed", "claims_per_day", "top_tier_share",
        "services_per_patient", "avg_minutes",
    ]
    peer_medians = metrics.groupby("specialty")[numeric_cols].median()

    rows = []
    for _, prov in metrics.iterrows():
        spec    = prov["specialty"]
        medians = peer_medians.loc[spec]
        for col in numeric_cols:
            z = prov.get(f"z_{col}", np.nan)
            if pd.isna(z) or abs(z) <= ZSCORE_THRESHOLD:
                continue
            rows.append({
                "provider_id":        prov["provider_id"],
                "provider_name":      prov["provider_name"],
                "specialty":          spec,
                "metric":             col,
                "provider_value":     round(float(prov[col]), 4),
                "peer_median":        round(float(medians[col]), 4),
                "z_score":            round(float(z), 2),
                "estimated_exposure": round(float(prov["total_billed"]), 2),
            })

    return pd.DataFrame(rows)


def run_peer_stats(df: pd.DataFrame = None):
    if df is None:
        df = load_claims()
    metrics = build_provider_metrics(df)
    metrics = zscore_within_specialty(metrics)
    metrics.to_csv(METRICS_CSV, index=False)
    flags   = build_flags(metrics)
    flags.to_csv(OUTPUT_CSV, index=False)
    return metrics, flags


def main():
    print("Phase 3 - Peer-Group Benchmarking")
    print("=" * 60)
    df      = load_claims()
    metrics, flags = run_peer_stats(df)

    print(f"  Providers analysed : {len(metrics)}")
    print(f"  Specialty groups   : {metrics['specialty'].nunique()}")
    print(f"  Flag records       : {len(flags)}")
    print(f"  Flagged providers  : {flags['provider_id'].nunique() if not flags.empty else 0}")
    print()

    if flags.empty:
        print("  No peer-stat anomalies detected.")
        return

    print(f"  {'Provider':<12} {'Specialty':<18} {'Metric':<24} {'Value':>10}  "
          f"{'Peer Med':>10}  {'Z':>6}")
    print("  " + "-" * 82)
    for _, row in flags.sort_values("z_score", key=abs, ascending=False).iterrows():
        print(f"  {row['provider_id']:<12} {row['specialty']:<18} {row['metric']:<24} "
              f"{row['provider_value']:>10.2f}  {row['peer_median']:>10.2f}  {row['z_score']:>6.2f}")

    print(f"\n  Metrics saved : {METRICS_CSV}")
    print(f"  Flags saved   : {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
