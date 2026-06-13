"""validation.py — Accuracy validation against labelled outcomes.

Measures how well the flagged worklist matches *labelled* outcomes, and whether
recovery-dollar estimates track *actual* recovered amounts. Crucially, it stamps
the BASIS of the validation so a number measured on synthetic data is never
presented as production accuracy:

  basis = SYNTHETIC            ground_truth_large.json (the planted answer key)
        = AUDITOR_DISPOSITIONS dispositions.csv (auditor confirm/clear labels)
        = ADJUDICATED_OUTCOMES adjudicated_outcomes.csv (real GM/HSARB outcomes,
                               optionally with recovered_amount for calibration)

is_validated() is True only when labels are real adjudicated outcomes (or
VALIDATION_TRUSTED=1). Otherwise metrics are reported but flagged NOT VALIDATED.

Metrics: provider-level confusion matrix, precision / recall / F1 / specificity,
and (when actual recovered amounts exist) recovery-estimate calibration.

Outputs: VALIDATION_REPORT.md + validation_metrics.json.
"""

import json
import os

import pandas as pd

from dataset_config import out

try:
    import config
    OUTCOMES_CSV = config.VALIDATION_OUTCOMES_CSV
    TRUSTED = config.VALIDATION_TRUSTED
except Exception:
    OUTCOMES_CSV = os.environ.get("VALIDATION_OUTCOMES_CSV", "adjudicated_outcomes.csv")
    TRUSTED = os.environ.get("VALIDATION_TRUSTED", "").strip().lower() in ("1", "true", "yes")

DISPOSITIONS_CSV  = "dispositions.csv"
GROUND_TRUTH_JSON = "ground_truth_large.json"
RISK_THRESHOLD    = 10   # mirrors scoring MIN_SCORE_THRESHOLD / app RISK_THRESHOLD


# ── Label resolution (pick the most authoritative source available) ───────────

def resolve_labels() -> tuple[pd.DataFrame, str]:
    """Return (labels_df[provider_id, label, recovered_amount?], basis).

    label: 1 = confirmed concern, 0 = cleared. Source preference:
    adjudicated outcomes > auditor dispositions > synthetic ground truth.
    """
    # 1. Real adjudicated outcomes — the only production-grade label source.
    if os.path.exists(OUTCOMES_CSV):
        df = pd.read_csv(OUTCOMES_CSV, dtype={"provider_id": str})
        df["label"] = (df["outcome"].astype(str).str.lower() == "confirmed").astype(int)
        return df, "ADJUDICATED_OUTCOMES"

    # 2. Auditor dispositions — treated as real labels only when the operator
    #    asserts it (VALIDATION_TRUSTED). The bundled demo dispositions are
    #    seeded from the synthetic key and belong to the small demo set, so they
    #    are NOT used by default to validate the active (large) dataset.
    if TRUSTED and os.path.exists(DISPOSITIONS_CSV):
        df = pd.read_csv(DISPOSITIONS_CSV, dtype={"provider_id": str})
        df = df.drop_duplicates("provider_id", keep="last")
        df["label"] = (df["outcome"].astype(str).str.lower() == "confirmed").astype(int)
        return df[["provider_id", "label"]], "AUDITOR_DISPOSITIONS"

    # 3. Synthetic ground truth matching the active dataset (demo basis).
    if os.path.exists(GROUND_TRUTH_JSON):
        gt = json.load(open(GROUND_TRUTH_JSON))
        bad = set(gt.get("all_bad_actors", []))
        # universe from provider metrics (one row per provider)
        pm = out("provider_metrics.csv")
        if os.path.exists(pm):
            universe = pd.read_csv(pm, dtype={"provider_id": str})["provider_id"].tolist()
        else:
            universe = list(bad)
        rows = [{"provider_id": p, "label": int(p in bad)} for p in universe]
        return pd.DataFrame(rows), "SYNTHETIC"

    return pd.DataFrame(columns=["provider_id", "label"]), "NONE"


def is_validated(basis: str) -> bool:
    """Production-validated only on real adjudicated outcomes (or explicit trust)."""
    return basis == "ADJUDICATED_OUTCOMES" or TRUSTED


def flagged_providers() -> set:
    path = out("risk_scores.csv")
    if not os.path.exists(path):
        return set()
    df = pd.read_csv(path, dtype={"provider_id": str})
    if "risk_score" in df.columns:
        df = df[df["risk_score"] >= RISK_THRESHOLD]
    return set(df["provider_id"])


# ── Metrics ───────────────────────────────────────────────────────────────────

def compute_metrics(labels: pd.DataFrame, flagged: set) -> dict:
    tp = fp = fn = tn = 0
    for _, r in labels.iterrows():
        predicted = r["provider_id"] in flagged
        actual = bool(r["label"])
        if predicted and actual:    tp += 1
        elif predicted and not actual: fp += 1
        elif not predicted and actual: fn += 1
        else:                       tn += 1
    precision = tp / (tp + fp) if (tp + fp) else None
    recall    = tp / (tp + fn) if (tp + fn) else None
    spec      = tn / (tn + fp) if (tn + fp) else None
    f1 = (2 * precision * recall / (precision + recall)
          if precision and recall else None)
    return {
        "n_labelled": len(labels), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 3) if precision is not None else None,
        "recall": round(recall, 3) if recall is not None else None,
        "specificity": round(spec, 3) if spec is not None else None,
        "f1": round(f1, 3) if f1 is not None else None,
    }


