"""data_gen_large.py — Expanded synthetic physician-billing generator.

A bigger, richer sibling of data_gen.py:

  • 15 specialties (was 6)              — "more doctor types"
  • ~69 distinct CPT-style fee codes    — "more different claims"
  • 2 calendar years (2023-2024)        — enables temporal escalation patterns
  • ~300 providers by default           — ~3-4x more claims than the base set
  • 11 distinct revenue-inflation       — "ways doctors make more money"
    schemes planted as known bad actors

It writes a SEPARATE dataset so the original curated demo (claims.csv +
ground_truth.json + validate_baseline.json + tests) is left untouched:

    claims_large.csv          full claim table (one row per claim)
    ground_truth_large.json   planted scheme → provider-id map

Deterministic given --seed, so the dataset (and the evidence report built from
it by fraud_evidence.py) is fully reproducible.

USAGE
    python data_gen_large.py                      # defaults (300 providers, 2yr)
    python data_gen_large.py --providers 500
    python data_gen_large.py --start-year 2024 --end-year 2024
"""

import argparse
import json
import math
import random
from datetime import date, timedelta

import numpy as np
import pandas as pd
from faker import Faker

DEFAULT_SEED = 1337

OUTPUT_CSV        = "claims_large.csv"
GROUND_TRUTH_JSON = "ground_truth_large.json"


