"""Phase 6 / Phase 8 -- Plain-English explanations for flagged providers.

Phase 6: Template-based by default; optionally calls the Anthropic API if
ANTHROPIC_API_KEY is set in the environment.

Phase 8 addition: SHAP TreeExplainer on IsolationForest identifies which
features drove each provider's anomaly score, adding feature-level
attribution to the audit summaries.

Outputs:
  explanations.json         -- provider_id -> full audit summary
  shap_values.csv           -- full SHAP matrix (provider x feature)
  shap_explanations.csv     -- provider_id, top_features, explanation
"""

import json
import os

import numpy as np
import pandas as pd

RULES_CSV   = "rules_flags.csv"
PEER_CSV    = "peer_flags.csv"
ML_CSV      = "ml_scores.csv"
SCORES_CSV  = "risk_scores.csv"
CLAIMS_CSV  = "claims.csv"
OUTPUT_JSON = "explanations.json"
OUTPUT_SHAP_CSV = "shap_values.csv"
OUTPUT_EXPL_CSV = "shap_explanations.csv"

TOP_N = 20   # only explain the top-N ranked providers

# Human-readable labels for common feature names
_FEATURE_LABELS = {
    "claims_per_day":       "unusually high daily claim volume",
    "avg_billed":           "above-peer average billed amount",
    "avg_minutes":          "above-peer average service duration",
    "top_tier_share":       "over-use of top-tier billing codes",
    "services_per_patient": "excessive services per patient",
    "billed_cv":            "high billing variability",
    "dup_rate":             "elevated duplicate claim rate",
    "max_daily_minutes":    "extreme single-day minutes billed",
    "code_entropy":         "unusual code diversity",
    "total_claims":         "high total claim count",
    "total_billed":         "high total amount billed",
}

def _feature_label(name: str) -> str:
    if name in _FEATURE_LABELS:
        return _FEATURE_LABELS[name]
    if name.startswith("pct_"):
        return f"over-use of code {name[4:]}"
    if name.startswith("spec_"):
        return f"specialty mix ({name[5:]})"
    return name.replace("_", " ")


def load_all():
    rules  = pd.read_csv(RULES_CSV,  dtype={"provider_id": str})
    peer   = pd.read_csv(PEER_CSV,   dtype={"provider_id": str}) if os.path.exists(PEER_CSV) else pd.DataFrame()
    ml     = pd.read_csv(ML_CSV,     dtype={"provider_id": str})
    scores = pd.read_csv(SCORES_CSV, dtype={"provider_id": str})
    claims = pd.read_csv(CLAIMS_CSV, parse_dates=["service_date"],
                         dtype={"fee_code": str, "provider_id": str,
                                "patient_id": str})
    return rules, peer, ml, scores, claims


# ── Template builders ─────────────────────────────────────────────────────────

def _explain_impossible_day(provider_id: str, rules_df: pd.DataFrame) -> str:
    rows = rules_df[(rules_df["provider_id"] == provider_id) &
                    (rules_df["rule"] == "impossible_day")]
    if rows.empty:
        return ""
    worst = rows.loc[rows["estimated_exposure"].idxmax()]
    n_days = len(rows)
    total_exp = rows["estimated_exposure"].sum()
    # Extract minutes and date from evidence string
    ev = worst["evidence"]
    return (
        f"Impossible billing volume: on {n_days} separate day(s) this provider's "
        f"total billed service-minutes exceeded 1,440 (24 hours). "
        f"Worst instance: {ev.rstrip('.')}. "
        f"Total dollar exposure across all impossible days: ${total_exp:,.2f}."
    )


def _explain_duplicate(provider_id: str, rules_df: pd.DataFrame) -> str:
    rows = rules_df[(rules_df["provider_id"] == provider_id) &
                    (rules_df["rule"] == "duplicate_billing")]
    if rows.empty:
        return ""
    total_exp = rows["estimated_exposure"].sum()
    ev = rows.iloc[0]["evidence"]
    return (
        f"Duplicate billing detected: {ev}. "
        f"Each duplicate represents a claim submitted more than once with "
        f"identical provider, patient, fee code, and service date. "
        f"Estimated excess billing: ${total_exp:,.2f}."
    )


def _explain_unbundling(provider_id: str, rules_df: pd.DataFrame) -> str:
    rows = rules_df[(rules_df["provider_id"] == provider_id) &
                    (rules_df["rule"] == "unbundling")]
    if rows.empty:
        return ""
    total_exp = rows["estimated_exposure"].sum()
    ev = rows.iloc[0]["evidence"]
    return (
        f"Potential unbundling: {ev}. "
        f"Billing component codes 93005 (ECG Tracing) and 93010 (ECG Interpretation) "
        f"separately, rather than using the bundle code 93000 (ECG Complete), "
        f"inflates reimbursement. Estimated overcharge: ${total_exp:,.2f}."
    )


