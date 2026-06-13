"""moh_audit.py — Ontario MOH (OHIP) Provider Audit Unit alignment layer.

Turns the system's statistical findings into artefacts that match the Ministry
of Health's *Physician Fee-for-Service Post-Payment Audit Process* (OHIP
Division, March 2021). It does three things the Provider Audit Unit does by
hand today:

  1. CLASSIFY each finding as a "Potential Billing Concern" and map it to the
     governing legislation — the Health Insurance Act (HIA) s.18(8)
     circumstances and the named examples in the process guide.

  2. CALCULATE the *statutorily recoverable* amount. The HSARB can only order
     repayment for a period (a) no longer than 24 months and (b) commencing no
     more than 5 years before the GM's review request. Raw "exposure" is not
     what gets recovered; this computes the defensible figure automatically.

  3. ASSEMBLE a GM's-Opinion-style case file per physician (in the ministry's
     own three-stage workflow, with the published SLA targets) so an auditor
     opens a ready dossier instead of a blank page.

Inputs (produced earlier in the pipeline):
    fraud_evidence.csv     per (provider, concern) findings + $ estimate
    claims_large.csv       claim-level table (for dates / amounts / recovery)

Outputs:
    MOH_AUDIT_CASEBOOK.md     ranked, GM-Opinion-style dossiers
    moh_recovery_summary.csv  structured per-provider recovery + pathway

NOTE: Synthetic data, decision-support only. Nothing here is a determination;
under the HIA only the GM forms an Opinion and only the HSARB can order recovery.
"""

import argparse
import os
import sys

# Make the section folders importable as flat modules regardless of CWD.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _sectionpath  # noqa: E402  (registers section folders on sys.path)

import pandas as pd

import fee_schedule as fs
from dataset_config import data_path, report_path

# ── Legislative framework (HIA s.18(8) circumstances) ─────────────────────────
# The six circumstances under which the GM may refer a matter to HSARB.
HIA_S18_8 = {
    "a": "All or part of the insured service was not in fact rendered.",
    "b": "The service was not rendered in accordance with the HIA and Regulations.",
    "c": "There is an absence of a record, as described in s.17.4 of the HIA.",
    "d": "The nature of the service is misrepresented, whether deliberately or inadvertently.",
    "e": "All or part of the service was not medically necessary (after consulting a physician).",
    "f": "The service was not provided in accordance with accepted professional standards.",
}

# Named "Potential Billing Concern" examples from the process guide.
PBC_NOT_RENDERED = "Billing for services which were apparently not rendered"
PBC_MORE_COMPLEX = "Billing for a more complex service than appears to have been performed"
PBC_MULTI_CODE   = "Billing multiple codes for a service described by one fee code"

# Statutory recovery limits (HIA / Schedule 1, HSARB).
RECOVERY_MAX_MONTHS = 24    # HSARB may order repayment over a period ≤ 24 months
RECOVERY_LOOKBACK_YEARS = 5  # ...commencing ≤ 5 years before the GM's review request

# Published process SLA targets (months), used for timeline guidance.
SLA = {
    "physician_ack_weeks":       2,    # confirm records will be provided
    "records_request_months":    (3, 6),
    "records_review_months":     (3, 6),
    "gm_opinion_months":         (1, 3),
    "total_target_months":       12,
}