# ── Fee schedule (~69 codes) ──────────────────────────────────────────────────
# minutes = typical service duration; amount = list price; tier = complexity rank.
FEE_SCHEDULE = {
    # Evaluation & Management — established patient
    "99211": {"desc": "Office Visit Minimal",          "minutes": 5,   "amount": 25.00,   "tier": 1},
    "99212": {"desc": "Office Visit Limited",           "minutes": 10,  "amount": 55.00,   "tier": 1},
    "99213": {"desc": "Office Visit Brief",             "minutes": 15,  "amount": 85.00,   "tier": 1},
    "99214": {"desc": "Office Visit Moderate",          "minutes": 25,  "amount": 130.00,  "tier": 2},
    "99215": {"desc": "Office Visit Complex",           "minutes": 40,  "amount": 200.00,  "tier": 3},
    # E&M — new patient
    "99202": {"desc": "New Patient Limited",            "minutes": 10,  "amount": 75.00,   "tier": 1},
    "99203": {"desc": "New Patient Low",                "minutes": 20,  "amount": 120.00,  "tier": 2},
    "99204": {"desc": "New Patient Moderate",           "minutes": 40,  "amount": 190.00,  "tier": 3},
    "99205": {"desc": "New Patient High",               "minutes": 60,  "amount": 260.00,  "tier": 3},
    # Hospital / inpatient
    "99221": {"desc": "Initial Hospital Care Low",      "minutes": 30,  "amount": 150.00,  "tier": 2},
    "99223": {"desc": "Initial Hospital Care High",     "minutes": 50,  "amount": 230.00,  "tier": 3},
    "99232": {"desc": "Subsequent Hospital Care",       "minutes": 20,  "amount": 110.00,  "tier": 2},
    "99233": {"desc": "Subsequent Hospital Care High",  "minutes": 35,  "amount": 160.00,  "tier": 3},
    # Emergency
    "99283": {"desc": "ER Visit Moderate",              "minutes": 30,  "amount": 130.00,  "tier": 2},
    "99284": {"desc": "ER Visit High",                  "minutes": 45,  "amount": 210.00,  "tier": 3},
    "99285": {"desc": "ER Visit Critical",              "minutes": 60,  "amount": 320.00,  "tier": 3},
    # Cardiology
    "93000": {"desc": "ECG Complete",                   "minutes": 20,  "amount": 70.00,   "tier": 2},
    "93005": {"desc": "ECG Tracing Only",               "minutes": 10,  "amount": 35.00,   "tier": 1},
    "93010": {"desc": "ECG Interpretation Only",        "minutes": 10,  "amount": 45.00,   "tier": 1},
    "93306": {"desc": "Echocardiogram Complete",        "minutes": 45,  "amount": 300.00,  "tier": 3},
    "93350": {"desc": "Stress Echocardiogram",          "minutes": 60,  "amount": 420.00,  "tier": 3},
    "93458": {"desc": "Cardiac Catheterization",        "minutes": 90,  "amount": 1500.00, "tier": 3},
    # Radiology
    "72148": {"desc": "MRI Lumbar Spine",               "minutes": 45,  "amount": 350.00,  "tier": 3},
    "70553": {"desc": "MRI Brain w/ Contrast",          "minutes": 60,  "amount": 450.00,  "tier": 3},
    "74177": {"desc": "CT Abdomen/Pelvis w/ Contrast",  "minutes": 40,  "amount": 400.00,  "tier": 3},
    "71250": {"desc": "CT Chest",                       "minutes": 30,  "amount": 300.00,  "tier": 3},
    "73721": {"desc": "MRI Lower Extremity Joint",      "minutes": 45,  "amount": 340.00,  "tier": 3},
    "76700": {"desc": "Abdominal Ultrasound",           "minutes": 25,  "amount": 180.00,  "tier": 2},
    # Psychiatry
    "90791": {"desc": "Psychiatric Diagnostic Eval",    "minutes": 60,  "amount": 220.00,  "tier": 3},
    "90832": {"desc": "Psychotherapy 30 min",           "minutes": 30,  "amount": 90.00,   "tier": 1},
    "90834": {"desc": "Psychotherapy 45 min",           "minutes": 45,  "amount": 140.00,  "tier": 2},
    "90837": {"desc": "Psychotherapy 60 min",           "minutes": 60,  "amount": 180.00,  "tier": 3},
    "90853": {"desc": "Group Psychotherapy",            "minutes": 60,  "amount": 60.00,   "tier": 1},
    # Dermatology
    "11100": {"desc": "Skin Biopsy First Lesion",       "minutes": 20,  "amount": 150.00,  "tier": 2},
    "11101": {"desc": "Skin Biopsy Additional Lesion",  "minutes": 10,  "amount": 75.00,   "tier": 1},
    "17000": {"desc": "Destruction Lesion First",       "minutes": 15,  "amount": 120.00,  "tier": 2},
    "17003": {"desc": "Destruction Lesion 2-14",        "minutes": 5,   "amount": 30.00,   "tier": 1},
    "96372": {"desc": "Therapeutic Injection",          "minutes": 10,  "amount": 40.00,   "tier": 1},
    # Orthopedic surgery
    "27447": {"desc": "Total Knee Replacement",         "minutes": 120, "amount": 1200.00, "tier": 3},
    "29881": {"desc": "Knee Arthroscopy",               "minutes": 90,  "amount": 900.00,  "tier": 3},
    "20610": {"desc": "Major Joint Injection",          "minutes": 15,  "amount": 120.00,  "tier": 2},
    "73564": {"desc": "Knee X-Ray",                     "minutes": 10,  "amount": 60.00,   "tier": 1},
    # General surgery
    "43239": {"desc": "Upper GI Endoscopy w/ Biopsy",   "minutes": 30,  "amount": 380.00,  "tier": 3},
    "45380": {"desc": "Colonoscopy w/ Biopsy",          "minutes": 45,  "amount": 500.00,  "tier": 3},
    "47562": {"desc": "Laparoscopic Cholecystectomy",   "minutes": 120, "amount": 1400.00, "tier": 3},
    "49505": {"desc": "Inguinal Hernia Repair",         "minutes": 90,  "amount": 900.00,  "tier": 3},
    # Gastroenterology
    "45378": {"desc": "Colonoscopy Diagnostic",         "minutes": 40,  "amount": 420.00,  "tier": 3},
    "43235": {"desc": "Upper Endoscopy Diagnostic",     "minutes": 25,  "amount": 320.00,  "tier": 3},
    "91110": {"desc": "Capsule Endoscopy",              "minutes": 30,  "amount": 700.00,  "tier": 3},
    # Ophthalmology
    "92014": {"desc": "Eye Exam Comprehensive",         "minutes": 30,  "amount": 140.00,  "tier": 2},
    "66984": {"desc": "Cataract Surgery",               "minutes": 60,  "amount": 1100.00, "tier": 3},
    "92134": {"desc": "OCT Retina Imaging",             "minutes": 15,  "amount": 80.00,   "tier": 1},
    "67028": {"desc": "Intravitreal Injection",         "minutes": 20,  "amount": 250.00,  "tier": 3},
    # OB/GYN
    "59400": {"desc": "Routine Obstetric Care (Global)","minutes": 180, "amount": 2500.00, "tier": 3},
    "58300": {"desc": "IUD Insertion",                  "minutes": 20,  "amount": 150.00,  "tier": 2},
    "57454": {"desc": "Colposcopy w/ Biopsy",           "minutes": 30,  "amount": 260.00,  "tier": 3},
    # Neurology
    "95910": {"desc": "Nerve Conduction Study",         "minutes": 60,  "amount": 400.00,  "tier": 3},
    "95816": {"desc": "Electroencephalogram (EEG)",     "minutes": 60,  "amount": 300.00,  "tier": 3},
    "64483": {"desc": "Epidural Steroid Injection",     "minutes": 30,  "amount": 350.00,  "tier": 3},
    # Anesthesiology
    "00790": {"desc": "Anesthesia Upper Abdomen",       "minutes": 60,  "amount": 500.00,  "tier": 3},
    "00810": {"desc": "Anesthesia Lower Intestinal",    "minutes": 45,  "amount": 400.00,  "tier": 3},
    "01402": {"desc": "Anesthesia Knee",                "minutes": 90,  "amount": 600.00,  "tier": 3},
    # Endocrinology
    "95251": {"desc": "CGM Interpretation",             "minutes": 20,  "amount": 120.00,  "tier": 2},
    "83036": {"desc": "Hemoglobin A1c",                 "minutes": 5,   "amount": 30.00,   "tier": 1},
    # Pulmonology
    "94010": {"desc": "Spirometry",                     "minutes": 20,  "amount": 110.00,  "tier": 2},
    "94060": {"desc": "Bronchodilator Responsiveness",  "minutes": 30,  "amount": 160.00,  "tier": 2},
    "31628": {"desc": "Bronchoscopy w/ Biopsy",         "minutes": 45,  "amount": 650.00,  "tier": 3},
    # Oncology
    "96413": {"desc": "Chemotherapy Infusion 1st Hr",   "minutes": 60,  "amount": 350.00,  "tier": 3},
    "96415": {"desc": "Chemotherapy Infusion Add'l Hr", "minutes": 60,  "amount": 150.00,  "tier": 2},
}

