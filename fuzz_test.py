"""fuzz_test.py -- Fuzz / chaos test harness for the billing anomaly pipeline.

Run: python fuzz_test.py

Feeds every module adversarial DataFrames and CSV files, records outcomes,
prints a structured result table, and summarises CRASH / SILENT_BAD / GRACEFUL / OK.
"""

import io
import os
import sys
import tempfile
import traceback
import warnings

import numpy as np
import pandas as pd

# ── Output helpers ─────────────────────────────────────────────────────────────

OUTCOMES = []   # list of dicts

_COL_W = {
    "outcome": 14,
    "module":  14,
    "case":    28,
    "detail":  60,
}


def _record(outcome: str, module: str, case: str, detail: str = ""):
    OUTCOMES.append({
        "outcome": outcome,
        "module":  module,
        "case":    case,
        "detail":  detail[:200],
    })
    tag = f"[{outcome}]".ljust(_COL_W["outcome"])
    mod = module.ljust(_COL_W["module"])
    cas = case.ljust(_COL_W["case"])
    print(f"{tag} {mod} {cas} {detail[:_COL_W['detail']]}")


# ── Minimal valid claims DataFrame factory ────────────────────────────────────

REQUIRED_COLS = [
    "claim_id", "provider_id", "provider_name", "patient_id", "fee_code",
    "service_date", "service_minutes", "amount_billed", "specialty", "clinic_id",
]


def _base_row(n: int = 20) -> dict:
    return {
        "claim_id":        [f"CLM{i:05d}" for i in range(n)],
        "provider_id":     [f"PRV{(i % 5):04d}" for i in range(n)],
        "provider_name":   [f"Doctor {i % 5}" for i in range(n)],
        "patient_id":      [f"PAT{i:05d}" for i in range(n)],
        "fee_code":        ["99213"] * n,
        "service_date":    pd.date_range("2024-01-01", periods=n, freq="D").tolist(),
        "service_minutes": [20] * n,
        "amount_billed":   [85.0] * n,
        "specialty":       ["Family Medicine"] * n,
        "clinic_id":       ["C001"] * n,
    }


def _make(n: int = 20, **overrides) -> pd.DataFrame:
    d = _base_row(n)
    d.update(overrides)
    return pd.DataFrame(d)


# ── 2a. Adversarial DataFrames ─────────────────────────────────────────────────

def case_negative_values():
    return _make(service_minutes=[-9999] * 20, amount_billed=[-0.01] * 20)

def case_zero_values():
    return _make(service_minutes=[0] * 20, amount_billed=[0.0] * 20)

def case_huge_values():
    return _make(service_minutes=[99_999_999] * 20, amount_billed=[9_999_999_999.99] * 20)

def case_null_provider():
    d = _base_row()
    pids = list(d["provider_id"])
    for i in range(0, len(pids), 2):
        pids[i] = None
    for i in range(1, len(pids), 4):
        pids[i] = ""
    d["provider_id"] = pids
    return pd.DataFrame(d)

def case_null_fee_code():
    d = _base_row()
    d["fee_code"] = [None if i % 3 == 0 else "99213" for i in range(20)]
    return pd.DataFrame(d)

def case_null_specialty():
    d = _base_row()
    d["specialty"] = [None if i % 2 == 0 else "Family Medicine" for i in range(20)]
    return pd.DataFrame(d)

def case_null_date():
    d = _base_row()
    d["service_date"] = [None if i % 3 == 0 else pd.Timestamp("2024-01-01")
                         for i in range(20)]
    return pd.DataFrame(d)

def case_far_future_date():
    return _make(service_date=[pd.Timestamp("3000-01-01")] * 20)

def case_far_past_date():
    return _make(service_date=[pd.Timestamp("1900-06-15")] * 20)

def case_malformed_date():
    d = _base_row(9)
    d["service_date"] = ["not-a-date", "32/13/2024", "", "2024-01-01",
                          "2024-13-01", "00/00/0000", "2024-01-01",
                          "2024/31/12", "abc"]
    return pd.DataFrame(d)

def case_wrong_type_minutes():
    d = _base_row()
    d["service_minutes"] = (["hello", True, [1, 2, 3]] * 7)[:20]
    df = pd.DataFrame(d)
    df["service_minutes"] = df["service_minutes"].astype(object)
    return df

def case_duplicate_claim_ids():
    d = _base_row()
    d["claim_id"] = ["DUPE0001"] * 20   # all same claim_id
    return pd.DataFrame(d)

