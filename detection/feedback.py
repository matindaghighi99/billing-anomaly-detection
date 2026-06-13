"""Phase 7 -- Feedback loop + semi-supervised learning.

Provides a way for auditors to record dispositions (confirmed / cleared) and,
once enough labels accumulate, trains an XGBoost classifier that blends into
the risk score.

WORKFLOW:
  1. record_disposition(provider_id, outcome)
       outcome = "confirmed" | "cleared"
       Appends a row to dispositions.csv (created on first call).

  2. run_feedback_model()
       Reads dispositions.csv + provider_codemix.csv + ml_scores.csv +
       provider_metrics.csv to build a labelled feature set.
       If >= MIN_LABELS rows exist: trains XGBoost, outputs feedback_scores.csv.
       If too few: returns empty DataFrame + a message (falls back gracefully).

  3. feedback_component() in scoring.py (called from build_risk_scores())
       Loads feedback_scores.csv if present and adds up to FEEDBACK_MAX_PTS
       to each provider's risk score.

DEMO USAGE:
  # Simulate auditor confirming known bad actors and clearing known clean ones:
  python feedback.py --seed-demo

  # Re-run the full pipeline to see the score shift:
  python scoring.py && python validate.py
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd

from dataset_config import out

DISPOSITIONS_CSV  = out("dispositions.csv")
FEEDBACK_CSV      = out("feedback_scores.csv")
GROUND_TRUTH_JSON = "ground_truth.json"

METRICS_CSV       = out("provider_metrics.csv")
CODEMIX_CSV       = out("provider_codemix.csv")
ML_CSV            = out("ml_scores.csv")
TEMPORAL_CSV      = out("provider_temporal.csv")

MIN_LABELS        = 6    # minimum confirmed+cleared to attempt training
FEEDBACK_MAX_PTS  = 10   # maximum points this layer contributes to risk score


# ── Disposition recording ─────────────────────────────────────────────────────

def record_disposition(provider_id: str, outcome: str,
                       notes: str = "", source: str = "manual") -> None:
    """Append one auditor disposition to dispositions.csv.

    outcome must be 'confirmed' (fraud likely) or 'cleared' (no issue found).
    """
    valid = {"confirmed", "cleared"}
    if outcome not in valid:
        raise ValueError(f"outcome must be one of {valid}, got {outcome!r}")

    row = pd.DataFrame([{
        "provider_id": provider_id,
        "outcome":     outcome,
        "notes":       notes,
        "source":      source,
    }])
    # Atomic create/append: open(path, 'x') fails with FileExistsError if the
    # file already exists, eliminating the TOCTOU race between the exists()
    # check and the write that caused double-header corruption under concurrent
    # auditor clicks.
    try:
        fh = open(DISPOSITIONS_CSV, "x", newline="", encoding="utf-8")
        write_header = True
    except FileExistsError:
        fh = open(DISPOSITIONS_CSV, "a", newline="", encoding="utf-8")
        write_header = False
    with fh:
        row.to_csv(fh, header=write_header, index=False)


# ── Feature assembly ──────────────────────────────────────────────────────────

def _build_feature_df() -> pd.DataFrame:
    """Assemble a per-provider feature matrix from existing pipeline outputs."""
    parts = []

    if os.path.exists(METRICS_CSV):
        m = pd.read_csv(METRICS_CSV, dtype={"provider_id": str})
        feat_cols = ["claims_per_day", "avg_billed", "avg_minutes",
                     "top_tier_share", "services_per_patient"]
        parts.append(m[["provider_id"] + feat_cols].set_index("provider_id"))

    if os.path.exists(CODEMIX_CSV):
        c = pd.read_csv(CODEMIX_CSV, dtype={"provider_id": str})
        parts.append(c[["provider_id", "kl_divergence",
                         "cosine_distance"]].set_index("provider_id"))

    if os.path.exists(ML_CSV):
        ml = pd.read_csv(ML_CSV, dtype={"provider_id": str})
        parts.append(ml[["provider_id", "ml_score"]].set_index("provider_id"))

    if os.path.exists(TEMPORAL_CSV):
        t = pd.read_csv(TEMPORAL_CSV, dtype={"provider_id": str})
        parts.append(t[["provider_id", "cusum_score",
                         "spike_ratio"]].set_index("provider_id"))

    if not parts:
        return pd.DataFrame()

    df = parts[0]
    for p in parts[1:]:
        df = df.join(p, how="outer")
    df = df.fillna(0).reset_index()
    return df


# ── Model training ────────────────────────────────────────────────────────────

def run_feedback_model(verbose: bool = True) -> pd.DataFrame:
    """Train XGBoost on confirmed/cleared dispositions and score all providers.

    Returns a DataFrame with columns [provider_id, feedback_score, feedback_label]
    or an empty DataFrame if too few labels.
    """
    if not os.path.exists(DISPOSITIONS_CSV):
        if verbose:
            print("  No dispositions file found. Record some dispositions first.")
        return pd.DataFrame()

    disp = pd.read_csv(DISPOSITIONS_CSV, dtype={"provider_id": str})
    # Keep latest disposition per provider
    disp = disp.drop_duplicates("provider_id", keep="last")
    disp["label"] = (disp["outcome"] == "confirmed").astype(int)

    n_confirmed = (disp["outcome"] == "confirmed").sum()
    n_cleared   = (disp["outcome"] == "cleared").sum()

    if verbose:
        print(f"  Dispositions: {n_confirmed} confirmed, {n_cleared} cleared, "
              f"{len(disp)} total")

    if len(disp) < MIN_LABELS:
        if verbose:
            print(f"  Need >= {MIN_LABELS} labels to train; falling back to "
                  f"unsupervised scores.")
        return pd.DataFrame()

    features = _build_feature_df()
    if features.empty:
        return pd.DataFrame()

    # Use left join so disposed providers are never silently dropped due to a
    # missing entry in one feature CSV; missing features fill as 0.
    labelled = disp.merge(features, on="provider_id", how="left")
    feat_cols = [c for c in labelled.columns
                 if c not in ("provider_id", "outcome", "label", "notes", "source")]
    labelled[feat_cols] = labelled[feat_cols].fillna(0)

    X_train = labelled[feat_cols].values.astype(float)
    y_train = labelled["label"].values

    _using_xgb = False
    try:
        from xgboost import XGBClassifier
        _using_xgb = True
    except ImportError:
        pass

    if not _using_xgb:
        if verbose:
            print("  xgboost not installed; falling back to LogisticRegression.")
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        scaler  = StandardScaler()
        X_train = scaler.fit_transform(X_train)
        clf     = LogisticRegression(max_iter=1000, random_state=42)
        clf.fit(X_train, y_train)
        _hyperparams = {"model": "LogisticRegression", "max_iter": 1000,
                        "random_state": 42}
        X_all = features[feat_cols].values.astype(float)
        X_all = scaler.transform(X_all)
        probs = clf.predict_proba(X_all)[:, 1]
    else:
        from xgboost import XGBClassifier
        _hyperparams = {
            "model": "XGBClassifier", "n_estimators": 100, "max_depth": 3,
            "learning_rate": 0.1, "random_state": 42,
        }
        clf = XGBClassifier(
            n_estimators=100, max_depth=3, learning_rate=0.1,
            use_label_encoder=False, eval_metric="logloss",
            random_state=42, n_jobs=-1,
        )
        clf.fit(X_train, y_train)
        X_all = features[feat_cols].values.astype(float)
        probs = clf.predict_proba(X_all)[:, 1]

    # Register model version and log to audit trail
    try:
        import model_registry as _mr
        version_id = _mr.register_model(
            clf,
            X_train,
            y_train,
            hyperparameters=_hyperparams,
            n_confirmed=int(n_confirmed),
            n_cleared=int(n_cleared),
        )
        if verbose:
            print(f"  Model registered as version {version_id} in model_registry/")
        try:
            import audit_log as _al
            _al.append_event(
                "model_updated",
                model_version=version_id,
                reasoning=(
                    f"Feedback model retrained on {len(y_train)} labels "
                    f"({n_confirmed} confirmed, {n_cleared} cleared)"
                ),
            )
        except Exception:
            pass
    except Exception as exc:
        if verbose:
            print(f"  Warning: model_registry not available ({exc})")

    # Only add points above the 0.5 decision boundary.
    # prob < 0.5 (cleared/uncertain) → 0 pts; prob = 1.0 → FEEDBACK_MAX_PTS.
    # This prevents cleared providers from receiving inflated risk scores.
    above_boundary = np.clip((probs - 0.5) * 2, 0, 1)
    scores = pd.DataFrame({
        "provider_id":     features["provider_id"],
        "feedback_score":  (above_boundary * FEEDBACK_MAX_PTS).round(2),
        "feedback_prob":   probs.round(4),
        "feedback_label":  (probs >= 0.5).astype(int),
    })
    scores.to_csv(FEEDBACK_CSV, index=False)
    if verbose:
        print(f"  Feedback scores saved to {FEEDBACK_CSV}")
    return scores


# ── Demo seeder ───────────────────────────────────────────────────────────────

def _seed_demo() -> None:
    """Record dispositions from ground truth for demo purposes.

    Labels confirmed = bad actors, cleared = clean traps.
    Simulates what auditors would enter after reviewing the worklist.
    This is for DEMO ONLY -- real feedback comes from real auditors.
    """
    import json

    if not os.path.exists(GROUND_TRUTH_JSON):
        print(f"ERROR: {GROUND_TRUTH_JSON} not found. Run data_gen.py first.")
        sys.exit(1)

    with open(GROUND_TRUTH_JSON) as f:
        gt = json.load(f)

    bad_actors = gt["all_bad_actors"]
    clean      = list(gt.get("clean_providers", {}).keys())

    # Clear any existing dispositions
    if os.path.exists(DISPOSITIONS_CSV):
        os.remove(DISPOSITIONS_CSV)

    # Record confirmed for the first 8 bad actors (simulates partial review)
    for pid in bad_actors[:8]:
        record_disposition(pid, "confirmed", notes="Planted bad actor (demo)",
                           source="ground_truth_demo")

    # Record cleared for clean traps
    for pid in clean:
        record_disposition(pid, "cleared", notes="Clean trap provider (demo)",
                           source="ground_truth_demo")

    print(f"  Seeded {len(bad_actors[:8])} confirmed + {len(clean)} cleared "
          f"dispositions -> {DISPOSITIONS_CSV}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Feedback loop for billing anomaly demo")
    parser.add_argument("--seed-demo", action="store_true",
                        help="Seed demo dispositions from ground truth")
    parser.add_argument("--confirm", metavar="PROVIDER_ID",
                        help="Record a 'confirmed' disposition for a provider")
    parser.add_argument("--clear", metavar="PROVIDER_ID",
                        help="Record a 'cleared' disposition for a provider")
    parser.add_argument("--notes", default="", help="Notes for the disposition")
    args = parser.parse_args()

    print("Phase 7 - Feedback Loop / Semi-Supervised Learning")
    print("=" * 60)

    if args.seed_demo:
        _seed_demo()

    if args.confirm:
        record_disposition(args.confirm, "confirmed", notes=args.notes)
        print(f"  Recorded: {args.confirm} => confirmed")

    if args.clear:
        record_disposition(args.clear, "cleared", notes=args.notes)
        print(f"  Recorded: {args.clear} => cleared")

    scores = run_feedback_model(verbose=True)

    if not scores.empty:
        print(f"\n  Top 15 feedback scores:")
        print(f"  {'Provider':<12} {'Prob':>8}  {'Score':>8}  Label")
        print("  " + "-" * 40)
        for _, row in scores.nlargest(15, "feedback_score").iterrows():
            label = "confirmed" if row["feedback_label"] else "normal"
            print(f"  {row['provider_id']:<12} {row['feedback_prob']:>8.4f}  "
                  f"{row['feedback_score']:>8.2f}  {label}")


if __name__ == "__main__":
    main()