# Unbundling: billing both components separately instead of the bundle inflates pay.
BUNDLE_RULES = [
    {"components": frozenset({"93005", "93010"}), "bundle_code": "93000",
     "bundle_desc": "ECG Complete", "bundle_amt": 70.00},
]

# Codes whose units are legitimately billed >1 (time/dose based) — used to make
# unit-inflation fraud blend in with normal multi-unit billing.
UNIT_BILLABLE = {"96413", "96415", "96372", "67028", "17003"}


# ── Specialties (15) ──────────────────────────────────────────────────────────
# code list per specialty; weights derived automatically (cheaper codes more
# common) so that an upcoder who flips to top-tier codes stands out cleanly.
SPECIALTY_CODES = {
    "Family Medicine":     ["99212", "99213", "99214", "99215", "99203", "99204", "96372"],
    "Internal Medicine":   ["99213", "99214", "99215", "99232", "99233", "83036"],
    "Cardiology":          ["93000", "99214", "99215", "93306", "93350", "93458", "93005", "93010"],
    "Radiology":           ["72148", "70553", "74177", "71250", "73721", "76700"],
    "Psychiatry":          ["90791", "90832", "90834", "90837", "90853", "99214"],
    "Dermatology":         ["11100", "11101", "17000", "17003", "99213", "99214", "96372"],
    "Orthopedic Surgery":  ["27447", "29881", "20610", "73564", "99214", "99204"],
    "General Surgery":     ["43239", "45380", "47562", "49505", "99223", "99233"],
    "Gastroenterology":    ["45378", "43235", "91110", "43239", "99214"],
    "Ophthalmology":       ["92014", "66984", "92134", "67028"],
    "OB/GYN":              ["59400", "58300", "57454", "99213", "99214"],
    "Neurology":           ["95910", "95816", "64483", "99214", "99215"],
    "Emergency Medicine":  ["99283", "99284", "99285", "93005"],
    "Endocrinology":       ["99214", "99215", "95251", "83036"],
    "Pulmonology":         ["94010", "94060", "31628", "99214", "99232"],
}

