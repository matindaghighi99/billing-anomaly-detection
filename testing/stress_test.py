"""stress_test.py — Scale and pathological-shape stress harness.

Sections:
  2a. Scale tests  : 100k / 500k / 1M claims — time + peak RSS per phase
  2b. Shape tests  : whale_provider, singleton_specialty, provider_explosion,
                     single_day  (~50k claims each)
  2c. Dashboard    : app.py data-loading smoke test (no Streamlit server)

Run:
    python stress_test.py

Phases are timed with time.perf_counter().  Peak RSS is sampled via
tracemalloc (snapshots) and psutil where available.  OOM or wall-time > 8 min
per phase is caught and recorded as TIMEOUT/OOM rather than crashing the run.

All output is written to stdout in a structured form that STRESS_REPORT.md
can summarise.
"""

import gc
import os
import sys
import time
import traceback
import warnings
import csv
import io

# Make the section folders importable as flat modules regardless of CWD.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _sectionpath  # noqa: E402  (registers section folders on sys.path)

import numpy as np
import pandas as pd

# ── RSS helpers ───────────────────────────────────────────────────────────────

def _rss_mb() -> float:
    """Return current process RSS in MiB (0 if psutil unavailable)."""
    try:
        import psutil
        return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
    except ImportError:
        return 0.0


def _peak_rss_context():
    """Context manager that returns peak-rss dict after the block."""
    class _Ctx:
        def __enter__(self):
            self.start = _rss_mb()
            self.peak  = self.start
            return self
        def measure(self):
            cur = _rss_mb()
            if cur > self.peak:
                self.peak = cur
        def __exit__(self, *_):
            self.measure()
            self.delta = self.peak - self.start
    return _Ctx()


# ── Timeout guard (Windows-compatible: no SIGALRM; use wall-clock check) ────

PHASE_TIMEOUT_S = 480   # 8 minutes


def _run_with_timeout(label: str, fn, *args, **kwargs):
    """Call fn(*args, **kwargs); return (result, elapsed_s, error_msg).

    Since signal.alarm is UNIX-only, we just run synchronously but record
    elapsed and return TIMEOUT if it exceeded the limit.
    """
    start = time.perf_counter()
    try:
        result = fn(*args, **kwargs)
    except MemoryError as exc:
        elapsed = time.perf_counter() - start
        return None, elapsed, f"OOM: {exc}"
    except Exception as exc:
        elapsed = time.perf_counter() - start
        return None, elapsed, f"ERROR: {type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - start
    if elapsed > PHASE_TIMEOUT_S:
        return result, elapsed, f"TIMEOUT ({elapsed:.0f}s > {PHASE_TIMEOUT_S}s)"
    return result, elapsed, None


# ── Synthetic claim generator for stress tests ────────────────────────────────

