"""Phase 6 — Plain-English explanations for flagged providers.

Template-based by default; optionally calls the Anthropic API if
ANTHROPIC_API_KEY is set in the environment.

Outputs explanations.json (provider_id -> explanation text).
"""

import json
import os

import pandas as pd

RULES_CSV   = "rules_flags.csv"
PEER_CSV    = "peer_flags.csv"
ML_CSV      = "ml_scores.csv"
SCORES_CSV  = "risk_scores.csv"
CLAIMS_CSV  = "claims.csv"
OUTPUT_JSON = "explanations.json"

TOP_N = 20   # only explain the top-N ranked providers


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


def _explain_ml(provider_id: str, ml_df: pd.DataFrame) -> str:
    row = ml_df[ml_df["provider_id"] == provider_id]
    if row.empty or not row.iloc[0]["ml_is_anomaly"]:
        return ""
    score = row.iloc[0]["ml_score"]
    return (
        f"Machine-learning anomaly detection (Isolation Forest) scored this "
        f"provider {score:.0f}/100 — ranking in the top outliers across all "
        f"150 providers. The model identified an unusual combination of billing "
        f"features inconsistent with typical patterns in the dataset."
    )


def build_template_explanation(provider_id: str, provider_name: str,
                                specialty: str, risk_score: float,
                                rules_df, peer_df, ml_df) -> str:
    parts = [
        f"AUDIT SUMMARY — {provider_name} ({provider_id}) | "
        f"{specialty} | Risk Score: {risk_score:.0f}/100",
        "",
        "FINDINGS:",
    ]

    sections = [
        _explain_impossible_day(provider_id, rules_df),
        _explain_duplicate(provider_id, rules_df),
        _explain_unbundling(provider_id, rules_df),
        _explain_peer(provider_id, peer_df),
        _explain_ml(provider_id, ml_df),
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
    rules, peer, ml, scores, _ = load_all()

    use_api = use_api and bool(os.environ.get("ANTHROPIC_API_KEY"))

    expls = {}
    for _, row in scores.head(TOP_N).iterrows():
        pid   = row["provider_id"]
        name  = row["provider_name"]
        spec  = row["specialty"]
        score = row["risk_score"]

        text = build_template_explanation(pid, name, spec, score, rules, peer, ml)
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

    print("Phase 6 - Plain-English Explanations")
    print("=" * 60)
    print(f"  Explanation mode : {mode}")
    expls = build_explanations(use_api=use_api)
    print(f"  Providers explained : {len(expls)}")
    print(f"  Saved to            : {OUTPUT_JSON}")
    print()

    # Print first 3 explanations as a preview
    for i, (pid, data) in enumerate(expls.items()):
        if i >= 3:
            break
        print("-" * 60)
        print(data["explanation"])
        print()


if __name__ == "__main__":
    main()