# ── Concern taxonomy: detector finding → ministry classification ───────────────
# Each entry encodes how the Provider Audit Unit would frame the concern.
#   pbc                : which named example it matches
#   hia                 : applicable s.18(8) circumstance ids
#   evidence_basis      : "documentary" (provable from claims data alone) vs
#                         "clinical"    (needs medical records / necessity review)
#   needs_medical_consult: whether s.18(8)(e) requires consulting a physician
CONCERN_MAP = {
    "Impossible day (>24h billed)": {
        "pbc": PBC_NOT_RENDERED, "hia": ["a", "d"],
        "evidence_basis": "documentary", "needs_medical_consult": False,
        "note": "Aggregate billed service-minutes exceed the hours physically "
                "available in a day; at least part of the service cannot have been rendered.",
    },
    "Duplicate claim resubmission": {
        "pbc": PBC_NOT_RENDERED, "hia": ["a"],
        "evidence_basis": "documentary", "needs_medical_consult": False,
        "note": "Identical patient + fee code + date + units submitted more than once; "
                "the duplicate represents a service that was not separately rendered.",
    },
    "Phantom / excessive claim volume": {
        "pbc": PBC_NOT_RENDERED, "hia": ["a", "d"],
        "evidence_basis": "clinical", "needs_medical_consult": True,
        "note": "Daily claim volume far exceeds the specialty cohort; records review "
                "required to confirm the volume of services was actually rendered.",
    },
    "Upcoding (E/M complexity inflation)": {
        "pbc": PBC_MORE_COMPLEX, "hia": ["d", "e"],
        "evidence_basis": "clinical", "needs_medical_consult": True,
        "note": "Predominant use of top-tier E/M codes vs cohort; records review "
                "required to confirm the complexity billed matches work performed.",
    },
    "Psychotherapy time inflation": {
        "pbc": PBC_MORE_COMPLEX, "hia": ["d"],
        "evidence_basis": "clinical", "needs_medical_consult": True,
        "note": "Predominant billing of 60-minute psychotherapy; records review "
                "required to confirm session durations.",
    },
    "Escalating upcoding over time": {
        "pbc": PBC_MORE_COMPLEX, "hia": ["d"],
        "evidence_basis": "clinical", "needs_medical_consult": True,
        "note": "Top-tier code share trends sharply upward over the period — a "
                "change in billing behaviour warranting records review.",
    },
    "Unbundling component codes": {
        "pbc": PBC_MULTI_CODE, "hia": ["b", "d"],
        "evidence_basis": "documentary", "needs_medical_consult": False,
        "note": "Component codes billed separately where a single bundle code "
                "describes the service performed.",
    },
    "Modifier-25 separate-E/M abuse": {
        "pbc": PBC_MULTI_CODE, "hia": ["b", "d"],
        "evidence_basis": "clinical", "needs_medical_consult": True,
        "note": "A separately-payable E/M is repeatedly stacked onto same-day "
                "procedures; records review required to confirm a significant, "
                "separately identifiable service.",
    },
    "Unit / dosage inflation": {
        "pbc": PBC_MORE_COMPLEX, "hia": ["a", "d"],
        "evidence_basis": "clinical", "needs_medical_consult": True,
        "note": "Units billed on dose/time-based codes far exceed cohort norms; "
                "records review required to confirm units actually delivered.",
    },
    "Self-referral out-of-specialty imaging": {
        "pbc": PBC_MORE_COMPLEX, "hia": ["e", "f"],
        "evidence_basis": "clinical", "needs_medical_consult": True,
        "note": "High-value imaging billed outside the provider's specialty; "
                "medical-necessity and professional-standards review required.",
    },
    "Weekend / closed-office billing": {
        "pbc": PBC_NOT_RENDERED, "hia": ["a", "c"],
        "evidence_basis": "documentary", "needs_medical_consult": False,
        "note": "Material claim volume on days the practice is ordinarily closed; "
                "records review required to confirm services were rendered.",
    },
}

_DEFAULT_CONCERN = {
    "pbc": "Potential Billing Concern", "hia": ["b"],
    "evidence_basis": "clinical", "needs_medical_consult": True, "note": "",
}


def classify(scheme: str) -> dict:
    return CONCERN_MAP.get(scheme, _DEFAULT_CONCERN)


# ── Statutory recovery calculator ─────────────────────────────────────────────

