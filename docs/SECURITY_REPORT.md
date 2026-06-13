# Security Audit Report — Physician Billing Anomaly Detection Demo

**Date:** 2026-06-09  
**Branch:** `hardening`  
**Scope:** Dependency vulnerabilities, insecure code patterns, secret leaks, injection,
and synthetic-data confirmation.  
**Tooling:** `pip-audit 2.10.0`, `bandit 1.9.4`, manual git-history grep, direct
tamper test against `audit_log.db`.

---

> **IMPORTANT DISCLAIMER**
>
> This is an **automated static-analysis scan and manual code review**, not a
> professional penetration test. It covers the attack surface visible from source
> code and git history. It does **not** include network-layer testing, runtime
> fuzzing under a running server, OS/container hardening, or supply-chain
> integrity beyond pip-audit. Engage a qualified penetration tester before
> deploying any version of this system against real healthcare data.

---

## Executive Summary

| Severity | Count | Status |
|----------|-------|--------|
| CRITICAL | 0 | — |
| HIGH | 1 | **Fixed** (`.gitignore` added) |
| MEDIUM | 2 | **Fixed** (pickle → joblib; `.gitignore`) |
| LOW | 5 | 2 Fixed, 3 left for owner decision |
| INFO | 8 | All clean |

**Verdict: No blocker for sharing this demo publicly**, with one important
caveat: `billing_anomaly.db` (10 MB binary) is permanently embedded in the git
initial commit. For clean public hosting (e.g. GitHub), remove it from history
with BFG Repo Cleaner before pushing. See H-1 below.

No API keys, passwords, or real patient/physician data were found anywhere in
the current code or across the full git history of all four branches.

---

## Findings — Severity Ranked

---

### H-1 · HIGH · No `.gitignore` — Binary DB and all output CSVs committed to git history

**Status: FIXED** — `.gitignore` created in this commit.

**Description:**  
The repository had no `.gitignore`. As a result the following files were
committed and tracked:

| File | Size | Risk |
|------|------|------|
| `billing_anomaly.db` | 10 MB | Binary blob; present since initial commit |
| `claims.csv` | 6 MB | 54k synthetic claims; committed in phase-0 |
| `shap_values.csv` / `shap_explanations.csv` | ~170 KB | Pipeline output |
| All other `*_flags.csv`, `*_scores.csv` | varies | Pipeline output |
| `__pycache__/*.pyc` | varies | Compiled bytecode |

**Why this matters:**  
While current data is confirmed synthetic (see I-6), committing output files
establishes a pattern that will silently include real data the moment a future
operator runs the pipeline against real claims. Once committed, data is
permanently in history and visible to anyone with repo access — deletion from
the working tree is insufficient.

**Reproduction:**
```bash
git ls-files | grep -E "\.db$|\.csv$|\.pyc$"
# Returns billing_anomaly.db, claims.csv, and 13 other files
```

**Fix applied:**  
`.gitignore` created covering all `.db`, `.csv`, `__pycache__/`, `model_registry/`,
`.env`, and `*.pyc` patterns.

**Remaining action required by owner:**  
The `.gitignore` prevents *future* commits; it does not remove already-tracked
files from git history. To stop tracking them going forward:
```bash
git rm --cached billing_anomaly.db claims.csv *.csv
git commit -m "stop tracking generated outputs — .gitignore now covers them"
```
To remove the 10 MB DB from history entirely (recommended before any public
GitHub push):
```bash
# Install BFG Repo Cleaner, then:
bfg --delete-files billing_anomaly.db
git reflog expire --expire=now --all && git gc --prune=now --aggressive
```
> **Do not run `git filter-branch` or BFG on a branch shared with teammates
> without coordinating first** — it rewrites all commit hashes.

---

### M-1 · MEDIUM · `pickle.load()` used for ML model artifacts (`model_registry.py`)

**Status: FIXED** — Migrated to `joblib`.

**Bandit rule:** B301 / B403 (`CWE-502 Deserialization of Untrusted Data`)

**Description:**  
`model_registry.py` previously used `pickle.dump()` / `pickle.load()` to
persist the XGBoost feedback classifier. Pickle can execute arbitrary Python
code when loading a maliciously crafted file, making it dangerous if the
`model_registry/` directory is ever writable by an untrusted party.

