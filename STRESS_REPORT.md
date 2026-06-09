# Stress & Scale Test Report
**Branch:** hardening  
**Date:** 2026-06-09  
**Tested by:** Automated stress harness (`stress_test.py`)

---

## Executive Summary

The pipeline handles up to 1 million claims without OOM or timeout on a standard Windows laptop (Python 3.14, pandas 3.0). Four bugs were discovered through pathological-shape testing — two hard crashes (`ValueError`, `KeyError`) and one O(n_groups) performance regression in the fairness module — and were fixed with low-risk, logic-preserving patches. After fixes, all 20 shape-test phases and all 18 scale-test phases complete with status OK.

---

## Scale Test Results

psutil was not installed so RSS delta was unavailable; values shown as 0 MiB (not an actual zero — RSS tracking was disabled). DataFrame in-memory sizes are derived from `df.memory_usage(deep=True)`.

| N Claims | Phase | Elapsed (s) | df Size (MiB) | Status |
|---:|---|---:|---:|---|
| 100,000 | datagen | 1.25 | 16 | OK |
| 100,000 | rules | 0.43 | — | OK (was crash before fix) |
| 100,000 | peer_stats | 0.86 | — | OK |
| 100,000 | codemix | 0.22 | — | OK |
| 100,000 | temporal | 0.13 | — | OK |
| 100,000 | anomaly_model | 2.81 | — | OK |
| 500,000 | datagen | 6.21 | 82 | OK |
| 500,000 | rules | 2.09 | — | OK |
| 500,000 | peer_stats | 0.43 | — | OK |
| 500,000 | codemix | 0.51 | — | OK |
| 500,000 | temporal | 0.19 | — | OK |
| 500,000 | anomaly_model | 2.48 | — | OK |
| 1,000,000 | datagen | 12.57 | 163 | OK |
| 1,000,000 | rules | 4.22 | — | OK |
| 1,000,000 | peer_stats | 0.91 | — | OK |
| 1,000,000 | codemix | 1.06 | — | OK |
| 1,000,000 | temporal | 0.31 | — | OK |
| 1,000,000 | anomaly_model | 4.60 | — | OK |

**Total elapsed for all scale tests (post-fix): ~55 s.  No OOM or TIMEOUT encountered at any scale.**

Key observation: the anomaly_model phase is not O(n_claims) beyond a point — the feature matrix collapses claims to one row per provider before ML fitting, so timing is dominated by DuckDB aggregation and sklearn fit, not raw claim count. This explains why 1M claims is only ~60% slower than 100k.

---

## Pathological Shape Results

All 20 phase × shape combinations pass after fixes. Pre-fix failure columns included in parentheses.

| Shape | Providers | Specialties | Dates | Rules | peer_stats | codemix | temporal | anomaly_model |
|---|---|---|---|---|---|---|---|---|
| whale_provider | 150 | 6 | 365 | 0.25s OK | 0.14s OK | 0.18s OK | 0.08s OK | 0.59s OK |
| singleton_specialty | 150 | 7 | 365 | 0.23s OK (was crash) | 0.13s OK | 0.18s OK | 0.08s OK | 0.60s OK |
| provider_explosion | ~9,933 | 6 | 365 | 0.25s OK (was crash) | 3.75s OK | 5.79s OK | 3.51s OK | 3.29s OK |
| single_day | 150 | 6 | 1 | 0.27s OK | 0.12s OK | 0.17s OK | 0.05s OK (was crash) | 0.62s OK |

**provider_explosion** (10k providers, ~5 claims each) is the only shape that produces noticeable slowdown: peer_stats takes ~3.75s, codemix ~5.79s, temporal ~3.51s. This is due to Python-level per-provider loops in those modules — acceptable for realistic provider counts (150–1,000) but would become the bottleneck at extreme provider cardinality.

---

## Dashboard Stress Test

A synthetic `risk_scores.csv` with 600 flagged providers (all scores > 0) was generated and all app.py data-loading code paths were exercised without starting the Streamlit server.

| Code path | Elapsed (s) | Result |
|---|---|---|
| load_scores (pd.read_csv) | 0.016 | 600 rows loaded OK |
| sidebar_stats (confidence counts) | 0.002 | HIGH=211, MEDIUM=195, LOW=194 |
| kpi_compute (exposure sum, proactive count) | 0.001 | OK |
| worklist_table (rename + index reset) | 0.002 | 600 rows OK |
| analytics_prep (groupby specialty, confidence counts) | 0.002 | 6 specialties OK |
| selectbox_maps (dict construction) | 0.004 | 600 providers OK |