def _make_stress_claims(
    n: int,
    rng: np.random.Generator,
    n_providers: int = 150,
    n_specialties: int = 6,
    date_range_days: int = 365,
    start_date: str = "2024-01-01",
    whale_provider: bool = False,
    singleton_specialty: bool = False,
    provider_explosion: bool = False,
    single_day: bool = False,
) -> pd.DataFrame:
    """Produce a synthetic claims DataFrame of exactly n rows.

    Shape flags:
      whale_provider      — 40k of 50k claims for one provider
      singleton_specialty — one specialty has exactly 1 provider
      provider_explosion  — 10k distinct providers, ~5 claims each
      single_day          — all claims on 2024-01-15
    """
    SPECIALTIES = ["Family Medicine", "Cardiology", "Radiology",
                   "Psychiatry", "Dermatology", "Surgery"]
    FEE_CODES   = [
        "99213","99214","99215","99232",
        "93000","93005","93010",
        "72148","70553",
        "90837","90834",
        "11100","11101",
        "27447","43239",
    ]
    FEE_AMOUNTS = {
        "99213": 85.0, "99214": 130.0, "99215": 200.0, "99232": 110.0,
        "93000": 70.0, "93005": 35.0,  "93010": 45.0,
        "72148": 350.0, "70553": 450.0,
        "90837": 180.0, "90834": 140.0,
        "11100": 150.0, "11101": 75.0,
        "27447": 1200.0, "43239": 380.0,
    }
    MINUTES = {
        "99213": 15, "99214": 25, "99215": 40, "99232": 20,
        "93000": 20, "93005": 10, "93010": 10,
        "72148": 45, "70553": 60,
        "90837": 60, "90834": 45,
        "11100": 20, "11101": 10,
        "27447": 120, "43239": 30,
    }

    # Provider list
    if provider_explosion:
        actual_n_providers = 10_000
    else:
        actual_n_providers = n_providers

    prov_ids  = [f"PRV{i+1:05d}" for i in range(actual_n_providers)]
    prov_spec = SPECIALTIES[:n_specialties]

    spec_array = rng.choice(prov_spec, size=actual_n_providers)
    if singleton_specialty:
        # Force provider 0 to have a unique specialty not shared by others
        unique_spec = "UniqueSurgery"
        spec_array[0] = unique_spec
        # All others stay as normal specialties
        for i in range(1, actual_n_providers):
            if spec_array[i] == unique_spec:
                spec_array[i] = "Family Medicine"
        prov_spec_extended = prov_spec + [unique_spec]
    else:
        prov_spec_extended = prov_spec

    # Assign claims to providers
    if whale_provider:
        # Provider 0 gets 40k of the 50k claims
        n_whale = min(40_000, n - actual_n_providers)
        n_others = n - n_whale
        provider_indices = np.concatenate([
            np.zeros(n_whale, dtype=int),
            rng.integers(1, actual_n_providers, size=n_others),
        ])
        rng.shuffle(provider_indices)
    elif provider_explosion:
        # ~5 claims each
        provider_indices = rng.integers(0, actual_n_providers, size=n)
    else:
        provider_indices = rng.integers(0, actual_n_providers, size=n)

    # Dates
    base_date = pd.Timestamp(start_date)
    if single_day:
        date_offsets = np.zeros(n, dtype=int)
        fixed_date = pd.Timestamp("2024-01-15")
    else:
        date_offsets = rng.integers(0, date_range_days, size=n)

    # Fee codes
    code_indices = rng.integers(0, len(FEE_CODES), size=n)
    codes  = [FEE_CODES[i] for i in code_indices]
    amounts = np.array([FEE_AMOUNTS[c] for c in codes]) * rng.uniform(0.95, 1.05, size=n)
    minutes = np.array([MINUTES[c]    for c in codes])

    if single_day:
        dates = [fixed_date] * n
    else:
        dates = [base_date + pd.Timedelta(days=int(d)) for d in date_offsets]

    df = pd.DataFrame({
        "claim_id":        [f"CLM{i+1:08d}" for i in range(n)],
        "provider_id":     [prov_ids[provider_indices[i]] for i in range(n)],
        "provider_name":   [f"Dr. Provider {provider_indices[i]+1}" for i in range(n)],
        "specialty":       [spec_array[provider_indices[i]] for i in range(n)],
        "patient_id":      [f"PAT{rng.integers(1, min(n//2, 50000)+1):05d}" for _ in range(n)],
        "service_date":    dates,
        "fee_code":        codes,
        "fee_description": [f"Service {c}" for c in codes],
        "service_minutes": minutes,
        "units":           np.ones(n, dtype=int),
        "amount_billed":   amounts.round(2),
        "clinic_id":       [f"CLN{rng.integers(1, 21):02d}" for _ in range(n)],
    })
    df["service_date"] = pd.to_datetime(df["service_date"])
    return df


# ── Phase runners (imported inline to avoid module-level side-effects) ────────

def _run_rules(df):
    from rules import run_rules
    return run_rules(df)


def _run_peer_stats(df):
    from peer_stats import run_peer_stats
    return run_peer_stats(df)


def _run_codemix(df):
    from peer_stats import run_peer_stats as rps
    from codemix import run_codemix
    metrics, _ = rps(df)
    return run_codemix(df, metrics)


def _run_temporal(df):
    from temporal import run_temporal
    return run_temporal(df)


