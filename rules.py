"""Phase 2 — Deterministic rule-based anomaly checks.

Three high-confidence rules:
  1. Impossible-day   : provider billed > 1 440 service-minutes in a single day
  2. Duplicate billing: identical provider + patient + fee_code + service_date
  3. Unbundling       : component codes 93005 + 93010 billed same patient/date
                        instead of the bundle 93000

Outputs rules_flags.csv (one row per flag event) and prints a summary.
"""

import pandas as pd

INPUT_CSV  = "claims.csv"
OUTPUT_CSV = "rules_flags.csv"

BUNDLE_RULES = [
    {
        "components":   frozenset({"93005", "93010"}),
        "bundle_code":  "93000",
        "bundle_desc":  "ECG Complete",
        "bundle_amt":   70.00,
    },
]


def load_claims() -> pd.DataFrame:
    return pd.read_csv(INPUT_CSV, parse_dates=["service_date"],
                       dtype={"fee_code": str, "provider_id": str,
                              "patient_id": str, "clinic_id": str})


# ── Rule 1: impossible day ───────────────────────────────────────────────────

def check_impossible_days(df: pd.DataFrame) -> pd.DataFrame:
    day_mins = (
        df.groupby(["provider_id", "provider_name", "specialty", "service_date"])
          .agg(total_minutes=("service_minutes", "sum"),
               n_claims=("claim_id", "count"),
               total_billed=("amount_billed", "sum"))
          .reset_index()
    )
    bad = day_mins[day_mins["total_minutes"] > 1_440].copy()
    if bad.empty:
        return pd.DataFrame()

    bad["rule"]     = "impossible_day"
    bad["evidence"] = bad.apply(
        lambda r: (f"Billed {r['total_minutes']:,} service-minutes on "
                   f"{r['service_date'].date()} across {r['n_claims']} claims "
                   f"(max 1 440 per day)"),
        axis=1,
    )
    # Exposure = amount billed on that day (all of it is suspect)
    bad["estimated_exposure"] = bad["total_billed"].round(2)
    return bad[["provider_id", "provider_name", "specialty",
                "rule", "evidence", "estimated_exposure"]]


# ── Rule 2: duplicate billing ────────────────────────────────────────────────

def check_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    key = ["provider_id", "patient_id", "fee_code", "service_date"]
    dup_counts = (
        df.groupby(key)
          .agg(n=("claim_id", "count"),
               total_billed=("amount_billed", "sum"),
               unit_billed=("amount_billed", "first"))
          .reset_index()
    )
    dup_counts = dup_counts[dup_counts["n"] > 1].copy()
    if dup_counts.empty:
        return pd.DataFrame()

    # Merge provider name / specialty back
    prov_meta = df[["provider_id", "provider_name", "specialty"]].drop_duplicates("provider_id")
    dup_counts = dup_counts.merge(prov_meta, on="provider_id")

    # Per-provider aggregation
    by_prov = (
        dup_counts.groupby(["provider_id", "provider_name", "specialty"])
                  .agg(n_dup_events=("n", "count"),
                       total_extra_billed=("unit_billed", "sum"))
                  .reset_index()
    )
    by_prov["rule"]     = "duplicate_billing"
    by_prov["evidence"] = by_prov.apply(
        lambda r: (f"{r['n_dup_events']} duplicate claim events "
                   f"(same provider + patient + code + date billed >1 time)"),
        axis=1,
    )
    by_prov["estimated_exposure"] = by_prov["total_extra_billed"].round(2)
    return by_prov[["provider_id", "provider_name", "specialty",
                     "rule", "evidence", "estimated_exposure"]]


# ── Rule 3: unbundling ────────────────────────────────────────────────────────

def check_unbundling(df: pd.DataFrame) -> pd.DataFrame:
    flags = []
    for rule in BUNDLE_RULES:
        components   = list(rule["components"])
        bundle_code  = rule["bundle_code"]
        bundle_desc  = rule["bundle_desc"]
        bundle_amt   = rule["bundle_amt"]

        # Keep only rows for component codes
        comp_df = df[df["fee_code"].isin(components)].copy()
        if comp_df.empty:
            continue

        # Count distinct component codes per provider+patient+date
        pivot = (
            comp_df.groupby(["provider_id", "patient_id", "service_date"])["fee_code"]
                   .apply(lambda x: frozenset(x))
                   .reset_index()
                   .rename(columns={"fee_code": "code_set"})
        )
        unbundled = pivot[pivot["code_set"] == rule["components"]].copy()
        if unbundled.empty:
            continue

        # Calculate exposure per event: sum of components billed minus bundle price
        comp_totals = (
            comp_df[comp_df["fee_code"].isin(components)]
            .groupby(["provider_id", "patient_id", "service_date"])
            .agg(comp_total=("amount_billed", "sum"))
            .reset_index()
        )
        unbundled = unbundled.merge(comp_totals, on=["provider_id", "patient_id", "service_date"])
        unbundled["event_overcharge"] = (unbundled["comp_total"] - bundle_amt).clip(lower=0)

        by_prov = (
            unbundled.groupby("provider_id")
                     .agg(n_events=("patient_id", "count"),
                          total_overcharge=("event_overcharge", "sum"))
                     .reset_index()
        )
        prov_meta = df[["provider_id", "provider_name", "specialty"]].drop_duplicates("provider_id")
        by_prov = by_prov.merge(prov_meta, on="provider_id")
        by_prov["rule"]     = "unbundling"
        by_prov["evidence"] = by_prov.apply(
            lambda r: (f"Billed {r['n_events']} patient-dates with component codes "
                       f"{components[0]}+{components[1]} instead of bundle {bundle_code} "
                       f"({bundle_desc})"),
            axis=1,
        )
        by_prov["estimated_exposure"] = by_prov["total_overcharge"].round(2)
        flags.append(by_prov[["provider_id", "provider_name", "specialty",
                                "rule", "evidence", "estimated_exposure"]])

    return pd.concat(flags) if flags else pd.DataFrame()


# ── Main ─────────────────────────────────────────────────────────────────────

def run_rules(df: pd.DataFrame = None) -> pd.DataFrame:
    if df is None:
        df = load_claims()

    parts = [
        check_impossible_days(df),
        check_duplicates(df),
        check_unbundling(df),
    ]
    non_empty = [p for p in parts if not p.empty]
    if not non_empty:
        flags = pd.DataFrame(columns=["provider_id", "provider_name", "specialty",
                                       "rule", "evidence", "estimated_exposure"])
    else:
        flags = pd.concat(non_empty, ignore_index=True)
    flags.to_csv(OUTPUT_CSV, index=False)
    return flags


def main():
    print("Phase 2 - Deterministic Rule Checks")
    print("=" * 60)
    df    = load_claims()
    flags = run_rules(df)

    if flags.empty:
        print("  No rule violations detected.")
        return

    print(f"  Total flag records : {len(flags)}")
    print(f"  Flagged providers  : {flags['provider_id'].nunique()}")
    print(f"  Total exposure     : ${flags['estimated_exposure'].sum():,.2f}")
    print()

    for rule, grp in flags.groupby("rule"):
        print(f"  Rule: {rule.upper()}")
        print(f"  {'Provider':<12} {'Specialty':<18} {'Exposure':>12}  Evidence")
        print("  " + "-" * 80)
        for _, row in grp.iterrows():
            ev = (row["evidence"][:65] + "...") if len(row["evidence"]) > 65 else row["evidence"]
            print(f"  {row['provider_id']:<12} {row['specialty']:<18} "
                  f"${row['estimated_exposure']:>10,.2f}  {ev}")
        print()

    print(f"  Saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
