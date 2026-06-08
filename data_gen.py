"""Phase 1 — Synthetic physician billing data generator.

Generates ~40 000 claims across 150 providers / 6 specialties for calendar
year 2024, then plants 10 distinct bad actors so later phases can be
validated against a known ground truth.

Three additional "clean trap" providers (TRAP01-03) are added to test
false-positive behaviour.  They must never be flagged by a well-calibrated
system.
"""

import json
import random
from datetime import date, timedelta

import numpy as np
import pandas as pd
from faker import Faker

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

OUTPUT_CSV         = "claims.csv"
GROUND_TRUTH_JSON  = "ground_truth.json"

# ── Fee schedule (15 codes) ──────────────────────────────────────────────────
FEE_SCHEDULE = {
    "99213": {"desc": "Office Visit Brief",            "minutes": 15,  "amount": 85.00,   "tier": 1},
    "99214": {"desc": "Office Visit Moderate",         "minutes": 25,  "amount": 130.00,  "tier": 2},
    "99215": {"desc": "Office Visit Complex",          "minutes": 40,  "amount": 200.00,  "tier": 3},
    "99232": {"desc": "Subsequent Hospital Care",      "minutes": 20,  "amount": 110.00,  "tier": 2},
    "93000": {"desc": "ECG Complete",                  "minutes": 20,  "amount": 70.00,   "tier": 2},
    "93005": {"desc": "ECG Tracing Only",              "minutes": 10,  "amount": 35.00,   "tier": 1},
    "93010": {"desc": "ECG Interpretation Only",       "minutes": 10,  "amount": 45.00,   "tier": 1},
    "72148": {"desc": "MRI Lumbar Spine",              "minutes": 45,  "amount": 350.00,  "tier": 3},
    "70553": {"desc": "MRI Brain w/ Contrast",         "minutes": 60,  "amount": 450.00,  "tier": 3},
    "90837": {"desc": "Psychotherapy 60 min",          "minutes": 60,  "amount": 180.00,  "tier": 3},
    "90834": {"desc": "Psychotherapy 45 min",          "minutes": 45,  "amount": 140.00,  "tier": 2},
    "11100": {"desc": "Skin Biopsy First Lesion",      "minutes": 20,  "amount": 150.00,  "tier": 2},
    "11101": {"desc": "Skin Biopsy Additional Lesion", "minutes": 10,  "amount": 75.00,   "tier": 1},
    "27447": {"desc": "Total Knee Replacement",        "minutes": 120, "amount": 1200.00, "tier": 3},
    "43239": {"desc": "Upper GI Endoscopy w/ Biopsy", "minutes": 30,  "amount": 380.00,  "tier": 3},
}

# Unbundling rule: billing both components instead of the bundle is fraud
BUNDLE_RULES = [
    {"components": frozenset({"93005", "93010"}), "bundle_code": "93000",
     "bundle_desc": "ECG Complete"},
]

# ── Specialty profiles ───────────────────────────────────────────────────────
SPECIALTIES = {
    "Family Medicine": {
        "codes":   ["99213", "99214", "99215", "99232"],
        "weights": [0.45,    0.35,    0.15,    0.05],
        "avg_daily_claims": 2.0,
        "top_tier_codes": ["99215"],
    },
    "Cardiology": {
        "codes":   ["93000", "99214", "99215", "93005", "93010"],
        "weights": [0.40,    0.25,    0.15,    0.10,    0.10],
        "avg_daily_claims": 1.8,
        "top_tier_codes": ["99215"],
    },
    "Radiology": {
        "codes":   ["72148", "70553"],
        "weights": [0.55,    0.45],
        "avg_daily_claims": 2.2,
        "top_tier_codes": ["70553"],
    },
    "Psychiatry": {
        "codes":   ["90837", "90834", "99214"],
        "weights": [0.50,    0.40,    0.10],
        "avg_daily_claims": 1.5,
        "top_tier_codes": ["90837"],
    },
    "Dermatology": {
        "codes":   ["11100", "11101", "99213", "99214"],
        "weights": [0.30,    0.25,    0.25,    0.20],
        "avg_daily_claims": 2.0,
        "top_tier_codes": ["11100"],
    },
    "Surgery": {
        "codes":   ["27447", "43239", "99215", "99232"],
        "weights": [0.20,    0.30,    0.25,    0.25],
        "avg_daily_claims": 1.0,
        "top_tier_codes": ["27447", "43239"],
    },
}

SPECIALTY_NAMES = list(SPECIALTIES.keys())
SPECIALTY_DIST  = [0.30, 0.20, 0.15, 0.15, 0.12, 0.08]

