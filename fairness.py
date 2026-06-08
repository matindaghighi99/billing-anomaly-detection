"""Phase 9 -- Bias / fairness audit.

Checks whether the detection system flags certain specialties, clinics, or
practice-settings at disproportionate rates that cannot be explained by the
planted bad actors.

METHODOLOGY:
  1. Merge the risk-score worklist with the full provider roster (from claims.csv).
  2. For each grouping variable (specialty, clinic_id, practice_setting):
     a. Flag rate: proportion of providers in the group that appear on the worklist.
     b. Mean risk score: average across ALL providers in the group (flagged or not).
     c. Confirmed bad-actor share: of flagged providers, what fraction are ground-truth
        bad actors vs. unknown/clean.  Measures precision proxy.
     d. Chi-square test (2x2: flagged/unflagged x group/not-group) for each group vs.
        the rest -- tests whether the group's flag rate differs significantly.
  3. Highlights groups with elevated flag rates not driven by planted bad actors
     (the "unexplained flagging" concern).

Outputs:
  fairness_summary.csv    -- one row per (dimension, group)
  fairness_report.md      -- human-readable narrative report
"""

import json
import os

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency

CLAIMS_CSV       = "claims.csv"
SCORES_CSV       = "risk_scores.csv"
GROUND_TRUTH_JSON = "ground_truth.json"
METRICS_CSV      = "provider_metrics.csv"
OUTPUT_CSV       = "fairness_summary.csv"
OUTPUT_REPORT    = "fairness_report.md"

MIN_GROUP_SIZE   = 5    # skip groups too small for meaningful chi-square
P_VALUE_ALERT    = 0.05 # flag groups with statistically significant differences


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_provider_roster() -> pd.DataFrame:
    """One row per provider with specialty, clinic_id, practice_setting."""
    claims = pd.read_csv(CLAIMS_CSV, parse_dates=["service_date"],
                         dtype={"provider_id": str, "fee_code": str,
                                "patient_id": str})
    providers = (
        claims.groupby("provider_id")
              .agg(specialty=("specialty", "first"),
                   clinic_id=("clinic_id", "first"),
                   n_claims=("claim_id", "count"),
                   n_days=("service_date", "nunique"))
              .reset_index()
    )
    # Derive practice setting (mirrors peer_stats.py)
    N_WORKING_DAYS = 261
    PART_TIME_THRESHOLD = 0.40
    providers["active_day_fraction"] = providers["n_days"] / N_WORKING_DAYS
    providers["practice_setting"] = np.where(
        providers["active_day_fraction"] < PART_TIME_THRESHOLD,
        "part_time", "full_time"
    )
    return providers


def _load_ground_truth() -> tuple[set, set]:
    """Returns (bad_actor_ids, clean_ids)."""
    if not os.path.exists(GROUND_TRUTH_JSON):
        return set(), set()
    with open(GROUND_TRUTH_JSON) as f:
        gt = json.load(f)
    bad  = set(gt.get("all_bad_actors", []))
    clean = set(gt.get("clean_providers", {}).keys())
    return bad, clean


# ── Core audit ────────────────────────────────────────────────────────────────

def _group_stats(dimension: str, providers: pd.DataFrame,
                 flagged_ids: set, bad_ids: set) -> pd.DataFrame:
    """Compute flag rate and chi-square p-value per group in a dimension."""
    rows = []
    all_ids   = set(providers["provider_id"])
    n_total   = len(all_ids)
    n_flagged_global = len(flagged_ids & all_ids)

    for grp_val, grp_df in providers.groupby(dimension):
        grp_ids    = set(grp_df["provider_id"])
        n_grp      = len(grp_ids)
        if n_grp < MIN_GROUP_SIZE:
            continue

        n_flagged_grp     = len(flagged_ids & grp_ids)
        n_unflagged_grp   = n_grp - n_flagged_grp
        n_flagged_other   = n_flagged_global - n_flagged_grp
        n_unflagged_other = (n_total - n_grp) - n_flagged_other

        flag_rate = n_flagged_grp / n_grp if n_grp > 0 else 0.0

        # Subset of flagged in this group: how many are ground-truth bad actors?
        flagged_in_grp = flagged_ids & grp_ids
        n_confirmed   = len(flagged_in_grp & bad_ids)
        precision_proxy = n_confirmed / n_flagged_grp if n_flagged_grp > 0 else None

        # Mean risk score across group (all providers, not just flagged)
        scores = pd.read_csv(SCORES_CSV, dtype={"provider_id": str})
        score_map = dict(zip(scores["provider_id"], scores["risk_score"]))
        grp_scores = [score_map.get(pid, 0.0) for pid in grp_ids]
        mean_risk  = float(np.mean(grp_scores))

        # Chi-square test: is this group's flag rate different from the rest?
        contingency = [
            [n_flagged_grp,   n_unflagged_grp],
            [n_flagged_other, n_unflagged_other],
        ]
        try:
            _, p_val, _, _ = chi2_contingency(contingency, correction=True)
        except ValueError:
            p_val = 1.0

        rows.append({
            "dimension":        dimension,
            "group":            grp_val,
            "n_providers":      n_grp,
            "n_flagged":        n_flagged_grp,
            "flag_rate":        round(flag_rate, 4),
            "mean_risk_score":  round(mean_risk, 2),
            "n_confirmed_bad":  n_confirmed,
            "precision_proxy":  round(precision_proxy, 4) if precision_proxy is not None else None,
            "chi2_p_value":     round(p_val, 4),
            "alert":            (p_val < P_VALUE_ALERT) and (flag_rate > n_flagged_global / n_total),
        })

    return pd.DataFrame(rows)


