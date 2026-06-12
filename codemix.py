"""Phase 3 (new module) -- Code-mix drift detection.

For each provider, build a fee-code frequency vector and compare it to the
expected distribution of their specialty cohort.  Two divergence measures:

  KL divergence  -- Kullback-Leibler D(provider || cohort)
                    Sensitive to codes the provider bills *more* than expected.
                    High KL means the provider over-uses certain codes relative
                    to peers even when total volume looks normal.

  Cosine distance  -- 1 - cosine_similarity(provider, cohort)
                    Direction-based; catches when the provider's code mix
                    *pattern* differs from the cohort regardless of scaling.

CALIBRATED THRESHOLDS (from synthetic distribution, seed 42):
  KL >  0.10 => flag (empirically ~top-5% of clean providers)
  cos > 0.15 => flag

Both scores are included in the output.  Either breach => drift_flag = True.
The KL / cosine scores feed into scoring.py as an additional signal layer.

Outputs codemix_flags.csv (one row per flagged provider) and
provider_codemix.csv (one row per provider, all scores).
"""

import logging
import os
import warnings

import numpy as np
import pandas as pd
from scipy.spatial.distance import cosine as cosine_dist
from scipy.special import rel_entr

from validators import validate_claims_df

from dataset_config import CLAIMS_FILE, out

INPUT_CSV         = CLAIMS_FILE

logger = logging.getLogger(__name__)
METRICS_CSV       = out("provider_metrics.csv")   # for practice_setting / cohort_key
OUTPUT_FLAGS_CSV  = out("codemix_flags.csv")
OUTPUT_SCORES_CSV = out("provider_codemix.csv")

# ── Calibrated thresholds ────────────────────────────────────────────────────
KL_THRESHOLD     = 0.10
COSINE_THRESHOLD = 0.15

# Smoothing pseudocount prevents log(0) in KL calculation
EPSILON = 1e-9


# ── Helpers ───────────────────────────────────────────────────────────────────

def _kl_divergence(p: np.ndarray, q: np.ndarray) -> float:
    """KL divergence D(p || q): how much p deviates from q."""
    p = p + EPSILON; p /= p.sum()
    q = q + EPSILON; q /= q.sum()
    return float(rel_entr(p, q).sum())


def _cosine_distance(p: np.ndarray, q: np.ndarray) -> float:
    """Cosine distance (0 = identical direction, 1 = orthogonal)."""
    if p.sum() == 0 or q.sum() == 0:
        return 1.0
    return float(cosine_dist(p, q))


# ── Main computation ──────────────────────────────────────────────────────────

def build_codemix_scores(df: pd.DataFrame, metrics_df: pd.DataFrame) -> pd.DataFrame:
    """Compute per-provider KL and cosine drift scores vs. their cohort median."""

    _meta_required = ["provider_id", "specialty", "cohort_key",
                      "practice_setting", "provider_name", "total_billed"]
    missing_meta = [c for c in _meta_required if c not in metrics_df.columns]
    if missing_meta or metrics_df.empty:
        warnings.warn(
            f"[codemix] metrics_df missing columns {missing_meta} or is empty; "
            "returning empty scores.", UserWarning,
        )
        return _EMPTY_SCORES.copy()

    all_codes = sorted(str(c) for c in df["fee_code"].unique() if pd.notna(c))

    # Per-provider code-frequency vector (fraction of total claims)
    code_counts = (
        df.groupby(["provider_id", "fee_code"])
          .size()
          .unstack(fill_value=0)
          .reindex(columns=all_codes, fill_value=0)
    )
    code_freq = code_counts.div(code_counts.sum(axis=1).clip(lower=1), axis=0)

    # Attach cohort_key from metrics
    prov_meta = metrics_df[["provider_id", "specialty", "cohort_key",
                             "practice_setting", "provider_name",
                             "total_billed"]].copy()

    # Drop rows with null/empty provider_id in metrics to prevent duplicate-index issues
    prov_meta = prov_meta[
        prov_meta["provider_id"].notna() &
        (prov_meta["provider_id"].astype(str).str.strip() != "")
    ]
    prov_meta = prov_meta.drop_duplicates("provider_id")

    if prov_meta.empty:
        warnings.warn("[codemix] No valid providers in metrics_df; returning empty scores.",
                      UserWarning)
        return _EMPTY_SCORES.copy()

    # Cohort reference distribution: median frequency across providers in cohort
    prov_meta = prov_meta.set_index("provider_id")
    freq_with_cohort = code_freq.join(prov_meta[["cohort_key", "specialty"]])

    cohort_ref = (
        freq_with_cohort
        .groupby("cohort_key")[all_codes]
        .median()
    )

    rows = []
    for pid, prow in code_freq.iterrows():
        if pid not in prov_meta.index:
            continue
        cohort_raw = prov_meta.loc[pid, "cohort_key"]
        # .loc may return a Series when there are duplicate index entries — take scalar
        if isinstance(cohort_raw, pd.Series):
            cohort = cohort_raw.iloc[0]
        else:
            cohort = cohort_raw
        try:
            ref = cohort_ref.loc[cohort].values if cohort in cohort_ref.index \
                  else code_freq.mean().values
        except (TypeError, KeyError):
            ref = code_freq.mean().values

        p_vec = prow.values.astype(float)
        q_vec = ref.astype(float)

        kl  = _kl_divergence(p_vec, q_vec)
        cos = _cosine_distance(p_vec, q_vec)

        def _scalar(val):
            """Return scalar from a Series or scalar."""
            return val.iloc[0] if isinstance(val, pd.Series) else val

        rows.append({
            "provider_id":        pid,
            "provider_name":      _scalar(prov_meta.loc[pid, "provider_name"]),
            "specialty":          _scalar(prov_meta.loc[pid, "specialty"]),
            "cohort_key":         cohort,
            "practice_setting":   _scalar(prov_meta.loc[pid, "practice_setting"]),
            "kl_divergence":      round(kl, 6),
            "cosine_distance":    round(cos, 6),
            "drift_flag":         (kl > KL_THRESHOLD) or (cos > COSINE_THRESHOLD),
            "estimated_exposure": float(_scalar(prov_meta.loc[pid, "total_billed"])),
        })

    return pd.DataFrame(rows).sort_values("kl_divergence", ascending=False)


