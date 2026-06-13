# Production Readiness & Control Profile

This document maps the Billing Anomaly Audit application to the controls a
government deployment (e.g. an Ontario Ministry of Health hosting environment)
typically requires, and states precisely **what the application provides**
versus **what the hosting organisation provides**. It is intended for the
ministry's infrastructure, security, and privacy teams during a pilot intake.

> **Status:** the application runs today as a synthetic-data demonstration.
> The production posture below is reachable by **configuration** (environment
> variables) plus the hosting organisation's standard platform services — not
> by code changes. Two items require validation passes and are called out as
> such: the PostgreSQL adapter (one integration test against the target
> instance) and detection accuracy (validation against real adjudicated
> outcomes — see `ops/validation.py`).

---

## 1. Demo vs. production — the configuration switch

Everything security-critical is environment-driven. `common/config.py`
enforces these in `APP_ENV=production`: the app **refuses to start** if a
security setting is missing or unsafe (`config.enforce()`), so a misconfigured
deployment never silently serves.

| Concern | Demo default | Production setting |
|---|---|---|
| Environment | `APP_ENV=demo` | `APP_ENV=production` (activates the fail-fast gate) |
| Identity | `AUTH_PROVIDER=mock` (password + TOTP) | `AUTH_PROVIDER=sso` (federate to ministry IdP) |
| Session signing | ephemeral key | `SESSION_SECRET` (≥32 random chars, from vault) |
| Datastore | SQLite files | `DATABASE_URL=postgresql://…` (managed instance) |
| Artefact storage | `./data`, `./reports` | `PIPELINE_DATA_DIR`, `REPORTS_DIR`, `DATA_DIR` on a mounted volume |
| Demo credentials | shown on login | `HIDE_DEMO_CREDS=1` |
| Logging | text/JSON to stdout | `LOG_FORMAT` JSON to stdout → SIEM drain |

---

## 2. Identity & access (SSO/AD)

**Application provides:**
- A provider-agnostic SSO layer (`auth/sso.py`) that derives the authenticated
  identity from EITHER (a) trusted reverse-proxy headers (oauth2-proxy, Azure
  App Service Easy Auth, an API gateway) or (b) a signed JWT in a request
  header (HS256 built in; RS256/JWKS via PyJWT).
- IdP **group → role** mapping (`SSO_GROUP_ROLE_MAP`) onto the app roles
  `auditor` / `supervisor` / `admin`, with highest-privilege-wins resolution
  and deny-by-default for unmapped users.
- Role-based access enforced server-side on every privileged action
  (`require_permission()` in `auth/auth_mock.py`) — not just UI hiding.
- Anti-spoofing guard for header-trust mode (`SSO_PROXY_SHARED_SECRET`).

**Hosting organisation provides:**
- The IdP itself (Entra ID / Azure AD or provincial gateway), MFA enforcement,
  password policy, lifecycle, and the authenticating reverse proxy in front of
  the app. The app must be unreachable except through that proxy.

**Configure:** `AUTH_PROVIDER=sso`, `SSO_USER_HEADER`, `SSO_GROUPS_HEADER`,
`SSO_GROUP_ROLE_MAP`, and (if used) the `SSO_JWT_*` settings. See `auth/sso.py`
for the full list.

---

## 3. Datastore (enterprise database)

**Application provides:**
- A storage seam (`common/db.py`) selected by `DATABASE_URL`: SQLite for the
  demo, PostgreSQL (psycopg v3) for production. The audit trail, case store,
  and clinical-review store all obtain connections here.
- The tamper-evident audit chain's exclusive-append lock maps correctly to each
  backend (`BEGIN IMMEDIATE` on SQLite, `LOCK TABLE … EXCLUSIVE` on PostgreSQL).

**Hosting organisation provides:**
- The managed PostgreSQL instance (HA, backups, encryption at rest, network
  isolation, DR), and the connection string injected from a secrets vault.

**Validation pending:** the PostgreSQL adapter is structurally complete and the
SQLite path is covered by the test suite; the PostgreSQL path needs **one
integration pass against the target instance** (no Postgres server is available
in CI).

---

## 4. Audit-grade logging at scale

**Application provides — two complementary streams:**
1. **Tamper-evident domain trail** (`audit/audit_log.py`): append-only,
   SHA-256 hash-chained record of every system/user event, with
   `verify_integrity()` that pinpoints the first altered/deleted row. No UPDATE
   or DELETE code paths exist.
2. **Operational/security event stream** (`ops/observability.py`): structured
   single-line JSON to stdout with a per-session correlation id and the
   authenticated actor on every privileged action (`log_action()` is called
   from export, disposition, stage-change, and integrity handlers). 12-factor
   stdout output is forwarded by the platform to the SIEM.

**Hosting organisation provides:**
- The SIEM/log drain (Splunk / Microsoft Sentinel / ELK), log retention meeting
  records-retention policy, and WORM/immutable storage for the audit stream.

**Configure:** `LOG_LEVEL`, JSON logging is the default formatter.

---

## 5. Hardened host

**Application provides:**
- A container image (`Dockerfile`) that runs as a **non-root** user, pins
  dependencies (`requirements.txt`), exposes a health endpoint
  (`/_stcore/health`), and reads **all** secrets from the environment (no
  secrets in the image or repo).
- A fail-fast production configuration gate (`config.enforce()`).

**Hosting organisation provides:**
- Deployment into the approved landing zone meeting the control profile:
  Canadian data residency, network isolation (private ingress only, via the
  proxy), TLS termination + WAF, vulnerability scanning and patching, a secrets
  vault (Key Vault), and platform monitoring/alerting.

**Recommended additions during pilot hardening (not yet in repo):**
- A CI security stage (`pip-audit`, `bandit`, image scan).
- Pinned, hash-locked dependencies.

---

## 6. Privacy & data

- **No real PHI is used today** — all providers, patients, and claims are
  synthetic and labelled as such throughout the UI.
- Recovery figures are stamped **INDICATIVE** until the authoritative Schedule
  of Benefits is loaded and `RECOVERY_VALIDATED` is set (`audit/fee_schedule.py`).
- Detection accuracy is **NOT validated** against real outcomes; it is measured
  on synthetic data. `ops/validation.py` flips to a validated basis only when
  real adjudicated outcomes are supplied (`VALIDATION_OUTCOMES_CSV`).

**Hosting organisation provides:** the Privacy Impact Assessment (PIA), Threat
& Risk Assessment (TRA), and data-sharing/authority approvals required before
real claims data is processed.

---

## 7. Control checklist (summary)

| Control | Provided by app | Provided by ministry | Status |
|---|---|---|---|
| SSO / MFA / directory | role mapping + enforcement | IdP + MFA + proxy | config |
| RBAC, server-side | ✅ `require_permission` | — | done |
| Enterprise DB | adapter + seam | managed Postgres | integration pass |
| Tamper-evident audit | ✅ hash chain | WORM retention | done |
| SIEM logging | ✅ structured JSON + actor | SIEM/drain | config |
| Secrets management | env-only, fail-fast gate | vault | config |
| Data residency / network | container | landing zone | ministry |
| Vulnerability scanning | (CI stage to add) | platform scanning | partial |
| Accuracy validation | framework ready | real outcomes data | pending data |
| PIA / TRA / authority | limitations surfaced in-app | assessments | ministry |

The honest one-line summary for a sponsor: **the codebase is configured for a
pilot and makes its own limits explicit; the remaining work is the ministry's
environment integration plus a real-data validation pass — not a rewrite.**