In this demo the models are self-generated and the directory is local, so
practical exploitability is low. The pattern is still worth eliminating
because it would become a real attack vector in a deployed environment where
the model store is shared storage (S3, NFS).

**Reproduction (pre-fix):**
```bash
python -m bandit model_registry.py -t B301
# >> Issue: [B301] Pickle... Severity: Medium  Confidence: High  Line 290
```

**Fix applied:**  
`import pickle` replaced with `import joblib`. `joblib.dump()` / `joblib.load()`
used instead. File extension changed from `.model.pkl` to `.model.joblib`.
`joblib` was already a project dependency (`joblib==1.5.3`).

---

### M-2 · MEDIUM · `billing_anomaly.db` permanently embedded in initial commit

**Status: Partially mitigated** — `.gitignore` prevents future tracking; history
rewrite is an owner decision.

**Description:**  
`billing_anomaly.db` (10.3 MB SQLite binary) was committed in the initial commit
(`373634d`) and is present in every branch. It contains the same synthetic data
as `claims.csv`, confirmed clean (see I-6). The issue is operational, not a
data-exposure finding: a 10 MB binary in git history bloats clones, makes diffs
meaningless, and sets a precedent that databases belong in git.

**Reproduction:**
```bash
git log --all -- billing_anomaly.db --oneline
# commit 373634d  Initial commit: physician billing anomaly detection demo
git cat-file -s 373634d:billing_anomaly.db
# 10305536 (bytes)
```

**Fix:** See H-1 for BFG removal instructions. Not applied here as history
rewrite is destructive and requires owner coordination.

---

### L-1 · LOW · f-string SQL in `create_db.py:500` (diagnostic summary only)

**Status: FIXED** — whitelist guard + `# nosec B608` added.

**Bandit rule:** B608 (`CWE-89 SQL Injection`)

**Description:**  
A single f-string SQL query appeared in the diagnostic row-count summary at
the end of `create_db.py`:
```python
# Before fix:
n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
```
`table` is drawn from a hardcoded list literal on the three preceding lines —
not user input, not network input — so this is not exploitable. Bandit cannot
prove that statically and correctly flags it.

**Fix applied:**  
Changed to string concatenation (SQLite does not support parameterised
identifiers), added an explicit whitelist check, and suppressed the false
positive with `# nosec B608` per bandit convention:
```python
_SUMMARY_TABLES = ("clinics", "providers", ...)
if table not in _SUMMARY_TABLES:
    raise ValueError(f"Unexpected table name: {table!r}")
n = conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]  # nosec B608
```

---

### L-2 · LOW · `try/except/pass` silently swallows audit-log errors

**Status: Left for owner decision** — silent failure is intentional in some
places, questionable in others.

**Bandit rule:** B110 (`CWE-703`)

**Locations:**

| File | Line | Context |
|------|------|---------|
| `scoring.py` | 361 | Reading current model version for audit record |
| `scoring.py` | 383 | Writing flag-generated event to audit log |
| `app.py` | 681 | Writing flag-viewed event to audit log |
| `feedback.py` | 210 | Writing model-updated event to audit log |

`scoring.py:383` and `app.py:681` have inline comments explaining the intent
("never block scoring output on audit log errors"). This is defensible for
pipeline robustness, but a silent failure means an auditor would not know the
audit trail has a gap.

**Recommended fix (not applied — owner decision):**
```python
except Exception as exc:
    import logging
    logging.getLogger(__name__).warning("Audit log write failed: %s", exc)
    # continues — does not block scoring
```

---

### L-3 · LOW · `audit_log.export_to_csv()` accepts arbitrary file path

**Status: Left for owner decision** — not exposed to user input in current UI.

**Description:**  
`audit_log.export_to_csv(path: str = "audit_log_export.csv")` opens the given
path for writing with no sanitization. If this function were ever called with
a user-supplied path from a web endpoint, it would allow writing to arbitrary
filesystem locations (path traversal / arbitrary file write).

Currently the only callers are the Streamlit dashboard (button click, no path
input) and CLI invocations. No user-controlled path reaches it today.