N_PROVIDERS = 150
N_CLINICS   = 20
YEAR_START  = date(2024, 1, 1)
YEAR_END    = date(2024, 12, 31)


def _working_days_2024():
    days, d = [], YEAR_START
    while d <= YEAR_END:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


WORKING_DAYS = _working_days_2024()   # 261 days


# ── Clean-trap provider definitions ─────────────────────────────────────────
# These providers exhibit patterns that might superficially resemble anomalies
# but are clinically legitimate.  A well-calibrated system must NOT flag them.
# IDs are outside the PRVxxxx range to prevent accidental collisions.

TRAP_PROVIDERS = [
    {
        "provider_id":   "TRAP01",
        "provider_name": "Dr. Helena Radcliffe",
        "specialty":     "Radiology",
        "clinic_id":     "CLN21",
        # High daily claim count (all 261 days, ~4.5 claims/day) — legitimately
        # busy hospital radiologist reading films continuously.  Will stress-test
        # whether plain z-score volume flags a real high-performer.
        "_trap_type":    "high_volume_clean",
        "_trap_desc":    "Legitimate high-volume radiologist (busy hospital reader)",
    },
    {
        "provider_id":   "TRAP02",
        "provider_name": "Dr. James Colquhoun",
        "specialty":     "Family Medicine",
        "clinic_id":     "CLN22",
        # Part-time locum: only ~40 scattered work days, 1-2 claims per day.
        # Will stress-test whether low-volume / sporadic patterns are mis-flagged.
        "_trap_type":    "part_time_clean",
        "_trap_desc":    "Part-time locum physician (low volume, sporadic schedule)",
    },
    {
        "provider_id":   "TRAP03",
        "provider_name": "Dr. Sandra Beaumont",
        "specialty":     "Family Medicine",
        "clinic_id":     "CLN23",
        # Sub-threshold marathoner: 5 very long clinical days where total
        # service_minutes reach 1 360 (just under the 1 440 rule trigger).
        # Tests stability near rule boundaries.
        "_trap_type":    "sub_threshold_clean",
        "_trap_desc":    "Sub-threshold provider (long days but always <1440 min)",
    },
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_claim(provider: dict, day: date, code: str, rng) -> dict:
    fee = FEE_SCHEDULE[code]
    return {
        "provider_id":     provider["provider_id"],
        "provider_name":   provider["provider_name"],
        "specialty":       provider["specialty"],
        "patient_id":      f"PAT{rng.integers(1, 50_001):05d}",
        "service_date":    day,
        "fee_code":        code,
        "fee_description": fee["desc"],
        "service_minutes": fee["minutes"],
        "units":           1,
        "amount_billed":   round(fee["amount"] * rng.uniform(0.95, 1.05), 2),
        "clinic_id":       provider["clinic_id"],
    }


# ── Provider creation ────────────────────────────────────────────────────────

def make_providers(rng) -> list[dict]:
    specs   = rng.choice(SPECIALTY_NAMES, size=N_PROVIDERS, p=SPECIALTY_DIST)
    clinics = rng.integers(1, N_CLINICS + 1, size=N_PROVIDERS)
    return [
        {
            "provider_id":   f"PRV{i+1:04d}",
            "provider_name": fake.name(),
            "specialty":     str(specs[i]),
            "clinic_id":     f"CLN{int(clinics[i]):02d}",
        }
        for i in range(N_PROVIDERS)
    ]


# ── Normal claim generation ──────────────────────────────────────────────────

def generate_base_claims(providers: list[dict], rng) -> list[dict]:
    claims = []
    wd   = WORKING_DAYS
    n_wd = len(wd)
    for prov in providers:
        spec    = SPECIALTIES[prov["specialty"]]
        codes   = spec["codes"]
        weights = np.array(spec["weights"], dtype=float)
        weights /= weights.sum()
        avg     = spec["avg_daily_claims"]

        n_days   = int(n_wd * rng.uniform(0.65, 0.82))
        day_idxs = sorted(rng.choice(n_wd, size=n_days, replace=False).tolist())
        work_days = [wd[i] for i in day_idxs]

        for day in work_days:
            n = max(1, int(rng.normal(avg, avg * 0.35)))
            for _ in range(n):
                code = str(rng.choice(codes, p=weights))
                claims.append(_make_claim(prov, day, code, rng))
    return claims


# ── Clean-trap claim generation ──────────────────────────────────────────────

def generate_trap_claims(rng) -> list[dict]:
    """Generate legitimate claims for the three clean-trap providers."""
    claims = []

    # Sanitise provider dicts (strip private _ keys before passing to _make_claim)
    def _safe(tp):
        return {k: v for k, v in tp.items() if not k.startswith("_")}

    # ── TRAP01: high-volume radiologist ──────────────────────────────────────
    t01   = _safe(TRAP_PROVIDERS[0])
    spec  = SPECIALTIES["Radiology"]
    codes = spec["codes"]
    wts   = np.array(spec["weights"], dtype=float); wts /= wts.sum()
    # Works all 261 days, ~4.5 claims/day — high but plausible for a hospital reader
    for day in WORKING_DAYS:
        n = max(3, int(rng.normal(4.5, 0.8)))
        for _ in range(n):
            code = str(rng.choice(codes, p=wts))
            claims.append(_make_claim(t01, day, code, rng))

    # ── TRAP02: part-time locum ───────────────────────────────────────────────
    t02   = _safe(TRAP_PROVIDERS[1])
    spec  = SPECIALTIES["Family Medicine"]
    codes = spec["codes"]
    wts   = np.array(spec["weights"], dtype=float); wts /= wts.sum()
    # Scattered 40 work-days per year, 1-2 claims each
    wd_idxs = sorted(rng.choice(len(WORKING_DAYS), size=40, replace=False).tolist())
    for idx in wd_idxs:
        n = max(1, int(rng.normal(1.5, 0.5)))
        for _ in range(n):
            code = str(rng.choice(codes, p=wts))
            claims.append(_make_claim(t02, WORKING_DAYS[idx], code, rng))

    # ── TRAP03: sub-threshold marathoner ─────────────────────────────────────
    t03   = _safe(TRAP_PROVIDERS[2])
    spec  = SPECIALTIES["Family Medicine"]
    codes = spec["codes"]
    wts   = np.array(spec["weights"], dtype=float); wts /= wts.sum()
    # Normal billing on 75% of working days
    n_norm  = int(len(WORKING_DAYS) * 0.75)
    norm_is = sorted(rng.choice(len(WORKING_DAYS), size=n_norm, replace=False).tolist())
    for idx in norm_is:
        n = max(1, int(rng.normal(2.0, 0.7)))
        for _ in range(n):
            code = str(rng.choice(codes, p=wts))
            claims.append(_make_claim(t03, WORKING_DAYS[idx], code, rng))
    # 5 "marathon" days: 34 × 40-min visits = 1 360 minutes (just under 1 440)
    marathon_is = rng.choice(len(WORKING_DAYS), size=5, replace=False).tolist()
    for idx in marathon_is:
        for _ in range(34):
            claims.append(_make_claim(t03, WORKING_DAYS[idx], "99215", rng))

    return claims


# ── Bad-actor planters ───────────────────────────────────────────────────────

def plant_impossible_days(pmap: dict, claims: list, ids: list, rng):
    """Force total service_minutes > 1 440 on 5 random days per target."""
    for pid in ids:
        prov = pmap[pid]
        days = sorted({c["service_date"] for c in claims if c["provider_id"] == pid})
        if not days:
            continue
        idxs     = rng.choice(len(days), size=min(5, len(days)), replace=False)
        bad_days = [days[i] for i in idxs]
        for day in bad_days:
            existing = sum(c["service_minutes"] for c in claims
                           if c["provider_id"] == pid and c["service_date"] == day)
            needed = 1_500 - existing
            while needed > 0:
                claims.append(_make_claim(prov, day, "99215", rng))
                needed -= FEE_SCHEDULE["99215"]["minutes"]


def plant_upcoders(pmap: dict, claims: list, ids: list, rng):
    """Replace 80 % of claims with the specialty's highest-fee code."""
    for pid in ids:
        prov = pmap[pid]
        top  = SPECIALTIES[prov["specialty"]]["top_tier_codes"]
        for c in claims:
            if c["provider_id"] == pid and rng.random() < 0.80:
                code = str(rng.choice(top))
                fee  = FEE_SCHEDULE[code]
                c["fee_code"]        = code
                c["fee_description"] = fee["desc"]
                c["service_minutes"] = fee["minutes"]
                c["amount_billed"]   = round(fee["amount"] * rng.uniform(0.95, 1.05), 2)


def plant_duplicates(pmap: dict, claims: list, ids: list, rng):
    """Duplicate ~15 % of each target's claims (same key fields)."""
    extras = []
    for pid in ids:
        idxs = [i for i, c in enumerate(claims) if c["provider_id"] == pid]
        n    = max(10, int(len(idxs) * 0.15))
        for i in rng.choice(idxs, size=n, replace=False).tolist():
            extras.append(claims[i].copy())
    claims.extend(extras)


def plant_volume_outliers(pmap: dict, claims: list, ids: list, rng):
    """Add 20–28 extra claims every working day for each target."""
    extras = []
    for pid in ids:
        prov  = pmap[pid]
        spec  = SPECIALTIES[prov["specialty"]]
        codes = spec["codes"]
        wts   = np.array(spec["weights"], dtype=float); wts /= wts.sum()
        days  = sorted({c["service_date"] for c in claims if c["provider_id"] == pid})
        for day in days:
            for _ in range(int(rng.integers(20, 29))):
                code = str(rng.choice(codes, p=wts))
                extras.append(_make_claim(prov, day, code, rng))
    claims.extend(extras)


def plant_unbundler(pmap: dict, claims: list, ids: list, rng):
    """Replace 93000 (ECG Complete) with components 93005 + 93010, add extras."""
    extras = []
    for pid in ids:
        prov = pmap[pid]
        for c in claims:
            if c["provider_id"] == pid and c["fee_code"] == "93000":
                c["fee_code"]        = "93005"
                c["fee_description"] = FEE_SCHEDULE["93005"]["desc"]
                c["service_minutes"] = FEE_SCHEDULE["93005"]["minutes"]
                c["amount_billed"]   = round(FEE_SCHEDULE["93005"]["amount"] * rng.uniform(0.95, 1.05), 2)
                comp = c.copy()
                comp["fee_code"]        = "93010"
                comp["fee_description"] = FEE_SCHEDULE["93010"]["desc"]
                comp["service_minutes"] = FEE_SCHEDULE["93010"]["minutes"]
                comp["amount_billed"]   = round(FEE_SCHEDULE["93010"]["amount"] * rng.uniform(0.95, 1.05), 2)
                extras.append(comp)
        days = sorted({c["service_date"] for c in claims if c["provider_id"] == pid})
        n    = min(35, len(days))
        for day in [days[i] for i in rng.choice(len(days), size=n, replace=False)]:
            pat = f"PAT{rng.integers(1, 50_001):05d}"
            for code in ["93005", "93010"]:
                fee = FEE_SCHEDULE[code]
                extras.append({
                    "provider_id":     pid,
                    "provider_name":   prov["provider_name"],
                    "specialty":       prov["specialty"],
                    "patient_id":      pat,
                    "service_date":    day,
                    "fee_code":        code,
                    "fee_description": fee["desc"],
                    "service_minutes": fee["minutes"],
                    "units":           1,
                    "amount_billed":   round(fee["amount"] * rng.uniform(0.95, 1.05), 2),
                    "clinic_id":       prov["clinic_id"],
                })
    claims.extend(extras)


def plant_novel_biller(pmap: dict, claims: list, ids: list, rng):
    """Bills MRI Lumbar + Psychotherapy (out-of-specialty for FM) on same patient/date.

    No hand-coded rule catches this; the ML layer should surface it via an
    anomalous feature vector (high avg amount, alien code mix for FM).
    """
    extras = []
    for pid in ids:
        prov = pmap[pid]
        days = sorted({c["service_date"] for c in claims if c["provider_id"] == pid})
        n    = min(45, len(days))
        for day in [days[i] for i in rng.choice(len(days), size=n, replace=False)]:
            pat = f"PAT{rng.integers(1, 50_001):05d}"
            for code in ["72148", "90837"]:      # MRI + Psychotherapy
                fee = FEE_SCHEDULE[code]
                extras.append({
                    "provider_id":     pid,
                    "provider_name":   prov["provider_name"],
                    "specialty":       prov["specialty"],
                    "patient_id":      pat,
                    "service_date":    day,
                    "fee_code":        code,
                    "fee_description": fee["desc"],
                    "service_minutes": fee["minutes"],
                    "units":           1,
                    "amount_billed":   round(fee["amount"] * rng.uniform(0.95, 1.05), 2),
                    "clinic_id":       prov["clinic_id"],
                })
    claims.extend(extras)


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    rng = np.random.default_rng(SEED)

    print("Phase 1 - Synthetic Physician Billing Data Generator")
    print("=" * 60)

    providers  = make_providers(rng)
    pmap       = {p["provider_id"]: p for p in providers}
    all_claims = generate_base_claims(providers, rng)
    print(f"  Providers created : {len(providers)}")
    print(f"  Base claims       : {len(all_claims):,}")

    # ── Pick bad-actor targets ────────────────────────────────────────────────
    used = set()

    def pick(specialty=None, n=2):
        pool   = [p["provider_id"] for p in providers
                  if (specialty is None or p["specialty"] == specialty)
                  and p["provider_id"] not in used]
        chosen = rng.choice(pool, size=n, replace=False).tolist()
        used.update(chosen)
        return chosen

    impossible_ids = pick(n=2)
    upcoder_ids    = pick(n=2)
    duplicate_ids  = pick(n=2)
    volume_ids     = pick(n=2)
    unbundler_ids  = pick(specialty="Cardiology", n=1)
    novel_ids      = pick(specialty="Family Medicine", n=1)

    # ── Plant anomalies ───────────────────────────────────────────────────────
    print("\n  Planting anomalies ...")
    plant_impossible_days(pmap, all_claims, impossible_ids, rng)
    plant_upcoders(pmap, all_claims, upcoder_ids, rng)
    plant_duplicates(pmap, all_claims, duplicate_ids, rng)
    plant_volume_outliers(pmap, all_claims, volume_ids, rng)
    plant_unbundler(pmap, all_claims, unbundler_ids, rng)
    plant_novel_biller(pmap, all_claims, novel_ids, rng)
    print(f"  Claims after planting: {len(all_claims):,}")

    # ── Add clean trap providers (after all bad-actor RNG calls) ─────────────
    trap_claims = generate_trap_claims(rng)
    all_claims.extend(trap_claims)
    for tp in TRAP_PROVIDERS:
        safe = {k: v for k, v in tp.items() if not k.startswith("_")}
        pmap[safe["provider_id"]] = safe
    print(f"  Claims after traps   : {len(all_claims):,}  (+{len(trap_claims)} trap claims)")

    # ── Assign claim IDs and write CSV ────────────────────────────────────────
    for i, c in enumerate(all_claims):
        c["claim_id"] = f"CLM{i+1:07d}"

    COLS = [
        "claim_id", "provider_id", "provider_name", "specialty",
        "patient_id", "service_date", "fee_code", "fee_description",
        "service_minutes", "units", "amount_billed", "clinic_id",
    ]
    df = pd.DataFrame(all_claims)[COLS]
    df["service_date"] = pd.to_datetime(df["service_date"])
    df.to_csv(OUTPUT_CSV, index=False)

    print(f"\n  Claims written       : {len(df):,}")
    print(f"  Unique providers     : {df['provider_id'].nunique()}")
    print(f"  Date range           : {df['service_date'].min().date()} to {df['service_date'].max().date()}")
    print(f"  Total billed         : ${df['amount_billed'].sum():>13,.2f}")
    print(f"  Avg billed/claim     : ${df['amount_billed'].mean():>10,.2f}")
    print(f"  Output               : {OUTPUT_CSV}")

    # ── Save ground truth ─────────────────────────────────────────────────────
    gt = {
        "impossible_day": impossible_ids,
        "upcoder":        upcoder_ids,
        "duplicate":      duplicate_ids,
        "volume_outlier": volume_ids,
        "unbundler":      unbundler_ids,
        "novel":          novel_ids,
        "all_bad_actors": sorted(set(
            impossible_ids + upcoder_ids + duplicate_ids +
            volume_ids + unbundler_ids + novel_ids
        )),
        "clean_providers": {
            tp["provider_id"]: {
                "description": tp["_trap_desc"],
                "type":        tp["_trap_type"],
            }
            for tp in TRAP_PROVIDERS
        },
    }
    with open(GROUND_TRUTH_JSON, "w") as fh:
        json.dump(gt, fh, indent=2)

    print("\n" + "=" * 60)
    print("GROUND TRUTH  (saved to ground_truth.json — do not peek until scoring!)")
    print("=" * 60)
    for cat in ("impossible_day", "upcoder", "duplicate", "volume_outlier", "unbundler", "novel"):
        label = f"  {cat:<20s}:"
        print(f"{label} {gt[cat]}")
    print(f"\n  Total unique bad actors : {len(gt['all_bad_actors'])}")
    print(f"  Clean trap providers    : {list(gt['clean_providers'].keys())}")
    print("=" * 60)

    # Print specialty of each bad actor (useful for cohort debugging)
    print("\n  Bad-actor specialty breakdown:")
    for cat in ("impossible_day", "upcoder", "duplicate", "volume_outlier", "unbundler", "novel"):
        for pid in gt[cat]:
            spec = pmap.get(pid, {}).get("specialty", "?")
            print(f"    {pid}  {cat:<20}  {spec}")


if __name__ == "__main__":
    main()
