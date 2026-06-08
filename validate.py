"""validate.py -- Measurement harness for the billing anomaly detection pipeline.

Prints a scored report after every pipeline run:
  • Detection rate  -- how many planted bad actors appear in top-N, and at which rank
  • False-positive rate -- are any "clean trap" providers wrongly flagged?
  • Before-vs-after comparison -- saved baseline vs. current run

Usage:
    python validate.py           # compare current run against saved baseline
    python validate.py --reset   # overwrite baseline with current results

The baseline is written automatically on the first run.
"""

import argparse
import datetime
import json
import os
import sys

import pandas as pd

GROUND_TRUTH_JSON  = "ground_truth.json"
SCORES_CSV         = "risk_scores.csv"
BASELINE_JSON      = "validate_baseline.json"

# A bad actor "counts as detected" when it ranks within this many providers
CAUGHT_WITHIN_RANK = 20
# Minimum risk score to count as a flag (mirrors app.py RISK_THRESHOLD)
RISK_SCORE_FP_CUTOFF = 5


# ── Data loading ──────────────────────────────────────────────────────────────

def _load():
    if not os.path.exists(GROUND_TRUTH_JSON):
        sys.exit(f"ERROR: {GROUND_TRUTH_JSON} not found. Run data_gen.py first.")
    if not os.path.exists(SCORES_CSV):
        sys.exit(f"ERROR: {SCORES_CSV} not found. Run the full pipeline first.")

    with open(GROUND_TRUTH_JSON) as f:
        gt = json.load(f)

    scores = pd.read_csv(SCORES_CSV, dtype={"provider_id": str})
    scores = scores.reset_index(drop=True)
    scores["rank"] = scores.index + 1
    return gt, scores


# ── Scoring ───────────────────────────────────────────────────────────────────

def _score_run(gt, scores):
    bad_actors      = gt["all_bad_actors"]
    clean_providers = gt.get("clean_providers", {})

    # ── Bad-actor rows ────────────────────────────────────────────────────────
    ba_rows = []
    for pid in sorted(bad_actors):
        types = [t for t in
                 ("impossible_day", "upcoder", "duplicate",
                  "volume_outlier", "unbundler", "novel")
                 if pid in gt.get(t, [])]
        row = scores[scores["provider_id"] == pid]
        if row.empty:
            ba_rows.append({"pid": pid, "types": "+".join(types) or "unknown",
                            "rank": 9999, "score": 0.0, "exposure": 0.0})
        else:
            r = row.iloc[0]
            ba_rows.append({
                "pid":      pid,
                "types":    "+".join(types) or "unknown",
                "rank":     int(r["rank"]),
                "score":    float(r["risk_score"]),
                "exposure": float(r["estimated_exposure"]),
            })

    # ── Clean-trap rows ───────────────────────────────────────────────────────
    fp_rows = []
    for pid, info in clean_providers.items():
        row = scores[scores["provider_id"] == pid]
        if row.empty:
            fp_rows.append({"pid": pid, "desc": info.get("description", ""),
                            "rank": None, "score": 0.0, "is_fp": False})
        else:
            r = row.iloc[0]
            fp_rows.append({
                "pid":   pid,
                "desc":  info.get("description", ""),
                "rank":  int(r["rank"]),
                "score": float(r["risk_score"]),
                "is_fp": float(r["risk_score"]) >= RISK_SCORE_FP_CUTOFF,
            })

    # ── Spurious FP: unknown providers in top 20 ─────────────────────────────
    top20_ids     = set(scores.head(20)["provider_id"].tolist())
    known_ids     = set(bad_actors) | set(clean_providers.keys())
    spurious_fp20 = sorted(top20_ids - known_ids)

    # ── Aggregate metrics ─────────────────────────────────────────────────────
    n_total       = len(ba_rows)
    ranks_found   = [r["rank"] for r in ba_rows if r["rank"] < 9999]
    n_caught_10   = sum(1 for r in ba_rows if r["rank"] <= 10)
    n_caught_20   = sum(1 for r in ba_rows if r["rank"] <= CAUGHT_WITHIN_RANK)
    avg_rank      = sum(ranks_found) / len(ranks_found) if ranks_found else 9999.0
    n_fp          = sum(1 for r in fp_rows if r["is_fp"])
    n_traps       = len(fp_rows)
    fp_rate       = round(n_fp / n_traps * 100, 1) if n_traps else 0.0

    return {
        "ba_rows":       ba_rows,
        "fp_rows":       fp_rows,
        "spurious_fp20": spurious_fp20,
        "n_total":       n_total,
        "n_caught_10":   n_caught_10,
        "n_caught_20":   n_caught_20,
        "avg_rank":      round(avg_rank, 1),
        "det_rate_10":   round(n_caught_10 / n_total * 100, 1),
        "det_rate_20":   round(n_caught_20 / n_total * 100, 1),
        "n_fp":          n_fp,
        "n_traps":       n_traps,
        "fp_rate":       fp_rate,
        "timestamp":     datetime.datetime.now().isoformat(),
    }


# ── Report printing ───────────────────────────────────────────────────────────

