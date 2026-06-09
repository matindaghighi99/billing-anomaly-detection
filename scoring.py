"""Phase 5 -- Multi-layer risk scoring.

Combines four evidence layers into a single 0-100 risk score per provider,
then weights the ranking by estimated dollar exposure so the highest-priority
audit targets appear first.

Weights (pre-normalisation):
  Rules layer    : 0-50 pts  (highest confidence -- binary violations)
  Peer stats     : 0-25 pts  (statistical outliers within cohort)
  ML anomaly     : 0-15 pts  (unsupervised; catches novel patterns)
  Code-mix drift : 0-10 pts  (KL / cosine drift from cohort)

Outputs risk_scores.csv.
"""

import os

import numpy as np
import pandas as pd

RULES_CSV    = "rules_flags.csv"
PEER_CSV     = "peer_flags.csv"
ML_CSV       = "ml_scores.csv"
CODEMIX_CSV   = "provider_codemix.csv"
TEMPORAL_CSV  = "provider_temporal.csv"
FEEDBACK_CSV  = "feedback_scores.csv"
CLAIMS_CSV    = "claims.csv"
OUTPUT_CSV    = "risk_scores.csv"

# Points per rule type
RULE_POINTS = {
    "impossible_day":    40,
    "duplicate_billing": 35,
    "unbundling":        30,
}

PEER_MAX_PTS     = 25   # cap for peer-stats contribution
ML_MAX_PTS       = 15   # cap for ML contribution
CODEMIX_MAX_PTS  = 10   # cap for code-mix drift contribution
TEMPORAL_MAX_PTS =  5   # cap for temporal change-point contribution

# ── Phase 6: confidence tiers and expected-recovery scoring ──────────────────
#
# Confidence is assigned per-flag based on the strongest signal present:
#   HIGH   -- deterministic rule violation (binary, defensible in audit)
#   MEDIUM -- multiple statistical/structural signals but no bright-line rule
#   LOW    -- single weak signal (ML-only or single marginal peer stat)
#
# Expected recovery = estimated_exposure x recovery_likelihood
#
# Providers below MIN_SCORE_THRESHOLD are suppressed from the ranked worklist;
# this eliminates very-low-confidence flags that would otherwise crowd out
# actionable cases.

CONFIDENCE_LIKELIHOOD = {
    "HIGH":   0.70,
    "MEDIUM": 0.40,
    "LOW":    0.15,
}

MIN_SCORE_THRESHOLD = 10   # suppress below this; only HIGH-confidence misses possible


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
    """0-25 pts based on how many metrics breach |z|>3.5 and by how much."""
    pdf = pd.read_csv(PEER_CSV, dtype={"provider_id": str})
    if pdf.empty:
        return pd.DataFrame(columns=["provider_id","peer_score","peer_exposure","peer_reasons"])

    pdf["metric_pts"] = pdf["z_score"].abs().apply(lambda z: min((z - 3.5) * 2 + 5, 10))

    agg = (
        pdf.groupby("provider_id")
           .agg(
               peer_score   =("metric_pts",          "sum"),
               peer_exposure=("estimated_exposure",  "first"),
               peer_reasons =("metric",              lambda x: "; ".join(sorted(set(x)))),
           )
           .reset_index()
    )
    agg["peer_score"] = agg["peer_score"].clip(upper=PEER_MAX_PTS)
    return agg


def ml_component() -> pd.DataFrame:
    """0-15 pts from IsolationForest normalised score."""
    mdf = pd.read_csv(ML_CSV, dtype={"provider_id": str})
    mdf["ml_score_pts"] = (mdf["ml_score"] / 100 * ML_MAX_PTS).round(2)
    return mdf[["provider_id","ml_score","ml_score_pts","ml_is_anomaly"]]