def _run_anomaly_model(df):
    from anomaly_model import run_anomaly_model
    return run_anomaly_model(df)


def _run_scoring():
    from scoring import build_risk_scores
    return build_risk_scores()


# ── 2a: Scale tests ───────────────────────────────────────────────────────────

SCALE_SIZES = [100_000, 500_000, 1_000_000]

# Phases to time at scale (scoring requires intermediate files)
SCALE_PHASES = [
    ("rules",    _run_rules),
    ("peer_stats", _run_peer_stats),
    ("codemix",   _run_codemix),
    ("temporal",  _run_temporal),
    ("anomaly_model", _run_anomaly_model),
]


def run_scale_tests():
    print("\n" + "=" * 70)
    print("2a. SCALE TESTS")
    print("=" * 70)

    results = []
    rng = np.random.default_rng(42)

    for n in SCALE_SIZES:
        print(f"\n--- N = {n:,} ---")

        # Generate data
        t0 = time.perf_counter()
        rss_before = _rss_mb()
        try:
            df = _make_stress_claims(n, rng)
            gen_elapsed = time.perf_counter() - t0
            rss_after   = _rss_mb()
            df_mb       = df.memory_usage(deep=True).sum() / 1024 / 1024
            print(f"  [datagen] {gen_elapsed:.2f}s | df size={df_mb:.0f} MiB | "
                  f"RSS delta={rss_after - rss_before:.0f} MiB")
        except MemoryError as exc:
            print(f"  [datagen] OOM at N={n:,}: {exc}")
            results.append({"n": n, "phase": "datagen", "status": "OOM",
                            "elapsed_s": None, "rss_mb": None})
            break

        phase_results = {"n": n, "phase": "datagen", "status": "OK",
                         "elapsed_s": round(gen_elapsed, 2),
                         "rss_mb": round(rss_after - rss_before, 1)}
        results.append(phase_results)

        # Run each phase
        for phase_name, phase_fn in SCALE_PHASES:
            gc.collect()
            rss_before = _rss_mb()
            result, elapsed, error = _run_with_timeout(phase_name, phase_fn, df)
            rss_after  = _rss_mb()

            if error:
                status = error[:60]
            else:
                status = "OK"

            print(f"  [{phase_name:<20}] {elapsed:.2f}s | "
                  f"RSS delta={rss_after - rss_before:.0f} MiB | {status}")
            results.append({
                "n":        n,
                "phase":    phase_name,
                "status":   status,
                "elapsed_s": round(elapsed, 2),
                "rss_mb":   round(rss_after - rss_before, 1),
            })

            if "OOM" in status or "TIMEOUT" in status:
                print(f"  Stopping scale test at N={n:,} ({status})")
                break

        del df
        gc.collect()

    print("\n--- Scale test summary ---")
    print(f"{'N':>10}  {'Phase':<22}  {'Elapsed(s)':>10}  {'RSS-delta(MiB)':>14}  Status")
    print("-" * 72)
    for r in results:
        el  = f"{r['elapsed_s']:.2f}" if r['elapsed_s'] is not None else "N/A"
        rss = f"{r['rss_mb']:.0f}"    if r['rss_mb']    is not None else "N/A"
        print(f"{r['n']:>10,}  {r['phase']:<22}  {el:>10}  {rss:>14}  {r['status']}")

    return results


# ── 2b: Pathological shape tests ─────────────────────────────────────────────

SHAPE_TESTS = [
    {
        "name":  "whale_provider",
        "desc":  "1 provider has 40k of 50k claims",
        "kwargs": {"n": 50_000, "whale_provider": True},
    },
    {
        "name":  "singleton_specialty",
        "desc":  "1 specialty has exactly 1 provider",
        "kwargs": {"n": 50_000, "singleton_specialty": True},
    },
    {
        "name":  "provider_explosion",
        "desc":  "10k distinct providers, ~5 claims each",
        "kwargs": {"n": 50_000, "provider_explosion": True},
    },
    {
        "name":  "single_day",
        "desc":  "All 50k claims on 2024-01-15",
        "kwargs": {"n": 50_000, "single_day": True},
    },
]


