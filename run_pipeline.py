"""Phase 10 -- Two-stage pipeline runner.

Full pipeline in the right order, with an optional --fast mode that implements
a two-stage funnel: run cheap stages first (rules + peer stats), then only
run the expensive ML ensemble on providers that clear a preliminary score
threshold.  Reduces ML runtime by ~60-70% on large datasets where most
providers are clearly clean.

STAGES (in order):
  1. data_gen.py          -- synthetic data (skip if claims.csv exists)
  2. rules.py             -- deterministic rule flags
  3. peer_stats.py        -- MAD z-score peer comparison
  4. codemix.py           -- KL/cosine code-mix drift
  5. temporal.py          -- CUSUM change-point detection
  6. anomaly_model.py     -- ensemble ML (IF + LOF + OC-SVM)
  7. feedback.py          -- semi-supervised feedback (if dispositions.csv exists)
  8. scoring.py           -- combined risk scoring
  9. explain.py           -- SHAP + plain-English explanations

USAGE:
  python run_pipeline.py            # full pipeline
  python run_pipeline.py --fast     # two-stage funnel (ML only on candidates)
  python run_pipeline.py --no-regen # skip data_gen if claims.csv exists
"""

import argparse
import os
import time

import pandas as pd

# Stage-1 preliminary score threshold: providers above this go to ML stage
STAGE1_THRESHOLD = 5   # pts from rules + peer alone


def _run_stage(label: str, fn, *args, **kwargs):
    t0  = time.perf_counter()
    res = fn(*args, **kwargs)
    elapsed = time.perf_counter() - t0
    print(f"  [{elapsed:5.2f}s]  {label}")
    return res


def main():
    parser = argparse.ArgumentParser(description="Two-stage pipeline runner")
    parser.add_argument("--fast",    action="store_true",
                        help="Two-stage funnel: ML only on stage-1 candidates")
    parser.add_argument("--no-regen", action="store_true",
                        help="Skip data_gen if claims.csv already exists")
    args = parser.parse_args()

    print("Pipeline Runner" + (" [FAST mode]" if args.fast else ""))
    print("=" * 60)
    total_t0 = time.perf_counter()

    # ── Stage 0: data generation ─────────────────────────────────────────────
    if args.no_regen and os.path.exists("claims.csv"):
        print("  [ skip ]  data_gen (claims.csv exists, --no-regen set)")
    else:
        from data_gen import main as dg_main
        _run_stage("data_gen", dg_main)

    # ── Load claims once; pass df to avoid re-reading ─────────────────────────
    claims = pd.read_csv("claims.csv", parse_dates=["service_date"],
                         dtype={"fee_code": str, "provider_id": str,
                                "patient_id": str, "clinic_id": str})

    # ── Stage 1: rules engine ─────────────────────────────────────────────────
    from rules import run_rules
    _run_stage("rules", run_rules, claims)

    # ── Stage 2: peer stats ───────────────────────────────────────────────────
    from peer_stats import run_peer_stats
    _run_stage("peer_stats", run_peer_stats, claims)

    # ── Stage 3: code-mix ─────────────────────────────────────────────────────
    from codemix import run_codemix
    _run_stage("codemix", run_codemix, claims)

    # ── Stage 4: temporal ─────────────────────────────────────────────────────
    from temporal import run_temporal
    _run_stage("temporal", run_temporal, claims)

    # ── Stage 5: ML ensemble (full or funnel) ─────────────────────────────────
    from anomaly_model import run_anomaly_model

    if args.fast:
        # Compute stage-1 preliminary scores to identify ML candidates
        rules_df = pd.read_csv("rules_flags.csv", dtype={"provider_id": str})
        peer_df  = pd.read_csv("peer_flags.csv",  dtype={"provider_id": str})

        rule_pts  = {"impossible_day": 40, "duplicate_billing": 35, "unbundling": 30}
        rules_pts = (
            rules_df.copy()
                    .assign(pts=rules_df["rule"].map(rule_pts).fillna(25))
                    .groupby("provider_id")["pts"].sum()
                    .clip(upper=50)
        )
        peer_pts = (
            peer_df.assign(pts=peer_df["z_score"].abs().apply(
                lambda z: min((z - 3.5) * 2 + 5, 10)
            ))
            .groupby("provider_id")["pts"].sum()
            .clip(upper=25)
        )
        stage1 = rules_pts.add(peer_pts, fill_value=0)
        candidates = stage1[stage1 >= STAGE1_THRESHOLD].index.tolist()

        n_all = claims["provider_id"].nunique()
        n_cand = len(candidates)
        print(f"  [ funnel]  {n_cand}/{n_all} providers pass stage-1 threshold "
              f"({STAGE1_THRESHOLD} pts) -> ML stage")
        _run_stage("anomaly_model (subset)", run_anomaly_model, claims, candidates)
    else:
        _run_stage("anomaly_model (full)", run_anomaly_model, claims)

    # ── Stage 6: feedback (optional) ─────────────────────────────────────────
    from feedback import run_feedback_model
    _run_stage("feedback", run_feedback_model, False)

    # ── Stage 7: combined scoring ─────────────────────────────────────────────
    from scoring import build_risk_scores
    _run_stage("scoring", build_risk_scores)

    # ── Stage 8: explanations ─────────────────────────────────────────────────
    from explain import build_explanations
    _run_stage("explain", build_explanations)

    total_elapsed = time.perf_counter() - total_t0
    print()
    print(f"  Total elapsed: {total_elapsed:.2f}s")
    print("  Output files: risk_scores.csv, explanations.json, shap_explanations.csv")


if __name__ == "__main__":
    main()