def case_unicode_provider():
    d = _base_row()
    d["provider_id"]   = ["PRV_\U0001F600_∞"] * 20
    d["provider_name"] = ["Dr ∞ Unicode"] * 20
    d["specialty"]     = ["Cardiology™ → Neurology"] * 20
    return pd.DataFrame(d)

def case_empty_df():
    return pd.DataFrame(columns=REQUIRED_COLS)

def case_single_row():
    return _make(1)

def case_single_provider():
    return _make(20)   # default already uses same PRV0000 for all rows?
    # Actually default uses PRV0000-PRV0004, so override:

def case_single_provider_real():
    d = _base_row()
    d["provider_id"]   = ["PRV0000"] * 20
    d["provider_name"] = ["Doctor 0"] * 20
    return pd.DataFrame(d)

def case_all_same_specialty():
    return _make(20)   # default already all same specialty

def case_all_same_date():
    return _make(service_date=[pd.Timestamp("2024-01-01")] * 20)

def case_missing_col_specialty():
    return _make().drop(columns=["specialty"])

def case_missing_col_fee_code():
    return _make().drop(columns=["fee_code"])

def case_missing_col_service_minutes():
    return _make().drop(columns=["service_minutes"])

def case_extra_columns():
    df = _make()
    df["foo"]      = "bar"
    df["bar"]      = 42
    df["injected"] = "<script>alert(1)</script>"
    return df

def case_all_nulls():
    df = _make()
    return pd.DataFrame(np.nan, index=df.index, columns=df.columns)


DATAFRAME_CASES = {
    "negative_values":        case_negative_values,
    "zero_values":            case_zero_values,
    "huge_values":            case_huge_values,
    "null_provider":          case_null_provider,
    "null_fee_code":          case_null_fee_code,
    "null_specialty":         case_null_specialty,
    "null_date":              case_null_date,
    "far_future_date":        case_far_future_date,
    "far_past_date":          case_far_past_date,
    "malformed_date":         case_malformed_date,
    "wrong_type_minutes":     case_wrong_type_minutes,
    "duplicate_claim_ids":    case_duplicate_claim_ids,
    "unicode_provider":       case_unicode_provider,
    "empty_df":               case_empty_df,
    "single_row":             case_single_row,
    "single_provider":        case_single_provider_real,
    "all_same_specialty":     case_all_same_specialty,
    "all_same_date":          case_all_same_date,
    "missing_col_specialty":  case_missing_col_specialty,
    "missing_col_fee_code":   case_missing_col_fee_code,
    "missing_col_svc_mins":   case_missing_col_service_minutes,
    "extra_columns":          case_extra_columns,
    "all_nulls":              case_all_nulls,
}


# ── 2b. CSV fuzz cases ─────────────────────────────────────────────────────────

HEADER = "claim_id,provider_id,provider_name,patient_id,fee_code,service_date,service_minutes,amount_billed,specialty,clinic_id\n"
GOOD_ROW = "CLM00001,PRV0001,Doctor 1,PAT00001,99213,2024-01-15,20,85.0,Family Medicine,C001\n"


def _write_temp(content: bytes, suffix: str = ".csv") -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(content)
    return path


