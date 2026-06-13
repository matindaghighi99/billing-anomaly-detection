# Edge & Boundary Test Report
**Branch:** hardening
**Date:** 2026-06-09
**Test suite:** tests/ (pytest)
**Python:** 3.14.4
**pytest:** 9.0.3

---

## Executive Summary

51 edge and boundary tests were written across 5 test files covering rules, peer statistics, temporal detection, scoring, code-mix drift, and full-pipeline integration against the planted ground truth. One real bug was found and fixed: `_modified_zscore` in `peer_stats.py` silently produced NaN z-scores for zero-variance cohorts (all-identical metric values), causing every provider in such a cohort to be invisibly excluded from flagging.  All 51 tests pass after the fix.

---

## Threshold Inventory

| Module | Constant | Value | Comparison Operator | Intended Behaviour |
|--------|----------|-------|---------------------|--------------------|
| rules.py | (unnamed) | 1440 minutes | `> 1440` (strict greater-than) | Exactly 24 h (1440 min) is NOT a violation; only strictly more than 1440 is flagged |
| rules.py | (unnamed) | 1 duplicate | `> 1` on count | Two or more identical provider+patient+code+date rows = duplicate |
| peer_stats.py | `ZSCORE_THRESHOLD` | 3.5 | `abs(z) <= threshold` skips (i.e., flag only when `abs(z) > 3.5`) | z=3.5 is NOT flagged; z=3.6 IS flagged |
| peer_stats.py | `MIN_COHORT_SIZE` | 5 | `len(grp) >= MIN_COHORT_SIZE` uses cohort path | < 5 providers in sub-cohort falls back to full-specialty distribution |
| peer_stats.py | `PART_TIME_THRESHOLD` | 0.40 | `< 0.40` = part_time | Providers active on < 40% of 261 working days classified as part-time |
| temporal.py | `CUSUM_THRESHOLD` | 3.0 | `cusum_score >= CUSUM_THRESHOLD` | CUSUM exactly 3.0 IS flagged (inclusive) |
| temporal.py | `SPIKE_MULTIPLIER` | 3.5 | `spike_ratio >= SPIKE_MULTIPLIER` | Spike ratio exactly 3.5x IS flagged (inclusive) |
| temporal.py | `MIN_ACTIVE_MONTHS` | 3 | `n_months < MIN_ACTIVE_MONTHS` skips | Providers with < 3 active months are excluded from temporal analysis |
| codemix.py | `KL_THRESHOLD` | 0.10 | `kl > KL_THRESHOLD` (strict greater-than) | KL exactly 0.10 is NOT flagged |
| codemix.py | `COSINE_THRESHOLD` | 0.15 | `cos > COSINE_THRESHOLD` (strict greater-than) | Cosine distance exactly 0.15 is NOT flagged |
| scoring.py | `RULE_POINTS[impossible_day]` | 40 pts | sum, capped at 50 | Impossible-day rule contributes up to 40 pts (or combined cap of 50) |
| scoring.py | `RULE_POINTS[duplicate_billing]` | 35 pts | sum, capped at 50 | Duplicate billing contributes up to 35 pts |
| scoring.py | `RULE_POINTS[unbundling]` | 30 pts | sum, capped at 50 | Unbundling contributes up to 30 pts |
| scoring.py | `PEER_MAX_PTS` | 25 | `.clip(upper=25)` | Peer stats capped at 25 pts |
| scoring.py | `ML_MAX_PTS` | 15 | normalised from ml_score/100 | ML ensemble capped at 15 pts |
| scoring.py | `CODEMIX_MAX_PTS` | 10 | KL clipped to 1.0 * 10 | Code-mix drift capped at 10 pts |
| scoring.py | `TEMPORAL_MAX_PTS` | 5 | CUSUM clipped to 6.0/6.0 * 5 | Temporal capped at 5 pts |
| scoring.py | `MIN_SCORE_THRESHOLD` | 10 | `risk_score >= 10` | Providers below 10 pts are suppressed from the worklist |
| scoring.py | `CONFIDENCE_LIKELIHOOD[HIGH]` | 0.70 | multiplication | 70% recovery likelihood for HIGH confidence |
| scoring.py | `CONFIDENCE_LIKELIHOOD[MEDIUM]` | 0.40 | multiplication | 40% recovery likelihood for MEDIUM confidence |
| scoring.py | `CONFIDENCE_LIKELIHOOD[LOW]` | 0.15 | multiplication | 15% recovery likelihood for LOW confidence |
| fairness.py | `MIN_GROUP_SIZE` | 5 | `n_grp < MIN_GROUP_SIZE` skips | Groups with < 5 providers excluded from chi-square test |
| fairness.py | `P_VALUE_ALERT` | 0.05 | `p < 0.05` triggers alert | Standard significance threshold for over-flagging alert |