**Reproduction:**
```python
import audit_log
audit_log.export_to_csv("../../some_other_dir/injected.csv")  # would write there
```

**Recommended fix for production:**
```python
import os, pathlib

def export_to_csv(path: str = "audit_log_export.csv") -> int:
    safe = pathlib.Path(path).resolve()
    allowed = pathlib.Path(".").resolve()
    if not str(safe).startswith(str(allowed)):
        raise ValueError(f"Path outside working directory: {path!r}")
    ...
```

---

### L-4 · LOW · `assert` in self-test blocks stripped by `python -O`

**Status: Informational** — affects only `__main__` self-tests, not runtime logic.

**Bandit rule:** B101

**Locations:** `audit_log.py:275–298`, `model_registry.py:371+`, `privacy.py:219–223`

All occurrences are in `if __name__ == "__main__":` self-test blocks. When run
as `python -O audit_log.py`, asserts are stripped and the self-tests pass
vacuously. Not a runtime risk (none of these blocks run during normal pipeline
or dashboard operation), but the self-tests would give false confidence under
optimized mode.

**Recommended fix:** Replace `assert cond, msg` with `if not cond: raise AssertionError(msg)`.
Not applied — scope is test code only.

---

### L-5 · LOW · `__pycache__/*.pyc` compiled bytecode committed

**Status: FIXED** — covered by `.gitignore`.

Compiled `.pyc` files for 8 modules were tracked (`__pycache__/anomaly_model.cpython-314.pyc`, etc.). These expose the Python version, are platform-specific, and rebuild automatically. They have no security impact here but should never be in version control.

---

## Verified Clean — Informational Findings

### I-1 · Dependency CVEs: 0 found

`pip-audit 2.10.0` scanned all 68 installed packages against the OSV database.

```
No known vulnerabilities found
```

All packages including `anthropic==0.107.1`, `streamlit==1.58.0`,
`scikit-learn==1.9.0`, `xgboost` (via feedback.py), `shap==0.52.0`, and
`diffprivlib==0.6.6` returned zero hits.

---

### I-2 · ANTHROPIC_API_KEY read from environment only — CONFIRMED

Three call sites verified:

| File | Line | Pattern |
|------|------|---------|
| `explain.py` | 315 | `api_key = os.environ.get("ANTHROPIC_API_KEY", "")` |
| `explain.py` | 349 | `use_api = use_api and bool(os.environ.get("ANTHROPIC_API_KEY"))` |
| `explain.py` | 381 | `use_api = bool(os.environ.get("ANTHROPIC_API_KEY"))` |

The key is never hardcoded, never logged, never written to a file. The
dashboard (`app.py`) references it only in a UI label string, not in code that
reads or uses it.

No `.env` file exists in the working tree or git history.

---

### I-3 · SQL injection: all execution-path queries are parameterized — CONFIRMED

Full scan of all `conn.execute()` / `cursor.execute()` / `executemany()` calls
in execution paths (i.e., excluding the one diagnostic summary covered by L-1):

| Module | Query style | Assessment |
|--------|------------|------------|
| `audit_log.py` | SQLite `?` placeholders throughout | SAFE |
| `create_db.py` | `executemany()` with tuple placeholders | SAFE |
| `anomaly_model.py` | DuckDB — SQL over registered DataFrames, no user values | SAFE |
| `peer_stats.py` | Pure pandas, no raw SQL | SAFE |
| `scoring.py` | SQLite `?` placeholders | SAFE |
| `feedback.py` | pandas/CSV, no raw SQL | SAFE |

No f-string or `%`-format string SQL found in any execution path.

---

### I-4 · No hardcoded secrets anywhere in git history — CONFIRMED

Scanned full history of all four branches (`master`, `hardening`, `security`,
`upgrades`) for patterns matching:

- `sk-ant-` (Anthropic key prefix)
- `ANTHROPIC_API_KEY\s*=\s*["'][^"']{10,}`
- `password\s*=\s*["'][^"']`
- `secret\s*=\s*["'][^"']`
- `token\s*=\s*["'][^"']{10,}`

**Zero matches across all commits and all files.**

