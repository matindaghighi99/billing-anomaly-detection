"""bootstrap.py — guarantee demonstration data exists at runtime.

On a fresh deployment some generated files may be absent (e.g. claims_large.csv
is gitignored, or a build didn't run the pipeline). ensure_data() regenerates
whatever is missing, in-process, so the dashboard is never empty.

It is idempotent and cheap in the common case: the committed *_large aggregates
already ship, so usually only the raw claims file (needed for the per-physician
Monthly Volume chart) is regenerated. The heavy detection pipeline runs only if
the scored worklist itself is missing.
"""

import os

from dataset_config import CLAIMS_FILE, out, is_large


def _missing(name: str) -> bool:
    return not os.path.exists(out(name))


def _run_main_with_clean_argv(module_name: str):
    """Call a module's argparse main() with default args (Streamlit owns sys.argv)."""
    import importlib
    import sys
    saved = sys.argv
    sys.argv = [f"{module_name}.py"]
    try:
        mod = importlib.import_module(module_name)
        mod.main()
    except SystemExit:
        pass
    finally:
        sys.argv = saved


def ensure_data() -> dict:
    """Generate any missing pipeline outputs. Returns a small status dict."""
    status = {"claims": False, "pipeline": False, "moh": False}

    # 1. Raw claims (cheap; pandas-only). Needed for the Monthly Volume chart.
    if not os.path.exists(CLAIMS_FILE):
        if is_large():
            from data_gen_large import main as gen
        else:
            from data_gen import main as gen
        gen()
        status["claims"] = True

    # 2. Scored worklist + detection-layer outputs (heavier; only if absent).
    if _missing("risk_scores.csv"):
        import pandas as pd
        claims = pd.read_csv(CLAIMS_FILE, parse_dates=["service_date"],
                             dtype={"fee_code": str, "provider_id": str,
                                    "patient_id": str, "clinic_id": str})
        from rules import run_rules
        from peer_stats import run_peer_stats
        from codemix import run_codemix
        from temporal import run_temporal
        from anomaly_model import run_anomaly_model
        from scoring import build_risk_scores
        run_rules(claims)
        run_peer_stats(claims)
        run_codemix(claims)
        run_temporal(claims)
        run_anomaly_model(claims)
        build_risk_scores()
        try:
            from explain import build_explanations
            build_explanations()
        except Exception:
            pass  # SHAP/Anthropic optional — templates suffice
        status["pipeline"] = True

    # 3. MOH casebook artefacts (only meaningful on the large set).
    if is_large():
        if not os.path.exists("fraud_evidence.csv"):
            _run_main_with_clean_argv("fraud_evidence")
            status["moh"] = True
        if not os.path.exists("moh_recovery_summary.csv"):
            _run_main_with_clean_argv("moh_audit")
            status["moh"] = True

    return status