---

## Test Results

| Test Name | PASS before fix | PASS after fix |
|-----------|-----------------|----------------|
| test_codemix_boundary::test_single_code_provider | PASS | PASS |
| test_codemix_boundary::test_identical_to_cohort | PASS | PASS |
| test_codemix_boundary::test_completely_different_from_cohort | PASS | PASS |
| test_codemix_boundary::test_single_provider_cohort | PASS | PASS |
| test_codemix_boundary::test_kl_divergence_helper_zero | PASS | PASS |
| test_codemix_boundary::test_cosine_distance_helper_zero | PASS | PASS |
| test_codemix_boundary::test_cosine_distance_zero_vector | PASS | PASS |
| test_integration_ground_truth::test_all_bad_actors_in_top_20 | PASS | PASS |
| test_integration_ground_truth::test_clean_traps_not_in_top_10 | PASS | PASS |
| test_integration_ground_truth::test_no_nan_in_risk_scores | PASS | PASS |
| test_integration_ground_truth::test_scores_in_range | PASS | PASS |
| test_integration_ground_truth::test_confidence_valid_values | PASS | PASS |
| test_peer_stats_boundary::test_cohort_n1 | PASS | PASS |
| test_peer_stats_boundary::test_cohort_n2 | PASS | PASS |
| **test_peer_stats_boundary::test_zero_variance_cohort** | **FAIL** | **PASS** |
| test_peer_stats_boundary::test_below_min_cohort_floor | PASS | PASS |
| test_peer_stats_boundary::test_exactly_at_min_cohort_floor | PASS | PASS |
| test_peer_stats_boundary::test_outlier_at_mad_z_3_4 | PASS | PASS |
| test_peer_stats_boundary::test_outlier_at_mad_z_3_5 | PASS | PASS |
| test_peer_stats_boundary::test_outlier_at_mad_z_3_6 | PASS | PASS |
| test_peer_stats_boundary::test_nan_propagation | PASS | PASS |
| test_rules_boundary::test_impossible_day_at_1439 | PASS | PASS |
| test_rules_boundary::test_impossible_day_at_1440 | PASS | PASS |
| test_rules_boundary::test_impossible_day_at_1441 | PASS | PASS |
| test_rules_boundary::test_impossible_day_exactly_zero | PASS | PASS |
| test_rules_boundary::test_duplicate_same_claim_id_same_day | PASS | PASS |
| test_rules_boundary::test_duplicate_same_code_same_day_different_claim_ids | PASS | PASS |
| test_rules_boundary::test_duplicate_different_day | PASS | PASS |
| test_rules_boundary::test_unbundling_present | PASS | PASS |
| test_rules_boundary::test_unbundling_absent | PASS | PASS |
| test_rules_boundary::test_empty_df | PASS | PASS |
| test_rules_boundary::test_single_row | PASS | PASS |
| test_scoring_boundary::test_all_layers_flagged_max_score | PASS | PASS |
| test_scoring_boundary::test_no_layers_flagged_score_zero | PASS | PASS |
| test_scoring_boundary::test_tie_break_deterministic | PASS | PASS |
| test_scoring_boundary::test_zero_exposure_expected_recovery | PASS | PASS |
| test_scoring_boundary::test_zero_likelihood_expected_recovery | PASS | PASS |
| test_scoring_boundary::test_negative_score_clipped_to_zero | PASS | PASS |
| test_scoring_boundary::test_score_above_100_clipped | PASS | PASS |
| test_scoring_boundary::test_confidence_tier_boundary_high_medium | PASS | PASS |
| test_scoring_boundary::test_confidence_tier_boundary_medium_low | PASS | PASS |
| test_scoring_boundary::test_single_provider_worklist | PASS | PASS |
| test_temporal_boundary::test_min_active_months_2 | PASS | PASS |
| test_temporal_boundary::test_min_active_months_3 | PASS | PASS |
| test_temporal_boundary::test_cusum_no_change | PASS | PASS |
| test_temporal_boundary::test_cusum_gradual_rise | PASS | PASS |
| test_temporal_boundary::test_cusum_sudden_spike | PASS | PASS |
| test_temporal_boundary::test_spike_exactly_at_threshold | PASS | PASS |
| test_temporal_boundary::test_cusum_threshold_at_boundary | PASS | PASS |
| test_temporal_boundary::test_single_month | PASS | PASS |
| test_temporal_boundary::test_all_zeros | PASS | PASS |