# Average claims per provider per working day, by specialty.
SPECIALTY_DAILY = {
    "Family Medicine": 2.4, "Internal Medicine": 2.2, "Cardiology": 1.8,
    "Radiology": 2.6, "Psychiatry": 1.5, "Dermatology": 2.2,
    "Orthopedic Surgery": 1.2, "General Surgery": 1.0, "Gastroenterology": 1.4,
    "Ophthalmology": 2.0, "OB/GYN": 1.6, "Neurology": 1.5,
    "Emergency Medicine": 2.8, "Endocrinology": 1.8, "Pulmonology": 1.6,
}

SPECIALTY_NAMES = list(SPECIALTY_CODES.keys())


def _build_specialty_profiles() -> dict:
    """Derive per-specialty weight vectors + top-tier code list from the fee schedule."""
    profiles = {}
    for spec, codes in SPECIALTY_CODES.items():
        amts = np.array([FEE_SCHEDULE[c]["amount"] for c in codes], dtype=float)
        # cheaper codes are more common: weight ∝ 1/sqrt(amount)
        w = 1.0 / np.sqrt(amts)
        w /= w.sum()
        # top-tier codes = tier-3 codes, or the single priciest if none are tier 3
        tier3 = [c for c in codes if FEE_SCHEDULE[c]["tier"] == 3]
        if not tier3:
            tier3 = [max(codes, key=lambda c: FEE_SCHEDULE[c]["amount"])]
        profiles[spec] = {
            "codes": codes,
            "weights": w,
            "avg_daily_claims": SPECIALTY_DAILY[spec],
            "top_tier_codes": tier3,
        }
    return profiles


SPECIALTIES = _build_specialty_profiles()


# ── Calendar ──────────────────────────────────────────────────────────────────

def _working_days(start_year: int, end_year: int):
    days, weekends = [], []
    d = date(start_year, 1, 1)
    end = date(end_year, 12, 31)
    while d <= end:
        (days if d.weekday() < 5 else weekends).append(d)
        d += timedelta(days=1)
    return days, weekends


# ── Claim factory ─────────────────────────────────────────────────────────────

def _make_claim(provider: dict, day, code: str, rng, *, units: int = 1,
                modifier: str = "") -> dict:
    fee = FEE_SCHEDULE[code]
    unit_price = round(fee["amount"] * rng.uniform(0.95, 1.05), 2)
    return {
        "provider_id":     provider["provider_id"],
        "provider_name":   provider["provider_name"],
        "specialty":       provider["specialty"],
        "patient_id":      f"PAT{rng.integers(1, 200_001):06d}",
        "service_date":    day,
        "fee_code":        code,
        "fee_description": fee["desc"],
        "service_minutes": fee["minutes"],
        "units":           units,
        "amount_billed":   round(unit_price * units, 2),
        "modifier":        modifier,
        "clinic_id":       provider["clinic_id"],
    }


# ── Provider + base-claim generation ──────────────────────────────────────────

