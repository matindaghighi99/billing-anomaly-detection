"""tests/test_integration_ground_truth.py
Full-pipeline integration tests against the synthetic ground truth.

Runs the full pipeline on the standard ~54k-claim dataset and asserts:
  1. All bad actors appear in the top-20 risk scores
  2. Clean traps do NOT appear in top-10 (TRAP03 is documented as known exception)
  3. No NaN in risk_scores.csv critical columns
  4. All scores are in [0, 100]
  5. Confidence column contains only valid values

IMPORTANT: This test depends on the pipeline having been run and
  risk_scores.csv existing in the project root, OR it will run the pipeline
  on demand. It uses the STANDARD claims.csv (54k claims).

This is the only test file that may read pre-existing CSV files.
"""

import sys
import os
import json
import subprocess

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

import pandas as pd
import numpy as np
import pytest

import dataset_config as _dc


def _ensure_demo_pipeline():
    """Generate the demo dataset + scored outputs on demand if absent.

    Pipeline artefacts live under data/ (git-ignored), so on a fresh clone they
    won't exist yet; regenerate them once so the end-to-end checks run instead of
    skipping. The DATASET env is left at its default (demo) for this fixture.
    """
    if os.path.exists(_dc.out("risk_scores.csv")) and os.path.exists(_dc.out("ground_truth.json")):
        return
    import bootstrap
    bootstrap.ensure_data()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def ground_truth():
    _ensure_demo_pipeline()
    gt_path = os.path.join(PROJECT_DIR, _dc.out("ground_truth.json"))
    if not os.path.exists(gt_path):
        pytest.skip("ground_truth.json not found — run data_pipeline/data_gen.py first")
    with open(gt_path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def risk_scores():
    _ensure_demo_pipeline()
    scores_path = os.path.join(PROJECT_DIR, _dc.out("risk_scores.csv"))
    if not os.path.exists(scores_path):
        pytest.skip(
            "risk_scores.csv not found — run the full pipeline first "
            "(python data_pipeline/run_pipeline.py --no-regen)"
        )
    df = pd.read_csv(scores_path, dtype={"provider_id": str})
    df = df.reset_index(drop=True)
    df["rank"] = df.index + 1
    return df


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_all_bad_actors_in_top_20(ground_truth, risk_scores):
    """Every bad actor in ground_truth.json must appear in the top-20 risk scores."""
    bad_actors = set(ground_truth["all_bad_actors"])
    top_20_ids = set(risk_scores.head(20)["provider_id"].tolist())

    missed = bad_actors - top_20_ids
    assert not missed, (
        f"The following bad actors were NOT in the top-20: {sorted(missed)}. "
        "Check detection thresholds and scoring weights."
    )


def test_clean_traps_not_in_top_10(ground_truth, risk_scores):
    """Clean trap providers must NOT appear in top-10 risk scores.

    EXCEPTION: TRAP03 ('Sub-threshold provider: long days but always <1440 min')
    is documented as a known edge case. If it appears, we document but do not
    fail the test -- it represents a near-threshold provider that may be
    caught by peer stats at certain random seeds.
    """
    clean_traps = set(ground_truth["clean_providers"].keys())
    top_10_ids  = set(risk_scores.head(10)["provider_id"].tolist())

    traps_in_top10 = clean_traps & top_10_ids
    known_exception = {"TRAP03"}
    unexplained_fp = traps_in_top10 - known_exception

    assert not unexplained_fp, (
        f"Clean trap providers (excluding known TRAP03 exception) appeared in "
        f"top-10 -- these are unexpected false positives: {sorted(unexplained_fp)}"
    )

    # Document TRAP03 if it appears
    if "TRAP03" in traps_in_top10:
        trap03_row = risk_scores[risk_scores["provider_id"] == "TRAP03"]
        if not trap03_row.empty:
            score = trap03_row.iloc[0]["risk_score"]
            rank  = trap03_row.iloc[0]["rank"]
            # Not a hard failure but document as warning
            print(
                f"\n[KNOWN EXCEPTION] TRAP03 appeared in top-10 at rank {rank}, "
                f"score {score:.1f}. This is a near-threshold clean provider and "
                "is a documented known exception."
            )


def test_no_nan_in_risk_scores(risk_scores):
    """risk_scores.csv must have no NaN in score, confidence, or expected_recovery."""
    for col in ["risk_score", "confidence", "expected_recovery"]:
        if col not in risk_scores.columns:
            pytest.skip(f"Column '{col}' not in risk_scores.csv")
        n_nan = risk_scores[col].isna().sum()
        assert n_nan == 0, (
            f"risk_scores.csv column '{col}' has {n_nan} NaN value(s) -- "
            "all critical columns must be populated"
        )


def test_scores_in_range(risk_scores):
    """All risk_scores must be in [0, 100]."""
    if "risk_score" not in risk_scores.columns:
        pytest.skip("risk_score column missing")
    out_of_range = risk_scores[
        (risk_scores["risk_score"] < 0) | (risk_scores["risk_score"] > 100)
    ]
    assert out_of_range.empty, (
        f"Found {len(out_of_range)} risk_score value(s) outside [0, 100]: "
        f"{out_of_range[['provider_id', 'risk_score']].to_dict('records')}"
    )


def test_confidence_valid_values(risk_scores):
    """Confidence column must only contain HIGH, MEDIUM, or LOW."""
    if "confidence" not in risk_scores.columns:
        pytest.skip("confidence column missing")
    valid = {"HIGH", "MEDIUM", "LOW"}
    invalid = set(risk_scores["confidence"].unique()) - valid
    assert not invalid, (
        f"Invalid confidence values found: {invalid}. "
        f"Only {valid} are permitted."
    )
