# Billing Anomaly Detection -- Fairness Audit Report

**Generated:** 2026-06-08 12:37
**Total providers:** 153
**Providers flagged:** 12
**Overall flag rate:** 7.8%
**Planted bad actors:** 10

---

## Methodology

For each grouping variable (specialty, clinic, practice-setting) we compute the flag rate (fraction of providers in the group that appear on the audit worklist) and test whether it differs from the rest of the population using a chi-square test with Yates continuity correction. A group is highlighted when p < 0.05 AND the group's flag rate exceeds the overall average -- indicating unexplained over-representation.

---

## Specialty Breakdown

| Specialty | Providers | Flagged | Flag Rate | Mean Score | Confirmed Bad | Precision | chi2 p | Alert |
|--------------|--------------|--------------|--------------|--------------|--------------|--------------|--------------|--------------|
| Surgery | 9 | 1 | 11.1% | 5.3 | 1 | 100% | 1.000 | no |
| Family Medicine | 45 | 5 | 11.1% | 6.3 | 4 | 80% | 0.522 | no |
| Dermatology | 12 | 1 | 8.3% | 8.3 | 1 | 100% | 1.000 | no |
| Psychiatry | 28 | 2 | 7.1% | 4.6 | 2 | 100% | 1.000 | no |
| Cardiology | 38 | 2 | 5.3% | 3.2 | 1 | 50% | 0.738 | no |
| Radiology | 21 | 1 | 4.8% | 2.9 | 1 | 100% | 0.898 | no |

## Clinic Breakdown

| Clinic | Providers | Flagged | Flag Rate | Mean Score | Confirmed Bad | Precision | chi2 p | Alert |
|--------------|--------------|--------------|--------------|--------------|--------------|--------------|--------------|--------------|
| CLN18 | 8 | 2 | 25.0% | 16.0 | 1 | 50% | 0.238 | no |
| CLN12 | 5 | 1 | 20.0% | 8.0 | 1 | 100% | 0.855 | no |
| CLN05 | 7 | 1 | 14.3% | 7.6 | 1 | 100% | 1.000 | no |
| CLN17 | 7 | 1 | 14.3% | 8.7 | 1 | 100% | 1.000 | no |
| CLN04 | 8 | 1 | 12.5% | 4.6 | 1 | 100% | 1.000 | no |
| CLN19 | 9 | 1 | 11.1% | 11.1 | 1 | 100% | 1.000 | no |
| CLN15 | 9 | 1 | 11.1% | 7.2 | 1 | 100% | 1.000 | no |
| CLN20 | 11 | 1 | 9.1% | 8.0 | 1 | 100% | 1.000 | no |
| CLN07 | 11 | 1 | 9.1% | 7.6 | 1 | 100% | 1.000 | no |
| CLN03 | 13 | 1 | 7.7% | 3.7 | 1 | 100% | 1.000 | no |
| CLN01 | 10 | 0 | 0.0% | 0.0 | 0 | nan% | 0.729 | no |
| CLN06 | 9 | 0 | 0.0% | 0.0 | 0 | nan% | 0.792 | no |
| CLN02 | 5 | 0 | 0.0% | 0.0 | 0 | nan% | 1.000 | no |
| CLN09 | 5 | 0 | 0.0% | 0.0 | 0 | nan% | 1.000 | no |
| CLN08 | 6 | 0 | 0.0% | 0.0 | 0 | nan% | 1.000 | no |
| CLN14 | 7 | 0 | 0.0% | 0.0 | 0 | nan% | 0.944 | no |
| CLN11 | 9 | 0 | 0.0% | 0.0 | 0 | nan% | 0.792 | no |

## Practice Setting Breakdown

| Practice Setting | Providers | Flagged | Flag Rate | Mean Score | Confirmed Bad | Precision | chi2 p | Alert |
|--------------|--------------|--------------|--------------|--------------|--------------|--------------|--------------|--------------|
| full_time | 152 | 12 | 7.9% | 4.9 | 10 | 83% | 1.000 | no |

---

## Summary of Alerts

No statistically significant unexplained over-flagging detected. All elevated flag rates are accounted for by planted bad actors.

---

> **Note:** This system operates on synthetic data. All findings are for demonstration only. In a production system, over-flagging of specific demographic or geographic groups would require investigation before deployment.