def make_providers(n_providers: int, n_clinics: int, fake, rng) -> list:
    # weight specialties: primary care more common than niche surgical fields
    spec_weights = np.array([SPECIALTIES[s]["avg_daily_claims"] for s in SPECIALTY_NAMES])
    spec_weights = spec_weights / spec_weights.sum()
    specs   = rng.choice(SPECIALTY_NAMES, size=n_providers, p=spec_weights)
    clinics = rng.integers(1, n_clinics + 1, size=n_providers)
    return [
        {
            "provider_id":   f"PRV{i+1:04d}",
            "provider_name": fake.name(),
            "specialty":     str(specs[i]),
            "clinic_id":     f"CLN{int(clinics[i]):03d}",
        }
        for i in range(n_providers)
    ]


def generate_base_claims(providers, working_days, rng) -> list:
    claims = []
    n_wd = len(working_days)
    for prov in providers:
        spec    = SPECIALTIES[prov["specialty"]]
        codes   = spec["codes"]
        weights = spec["weights"]
        avg     = spec["avg_daily_claims"]

        n_days   = int(n_wd * rng.uniform(0.55, 0.78))
        day_idxs = rng.choice(n_wd, size=n_days, replace=False)
        for di in day_idxs:
            day = working_days[di]
            n = max(1, int(rng.normal(avg, avg * 0.35)))
            for _ in range(n):
                code = str(rng.choice(codes, p=weights))
                claims.append(_make_claim(prov, day, code, rng))
    return claims


def _index_by_provider(claims) -> dict:
    """Map provider_id -> list of indices into `claims` (built once, O(n))."""
    idx = {}
    for i, c in enumerate(claims):
        idx.setdefault(c["provider_id"], []).append(i)
    return idx


# ════════════════════════════════════════════════════════════════════════════
#  REVENUE-INFLATION SCHEMES  ("how doctors make more money")
#  Each planter mutates/extends `claims` for the given provider ids and returns
#  nothing; ground-truth tagging happens in main().
# ════════════════════════════════════════════════════════════════════════════

def plant_upcoding(pmap, claims, pidx, ids, rng):
    """Bill the highest-complexity code regardless of actual work done."""
    for pid in ids:
        top = SPECIALTIES[pmap[pid]["specialty"]]["top_tier_codes"]
        for i in pidx[pid]:
            if rng.random() < 0.80:
                code = str(rng.choice(top))
                fee  = FEE_SCHEDULE[code]
                c = claims[i]
                c["fee_code"]        = code
                c["fee_description"] = fee["desc"]
                c["service_minutes"] = fee["minutes"]
                c["amount_billed"]   = round(fee["amount"] * rng.uniform(0.95, 1.05), 2)


def plant_psych_time_inflation(pmap, claims, pidx, ids, rng):
    """Psychiatrists billing 60-min therapy (90837) for routine shorter sessions."""
    for pid in ids:
        for i in pidx[pid]:
            c = claims[i]
            if c["fee_code"] in ("90832", "90834") and rng.random() < 0.85:
                fee = FEE_SCHEDULE["90837"]
                c["fee_code"]        = "90837"
                c["fee_description"] = fee["desc"]
                c["service_minutes"] = fee["minutes"]
                c["amount_billed"]   = round(fee["amount"] * rng.uniform(0.95, 1.05), 2)


def plant_unbundling(pmap, claims, pidx, ids, rng, working_days):
    """Replace ECG-complete with separately-billed components + add extra events."""
    extras = []
    for pid in ids:
        prov = pmap[pid]
        for i in pidx[pid]:
            c = claims[i]
            if c["fee_code"] == "93000":
                c["fee_code"]        = "93005"
                c["fee_description"] = FEE_SCHEDULE["93005"]["desc"]
                c["service_minutes"] = FEE_SCHEDULE["93005"]["minutes"]
                c["amount_billed"]   = round(FEE_SCHEDULE["93005"]["amount"] * rng.uniform(0.95, 1.05), 2)
                comp = _make_claim(prov, c["service_date"], "93010", rng)
                comp["patient_id"] = c["patient_id"]
                extras.append(comp)
        # add fresh unbundled pairs on random days
        for _ in range(40):
            day = working_days[int(rng.integers(0, len(working_days)))]
            pat = f"PAT{rng.integers(1, 200_001):06d}"
            for code in ("93005", "93010"):
                cl = _make_claim(prov, day, code, rng)
                cl["patient_id"] = pat
                extras.append(cl)
    claims.extend(extras)


