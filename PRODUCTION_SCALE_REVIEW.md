# Production-Scale Readiness Review

**Project:** Physician Billing Anomaly Detection
**Date:** 2026-06-23
**Scope:** Architecture, persistence, concurrency, security, and ML serving concerns for running this system on real, production-scale data. Synthetic-data quality is explicitly out of scope per request.

---

## Summary

The codebase is well-engineered for what it is: a single-machine batch pipeline feeding a single-process Streamlit dashboard for a small audit team, backed by flat CSV files. It is internally consistent, security-aware in its comments, and already stress-tested to ~1M claims at the *pipeline* level.

The concerns below are not bugs — they are architectural boundaries that will break when this moves from "demo for a small team" to "production service over real claims data and many concurrent users." They cluster into four areas: **flat-file storage, single-process serving, mock authentication, and batch-only ML.** Roughly in priority order:

---

## High priority — will break or expose data in production

### 1. Flat CSV files are the system of record
Every layer reads the full CSV into pandas, recomputes, and overwrites the whole file (`pd.read_csv(...) → ... → df.to_csv(...)`). The dashboard reads `risk_scores.csv`, `rules_flags.csv`, etc. directly. There is a `billing_anomaly.db` (SQLite, ~10 MB) but **the dashboard never reads it** — it reads CSVs.

Why it breaks at scale:
- No concurrency safety. A pipeline run overwriting `risk_scores.csv` while the dashboard reads it (or a second pipeline run) can serve or write a torn file. No transactions, no atomic swap, no locking.
- No incremental updates. Every run rewrites everything; cost grows with total data, not new data.
- `dispositions.csv` (the human-label training data for the feedback model) is **appended to by every auditor action** from the dashboard with no locking. Concurrent confirms/clears can interleave and corrupt the file that trains the model.

Fix direction: move the system of record to a real database (Postgres), write scores/flags/dispositions through transactional inserts, and have the dashboard query the DB rather than CSVs. Treat CSVs as export artifacts only.

### 2. Authentication is a documented mock
`auth_mock.py` states this plainly: hardcoded credentials, plaintext password comparison, no MFA, no lockout/rate-limiting, sessions are server-side dicts. Permission checks (`require_permission`) are UI-level gates — anyone who can reach the Streamlit server is served the app; security currently depends entirely on the network perimeter.

This is fine for a demo but is a hard blocker before any real PHI. The module already lists the production requirements (SSO/OAuth or SAML, MFA, bcrypt/argon2, signed session tokens, idle timeout, auth events in the audit trail). Those need to be actually implemented, ideally by putting the app behind an identity-aware proxy rather than building auth into Streamlit.

### 3. PHI leaves the trust boundary via the Anthropic API
`explain.py::_call_anthropic` sends provider name, specialty, and structured findings to the Anthropic API to enrich explanations. On synthetic data this is harmless; on real data this is PHI crossing an external boundary and requires a BAA, de-identification, and an explicit opt-in/config flag. The call also has **no timeout, retry, or backoff** — a slow API response blocks the Streamlit request thread.

---

## Medium priority — won't scale or will degrade under load

### 4. Streamlit is single-process and in-memory
The whole dashboard runs in one Python process, with each CSV loaded fully into a shared `@st.cache_data` DataFrame. This does not scale horizontally, has no real multi-tenant isolation, and holds all data in memory. Adequate for a "small audit team"; it will not support org-wide concurrent use. For production, plan for a stateless app tier querying the DB, behind a load balancer, with the heavy data kept in the database rather than in process memory.

### 5. Audit-log SQLite concurrency
`audit_log.py` is well-designed for integrity (hash chain, `BEGIN IMMEDIATE` to prevent chain forks, INSERT-only). But:
- No `PRAGMA busy_timeout` and no WAL mode on `audit_log.db`. Under concurrent writers (multiple auditors acting at once) SQLite raises `database is locked`; the dashboard catches it generically and shows "Error," silently dropping the audit event.
- `BEGIN IMMEDIATE` serializes *all* writes globally — a throughput ceiling.
- A new connection is opened per event.
- Uses deprecated `datetime.utcnow()`.

For production, move the audit trail into the same Postgres instance (append-only table, keep the hash chain), or at minimum enable WAL + a busy timeout. SQLite is not the right backend for concurrent multi-user writes.

### 6. ML models are retrained from scratch every run, with no serving artifact
`anomaly_model.py` fits IsolationForest + LOF + OC-SVM on every pipeline run; no model is persisted and loaded by the dashboard. `model_registry.py` is only touched to record a version string in `scoring.py`. Consequences: no reproducible served model, retraining cost on every run, and LOF/OC-SVM scale poorly (roughly quadratic) as the *provider* population grows — note the stress test scaled *claims*, but model cost is driven by the number of scored entities. For production: persist fitted models as versioned artifacts, load them for scoring, and separate (scheduled) training from serving.

### 7. Batch-only — no ingestion or real-time path
Scoring only happens when someone manually runs `run_pipeline.py`. There is no scheduler, ingestion service, or scoring API, so the worklist is stale between manual runs. Production needs a scheduled/triggered pipeline (e.g. nightly) and a defined data-ingestion path for new claims.

---

## Lower priority — operational hardening

### 8. Hardcoded relative paths / no environment config
All data locations are relative filename constants, so the app must run from the project directory. There's no env-driven config for data location or DB connection. Deploying to a server with separate storage requires code changes. Introduce a config layer (env vars / settings module).

### 9. Manual cache invalidation
`st.cache_data` is only cleared by the "Clear Cache & Reload" button or after a dashboard action. If the pipeline regenerates CSVs out-of-band, the dashboard shows stale data until a manual clear. With a DB backend and short TTL caching this largely goes away.

### 10. Secrets handling
Good hygiene is present (`.env` gitignored, `detect-secrets` baseline, `.env.example`). For production, load `ANTHROPIC_API_KEY` and any DB credentials from a managed secret store rather than a process-level `.env`.

---

## What's already solid

- Pipeline correctness is stress-tested to ~1M claims (`STRESS_REPORT.md`); several pathological-shape bugs already found and fixed.
- The two-stage `--fast` funnel is a sensible cost optimization and correctly shares scoring weights to avoid candidate drift.
- Audit-trail design (hash chain, append-only, integrity verification) is genuinely good — it just needs a concurrent-safe backend.
- The team clearly understands the gap: `auth_mock.py` and the README both flag the demo-vs-production boundary explicitly.

---

## Suggested sequencing toward production

1. Replace CSV system-of-record with Postgres (scores, flags, dispositions, audit log); dashboard queries the DB.
2. Put real auth in front (identity-aware proxy / SSO + MFA); wire auth events into the audit trail.
3. Gate the Anthropic enrichment behind a config flag with de-identification + BAA; add timeout/retry.
4. Split training from serving: persist versioned models, score from artifacts, schedule retraining.
5. Add a scheduled ingestion + scoring pipeline; remove manual-run dependence.
6. Externalize config, move secrets to a managed store, and make the app tier stateless/horizontally scalable.
