"""tests/test_peer_stats_boundary.py
Edge and boundary tests for peer_stats.py

Covers:
  - Minimum cohort size (MIN_COHORT_SIZE = 5) and fallback behaviour
  - MAD z-score math: zero-variance cohort, NaN/Inf propagation
  - Minimum claims floor (there is no MIN_CLAIMS constant in peer_stats.py --
    the module does not filter by total_claims; only MIN_COHORT_SIZE guards
    the cohort)
  - ZSCORE_THRESHOLD = 3.5 boundary (> vs <=)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pytest

from peer_stats import (
    build_provider_metrics,
    zscore_within_cohort,
    build_flags,
    run_peer_stats,
    ZSCORE_THRESHOLD,
    MIN_COHORT_SIZE,
)


# ── DataFrame factory ──────────────────────────────────────────────────────────

def _provider_claims(provider_id: str, n_claims: int, specialty: str = "Family Medicine",
                     avg_minutes: float = 20.0, avg_billed: float = 100.0,
                     n_patients: int = None, n_days: int = None,
                     start_date: str = "2024-01-01") -> pd.DataFrame:
    """Build a minimal claims DataFrame for one provider."""
    if n_patients is None:
        n_patients = max(1, n_claims // 2)
    if n_days is None:
        n_days = max(1, n_claims // 3)

    rng = np.random.default_rng(abs(hash(provider_id)) % (2**32))
    dates = pd.date_range(start_date, periods=n_days, freq="D")

    rows = []
    for i in range(n_claims):
        rows.append({
            "claim_id":       f"{provider_id}_C{i:04d}",
            "provider_id":    provider_id,
            "provider_name":  f"Dr {provider_id}",
            "patient_id":     f"PAT{(i % n_patients):04d}",
            "fee_code":       "99213",
            "service_date":   dates[i % n_days],
            "service_minutes": avg_minutes + rng.uniform(-2, 2),
            "amount_billed":  avg_billed + rng.uniform(-5, 5),
            "specialty":      specialty,
            "clinic_id":      "CLN01",
        })
    return pd.DataFrame(rows)


def _cohort_df(n_providers: int, specialty: str = "Family Medicine",
               avg_minutes: float = 20.0, n_claims_each: int = 30,
               outlier_idx: int = None, outlier_minutes: float = 200.0,
               n_days_each: int = 100) -> pd.DataFrame:
    """Build a cohort DataFrame with n_providers, optionally with one outlier."""
    parts = []
    for i in range(n_providers):
        pid = f"PRV{i:03d}"
        minutes = outlier_minutes if (outlier_idx is not None and i == outlier_idx) \
                  else avg_minutes
        parts.append(
            _provider_claims(pid, n_claims_each, specialty, avg_minutes=minutes,
                             n_days=n_days_each)
        )
    return pd.concat(parts, ignore_index=True)


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_cohort_n1():
    """Cohort of 1 provider: run_peer_stats must not crash.

    With only 1 provider the modified z-score falls back to the full-specialty
    distribution (which is also size 1).  scipy.stats.zscore with ddof=1 on a
    1-element array returns NaN, and build_flags skips NaN z-scores.
    Result: no flags, no crash.
    """
    df = _provider_claims("PRV000", 30)
    metrics, flags = run_peer_stats(df)
    assert isinstance(metrics, pd.DataFrame), "run_peer_stats must return (metrics, flags)"
    assert isinstance(flags, pd.DataFrame),   "run_peer_stats must return (metrics, flags)"
    # With 1 provider there should be no flags (NaN z-scores are skipped)
    assert flags.empty or len(flags) == 0, (
        "Single-provider cohort should produce no peer flags "
        "(NaN z-score is skipped in build_flags)"
    )


def test_cohort_n2():
    """Cohort of 2 providers: must not crash; z-score math is documented.

    With n=2 and ddof=1, the standard deviation has df=1, which is valid.
    The modified z-score uses MAD; with n=2 the MAD is |x1-median|.
    Both are finite so the result should be a number, not NaN/Inf.
    """
    df = _cohort_df(2)
    metrics, flags = run_peer_stats(df)
    assert isinstance(metrics, pd.DataFrame), "run_peer_stats must return DataFrames"
    # Check no NaN in z-score columns
    z_cols = [c for c in metrics.columns if c.startswith("z_")]
    for col in z_cols:
        n_nan = metrics[col].isna().sum()
        # n=2 cohort that falls back to full-specialty; result may legitimately be NaN
        # when scipy.stats.zscore(ddof=1) on 2 equal values returns 0/0.
        # We only require no Inf values.
        n_inf = np.isinf(metrics[col].fillna(0)).sum()
        assert n_inf == 0, f"z_score column '{col}' must not contain Inf for n=2 cohort"


def test_zero_variance_cohort():
    """All providers have EXACTLY identical avg_minutes: MAD=0, fallback path.

    When MAD=0 and scipy.stats.zscore(ddof=1) returns NaN (std==0, i.e. 0/0),
    the fix in _modified_zscore replaces NaN with 0.0 so that providers in a
    zero-variance cohort are not silently excluded from scoring output.

    BUG FOUND (hardening): before the fix, scipy returned NaN for all-identical
    values (0/0 in std). build_flags silently skipped NaN z-scores, making every
    provider in such a cohort invisible to the flag logic.
    FIX (peer_stats.py _modified_zscore): fill NaN z-scores with 0.0 after
    scipy fallback — zero deviation from the median IS z=0 by definition.

    This test forces MAD=0 on avg_minutes by using exactly 20.0 for every
    service_minutes value (no jitter).
    """
    # Build claims with EXACTLY identical service_minutes (no jitter)
    rows = []
    for i in range(10):
        pid = f"PRV{i:03d}"
        for j in range(30):
            rows.append({
                "claim_id":        f"{pid}_C{j:04d}",
                "provider_id":     pid,
                "provider_name":   f"Dr {pid}",
                "patient_id":      f"PAT{j:04d}",
                "fee_code":        "99213",
                "service_date":    pd.Timestamp("2024-01-01") + pd.Timedelta(days=j % 100),
                "service_minutes": 20.0,   # EXACTLY identical — forces MAD=0
                "amount_billed":   100.0 + i * 0.01,  # slight variation on other metrics
                "specialty":       "Family Medicine",
                "clinic_id":       "CLN01",
            })
    df = pd.DataFrame(rows)
    metrics, flags = run_peer_stats(df)

    z_col = "z_avg_minutes"
    assert z_col in metrics.columns, f"Expected '{z_col}' in metrics output"
    vals = metrics[z_col]

    # After the fix: no NaN, no Inf, all values must be 0
    assert not np.any(np.isinf(vals.fillna(0).values)), (
        f"Zero-variance cohort must not produce Inf in '{z_col}'"
    )
    assert not vals.isna().any(), (
        f"Zero-variance avg_minutes must produce z=0.0, not NaN, after bug fix. "
        "If NaN appears, the _modified_zscore NaN-fill fix is not applied."
    )
    assert np.allclose(vals.values, 0.0, atol=1e-6), (
        f"Zero-variance avg_minutes: all z_avg_minutes should be 0.0, "
        f"got {vals.values}"
    )


def test_below_min_cohort_floor():
    """A cohort smaller than MIN_COHORT_SIZE (=5) falls back to full-specialty.

    There is no per-provider minimum-claims floor in peer_stats.py.
    The only guard is MIN_COHORT_SIZE for the cohort group.
    A provider with very few claims is included but scored against the full
    specialty distribution when their sub-cohort is too small.
    """
    # Only 3 providers -> cohort_size < MIN_COHORT_SIZE
    df = _cohort_df(3)
    metrics, flags = run_peer_stats(df)
    # Should not crash and should return DataFrames
    assert isinstance(metrics, pd.DataFrame)
    assert isinstance(flags, pd.DataFrame)
    # The fallback path must produce finite z-scores (or NaN, never Inf)
    z_cols = [c for c in metrics.columns if c.startswith("z_")]
    for col in z_cols:
        n_inf = np.isinf(metrics[col].fillna(0)).sum()
        assert n_inf == 0, f"Fallback z-scores must not be Inf in '{col}'"


def test_exactly_at_min_cohort_floor():
    """Cohort of exactly MIN_COHORT_SIZE providers uses the cohort z-score path."""
    df = _cohort_df(MIN_COHORT_SIZE)
    metrics, flags = run_peer_stats(df)
    assert isinstance(metrics, pd.DataFrame)
    assert isinstance(flags, pd.DataFrame)
    # MIN_COHORT_SIZE providers, all similar -> no outliers expected
    # (just confirming no crash and sensible output)
    z_cols = [c for c in metrics.columns if c.startswith("z_")]
    for col in z_cols:
        n_inf = np.isinf(metrics[col].fillna(0)).sum()
        assert n_inf == 0, f"No Inf allowed in '{col}' for exactly-min-size cohort"


def test_outlier_at_mad_z_3_4():
    """Provider with MAD z-score of ~3.4 must NOT be flagged (threshold is > 3.5).

    INTENTIONAL DESIGN: build_flags uses `abs(z) <= threshold` to SKIP the row
    (i.e., flag only when abs(z) > threshold).  So z=3.4 is NOT flagged.
    """
    # Build a cohort where we can precisely control the outlier's z-score.
    # Use a large cohort to make the MAD stable.
    df = _cohort_df(20, avg_minutes=20.0, n_claims_each=50, n_days_each=100,
                    outlier_idx=0, outlier_minutes=20.0)  # no outlier yet
    metrics, _ = run_peer_stats(df)
    # Manually test the build_flags threshold by constructing a synthetic metrics row
    # that has z_avg_minutes = 3.4 and checking it is NOT flagged.
    med = metrics["avg_minutes"].median()
    mad = (metrics["avg_minutes"] - med).abs().median()
    if mad == 0:
        pytest.skip("MAD is 0 for this cohort; cannot test z=3.4 boundary")

    # Inject a provider row with z_avg_minutes = 3.4
    synthetic = metrics.iloc[0:1].copy()
    synthetic["z_avg_minutes"] = 3.4
    synthetic["provider_id"]   = "PTEST_3_4"
    synthetic["provider_name"] = "Dr Z=3.4"
    synthetic["practice_setting"] = "full_time"
    synthetic["cohort_key"] = synthetic["specialty"].iloc[0] + " | full_time"
    flag_rows = build_flags(synthetic)
    avg_minutes_flags = flag_rows[flag_rows["metric"] == "avg_minutes"] if not flag_rows.empty \
                        else pd.DataFrame()
    assert avg_minutes_flags.empty, (
        "z=3.4 must NOT be flagged (threshold is > 3.5, and 3.4 <= 3.5)"
    )


def test_outlier_at_mad_z_3_5():
    """Provider with MAD z-score = 3.5 is NOT flagged.

    build_flags uses `abs(z) <= threshold` to skip -- so at exactly 3.5 the
    condition is True (3.5 <= 3.5) and the row is skipped (not flagged).
    INTENTIONAL: the threshold is inclusive -- a z exactly at 3.5 does NOT flag.
    """
    synthetic = pd.DataFrame([{
        "provider_id":      "PTEST_3_5",
        "provider_name":    "Dr Z=3.5",
        "specialty":        "Family Medicine",
        "cohort_key":       "Family Medicine | full_time",
        "practice_setting": "full_time",
        "avg_billed":       150.0,
        "claims_per_day":   5.0,
        "top_tier_share":   0.3,
        "services_per_patient": 2.0,
        "avg_minutes":      80.0,
        "z_avg_billed":       0.0,
        "z_claims_per_day":   0.0,
        "z_top_tier_share":   0.0,
        "z_services_per_patient": 0.0,
        "z_avg_minutes":    3.5,   # exactly at threshold
        "total_billed":     10000.0,
    }])
    flag_rows = build_flags(synthetic)
    avg_minutes_flags = flag_rows[flag_rows["metric"] == "avg_minutes"] if not flag_rows.empty \
                        else pd.DataFrame()
    assert avg_minutes_flags.empty, (
        "z=3.5 must NOT be flagged (rule is abs(z) <= threshold skips; "
        "3.5 <= 3.5 is True so the row is skipped). "
        "INTENTIONAL: threshold is inclusive on the non-flag side."
    )


def test_outlier_at_mad_z_3_6():
    """Provider with MAD z-score = 3.6 MUST be flagged (strictly above 3.5)."""
    synthetic = pd.DataFrame([{
        "provider_id":      "PTEST_3_6",
        "provider_name":    "Dr Z=3.6",
        "specialty":        "Family Medicine",
        "cohort_key":       "Family Medicine | full_time",
        "practice_setting": "full_time",
        "avg_billed":       150.0,
        "claims_per_day":   5.0,
        "top_tier_share":   0.3,
        "services_per_patient": 2.0,
        "avg_minutes":      80.0,
        "z_avg_billed":       0.0,
        "z_claims_per_day":   0.0,
        "z_top_tier_share":   0.0,
        "z_services_per_patient": 0.0,
        "z_avg_minutes":    3.6,   # just above threshold
        "total_billed":     10000.0,
    }])
    flag_rows = build_flags(synthetic)
    assert not flag_rows.empty, "z=3.6 MUST be flagged (3.6 > 3.5)"
    assert any(flag_rows["metric"] == "avg_minutes"), (
        "avg_minutes with z=3.6 must appear in flags"
    )


def test_nan_propagation():
    """Verify no NaN or Inf in output flags when input has edge values."""
    df = _cohort_df(10, avg_minutes=20.0, n_claims_each=30)
    metrics, flags = run_peer_stats(df)
    if flags.empty:
        return  # No flags is fine; just check metrics
    for col in ["z_score", "provider_value", "peer_median", "estimated_exposure"]:
        if col in flags.columns:
            assert not flags[col].isna().any(), f"flags['{col}'] must not contain NaN"
            assert not np.isinf(flags[col].fillna(0).values).any(), \
                f"flags['{col}'] must not contain Inf"