def plant_duplicates(pmap, claims, pidx, ids, rng):
    """Resubmit ~15% of a provider's claims verbatim (paid twice)."""
    extras = []
    for pid in ids:
        idxs = pidx[pid]
        n = min(max(1, int(len(idxs) * 0.15)), len(idxs))
        for i in rng.choice(idxs, size=n, replace=False):
            extras.append(claims[int(i)].copy())
    claims.extend(extras)


def plant_impossible_days(pmap, claims, pidx, ids, rng):
    """Push total billed service-minutes past 1 440 (a 24h day) on several days."""
    for pid in ids:
        prov = pmap[pid]
        by_day = {}
        for i in pidx[pid]:
            by_day.setdefault(claims[i]["service_date"], 0)
            by_day[claims[i]["service_date"]] += claims[i]["service_minutes"]
        days = sorted(by_day)
        if not days:
            continue
        chosen = rng.choice(len(days), size=min(6, len(days)), replace=False)
        for di in chosen:
            day = days[int(di)]
            needed = 1_500 - by_day[day]
            while needed > 0:
                claims.append(_make_claim(prov, day, "99215", rng))
                needed -= FEE_SCHEDULE["99215"]["minutes"]


def plant_phantom_volume(pmap, claims, pidx, ids, rng):
    """Add 18-28 extra claims on every day the provider already bills."""
    extras = []
    for pid in ids:
        prov  = pmap[pid]
        spec  = SPECIALTIES[prov["specialty"]]
        codes, wts = spec["codes"], spec["weights"]
        days = sorted({claims[i]["service_date"] for i in pidx[pid]})
        for day in days:
            for _ in range(int(rng.integers(18, 29))):
                extras.append(_make_claim(prov, day, str(rng.choice(codes, p=wts)), rng))
    claims.extend(extras)


def plant_self_referral_imaging(pmap, claims, pidx, ids, rng, working_days):
    """Non-radiology providers self-referring high-value MRI/CT (out-of-specialty)."""
    imaging = ["72148", "70553", "74177", "73721"]
    extras = []
    for pid in ids:
        prov = pmap[pid]
        for _ in range(50):
            day = working_days[int(rng.integers(0, len(working_days)))]
            pat = f"PAT{rng.integers(1, 200_001):06d}"
            extras.append(_make_claim(prov, day, str(rng.choice(imaging)), rng))
    claims.extend(extras)


def plant_modifier_25_abuse(pmap, claims, pidx, ids, rng):
    """Attach a separately-payable E/M (modifier 25) to most procedure days."""
    extras = []
    procedure_codes = {c for c, f in FEE_SCHEDULE.items()
                       if f["tier"] >= 2 and not c.startswith("99")}
    for pid in ids:
        prov = pmap[pid]
        proc_days = sorted({claims[i]["service_date"] for i in pidx[pid]
                            if claims[i]["fee_code"] in procedure_codes})
        for day in proc_days:
            if rng.random() < 0.85:
                em = _make_claim(prov, day, "99214", rng, modifier="25")
                extras.append(em)
    claims.extend(extras)