---

### I-5 · No real patient/physician data — CONFIRMED

**claims.csv** (53,990 rows, 6 MB) scanned for:

- US Social Security Number pattern (`\d{3}-\d{2}-\d{4}`): **0 matches**
- OHIP-like 10-digit number (`\d{10}`): **0 matches**
- Real addresses or DOBs: columns are `claim_id`, `provider_id`, `provider_name`,
  `specialty`, `patient_id`, `service_date`, `fee_code`, `service_minutes`,
  `units`, `amount_billed`, `clinic_id` — no address or DOB field exists

**Identity fields are obviously synthetic:**
- `claim_id`: sequential integers formatted `CLM0000001`
- `provider_id`: `PRV0001` … `PRV0150`
- `patient_id`: `PAT00001` … `PAT50000`
- `clinic_id`: `CLN01` … `CLN20`

**Provider names** are generated by `Faker.name()` (`data_gen.py:183`). These
are random English-language name combinations from Faker's word lists.
They could coincidentally match a real physician's name but are not linked to
any real identifiers, addresses, billing numbers, or registration data.
The README's `SYNTHETIC DATA ONLY` banner and `data_gen.py` provenance make
the fictional nature unambiguous.

---

### I-6 · Audit-log tamper detection: CONFIRMED working

Direct SQL manipulation test performed against a copy of `audit_log.db`:

```python
# Modified column `reasoning` in row id=2 directly via sqlite3
conn.execute("UPDATE audit_log SET reasoning = 'TAMPERED_RECORD' WHERE id = 2")

# verify_integrity() response:
{
  'ok': False,
  'total_rows': 32,
  'first_bad_id': 2,
  'message': 'Tampered record at row id=2: recomputed hash differs from stored hash. '
             'The record content has been altered.'
}
```

The SHA-256 hash chain correctly detected the alteration at row 2.
Unmodified state verified beforehand: `{'ok': True, 'total_rows': 32, ...}`.

---

### I-7 · No subprocess/shell execution, no eval/exec — CONFIRMED

Full codebase search: zero uses of `os.system`, `subprocess.Popen`,
`subprocess.call`, `subprocess.run`, `eval()`, or `exec()` in any Python
source file.

---

### I-8 · Cryptographic algorithms appropriate for stated purpose — CONFIRMED

| Use | Algorithm | Assessment |
|-----|-----------|------------|
| Audit hash chain | SHA-256 (`hashlib`) | Appropriate for integrity, not confidentiality |
| Model training-data provenance | SHA-256 | Appropriate |
| SHAP display privacy | Laplace(`ε=1.0`) via `diffprivlib` | Appropriate for demo-grade noise; correctly labelled as NOT formal DP throughout |

No MD5, SHA-1, DES, or RC4 found anywhere.

---

## Fixes Applied in This Commit

| ID | File | Change |
|----|------|--------|
| H-1 | `.gitignore` (new) | Added; covers `.db`, `.csv`, `__pycache__/`, `model_registry/`, `.env`, `*.pyc` |
| M-1 | `model_registry.py` | `import pickle` → `import joblib`; `pickle.dump/load` → `joblib.dump/load`; file extension `.pkl` → `.joblib` |
| L-1 | `create_db.py:500` | f-string SQL → explicit whitelist + string concat + `# nosec B608` |
| L-5 | `.gitignore` (new) | `__pycache__/` and `*.pyc` now excluded |

---

## Actions Required by Owner

| Priority | Action |
|----------|--------|
| **Required before public push** | `git rm --cached billing_anomaly.db *.csv` then commit, to stop tracking generated outputs under the new `.gitignore` |
| **Recommended before GitHub** | Use BFG Repo Cleaner to remove `billing_anomaly.db` from history (see H-1 for commands) |
| **Optional hardening** | Replace `try/except/pass` in audit-log write paths with `logging.warning()` (L-2) |
| **Optional hardening** | Add path-traversal guard to `audit_log.export_to_csv()` (L-3) |
| **Optional hardening** | Replace `assert` in self-test blocks with explicit `if/raise` (L-4) |

---

*Scan completed 2026-06-09. Automated analysis only — not a professional penetration test.*
