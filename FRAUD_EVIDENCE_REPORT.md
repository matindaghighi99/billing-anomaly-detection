# Billing Revenue-Inflation Evidence Report

> **Synthetic data.** Every provider, patient, and claim in this report is fictional. This is a decision-support discovery tool for human auditors; nothing here constitutes a finding of fraud.

## Dataset

| Field | Value |
|---|---|
| Source file | `claims_large.csv` |
| Claims analysed | 188,947 |
| Providers | 300 |
| Specialties | 15 |
| Distinct billing codes | 60 |
| Date range | 2023-01-01 → 2024-12-31 |
| Providers with ≥1 evidence signal | 24 |
| **Total estimated extra revenue** | **$4,069,218** |

_Dollar figures are estimates of revenue inflated above the specialty cohort baseline; methods can overlap, so per-provider totals are an upper-bound sum across detected schemes._

## Top revenue-inflating providers

| Rank | Provider | Specialty | Est. extra revenue | # Schemes | Methods used |
|---:|---|---|---:|---:|---|
| 1 | `PRV0084` | Neurology | $2,379,890 | 1 | Phantom / excessive claim volume |
| 2 | `PRV0008` | Psychiatry | $1,014,523 | 2 | Impossible day (>24h billed), Phantom / excessive claim volume |
| 3 | `PRV0216` | Ophthalmology | $85,253 | 1 | Unit / dosage inflation |
| 4 | `PRV0280` | Ophthalmology | $68,361 | 1 | Unit / dosage inflation |
| 5 | `PRV0279` | Gastroenterology | $68,244 | 3 | Escalating upcoding over time, Impossible day (>24h billed), Upcoding (E/M complexity inflation) |
| 6 | `PRV0069` | Radiology | $63,692 | 1 | Weekend / closed-office billing |
| 7 | `PRV0264` | Family Medicine | $63,690 | 2 | Impossible day (>24h billed), Upcoding (E/M complexity inflation) |
| 8 | `PRV0296` | Family Medicine | $43,149 | 1 | Upcoding (E/M complexity inflation) |
| 9 | `PRV0256` | Family Medicine | $42,339 | 1 | Upcoding (E/M complexity inflation) |
| 10 | `PRV0061` | Radiology | $38,679 | 1 | Duplicate claim resubmission |
| 11 | `PRV0158` | Pulmonology | $36,830 | 1 | Weekend / closed-office billing |
| 12 | `PRV0252` | Family Medicine | $35,970 | 1 | Upcoding (E/M complexity inflation) |
| 13 | `PRV0145` | Orthopedic Surgery | $19,533 | 1 | Self-referral out-of-specialty imaging |
| 14 | `PRV0162` | Orthopedic Surgery | $19,373 | 1 | Self-referral out-of-specialty imaging |
| 15 | `PRV0046` | Internal Medicine | $13,634 | 2 | Escalating upcoding over time, Upcoding (E/M complexity inflation) |
| 16 | `PRV0043` | Dermatology | $13,492 | 1 | Modifier-25 separate-E/M abuse |
| 17 | `PRV0055` | Internal Medicine | $13,094 | 2 | Escalating upcoding over time, Upcoding (E/M complexity inflation) |
| 18 | `PRV0262` | Dermatology | $12,511 | 1 | Modifier-25 separate-E/M abuse |
| 19 | `PRV0122` | Family Medicine | $11,469 | 1 | Duplicate claim resubmission |
| 20 | `PRV0009` | Orthopedic Surgery | $10,838 | 1 | Duplicate claim resubmission |
| 21 | `PRV0125` | Psychiatry | $6,600 | 1 | Psychotherapy time inflation |
| 22 | `PRV0268` | Psychiatry | $5,680 | 1 | Psychotherapy time inflation |
| 23 | `PRV0039` | Cardiology | $1,221 | 1 | Unbundling component codes |
| 24 | `PRV0012` | Cardiology | $1,152 | 1 | Unbundling component codes |

