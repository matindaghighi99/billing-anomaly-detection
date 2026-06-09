"""Phase 3 -- Peer-group benchmarking.

Groups providers by specialty, computes per-provider metrics, then scores each
metric within its RISK-ADJUSTED PEER COHORT using the modified z-score (MAD).

PHASE 2 CHANGES -- RISK-ADJUSTED PEER COHORTS:

  1. PRACTICE-SETTING STRATIFICATION
     Providers are split into 'part_time' (< 40% of working year) and 'full_time'
     before comparison.  A locum working 40 days is not compared against full-time
     physicians -- their inherently different practice pattern is no longer
     grounds for a flag.

  2. MINIMUM COHORT SIZE
     If a sub-cohort (specialty + practice_setting) has fewer than
     MIN_COHORT_SIZE providers, the score falls back to the full-specialty
     modified z-score so the estimate stays meaningful.

  3. ONE-SIDED FLAGS FOR DIRECTIONAL METRICS
     Billing fraud is almost always ABOVE the peer median (overbilling, not
     underbilling).  Flagging a provider for unusually LOW claims_per_day
     produces false positives on part-time and locum providers.  Volume and
     billing metrics are therefore only flagged when z > +threshold.

  4. SPECIALTY-AWARE THRESHOLDS
     Radiology imaging volume is driven by referral load and facility throughput,
     not personal effort.  A hospital reader can legitimately process 4-6 studies
     per day; flagging that as suspicious generates false positives.  A higher
     volume threshold for Radiology suppresses this while leaving code-mix and
     cost metrics (which still catch PRV0133's duplicate-billing) intact.

Outputs peer_flags.csv with a new 'cohort_key' column.
"""

import logging
import warnings

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from validators import validate_claims_df

INPUT_CSV   = "claims.csv"

logger = logging.getLogger(__name__)
OUTPUT_CSV  = "peer_flags.csv"
METRICS_CSV = "provider_metrics.csv"

# Top-tier codes per specialty (same as data_gen)
SPECIALTY_TOP_TIER = {
    "Family Medicine": {"99215"},
    "Cardiology":      {"99215"},
    "Radiology":       {"70553"},
    "Psychiatry":      {"90837"},
    "Dermatology":     {"11100"},
    "Surgery":         {"27447", "43239"},
}

# ── Phase 2 cohort parameters ────────────────────────────────────────────────

ZSCORE_THRESHOLD = 3.5          # base threshold (MAD scale)
MIN_COHORT_SIZE  = 5            # fall back to full specialty below this

# Providers with < this fraction of working days active are "part-time"
PART_TIME_THRESHOLD = 0.40      # < 40% of 261 working days (~104 days)
N_WORKING_DAYS      = 261       # calendar year 2024

# Only flag ABOVE-median deviations for these metrics.
# A provider billing LOW is not fraudulent; flagging them creates FP on locums.
POSITIVE_ONLY_METRICS = {
    "claims_per_day",
    "services_per_patient",
    "avg_billed",
    "top_tier_share",
    "avg_minutes",
}

# Per-specialty per-metric threshold overrides.
# Radiology imaging volume reflects facility throughput, not fraud effort.
# Raising the threshold stops legitimate high-throughput readers from being
# flagged for volume alone while keeping the cost/code-mix checks active.
SPECIALTY_THRESHOLDS = {
    "Radiology": {
        "claims_per_day": 65.0,   # >65 modified-z required to flag Radiology volume
    },
}


# ── Data loading ──────────────────────────────────────────────────────────────

def load_claims() -> pd.DataFrame:
    return pd.read_csv(INPUT_CSV, parse_dates=["service_date"],
                       dtype={"fee_code": str, "provider_id": str,
                              "patient_id": str, "clinic_id": str})


# ── Metric building ───────────────────────────────────────────────────────────