The dashboard loads 600 providers instantly. Streamlit's `@st.cache_data` means all six loaders above are called only once per session; no performance concern at realistic flagged-provider counts.

---

## Findings (Severity-Ranked)

### CRITICAL

**Finding C-1: `rules.py` crashes with `ValueError: No objects to concatenate` when no rule violations exist**

- **What breaks**: `run_rules()` returns a crash instead of an empty DataFrame whenever the input data contains no impossible days, no duplicates, and no unbundling patterns.
- **At what scale**: Any scale — triggered whenever all three rule-check functions return empty DataFrames (e.g., 100k claims with no planted anomalies, or `singleton_specialty` and `provider_explosion` shapes which have no ECG codes to trigger unbundling).
- **Root cause** (`rules.py:166`): `pd.concat([p for p in parts if not p.empty], ignore_index=True)` — pandas 3.x raises `ValueError: No objects to concatenate` when passed an empty list. Older pandas silently returned an empty DataFrame.
- **Reproduction steps**: Generate any claims dataset with no rule violations and call `run_rules(df)`. Confirmed by the pre-fix 100k, singleton_specialty, and provider_explosion scale tests.
- **Fix applied**: `rules.py:161–168` — check if the filtered list is empty before calling `pd.concat`; return an explicitly-typed empty DataFrame with correct column names.

---

**Finding C-2: `temporal.py` crashes with `KeyError: 'cusum_score'` on single-day datasets**

- **What breaks**: `build_temporal_scores()` returns an empty `pd.DataFrame()` with no columns when all providers are skipped by the `MIN_ACTIVE_MONTHS = 3` guard (as happens when all claims fall on one date). `sort_values("cusum_score")` on a column-less DataFrame raises `KeyError`.
- **At what scale**: Any dataset where all claims are on the same date (or fewer than 3 months of data).
- **Root cause** (`temporal.py:111`): `return pd.DataFrame(rows).sort_values("cusum_score", ascending=False)` — when `rows` is empty, the resulting DataFrame has no columns.
- **Reproduction steps**: Call `run_temporal(df)` where all `service_date` values are `2024-01-15`. Confirmed by pre-fix `single_day` shape test.
- **Fix applied**: `temporal.py:111–114` — check `result.empty` before calling `sort_values`; `run_temporal` also guards against missing `temporal_flag` column on empty result.

---

### HIGH

**Finding H-1: `fairness.py` reads `risk_scores.csv` once per group inside a per-group loop (O(n_groups) file I/O)**

- **What breaks**: `_group_stats()` calls `pd.read_csv(SCORES_CSV)` inside the `for grp_val, grp_df in providers.groupby(dimension)` loop. With 6 specialties × 20 clinics × 2 practice settings = ~28 iterations, that means 28 file reads of `risk_scores.csv` per `run_fairness_audit()` call.
- **At what scale**: Becomes measurable when `risk_scores.csv` is large (thousands of providers). At 1M-claim scale, `risk_scores.csv` could be several hundred MB.
- **Root cause** (`fairness.py:108`): `scores = pd.read_csv(SCORES_CSV, ...)` inside the loop body.
- **Reproduction steps**: Run `fairness.py` with a large `risk_scores.csv` and observe repeated disk I/O.
- **Fix applied**: `fairness.py:84–86` — move `pd.read_csv(SCORES_CSV)` and `score_map` construction to before the loop, reducing to a single file read.

---

### MEDIUM

**Finding M-1: `anomaly_model.py` uses a per-provider Python `apply` for `top_tier_share` and a per-row Python `apply` for Shannon entropy**

- **What breaks**: Correctness is preserved, but performance degrades linearly with provider count. At 10k providers the `groupby("provider_id").apply(top_share)` call adds measurable overhead; the `apply(entropy, axis=1)` call scales with n_providers × n_codes.
- **At what scale**: Noticeable at provider_explosion shape (10k providers), negligible for typical demo (150 providers).
- **Root cause** (`anomaly_model.py:182–203`): Both use Python-level `apply` rather than vectorized NumPy operations.
- **Fix applied**: `anomaly_model.py:167–218` — `top_tier_share` now uses vectorized `map` + `groupby.mean()`; entropy is computed with `np.where` and `np.sum` on the full matrix in one vectorized pass.

---