def plant_unit_inflation(pmap, claims, pidx, ids, rng):
    """Inflate units on time/dose-based codes so reimbursement multiplies."""
    for pid in ids:
        prov = pmap[pid]
        spec = SPECIALTIES[prov["specialty"]]
        unit_codes = [c for c in spec["codes"] if c in UNIT_BILLABLE]
        if not unit_codes:
            unit_codes = ["96372"]
        for i in pidx[pid]:
            c = claims[i]
            if c["fee_code"] in UNIT_BILLABLE and rng.random() < 0.7:
                k = int(rng.integers(3, 9))
                unit_price = c["amount_billed"]
                c["units"] = k
                c["amount_billed"] = round(unit_price * k, 2)


def plant_escalating_biller(pmap, claims, pidx, ids, rng, span_days, day0):
    """Top-tier substitution probability ramps from ~0 to ~0.9 over the period."""
    for pid in ids:
        top = SPECIALTIES[pmap[pid]["specialty"]]["top_tier_codes"]
        for i in pidx[pid]:
            c = claims[i]
            frac = (c["service_date"] - day0).days / max(1, span_days)
            if rng.random() < min(0.9, max(0.0, frac)):
                code = str(rng.choice(top))
                fee  = FEE_SCHEDULE[code]
                c["fee_code"]        = code
                c["fee_description"] = fee["desc"]
                c["service_minutes"] = fee["minutes"]
                c["amount_billed"]   = round(fee["amount"] * rng.uniform(0.95, 1.05), 2)


def plant_weekend_biller(pmap, claims, pidx, ids, rng, weekend_days):
    """Bill procedures on weekends/holidays when the office is closed."""
    extras = []
    for pid in ids:
        prov = pmap[pid]
        spec = SPECIALTIES[prov["specialty"]]
        codes, wts = spec["codes"], spec["weights"]
        sample = rng.choice(len(weekend_days), size=min(60, len(weekend_days)), replace=False)
        for di in sample:
            for _ in range(int(rng.integers(2, 6))):
                extras.append(_make_claim(prov, weekend_days[int(di)],
                                          str(rng.choice(codes, p=wts)), rng))
    claims.extend(extras)


# ── Entry point ───────────────────────────────────────────────────────────────

SCHEME_PLAN = [
    # (key, label, n_providers, optional specialty constraint)
    ("upcoding",            "Upcoding (E/M complexity inflation)",      3, "Family Medicine"),
    ("psych_time",          "Psychotherapy time inflation",            2, "Psychiatry"),
    ("unbundling",          "Unbundling component codes",              2, "Cardiology"),
    ("duplicate",           "Duplicate claim resubmission",            3, None),
    ("impossible_day",      "Impossible day (>24h billed)",            2, None),
    ("phantom_volume",      "Phantom / excessive claim volume",        2, None),
    ("self_referral",       "Self-referral out-of-specialty imaging",  2, "Orthopedic Surgery"),
    ("modifier_25",         "Modifier-25 separate-E/M abuse",          2, "Dermatology"),
    ("unit_inflation",      "Unit / dosage inflation",                 2, "Ophthalmology"),
    ("escalating",          "Escalating upcoding over time",           2, "Internal Medicine"),
    ("weekend",             "Weekend / closed-office billing",         2, None),
]