_CODEMIX_REQUIRED = [
    "claim_id", "provider_id", "fee_code", "amount_billed",
]

_EMPTY_SCORES = pd.DataFrame(columns=[
    "provider_id", "provider_name", "specialty", "cohort_key",
    "practice_setting", "kl_divergence", "cosine_distance",
    "drift_flag", "estimated_exposure",
])
_EMPTY_FLAGS = _EMPTY_SCORES.copy()


def run_codemix(df: pd.DataFrame = None, metrics_df: pd.DataFrame = None):
    if df is None:
        df = pd.read_csv(INPUT_CSV, parse_dates=["service_date"],
                         dtype={"fee_code": str, "provider_id": str,
                                "patient_id": str})
    if metrics_df is None:
        if not os.path.exists(METRICS_CSV):
            raise FileNotFoundError(f"{METRICS_CSV} not found. Run peer_stats.py first.")
        metrics_df = pd.read_csv(METRICS_CSV, dtype={"provider_id": str})

    # ── Validate and clean input ──────────────────────────────────────────────
    try:
        df = validate_claims_df(df, _CODEMIX_REQUIRED, caller="codemix")
    except (ValueError, TypeError) as exc:
        warnings.warn(f"[codemix] Validation failed: {exc}", UserWarning)
        _EMPTY_SCORES.to_csv(OUTPUT_SCORES_CSV, index=False)
        _EMPTY_FLAGS.to_csv(OUTPUT_FLAGS_CSV, index=False)
        return _EMPTY_SCORES.copy(), _EMPTY_FLAGS.copy()

    if df.empty or (metrics_df is not None and metrics_df.empty):
        _EMPTY_SCORES.to_csv(OUTPUT_SCORES_CSV, index=False)
        _EMPTY_FLAGS.to_csv(OUTPUT_FLAGS_CSV, index=False)
        return _EMPTY_SCORES.copy(), _EMPTY_FLAGS.copy()

    # Drop genuinely missing fee codes BEFORE astype(str) so we never produce
    # the string "nan" — which would collide with any real claim coded "nan"
    # and silently drop it alongside the missing values.
    df = df.copy()
    df = df[df["fee_code"].notna()]
    df["fee_code"] = df["fee_code"].astype(str)

    if df.empty:
        _EMPTY_SCORES.to_csv(OUTPUT_SCORES_CSV, index=False)
        _EMPTY_FLAGS.to_csv(OUTPUT_FLAGS_CSV, index=False)
        return _EMPTY_SCORES.copy(), _EMPTY_FLAGS.copy()

    scores = build_codemix_scores(df, metrics_df)
    scores.to_csv(OUTPUT_SCORES_CSV, index=False)

    flags = scores[scores["drift_flag"]].copy()
    flags.to_csv(OUTPUT_FLAGS_CSV, index=False)
    return scores, flags


def main():
    print("Phase 3b - Code-Mix Drift Detection")
    print("=" * 60)

    df         = pd.read_csv(INPUT_CSV, parse_dates=["service_date"],
                              dtype={"fee_code": str, "provider_id": str,
                                     "patient_id": str})
    metrics_df = pd.read_csv(METRICS_CSV, dtype={"provider_id": str})

    scores, flags = run_codemix(df, metrics_df)

    print(f"  Providers scored  : {len(scores)}")
    print(f"  Providers flagged : {len(flags)}  "
          f"(KL > {KL_THRESHOLD} or cosine > {COSINE_THRESHOLD})")
    print()

    if flags.empty:
        print("  No code-mix drift flags.")
    else:
        print(f"  {'Provider':<12} {'Specialty':<18} {'Setting':<10} "
              f"{'KL':>8}  {'Cosine':>8}  {'Exposure':>12}")
        print("  " + "-" * 74)
        for _, row in flags.head(20).iterrows():
            print(f"  {row['provider_id']:<12} {row['specialty']:<18} "
                  f"{row['practice_setting']:<10} "
                  f"{row['kl_divergence']:>8.4f}  {row['cosine_distance']:>8.4f}  "
                  f"${row['estimated_exposure']:>10,.2f}")

    print(f"\n  Scores saved : {OUTPUT_SCORES_CSV}")
    print(f"  Flags saved  : {OUTPUT_FLAGS_CSV}")


if __name__ == "__main__":
    main()
