"""fraud_evidence.py — Mine a claims table for evidence of revenue inflation.

This is the "search for any evidence or information that the doctors use to make
more money" step. It is a DISCOVERY tool: it reads only the claims table (never
the ground-truth file) and surfaces, per provider, the concrete billing
behaviours that inflate reimbursement — each with a plain-English evidence
string, a dollar estimate of the extra revenue, and a count of supporting
claims/events.

Detectors (each maps to a documented real-world scheme):
  1.  Upcoding (E/M complexity inflation)        — avg E/M price vs specialty cohort
  2.  Psychotherapy time inflation               — 90837 share vs cohort
  3.  Unbundling                                 — 93005+93010 vs bundle 93000
  4.  Duplicate billing                          — identical claim resubmitted
  5.  Impossible day                             — >1 440 service-minutes in a day
  6.  Phantom / excessive volume                 — claims/active-day vs cohort
  7.  Self-referral out-of-specialty imaging     — MRI/CT billed by non-radiology
  8.  Modifier-25 separate-E/M abuse             — E/M -25 stacked on procedures
  9.  Unit / dosage inflation                    — units far above cohort on dose codes
  10. Escalating upcoding over time              — top-tier share trend (early→late)
  11. Weekend / closed-office billing            — claims on Sat/Sun

OUTPUTS
    fraud_evidence.csv          one row per (provider, scheme) finding
    FRAUD_EVIDENCE_REPORT.md    ranked narrative report

USAGE
    python fraud_evidence.py                      # reads claims_large.csv
    python fraud_evidence.py --input claims.csv   # works on the base dataset too
"""

import argparse
import json
import os
import sys

# Make the section folders importable as flat modules regardless of CWD.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _sectionpath  # noqa: E402  (registers section folders on sys.path)

import numpy as np
import pandas as pd

from data_gen_large import FEE_SCHEDULE, BUNDLE_RULES, UNIT_BILLABLE
from dataset_config import data_path, report_path

# ── Code groups ───────────────────────────────────────────────────────────────
EM_OFFICE   = {"99211", "99212", "99213", "99214", "99215",
               "99202", "99203", "99204", "99205"}
EM_TOP      = {"99215", "99205", "99204"}
THERAPY     = {"90832", "90834", "90837"}
IMAGING_HI  = {"72148", "70553", "74177", "71250", "73721"}

# Thresholds (kept explicit so analysts can tune sensitivity)
MIN_EM_CLAIMS      = 25     # need enough E/M volume to judge upcoding
UPCODE_DELTA       = 0.20   # provider top-tier share must exceed cohort median by this
UPCODE_ABS         = 0.45   # ...and exceed this absolute share
VOLUME_MULT        = 3.0    # claims/active-day this many× cohort median = excessive
IMPOSSIBLE_MIN     = 1440   # service-minutes/day ceiling
UNIT_MULT          = 2.5    # units this many× cohort median on a dose code


def _evidence_row(pid, specialty, scheme, evidence, extra, support):
    return {
        "provider_id": pid, "specialty": specialty, "scheme": scheme,
        "evidence": evidence,
        "estimated_extra_revenue": round(float(max(extra, 0.0)), 2),
        "support_claims": int(support),
    }


def load_claims(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["service_date"],
                     dtype={"fee_code": str, "provider_id": str,
                            "patient_id": str, "clinic_id": str,
                            "modifier": str})
    if "modifier" not in df.columns:
        df["modifier"] = ""
    # mostly-empty CSV columns get re-inferred as float on read (".0" suffix);
    # normalise back to clean modifier tokens.
    df["modifier"] = (df["modifier"].fillna("").astype(str)
                        .str.replace(r"\.0$", "", regex=True)
                        .replace("nan", ""))
    if "units" not in df.columns:
        df["units"] = 1
    return df


def provider_meta(df: pd.DataFrame) -> pd.DataFrame:
    return df[["provider_id", "specialty"]].drop_duplicates("provider_id") \
             .set_index("provider_id")