def statutory_recovery(prov_claims: pd.DataFrame, inflation_ratio: float,
                       request_date: pd.Timestamp) -> dict:
    """Compute the legally recoverable amount under the HSARB 24-month / 5-year rule.

    Approach: within the 5-year lookback window, estimate suspect dollars per
    month (monthly billed × the provider's inflation ratio), then find the best
    contiguous window of length ≤ 24 months. Because suspect dollars are
    non-negative, the optimum is the 24 consecutive months (or the whole span,
    if shorter) with the greatest suspect total.
    """
    req = pd.Timestamp(request_date)
    lookback_start = req - pd.DateOffset(years=RECOVERY_LOOKBACK_YEARS)
    elig = prov_claims[(prov_claims["service_date"] >= lookback_start) &
                       (prov_claims["service_date"] <= req)]
    if elig.empty:
        return {"recoverable": 0.0, "window_start": None, "window_end": None,
                "months_in_window": 0, "outside_window": 0.0}

    monthly = (elig.set_index("service_date")["amount_billed"]
                   .resample("MS").sum())
    suspect = monthly * inflation_ratio
    total_suspect = float(suspect.sum())

    if len(suspect) <= RECOVERY_MAX_MONTHS:
        recoverable = total_suspect
        win_start, win_end, n_months = suspect.index[0], suspect.index[-1], len(suspect)
    else:
        roll = suspect.rolling(RECOVERY_MAX_MONTHS).sum()
        win_end = roll.idxmax()
        recoverable = float(roll.max())
        win_start = win_end - pd.DateOffset(months=RECOVERY_MAX_MONTHS - 1)
        n_months = RECOVERY_MAX_MONTHS

    return {
        "recoverable": round(recoverable, 2),
        "window_start": win_start.date().isoformat() if win_start is not None else None,
        "window_end": win_end.date().isoformat() if win_end is not None else None,
        "months_in_window": int(n_months),
        # the part of suspect billing the statute makes NON-recoverable (cap/lookback)
        "outside_window": round(max(0.0, total_suspect - recoverable), 2),
    }


# ── Recommended audit pathway (mirrors the ministry's decision tree) ───────────

def recommend_pathway(concerns: list, recoverable: float) -> dict:
    """Map findings to the ministry's three-stage outcomes.

    Stage 1 (Initial Action) is always complete once a preliminary claims-data
    review exists (this system). The recommendation is the *next* ministry step.
    """
    bases = {classify(c)["evidence_basis"] for c in concerns}
    has_documentary = "documentary" in bases
    high_value = recoverable >= 50_000

    if has_documentary and high_value:
        nxt = "Full Audit Review — issue Request for Records and Information letter"
        outcome = "Likely negotiated settlement or HSARB referral (documentary concern, material amount)"
    elif has_documentary:
        nxt = "Full Audit Review — request records for the flagged dates"
        outcome = "Billing education and/or negotiated settlement"
    elif high_value:
        nxt = "Full Audit Review — request records; engage medical consultant on necessity"
        outcome = "Billing education; settlement if records do not support claims"
    else:
        nxt = "Initial Action — billing education letter, then monitor future claims"
        outcome = "Education and close (no determination at this stage)"

    return {"next_step": nxt, "potential_outcome": outcome,
            "has_documentary": has_documentary}


# ── Case-file assembly ─────────────────────────────────────────────────────────

def _provider_totals(claims: pd.DataFrame) -> pd.DataFrame:
    g = claims.groupby("provider_id")
    return pd.DataFrame({
        "specialty": g["specialty"].first(),
        "total_billed": g["amount_billed"].sum(),
        "n_claims": g.size(),
    })


