# Physician Billing Anomaly Detection Demo

Decision-support tool that turns a reactive, complaint-driven audit process into
a proactive, dollar-ranked worklist for a small audit team.

> **SYNTHETIC DATA ONLY** — All providers, patients, and claims are entirely
> fictional. This system is designed to flag candidates for **human review**;
> it never makes automated decisions or penalties.

---

## What It Demonstrates

| Layer | Technique | What It Catches |
|-------|-----------|-----------------|
| Rules | Deterministic checks | Impossible days, duplicates, unbundling |
| Peer Stats | MAD modified z-score (specialty + practice-setting cohort) | Upcoders, volume outliers; robust to extreme values |
| Code-Mix Drift | KL divergence + cosine distance vs cohort median | Over-use of specific billing codes |
| Temporal | CUSUM change-point + spike detection | Sudden-onset billing increases |
| ML Ensemble | IsolationForest + LOF + OC-SVM (majority vote) | Novel patterns no rule covers |
| Feedback | Semi-supervised XGBoost on auditor dispositions | Gets smarter with use |
| SHAP | TreeExplainer on IsolationForest | Per-feature attribution for ML flags |

All layers combine into a single 0-100 risk score with **confidence tiers** (HIGH/MEDIUM/LOW)
and **expected recovery** (exposure x recovery likelihood), so the highest-value actionable
cases appear at the top of the worklist.

---

## Requirements

```
Python 3.10+
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Quickstart

### Option A: One-command pipeline runner (recommended)

```bash
# Full pipeline with timing output
python run_pipeline.py

# Fast mode: two-stage funnel (ML only on rule/peer candidates)
python run_pipeline.py --fast

# Skip data regeneration if claims.csv already exists
python run_pipeline.py --no-regen
```

### Option B: Run phases individually

```bash
# Phase 1 -- generate 52,000+ synthetic claims + plant 10 bad actors + 3 clean traps
python data_gen.py

# Phase 2 -- deterministic rule checks (impossible days, duplicates, unbundling)
python rules.py

# Phase 3 -- peer-group benchmarking (MAD z-scores within specialty + practice-setting cohort)
python peer_stats.py

# Phase 3b -- code-mix drift (KL divergence + cosine distance)
python codemix.py

# Phase 4 -- temporal change-point detection (CUSUM + spike)
python temporal.py

# Phase 4b -- ensemble anomaly scoring (IF + LOF + OC-SVM)
python anomaly_model.py

# Phase 5 -- combine all layers into ranked risk scores with confidence tiers
python scoring.py

# Phase 6 -- SHAP explanations + plain-English audit summaries
python explain.py

# Phase 7 -- feedback loop: seed demo dispositions, train semi-supervised model
python feedback.py --seed-demo

# Phase 9 -- fairness audit by specialty / clinic / practice-setting
python fairness.py