## Evidence by scheme

| Scheme | Providers | Est. extra revenue |
|---|---:|---:|
| Phantom / excessive claim volume | 2 | $3,359,044 |
| Upcoding (E/M complexity inflation) | 7 | $173,189 |
| Unit / dosage inflation | 2 | $153,614 |
| Impossible day (>24h billed) | 3 | $127,719 |
| Weekend / closed-office billing | 2 | $100,522 |
| Duplicate claim resubmission | 3 | $60,986 |
| Self-referral out-of-specialty imaging | 2 | $38,906 |
| Modifier-25 separate-E/M abuse | 2 | $26,003 |
| Escalating upcoding over time | 3 | $14,582 |
| Psychotherapy time inflation | 2 | $12,280 |
| Unbundling component codes | 2 | $2,373 |

### Phantom / excessive claim volume

_2 provider(s), $3,359,044 estimated extra revenue._

- **`PRV0084`** (Neurology) — $2,379,890, 9797 claims/events: 24.2 claims/active-day vs Neurology cohort median 1.2 (~9,319 excess claims)
- **`PRV0008`** (Psychiatry) — $979,154, 8263 claims/events: 24.0 claims/active-day vs Psychiatry cohort median 1.2 (~7,857 excess claims)

### Upcoding (E/M complexity inflation)

_7 provider(s), $173,189 estimated extra revenue._

- **`PRV0296`** (Family Medicine) — $43,149, 694 claims/events: Top-tier E/M codes on 86% of 694 office visits vs Family Medicine cohort median 26%; avg E/M $181 vs cohort $118
- **`PRV0256`** (Family Medicine) — $42,339, 664 claims/events: Top-tier E/M codes on 87% of 664 office visits vs Family Medicine cohort median 26%; avg E/M $182 vs cohort $118
- **`PRV0252`** (Family Medicine) — $35,970, 572 claims/events: Top-tier E/M codes on 87% of 572 office visits vs Family Medicine cohort median 26%; avg E/M $181 vs cohort $118
- **`PRV0264`** (Family Medicine) — $18,088, 708 claims/events: Top-tier E/M codes on 49% of 708 office visits vs Family Medicine cohort median 26%; avg E/M $144 vs cohort $118
- **`PRV0279`** (Gastroenterology) — $15,602, 344 claims/events: Top-tier E/M codes on 65% of 344 office visits vs Gastroenterology cohort median 0%; avg E/M $175 vs cohort $130
- **`PRV0046`** (Internal Medicine) — $9,605, 231 claims/events: Top-tier E/M codes on 71% of 231 office visits vs Internal Medicine cohort median 27%; avg E/M $172 vs cohort $131

### Unit / dosage inflation

_2 provider(s), $153,614 estimated extra revenue._

- **`PRV0216`** (Ophthalmology) — $85,253, 101 claims/events: Inflated units on dose-based codes: 67028(avg 4.4u vs 1)
- **`PRV0280`** (Ophthalmology) — $68,361, 99 claims/events: Inflated units on dose-based codes: 67028(avg 3.8u vs 1)

### Impossible day (>24h billed)

_3 provider(s), $127,719 estimated extra revenue._

- **`PRV0279`** (Gastroenterology) — $46,748, 6 claims/events: 6 day(s) over 1440 service-minutes; worst: 1,510 min across 38 claims on 2023-05-23
- **`PRV0264`** (Family Medicine) — $45,602, 6 claims/events: 6 day(s) over 1440 service-minutes; worst: 1,530 min across 39 claims on 2023-08-31
- **`PRV0008`** (Psychiatry) — $35,370, 10 claims/events: 10 day(s) over 1440 service-minutes; worst: 1,535 min across 29 claims on 2023-11-22

### Weekend / closed-office billing

_2 provider(s), $100,522 estimated extra revenue._

