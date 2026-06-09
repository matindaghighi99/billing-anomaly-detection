"""tests/test_codemix_boundary.py
Edge and boundary tests for codemix.py

Covers:
  - Single-code provider (KL divergence behaviour)
  - Provider whose code mix is identical to cohort (KL=0, no flag)
  - Provider with completely different codes (max divergence, should flag)
  - Single-provider cohort (graceful return)

Key constants from codemix.py:
  KL_THRESHOLD     = 0.10   (strictly >, so KL == 0.10 is NOT flagged)
  COSINE_THRESHOLD = 0.15   (strictly >, so cosine == 0.15 is NOT flagged)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pytest

from codemix import build_codemix_scores, KL_THRESHOLD, COSINE_THRESHOLD, _kl_divergence, _cosine_distance


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_claims(provider_id: str, codes: list, n_each: int = 20,
                 specialty: str = "Cardiology") -> pd.DataFrame:
    """Build claims where each fee_code appears n_each times."""
    rows = []
    for i, code in enumerate(codes):
        for j in range(n_each):
            rows.append({
                "claim_id":       f"{provider_id}_{code}_{j}",
                "provider_id":    provider_id,
                "provider_name":  f"Dr {provider_id}",
                "specialty":      specialty,
                "fee_code":       code,
                "service_date":   pd.Timestamp("2024-01-01") + pd.Timedelta(days=j),
                "amount_billed":  100.0,
                "patient_id":     f"PAT{j:04d}",
                "clinic_id":      "CLN01",
            })
    return pd.DataFrame(rows)


def _make_metrics(provider_ids: list, specialty: str = "Cardiology",
                  n_claims: int = 40, billed_days: int = 100) -> pd.DataFrame:
    """Build a minimal provider_metrics DataFrame."""
    rows = []
    for pid in provider_ids:
        rows.append({
            "provider_id":       pid,
            "provider_name":     f"Dr {pid}",
            "specialty":         specialty,
            "cohort_key":        f"{specialty} | full_time",
            "practice_setting":  "full_time",
            "total_billed":      5000.0,
            "total_claims":      n_claims,
            "billed_days":       billed_days,
            "avg_billed":        125.0,
            "avg_minutes":       20.0,
            "unique_patients":   20,
            "unique_codes":      3,
            "claims_per_day":    n_claims / billed_days,
            "services_per_patient": 2.0,
            "top_tier_share":    0.2,
            "active_day_fraction": billed_days / 261,
        })
    return pd.DataFrame(rows)


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_single_code_provider():
    """Provider only bills one fee_code: KL divergence is computed, no crash."""
    pid = "PRV_SINGLE"
    df = _make_claims(pid, ["99213"], n_each=30)
    # Add a cohort peer with multiple codes so comparison is meaningful
    df2 = _make_claims("PRV_MULTI", ["99213", "99214", "99215"], n_each=10)
    all_df = pd.concat([df, df2], ignore_index=True)
    metrics = _make_metrics([pid, "PRV_MULTI"])

    scores = build_codemix_scores(all_df, metrics)
    assert isinstance(scores, pd.DataFrame), "build_codemix_scores must return DataFrame"
    assert pid in scores["provider_id"].values, "Single-code provider must appear in output"

    row = scores[scores["provider_id"] == pid].iloc[0]
    assert not np.isnan(row["kl_divergence"]), "KL divergence must not be NaN for single-code provider"
    assert not np.isinf(row["kl_divergence"]), "KL divergence must not be Inf for single-code provider"
    assert not np.isnan(row["cosine_distance"]), "Cosine distance must not be NaN for single-code provider"


def test_identical_to_cohort():
    """Provider's code mix is exactly the cohort median: KL=0, cosine=0, not flagged."""
    # Both providers use the same codes in the same proportions
    codes = ["93000", "99214", "99215"]
    n_each = 10
    pid1 = "PRV_MATCH1"
    pid2 = "PRV_MATCH2"
    df1 = _make_claims(pid1, codes, n_each=n_each)
    df2 = _make_claims(pid2, codes, n_each=n_each)
    all_df = pd.concat([df1, df2], ignore_index=True)
    metrics = _make_metrics([pid1, pid2])

    scores = build_codemix_scores(all_df, metrics)
    assert not scores.empty

    row = scores[scores["provider_id"] == pid1].iloc[0]
    # With identical distributions, KL should be near 0 and cosine near 0
    assert row["kl_divergence"] < KL_THRESHOLD, (
        f"Identical-to-cohort provider must have KL < {KL_THRESHOLD}, "
        f"got {row['kl_divergence']}"
    )
    assert not row["drift_flag"], (
        "Provider with identical code mix to cohort must NOT be flagged"
    )