def recovery_calibration(labels: pd.DataFrame) -> dict | None:
    """Compare estimated recoverable vs actual recovered (needs recovered_amount)."""
    if "recovered_amount" not in labels.columns:
        return None
    rec_path = "moh_recovery_summary.csv"
    if not os.path.exists(rec_path):
        return None
    est = pd.read_csv(rec_path, dtype={"provider_id": str})[
        ["provider_id", "statutory_recoverable"]]
    merged = labels.merge(est, on="provider_id", how="inner")
    merged = merged[merged["recovered_amount"].notna() & (merged["recovered_amount"] > 0)]
    if merged.empty:
        return None
    ratio = (merged["statutory_recoverable"] / merged["recovered_amount"]).mean()
    mae = (merged["statutory_recoverable"] - merged["recovered_amount"]).abs().mean()
    return {"n": int(len(merged)), "mean_estimate_to_actual_ratio": round(float(ratio), 3),
            "mae": round(float(mae), 2)}


# ── Report ─────────────────────────────────────────────────────────────────────

def build_report() -> tuple[str, dict]:
    labels, basis = resolve_labels()
    flagged = flagged_providers()
    validated = is_validated(basis)
    metrics = compute_metrics(labels, flagged) if not labels.empty else {}
    calib = recovery_calibration(labels) if not labels.empty else None

    result = {
        "basis": basis, "validated": validated,
        "n_flagged": len(flagged), "metrics": metrics, "recovery_calibration": calib,
    }

    L = ["# Detection Accuracy Validation\n"]
    if validated:
        L.append(f"> ✅ **VALIDATED** against **{basis}**.\n")
    else:
        L.append(f"> ⚠ **NOT VALIDATED FOR PRODUCTION.** Basis: **{basis}**. "
                 f"These metrics are measured on "
                 f"{'the synthetic answer key' if basis == 'SYNTHETIC' else 'auditor dispositions seeded from synthetic data'}, "
                 f"not real adjudicated outcomes. Provide `adjudicated_outcomes.csv` "
                 f"(provider_id, outcome[, recovered_amount]) and set "
                 f"`VALIDATION_TRUSTED=1` once accuracy has been confirmed.\n")
    if metrics:
        L.append("| Metric | Value |\n|---|---|")
        L.append(f"| Labelled providers | {metrics['n_labelled']} |")
        L.append(f"| Flagged (worklist) | {len(flagged)} |")
        L.append(f"| True positives | {metrics['tp']} |")
        L.append(f"| False positives | {metrics['fp']} |")
        L.append(f"| False negatives | {metrics['fn']} |")
        L.append(f"| True negatives | {metrics['tn']} |")
        L.append(f"| **Precision** | **{metrics['precision']}** |")
        L.append(f"| **Recall** | **{metrics['recall']}** |")
        L.append(f"| Specificity | {metrics['specificity']} |")
        L.append(f"| F1 | {metrics['f1']} |\n")
    if calib:
        L.append("## Recovery-estimate calibration\n")
        L.append(f"Across {calib['n']} cases with a recorded recovered amount, the "
                 f"estimate/actual ratio is **{calib['mean_estimate_to_actual_ratio']}** "
                 f"(MAE ${calib['mae']:,.0f}).\n")
    else:
        L.append("## Recovery-estimate calibration\n")
        L.append("_Not available — requires `recovered_amount` in adjudicated "
                 "outcomes. Until then, recovery figures are unvalidated estimates._\n")
    L.append("## Clinical / medical-necessity review\n")
    try:
        import clinical_review as cr
        s = cr.summary()
        L.append(f"- Concerns requiring s.18(8)(e) clinical review with an opinion "
                 f"recorded: **{s['reviewed']}**; opinions supporting necessity: "
                 f"{s['supports']}, not medically necessary: {s['not_necessary']}.")
    except Exception:
        L.append("- Clinical review loop available via `clinical_review.py`.")
    return "\n".join(L), result


def main():
    md, result = build_report()
    with open("VALIDATION_REPORT.md", "w", encoding="utf-8") as fh:
        fh.write(md)
    with open("validation_metrics.json", "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
    print("Detection Accuracy Validation")
    print("=" * 60)
    print(f"  Basis      : {result['basis']}  (validated={result['validated']})")
    m = result["metrics"]
    if m:
        print(f"  Precision  : {m['precision']}  Recall: {m['recall']}  F1: {m['f1']}")
        print(f"  TP/FP/FN/TN: {m['tp']}/{m['fp']}/{m['fn']}/{m['tn']}")
    if not result["validated"]:
        print("  ⚠ NOT validated against real adjudicated outcomes — see report.")
    print("  → VALIDATION_REPORT.md, validation_metrics.json")


if __name__ == "__main__":
    main()