def _explain_peer(provider_id: str, peer_df: pd.DataFrame) -> str:
    if peer_df.empty:
        return ""
    rows = peer_df[peer_df["provider_id"] == provider_id]
    if rows.empty:
        return ""
    parts = []
    for _, row in rows.sort_values("z_score", key=abs, ascending=False).head(3).iterrows():
        direction = "above" if row["z_score"] > 0 else "below"
        parts.append(
            f"{row['metric'].replace('_', ' ')} of {row['provider_value']:.2f} "
            f"is {abs(row['z_score']):.1f} standard deviations {direction} "
            f"the specialty median of {row['peer_median']:.2f}"
        )
    return "Peer comparison outliers: " + "; ".join(parts) + "."


def _explain_ml(provider_id: str, ml_df: pd.DataFrame,
                shap_expl: pd.DataFrame = None) -> str:
    row = ml_df[ml_df["provider_id"] == provider_id]
    if row.empty or not row.iloc[0]["ml_is_anomaly"]:
        return ""
    score = row.iloc[0]["ml_score"]
    base = (
        f"Machine-learning anomaly detection (ensemble: Isolation Forest + LOF + "
        f"OC-SVM) scored this provider {score:.0f}/100 -- placing them among the "
        f"top outliers across all providers."
    )
    if shap_expl is not None and not shap_expl.empty:
        srow = shap_expl[shap_expl["provider_id"] == provider_id]
        if not srow.empty:
            base += " " + srow.iloc[0]["explanation"]
    else:
        base += (
            " The model identified an unusual combination of billing features "
            "inconsistent with typical patterns in the dataset."
        )
    return base


# ── Phase 8: SHAP explanations ────────────────────────────────────────────────

def build_shap_explanations(df: pd.DataFrame = None) -> pd.DataFrame:
    """Fit IsolationForest + SHAP TreeExplainer; return explanations DataFrame.

    Returns empty DataFrame (with a warning) if shap is not installed.
    """
    try:
        import shap
    except ImportError:
        print("  shap not installed; run: pip install shap")
        return pd.DataFrame()

    from anomaly_model import build_feature_matrix, load_claims, SEED
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import RobustScaler

    if df is None:
        df = load_claims()

    features      = build_feature_matrix(df)
    provider_ids  = features.index.tolist()
    feature_names = features.columns.tolist()
    X = features.values.astype(float)

    scaler   = RobustScaler()
    X_scaled = scaler.fit_transform(X)

    iforest = IsolationForest(
        n_estimators=300, max_samples="auto",
        contamination=0.10, random_state=SEED, n_jobs=-1,
    )
    iforest.fit(X_scaled)

    explainer = shap.TreeExplainer(iforest)
    shap_vals = explainer.shap_values(X_scaled)   # shape: (n_providers, n_features)

    # Negate: IsolationForest SHAP values are negative-score contributions;
    # we want positive = drives toward anomaly classification.
    anomaly_shap = -shap_vals

    shap_df = pd.DataFrame(anomaly_shap, columns=feature_names)
    shap_df.insert(0, "provider_id", provider_ids)
    shap_df.to_csv(OUTPUT_SHAP_CSV, index=False)

    rows = []
    for i, pid in enumerate(provider_ids):
        contribs = pd.Series(anomaly_shap[i], index=feature_names)
        top3 = contribs.nlargest(3)
        top_features = "; ".join(top3.index.tolist())
        parts = [_feature_label(f) for f, v in top3.items() if v > 0.001]
        explanation = ("Flagged due to: " + ", ".join(parts) + ".") if parts \
                      else "No dominant single-feature driver."
        rows.append({
            "provider_id":   pid,
            "top_features":  top_features,
            "explanation":   explanation,
            "shap_top1_val": round(float(top3.iloc[0]), 4) if len(top3) > 0 else 0.0,
            "shap_top2_val": round(float(top3.iloc[1]), 4) if len(top3) > 1 else 0.0,
            "shap_top3_val": round(float(top3.iloc[2]), 4) if len(top3) > 2 else 0.0,
        })

    expl_df = pd.DataFrame(rows)
    expl_df.to_csv(OUTPUT_EXPL_CSV, index=False)
    return expl_df


def get_shap_explanation(provider_id: str) -> str:
    """Return the SHAP plain-English explanation for one provider, or ''."""
    if not os.path.exists(OUTPUT_EXPL_CSV):
        return ""
    expl = pd.read_csv(OUTPUT_EXPL_CSV, dtype={"provider_id": str})
    row  = expl[expl["provider_id"] == provider_id]
    return "" if row.empty else row.iloc[0]["explanation"]