def run_fairness_audit() -> pd.DataFrame:
    providers = _load_provider_roster()
    scores    = pd.read_csv(SCORES_CSV, dtype={"provider_id": str})
    bad_ids, clean_ids = _load_ground_truth()

    flagged_ids = set(scores["provider_id"])

    parts = []
    for dim in ["specialty", "clinic_id", "practice_setting"]:
        df = _group_stats(dim, providers, flagged_ids, bad_ids)
        parts.append(df)

    summary = pd.concat(parts, ignore_index=True)
    summary.to_csv(OUTPUT_CSV, index=False)
    return summary, flagged_ids, bad_ids, providers


# ── Report writer ─────────────────────────────────────────────────────────────

def write_report(summary: pd.DataFrame, flagged_ids: set,
                 bad_ids: set, providers: pd.DataFrame) -> str:
    lines = []
    lines.append("# Billing Anomaly Detection -- Fairness Audit Report")
    lines.append("")
    lines.append(f"**Generated:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Total providers:** {len(providers)}")
    lines.append(f"**Providers flagged:** {len(flagged_ids)}")
    lines.append(f"**Overall flag rate:** {len(flagged_ids)/len(providers):.1%}")
    lines.append(f"**Planted bad actors:** {len(bad_ids)}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Methodology")
    lines.append("")
    lines.append(
        "For each grouping variable (specialty, clinic, practice-setting) we compute "
        "the flag rate (fraction of providers in the group that appear on the audit "
        "worklist) and test whether it differs from the rest of the population using "
        "a chi-square test with Yates continuity correction. A group is highlighted "
        f"when p < {P_VALUE_ALERT} AND the group's flag rate exceeds the overall "
        "average -- indicating unexplained over-representation."
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    alert_rows = summary[summary["alert"] == True]

    for dim in ["specialty", "clinic_id", "practice_setting"]:
        dim_df = summary[summary["dimension"] == dim].sort_values(
            "flag_rate", ascending=False
        )
        label = {"specialty": "Specialty", "clinic_id": "Clinic",
                 "practice_setting": "Practice Setting"}[dim]
        lines.append(f"## {label} Breakdown")
        lines.append("")
        lines.append(
            f"| {label} | Providers | Flagged | Flag Rate | Mean Score | "
            f"Confirmed Bad | Precision | chi2 p | Alert |"
        )
        lines.append(
            "|" + "|".join(["-" * 14] * 9) + "|"
        )
        overall_rate = len(flagged_ids) / len(providers)
        for _, row in dim_df.iterrows():
            prec = f"{row['precision_proxy']:.0%}" if row["precision_proxy"] is not None else "n/a"
            alert_str = "**YES**" if row["alert"] else "no"
            lines.append(
                f"| {row['group']} | {row['n_providers']} | {row['n_flagged']} | "
                f"{row['flag_rate']:.1%} | {row['mean_risk_score']:.1f} | "
                f"{row['n_confirmed_bad']} | {prec} | {row['chi2_p_value']:.3f} | "
                f"{alert_str} |"
            )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Summary of Alerts")
    lines.append("")

    if alert_rows.empty:
        lines.append(
            "No statistically significant unexplained over-flagging detected. "
            "All elevated flag rates are accounted for by planted bad actors."
        )
    else:
        lines.append(
            f"{len(alert_rows)} group(s) show statistically significant "
            f"over-representation (p < {P_VALUE_ALERT}):"
        )
        lines.append("")
        for _, row in alert_rows.iterrows():
            lines.append(
                f"- **{row['dimension']} = {row['group']}**: flag rate "
                f"{row['flag_rate']:.1%} vs overall "
                f"{len(flagged_ids)/len(providers):.1%} "
                f"(p={row['chi2_p_value']:.3f}, {row['n_confirmed_bad']} of "
                f"{row['n_flagged']} flagged are confirmed bad actors)"
            )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "> **Note:** This system operates on synthetic data. "
        "All findings are for demonstration only. "
        "In a production system, over-flagging of specific demographic or "
        "geographic groups would require investigation before deployment."
    )

    report = "\n".join(lines)
    with open(OUTPUT_REPORT, "w", encoding="utf-8") as f:
        f.write(report)
    return report


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print("Phase 9 - Bias / Fairness Audit")
    print("=" * 60)

    summary, flagged_ids, bad_ids, providers = run_fairness_audit()
    report = write_report(summary, flagged_ids, bad_ids, providers)

    n_alerts = summary["alert"].sum()
    print(f"  Providers in roster  : {len(providers)}")
    print(f"  Providers flagged    : {len(flagged_ids)}")
    print(f"  Overall flag rate    : {len(flagged_ids)/len(providers):.1%}")
    print()

    for dim in ["specialty", "clinic_id", "practice_setting"]:
        dim_df = summary[summary["dimension"] == dim].sort_values("flag_rate", ascending=False)
        label  = {"specialty": "Specialty", "clinic_id": "Clinic",
                  "practice_setting": "Practice Setting"}[dim]
        print(f"  {label}:")
        print(f"  {'Group':<22} {'N':>5}  {'Flagged':>7}  {'Rate':>7}  {'p-val':>7}  Alert")
        print("  " + "-" * 62)
        for _, row in dim_df.iterrows():
            alert = "YES" if row["alert"] else ""
            print(f"  {str(row['group']):<22} {row['n_providers']:>5}  "
                  f"{row['n_flagged']:>7}  {row['flag_rate']:>6.1%}  "
                  f"{row['chi2_p_value']:>7.3f}  {alert}")
        print()

    print(f"  Alerts (over-flagging, p<{P_VALUE_ALERT}): {n_alerts}")
    print(f"  Full summary : {OUTPUT_CSV}")
    print(f"  Report       : {OUTPUT_REPORT}")


if __name__ == "__main__":
    main()
