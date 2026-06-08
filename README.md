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
| Peer Stats | Z-score benchmarking | Upcoders, volume outliers vs specialty peers |
| ML | Isolation Forest | Novel patterns no rule covers |

All three layers combine into a single 0-100 risk score weighted by dollar
exposure, so the biggest-risk cases always appear at the top of the worklist.

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

## Running Each Phase

Run phases in order (each writes output files consumed by later phases):

```bash
# Phase 1 — generate 52 000+ synthetic claims + plant 10 bad actors
python data_gen.py

# Phase 2 — deterministic rule checks (impossible days, duplicates, unbundling)
python rules.py

# Phase 3 — peer-group benchmarking (z-scores within specialty)
python peer_stats.py

# Phase 4 — IsolationForest anomaly scoring
python anomaly_model.py

# Phase 5 — combine all layers into ranked risk scores
python scoring.py

# Phase 6 — generate plain-English explanations
python explain.py

# Optional: verify detection against ground truth
python verify.py
```

**Optional Anthropic API enrichment** (Phase 6):

```bash
set ANTHROPIC_API_KEY=sk-ant-...
python explain.py
```

If the key is absent, explain.py silently falls back to template-based output.

---

## Launch the Dashboard (Phase 7)

```bash
streamlit run app.py
```

Open http://localhost:8501 in your browser.

### Dashboard features

- **Warning banner** reminding auditors this is decision-support only
- **Three KPI tiles**: total flagged exposure, providers flagged, proactive finds
  (surfaced by stats/ML rather than complaints)
- **Ranked worklist table** with colour-coded risk scores
- **Provider detail view** with four tabs:
  - Rule Evidence — specific violations with dollar amounts
  - Peer Comparison — bar chart vs specialty median for 5 metrics
  - Monthly Volume — claims and billing trend over the year
  - Explanation — plain-English audit summary

---

## Output Files

| File | Description |
|------|-------------|
| `claims.csv` | 52 000+ synthetic claims |
| `ground_truth.json` | Planted bad-actor provider IDs (do not peek until after scoring) |
| `rules_flags.csv` | Deterministic rule violations |
| `peer_flags.csv` | Peer-stat outliers (|z| > 3) |
| `provider_metrics.csv` | Per-provider billing metrics |
| `ml_scores.csv` | IsolationForest scores (0-100) |
| `risk_scores.csv` | Combined ranked risk scores |
| `explanations.json` | Plain-English audit summaries |

---

## Detection Results (fixed seed 42)

All 10 planted bad actors detected in the top 10 ranked providers;
zero false positives in the top 10.

| Provider | Fraud Type | Rank | Risk Score |
|----------|-----------|------|------------|
| PRV0025 | volume_outlier | 1 | 87.8 |
| PRV0089 | impossible_day | 2 | 84.9 |
| PRV0045 | impossible_day | 3 | 82.6 |
| PRV0133 | duplicate | 4 | 61.8 |
| PRV0098 | volume_outlier | 5 | 24.9 |
| PRV0112 | novel (ML-only) | 6 | 39.0 |
| PRV0008 | upcoder | 7 | 39.8 |
| PRV0077 | duplicate | 8 | 52.6 |
| PRV0142 | unbundler | 9 | 77.9 |
| PRV0006 | upcoder | 10 | 19.9 |