def temporal_component() -> pd.DataFrame:
    """0-5 pts from CUSUM change-point / spike detection.  Skipped if absent."""
    if not os.path.exists(TEMPORAL_CSV):
        return pd.DataFrame(columns=["provider_id","temporal_score","temporal_flag"])
    tdf = pd.read_csv(TEMPORAL_CSV, dtype={"provider_id": str})
    # Normalise CUSUM score (cap at 6.0 => full 5 pts)
    tdf["temporal_score"] = (
        tdf["cusum_score"].clip(upper=6.0) / 6.0 * TEMPORAL_MAX_PTS
    ).round(2)
    # Extra point for spike
    tdf["temporal_score"] += tdf["spike_flag"].astype(float) * 1.0
    tdf["temporal_score"]  = tdf["temporal_score"].clip(upper=TEMPORAL_MAX_PTS).round(2)
    tdf["temporal_flag"]   = tdf["temporal_flag"].astype(int)
    return tdf[["provider_id","temporal_score","temporal_flag"]]


def codemix_component() -> pd.DataFrame:
    """0-10 pts from KL/cosine code-mix drift.  Skipped if file absent."""
    if not os.path.exists(CODEMIX_CSV):
        return pd.DataFrame(columns=["provider_id","codemix_score","codemix_flag",
                                     "kl_divergence","cosine_distance"])
    cdf = pd.read_csv(CODEMIX_CSV, dtype={"provider_id": str})
    # Normalise KL to 0-10 pts (cap at KL=1.0 => 10 pts)
    cdf["codemix_score"] = (cdf["kl_divergence"].clip(upper=1.0) * CODEMIX_MAX_PTS).round(2)
    cdf["codemix_flag"]  = cdf["drift_flag"].astype(int)
    return cdf[["provider_id","codemix_score","codemix_flag",
                "kl_divergence","cosine_distance"]]


def feedback_component() -> pd.DataFrame:
    """0-10 pts from semi-supervised feedback model.  Skipped if absent."""
    if not os.path.exists(FEEDBACK_CSV):
        return pd.DataFrame(columns=["provider_id", "feedback_score", "feedback_label"])
    fdf = pd.read_csv(FEEDBACK_CSV, dtype={"provider_id": str})
    return fdf[["provider_id", "feedback_score", "feedback_label"]]