def main():
    ap = argparse.ArgumentParser(description="Expanded synthetic billing generator")
    ap.add_argument("--providers", type=int, default=300)
    ap.add_argument("--clinics",   type=int, default=60)
    ap.add_argument("--start-year", type=int, default=2023)
    ap.add_argument("--end-year",   type=int, default=2024)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--output", default=OUTPUT_CSV)
    args = ap.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    fake = Faker(); Faker.seed(args.seed)
    rng = np.random.default_rng(args.seed)

    working_days, weekend_days = _working_days(args.start_year, args.end_year)
    day0      = working_days[0]
    span_days = (working_days[-1] - working_days[0]).days

    print("Expanded Synthetic Physician Billing Generator")
    print("=" * 64)
    print(f"  Specialties        : {len(SPECIALTY_NAMES)}")
    print(f"  Fee codes          : {len(FEE_SCHEDULE)}")
    print(f"  Date range         : {working_days[0]} → {working_days[-1]} "
          f"({len(working_days)} working days)")

    providers  = make_providers(args.providers, args.clinics, fake, rng)
    pmap       = {p["provider_id"]: p for p in providers}
    claims     = generate_base_claims(providers, working_days, rng)
    print(f"  Providers          : {len(providers)}")
    print(f"  Base claims        : {len(claims):,}")

    pidx = _index_by_provider(claims)

    # ── Pick bad-actor targets (disjoint) ─────────────────────────────────────
    used, assignments = set(), {}

    def pick(n, specialty=None):
        pool = [p["provider_id"] for p in providers
                if p["provider_id"] not in used
                and (specialty is None or p["specialty"] == specialty)]
        chosen = rng.choice(pool, size=min(n, len(pool)), replace=False).tolist()
        used.update(chosen)
        return chosen

    for key, _label, n, spec in SCHEME_PLAN:
        assignments[key] = pick(n, spec)

    # ── Plant schemes ─────────────────────────────────────────────────────────
    print("\n  Planting revenue-inflation schemes ...")
    plant_upcoding(pmap, claims, pidx, assignments["upcoding"], rng)
    plant_psych_time_inflation(pmap, claims, pidx, assignments["psych_time"], rng)
    plant_unbundling(pmap, claims, pidx, assignments["unbundling"], rng, working_days)
    plant_duplicates(pmap, claims, pidx, assignments["duplicate"], rng)
    plant_impossible_days(pmap, claims, pidx, assignments["impossible_day"], rng)
    plant_phantom_volume(pmap, claims, pidx, assignments["phantom_volume"], rng)
    plant_self_referral_imaging(pmap, claims, pidx, assignments["self_referral"], rng, working_days)
    plant_modifier_25_abuse(pmap, claims, pidx, assignments["modifier_25"], rng)
    plant_unit_inflation(pmap, claims, pidx, assignments["unit_inflation"], rng)
    plant_escalating_biller(pmap, claims, pidx, assignments["escalating"], rng, span_days, day0)
    plant_weekend_biller(pmap, claims, pidx, assignments["weekend"], rng, weekend_days)
    print(f"  Claims after planting: {len(claims):,}")

    # ── Assign claim ids + write CSV ──────────────────────────────────────────
    for i, c in enumerate(claims):
        c["claim_id"] = f"CLM{i+1:08d}"

    COLS = [
        "claim_id", "provider_id", "provider_name", "specialty",
        "patient_id", "service_date", "fee_code", "fee_description",
        "service_minutes", "units", "amount_billed", "modifier", "clinic_id",
    ]
    df = pd.DataFrame(claims)[COLS]
    df["service_date"] = pd.to_datetime(df["service_date"])
    df = df.sort_values(["service_date", "provider_id"]).reset_index(drop=True)
    df.to_csv(args.output, index=False)

    all_bad = sorted({pid for ids in assignments.values() for pid in ids})
    print(f"\n  Claims written     : {len(df):,} → {args.output}")
    print(f"  Unique providers   : {df['provider_id'].nunique()}")
    print(f"  Unique patients    : {df['patient_id'].nunique():,}")
    print(f"  Total billed       : ${df['amount_billed'].sum():,.2f}")
    print(f"  Planted bad actors : {len(all_bad)} across {len(SCHEME_PLAN)} schemes")

    # ── Ground truth ──────────────────────────────────────────────────────────
    gt = {
        "schemes": {key: assignments[key] for key, *_ in SCHEME_PLAN},
        "scheme_labels": {key: label for key, label, *_ in SCHEME_PLAN},
        "all_bad_actors": all_bad,
        "n_providers": int(df["provider_id"].nunique()),
        "n_claims": int(len(df)),
        "date_range": [str(working_days[0]), str(working_days[-1])],
    }
    with open(GROUND_TRUTH_JSON, "w") as fh:
        json.dump(gt, fh, indent=2)
    print(f"  Ground truth       → {GROUND_TRUTH_JSON}")


if __name__ == "__main__":
    main()