def test_completely_different_from_cohort():
    """Provider uses codes the cohort never uses: maximum divergence, should flag."""
    # Cohort uses cardiology codes; provider uses completely different codes
    pid_cohort1 = "PRV_COH1"
    pid_cohort2 = "PRV_COH2"
    pid_outlier = "PRV_ODD"
    cohort_codes  = ["93000", "99214"]
    outlier_codes = ["27447", "43239"]  # surgery codes in cardiology cohort

    df_cohort1 = _make_claims(pid_cohort1, cohort_codes, n_each=20)
    df_cohort2 = _make_claims(pid_cohort2, cohort_codes, n_each=20)
    df_outlier  = _make_claims(pid_outlier, outlier_codes, n_each=20)
    all_df = pd.concat([df_cohort1, df_cohort2, df_outlier], ignore_index=True)
    metrics = _make_metrics([pid_cohort1, pid_cohort2, pid_outlier])

    scores = build_codemix_scores(all_df, metrics)
    row = scores[scores["provider_id"] == pid_outlier].iloc[0]
    assert row["kl_divergence"] > KL_THRESHOLD, (
        f"Completely different code mix must produce KL > {KL_THRESHOLD}, "
        f"got {row['kl_divergence']}"
    )
    assert row["drift_flag"], (
        "Provider using codes the cohort never uses MUST be flagged"
    )


def test_single_provider_cohort():
    """Only one provider in the specialty: no comparison possible, graceful return."""
    pid = "PRV_ONLY"
    df = _make_claims(pid, ["93000", "99214"], n_each=20)
    metrics = _make_metrics([pid])

    scores = build_codemix_scores(df, metrics)
    # Must not crash; result may be empty or contain the single provider
    assert isinstance(scores, pd.DataFrame), (
        "build_codemix_scores must return DataFrame for single-provider cohort"
    )
    if not scores.empty:
        row = scores[scores["provider_id"] == pid]
        assert not row.empty, "Single provider should appear in output"
        assert not np.isnan(row.iloc[0]["kl_divergence"]), (
            "KL divergence must not be NaN for single-provider cohort"
        )


def test_kl_divergence_helper_zero():
    """_kl_divergence of identical distributions must be near 0."""
    p = np.array([0.5, 0.3, 0.2])
    q = np.array([0.5, 0.3, 0.2])
    kl = _kl_divergence(p.copy(), q.copy())
    assert kl == pytest.approx(0.0, abs=1e-5), (
        f"KL of identical distributions must be ~0, got {kl}"
    )


def test_cosine_distance_helper_zero():
    """_cosine_distance of identical vectors must be 0."""
    p = np.array([0.5, 0.3, 0.2])
    q = np.array([0.5, 0.3, 0.2])
    cos = _cosine_distance(p, q)
    assert cos == pytest.approx(0.0, abs=1e-5), (
        f"Cosine distance of identical vectors must be 0, got {cos}"
    )


def test_cosine_distance_zero_vector():
    """_cosine_distance with a zero vector must return 1.0 (fully orthogonal)."""
    p = np.array([0.0, 0.0, 0.0])
    q = np.array([0.5, 0.3, 0.2])
    cos = _cosine_distance(p, q)
    assert cos == pytest.approx(1.0), (
        "Cosine distance of zero vector vs any vector must be 1.0"
    )
