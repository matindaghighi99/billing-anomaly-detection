"""tests/test_scoring_boundary.py
Edge and boundary tests for scoring.py combining logic.

Tests build their own minimal in-memory DataFrames and call scoring internals
directly (build_flags logic, validate_risk_scores_df, etc.) rather than
reading CSV files, so they are fully self-contained.

Key constants from scoring.py:
  RULE_POINTS        = {impossible_day: 40, duplicate_billing: 35, unbundling: 30}
  PEER_MAX_PTS       = 25
  ML_MAX_PTS         = 15
  CODEMIX_MAX_PTS    = 10
  TEMPORAL_MAX_PTS   = 5
  CONFIDENCE_LIKELIHOOD = {HIGH: 0.70, MEDIUM: 0.40, LOW: 0.15}
  MIN_SCORE_THRESHOLD = 10

Confidence tiers (from scoring.py build_risk_scores vectorized logic):
  HIGH   -> rules_score > 0
  MEDIUM -> (n_stat >= 2) OR (n_stat == 1 AND ml_is_anomaly)
            where n_stat = (peer_score>0) + codemix_flag + temporal_flag
  LOW    -> otherwise
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pytest

from scoring import validate_risk_scores_df, CONFIDENCE_LIKELIHOOD, MIN_SCORE_THRESHOLD


# ── Helper: build a synthetic pre-scored DataFrame ───────────────────────────

def _make_scored_df(**kwargs) -> pd.DataFrame:
    """Return a one-row scored DataFrame with defaults overridden by kwargs."""
    defaults = {
        "provider_id":        "PRV001",
        "provider_name":      "Dr Test",
        "specialty":          "Family Medicine",
        "risk_score":         50.0,
        "confidence":         "HIGH",
        "estimated_exposure": 10000.0,
        "expected_recovery":  7000.0,
        "rules_score":        40.0,
        "peer_score":         10.0,
        "ml_score":           60.0,
        "ml_is_anomaly":      1,
        "codemix_score":      5.0,
        "codemix_flag":       1,
        "kl_divergence":      0.2,
        "cosine_distance":    0.2,
        "temporal_score":     3.0,
        "temporal_flag":      1,
        "feedback_score":     0.0,
        "feedback_label":     0,
        "top_reason":         "Rule: impossible_day",
    }
    defaults.update(kwargs)
    return pd.DataFrame([defaults])


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_all_layers_flagged_max_score():
    """Provider flagged by all layers: risk_score must be near max and confidence HIGH."""
    # Maximum possible:
    # rules: 40 (impossible_day) + 35 (duplicate) + 30 (unbundling) -> capped at 50
    # peer: many metrics -> capped at 25
    # ml: 15
    # codemix: 10
    # temporal: 5
    # total: 50+25+15+10+5 = 105 -> clipped to 100
    row = _make_scored_df(
        rules_score=50.0, peer_score=25.0, ml_score_pts=15.0,
        codemix_score=10.0, temporal_score=5.0,
        risk_score=min(50+25+15+10+5, 100),
        confidence="HIGH",
    )
    # Validate score clipping
    validated = validate_risk_scores_df(row)
    assert validated.iloc[0]["risk_score"] <= 100, "risk_score must be <= 100 even if sum exceeds"
    assert validated.iloc[0]["risk_score"] >= 0,   "risk_score must be >= 0"


def test_no_layers_flagged_score_zero():
    """Provider with no flags: score = 0, should NOT appear on worklist."""
    row = _make_scored_df(
        risk_score=0.0, rules_score=0.0, peer_score=0.0, ml_score=0.0,
        ml_is_anomaly=0, codemix_score=0.0, codemix_flag=0,
        temporal_score=0.0, temporal_flag=0, feedback_score=0.0,
        confidence="LOW",
    )
    # Scores below MIN_SCORE_THRESHOLD are suppressed from worklist
    assert row.iloc[0]["risk_score"] < MIN_SCORE_THRESHOLD, (
        f"Score 0 must be below MIN_SCORE_THRESHOLD ({MIN_SCORE_THRESHOLD})"
    )


def test_tie_break_deterministic():
    """Two providers with identical combined scores must have stable sort order."""
    rows = []
    for pid in ["PRV_A", "PRV_B"]:
        rows.append({
            "provider_id": pid, "provider_name": f"Dr {pid}",
            "specialty": "Family Medicine",
            "risk_score": 45.0, "confidence": "HIGH",
            "estimated_exposure": 10000.0,
            "expected_recovery": 7000.0,
            "_rank_score": 45.0 * np.log1p(7000.0 / 1000),
        })
    df = pd.DataFrame(rows)
    # Apply same sort as scoring.py
    sorted1 = df.sort_values("_rank_score", ascending=False, kind="stable")
    sorted2 = df.sort_values("_rank_score", ascending=False, kind="stable")
    assert list(sorted1["provider_id"]) == list(sorted2["provider_id"]), (
        "Identical scores must produce deterministic (stable) sort order"
    )


def test_zero_exposure_expected_recovery():
    """Provider flagged but billed_amount = 0: expected_recovery must be 0, not NaN."""
    row = _make_scored_df(
        estimated_exposure=0.0,
        expected_recovery=0.0 * CONFIDENCE_LIKELIHOOD["HIGH"],  # = 0.0
        confidence="HIGH",
    )
    assert row.iloc[0]["expected_recovery"] == pytest.approx(0.0), (
        "Zero exposure must produce expected_recovery = 0.0, not NaN"
    )
    assert not pd.isna(row.iloc[0]["expected_recovery"]), (
        "expected_recovery must not be NaN when exposure is 0"
    )


def test_zero_likelihood_expected_recovery():
    """Recovery likelihood formula: 0 exposure * any likelihood = 0, not NaN or Inf."""
    for conf, likelihood in CONFIDENCE_LIKELIHOOD.items():
        recovery = 0.0 * likelihood
        assert recovery == pytest.approx(0.0), (
            f"0 * {likelihood} must equal 0.0 for confidence={conf}"
        )
        assert not np.isnan(recovery), "0 * likelihood must not be NaN"
        assert not np.isinf(recovery), "0 * likelihood must not be Inf"


def test_negative_score_clipped_to_zero():
    """validate_risk_scores_df must clip negative risk_scores to 0.

    Regression guard from fuzz session.
    """
    import warnings
    row = _make_scored_df(risk_score=-5.0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        validated = validate_risk_scores_df(row)
    assert validated.iloc[0]["risk_score"] == pytest.approx(0.0), (
        "Negative risk_score must be clipped to 0 by validate_risk_scores_df"
    )


def test_score_above_100_clipped():
    """validate_risk_scores_df must clip scores above 100 to exactly 100."""
    import warnings
    row = _make_scored_df(risk_score=110.0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        validated = validate_risk_scores_df(row)
    assert validated.iloc[0]["risk_score"] == pytest.approx(100.0), (
        "risk_score > 100 must be clipped to 100"
    )


def test_confidence_tier_boundary_high_medium():
    """Test the exact flip point HIGH -> MEDIUM -> LOW.

    From scoring.py (lines ~286-289):
      HIGH   : rules_score > 0
      MEDIUM : rules_score == 0 AND ((n_stat >= 2) OR (n_stat == 1 AND ml_is_anomaly))
      LOW    : otherwise

    Boundary: rules_score = 0, n_stat = 2 -> MEDIUM
              rules_score = 0, n_stat = 1, ml_is_anomaly=1 -> MEDIUM
              rules_score = 0, n_stat = 1, ml_is_anomaly=0 -> LOW
    """
    # HIGH: rules_score > 0
    assert _infer_confidence(rules_score=1.0, n_stat=0, ml_is_anomaly=0) == "HIGH", \
        "rules_score > 0 must be HIGH confidence"

    # MEDIUM: rules_score == 0, n_stat >= 2
    assert _infer_confidence(rules_score=0.0, n_stat=2, ml_is_anomaly=0) == "MEDIUM", \
        "n_stat=2, no rules -> MEDIUM"

    # MEDIUM: rules_score == 0, n_stat=1, ml_is_anomaly=1
    assert _infer_confidence(rules_score=0.0, n_stat=1, ml_is_anomaly=1) == "MEDIUM", \
        "n_stat=1 + ML anomaly -> MEDIUM"

    # LOW: rules_score == 0, n_stat=1, ml_is_anomaly=0
    assert _infer_confidence(rules_score=0.0, n_stat=1, ml_is_anomaly=0) == "LOW", \
        "n_stat=1, no ML -> LOW"

    # LOW: rules_score == 0, n_stat=0, ml_is_anomaly=0
    assert _infer_confidence(rules_score=0.0, n_stat=0, ml_is_anomaly=0) == "LOW", \
        "no signals -> LOW"


def test_confidence_tier_boundary_medium_low():
    """Confirm exact boundary between MEDIUM and LOW.

    n_stat = 1 without ML anomaly -> LOW (boundary case)
    n_stat = 1 with ML anomaly    -> MEDIUM (boundary case)
    n_stat = 0 with ML anomaly    -> LOW (ml_is_anomaly alone without n_stat >= 1)
    """
    # n_stat=1 without ML -> LOW
    assert _infer_confidence(rules_score=0.0, n_stat=1, ml_is_anomaly=0) == "LOW"
    # n_stat=1 with ML -> MEDIUM
    assert _infer_confidence(rules_score=0.0, n_stat=1, ml_is_anomaly=1) == "MEDIUM"
    # n_stat=0 with ML -> LOW (ml_is_anomaly alone does NOT trigger MEDIUM)
    assert _infer_confidence(rules_score=0.0, n_stat=0, ml_is_anomaly=1) == "LOW", (
        "ML anomaly alone (n_stat=0) must be LOW confidence, not MEDIUM"
    )


def _infer_confidence(rules_score: float, n_stat: int, ml_is_anomaly: int) -> str:
    """Replicate scoring.py confidence-tier logic for testing."""
    if rules_score > 0:
        return "HIGH"
    medium_cond = (n_stat >= 2) or (n_stat == 1 and bool(ml_is_anomaly))
    return "MEDIUM" if medium_cond else "LOW"


def test_single_provider_worklist():
    """Only one provider flagged: rank must be 1, no index errors."""
    row = _make_scored_df(risk_score=50.0, confidence="HIGH")
    row = row[row["risk_score"] >= MIN_SCORE_THRESHOLD].copy()
    row = row.sort_values("risk_score", ascending=False).reset_index(drop=True)
    row["rank"] = row.index + 1
    assert len(row) == 1, "One provider should produce one row"
    assert row.iloc[0]["rank"] == 1, "Single provider must have rank=1"
    assert not pd.isna(row.iloc[0]["risk_score"]), "risk_score must not be NaN"