- **`PRV0069`** (Radiology) — $63,692, 192 claims/events: 192 claims ($63,692) billed on weekends — unusual for an outpatient Radiology practice
- **`PRV0158`** (Pulmonology) — $36,830, 207 claims/events: 207 claims ($36,830) billed on weekends — unusual for an outpatient Pulmonology practice

### Duplicate claim resubmission

_3 provider(s), $60,986 estimated extra revenue._

- **`PRV0061`** (Radiology) — $38,679, 123 claims/events: 123 claim(s) resubmitted with identical patient, code, date and units (paid more than once)
- **`PRV0122`** (Family Medicine) — $11,469, 103 claims/events: 103 claim(s) resubmitted with identical patient, code, date and units (paid more than once)
- **`PRV0009`** (Orthopedic Surgery) — $10,838, 50 claims/events: 50 claim(s) resubmitted with identical patient, code, date and units (paid more than once)

### Self-referral out-of-specialty imaging

_2 provider(s), $38,906 estimated extra revenue._

- **`PRV0145`** (Orthopedic Surgery) — $19,533, 50 claims/events: Billed 50 high-value MRI/CT studies ($19,533) under the Orthopedic Surgery specialty — imaging normally read by Radiology
- **`PRV0162`** (Orthopedic Surgery) — $19,373, 50 claims/events: Billed 50 high-value MRI/CT studies ($19,373) under the Orthopedic Surgery specialty — imaging normally read by Radiology

### Modifier-25 separate-E/M abuse

_2 provider(s), $26,003 estimated extra revenue._

- **`PRV0043`** (Dermatology) — $13,492, 104 claims/events: 104 office visits billed with modifier 25 (separately-payable E/M) stacked onto same-day procedures ($13,492)
- **`PRV0262`** (Dermatology) — $12,511, 96 claims/events: 96 office visits billed with modifier 25 (separately-payable E/M) stacked onto same-day procedures ($12,511)

### Escalating upcoding over time

_3 provider(s), $14,582 estimated extra revenue._

- **`PRV0279`** (Gastroenterology) — $5,894, 344 claims/events: Top-tier E/M share climbed from 40% (early) to 73% (late); avg visit $158 → $182
- **`PRV0055`** (Internal Medicine) — $4,659, 243 claims/events: Top-tier E/M share climbed from 44% (early) to 82% (late); avg visit $146 → $185
- **`PRV0046`** (Internal Medicine) — $4,029, 231 claims/events: Top-tier E/M share climbed from 53% (early) to 89% (late); avg visit $155 → $189

### Psychotherapy time inflation

_2 provider(s), $12,280 estimated extra revenue._

- **`PRV0125`** (Psychiatry) — $6,600, 181 claims/events: Billed 60-min psychotherapy (90837) on 91% of 181 sessions vs cohort median 28%
- **`PRV0268`** (Psychiatry) — $5,680, 164 claims/events: Billed 60-min psychotherapy (90837) on 87% of 164 sessions vs cohort median 28%

### Unbundling component codes

_2 provider(s), $2,373 estimated extra revenue._

- **`PRV0039`** (Cardiology) — $1,221, 122 claims/events: 122 patient-dates billed 93005+93010 separately instead of bundle 93000 (ECG Complete)
- **`PRV0012`** (Cardiology) — $1,152, 116 claims/events: 116 patient-dates billed 93005+93010 separately instead of bundle 93000 (ECG Complete)

## Detection vs planted ground truth

- Planted bad actors: **24**
- Detected (≥1 signal): **24/24** (100% recall)
- Providers flagged that were NOT planted: **0** (expected — real cohorts contain naturally aggressive billers)

## Method & caveats

- Each detector compares a provider to the **median of their own specialty cohort**, so high-acuity specialties are not penalised for billing high-value codes.
- Signals are **evidence for human review**, not automated determinations. Many have legitimate explanations (busy hospital readers, complex case-mix, locum schedules).
- Dollar estimates are deliberately conservative baselines for triage/prioritisation, not recovery amounts.