# ── 1. Upcoding ────────────────────────────────────────────────────────────────

def detect_upcoding(df, meta):
    em = df[df["fee_code"].isin(EM_OFFICE)]
    if em.empty:
        return []
    g = em.groupby("provider_id")
    per = pd.DataFrame({
        "specialty":  g["specialty"].first(),
        "n_em":       g.size(),
        "avg_price":  g["amount_billed"].mean(),
        "top_share":  g["fee_code"].apply(lambda s: s.isin(EM_TOP).mean()),
    })
    # specialty cohort baselines
    coh_share = per.groupby("specialty")["top_share"].median()
    coh_price = per.groupby("specialty")["avg_price"].median()
    rows = []
    for pid, r in per.iterrows():
        if r["n_em"] < MIN_EM_CLAIMS:
            continue
        base_share = coh_share[r["specialty"]]
        if r["top_share"] >= max(UPCODE_ABS, base_share + UPCODE_DELTA):
            extra = r["n_em"] * max(0.0, r["avg_price"] - coh_price[r["specialty"]])
            rows.append(_evidence_row(
                pid, r["specialty"], "Upcoding (E/M complexity inflation)",
                f"Top-tier E/M codes on {r['top_share']:.0%} of {int(r['n_em'])} office "
                f"visits vs {r['specialty']} cohort median {base_share:.0%}; "
                f"avg E/M ${r['avg_price']:.0f} vs cohort ${coh_price[r['specialty']]:.0f}",
                extra, r["n_em"]))
    return rows


# ── 2. Psychotherapy time inflation ─────────────────────────────────────────────

def detect_psych_time(df, meta):
    th = df[df["fee_code"].isin(THERAPY)]
    if th.empty:
        return []
    g = th.groupby("provider_id")
    per = pd.DataFrame({
        "specialty": g["specialty"].first(),
        "n_th":      g.size(),
        "share_60":  g["fee_code"].apply(lambda s: (s == "90837").mean()),
    })
    coh = per.groupby("specialty")["share_60"].median()
    rows = []
    p60 = FEE_SCHEDULE["90837"]["amount"]
    p45 = FEE_SCHEDULE["90834"]["amount"]
    for pid, r in per.iterrows():
        if r["n_th"] < MIN_EM_CLAIMS:
            continue
        if r["share_60"] >= max(0.7, coh[r["specialty"]] + 0.25):
            extra = r["n_th"] * r["share_60"] * (p60 - p45)
            rows.append(_evidence_row(
                pid, r["specialty"], "Psychotherapy time inflation",
                f"Billed 60-min psychotherapy (90837) on {r['share_60']:.0%} of "
                f"{int(r['n_th'])} sessions vs cohort median {coh[r['specialty']]:.0%}",
                extra, r["n_th"]))
    return rows


# ── 3. Unbundling ────────────────────────────────────────────────────────────

def detect_unbundling(df, meta):
    rows = []
    for rule in BUNDLE_RULES:
        comps = rule["components"]
        sub = df[df["fee_code"].isin(comps)]
        if sub.empty:
            continue
        pivot = (sub.groupby(["provider_id", "patient_id", "service_date"])["fee_code"]
                    .agg(lambda s: frozenset(s)))
        amt = (sub.groupby(["provider_id", "patient_id", "service_date"])["amount_billed"]
                  .sum())
        events = pivot[pivot == comps]
        if events.empty:
            continue
        ev_amt = amt.loc[events.index]
        per = ev_amt.groupby(level=0)
        for pid, grp in per:
            n = len(grp)
            extra = float(grp.sum() - n * rule["bundle_amt"])
            rows.append(_evidence_row(
                pid, meta.loc[pid, "specialty"], "Unbundling component codes",
                f"{n} patient-dates billed {'+'.join(sorted(comps))} separately "
                f"instead of bundle {rule['bundle_code']} ({rule['bundle_desc']})",
                extra, n))
    return rows