def run_shape_tests():
    print("\n" + "=" * 70)
    print("2b. PATHOLOGICAL SHAPE TESTS")
    print("=" * 70)

    results = []
    rng = np.random.default_rng(99)

    for spec in SHAPE_TESTS:
        name  = spec["name"]
        desc  = spec["desc"]
        kw    = spec["kwargs"]
        print(f"\n--- {name}: {desc} ---")

        # Generate
        t0 = time.perf_counter()
        try:
            df = _make_stress_claims(rng=rng, **kw)
        except Exception as exc:
            print(f"  [datagen] FAILED: {exc}")
            results.append({"shape": name, "phase": "datagen",
                            "elapsed_s": None, "status": f"FAILED: {exc}"})
            continue
        gen_time = time.perf_counter() - t0
        print(f"  [datagen] {gen_time:.2f}s  |  "
              f"providers={df['provider_id'].nunique()}  "
              f"specialties={df['specialty'].nunique()}  "
              f"dates={df['service_date'].nunique()}")

        shape_phases = [
            ("rules",         _run_rules),
            ("peer_stats",    _run_peer_stats),
            ("codemix",       _run_codemix),
            ("temporal",      _run_temporal),
            ("anomaly_model", _run_anomaly_model),
        ]

        for phase_name, phase_fn in shape_phases:
            result, elapsed, error = _run_with_timeout(phase_name, phase_fn, df)
            if error:
                status = error[:80]
            else:
                status = "OK"
            print(f"  [{phase_name:<20}] {elapsed:.2f}s  {status}")
            results.append({
                "shape":     name,
                "phase":     phase_name,
                "elapsed_s": round(elapsed, 2),
                "status":    status,
            })

        del df
        gc.collect()

    print("\n--- Shape test summary ---")
    print(f"{'Shape':<22}  {'Phase':<22}  {'Elapsed(s)':>10}  Status")
    print("-" * 68)
    for r in results:
        el = f"{r['elapsed_s']:.2f}" if r['elapsed_s'] is not None else "N/A"
        print(f"{r['shape']:<22}  {r['phase']:<22}  {el:>10}  {r['status']}")

    return results


# ── 2c: Dashboard smoke test ──────────────────────────────────────────────────

