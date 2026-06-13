"""fee_schedule.py — Authoritative-aware fee schedule with provenance.

The Ontario Schedule of Benefits for Physician Services (under Regulation 552
of the Health Insurance Act) is the *authoritative* source of fee codes and
amounts. This system must never present a dollar figure derived from a
stand-in schedule as if it were defensible in a GM's Opinion or at HSARB.

This module makes the fee schedule a REPLACEABLE, VERSIONED, PROVENANCE-STAMPED
data source:

  • The schedule is loaded from a CSV (FEE_SCHEDULE_CSV) — not hardcoded — so an
    export of the real Schedule of Benefits can be dropped in without code
    changes (same columns: fee_code, description, amount, tier, minutes).
  • Sidecar metadata (FEE_SCHEDULE_META) records source / version /
    effective_date / authoritative, and travels with every recovery figure.
  • Recovery figures are "defensible" (usable to inform a GM's Opinion) ONLY
    when the schedule is authoritative AND has been validated against
    adjudicated outcomes (RECOVERY_VALIDATED=1). Otherwise they are explicitly
    labelled INDICATIVE everywhere they appear.

Default ships a synthetic DEMO subset clearly marked authoritative=false.

To go authoritative:
  1. Replace fee_schedule.csv with a Schedule of Benefits export (same columns).
  2. Set fee_schedule_meta.json: {"authoritative": true, "version": "...",
     "effective_date": "YYYY-MM-DD", "source": "Schedule of Benefits ..."}.
  3. After validating recovery against adjudicated outcomes, set
     RECOVERY_VALIDATED=1 in the environment.
"""

import json
import os

import pandas as pd

FEE_SCHEDULE_CSV  = os.environ.get("FEE_SCHEDULE_CSV", "fee_schedule.csv")
FEE_SCHEDULE_META = os.environ.get("FEE_SCHEDULE_META", "fee_schedule_meta.json")

# Recovery figures may inform a GM's Opinion only after validation against
# adjudicated outcomes. Off by default — figures are indicative until proven.
RECOVERY_VALIDATED = os.environ.get("RECOVERY_VALIDATED", "").strip().lower() \
    in ("1", "true", "yes")

_DEFAULT_META = {
    "source": "synthetic_demo",
    "description": "Representative DEMO fee subset — NOT the authoritative "
                   "Ontario Schedule of Benefits (Regulation 552).",
    "version": "demo",
    "effective_date": None,
    "authoritative": False,
}

_schedule_cache = None
_meta_cache = None


def get_meta() -> dict:
    """Provenance metadata for the active fee schedule."""
    global _meta_cache
    if _meta_cache is not None:
        return _meta_cache
    meta = dict(_DEFAULT_META)
    if os.path.exists(FEE_SCHEDULE_META):
        try:
            with open(FEE_SCHEDULE_META) as fh:
                meta.update(json.load(fh))
        except (json.JSONDecodeError, OSError):
            pass
    _meta_cache = meta
    return meta


def get_schedule() -> dict:
    """Return {fee_code: {description, amount, tier, minutes}}.

    Loads FEE_SCHEDULE_CSV; falls back to the bundled demo schedule (marked
    non-authoritative) if the CSV is absent, so the pipeline never hard-fails.
    """
    global _schedule_cache
    if _schedule_cache is not None:
        return _schedule_cache
    if os.path.exists(FEE_SCHEDULE_CSV):
        df = pd.read_csv(FEE_SCHEDULE_CSV, dtype={"fee_code": str})
        sched = {}
        for _, r in df.iterrows():
            sched[str(r["fee_code"])] = {
                "desc": r.get("description", ""),
                "amount": float(r["amount"]),
                "tier": int(r["tier"]) if not pd.isna(r.get("tier")) else 0,
                "minutes": int(r["minutes"]) if not pd.isna(r.get("minutes")) else 0,
            }
    else:
        from data_gen_large import FEE_SCHEDULE as _demo
        sched = dict(_demo)
    _schedule_cache = sched
    return sched


def amount(fee_code: str):
    """Authoritative amount for a fee code, or None if not in the schedule."""
    rec = get_schedule().get(str(fee_code))
    return rec["amount"] if rec else None


def is_authoritative() -> bool:
    """True only when the loaded schedule is the real Schedule of Benefits."""
    return bool(get_meta().get("authoritative", False))


def is_recovery_defensible() -> bool:
    """Recovery figures may inform a GM's Opinion only when the schedule is
    authoritative AND recovery has been validated against adjudicated outcomes."""
    return is_authoritative() and RECOVERY_VALIDATED


def provenance_label() -> str:
    """Human-readable one-line provenance for the active schedule."""
    m = get_meta()
    if is_authoritative():
        eff = f" effective {m['effective_date']}" if m.get("effective_date") else ""
        return f"{m.get('source', 'Schedule of Benefits')} v{m.get('version', '?')}{eff}"
    return f"{m.get('source', 'demo')} ({m.get('version', 'demo')}) — NOT authoritative"


def figure_status() -> str:
    """'DEFENSIBLE' or 'INDICATIVE' — stamps every recovery/exposure figure."""
    return "DEFENSIBLE" if is_recovery_defensible() else "INDICATIVE"


def status_detail() -> str:
    """Why figures are/aren't defensible — for banners and disclaimers."""
    if is_recovery_defensible():
        return ("Figures are derived from the authoritative Schedule of Benefits "
                "and validated against adjudicated outcomes.")
    reasons = []
    if not is_authoritative():
        reasons.append("a demonstration fee schedule (not the authoritative "
                       "Schedule of Benefits / Regulation 552)")
    if not RECOVERY_VALIDATED:
        reasons.append("recovery has not been validated against adjudicated outcomes")
    return ("INDICATIVE ONLY — based on " + " and ".join(reasons) +
            ". Not for use in a GM's Opinion or HSARB referral.")