def build_risk_scores() -> pd.DataFrame:
    meta     = load_claims_meta()
    rules    = rules_component()
    peer     = peer_component()
    ml       = ml_component()
    codemix  = codemix_component()
    temporal = temporal_component()
    feedback = feedback_component()

    df = meta.merge(rules,    on="provider_id", how="left")
    df = df.merge(peer,       on="provider_id", how="left")
    df = df.merge(ml,         on="provider_id", how="left")
    df = df.merge(codemix,    on="provider_id", how="left")
    df = df.merge(temporal,   on="provider_id", how="left")
    df = df.merge(feedback,   on="provider_id", how="left")

    df["rules_score"]     = df["rules_score"].fillna(0)
    df["peer_score"]      = df["peer_score"].fillna(0)
    df["ml_score_pts"]    = df["ml_score_pts"].fillna(0)
    df["ml_score"]        = df["ml_score"].fillna(0)
    df["ml_is_anomaly"]   = df["ml_is_anomaly"].fillna(0).astype(int)
    df["codemix_score"]   = df["codemix_score"].fillna(0)
    df["codemix_flag"]    = df["codemix_flag"].fillna(0).astype(int)
    df["kl_divergence"]   = df["kl_divergence"].fillna(0)
    df["cosine_distance"] = df["cosine_distance"].fillna(0)
    df["temporal_score"]  = df["temporal_score"].fillna(0)
    df["temporal_flag"]   = df["temporal_flag"].fillna(0).astype(int)
    df["feedback_score"]  = df["feedback_score"].fillna(0)
    df["feedback_label"]  = df["feedback_label"].fillna(0).astype(int)

    # Combined 0-100 risk score
    df["risk_score"] = (
        df["rules_score"] + df["peer_score"] +
        df["ml_score_pts"] + df["codemix_score"] + df["temporal_score"] +
        df["feedback_score"]
    ).clip(upper=100).round(1)

    # Estimated exposure: rules exposure where available, else fraction of total billed
    df["estimated_exposure"] = (
        df["rules_exposure"]
          .fillna(df["peer_exposure"])
          .fillna(df["total_billed"] * 0.10)
    )

    # Dollar-weighted rank score (used only for ordering)
    df["_rank_score"] = df["risk_score"] * np.log1p(df["estimated_exposure"] / 1_000)

    # ── Top reason (vectorized — no per-row Python apply) ────────────────────
    has_rule   = df["rules_reasons"].notna() & (df["rules_reasons"] != "")
    has_peer   = df["peer_reasons"].notna()  & (df["peer_reasons"]  != "")
    has_ml     = df["ml_is_anomaly"].astype(bool)
    has_cm     = df["codemix_flag"].astype(bool)
    has_temp   = df["temporal_flag"].astype(bool)
    has_fb     = df["feedback_label"].astype(bool)

    rule_str  = np.where(has_rule,   "Rule: "         + df["rules_reasons"].fillna(""),    "")
    peer_str  = np.where(has_peer,   "Peer z>3: "     + df["peer_reasons"].fillna(""),     "")
    ml_str    = np.where(has_ml,     "ML anomaly score " + df["ml_score"].map("{:.0f}".format) + "/100", "")
    cm_str    = np.where(has_cm,     "Code-mix drift KL=" + df["kl_divergence"].map("{:.3f}".format), "")
    temp_str  = np.where(has_temp,   "Temporal change-point",                              "")
    fb_str    = np.where(has_fb,     "Feedback model confirmed",                           "")

    def _join_parts(row_parts):
        return " | ".join(p for p in row_parts if p) or "no flags"

    reason_parts = list(zip(rule_str, peer_str, ml_str, cm_str, temp_str, fb_str))
    df["top_reason"] = [_join_parts(p) for p in reason_parts]

    # ── Phase 6: confidence tier (vectorized) ────────────────────────────────
    n_stat = (
        (df["peer_score"]    > 0).astype(int) +
        df["codemix_flag"].astype(int) +
        df["temporal_flag"].astype(int)
    )
    medium_cond = (n_stat >= 2) | ((n_stat == 1) & df["ml_is_anomaly"].astype(bool))
    df["confidence"] = np.where(
        df["rules_score"] > 0, "HIGH",
        np.where(medium_cond, "MEDIUM", "LOW")
    )

    # ── Expected recovery = exposure x likelihood (vectorized) ───────────────
    likelihood_map = pd.Series(CONFIDENCE_LIKELIHOOD)
    df["expected_recovery"] = (
        df["estimated_exposure"] * df["confidence"].map(likelihood_map)
    ).round(2)

    # ── Dollar-weighted rank score using expected recovery (not raw exposure) ─
    df["_rank_score"] = df["risk_score"] * np.log1p(df["expected_recovery"] / 1_000)

    # ── Suppress very-low-confidence flags (reduces FP noise) ─────────────────
    flagged = df[df["risk_score"] >= MIN_SCORE_THRESHOLD].copy()
    flagged = flagged.sort_values("_rank_score", ascending=False)

    out_cols = [
        "provider_id","provider_name","specialty",
        "risk_score","confidence","estimated_exposure","expected_recovery",
        "rules_score","peer_score","ml_score","ml_is_anomaly",
        "codemix_score","codemix_flag","kl_divergence","cosine_distance",
        "temporal_score","temporal_flag",
        "feedback_score","feedback_label",
        "top_reason",
    ]
    result = flagged[out_cols].reset_index(drop=True)
    result.to_csv(OUTPUT_CSV, index=False)

    # Append flag_generated events to the immutable audit trail.
    # Wrapped in try/except so a missing audit_log never blocks scoring.
    try:
        import audit_log as _al
        _current_version = None
        try:
            import model_registry as _mr
            v = _mr.current_version()
            if v:
                _current_version = v["version_id"]
        except Exception:
            pass

        for _, row in result.iterrows():
            sigs = []
            if row["rules_score"] > 0:
                sigs.append(str(row.get("rules_reasons", "rules")))
            if row["peer_score"] > 0:
                sigs.append("peer_stats")
            if row["ml_is_anomaly"]:
                sigs.append(f"ml_ensemble:{row['ml_score']:.0f}")
            if row["codemix_flag"]:
                sigs.append("codemix_drift")
            if row["temporal_flag"]:
                sigs.append("temporal_change_point")
            _al.append_event(
                "flag_generated",
                provider_id=row["provider_id"],
                model_version=_current_version,
                signals_shown=sigs,
                reasoning=row["top_reason"],
            )
    except Exception:
        pass  # never block scoring output on audit log errors

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