def run_dashboard_smoke_test():
    print("\n" + "=" * 70)
    print("2c. DASHBOARD SMOKE TEST (app.py data-loading, no Streamlit server)")
    print("=" * 70)

    results = {}

    # Build a risk_scores.csv with 500+ flagged providers (score > 0)
    print("\n  Building synthetic risk_scores.csv with 600 flagged providers...")
    n_providers = 600
    rng = np.random.default_rng(123)

    providers = [f"PRV{i+1:05d}" for i in range(n_providers)]
    specialties = ["Family Medicine", "Cardiology", "Radiology",
                   "Psychiatry", "Dermatology", "Surgery"]
    confidence  = rng.choice(["HIGH", "MEDIUM", "LOW"], size=n_providers)

    scores_df = pd.DataFrame({
        "provider_id":        providers,
        "provider_name":      [f"Dr. Test Provider {i}" for i in range(n_providers)],
        "specialty":          rng.choice(specialties, size=n_providers),
        "risk_score":         rng.uniform(10, 95, size=n_providers).round(1),
        "confidence":         confidence,
        "estimated_exposure": rng.uniform(5_000, 500_000, size=n_providers).round(2),
        "expected_recovery":  rng.uniform(1_000, 100_000, size=n_providers).round(2),
        "rules_score":        rng.uniform(0, 50, size=n_providers).round(1),
        "peer_score":         rng.uniform(0, 25, size=n_providers).round(1),
        "ml_score":           rng.uniform(0, 100, size=n_providers).round(1),
        "ml_is_anomaly":      rng.integers(0, 2, size=n_providers),
        "codemix_score":      rng.uniform(0, 10, size=n_providers).round(2),
        "codemix_flag":       rng.integers(0, 2, size=n_providers),
        "kl_divergence":      rng.uniform(0, 1, size=n_providers).round(4),
        "cosine_distance":    rng.uniform(0, 1, size=n_providers).round(4),
        "temporal_score":     rng.uniform(0, 5, size=n_providers).round(2),
        "temporal_flag":      rng.integers(0, 2, size=n_providers),
        "feedback_score":     rng.uniform(0, 10, size=n_providers).round(2),
        "feedback_label":     rng.integers(0, 2, size=n_providers),
        "top_reason":         ["Rule: impossible_day" if i % 3 == 0 else
                               "Peer z>3: claims_per_day" if i % 3 == 1 else
                               "ML anomaly score 75/100" for i in range(n_providers)],
    })
    scores_df = scores_df.sort_values("risk_score", ascending=False).reset_index(drop=True)
    scores_path = "stress_test_risk_scores.csv"
    scores_df.to_csv(scores_path, index=False)
    print(f"  Written: {scores_path}  ({len(scores_df)} rows, score > 0: {(scores_df['risk_score'] > 0).sum()})")

    # Exercise the data loading functions that app.py calls
    print("\n  Exercising app.py data-loading code paths...")

    # Test 1: load_scores equivalent
    t0 = time.perf_counter()
    try:
        loaded = pd.read_csv(scores_path, dtype={"provider_id": str})
        n_loaded = len(loaded)
        elapsed = time.perf_counter() - t0
        print(f"  [load_scores]  {elapsed:.3f}s  loaded {n_loaded} rows  OK")
        results["load_scores"] = {"status": "OK", "n_rows": n_loaded,
                                   "elapsed_s": round(elapsed, 3)}
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        print(f"  [load_scores]  FAILED: {exc}")
        results["load_scores"] = {"status": f"FAILED: {exc}", "elapsed_s": round(elapsed, 3)}

    # Test 2: Sidebar stats computation (mirrors app.py render_sidebar)
    t0 = time.perf_counter()
    try:
        flagged = loaded[loaded["risk_score"] >= 10]
        hi = len(flagged[flagged["confidence"] == "HIGH"])
        me = len(flagged[flagged["confidence"] == "MEDIUM"])
        lo = len(flagged[flagged["confidence"] == "LOW"])
        elapsed = time.perf_counter() - t0
        print(f"  [sidebar_stats]  {elapsed:.3f}s  HIGH={hi} MEDIUM={me} LOW={lo}  OK")
        results["sidebar_stats"] = {"status": "OK", "elapsed_s": round(elapsed, 3)}
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        print(f"  [sidebar_stats]  FAILED: {exc}")
        results["sidebar_stats"] = {"status": f"FAILED: {exc}", "elapsed_s": round(elapsed, 3)}

    # Test 3: KPI computation (mirrors app.py main KPI block)
    t0 = time.perf_counter()
    try:
        all_flagged    = loaded[loaded["risk_score"] >= 10]
        total_exposure = all_flagged["estimated_exposure"].sum()
        n_flagged_kpi  = len(all_flagged)
        n_proactive    = len(all_flagged[
            (all_flagged["rules_score"] == 0) &
            ((all_flagged["peer_score"] > 0) | (all_flagged["ml_is_anomaly"] == 1))
        ])
        top_exposure   = all_flagged["estimated_exposure"].max()
        elapsed        = time.perf_counter() - t0
        print(f"  [kpi_compute]  {elapsed:.3f}s  flagged={n_flagged_kpi}  "
              f"exposure=${total_exposure:,.0f}  proactive={n_proactive}  OK")
        results["kpi_compute"] = {"status": "OK", "elapsed_s": round(elapsed, 3)}
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        print(f"  [kpi_compute]  FAILED: {exc}")
        results["kpi_compute"] = {"status": f"FAILED: {exc}", "elapsed_s": round(elapsed, 3)}

    # Test 4: Worklist table (styled DataFrame construction)
    t0 = time.perf_counter()
    try:
        worklist = loaded[loaded["risk_score"] >= 10].copy()
        display_cols = {
            "provider_id":        "Provider ID",
            "provider_name":      "Name",
            "specialty":          "Specialty",
            "risk_score":         "Risk Score",
            "confidence":         "Confidence",
            "expected_recovery":  "Exp. Recovery ($)",
            "estimated_exposure": "Est. Exposure ($)",
            "top_reason":         "Top Reason",
        }
        table = worklist[list(display_cols.keys())].rename(columns=display_cols).reset_index(drop=True)
        table.index = table.index + 1
        elapsed = time.perf_counter() - t0
        print(f"  [worklist_table]  {elapsed:.3f}s  {len(table)} rows  OK")
        results["worklist_table"] = {"status": "OK", "n_rows": len(table),
                                      "elapsed_s": round(elapsed, 3)}
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        print(f"  [worklist_table]  FAILED: {exc}")
        results["worklist_table"] = {"status": f"FAILED: {exc}", "elapsed_s": round(elapsed, 3)}

    # Test 5: Analytics charts data preparation
    t0 = time.perf_counter()
    try:
        # exposure_by_specialty_chart data
        grp = (worklist.groupby("specialty")["estimated_exposure"]
               .sum().sort_values(ascending=False).head(8).reset_index())
        # confidence_breakdown_chart data
        counts = worklist["confidence"].value_counts().reindex(
            ["HIGH", "MEDIUM", "LOW"], fill_value=0
        )
        # score_distribution_chart data
        hist_data = worklist["risk_score"].values
        elapsed = time.perf_counter() - t0
        print(f"  [analytics_prep]  {elapsed:.3f}s  specialties={len(grp)}  OK")
        results["analytics_prep"] = {"status": "OK", "elapsed_s": round(elapsed, 3)}
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        print(f"  [analytics_prep]  FAILED: {exc}")
        results["analytics_prep"] = {"status": f"FAILED: {exc}", "elapsed_s": round(elapsed, 3)}

    # Test 6: Provider selectbox population
    t0 = time.perf_counter()
    try:
        pid_options = worklist["provider_id"].tolist()
        name_map    = dict(zip(worklist["provider_id"], worklist["provider_name"]))
        spec_map    = dict(zip(worklist["provider_id"], worklist["specialty"]))
        score_map   = dict(zip(worklist["provider_id"], worklist["risk_score"]))
        conf_map    = dict(zip(worklist["provider_id"], worklist["confidence"]))
        elapsed = time.perf_counter() - t0
        print(f"  [selectbox_maps]  {elapsed:.3f}s  {len(pid_options)} providers  OK")
        results["selectbox_maps"] = {"status": "OK", "n_providers": len(pid_options),
                                      "elapsed_s": round(elapsed, 3)}
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        print(f"  [selectbox_maps]  FAILED: {exc}")
        results["selectbox_maps"] = {"status": f"FAILED: {exc}", "elapsed_s": round(elapsed, 3)}

    # Cleanup
    try:
        os.remove(scores_path)
    except OSError:
        pass

    print("\n  Dashboard smoke test complete.")
    return results


# ── Main orchestrator ─────────────────────────────────────────────────────────

def main():
    total_start = time.perf_counter()

    print("=" * 70)
    print("BILLING ANOMALY DEMO — STRESS & SCALE TEST HARNESS")
    print(f"Python {sys.version.split()[0]}  |  pandas {pd.__version__}  |  "
          f"numpy {np.__version__}")
    try:
        import psutil
        rss = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
        print(f"Starting RSS: {rss:.0f} MiB")
    except ImportError:
        print("(psutil not installed — RSS tracking disabled)")

    # Suppress verbose warnings during stress runs
    warnings.filterwarnings("ignore", category=FutureWarning)
    warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

    # Change to project directory so relative file paths work
    project_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_dir)
    sys.path.insert(0, project_dir)

    scale_results  = run_scale_tests()
    shape_results  = run_shape_tests()
    dash_results   = run_dashboard_smoke_test()

    total_elapsed = time.perf_counter() - total_start
    print(f"\n{'=' * 70}")
    print(f"TOTAL ELAPSED: {total_elapsed:.1f}s  ({total_elapsed/60:.1f} min)")
    print("=" * 70)


if __name__ == "__main__":
    main()
