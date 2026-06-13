# Detection Accuracy Validation

> ⚠ **NOT VALIDATED FOR PRODUCTION.** Basis: **SYNTHETIC**. These metrics are measured on the synthetic answer key, not real adjudicated outcomes. Provide `adjudicated_outcomes.csv` (provider_id, outcome[, recovered_amount]) and set `VALIDATION_TRUSTED=1` once accuracy has been confirmed.

| Metric | Value |
|---|---|
| Labelled providers | 300 |
| Flagged (worklist) | 23 |
| True positives | 23 |
| False positives | 0 |
| False negatives | 1 |
| True negatives | 276 |
| **Precision** | **1.0** |
| **Recall** | **0.958** |
| Specificity | 1.0 |
| F1 | 0.979 |

## Recovery-estimate calibration

_Not available — requires `recovered_amount` in adjudicated outcomes. Until then, recovery figures are unvalidated estimates._

## Clinical / medical-necessity review

- Concerns requiring s.18(8)(e) clinical review with an opinion recorded: **0**; opinions supporting necessity: 0, not medically necessary: 0.