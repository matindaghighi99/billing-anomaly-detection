"""Phase 5 — Multi-layer risk scoring.

Combines three evidence layers into a single 0-100 risk score per provider,
then weights the ranking by estimated dollar exposure so the highest-priority
audit targets appear first.

Weights (pre-normalisation):
  Rules layer  : 0-50 pts  (highest confidence — binary violations)
  Peer stats   : 0-30 pts  (statistical outliers within specialty)
  ML anomaly   : 0-20 pts  (unsupervised; catches novel patterns)

Outputs risk_scores.csv.
"""

import numpy as np
import pandas as pd

RULES_CSV   = "rules_flags.csv"
PEER_CSV    = "peer_flags.csv"
ML_CSV      = "ml_scores.csv"
CLAIMS_CSV  = "claims.csv"
OUTPUT_CSV  = "risk_scores.csv"

# Points per rule type
RULE_POINTS = {
    "impossible_day":   40,
    "duplicate_billing":35,
    "unbundling":       30,
}

PEER_MAX_PTS = 30   # cap for peer-stats contribution
ML_MAX_PTS   = 20   # cap for ML contribution


def load_claims_meta(path=CLAIMS_CSV) -> pd.DataFrame:
    """Return per-provider total-billed (used as fallback exposure estimate)."""
    df = pd.read_csv(path, parse_dates=["service_date"],
                     dtype={"fee_code": str, "provider_id": str,
                            "patient_id": str})
    return (
        df.groupby(["provider_id", "provider_name", "specialty"])
          .agg(total_billed=("amount_billed", "sum"))
          .reset_index()
    )


def rules_component() -> pd.DataFrame:
    """0-50 pts; also aggregates dollar exposure from rule violations."""
    rdf = pd.read_csv(RULES_CSV,
                      dtype={"provider_id": str})
    if rdf.empty:
        return pd.DataFrame(columns=["provider_id","rules_score","rules_exposure","rules_reasons"])

    pts = rdf["rule"].map(RULE_POINTS).fillna(25)
    rdf["rule_pts"] = pts

    agg = (
        rdf.groupby("provider_id")
           .agg(
               rules_score  =("rule_pts",           "sum"),
               rules_exposure=("estimated_exposure", "sum"),
               rules_reasons =("rule",               lambda x: "; ".join(sorted(set(x)))),
           )
           .reset_index()
    )
    # Cap at 50
    agg["rules_score"] = agg["rules_score"].clip(upper=50)
    return agg


def peer_component() -> pd.DataFrame:
    """0-30 pts based on how many metrics breach |z|>3 and by how much."""
    pdf = pd.read_csv(PEER_CSV,
                      dtype={"provider_id": str})
    if pdf.empty:
        return pd.DataFrame(columns=["provider_id","peer_score","peer_exposure","peer_reasons"])

    pdf["metric_pts"] = pdf["z_score"].abs().apply(lambda z: min((z - 3) * 2 + 5, 10))

    agg = (
        pdf.groupby("provider_id")
           .agg(
               peer_score  =("metric_pts",          "sum"),
               peer_exposure=("estimated_exposure",  "first"),
               peer_reasons =("metric",              lambda x: "; ".join(sorted(set(x)))),
           )
           .reset_index()
    )
    agg["peer_score"] = agg["peer_score"].clip(upper=PEER_MAX_PTS)
    return agg


def ml_component() -> pd.DataFrame:
    """0-20 pts from IsolationForest normalised score."""
    mdf = pd.read_csv(ML_CSV, dtype={"provider_id": str})
    mdf["ml_score_pts"] = (mdf["ml_score"] / 100 * ML_MAX_PTS).round(2)
    return mdf[["provider_id","ml_score","ml_score_pts","ml_is_anomaly"]]


def build_risk_scores() -> pd.DataFrame:
    meta   = load_claims_meta()
    rules  = rules_component()
    peer   = peer_component()
    ml     = ml_component()

    df = meta.merge(rules, on="provider_id", how="left")
    df = df.merge(peer,   on="provider_id", how="left")
    df = df.merge(ml,     on="provider_id", how="left")

    df["rules_score"]   = df["rules_score"].fillna(0)
    df["peer_score"]    = df["peer_score"].fillna(0)
    df["ml_score_pts"]  = df["ml_score_pts"].fillna(0)
    df["ml_score"]      = df["ml_score"].fillna(0)
    df["ml_is_anomaly"] = df["ml_is_anomaly"].fillna(0).astype(int)

    # Combined 0-100 risk score
    df["risk_score"] = (df["rules_score"] + df["peer_score"] + df["ml_score_pts"]).clip(upper=100).round(1)

    # Estimated exposure: rules exposure where available, else fraction of total billed
    df["estimated_exposure"] = (
        df["rules_exposure"]
          .fillna(df["peer_exposure"])
          .fillna(df["total_billed"] * 0.10)   # 10% heuristic for ML-only hits
    )

    # Dollar-weighted rank score (used only for ordering)
    df["_rank_score"] = df["risk_score"] * np.log1p(df["estimated_exposure"] / 1_000)

    # Top reason
    def top_reason(row):
        reasons = []
        if pd.notna(row.get("rules_reasons")) and row["rules_reasons"]:
            reasons.append(f"Rule: {row['rules_reasons']}")
        if pd.notna(row.get("peer_reasons")) and row["peer_reasons"]:
            reasons.append(f"Peer z>3: {row['peer_reasons']}")
        if row["ml_is_anomaly"]:
            reasons.append(f"ML anomaly score {row['ml_score']:.0f}/100")
        return " | ".join(reasons) if reasons else "no flags"

    df["top_reason"] = df.apply(top_reason, axis=1)

    # Only keep providers with any signal
    flagged = df[df["risk_score"] > 0].copy()
    flagged = flagged.sort_values("_rank_score", ascending=False)

    out_cols = [
        "provider_id","provider_name","specialty",
        "risk_score","estimated_exposure",
        "rules_score","peer_score","ml_score",
        "ml_is_anomaly","top_reason",
    ]
    result = flagged[out_cols].reset_index(drop=True)
    result.to_csv(OUTPUT_CSV, index=False)
    return result


def main():
    print("Phase 5 - Combined Risk Scoring")
    print("=" * 60)
    scored = build_risk_scores()

    total_exposure = scored["estimated_exposure"].sum()
    n_flagged      = len(scored)

    print(f"  Providers flagged  : {n_flagged}")
    print(f"  Total est. exposure: ${total_exposure:,.2f}")
    print()
    print(f"  {'Rank':<5} {'Provider':<12} {'Specialty':<18} {'Score':>6}  "
          f"{'Exposure':>12}  Top Reason")
    print("  " + "-" * 100)
    for rank, (_, row) in enumerate(scored.head(20).iterrows(), 1):
        reason = row["top_reason"]
        reason = (reason[:55] + "...") if len(reason) > 55 else reason
        print(f"  {rank:<5} {row['provider_id']:<12} {row['specialty']:<18} "
              f"{row['risk_score']:>6.1f}  ${row['estimated_exposure']:>10,.2f}  {reason}")

    print(f"\n  Full table saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
