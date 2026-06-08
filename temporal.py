"""Phase 4 (new module) -- Temporal change-point detection.

For each provider, track monthly billing intensity over the 12-month period
and flag sudden jumps using a simple CUSUM (cumulative-sum) change-point
method applied to the month-over-month change in claims/month.

WHY TEMPORAL MATTERS:
A provider who always bills a lot is different from one whose volume suddenly
doubles in month 9.  The sudden-onset pattern is more consistent with
opportunistic fraud (new loophole discovered, new patient roster manufactured)
than with legitimate practice growth.

METHOD:
  1. Aggregate claims per provider per calendar month.
  2. Compute month-over-month fractional change in claims.
  3. Run a one-sided CUSUM on the fractional-change series: resets to 0 when
     change is negative (i.e. billing decreased), accumulates when positive.
  4. Flag when the CUSUM statistic exceeds CUSUM_THRESHOLD (calibrated so
     that ~5% of clean providers are flagged -- no jumps expected).
  5. Also flag providers where any single month is > SPIKE_MULTIPLIER * the
     provider's own yearly median (single-month spike).

Both the CUSUM score and spike flag are fed into scoring.py.

Outputs temporal_flags.csv and provider_temporal.csv.
"""

import numpy as np
import pandas as pd

INPUT_CSV         = "claims.csv"
OUTPUT_FLAGS_CSV  = "temporal_flags.csv"
OUTPUT_SCORES_CSV = "provider_temporal.csv"

# ── Calibrated thresholds ────────────────────────────────────────────────────
CUSUM_THRESHOLD   = 3.0   # CUSUM score above this => change-point flag
SPIKE_MULTIPLIER  = 3.5   # any month > 3.5x yearly median => spike flag
MIN_ACTIVE_MONTHS = 3     # skip providers with too few data points


# ── CUSUM helper ──────────────────────────────────────────────────────────────

def _cusum_max(series: np.ndarray) -> float:
    """One-sided CUSUM: detect upward trend changes.

    Accumulates positive increments; resets to 0 on any decrease.
    Returns the maximum CUSUM value reached.
    """
    s, s_max = 0.0, 0.0
    for v in series:
        s = max(0.0, s + v)
        if s > s_max:
            s_max = s
    return s_max


# ── Main computation ──────────────────────────────────────────────────────────

def build_temporal_scores(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["month"] = df["service_date"].dt.to_period("M")

    monthly = (
        df.groupby(["provider_id", "provider_name", "specialty", "month"])
          .agg(n_claims=("claim_id", "count"),
               total_billed=("amount_billed", "sum"))
          .reset_index()
    )
    monthly = monthly.sort_values(["provider_id", "month"])

    rows = []
    for pid, grp in monthly.groupby("provider_id"):
        grp = grp.sort_values("month")
        claims_series = grp["n_claims"].values.astype(float)
        n_months = len(claims_series)

        if n_months < MIN_ACTIVE_MONTHS:
            continue

        provider_name = grp["provider_name"].iloc[0]
        specialty     = grp["specialty"].iloc[0]
        total_billed  = grp["total_billed"].sum()
        median_claims = float(np.median(claims_series))

        # Month-over-month fractional change (clipped to avoid division by zero)
        baseline = np.clip(claims_series[:-1], a_min=1, a_max=None)
        mom_changes = (claims_series[1:] - claims_series[:-1]) / baseline

        cusum_score  = _cusum_max(mom_changes)
        cusum_flag   = cusum_score >= CUSUM_THRESHOLD

        # Single-month spike
        spike_ratio  = float(claims_series.max() / max(median_claims, 1))
        spike_flag   = spike_ratio >= SPIKE_MULTIPLIER

        any_flag = cusum_flag or spike_flag

        rows.append({
            "provider_id":        pid,
            "provider_name":      provider_name,
            "specialty":          specialty,
            "n_active_months":    n_months,
            "cusum_score":        round(cusum_score, 4),
            "cusum_flag":         cusum_flag,
            "spike_ratio":        round(spike_ratio, 4),
            "spike_flag":         spike_flag,
            "temporal_flag":      any_flag,
            "estimated_exposure": round(total_billed, 2),
        })

    return pd.DataFrame(rows).sort_values("cusum_score", ascending=False)


def run_temporal(df: pd.DataFrame = None):
    if df is None:
        df = pd.read_csv(INPUT_CSV, parse_dates=["service_date"],
                         dtype={"fee_code": str, "provider_id": str,
                                "patient_id": str})
    scores = build_temporal_scores(df)
    scores.to_csv(OUTPUT_SCORES_CSV, index=False)

    flags = scores[scores["temporal_flag"]].copy()
    flags.to_csv(OUTPUT_FLAGS_CSV, index=False)
    return scores, flags


def main():
    print("Phase 4 - Temporal Change-Point Detection")
    print("=" * 60)

    df = pd.read_csv(INPUT_CSV, parse_dates=["service_date"],
                     dtype={"fee_code": str, "provider_id": str,
                            "patient_id": str})

    scores, flags = run_temporal(df)

    print(f"  Providers analysed : {len(scores)}")
    n_cusum = scores["cusum_flag"].sum()
    n_spike = scores["spike_flag"].sum()
    print(f"  CUSUM flags        : {n_cusum}")
    print(f"  Spike flags        : {n_spike}")
    print(f"  Any temporal flag  : {len(flags)}")
    print()

    if not flags.empty:
        print(f"  {'Provider':<12} {'Specialty':<18} {'CUSUM':>8}  "
              f"{'Spike':>8}  {'Exposure':>12}  Flags")
        print("  " + "-" * 72)
        for _, row in flags.head(20).iterrows():
            flag_str = []
            if row["cusum_flag"]:
                flag_str.append(f"CUSUM={row['cusum_score']:.2f}")
            if row["spike_flag"]:
                flag_str.append(f"spike={row['spike_ratio']:.1f}x")
            print(f"  {row['provider_id']:<12} {row['specialty']:<18} "
                  f"{row['cusum_score']:>8.3f}  "
                  f"{row['spike_ratio']:>8.2f}x  "
                  f"${row['estimated_exposure']:>10,.2f}  {', '.join(flag_str)}")

    print(f"\n  Scores saved : {OUTPUT_SCORES_CSV}")
    print(f"  Flags saved  : {OUTPUT_FLAGS_CSV}")


if __name__ == "__main__":
    main()