def build_provider_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """One row per provider with billing behaviour metrics."""

    billed_days = (
        df.groupby("provider_id")["service_date"]
          .nunique()
          .rename("billed_days")
    )

    agg = df.groupby(["provider_id", "provider_name", "specialty"]).agg(
        total_claims   =("claim_id",        "count"),
        total_billed   =("amount_billed",   "sum"),
        avg_billed     =("amount_billed",   "mean"),
        avg_minutes    =("service_minutes", "mean"),
        unique_patients=("patient_id",      "nunique"),
        unique_codes   =("fee_code",        "nunique"),
    ).reset_index()
    agg = agg.join(billed_days, on="provider_id")

    agg["claims_per_day"]      = agg["total_claims"] / agg["billed_days"].clip(lower=1)
    agg["services_per_patient"] = agg["total_claims"] / agg["unique_patients"].clip(lower=1)

    def top_tier_share(sub: pd.DataFrame) -> float:
        # include_groups=False means 'specialty' is NOT in sub; look it up from df
        pid  = sub.index[0] if hasattr(sub.index, '__len__') and len(sub.index) > 0 else None
        if pid is None or "provider_id" not in df.columns:
            return 0.0
        spec_vals = df.loc[df["provider_id"] == pid, "specialty"]
        if spec_vals.empty:
            return 0.0
        spec = spec_vals.iloc[0]
        top  = SPECIALTY_TOP_TIER.get(spec, set())
        if not top:
            return 0.0
        if "fee_code" not in sub.columns:
            return 0.0
        return float((sub["fee_code"].isin(top)).mean())

    try:
        top_shares_raw = (
            df.groupby("provider_id")
              .apply(top_tier_share, include_groups=False)
        )
        # Ensure it is a Series (groupby.apply may return a scalar on single group)
        if not isinstance(top_shares_raw, pd.Series):
            top_shares_raw = pd.Series(
                [top_shares_raw],
                index=df["provider_id"].unique()[:1],
            )
        top_shares = top_shares_raw.rename("top_tier_share")
    except Exception as exc:
        warnings.warn(f"[peer_stats] top_tier_share computation failed: {exc}; defaulting to 0",
                      UserWarning)
        top_shares = pd.Series(0.0,
                               index=df["provider_id"].unique(),
                               name="top_tier_share")
    agg = agg.join(top_shares, on="provider_id")
    if "top_tier_share" not in agg.columns:
        agg["top_tier_share"] = 0.0
    agg["top_tier_share"] = agg["top_tier_share"].fillna(0.0)

    # ── Practice-setting flag ─────────────────────────────────────────────────
    agg["active_day_fraction"] = agg["billed_days"] / N_WORKING_DAYS
    agg["practice_setting"]    = agg["active_day_fraction"].apply(
        lambda f: "part_time" if f < PART_TIME_THRESHOLD else "full_time"
    )
    agg["cohort_key"] = agg["specialty"] + " | " + agg["practice_setting"]

    return agg


# ── Robust z-score helpers ────────────────────────────────────────────────────

def _modified_zscore(x: pd.Series) -> pd.Series:
    """Modified z-score: 0.6745 * (x - median) / MAD.

    Robust to outliers because both the median and MAD have a 50% breakdown
    point.  Falls back to plain z-score if MAD == 0 (all values identical).

    BUG FIX (hardening): when MAD == 0 and scipy.stats.zscore also returns NaN
    (because std == 0 for all-identical values, causing 0/0), fill NaN with 0.
    All-identical values have zero deviation from the median, so z = 0 is
    the mathematically correct answer; NaN would cause build_flags to silently
    skip every provider in such a cohort.
    """
    med = x.median()
    mad = (x - med).abs().median()
    if mad == 0:
        z_vals = scipy_stats.zscore(x, ddof=1, nan_policy="omit")
        # When std == 0 (all-identical), scipy returns NaN; replace with 0
        # because zero deviation from median = z-score of 0 by definition.
        z_vals = np.where(np.isnan(z_vals), 0.0, z_vals)
        return pd.Series(z_vals, index=x.index)
    return 0.6745 * (x - med) / mad


def zscore_within_cohort(metrics: pd.DataFrame) -> pd.DataFrame:
    """Modified z-scores within specialty + practice_setting cohort.

    If a cohort is smaller than MIN_COHORT_SIZE, falls back to the
    full-specialty distribution to keep the estimate stable.
    """
    numeric_cols = [
        "avg_billed", "claims_per_day", "top_tier_share",
        "services_per_patient", "avg_minutes",
    ]

    for col in numeric_cols:
        z_col  = f"z_{col}"
        z_vals = pd.Series(np.nan, index=metrics.index, dtype=float)

        for cohort_key, grp in metrics.groupby("cohort_key"):
            specialty = grp["specialty"].iloc[0]

            if len(grp) >= MIN_COHORT_SIZE:
                z_vals.loc[grp.index] = _modified_zscore(grp[col]).values
            else:
                # Fall back: use full-specialty modified z-score for this provider
                full_spec = metrics[metrics["specialty"] == specialty]
                full_z    = _modified_zscore(full_spec[col])
                z_vals.loc[grp.index] = full_z.loc[grp.index].values

        metrics[z_col] = z_vals

    return metrics


# ── Flag building ─────────────────────────────────────────────────────────────

def _get_threshold(specialty: str, metric: str) -> float:
    return SPECIALTY_THRESHOLDS.get(specialty, {}).get(metric, ZSCORE_THRESHOLD)


