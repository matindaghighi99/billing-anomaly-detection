"""generate_samples.py — build labelled sample claims datasets for testing.

Produces five small, self-contained claims files, each a DIFFERENT specialty and
a DIFFERENT fraud/suspicion pattern, so you can point the system at each one and
confirm it flags the planted bad actor before any real OHIP data is involved.

Each file matches the production claims schema exactly:
    claim_id, provider_id, provider_name, specialty, patient_id, service_date,
    fee_code, fee_description, service_minutes, units, amount_billed, clinic_id

Every file contains a COHORT of clean providers (so the peer-comparison detector
has a baseline) plus one or two planted bad actors. The answer key is written to
ground_truth.json next to the CSVs.

Regenerate with:
    python sample_claims/generate_samples.py
"""

import json
import os

import numpy as np
import pandas as pd
from faker import Faker

HERE = os.path.dirname(os.path.abspath(__file__))
YEAR_START = pd.Timestamp("2024-01-01")
YEAR_END = pd.Timestamp("2024-12-31")

FEE_SCHEDULE = {
    "99213": ("Office Visit Brief", 15, 85.00),
    "99214": ("Office Visit Moderate", 25, 130.00),
    "99215": ("Office Visit Complex", 40, 200.00),
    "93000": ("ECG Complete", 20, 70.00),
    "93005": ("ECG Tracing Only", 10, 35.00),
    "93010": ("ECG Interpretation Only", 10, 45.00),
    "72148": ("MRI Lumbar Spine", 45, 350.00),
    "70553": ("MRI Brain w/ Contrast", 60, 450.00),
    "90837": ("Psychotherapy 60 min", 60, 180.00),
    "90834": ("Psychotherapy 45 min", 45, 140.00),
}

_claim_seq = 0


def _working_days(rng, n):
    """Pick n weekday dates across 2024."""
    all_days = pd.bdate_range(YEAR_START, YEAR_END)
    idx = sorted(rng.choice(len(all_days), size=min(n, len(all_days)), replace=False))
    return [all_days[i] for i in idx]


def _claim(rng, prov_id, name, specialty, clinic, day, code):
    global _claim_seq
    _claim_seq += 1
    desc, minutes, amount = FEE_SCHEDULE[code]
    return {
        "claim_id": f"CLM{_claim_seq:08d}",
        "provider_id": prov_id,
        "provider_name": name,
        "specialty": specialty,
        "patient_id": f"PAT{rng.integers(0, 80000):05d}",
        "service_date": day.strftime("%Y-%m-%d"),
        "fee_code": code,
        "fee_description": desc,
        "service_minutes": minutes,
        "units": 1,
        "amount_billed": round(amount * rng.uniform(0.97, 1.06), 2),
        "clinic_id": clinic,
    }


def _emit_provider(rows, rng, prov_id, name, specialty, clinic, codes, weights,
                   claims_per_day, active_days, months=None):
    """Emit a clean provider's year of claims."""
    days = _working_days(rng, active_days)
    if months is not None:
        days = [d for d in days if d.month in months]
    for day in days:
        k = max(1, int(rng.poisson(claims_per_day)))
        for code in rng.choice(codes, size=k, p=weights):
            rows.append(_claim(rng, prov_id, name, specialty, clinic, day, str(code)))


def _cohort(rows, rng, fake, specialty, prefix, codes, weights, cpd, n=12):
    """A clean peer cohort for *specialty*."""
    for i in range(1, n + 1):
        _emit_provider(rows, rng, f"{prefix}{i:03d}", fake.name(), specialty,
                       f"CLN{rng.integers(1, 40):02d}", codes, weights, cpd,
                       active_days=rng.integers(150, 210))


# ── Scenario builders — each returns (DataFrame, list-of-bad-actor-dicts) ──────

def scenario_upcoding(seed):
    """Internal Medicine — upcoding: bad actor bills the complex E/M code (99215)
    for almost every visit while peers mostly bill brief/moderate visits."""
    rng = np.random.default_rng(seed); fake = Faker(); Faker.seed(seed)
    rows = []
    codes, w = ["99213", "99214", "99215"], [0.55, 0.32, 0.13]
    _cohort(rows, rng, fake, "Internal Medicine", "IMP", codes, w, 2.0)
    bad = "IMP999"
    _emit_provider(rows, rng, bad, fake.name(), "Internal Medicine", "CLN07",
                   ["99214", "99215"], [0.10, 0.90], 2.2, active_days=200)
    return pd.DataFrame(rows), [{"provider_id": bad,
        "scheme": "Upcoding (E/M complexity inflation)",
        "expect": "peer-stats flag: high top-tier share / avg billed vs cohort"}]


def scenario_overimaging(seed):
    """Radiology — over-utilisation / self-referral: bad actor images at several
    times the volume of peers, heavy on the most expensive MRI."""
    rng = np.random.default_rng(seed); fake = Faker(); Faker.seed(seed)
    rows = []
    codes, w = ["72148", "70553"], [0.55, 0.45]
    _cohort(rows, rng, fake, "Radiology", "RAD", codes, w, 2.2)
    bad = "RAD999"
    _emit_provider(rows, rng, bad, fake.name(), "Radiology", "CLN03",
                   ["72148", "70553"], [0.25, 0.75], 9.0, active_days=205)
    return pd.DataFrame(rows), [{"provider_id": bad,
        "scheme": "Over-utilisation / self-referral imaging",
        "expect": "peer-stats flag: volume + total-billed outlier vs cohort"}]


