# Sample claims datasets — test the detector before real OHIP data

Five small, labelled claims files (plus a copy of the original demo set), each a
**different specialty** and a **different fraud/suspicion pattern**, so you can
point the system at each one and confirm it flags the planted bad actor. Every
file uses the exact production claims schema.

> All data here is **synthetic**. The answer key (which provider is bad and why)
> is in `ANSWER_KEY.json`. Regenerate everything with
> `python sample_claims/generate_samples.py`.

## The datasets

| File | Specialty | Planted scheme | Bad actor | Caught by |
|------|-----------|----------------|-----------|-----------|
| `claims_internalmed_upcoding.csv` | Internal Medicine | Upcoding — bills the complex E/M code (99215) for nearly every visit | `IMP999` | Peer-stats (top-tier share / avg billed) |
| `claims_radiology_overimaging.csv` | Radiology | Over-utilisation / self-referral — images at ~4× peer volume, heavy on the costliest MRI | `RAD999` | Peer-stats (volume / total-billed outlier) |
| `claims_familymed_impossibleday.csv` | Family Medicine | Impossible day — >1,440 billed minutes in a single day (phantom visits) | `FAM999` | Rules (impossible_day) |
| `claims_cardiology_unbundling.csv` | Cardiology | Unbundling — bills ECG components 93005+93010 separately instead of the 93000 bundle | `CAR999` | Rules (unbundling + duplicate) |
| `claims_psychiatry_temporalspike.csv` | Psychiatry | Temporal spike — normal for H1, then ~2.5× volume in H2 | `PSY999` | Temporal (CUSUM change-point) |
| `claims_baseline_demo.csv` | (6 specialties) | The original demo set (10 planted actors) | see repo | All layers |

All five were verified end-to-end: in each case the planted bad actor is the
**#1 ranked provider** on the worklist.

## Schema (required columns)

```
claim_id, provider_id, provider_name, specialty, patient_id, service_date,
fee_code, fee_description, service_minutes, units, amount_billed, clinic_id
```

Any CSV with these columns can be fed to the system. Include several clean
providers per specialty (≥5) so the peer-comparison detector has a baseline.

---

## How to change the data feeding the system

The system reads its input from the **`CLAIMS_FILE`** environment variable. When
unset it defaults to `data/claims.csv` (or `data/claims_large.csv` when
`DATASET=large`). So pointing the pipeline at any file is one variable:

### 1. Run a sample through the full pipeline

```bash
# from the repository root
CLAIMS_FILE=sample_claims/claims_internalmed_upcoding.csv DATASET=demo \
    python data_pipeline/run_pipeline.py --no-regen
```

- `CLAIMS_FILE=…` — the dataset to analyse.
- `--no-regen` — **important**: tells the runner to use `CLAIMS_FILE` as-is and
  NOT overwrite it with freshly generated synthetic data.
- `DATASET=demo` — keeps the output filenames unsuffixed (`data/risk_scores.csv`).

The detectors write their results to `data/` (`risk_scores.csv`,
`rules_flags.csv`, `peer_flags.csv`, …).

### 2. See the ranked results

```bash
python -c "import pandas as pd; d=pd.read_csv('data/risk_scores.csv'); \
print(d.sort_values('risk_score',ascending=False).head(10)[['provider_id','risk_score','top_reason']].to_string(index=False))"
```

Or open it in the dashboard (it reads the `data/` outputs you just produced):

```bash
DATASET=demo streamlit run dashboard/app.py
```

### 3. Try the others / your own data

```bash
CLAIMS_FILE=sample_claims/claims_radiology_overimaging.csv  DATASET=demo python data_pipeline/run_pipeline.py --no-regen
CLAIMS_FILE=sample_claims/claims_cardiology_unbundling.csv  DATASET=demo python data_pipeline/run_pipeline.py --no-regen
CLAIMS_FILE=/path/to/your_own_claims.csv                    DATASET=demo python data_pipeline/run_pipeline.py --no-regen
```

### 4. Reset back to the standard demo data

```bash
rm -rf data reports
DATASET=demo python data_pipeline/run_pipeline.py
```

### When the real OHIP data arrives

Same mechanism — point `CLAIMS_FILE` at the real claims export (mapped to the
schema above), or replace `data/claims_large.csv` and run with `DATASET=large`.
Nothing else changes. (For a managed deployment, also set `PIPELINE_DATA_DIR`
to the mounted data volume — see `docs/PRODUCTION_READINESS.md`.)