# ── 4. Duplicate billing ─────────────────────────────────────────────────────

def detect_duplicates(df, meta):
    key = ["provider_id", "patient_id", "fee_code", "service_date", "units"]
    g = df.groupby(key).agg(n=("claim_id", "count"),
                            unit=("amount_billed", "first"))
    dups = g[g["n"] > 1]
    if dups.empty:
        return []
    dups = dups.reset_index()
    dups["extra"] = (dups["n"] - 1) * dups["unit"]
    per = dups.groupby("provider_id").agg(events=("n", "count"),
                                          extra=("extra", "sum"))
    rows = []
    for pid, r in per.iterrows():
        if r["events"] < 3:
            continue
        rows.append(_evidence_row(
            pid, meta.loc[pid, "specialty"], "Duplicate claim resubmission",
            f"{int(r['events'])} claim(s) resubmitted with identical patient, code, "
            f"date and units (paid more than once)",
            r["extra"], r["events"]))
    return rows


# ── 5. Impossible day ──────────────────────────────────────────────────────────

def detect_impossible_days(df, meta):
    day = df.groupby(["provider_id", "service_date"]).agg(
        mins=("service_minutes", "sum"),
        billed=("amount_billed", "sum"),
        n=("claim_id", "count"))
    bad = day[day["mins"] > IMPOSSIBLE_MIN].reset_index()
    if bad.empty:
        return []
    rows = []
    for pid, grp in bad.groupby("provider_id"):
        worst = grp.loc[grp["mins"].idxmax()]
        rows.append(_evidence_row(
            pid, meta.loc[pid, "specialty"], "Impossible day (>24h billed)",
            f"{len(grp)} day(s) over {IMPOSSIBLE_MIN} service-minutes; worst: "
            f"{int(worst['mins']):,} min across {int(worst['n'])} claims on "
            f"{worst['service_date'].date()}",
            grp["billed"].sum(), len(grp)))
    return rows


# ── 6. Phantom / excessive volume ───────────────────────────────────────────────

def detect_volume(df, meta):
    g = df.groupby("provider_id")
    per = pd.DataFrame({
        "specialty":   g["specialty"].first(),
        "n":           g.size(),
        "active_days": g["service_date"].nunique(),
        "avg_price":   g["amount_billed"].mean(),
    })
    per["cpd"] = per["n"] / per["active_days"].clip(lower=1)
    coh = per.groupby("specialty")["cpd"].median()
    rows = []
    for pid, r in per.iterrows():
        base = coh[r["specialty"]]
        if r["cpd"] >= VOLUME_MULT * base and r["cpd"] >= 8:
            excess = (r["cpd"] - base) * r["active_days"]
            rows.append(_evidence_row(
                pid, r["specialty"], "Phantom / excessive claim volume",
                f"{r['cpd']:.1f} claims/active-day vs {r['specialty']} cohort median "
                f"{base:.1f} (~{int(excess):,} excess claims)",
                excess * r["avg_price"], r["n"]))
    return rows


# ── 7. Self-referral out-of-specialty imaging ───────────────────────────────────

def detect_self_referral(df, meta):
    img = df[df["fee_code"].isin(IMAGING_HI) & (df["specialty"] != "Radiology")]
    if img.empty:
        return []
    g = img.groupby("provider_id")
    per = pd.DataFrame({"specialty": g["specialty"].first(),
                        "n": g.size(), "billed": g["amount_billed"].sum()})
    rows = []
    for pid, r in per.iterrows():
        if r["n"] < 10:
            continue
        rows.append(_evidence_row(
            pid, r["specialty"], "Self-referral out-of-specialty imaging",
            f"Billed {int(r['n'])} high-value MRI/CT studies (${r['billed']:,.0f}) "
            f"under the {r['specialty']} specialty — imaging normally read by Radiology",
            r["billed"], r["n"]))
    return rows


# ── 8. Modifier-25 abuse ─────────────────────────────────────────────────────

