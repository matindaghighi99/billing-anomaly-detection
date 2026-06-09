"""tests/test_temporal_boundary.py
Edge and boundary tests for temporal.py

Covers:
  - MIN_ACTIVE_MONTHS = 3 boundary (< 3 skipped, >= 3 included)
  - CUSUM_THRESHOLD = 3.0 boundary (>= 3.0 flags)
  - SPIKE_MULTIPLIER = 3.5 boundary (>= 3.5 flags)
  - Flat, gradual-rise, sudden-spike scenarios
  - Degenerate inputs: 1 month, all-zeros
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pytest

from temporal import (
    build_temporal_scores,
    run_temporal,
    _cusum_max,
    CUSUM_THRESHOLD,
    SPIKE_MULTIPLIER,
    MIN_ACTIVE_MONTHS,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_monthly_claims(provider_id: str, monthly_counts: list,
                         start_month: str = "2024-01") -> pd.DataFrame:
    """Build a minimal claims DataFrame with the given monthly claim counts."""
    rows = []
    claim_n = 0
    for month_offset, count in enumerate(monthly_counts):
        month_start = pd.Timestamp(start_month) + pd.DateOffset(months=month_offset)
        for i in range(count):
            rows.append({
                "claim_id":      f"{provider_id}_C{claim_n:05d}",
                "provider_id":   provider_id,
                "provider_name": f"Dr {provider_id}",
                "specialty":     "Family Medicine",
                "service_date":  month_start + pd.Timedelta(days=i % 28),
                "amount_billed": 100.0,
                "fee_code":      "99213",
                "patient_id":    f"PAT{i:04d}",
                "clinic_id":     "CLN01",
            })
            claim_n += 1
    return pd.DataFrame(rows)


def _single_provider_scores(monthly_counts: list, pid: str = "PRV001") -> pd.DataFrame:
    df = _make_monthly_claims(pid, monthly_counts)
    return build_temporal_scores(df)


# ── MIN_ACTIVE_MONTHS boundary ────────────────────────────────────────────────

def test_min_active_months_2():
    """Provider with only 2 active months must be SKIPPED (below MIN_ACTIVE_MONTHS=3)."""
    scores = _single_provider_scores([10, 12], pid="PRV_2M")
    assert scores.empty, (
        "Provider with 2 active months must be excluded from temporal scores "
        f"(MIN_ACTIVE_MONTHS={MIN_ACTIVE_MONTHS})"
    )


def test_min_active_months_3():
    """Provider with exactly 3 active months must be INCLUDED."""
    scores = _single_provider_scores([10, 12, 11], pid="PRV_3M")
    assert not scores.empty, (
        f"Provider with exactly {MIN_ACTIVE_MONTHS} active months must be included"
    )
    assert "PRV_3M" in scores["provider_id"].values


# ── CUSUM flat and gradual scenarios ──────────────────────────────────────────

def test_cusum_no_change():
    """Perfectly flat monthly volume: CUSUM score should be 0."""
    scores = _single_provider_scores([10, 10, 10, 10, 10, 10], pid="PRV_FLAT")
    assert not scores.empty, "Flat provider must be included"
    row = scores[scores["provider_id"] == "PRV_FLAT"].iloc[0]
    assert row["cusum_score"] == pytest.approx(0.0, abs=1e-9), (
        "Flat monthly volume must produce CUSUM score of 0"
    )
    assert not row["cusum_flag"], "Flat volume must NOT trigger cusum_flag"


def test_cusum_gradual_rise():
    """Slow linear increase: should NOT trigger CUSUM (change accumulates slowly)."""
    # Monthly counts: 10, 11, 12, 13, 14, 15 -- each ~10% increase
    scores = _single_provider_scores([10, 11, 12, 13, 14, 15], pid="PRV_GRAD")
    assert not scores.empty
    row = scores[scores["provider_id"] == "PRV_GRAD"].iloc[0]
    assert not row["cusum_flag"], (
        "Slow linear growth should NOT trigger CUSUM flag "
        f"(threshold={CUSUM_THRESHOLD})"
    )


def test_cusum_sudden_spike():
    """Last month has 10x normal volume: must trigger CUSUM and/or spike flag."""
    # 5 normal months then one massive spike
    scores = _single_provider_scores([10, 10, 10, 10, 10, 100], pid="PRV_SPIKE")
    assert not scores.empty
    row = scores[scores["provider_id"] == "PRV_SPIKE"].iloc[0]
    assert row["temporal_flag"], (
        "10x spike in last month MUST trigger temporal_flag"
    )


def test_spike_exactly_at_threshold():
    """Spike ratio exactly = SPIKE_MULTIPLIER (3.5): must be flagged.

    INTENTIONAL DESIGN: temporal.py uses `>= SPIKE_MULTIPLIER` for spike_flag.
    So a ratio of exactly 3.5 IS flagged.
    """
    # median of [10,10,10,10] = 10; spike month = 35 => ratio = 35/10 = 3.5
    scores = _single_provider_scores([10, 10, 10, 10, 35], pid="PRV_EXACT_SPIKE")
    assert not scores.empty
    row = scores[scores["provider_id"] == "PRV_EXACT_SPIKE"].iloc[0]
    spike_ratio = row["spike_ratio"]
    assert spike_ratio == pytest.approx(SPIKE_MULTIPLIER, abs=0.01), (
        f"Expected spike_ratio ~ {SPIKE_MULTIPLIER}, got {spike_ratio}"
    )
    assert row["spike_flag"], (
        f"spike_ratio = {SPIKE_MULTIPLIER} MUST trigger spike_flag "
        f"(rule uses >= {SPIKE_MULTIPLIER})"
    )


def test_cusum_threshold_at_boundary():
    """Verify the CUSUM threshold boundary via the helper function directly.

    _cusum_max returns the max accumulated CUSUM.
    A series that produces exactly CUSUM_THRESHOLD should be flagged
    (temporal.py uses `cusum_score >= CUSUM_THRESHOLD`).
    """
    # We test the flag logic directly using known CUSUM values.
    # cusum_flag = cusum_score >= CUSUM_THRESHOLD
    assert CUSUM_THRESHOLD == 3.0, "This test assumes CUSUM_THRESHOLD=3.0"
    # A series of [3.0] gives _cusum_max = 3.0
    val = _cusum_max(np.array([3.0]))
    assert val == pytest.approx(3.0)
    # cusum_flag logic
    cusum_flag_at_threshold = (val >= CUSUM_THRESHOLD)
    assert cusum_flag_at_threshold, (
        "CUSUM score == CUSUM_THRESHOLD must trigger flag (rule uses >=)"
    )

    # Just below threshold
    val_below = _cusum_max(np.array([2.99]))
    assert val_below < CUSUM_THRESHOLD
    assert not (val_below >= CUSUM_THRESHOLD), "2.99 < 3.0 must NOT flag"


# ── Degenerate inputs ─────────────────────────────────────────────────────────

def test_single_month():
    """Only 1 month of data: must return empty/skipped, not crash."""
    scores = _single_provider_scores([20], pid="PRV_1M")
    assert scores.empty, (
        "Provider with only 1 month must be skipped (< MIN_ACTIVE_MONTHS)"
    )


def test_all_zeros():
    """All monthly claim counts are 0: no crash, no division by zero."""
    # 0-claim months can't be created with _make_monthly_claims (produces 0 rows
    # per month -> provider is excluded as having 0 data).
    # Instead test via build_temporal_scores with a DF that has actual claim rows
    # but in just 2 calendar months -- they'll be skipped by MIN_ACTIVE_MONTHS.
    # To test zero-volume arithmetic, test the _cusum_max helper directly.
    result = _cusum_max(np.array([0.0, 0.0, 0.0, 0.0, 0.0]))
    assert result == pytest.approx(0.0), "All-zero fractional changes must give CUSUM=0"
    assert not (result >= CUSUM_THRESHOLD), "All-zero series must not trigger CUSUM flag"

    # Also verify run_temporal on an empty DataFrame doesn't crash
    df = pd.DataFrame(columns=[
        "claim_id", "provider_id", "provider_name", "specialty",
        "service_date", "amount_billed", "fee_code", "patient_id",
    ])
    scores, flags = run_temporal(df)
    assert isinstance(scores, pd.DataFrame), "run_temporal must return DataFrame on empty input"
    assert scores.empty, "run_temporal on empty input must return empty scores"