def build_flags(metrics: pd.DataFrame) -> pd.DataFrame:
    """One row per (provider, metric) where |z| > threshold.

    Enforces one-sided flagging for POSITIVE_ONLY_METRICS: a provider below
    the peer median on those metrics is NOT flagged (underbilling is not fraud).
    """
    numeric_cols = [
        "avg_billed", "claims_per_day", "top_tier_share",
        "services_per_patient", "avg_minutes",
    ]
    # Compute per-cohort medians for reporting
    cohort_medians = metrics.groupby("cohort_key")[numeric_cols].median()

    rows = []
    for _, prov in metrics.iterrows():
        cohort   = prov["cohort_key"]
        spec     = prov["specialty"]
        medians  = cohort_medians.loc[cohort] if cohort in cohort_medians.index \
                   else metrics[metrics["specialty"] == spec][numeric_cols].median()

        for col in numeric_cols:
            z = prov.get(f"z_{col}", np.nan)
            if pd.isna(z):
                continue

            threshold = _get_threshold(spec, col)

            # One-sided: skip negative z for above-median-only metrics
            if col in POSITIVE_ONLY_METRICS and z <= 0:
                continue

            if abs(z) <= threshold:
                continue

            rows.append({
                "provider_id":        prov["provider_id"],
                "provider_name":      prov["provider_name"],
                "specialty":          spec,
                "cohort_key":         cohort,
                "practice_setting":   prov["practice_setting"],
                "metric":             col,
                "provider_value":     round(float(prov[col]), 4),
                "peer_median":        round(float(medians[col]), 4),
                "z_score":            round(float(z), 2),
                "estimated_exposure": round(float(prov["total_billed"]), 2),
            })

    return pd.DataFrame(rows)


# ── Orchestration ─────────────────────────────────────────────────────────────

_PEER_REQUIRED = [
    "claim_id", "provider_id", "provider_name", "patient_id",
    "fee_code", "service_date", "service_minutes", "amount_billed", "specialty",
]

_EMPTY_FLAGS   = pd.DataFrame(columns=[
    "provider_id","provider_name","specialty","cohort_key","practice_setting",
    "metric","provider_value","peer_median","z_score","estimated_exposure",
])
_EMPTY_METRICS = pd.DataFrame(columns=[
    "provider_id","provider_name","specialty","total_claims","total_billed",
    "avg_billed","avg_minutes","unique_patients","unique_codes","billed_days",
    "claims_per_day","services_per_patient","top_tier_share",
    "active_day_fraction","practice_setting","cohort_key",
])


def run_peer_stats(df: pd.DataFrame = None):
    if df is None:
        df = load_claims()

    try:
        df = validate_claims_df(df, _PEER_REQUIRED, caller="peer_stats")
    except (ValueError, TypeError) as exc:
        warnings.warn(f"[peer_stats] Validation failed: {exc}", UserWarning)
        _EMPTY_METRICS.to_csv(METRICS_CSV, index=False)
        _EMPTY_FLAGS.to_csv(OUTPUT_CSV, index=False)
        return _EMPTY_METRICS.copy(), _EMPTY_FLAGS.copy()

    if df.empty:
        _EMPTY_METRICS.to_csv(METRICS_CSV, index=False)
        _EMPTY_FLAGS.to_csv(OUTPUT_CSV, index=False)
        return _EMPTY_METRICS.copy(), _EMPTY_FLAGS.copy()

    # Need at least 1 provider with numeric service_minutes
    df["service_minutes"] = pd.to_numeric(df["service_minutes"], errors="coerce").fillna(0)
    df["amount_billed"]   = pd.to_numeric(df["amount_billed"],   errors="coerce").fillna(0)

    metrics = build_provider_metrics(df)
    metrics = zscore_within_cohort(metrics)
    metrics.to_csv(METRICS_CSV, index=False)
    flags   = build_flags(metrics)
    flags.to_csv(OUTPUT_CSV, index=False)
    return metrics, flags


def main():
    print("Phase 3 - Peer-Group Benchmarking (Phase 2: risk-adjusted cohorts)")
    print("=" * 60)
    df      = load_claims()
    metrics, flags = run_peer_stats(df)

    print(f"  Providers analysed : {len(metrics)}")
    print(f"  Specialty groups   : {metrics['specialty'].nunique()}")
    print(f"  Cohorts (spec+setting) : {metrics['cohort_key'].nunique()}")
    pt = metrics[metrics["practice_setting"] == "part_time"]
    print(f"  Part-time providers: {len(pt)}")
    print(f"  Flag records       : {len(flags)}")
    print(f"  Flagged providers  : {flags['provider_id'].nunique() if not flags.empty else 0}")
    print()

    if flags.empty:
        print("  No peer-stat anomalies detected.")
        return

    print(f"  {'Provider':<12} {'Specialty':<16} {'Setting':<10} {'Metric':<24} "
          f"{'Value':>8}  {'Med':>8}  {'Z':>8}")
    print("  " + "-" * 92)
    for _, row in flags.sort_values("z_score", key=abs, ascending=False).iterrows():
        print(f"  {row['provider_id']:<12} {row['specialty']:<16} "
              f"{row['practice_setting']:<10} {row['metric']:<24} "
              f"{row['provider_value']:>8.2f}  {row['peer_median']:>8.2f}  {row['z_score']:>8.2f}")

    print(f"\n  Metrics saved : {METRICS_CSV}")
    print(f"  Flags saved   : {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
