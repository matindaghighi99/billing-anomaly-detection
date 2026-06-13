"""Verification: how many planted bad actors were detected and at what rank?"""

import json
import pandas as pd

GROUND_TRUTH_JSON = "ground_truth.json"
SCORES_CSV        = "risk_scores.csv"


def main():
    with open(GROUND_TRUTH_JSON) as f:
        gt = json.load(f)

    scores = pd.read_csv(SCORES_CSV, dtype={"provider_id": str})
    scores = scores.reset_index()
    scores["rank"] = scores.index + 1

    bad_actors = gt["all_bad_actors"]

    print("Verification: Ground Truth vs. Detected")
    print("=" * 70)
    print(f"  Planted bad actors : {len(bad_actors)}")
    print()
    print(f"  {'Provider':<12} {'Type(s)':<28} {'Rank':>5}  {'Score':>6}  {'Exposure':>12}")
    print("  " + "-" * 68)

    found_ranks = []
    for pid in bad_actors:
        types = [t for t in ("impossible_day","upcoder","duplicate",
                             "volume_outlier","unbundler","novel")
                 if pid in gt.get(t, [])]
        type_str = "+".join(types)
        row = scores[scores["provider_id"] == pid]
        if row.empty:
            print(f"  {pid:<12} {type_str:<28} {'MISSED':>5}  {'—':>6}  {'—':>12}")
        else:
            r = row.iloc[0]
            rank = int(r["rank"])
            found_ranks.append(rank)
            print(f"  {pid:<12} {type_str:<28} {rank:>5}  {r['risk_score']:>6.1f}  "
                  f"${r['estimated_exposure']:>10,.2f}")

    n_found = len(found_ranks)
    n_total = len(bad_actors)
    print()
    print(f"  Detection rate : {n_found}/{n_total} ({n_found/n_total*100:.0f}%)")
    if found_ranks:
        print(f"  Avg rank       : {sum(found_ranks)/len(found_ranks):.1f}")
        print(f"  Max rank       : {max(found_ranks)}")
        n_top10 = sum(1 for r in found_ranks if r <= 10)
        print(f"  In top 10      : {n_top10}/{n_total}")
        n_top20 = sum(1 for r in found_ranks if r <= 20)
        print(f"  In top 20      : {n_top20}/{n_total}")
    print("=" * 70)

    # False positives in top 10
    top10_ids   = set(scores.head(10)["provider_id"].tolist())
    fp_in_top10 = top10_ids - set(bad_actors)
    print(f"\n  False positives in top 10: {len(fp_in_top10)} — {fp_in_top10 or 'none'}")
    print()


if __name__ == "__main__":
    main()
