# Production Readiness Checklist

Tracks what stands between this project and a real, PHI-bearing production
deployment. **Current status: DEMO — not production-ready.** The system runs on
synthetic data with built-in demo credentials and is explicitly a
decision-support tool for human auditors (no automated decisions).

This checklist complements `SECURITY_REPORT.md` (point-in-time findings). It is
the living tracker of remaining work.

## Legend

- **Status:** `[x]` done · `[~]` partial · `[ ]` not started
- **Owner:**
  - **ENG** — codeable now without external decisions (Claude/engineering can do)
  - **ENG+YOU** — Claude builds the integration; you choose the provider / supply credentials
  - **YOU** — business / org decision, data, or infrastructure ownership
  - **3P** — third party (compliance, legal, independent security assessment)

## Machine-checkable gate

A subset of these items is enforced automatically. `config.py` runs a
**production preflight**: with `APP_ENV=production` the app (and the
`python config.py` CLI, exit≠0) refuses to start while insecure defaults remain
(demo credentials, default password salt, missing `MODEL_REGISTRY_HMAC_KEY`).
In demo/dev it only logs a warning so the synthetic demo still runs.

---

## 1. Application security — mostly shipped

- [x] Constant-time, hashed credential comparison; no plaintext storage — **ENG** (`auth_mock.py`)
- [x] Failed-login lockout + idle session timeout — **ENG** (`auth_mock.py`)
- [x] Audit-trail user bound to authenticated session (no impersonation) — **ENG** (`app.py`)
- [x] Stored-XSS escaping for all data rendered via `unsafe_allow_html` — **ENG** (`app.py`)
- [x] Model-artifact integrity check before `joblib.load` — **ENG** (`model_registry.py`)
- [x] CSV/formula-injection neutralisation on audit export — **ENG** (`audit_log.py`)
- [x] Non-reversible privacy noise for SHAP display values — **ENG** (`explain.py`)
- [x] Generic UI errors; details logged server-side — **ENG** (`app.py`)
- [x] Boot-time guard against insecure demo defaults — **ENG** (`config.py`)
- [ ] Security headers (CSP, HSTS, X-Frame-Options) at the proxy/edge — **ENG**
- [ ] Input size/rate limits on expensive endpoints (regen, export) — **ENG**

## 2. Authentication & Authorization — BLOCKER

- [ ] Replace mock auth with a real IdP (OAuth2/OIDC or SAML) — **ENG+YOU** (you pick Okta/Azure AD/Auth0/…)
- [ ] Enforce MFA for all users — **ENG+YOU**
- [ ] Server-signed / encrypted session tokens (not client-influenced state) — **ENG+YOU**
      *(closes the known `test_auth_bypass` B-1 session-state escalation, which is inherent to the current model)*
- [ ] Real RBAC model beyond the three demo roles; least privilege review — **YOU** (role design) + **ENG** (impl)
- [ ] Centralised, distributed lockout/rate-limit (current lockout is in-process only) — **ENG**
- [ ] Auth events (login/logout/failure/lockout) written to the audit trail — **ENG**

## 3. Data protection, privacy & compliance — BLOCKER

- [ ] HIPAA gap assessment & sign-off; sign BAAs with all processors — **3P / YOU**
- [ ] Encryption at rest (DB + artifacts) and in transit (TLS everywhere) — **ENG+YOU**
- [ ] PHI handling: minimisation, de-identification where possible, access logging — **ENG+YOU**
- [ ] Formal differential-privacy budget if DP is claimed (current noise is demo-grade, **not** formal DP) — **YOU** (decision) + **ENG** (impl)
- [ ] Data retention & deletion policy (claims, audit log, model artifacts) — **YOU** + **ENG**
- [ ] Secrets in a managed store (Vault/Cloud Secret Manager); none in env files or source — **ENG+YOU**

## 4. Data & repository hygiene

- [x] Stop tracking generated/PHI-shaped data artifacts and bytecode — **ENG** (`.gitignore` + untracked)
- [ ] **Purge git history** of previously-committed data blobs before any real data (`git filter-repo`) — **ENG (with your go-ahead — rewrites hashes)**
- [ ] Confirm `.env`/secrets never enter history; rotate any exposed keys — **ENG+YOU**

## 5. Infrastructure & deployment

- [ ] Move off SQLite + local CSVs to a concurrent datastore (e.g. Postgres) with migrations — **ENG** (impl) + **YOU** (infra)
- [ ] Containerisation (Dockerfile) + IaC (Terraform) + deploy manifests — **ENG** (authoring) + **YOU** (cloud account/approval)
- [ ] TLS termination, WAF/edge protection, network isolation — **ENG+YOU**
- [ ] Backups + tested restore for DB and audit log — **YOU** + **ENG**
- [ ] Horizontal-scaling / load review for multi-user usage — **ENG+YOU**

## 6. Observability & operations

- [ ] Structured application logging shipped to a log platform — **ENG**
- [ ] Metrics + health/readiness probes — **ENG**
- [ ] Alerting on errors, auth anomalies, and audit-integrity failures — **ENG** (impl) + **YOU** (on-call/routing)
- [ ] Runbook / incident-response procedures — **YOU** + **ENG**

## 7. ML model governance

- [x] Versioned model registry + model cards + integrity tags — **ENG** (`model_registry.py`)
- [ ] Validate models on **real labeled data** (current training is synthetic, tiny seed) — **YOU** (data) + **ENG** (harness)
- [ ] Drift monitoring + scheduled retraining/governance process — **ENG** (impl) + **YOU** (policy)
- [ ] Fairness re-evaluation on real data (current audit is synthetic-only) — **ENG** (impl) + **YOU/3P** (review)
- [ ] Set `MODEL_REGISTRY_HMAC_KEY` (secret) and lock down write access to the model store — **ENG+YOU**

## 8. CI/CD & quality

- [x] CI: tests on py3.11/3.12 + full-pipeline integration — **ENG** (`.github/workflows/ci.yml`)
- [x] Security scanning in CI: bandit, detect-secrets, pip-audit — **ENG**
- [ ] Make pip-audit blocking once a triage/exception process exists — **ENG+YOU**
- [ ] Coverage reporting + threshold gate — **ENG**
- [ ] Required status checks + branch protection on the default branch — **YOU** (repo admin)

## 9. Independent verification — BLOCKER for launch

- [ ] Independent security assessment / penetration test (not the authors) — **3P**
- [ ] Compliance audit for the target jurisdiction(s) — **3P / YOU**
- [ ] Sign-off from data/clinical governance stakeholders — **YOU**

---

## Suggested next steps (no external dependency)

These can proceed immediately, each as its own PR:

1. Security headers + edge rate limiting (§1).
2. Postgres migration scaffold with Alembic migrations (§5).
3. Dockerfile + Terraform skeleton (§5).
4. Structured logging + health/metrics endpoints (§6).
5. Real-data model-validation harness (runs once you provide labeled data) (§7).
6. Git history purge — **only with your explicit go-ahead** (§4).
