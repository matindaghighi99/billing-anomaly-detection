# Alignment with the MOH OHIP Post-Payment Audit Process

**Client:** Ontario Ministry of Health (MOH), OHIP Division — **Provider Audit Unit**
**Reference:** *The physician fee-for-service post-payment audit process* (OHIP Division / OMA, March 2021)
**Legislation:** Health Insurance Act (HIA) s.18 & Schedule 1; Regulation 552; Schedule of Benefits for Physician Services; HSARB Rules of Practice and Procedure.

This document maps the ministry's published process, principles, and legal
constraints to concrete capabilities in this system, so the Provider Audit Unit
can see — point by point — that the tool fits how they actually work. It also
states, honestly, where the current build is a demonstrator and what production
deployment requires.

> **Posture.** This is a **decision-support** tool for trained Provider Audit
> Unit staff. It makes **no determinations**. Consistent with the HIA, only the
> OHIP General Manager forms an Opinion, and only the HSARB can order recovery.
> All data in the demonstrator is **synthetic**.

---

## 1. The three-stage process → system support

The ministry conducts audits in three stages (Initial Action → Full Audit
Review → Board Hearing), targeting **< 12 months** end-to-end. The system is
built around that lifecycle.

| Ministry stage | What the ministry does | How the system supports it |
|---|---|---|
| **1. Initial Action** | A Potential Billing Concern (PBC) is identified (often via tips); the Provider Audit Unit performs an **impartial preliminary claims-data review** to understand the practice and assess merit. | This *is* the preliminary claims-data review: it ingests the full claims history and surfaces ranked PBCs with quantified, cohort-relative evidence — replacing weeks of manual data pulls. Selection is **impartial** (statistical, cohort-based) and **documented** (`fraud_evidence.py`, `FRAUD_EVIDENCE_REPORT.md`). |
| **2. Full Audit Review** | Request records → review records against HIA/Reg 552/Schedule of Benefits and medical necessity → prepare findings → physician written submission → **GM's Opinion**. | The system pre-assembles a **GM's-Opinion-style case file** per physician: the concern, its legal basis, the evidence, the records to request, and a recommended pathway — so the auditor opens a dossier, not a blank page (`moh_audit.py`, `MOH_AUDIT_CASEBOOK.md`). The dashboard records every auditor disposition (`confirm / clear / investigate`) to an immutable trail. |
| **3. Board Hearing (HSARB)** | The GM may refer to HSARB; recovery only by order (or settlement). | The system computes the **statutorily recoverable amount** the GM must be able to justify, and produces the per-concern evidence and legal mapping needed to *demonstrate at HSARB*. |

SLA targets from the guide (physician acknowledgement in **2 weeks**; records
request **3–6 months**; records review **3–6 months**; GM's Opinion **1–3
months**) are encoded in `moh_audit.SLA` and surfaced in each case file.

---

## 2. Potential Billing Concerns → HIA s.18(8) crosswalk

The guide names three example concerns and the six s.18(8) circumstances under
which the GM may refer to HSARB. Every detector is mapped to that framework
(`moh_audit.CONCERN_MAP`), so findings arrive in the ministry's own legal
language rather than as opaque "anomaly scores."

| System finding | Named PBC example | HIA s.18(8) | Evidence basis |
|---|---|---|---|
| Impossible day (>24h billed) | Services not rendered | (a),(d) | Documentary |
| Duplicate claim resubmission | Services not rendered | (a) | Documentary |
| Phantom / excessive volume | Services not rendered | (a),(d) | Clinical (records) |
| Upcoding (E/M complexity) | More complex than performed | (d),(e) | Clinical (records) |
| Psychotherapy time inflation | More complex than performed | (d) | Clinical (records) |
| Escalating upcoding over time | More complex than performed | (d) | Clinical (records) |
| Unbundling component codes | Multiple codes for one service | (b),(d) | Documentary |
| Modifier-25 separate-E/M abuse | Multiple codes for one service | (b),(d) | Clinical (records) |
| Unit / dosage inflation | More complex than performed | (a),(d) | Clinical (records) |
| Self-referral out-of-specialty imaging | More complex / necessity | (e),(f) | Clinical (records) |
| Weekend / closed-office billing | Services not rendered | (a),(c) | Documentary |

s.18(8): (a) not rendered · (b) not per HIA/Regs · (c) absence of record (s.17.4)
· (d) misrepresented · (e) not medically necessary · (f) not per professional standards.

"Documentary" concerns are provable from claims data alone; "clinical" concerns
**require a records review and, where (e) applies, consultation with a
physician** — the system flags exactly which, so staff know when to engage a
medical consultant.

---

## 3. Governing principles → controls

The guide requires procedural fairness, integrity, transparency, and
accountability. Each maps to a built control:

| Principle (guide) | Control in the system |
|---|---|
| **Impartial selection** of physicians | Cohort-relative statistical selection; every physician scored on the same criteria; no manual targeting. A fairness audit (`fairness.py`) checks for over-flagging by specialty/clinic. |
| **Trained staff / quality assurance** | Tool augments, never replaces, trained auditors; explainable evidence (SHAP, `explain.py`) supports QA review. |
| **Ability to dispute; recover only by order** | The system never recovers or penalises; it produces evidence for the GM and HSARB. Recovery figures are clearly labelled as *potential*, capped by statute (§5). |
| **GM must demonstrate at HSARB** | Each finding ships with its legal basis and supporting claim-level evidence — the demonstrable record the GM needs. |
| **Privacy & confidentiality** | Displayed explanations carry calibrated privacy noise (`privacy.py`); role-based access gates the model card and audit trail; audit data is not externally released. |
| **Timely communication & full info to GM** | Case files consolidate everything for the physician letter and the GM's Opinion; SLA timers track the < 12-month target. |
| **Accountability / integrity** | Append-only, SHA-256 hash-chained audit trail of every flag, view, and action (`audit_log.py`), with a tamper-verification function. |

---

## 4. Referrals

The guide allows referral to CPSO (professional misconduct / patient safety),
the **OPP Health Fraud Investigation Unit** (suspected fraud), and other program
areas. The case file's concern classification and evidence basis give auditors
the structured starting point for those referral packages. (Automated referral
routing is on the roadmap — §7.)

---

## 5. The statutory recovery engine — where the millions are saved

Raw "exposure" is **not** what the ministry can recover. Under the HIA /
Schedule 1, the HSARB may order repayment only for a period **(a) no longer than
24 months** and **(b) commencing no more than 5 years before the GM's review
request**. Hand-calculating the optimal, defensible window across years of
claims is slow and error-prone.

`moh_audit.statutory_recovery()` computes it automatically: within the 5-year
lookback it finds the contiguous ≤24-month window with the greatest suspect
billing, and reports both the **recoverable amount** and the amount **barred by
the statutory limit**. This:

- gives the GM a **defensible** figure to take to settlement or HSARB (not an
  inflated number a physician's counsel can dismantle);
- prevents wasted effort pursuing time-barred amounts;
- generalises to real multi-year data (verified: a 36-month series correctly
  caps to its best 24 months; data older than 5 years correctly returns $0).

In the synthetic demonstrator (24 months of data) the cap is naturally
non-binding, so recoverable = exposure; on real multi-year histories the engine
does the limiting automatically.

---

## 6. What should surprise the Provider Audit Unit

1. **Findings already in their language** — PBCs mapped to s.18(8), not "scores."
2. **A pre-drafted GM's-Opinion-style case file per physician**, ranked by *recoverable* dollars, with the records to request and the recommended next step.
3. **The statutory recovery calculation done for them**, defensibly, in seconds.
4. **Impartiality and defensibility built in** — cohort-relative selection, explainability, a fairness audit, and a tamper-evident trail that stands up at HSARB.
5. **Proactive discovery** — surfaces concerns beyond tips/complaints (today the majority of their leads), expanding coverage without adding headcount.

---

## 7. Honest gaps & path to production

A ministry buyer should trust the vendor who names the gaps. To move from this
demonstrator to a production deployment handling real OHIP data:

- **Identity & access:** replace the mock auth with the ministry SSO/IdP (SAML/OAuth), MFA, session expiry, and full auth-event logging. *(Tracked in the security review.)*
- **Schedule of Benefits ingestion:** load the authoritative Reg 552 / Schedule of Benefits fee rules and bundle/eligibility logic (the demo uses a representative subset).
- **Records & correspondence workflow:** integrate records intake, the 2-week acknowledgement, extension tracking, physician written submissions, and letter generation; persist case state across the three stages.
- **Referral routing:** structured CPSO / OPP / program-area referral packages.
- **Privacy & residency:** Ontario data-residency, PHIPA alignment, formal privacy-budget management (the demo's noise is demo-grade, clearly labelled).
- **Validation:** clinical/medical-consultant review loop and accuracy validation against adjudicated outcomes before any figure informs a GM's Opinion.

---

## 8. Try it

```bash
python data_gen_large.py     # synthetic claims (15 specialties, 2 years)
python fraud_evidence.py     # discover Potential Billing Concerns + evidence
python moh_audit.py          # build the MOH-aligned casebook + recovery summary
```

Outputs: `FRAUD_EVIDENCE_REPORT.md`, `MOH_AUDIT_CASEBOOK.md`, `moh_recovery_summary.csv`.

---

*This educational/demonstration resource does not replace the Health Insurance
Act, its Regulations, or the Schedule of Benefits, which are the definitive
authorities. All providers and claims in the demonstrator are fictional.*