def detect_modifier_25(df, meta):
    m = df[(df["modifier"] == "25") & df["fee_code"].isin(EM_OFFICE)]
    if m.empty:
        return []
    g = m.groupby("provider_id")
    per = pd.DataFrame({"specialty": g["specialty"].first(),
                        "n": g.size(), "billed": g["amount_billed"].sum()})
    rows = []
    for pid, r in per.iterrows():
        if r["n"] < 15:
            continue
        rows.append(_evidence_row(
            pid, r["specialty"], "Modifier-25 separate-E/M abuse",
            f"{int(r['n'])} office visits billed with modifier 25 (separately-payable "
            f"E/M) stacked onto same-day procedures (${r['billed']:,.0f})",
            r["billed"], r["n"]))
    return rows


# ── 9. Unit / dosage inflation ──────────────────────────────────────────────────

def detect_unit_inflation(df, meta):
    sub = df[df["fee_code"].isin(UNIT_BILLABLE)].copy()
    if sub.empty:
        return []
    sub["units"] = pd.to_numeric(sub["units"], errors="coerce").fillna(1)
    coh = sub.groupby("fee_code")["units"].median()
    rows = []
    for pid, grp in sub.groupby("provider_id"):
        flagged_units = 0
        extra = 0.0
        codes_hit = []
        for code, cg in grp.groupby("fee_code"):
            base = max(coh[code], 1.0)
            avg_u = cg["units"].mean()
            if avg_u >= UNIT_MULT * base and len(cg) >= 10:
                unit_price = (cg["amount_billed"] / cg["units"].clip(lower=1)).mean()
                extra += float(((cg["units"] - base).clip(lower=0) * unit_price).sum())
                flagged_units += len(cg)
                codes_hit.append(f"{code}(avg {avg_u:.1f}u vs {base:.0f})")
        if flagged_units >= 10:
            rows.append(_evidence_row(
                pid, meta.loc[pid, "specialty"], "Unit / dosage inflation",
                f"Inflated units on dose-based codes: {', '.join(codes_hit)}",
                extra, flagged_units))
    return rows


# ── 10. Escalating upcoding over time ────────────────────────────────────────────

def detect_escalating(df, meta):
    em = df[df["fee_code"].isin(EM_OFFICE)].copy()
    if em.empty:
        return []
    mid = em["service_date"].min() + (em["service_date"].max() - em["service_date"].min()) / 2
    em["half"] = np.where(em["service_date"] <= mid, "early", "late")
    rows = []
    for pid, grp in em.groupby("provider_id"):
        early = grp[grp["half"] == "early"]
        late  = grp[grp["half"] == "late"]
        if len(early) < 20 or len(late) < 20:
            continue
        s_early = early["fee_code"].isin(EM_TOP).mean()
        s_late  = late["fee_code"].isin(EM_TOP).mean()
        if (s_late - s_early) >= 0.30 and s_late >= 0.5:
            extra = len(late) * max(0.0, late["amount_billed"].mean() - early["amount_billed"].mean())
            rows.append(_evidence_row(
                pid, meta.loc[pid, "specialty"], "Escalating upcoding over time",
                f"Top-tier E/M share climbed from {s_early:.0%} (early) to {s_late:.0%} "
                f"(late); avg visit ${early['amount_billed'].mean():.0f} → "
                f"${late['amount_billed'].mean():.0f}",
                extra, len(grp)))
    return rows


# ── 11. Weekend / closed-office billing ──────────────────────────────────────────

def detect_weekend(df, meta):
    wk = df[df["service_date"].dt.weekday >= 5]
    if wk.empty:
        return []
    g = wk.groupby("provider_id")
    per = pd.DataFrame({"specialty": g["specialty"].first(),
                        "n": g.size(), "billed": g["amount_billed"].sum()})
    rows = []
    for pid, r in per.iterrows():
        if r["n"] < 20:
            continue
        rows.append(_evidence_row(
            pid, r["specialty"], "Weekend / closed-office billing",
            f"{int(r['n'])} claims (${r['billed']:,.0f}) billed on weekends — "
            f"unusual for an outpatient {r['specialty']} practice",
            r["billed"], r["n"]))
    return rows