# Validate detection against ground truth
python validate.py
```

**Optional Anthropic API enrichment** (explain.py):

```bash
set ANTHROPIC_API_KEY=sk-ant-...
python explain.py
```

---

## Launch the Dashboard

```bash
streamlit run app.py
```

Open http://localhost:8501 in your browser.

### Dashboard features

- **Warning banner** reminding auditors this is decision-support only
- **Three KPI tiles**: total flagged exposure, providers flagged, proactive finds
- **Ranked worklist table** with risk score, confidence tier, and expected recovery
- **Provider detail view** with four tabs:
  - Rule Evidence -- specific violations with dollar amounts + peer-stat outliers
  - Peer Comparison -- bar chart vs specialty median for 5 metrics
  - Monthly Volume -- claims and billing trend over the year
  - Explanation -- SHAP feature drivers + plain-English audit summary
- **Model Card** (bottom, expandable) -- methodology, confidence tiers, known limitations, fairness audit results

---

## Output Files

| File | Description |
|------|-------------|
| `claims.csv` | ~54,000 synthetic claims |
| `ground_truth.json` | Planted bad-actor + clean-trap IDs |
| `rules_flags.csv` | Deterministic rule violations |
| `peer_flags.csv` | Peer-stat outliers (MAD |z| > 3.5) |
| `provider_metrics.csv` | Per-provider billing metrics |
| `provider_codemix.csv` | KL divergence + cosine distance per provider |
| `provider_temporal.csv` | CUSUM scores + spike flags per provider |
| `ml_scores.csv` | Ensemble anomaly scores (0-100) + per-detector flags |
| `risk_scores.csv` | Combined ranked risk scores with confidence + expected recovery |
| `feedback_scores.csv` | Semi-supervised feedback model scores |
| `shap_values.csv` | Full SHAP value matrix (provider x feature) |
| `shap_explanations.csv` | Plain-English SHAP attribution per provider |
| `explanations.json` | Full audit summaries (template + optional API) |
| `fairness_summary.csv` | Flag rates + chi-square p-values by specialty/clinic/setting |
| `fairness_report.md` | Human-readable fairness audit report |
| `dispositions.csv` | Auditor-recorded confirmed/cleared dispositions |

---

## Detection Results (upgrades branch, seed 42)

After all 11 upgrade phases vs. the baseline:

| Metric | Baseline | After All Phases | Delta |
|--------|----------|------------------|-------|
| Detection top-10 (%) | 80% | **90%** | +10 |
| Detection top-20 (%) | 100% | 100% | 0 |
| Avg rank of bad actors | 6.1 | **5.8** | -0.3 |
| False-positive rate (traps) | 100% (3/3) | **33% (1/3)** | -67% |
| Spurious FP in top-20 | 8 | **1** (PRV0127) | -7 |

The remaining false positive (TRAP03) is a sub-threshold marathoner whose long working days are genuinely statistically unusual even though they stay below the 1,440-minute limit. PRV0127 has a single accidental duplicate claim -- a legitimate rule trigger.

### Final worklist (top 11)

| Rank | Provider | Type | Score | Confidence | Est. Exposure |
|------|----------|------|-------|------------|---------------|
| 1 | PRV0025 | volume_outlier | 88.2 | HIGH | $213,461 |
| 2 | PRV0045 | impossible_day | 100.0 | HIGH | $37,966 |
| 3 | PRV0089 | impossible_day | 90.4 | HIGH | $38,206 |
| 4 | PRV0098 | volume_outlier | 36.5 | MEDIUM | $621,307 |
| 5 | PRV0006 | upcoder | 47.4 | MEDIUM | $141,573 |
| 6 | PRV0112 | novel | 53.6 | MEDIUM | $59,524 |
| 7 | PRV0133 | duplicate | 60.8 | HIGH | $20,226 |
| 9 | PRV0008 | upcoder | 39.8 | MEDIUM | $37,631 |
| 10 | PRV0077 | duplicate | 64.0 | HIGH | $5,440 |
| 11 | PRV0142 | unbundler | 83.4 | HIGH | $1,427 |

---

## Architecture

```
data_gen.py        -- synthetic claim generator; seeds bad actors + clean traps
rules.py           -- deterministic rule engine
peer_stats.py      -- MAD z-score benchmarking with cohort stratification
codemix.py         -- KL divergence + cosine code-mix drift
temporal.py        -- CUSUM change-point + spike detection
anomaly_model.py   -- IF + LOF + OC-SVM ensemble; DuckDB feature matrix
feedback.py        -- semi-supervised feedback loop
scoring.py         -- multi-layer risk scoring, confidence tiers, expected recovery
explain.py         -- SHAP feature attribution + plain-English summaries
fairness.py        -- disparate-impact audit by specialty/clinic/setting
validate.py        -- ground-truth validation harness
run_pipeline.py    -- orchestrator with two-stage funnel (--fast mode)
app.py             -- Streamlit audit dashboard
```