**Summary: 50 passed before fix, 51 passed after fix (1 real bug found and fixed).**

---

## Findings (Severity-Ranked)

### HIGH

**Finding 1: Zero-variance cohort produces NaN z-scores (silent exclusion)**

- **Test:** `tests/test_peer_stats_boundary.py::test_zero_variance_cohort`
- **Input:** A cohort of 10 providers all with exactly 20.0 service_minutes (no variation) — forces MAD = 0 on `avg_minutes`
- **Expected:** `z_avg_minutes` = 0.0 for all providers (zero deviation from the median is mathematically z=0)
- **Actual (before fix):** `z_avg_minutes` = NaN for all providers; `build_flags` silently skips NaN z-scores via `if pd.isna(z): continue`, so every provider in such a cohort is completely invisible to the peer-stat flagging layer
- **Root cause:** `peer_stats.py:182` — `_modified_zscore` falls back to `scipy_stats.zscore(x, ddof=1, nan_policy="omit")` when MAD=0, but scipy returns NaN when std=0 (0/0 division). The returned NaN was not handled.
- **Fix applied:** `peer_stats.py:188` — after the scipy call, replace NaN values with 0.0: `z_vals = np.where(np.isnan(z_vals), 0.0, z_vals)`. Also added docstring explaining the fix rationale. A comment explains why: "zero deviation from median = z-score of 0 by definition."
- **Severity rationale:** HIGH because this is a silent exclusion — no warning, no error, providers simply vanish from peer-stat analysis. If a specialty group (e.g. Radiology) had unusually homogeneous minutes in a given dataset, the entire specialty could be excluded from volume-based peer flagging.

---

### MEDIUM

No medium-severity findings.

---

### LOW

**Finding 2: scipy RuntimeWarning for nearly-identical values (not a code bug)**

- **Test:** `tests/test_peer_stats_boundary.py::test_cohort_n2` (and related)
- **Input:** Cohorts of 2 providers with near-identical metrics
- **Expected:** Numeric z-scores (finite), possible NaN acceptable
- **Actual:** RuntimeWarning "Precision loss occurred in moment calculation due to catastrophic cancellation" from scipy. Not a crash. Produces NaN which is handled by the fix above for the zero-variance case.
- **Root cause:** `peer_stats.py:188` — scipy's internal precision warning for nearly-identical data
- **Fix applied / proposed:** The zero-variance NaN fix above handles this case. The RuntimeWarning is benign in context (it is a scipy-level warning about floating-point precision, not a logic error). No suppression added — warnings are useful signal for operators.

---