def _print_report(result, baseline=None):
    W = 74
    ts = result["timestamp"][:19].replace("T", " ")

    print("=" * W)
    print("  BILLING ANOMALY DETECTION -- VALIDATION SCORECARD")
    print(f"  Run: {ts}")
    print("=" * W)

    # ── Bad actors ────────────────────────────────────────────────────────────
    print(f"\n  BAD ACTORS  ({result['n_total']} planted)")
    print(f"  {'Provider':<12} {'Type':<22} {'Rank':>5}  {'Score':>6}  {'Exposure':>12}  Status")
    print("  " + "-" * 70)
    for r in sorted(result["ba_rows"], key=lambda x: x["rank"]):
        if r["rank"] <= 10:
            status = "CAUGHT (top-10)"
        elif r["rank"] <= CAUGHT_WITHIN_RANK:
            status = f"caught (rank {r['rank']})"
        elif r["rank"] < 9999:
            status = f"MISSED (rank {r['rank']})"
        else:
            status = "MISSED (not scored)"
        print(f"  {r['pid']:<12} {r['types']:<22} {r['rank']:>5}  {r['score']:>6.1f}  "
              f"${r['exposure']:>10,.2f}  {status}")

    print()
    print(f"  Detection top-10 : {result['n_caught_10']}/{result['n_total']}"
          f"  ({result['det_rate_10']:.0f}%)")
    print(f"  Detection top-20 : {result['n_caught_20']}/{result['n_total']}"
          f"  ({result['det_rate_20']:.0f}%)")
    print(f"  Avg rank         : {result['avg_rank']}")

    # ── Clean traps ───────────────────────────────────────────────────────────
    if result["fp_rows"]:
        print(f"\n  CLEAN TRAPS  ({result['n_traps']} -- must NOT be flagged)")
        print(f"  {'Provider':<10} {'Description':<40} {'Rank':>5}  {'Score':>6}  Verdict")
        print("  " + "-" * 70)
        for r in result["fp_rows"]:
            rank_s  = str(r["rank"]) if r["rank"] is not None else "--"
            verdict = "FALSE POSITIVE !" if r["is_fp"] else "OK (clean)"
            print(f"  {r['pid']:<10} {r['desc'][:40]:<40} {rank_s:>5}  "
                  f"{r['score']:>6.1f}  {verdict}")
        print()
        print(f"  False-positive rate (traps) : "
              f"{result['n_fp']}/{result['n_traps']}  ({result['fp_rate']:.0f}%)")

    # ── Spurious FP in top-20 ─────────────────────────────────────────────────
    if result["spurious_fp20"]:
        print(f"  Spurious FP in top-20 (unknown providers) : "
              f"{result['spurious_fp20']}")
    else:
        print("  Spurious FP in top-20       : none")

    # ── Before vs. after ─────────────────────────────────────────────────────
    if baseline:
        print()
        print("  BEFORE vs. AFTER")
        print(f"  (baseline from {baseline.get('timestamp','?')[:10]})")
        print(f"  {'Metric':<32} {'Baseline':>10}  {'Now':>10}  {'Δ':>8}")
        print("  " + "-" * 64)

        METRICS = [
            ("det_rate_10", "Detection top-10 (%)"),
            ("det_rate_20", "Detection top-20 (%)"),
            ("avg_rank",    "Avg rank of bad actors"),
            ("fp_rate",     "FP rate -- traps (%)"),
            ("n_fp",        "FP count -- traps"),
        ]
        for key, label in METRICS:
            b = baseline.get(key)
            c = result.get(key)
            if b is None:
                b_s, delta_s = "--", "--"
            else:
                b_s = str(b)
                if isinstance(c, (int, float)):
                    delta = c - b
                    # Up is good for detection; down is good for FP/rank
                    marker = ""
                    if key in ("det_rate_10", "det_rate_20") and delta > 0:
                        marker = " ^"
                    elif key in ("fp_rate", "n_fp", "avg_rank") and delta < 0:
                        marker = " v"
                    delta_s = f"{delta:+.1f}{marker}"
                else:
                    delta_s = "--"
            c_s = str(c) if c is not None else "--"
            print(f"  {label:<32} {b_s:>10}  {c_s:>10}  {delta_s:>10}")

    print("=" * W)


# ── Baseline persistence ──────────────────────────────────────────────────────

def _serialisable(result):
    """Strip non-serialisable list-of-dicts before saving to JSON."""
    return {k: v for k, v in result.items()
            if k not in ("ba_rows", "fp_rows", "spurious_fp20")}


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Validate anomaly detection pipeline")
    parser.add_argument("--reset", action="store_true",
                        help="Overwrite baseline with current results")
    args = parser.parse_args()

    gt, scores = _load()
    result     = _score_run(gt, scores)

    baseline = None
    if os.path.exists(BASELINE_JSON) and not args.reset:
        with open(BASELINE_JSON) as f:
            baseline = json.load(f)

    _print_report(result, baseline)

    if not os.path.exists(BASELINE_JSON) or args.reset:
        with open(BASELINE_JSON, "w") as f:
            json.dump(_serialisable(result), f, indent=2)
        label = "reset" if args.reset else "saved"
        print(f"\n  Baseline {label}: {BASELINE_JSON}\n")


if __name__ == "__main__":
    main()