def build_template_explanation(provider_id: str, provider_name: str,
                                specialty: str, risk_score: float,
                                rules_df, peer_df, ml_df,
                                shap_expl: pd.DataFrame = None) -> str:
    parts = [
        f"AUDIT SUMMARY -- {provider_name} ({provider_id}) | "
        f"{specialty} | Risk Score: {risk_score:.0f}/100",
        "",
        "FINDINGS:",
    ]

    sections = [
        _explain_impossible_day(provider_id, rules_df),
        _explain_duplicate(provider_id, rules_df),
        _explain_unbundling(provider_id, rules_df),
        _explain_peer(provider_id, peer_df),
        _explain_ml(provider_id, ml_df, shap_expl),
    ]
    for s in sections:
        if s:
            parts.append(f"  - {s}")

    if len(parts) == 3:
        parts.append("  No specific flags triggered; surfaced by combined scoring.")

    parts += [
        "",
        "NOTE: This is synthetic data. All findings are flagged for human "
        "auditor review only. No automated action should be taken.",
    ]
    return "\n".join(parts)


# ── Optional Anthropic API path ───────────────────────────────────────────────

def _call_anthropic(provider_id: str, provider_name: str, specialty: str,
                    template_text: str) -> str:
    """Try to enrich via Anthropic API; return template on any failure."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return template_text
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        system = (
            "You are an experienced healthcare billing compliance analyst writing "
            "summaries for human auditors. Write in clear, factual, professional prose. "
            "Do NOT speculate about intent or guilt. Stick strictly to the evidence provided."
        )
        prompt = (
            f"Below is a structured audit summary for a provider. "
            f"Rewrite it as two concise paragraphs: (1) what the data shows, "
            f"(2) what an auditor should look at first. "
            f"No headings, no bullet points.\n\n{template_text}"
        )
        msg = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=400,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        enriched = msg.content[0].text.strip()
        return enriched + "\n\n[Generated with Anthropic API]"
    except Exception:
        return template_text


# ── Entry point ───────────────────────────────────────────────────────────────

def build_explanations(use_api: bool = False) -> dict:
    rules, peer, ml, scores, claims = load_all()

    use_api = use_api and bool(os.environ.get("ANTHROPIC_API_KEY"))

    # Build SHAP explanations once (covers all providers)
    shap_expl = build_shap_explanations(claims)

    expls = {}
    for _, row in scores.head(TOP_N).iterrows():
        pid   = row["provider_id"]
        name  = row["provider_name"]
        spec  = row["specialty"]
        score = row["risk_score"]

        text = build_template_explanation(
            pid, name, spec, score, rules, peer, ml, shap_expl
        )
        if use_api:
            text = _call_anthropic(pid, name, spec, text)

        expls[pid] = {
            "provider_name":      name,
            "specialty":          spec,
            "risk_score":         score,
            "estimated_exposure": row["estimated_exposure"],
            "explanation":        text,
        }

    with open(OUTPUT_JSON, "w") as fh:
        json.dump(expls, fh, indent=2)
    return expls


def main():
    use_api = bool(os.environ.get("ANTHROPIC_API_KEY"))
    mode    = "Anthropic API" if use_api else "template (no API key)"

    print("Phase 6/8 - Plain-English Explanations + SHAP Feature Attribution")
    print("=" * 60)
    print(f"  Explanation mode : {mode}")
    expls = build_explanations(use_api=use_api)
    print(f"  Providers explained : {len(expls)}")
    print(f"  Saved to            : {OUTPUT_JSON}")

    if os.path.exists(OUTPUT_EXPL_CSV):
        shap_df = pd.read_csv(OUTPUT_EXPL_CSV, dtype={"provider_id": str})
        ml      = pd.read_csv(ML_CSV,          dtype={"provider_id": str})
        top_anom = (
            ml[ml["ml_is_anomaly"] == 1]
              .sort_values("ml_score", ascending=False)
              .head(10)
              .merge(shap_df, on="provider_id")
        )
        print()
        print("  SHAP top-feature drivers for ML-flagged providers:")
        print(f"  {'Provider':<12} {'ML Score':>8}  Top features")
        print("  " + "-" * 75)
        for _, row in top_anom.iterrows():
            feats = row["top_features"].replace(";", " |")[:55]
            print(f"  {row['provider_id']:<12} {row['ml_score']:>8.2f}  {feats}")

    print()
    # Print first 3 full explanations as a preview
    for i, (pid, data) in enumerate(expls.items()):
        if i >= 3:
            break
        print("-" * 60)
        print(data["explanation"])
        print()


if __name__ == "__main__":
    main()