def scenario_impossible_day(seed):
    """Family Medicine — impossible day: bad actor bills > 1,440 service-minutes
    (impossible in a 24h day) on multiple days — phantom visits."""
    rng = np.random.default_rng(seed); fake = Faker(); Faker.seed(seed)
    rows = []
    codes, w = ["99213", "99214", "99215"], [0.5, 0.35, 0.15]
    _cohort(rows, rng, fake, "Family Medicine", "FAM", codes, w, 2.0)
    bad = "FAM999"
    name = fake.name()
    # ~40 complex visits (40 min each = 1,600 min) on 12 scattered days.
    for day in _working_days(rng, 12):
        for _ in range(40):
            rows.append(_claim(rng, bad, name, "Family Medicine", "CLN11", day, "99215"))
    # plus normal-looking baseline activity the rest of the year
    _emit_provider(rows, rng, bad, name, "Family Medicine", "CLN11", codes, w,
                   2.0, active_days=150)
    return pd.DataFrame(rows), [{"provider_id": bad,
        "scheme": "Impossible day (phantom visits)",
        "expect": "rules flag: >1,440 billed minutes in a single day"}]


def scenario_unbundling(seed):
    """Cardiology — unbundling: bad actor bills ECG components 93005 + 93010
    separately (same patient/date) instead of the bundled 93000."""
    rng = np.random.default_rng(seed); fake = Faker(); Faker.seed(seed)
    rows = []
    codes, w = ["93000", "99214", "99215"], [0.6, 0.25, 0.15]
    _cohort(rows, rng, fake, "Cardiology", "CAR", codes, w, 1.8)
    bad = "CAR999"
    name = fake.name()
    for day in _working_days(rng, 180):
        n = max(1, int(rng.poisson(2.0)))
        for _ in range(n):
            pat = f"PAT{rng.integers(0, 80000):05d}"
            for code in ("93005", "93010"):       # split instead of 93000
                global _claim_seq
                _claim_seq += 1
                desc, minutes, amount = FEE_SCHEDULE[code]
                rows.append({"claim_id": f"CLM{_claim_seq:08d}", "provider_id": bad,
                    "provider_name": name, "specialty": "Cardiology",
                    "patient_id": pat, "service_date": day.strftime("%Y-%m-%d"),
                    "fee_code": code, "fee_description": desc,
                    "service_minutes": minutes, "units": 1,
                    "amount_billed": round(amount * rng.uniform(0.97, 1.06), 2),
                    "clinic_id": "CLN05"})
    return pd.DataFrame(rows), [{"provider_id": bad,
        "scheme": "Unbundling (ECG 93005+93010 vs 93000)",
        "expect": "rules flag: component codes billed instead of the bundle"}]


def scenario_temporal_spike(seed):
    """Psychiatry — temporal spike: bad actor bills normally for H1 2024 then
    jumps ~2.5x in H2 — a sudden-onset change in billing."""
    rng = np.random.default_rng(seed); fake = Faker(); Faker.seed(seed)
    rows = []
    codes, w = ["90837", "90834", "99214"], [0.5, 0.4, 0.1]
    _cohort(rows, rng, fake, "Psychiatry", "PSY", codes, w, 1.5)
    bad = "PSY999"
    name = fake.name()
    _emit_provider(rows, rng, bad, name, "Psychiatry", "CLN02", codes, w,
                   1.5, active_days=120, months={1, 2, 3, 4, 5, 6})
    _emit_provider(rows, rng, bad, name, "Psychiatry", "CLN02", codes, w,
                   3.8, active_days=120, months={7, 8, 9, 10, 11, 12})
    return pd.DataFrame(rows), [{"provider_id": bad,
        "scheme": "Temporal billing spike (sudden-onset)",
        "expect": "temporal flag: CUSUM change-point / spike mid-year"}]


SCENARIOS = {
    "claims_internalmed_upcoding.csv":   (scenario_upcoding,       101),
    "claims_radiology_overimaging.csv":  (scenario_overimaging,    102),
    "claims_familymed_impossibleday.csv": (scenario_impossible_day, 103),
    "claims_cardiology_unbundling.csv":  (scenario_unbundling,     104),
    "claims_psychiatry_temporalspike.csv": (scenario_temporal_spike, 105),
}


def main():
    global _claim_seq
    answer_key = {}
    for fname, (builder, seed) in SCENARIOS.items():
        _claim_seq = 0
        df, bad_actors = builder(seed)
        df = df.sort_values(["service_date", "provider_id"]).reset_index(drop=True)
        out = os.path.join(HERE, fname)
        df.to_csv(out, index=False)
        answer_key[fname] = {
            "rows": len(df),
            "providers": int(df.provider_id.nunique()),
            "specialty": df.specialty.iloc[0],
            "bad_actors": bad_actors,
        }
        print(f"  {fname:38} {len(df):>7,} rows  {df.provider_id.nunique():>3} providers"
              f"  bad: {[b['provider_id'] for b in bad_actors]}")
    with open(os.path.join(HERE, "ANSWER_KEY.json"), "w") as fh:
        json.dump(answer_key, fh, indent=2)
    print("  ANSWER_KEY.json written.")


if __name__ == "__main__":
    main()