## > vs >= Audit

| File:Line | Threshold | Operator | Intentional? | Comment in Code |
|-----------|-----------|----------|--------------|-----------------|
| `rules.py:50` | 1440 minutes | `> 1440` (strict) | YES — intentional | See docstring: "1 440 service-minutes per day" is the limit; exactly 1440 = exactly 24 h, NOT a violation |
| `rules.py:78` | 1 duplicate count | `> 1` on `n` (strict) | YES — intentional | Count > 1 means at least 2 identical rows, which is the minimum for a duplicate |
| `peer_stats.py:255` | 3.5 z-score | `abs(z) <= threshold` to SKIP | YES — intentional | `<= 3.5` skips (does NOT flag); z must be strictly ABOVE 3.5 to flag. A comment in the function documents this. |
| `peer_stats.py:205` | MIN_COHORT_SIZE=5 | `>= MIN_COHORT_SIZE` uses cohort path | YES — intentional | Exactly 5 providers IS enough for the cohort path |
| `temporal.py:109` | CUSUM_THRESHOLD=3.0 | `>= CUSUM_THRESHOLD` | YES — intentional | Exactly 3.0 IS flagged (inclusive threshold) |
| `temporal.py:113` | SPIKE_MULTIPLIER=3.5 | `>= SPIKE_MULTIPLIER` | YES — intentional | Exactly 3.5x IS flagged (inclusive threshold) |
| `temporal.py:96` | MIN_ACTIVE_MONTHS=3 | `< MIN_ACTIVE_MONTHS` to skip | YES — intentional | Exactly 3 months IS included |
| `codemix.py:155` | KL_THRESHOLD=0.10 | `kl > KL_THRESHOLD` (strict) | YES — intentional | KL exactly 0.10 is NOT flagged |
| `codemix.py:155` | COSINE_THRESHOLD=0.15 | `cos > COSINE_THRESHOLD` (strict) | YES — intentional | Cosine exactly 0.15 is NOT flagged |
| `scoring.py:301` | MIN_SCORE_THRESHOLD=10 | `>= MIN_SCORE_THRESHOLD` includes | YES — intentional | Exactly 10 pts IS included on the worklist |
| `scoring.py:287` | rules_score=0 boundary | `rules_score > 0` for HIGH | YES — intentional | Strictly positive rules_score = HIGH; zero = not HIGH |

**Asymmetry note:** rules.py uses `> 1440` (1440 NOT flagged) while temporal.py uses `>= 3.0` (3.0 IS flagged). Both are intentional but differ in style. The rules threshold represents a physical impossibility (you cannot exceed 24 hours — 1440 min is theoretically possible at the extreme), while the CUSUM threshold represents a statistical trigger where being exactly at the threshold is sufficient evidence.

---

## Ground Truth Validation

Results from `test_integration_ground_truth.py` against the live `risk_scores.csv`:

| Metric | Result |
|--------|--------|
| Bad actors in top-20 | 10/10 (100%) — all bad actors detected |
| Clean traps in top-10 | 0 unexpected FPs (TRAP03 not in top-10 in this run) |
| NaN in risk_score column | 0 |
| NaN in confidence column | 0 |
| NaN in expected_recovery column | 0 |
| Scores outside [0, 100] | 0 |
| Invalid confidence values | 0 (only HIGH, MEDIUM, LOW present) |

TRAP03 ("Sub-threshold provider: long days but always <1440 min") is documented as a known potential exception — at some random seeds it may appear in the top-10 as a peer-stats false positive. It did NOT appear in the top-10 in the current run.

---

## Verdict

The detection logic is correct at the boundaries with one exception now fixed: the `_modified_zscore` zero-variance path in `peer_stats.py` silently discarded all providers from a homogeneous cohort before the fix. All other threshold comparisons (`> vs >=`) are intentional and correctly implemented. The full pipeline achieves 100% detection of all 10 planted bad actors in the top-20 with zero false positives on clean trap providers.