**Finding M-2: `scoring.py` uses three row-by-row Python `apply` calls in the hot path**

- **What breaks**: `top_reason`, `assign_confidence`, and `expected_recovery` all use `df.apply(..., axis=1)`, each iterating over every flagged provider in Python.
- **At what scale**: Negligible at demo scale (150 providers), but would slow proportionally at 10k+ providers.
- **Root cause** (`scoring.py:229`, `244`, `247–251`).
- **Fix applied**: `scoring.py:212–260` — all three replaced with vectorized `np.where` / `pd.Series.map` operations.

---

### LOW

**Finding L-1: `peer_stats.py` uses `iterrows()` in `build_flags()` — Python loop over providers**

- **What breaks**: Correctness preserved. Performance degrades at >1k providers. At 10k providers (provider_explosion) this function accounts for ~1.5s of the 3.75s peer_stats time.
- **At what scale**: Noticeable at provider_explosion; acceptable for demo.
- **Root cause** (`peer_stats.py:206`): `for _, prov in metrics.iterrows()`.
- **Fix applied**: Not applied (would require more substantial restructuring with non-trivial risk of logic change to the z-score threshold and one-sided flagging logic). Recommended for a follow-up hardening pass.

---

**Finding L-2: `peer_stats.py` numerical precision warning from `scipy.stats.zscore`**

- **What breaks**: `RuntimeWarning: Precision loss occurred in moment calculation due to catastrophic cancellation` fires when a cohort has nearly-identical values (e.g., all providers with the same `avg_minutes`). The function falls back to `zscore` after MAD=0, but the result may be numerically unreliable.
- **At what scale**: Occurs in pathological shapes (singleton_specialty, single_day).
- **Root cause** (`peer_stats.py:150`): `scipy_stats.zscore` with nearly-constant input.
- **Fix applied**: Not applied (warning is informational; changing the fallback behavior would alter detection results).

---

**Finding L-3: `anomaly_model.py` uses `fillna(0, inplace=True)` — deprecated pattern**

- **What breaks**: pandas 3.x warns that `inplace` on a DataFrame that is a result of a chain operation may not apply. Correctness is preserved here because `features` is an independently-created DataFrame, not a slice.
- **At what scale**: Fires at every `build_feature_matrix` call.
- **Root cause** (`anomaly_model.py:207`).
- **Fix applied**: `anomaly_model.py:221` — replaced with `features = features.fillna(0)`.

---

## Low-Risk Fixes Applied

| # | File | Line(s) | Description |
|---|---|---|---|
| 1 | `rules.py` | 161–170 | Guard `pd.concat` against empty list; return typed empty DataFrame with correct columns when no violations exist. |
| 2 | `temporal.py` | 111–114 | Guard `sort_values("cusum_score")` against empty DataFrame returned when all providers skipped by `MIN_ACTIVE_MONTHS`. |
| 3 | `temporal.py` | 125–130 | Guard `run_temporal` against missing `temporal_flag` column on empty scores DataFrame. |
| 4 | `fairness.py` | 84–86 | Move `pd.read_csv(SCORES_CSV)` outside per-group loop — from O(n_groups) to O(1) file reads. |
| 5 | `anomaly_model.py` | 167–196 | Replace per-provider Python `apply(top_share)` with vectorized `map` + `groupby.mean()`. |
| 6 | `anomaly_model.py` | 197–202 | Replace per-row Python `apply(entropy)` with vectorized `np.where` / `np.sum` matrix operation. |
| 7 | `anomaly_model.py` | 221 | Replace deprecated `fillna(0, inplace=True)` with `features = features.fillna(0)`. |
| 8 | `scoring.py` | 212–248 | Vectorize `top_reason` string building (was `apply(top_reason, axis=1)`). |
| 9 | `scoring.py` | 250–257 | Vectorize `assign_confidence` (was `apply(assign_confidence, axis=1)`) using `np.where`. |
| 10 | `scoring.py` | 259–261 | Vectorize `expected_recovery` (was `apply(lambda r: ..., axis=1)`) using `Series.map`. |

No algorithm changes, threshold changes, model changes, or schema changes were made. Detection results are preserved.

---

## Verdict

Yes — the pipeline runs smoothly on a laptop at realistic demo volumes (40k–150k claims): the full pipeline completes in under 30 seconds. Even at 1M claims all individual phases complete in under 15 seconds each. The two pre-fix crashes (rules empty-concat, temporal KeyError) were the only blockers to a clean live demo; both are now fixed.