def make_csv_cases() -> dict:
    cases = {}

    # 22. empty csv
    cases["empty_csv"] = _write_temp(b"")

    # 23. header only
    cases["header_only_csv"] = _write_temp(HEADER.encode())

    # 24. truncated mid-row
    full = (HEADER + GOOD_ROW * 5).encode()
    cases["truncated_csv"] = _write_temp(full[:len(full) // 2])

    # 25. pipe-delimited
    pipe = HEADER.replace(",", "|") + GOOD_ROW.replace(",", "|")
    cases["wrong_delimiter_csv"] = _write_temp(pipe.encode())

    # 26. extra cols
    extra_hdr = HEADER.rstrip("\n") + ",extra_col1,extra_col2\n"
    extra_row = GOOD_ROW.rstrip("\n") + ",hello,42\n"
    cases["extra_cols_csv"] = _write_temp((extra_hdr + extra_row * 5).encode())

    # 27. missing required col (no 'amount_billed')
    cols_no_amount = [c for c in HEADER.rstrip("\n").split(",") if c != "amount_billed"]
    bad_hdr = ",".join(cols_no_amount) + "\n"
    bad_row_vals = GOOD_ROW.rstrip("\n").split(",")
    # amount_billed is column index 7 — remove it
    bad_row_vals.pop(7)
    bad_row = ",".join(bad_row_vals) + "\n"
    cases["missing_required_col_csv"] = _write_temp((bad_hdr + bad_row * 5).encode())

    # 28. binary garbage
    cases["binary_garbage"] = _write_temp(os.urandom(4096))

    # 29. huge csv (200 000 rows)
    rows = [HEADER]
    for i in range(200_000):
        pid   = f"PRV{(i % 100):04d}"
        date_ = f"2024-{(i % 12 + 1):02d}-{(i % 28 + 1):02d}"
        rows.append(
            f"CLM{i:07d},{pid},Doctor {i%100},PAT{i:07d},99213,"
            f"{date_},20,85.0,Family Medicine,C001\n"
        )
    cases["huge_repeated_csv"] = _write_temp("".join(rows).encode())

    return cases


# ── 2c. Module fuzz runner ─────────────────────────────────────────────────────

def _run(fn, *args, **kwargs):
    """Run fn(*args, **kwargs), suppress stdout/stderr, return (result, exc)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            result = fn(*args, **kwargs)
            return result, None
        except Exception as exc:
            return None, exc


def _classify_result(result, exc, case_name: str, module: str) -> tuple[str, str]:
    """Return (outcome, detail)."""
    if exc is not None:
        # Check if it's a graceful validation error
        exc_type = type(exc).__name__
        msg = str(exc)
        if isinstance(exc, (ValueError, TypeError)) and (
            "Missing columns" in msg
            or "Expected a pandas" in msg
            or "missing" in msg.lower()
        ):
            return "GRACEFUL", f"{exc_type}: {msg[:120]}"
        return "CRASH", f"{exc_type}: {msg[:120]}"

    # No exception — check result quality
    if result is None:
        return "SILENT_BAD", "returned None with no exception"

    # Unpack tuple results (peer_stats, codemix, temporal return (scores, flags))
    main_result = result[0] if isinstance(result, tuple) else result

    if isinstance(main_result, pd.DataFrame):
        if len(main_result) == 0:
            return "GRACEFUL", "returned empty DataFrame (OK for empty/invalid input)"
        return "OK", f"returned DataFrame with {len(main_result)} rows"

    return "OK", f"returned {type(main_result).__name__}"


def fuzz_rules(df: pd.DataFrame, case_name: str):
    """Test rules.run_rules(df)."""
    from rules import run_rules
    result, exc = _run(run_rules, df)
    outcome, detail = _classify_result(result, exc, case_name, "rules")
    _record(outcome, "rules", case_name, detail)


def fuzz_peer_stats(df: pd.DataFrame, case_name: str):
    """Test peer_stats.run_peer_stats(df)."""
    from peer_stats import run_peer_stats
    result, exc = _run(run_peer_stats, df)
    outcome, detail = _classify_result(result, exc, case_name, "peer_stats")
    _record(outcome, "peer_stats", case_name, detail)


def _make_minimal_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Build a minimal provider_metrics-like DataFrame from df for codemix."""
    if df.empty or "provider_id" not in df.columns:
        return pd.DataFrame(columns=[
            "provider_id", "provider_name", "specialty", "cohort_key",
            "practice_setting", "total_billed",
        ])
    from peer_stats import build_provider_metrics, zscore_within_cohort
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m = build_provider_metrics(df)
            m = zscore_within_cohort(m)
            return m
    except Exception:
        return pd.DataFrame(columns=[
            "provider_id", "provider_name", "specialty", "cohort_key",
            "practice_setting", "total_billed",
        ])


def fuzz_codemix(df: pd.DataFrame, case_name: str):
    """Test codemix.run_codemix(df, metrics_df)."""
    from codemix import run_codemix
    metrics_df = _make_minimal_metrics(df)
    result, exc = _run(run_codemix, df, metrics_df)
    outcome, detail = _classify_result(result, exc, case_name, "codemix")
    _record(outcome, "codemix", case_name, detail)


def fuzz_temporal(df: pd.DataFrame, case_name: str):
    """Test temporal.run_temporal(df)."""
    from temporal import run_temporal
    result, exc = _run(run_temporal, df)
    outcome, detail = _classify_result(result, exc, case_name, "temporal")
    _record(outcome, "temporal", case_name, detail)


def fuzz_anomaly_model(df: pd.DataFrame, case_name: str):
    """Test anomaly_model.build_feature_matrix(df)."""
    from anomaly_model import build_feature_matrix
    result, exc = _run(build_feature_matrix, df)
    outcome, detail = _classify_result(result, exc, case_name, "anomaly_model")
    _record(outcome, "anomaly_model", case_name, detail)


# ── 2d. Scoring CSV fuzz ───────────────────────────────────────────────────────

def fuzz_scoring_csv(case_label: str, risk_csv_content: str):
    """Write a fuzzed risk_scores.csv and test whether scoring.validate_risk_scores_df
    handles it cleanly (warns but doesn't crash, and corrects bad values).
    """
    from scoring import validate_risk_scores_df

    fd, tmp_path = tempfile.mkstemp(suffix=".csv")

    # Write the fuzzed risk CSV content
    with os.fdopen(fd, "w") as f:
        f.write(risk_csv_content)

    try:
        # Step 1: read the CSV
        df_read, read_exc = _run(pd.read_csv, tmp_path, dtype={"provider_id": str})
        if read_exc:
            _record("GRACEFUL", "scoring_csv", case_label,
                    f"read_csv raised {type(read_exc).__name__}: {str(read_exc)[:80]}")
            return

        if df_read is None or df_read.empty:
            _record("GRACEFUL", "scoring_csv", case_label,
                    "read_csv returned empty DataFrame")
            return

        # Step 2: apply validate_risk_scores_df — this should warn+fix, not crash
        with warnings.catch_warnings(record=True) as w_list:
            warnings.simplefilter("always")
            validated, val_exc = _run(validate_risk_scores_df, df_read)

        if val_exc:
            exc_type = type(val_exc).__name__
            msg = str(val_exc)
            # ValueError for missing risk_score column is GRACEFUL
            if isinstance(val_exc, (ValueError, TypeError)):
                _record("GRACEFUL", "scoring_csv", case_label,
                        f"{exc_type}: {msg[:80]}")
            else:
                _record("CRASH", "scoring_csv", case_label,
                        f"{exc_type}: {msg[:80]}")
            return

        # Step 3: verify bad values have been fixed
        if validated is not None and "risk_score" in validated.columns:
            n_nan  = int(validated["risk_score"].isna().sum())
            n_neg  = int((validated["risk_score"].dropna() < 0).sum())
            n_over = int((validated["risk_score"].dropna() > 100).sum())
            if n_nan or n_neg or n_over:
                issues = []
                if n_nan:  issues.append(f"{n_nan} NaN scores remain")
                if n_neg:  issues.append(f"{n_neg} negative scores remain")
                if n_over: issues.append(f"{n_over} scores >100 remain")
                _record("SILENT_BAD", "scoring_csv", case_label,
                        "validate_risk_scores_df did not fix: " + ", ".join(issues))
                return

            warned = len([x for x in w_list if issubclass(x.category, UserWarning)])
            if warned:
                _record("GRACEFUL", "scoring_csv", case_label,
                        f"validate_risk_scores_df fixed issues with {warned} warning(s)")
            else:
                _record("OK", "scoring_csv", case_label,
                        f"validated {len(validated)} rows, all scores in range")
        else:
            _record("OK", "scoring_csv", case_label,
                    f"read_csv returned {len(df_read)} rows; no risk_score column to validate")
    finally:
        os.unlink(tmp_path)


def run_scoring_csv_fuzz():
    """Section 2d: fuzz scoring.py with malformed risk_scores CSVs."""
    valid_hdr = (
        "provider_id,provider_name,specialty,risk_score,confidence,"
        "estimated_exposure,expected_recovery,rules_score,peer_score,"
        "ml_score,ml_is_anomaly,codemix_score,codemix_flag,"
        "kl_divergence,cosine_distance,temporal_score,temporal_flag,"
        "feedback_score,feedback_label,top_reason\n"
    )
    good_row = (
        "PRV0001,Doctor 1,Family Medicine,45.0,HIGH,"
        "12000.0,8400.0,35,5,30.0,1,2.0,0,"
        "0.05,0.10,2.5,0,0.0,0,Rule: duplicate_billing\n"
    )

    # NaN in score column
    nan_row = (
        "PRV0002,Doctor 2,Cardiology,,MEDIUM,"
        "5000.0,2000.0,0,5,20.0,0,1.0,0,"
        "0.02,0.05,0.0,0,0.0,0,no flags\n"
    )
    fuzz_scoring_csv("nan_score", valid_hdr + good_row + nan_row)

    # Negative scores
    neg_row = (
        "PRV0003,Doctor 3,Radiology,-10.0,LOW,"
        "3000.0,450.0,0,0,5.0,0,0.5,0,"
        "0.01,0.02,0.0,0,0.0,0,no flags\n"
    )
    fuzz_scoring_csv("negative_score", valid_hdr + neg_row)

    # Scores > 100
    over_row = (
        "PRV0004,Doctor 4,Surgery,150.0,HIGH,"
        "50000.0,35000.0,50,25,15.0,1,10.0,1,"
        "0.8,0.5,5.0,1,0.0,0,Rule: impossible_day\n"
    )
    fuzz_scoring_csv("score_over_100", valid_hdr + over_row)

    # Missing required column (no risk_score)
    no_score_hdr = valid_hdr.replace("risk_score,", "")
    no_score_row = good_row.replace("45.0,HIGH,", "HIGH,")
    fuzz_scoring_csv("missing_risk_score_col", no_score_hdr + no_score_row)

    # Empty file
    fuzz_scoring_csv("empty_risk_csv", "")

    # Header only
    fuzz_scoring_csv("header_only_risk_csv", valid_hdr)


# ── 2b. CSV read fuzz ─────────────────────────────────────────────────────────

def run_csv_fuzz(csv_cases: dict):
    """Test pd.read_csv behaviour on all CSV fuzz cases."""
    for case_name, path in csv_cases.items():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                df = pd.read_csv(path, dtype={"provider_id": str, "fee_code": str})
                if df is None or df.empty:
                    _record("GRACEFUL", "pd.read_csv", case_name,
                            "returned empty DataFrame")
                else:
                    # Check for silent coercions that could propagate downstream
                    issues = []
                    if "service_date" in df.columns:
                        df["service_date"] = pd.to_datetime(
                            df["service_date"], errors="coerce"
                        )
                        n_nat = df["service_date"].isna().sum()
                        if n_nat:
                            issues.append(f"{n_nat} NaT dates")
                    if "service_minutes" in df.columns:
                        n_bad = pd.to_numeric(
                            df["service_minutes"], errors="coerce"
                        ).isna().sum()
                        if n_bad:
                            issues.append(f"{n_bad} non-numeric service_minutes")
                    if issues:
                        _record("SILENT_BAD", "pd.read_csv", case_name,
                                "silently loaded with issues: " + ", ".join(issues))
                    else:
                        _record("OK", "pd.read_csv", case_name,
                                f"loaded {len(df)} rows without issue")
            except Exception as exc:
                exc_type = type(exc).__name__
                _record("GRACEFUL", "pd.read_csv", case_name,
                        f"raised {exc_type}: {str(exc)[:80]}")
        # Clean up temp files
        try:
            os.unlink(path)
        except OSError:
            pass


# ── Main orchestration ────────────────────────────────────────────────────────

def run_dataframe_fuzz():
    """Run all adversarial DataFrames through every module."""
    module_fuzzers = [
        ("rules",        fuzz_rules),
        ("peer_stats",   fuzz_peer_stats),
        ("codemix",      fuzz_codemix),
        ("temporal",     fuzz_temporal),
        ("anomaly_model", fuzz_anomaly_model),
    ]

    for case_name, case_fn in DATAFRAME_CASES.items():
        df = case_fn()
        for _mod_label, fuzzer in module_fuzzers:
            fuzzer(df, case_name)


def print_summary():
    counts = {"CRASH": 0, "SILENT_BAD": 0, "GRACEFUL": 0, "OK": 0}
    for r in OUTCOMES:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    for k, v in counts.items():
        print(f"  {k:<12} : {v}")
    print(f"  {'TOTAL':<12} : {sum(counts.values())}")
    print()

    # Print crashes and silent bads for visibility
    crashes = [r for r in OUTCOMES if r["outcome"] == "CRASH"]
    silents = [r for r in OUTCOMES if r["outcome"] == "SILENT_BAD"]

    if crashes:
        print(f"CRASHES ({len(crashes)}):")
        for r in crashes:
            print(f"  {r['module']:<14} {r['case']:<28} {r['detail']}")
        print()

    if silents:
        print(f"SILENT_BAD ({len(silents)}):")
        for r in silents:
            print(f"  {r['module']:<14} {r['case']:<28} {r['detail']}")
        print()

    return counts


if __name__ == "__main__":
    print("=" * 80)
    print("BILLING ANOMALY PIPELINE -- FUZZ / CHAOS TEST HARNESS")
    print("=" * 80)
    print()
    print(f"{'[OUTCOME]':<14} {'MODULE':<14} {'CASE':<28} DETAIL")
    print("-" * 80)

    # Section 2a + 2c: DataFrame fuzz through all modules
    run_dataframe_fuzz()

    print()
    print("--- CSV fuzz (pd.read_csv) ---")
    csv_cases = make_csv_cases()
    run_csv_fuzz(csv_cases)

    print()
    print("--- Scoring CSV fuzz ---")
    run_scoring_csv_fuzz()

    # Final summary
    counts = print_summary()

    # Exit code: non-zero if any CRASHes remain
    sys.exit(1 if counts.get("CRASH", 0) > 0 else 0)