DETECTORS = [
    detect_upcoding, detect_psych_time, detect_unbundling, detect_duplicates,
    detect_impossible_days, detect_volume, detect_self_referral,
    detect_modifier_25, detect_unit_inflation, detect_escalating, detect_weekend,
]


# ── Report ─────────────────────────────────────────────────────────────────────

def build_report(df, findings: pd.DataFrame, input_path: str, gt: dict | None) -> str:
    n_claims    = len(df)
    n_providers = df["provider_id"].nunique()
    total_extra = findings["estimated_extra_revenue"].sum()
    by_prov = (findings.groupby(["provider_id", "specialty"])
                       .agg(total_extra=("estimated_extra_revenue", "sum"),
                            n_schemes=("scheme", "nunique"),
                            schemes=("scheme", lambda s: ", ".join(sorted(set(s)))))
                       .reset_index()
                       .sort_values("total_extra", ascending=False))

    L = []
    L.append("# Billing Revenue-Inflation Evidence Report\n")
    L.append("> **Synthetic data.** Every provider, patient, and claim in this report "
             "is fictional. This is a decision-support discovery tool for human "
             "auditors; nothing here constitutes a finding of fraud.\n")
    L.append("## Dataset\n")
    L.append(f"| Field | Value |\n|---|---|")
    L.append(f"| Source file | `{input_path}` |")
    L.append(f"| Claims analysed | {n_claims:,} |")
    L.append(f"| Providers | {n_providers} |")
    L.append(f"| Specialties | {df['specialty'].nunique()} |")
    L.append(f"| Distinct billing codes | {df['fee_code'].nunique()} |")
    L.append(f"| Date range | {df['service_date'].min().date()} → {df['service_date'].max().date()} |")
    L.append(f"| Providers with ≥1 evidence signal | {by_prov['provider_id'].nunique()} |")
    L.append(f"| **Total estimated extra revenue** | **${total_extra:,.0f}** |\n")
    L.append("_Dollar figures are estimates of revenue inflated above the specialty "
             "cohort baseline; methods can overlap, so per-provider totals are an "
             "upper-bound sum across detected schemes._\n")

    # ── Top providers ─────────────────────────────────────────────────────────
    L.append("## Top revenue-inflating providers\n")
    L.append("| Rank | Provider | Specialty | Est. extra revenue | # Schemes | Methods used |")
    L.append("|---:|---|---|---:|---:|---|")
    for i, (_, r) in enumerate(by_prov.head(25).iterrows(), 1):
        L.append(f"| {i} | `{r['provider_id']}` | {r['specialty']} | "
                 f"${r['total_extra']:,.0f} | {r['n_schemes']} | {r['schemes']} |")
    L.append("")

    # ── Per-scheme breakdown ──────────────────────────────────────────────────
    L.append("## Evidence by scheme\n")
    scheme_grp = (findings.groupby("scheme")
                          .agg(providers=("provider_id", "nunique"),
                               total=("estimated_extra_revenue", "sum"))
                          .sort_values("total", ascending=False))
    L.append("| Scheme | Providers | Est. extra revenue |")
    L.append("|---|---:|---:|")
    for scheme, r in scheme_grp.iterrows():
        L.append(f"| {scheme} | {int(r['providers'])} | ${r['total']:,.0f} |")
    L.append("")

    for scheme in scheme_grp.index:
        sub = findings[findings["scheme"] == scheme] \
                .sort_values("estimated_extra_revenue", ascending=False)
        L.append(f"### {scheme}\n")
        L.append(f"_{int(scheme_grp.loc[scheme, 'providers'])} provider(s), "
                 f"${scheme_grp.loc[scheme, 'total']:,.0f} estimated extra revenue._\n")
        for _, r in sub.head(6).iterrows():
            L.append(f"- **`{r['provider_id']}`** ({r['specialty']}) — "
                     f"${r['estimated_extra_revenue']:,.0f}, {int(r['support_claims'])} "
                     f"claims/events: {r['evidence']}")
        L.append("")

    # ── Validation vs ground truth ────────────────────────────────────────────
    if gt and "all_bad_actors" in gt:
        planted = set(gt["all_bad_actors"])
        detected = set(findings["provider_id"])
        hit = planted & detected
        L.append("## Detection vs planted ground truth\n")
        L.append(f"- Planted bad actors: **{len(planted)}**")
        L.append(f"- Detected (≥1 signal): **{len(hit)}/{len(planted)}** "
                 f"({len(hit)/len(planted):.0%} recall)")
        flagged_clean = detected - planted
        L.append(f"- Providers flagged that were NOT planted: **{len(flagged_clean)}** "
                 f"(expected — real cohorts contain naturally aggressive billers)")
        missed = planted - detected
        if missed:
            L.append(f"- Missed: {', '.join(sorted(missed))}")
        L.append("")

    L.append("## Method & caveats\n")
    L.append("- Each detector compares a provider to the **median of their own "
             "specialty cohort**, so high-acuity specialties are not penalised for "
             "billing high-value codes.")
    L.append("- Signals are **evidence for human review**, not automated "
             "determinations. Many have legitimate explanations (busy hospital "
             "readers, complex case-mix, locum schedules).")
    L.append("- Dollar estimates are deliberately conservative baselines for "
             "triage/prioritisation, not recovery amounts.")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="Mine claims for revenue-inflation evidence")
    ap.add_argument("--input", default=data_path("claims_large.csv"))
    ap.add_argument("--ground-truth", default=data_path("ground_truth_large.json"))
    ap.add_argument("--out-csv", default=data_path("fraud_evidence.csv"))
    ap.add_argument("--out-md", default=report_path("FRAUD_EVIDENCE_REPORT.md"))
    args = ap.parse_args()

    if not os.path.exists(args.input):
        raise SystemExit(f"Input not found: {args.input}. Run data_gen_large.py first.")

    print("Billing Revenue-Inflation Evidence Miner")
    print("=" * 64)
    df = load_claims(args.input)
    meta = provider_meta(df)
    print(f"  Loaded {len(df):,} claims · {df['provider_id'].nunique()} providers · "
          f"{df['specialty'].nunique()} specialties")

    all_rows = []
    for det in DETECTORS:
        rows = det(df, meta)
        all_rows.extend(rows)
        print(f"  {det.__name__:<28} {len(rows):>3} provider finding(s)")

    findings = pd.DataFrame(all_rows)
    if findings.empty:
        print("  No evidence signals found.")
        return
    findings = findings.sort_values("estimated_extra_revenue", ascending=False)
    findings.to_csv(args.out_csv, index=False)

    gt = None
    if os.path.exists(args.ground_truth):
        with open(args.ground_truth) as fh:
            gt = json.load(fh)

    report = build_report(df, findings, args.input, gt)
    with open(args.out_md, "w", encoding="utf-8") as fh:
        fh.write(report)

    total = findings["estimated_extra_revenue"].sum()
    print("-" * 64)
    print(f"  Findings           : {len(findings)} rows")
    print(f"  Providers flagged  : {findings['provider_id'].nunique()}")
    print(f"  Est. extra revenue : ${total:,.0f}")
    print(f"  Structured output  → {args.out_csv}")
    print(f"  Report             → {args.out_md}")
    if gt:
        planted = set(gt["all_bad_actors"]); detected = set(findings["provider_id"])
        hit = planted & detected
        print(f"  Ground-truth recall: {len(hit)}/{len(planted)} "
              f"({len(hit)/len(planted):.0%})")


if __name__ == "__main__":
    main()