def build_casebook(findings: pd.DataFrame, claims: pd.DataFrame,
                   request_date: pd.Timestamp, top: int) -> tuple:
    totals = _provider_totals(claims)
    rows, md = [], []

    # Aggregate findings per provider
    per = (findings.groupby("provider_id")
                   .agg(specialty=("specialty", "first"),
                        exposure=("estimated_extra_revenue", "sum"),
                        concerns=("scheme", lambda s: list(s)))
                   .reset_index())

    # Compute statutory recovery per provider
    recs = []
    for _, r in per.iterrows():
        pid = r["provider_id"]
        tot_billed = float(totals.loc[pid, "total_billed"]) if pid in totals.index else 0.0
        ratio = min(1.0, r["exposure"] / tot_billed) if tot_billed > 0 else 0.0
        rec = statutory_recovery(claims[claims["provider_id"] == pid], ratio, request_date)
        path = recommend_pathway(r["concerns"], rec["recoverable"])
        recs.append({**r.to_dict(), "total_billed": round(tot_billed, 2),
                     "inflation_ratio": round(ratio, 4), **rec, **path})
    per_rec = pd.DataFrame(recs).sort_values("recoverable", ascending=False)

    # ── Header ────────────────────────────────────────────────────────────────
    total_exposure = per_rec["exposure"].sum()
    total_recoverable = per_rec["recoverable"].sum()
    defensible = fs.is_recovery_defensible()
    status = fs.figure_status()            # DEFENSIBLE | INDICATIVE
    rec_label = "Statutorily recoverable" if defensible \
        else "Statutorily recoverable (INDICATIVE)"
    md.append("# OHIP Provider Audit — Post-Payment Casebook\n")
    md.append("> **Decision-support, synthetic data.** Prepared to mirror the Ministry "
              "of Health *Physician Fee-for-Service Post-Payment Audit Process* (OHIP "
              "Division). No determination is made here — under the HIA only the OHIP "
              "General Manager forms an Opinion and only the HSARB can order recovery.\n")
    # ── Fee-schedule provenance gate ────────────────────────────────────────
    if not defensible:
        md.append(f"> ⚠ **{status} FIGURES — NOT FOR A GM'S OPINION.** "
                  f"{fs.status_detail()} Fee schedule in use: "
                  f"*{fs.provenance_label()}*. Replace with the authoritative "
                  f"Schedule of Benefits and validate against adjudicated outcomes "
                  f"before any dollar figure informs a determination (see docs/DEPLOY.md).\n")
    else:
        md.append(f"> ✅ **DEFENSIBLE FIGURES.** {fs.status_detail()} "
                  f"Fee schedule: *{fs.provenance_label()}*.\n")
    md.append("## Portfolio summary\n")
    md.append("| Metric | Value |\n|---|---|")
    md.append(f"| Physicians with a Potential Billing Concern | {len(per_rec)} |")
    md.append(f"| Total estimated billing exposure | ${total_exposure:,.0f} |")
    md.append(f"| **{rec_label} (HSARB 24-mo / 5-yr cap)** | **${total_recoverable:,.0f}** |")
    md.append(f"| Amount barred by statutory limits | ${per_rec['outside_window'].sum():,.0f} |")
    md.append(f"| Fee schedule | {fs.provenance_label()} |")
    md.append(f"| Figure status | {status} |")
    md.append(f"| Assumed GM review-request date | {pd.Timestamp(request_date).date()} |")
    md.append(f"| Target audit duration (ministry SLA) | < {SLA['total_target_months']} months |\n")
    md.append("_Recoverable amount applies HIA / Schedule 1: HSARB may order repayment "
              "over a period ≤ 24 months commencing ≤ 5 years before the review request. "
              "Exposure beyond that window is not recoverable and is excluded._\n")

    md.append("## Worklist — ranked by recoverable amount\n")
    md.append("| Rank | Physician | Specialty | Recoverable | Exposure | Concerns | Recommended next step |")
    md.append("|---:|---|---|---:|---:|---:|---|")
    for i, (_, r) in enumerate(per_rec.head(top).iterrows(), 1):
        md.append(f"| {i} | `{r['provider_id']}` | {r['specialty']} | "
                  f"${r['recoverable']:,.0f} | ${r['exposure']:,.0f} | "
                  f"{len(r['concerns'])} | {r['next_step']} |")
    md.append("")

    # ── Per-physician dossiers ─────────────────────────────────────────────────
    md.append("## Case files\n")
    fdf = findings.set_index("provider_id")
    for i, (_, r) in enumerate(per_rec.head(top).iterrows(), 1):
        pid = r["provider_id"]
        md.append(f"### {i}. `{pid}` — {r['specialty']}\n")
        md.append(f"- **Stage:** Initial Action complete (preliminary claims-data review).")
        md.append(f"- **Recommended next step:** {r['next_step']}")
        md.append(f"- **Potential outcome:** {r['potential_outcome']}")
        md.append(f"- **Estimated exposure:** ${r['exposure']:,.0f} · "
                  f"**Statutorily recoverable:** ${r['recoverable']:,.0f} "
                  f"(window {r['window_start']} → {r['window_end']}, "
                  f"{r['months_in_window']} months)")
        if r["outside_window"] > 0:
            md.append(f"- **Barred by 24-mo/5-yr limit:** ${r['outside_window']:,.0f}")
        md.append("\n**Potential Billing Concerns identified:**\n")
        sub = fdf.loc[[pid]] if pid in fdf.index else pd.DataFrame()
        for _, f in sub.iterrows():
            cls = classify(f["scheme"])
            hia = "; ".join(f"s.18(8)({k})" for k in cls["hia"])
            consult = " · medical consult required" if cls["needs_medical_consult"] else ""
            md.append(f"- **{f['scheme']}** — {cls['pbc']}.")
            md.append(f"  - _Evidence:_ {f['evidence']} "
                      f"(est. ${f['estimated_extra_revenue']:,.0f}, "
                      f"{int(f['support_claims'])} claims/events).")
            md.append(f"  - _Legal basis:_ {hia} — {cls['evidence_basis']} evidence{consult}.")
        md.append("")
        # records to request (Stage 2)
        needs_records = any(classify(c)["evidence_basis"] == "clinical" for c in r["concerns"])
        if needs_records:
            md.append("**Records to request (Stage 2):** medical records for the flagged "
                      "service dates to confirm services rendered, complexity, medical "
                      "necessity and documentation per s.17.4. Physician acknowledgement "
                      f"requested within {SLA['physician_ack_weeks']} weeks.\n")
        rows.append({
            "provider_id": pid, "specialty": r["specialty"],
            "n_concerns": len(r["concerns"]),
            "concerns": "; ".join(r["concerns"]),
            "estimated_exposure": round(r["exposure"], 2),
            "statutory_recoverable": r["recoverable"],
            "recovery_window_start": r["window_start"],
            "recovery_window_end": r["window_end"],
            "barred_by_statute": r["outside_window"],
            "hia_circumstances": "; ".join(sorted({k for c in r["concerns"]
                                                   for k in classify(c)["hia"]})),
            "needs_medical_consult": any(classify(c)["needs_medical_consult"]
                                         for c in r["concerns"]),
            "recommended_next_step": r["next_step"],
            "potential_outcome": r["potential_outcome"],
            # Provenance stamp travels with every recovery figure.
            "figure_status": status,
            "fee_schedule": fs.provenance_label(),
            "fee_schedule_authoritative": fs.is_authoritative(),
            "recovery_defensible": defensible,
        })

    return "\n".join(md), pd.DataFrame(rows)


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="MOH OHIP post-payment audit casebook")
    ap.add_argument("--findings", default=data_path("fraud_evidence.csv"))
    ap.add_argument("--claims", default=data_path("claims_large.csv"))
    ap.add_argument("--request-date", default=None,
                    help="GM review-request date (YYYY-MM-DD); default = last claim + 1 day")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--out-md", default=report_path("MOH_AUDIT_CASEBOOK.md"))
    ap.add_argument("--out-csv", default=data_path("moh_recovery_summary.csv"))
    args = ap.parse_args()

    for f in (args.findings, args.claims):
        if not os.path.exists(f):
            raise SystemExit(f"Missing {f}. Run data_gen_large.py and fraud_evidence.py first.")

    print("OHIP Provider Audit — Post-Payment Casebook Builder")
    print("=" * 64)
    print(f"  Fee schedule       : {fs.provenance_label()}")
    print(f"  Figure status      : {fs.figure_status()}")
    if not fs.is_recovery_defensible():
        print(f"  ⚠ {fs.status_detail()}")
    findings = pd.read_csv(args.findings, dtype={"provider_id": str})
    claims = pd.read_csv(args.claims, parse_dates=["service_date"],
                         dtype={"provider_id": str, "fee_code": str})

    request_date = (pd.Timestamp(args.request_date) if args.request_date
                    else claims["service_date"].max() + pd.Timedelta(days=1))
    print(f"  Findings           : {len(findings)} rows, "
          f"{findings['provider_id'].nunique()} physicians")
    print(f"  GM review-request  : {request_date.date()}  "
          f"(recovery window ≤ {RECOVERY_MAX_MONTHS} mo, lookback {RECOVERY_LOOKBACK_YEARS} yr)")

    md, summary = build_casebook(findings, claims, request_date, args.top)
    with open(args.out_md, "w", encoding="utf-8") as fh:
        fh.write(md)
    summary.to_csv(args.out_csv, index=False)

    print("-" * 64)
    print(f"  Total exposure     : ${summary['estimated_exposure'].sum():,.0f}")
    print(f"  Statutorily recoverable : ${summary['statutory_recoverable'].sum():,.0f}")
    print(f"  Barred by 24mo/5yr cap  : ${summary['barred_by_statute'].sum():,.0f}")
    print(f"  Casebook           → {args.out_md}")
    print(f"  Recovery summary   → {args.out_csv}")


if __name__ == "__main__":
    main()
