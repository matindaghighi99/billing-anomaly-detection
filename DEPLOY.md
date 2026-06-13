# Deployment guide

The dashboard is a Streamlit app (`app.py`). This guide covers a containerised
deployment and Streamlit Community Cloud, plus the security configuration you
must set for anything beyond a local demo.

> **Before exposing this anywhere:** the bundled authentication is a hardened
> *mock* (PBKDF2-hashed passwords, constant-time compare, login lockout) but it
> is still session-dict RBAC, not a real identity provider. For a production
> deployment with real data, put it behind your IdP (SSO/OAuth/SAML) and follow
> the checklist in `MOH_ALIGNMENT.md` §7. At minimum, set `HIDE_DEMO_CREDS=1`
> and replace the demo users via `BAAD_USERS_JSON` (below).

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `DATASET` | `large` (expanded MOH set) or `demo` (original 6-specialty set) | `large` in app/Docker |
| `SESSION_SECRET` | HMAC key for signing session tokens. **Set this in production** (a strong random string) so sessions survive restarts and cannot be forged. | ephemeral per-process key |
| `MFA_ENABLED` | Enforce the TOTP second factor at login | `1` (on) |
| `SESSION_TTL_SECONDS` | Absolute session lifetime before re-login | `28800` (8h) |
| `HIDE_DEMO_CREDS` | Hide the on-screen demo credentials + live MFA codes | unset (shown) |
| `BAAD_USERS_JSON` | Override the user store (JSON, salted PBKDF2 hashes + TOTP secrets) | unset (demo users) |
| `BAAD_MAX_LOGIN_FAILS` | Failed logins before lockout | `5` |
| `BAAD_LOCKOUT_SECONDS` | Lockout duration after too many fails | `60` |
| `ANTHROPIC_API_KEY` | Enables AI-enriched explanations (optional) | unset (templates) |
| `FEE_SCHEDULE_CSV` | Path to the fee schedule (fee_code,description,amount,tier,minutes) | `fee_schedule.csv` (demo subset) |
| `FEE_SCHEDULE_META` | Provenance sidecar (source/version/effective_date/authoritative) | `fee_schedule_meta.json` |
| `RECOVERY_VALIDATED` | Recovery validated against adjudicated outcomes | unset (off) |

### Fee schedule & recovery defensibility

Recovery figures are derived from a fee schedule. The bundled
`fee_schedule.csv` is a **representative DEMO subset**, not the authoritative
Ontario Schedule of Benefits (Regulation 552), so every figure in the casebook,
the recovery CSV, and the dashboard is stamped **INDICATIVE — not for a GM's
Opinion**. To make figures defensible:

1. Replace `fee_schedule.csv` with a Schedule of Benefits export (same columns).
2. Edit `fee_schedule_meta.json`: `{"authoritative": true, "version": "...",
   "effective_date": "YYYY-MM-DD", "source": "Schedule of Benefits ..."}`.
3. Validate recovery against adjudicated outcomes, then set `RECOVERY_VALIDATED=1`.

Only when the schedule is **authoritative AND** `RECOVERY_VALIDATED=1` do the
figures switch to **DEFENSIBLE**. This is enforced in code (`fee_schedule.py`),
not just documented.

### Authentication

Login is **password (PBKDF2-hashed) + TOTP MFA**, and the session is an
**HMAC server-signed token** whose role is verified on every request — editing
client-side state cannot escalate privileges. Set a strong `SESSION_SECRET` and
keep `MFA_ENABLED=1` in production.

Generate a real user record (no plaintext stored; includes a fresh TOTP secret):

```bash
python -c "import auth_mock; print(auth_mock.make_user_record('S0me-Strong-Pass','supervisor','Jane Q. Auditor'))"
# → {"salt":"...", "hash":"...", "totp_secret":"...", "role":"supervisor", "display":"Jane Q. Auditor"}
```

Enrol the `totp_secret` in an authenticator app (Google Authenticator, Authy, …):

```bash
python -c "import auth_mock; print(auth_mock.provisioning_uri('jane','<totp_secret>'))"
# → otpauth://totp/... (paste into the app, or render as a QR code)
```

Then set, e.g.:

```bash
export SESSION_SECRET="$(python -c 'import secrets;print(secrets.token_hex(32))')"
export BAAD_USERS_JSON='{"jane": {"salt":"...","hash":"...","totp_secret":"...","role":"supervisor","display":"Jane Q. Auditor"}}'
export HIDE_DEMO_CREDS=1
```

> The bundled demo accounts (`auditor1` / `supervisor1` / `admin1`) show their
> live MFA code on the login screen so the demo is usable without enrolling a
> device. This only happens when `HIDE_DEMO_CREDS` is unset — never in production.

## Deploy to Render (configured — recommended)

This repo ships a Render Blueprint (`render.yaml`) that builds the Dockerfile and
serves the app over HTTPS. No credentials live in the repo.

One-time setup (≈3 minutes):
1. Push the branch (done) and sign in at https://render.com (GitHub login).
2. **New → Blueprint** → select this repository. Render reads `render.yaml`,
   creates the `billing-anomaly-audit` web service, and starts the first build
   (it runs the full pipeline at build, ~3–5 min the first time).
3. When prompted for the `sync:false` env vars, set:
   - `BAAD_USERS_JSON` — your real users (generate records with the
     `make_user_record()` helper shown above). Optional for a demo; leave blank
     to use the bundled demo accounts (already hashed; the on-screen hint is
     hidden because `HIDE_DEMO_CREDS=1`).
   - `ANTHROPIC_API_KEY` — optional, enables AI-enriched explanations.
4. Render gives you `https://billing-anomaly-audit.onrender.com`. Every push to
   the configured branch auto-redeploys.

The free plan spins down when idle (first request after idle is slow); switch
`plan: free` → `starter` in `render.yaml` for an always-on instance.

## Option A — Docker (any host)

The image regenerates the dataset and runs the full pipeline at build time, so
it ships ready to serve. It runs as a non-root user with a health check.

```bash
docker build -t billing-audit .
docker run -p 8501:8501 \
  -e HIDE_DEMO_CREDS=1 \
  -e BAAD_USERS_JSON="$BAAD_USERS_JSON" \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  billing-audit
```

Open http://localhost:8501. Put a TLS-terminating reverse proxy (nginx/Caddy)
or your platform's HTTPS in front of it before exposing it. This image runs on
any container host — Fly.io, Render, Azure Container Apps, AWS App Runner, GCP
Cloud Run, or a plain VM.

## Option B — Streamlit Community Cloud

1. Connect the GitHub repo at https://share.streamlit.io and select `app.py`.
2. Add `ANTHROPIC_API_KEY` and `HIDE_DEMO_CREDS` under **Secrets**.
3. **Data:** `claims_large.csv` is gitignored, so the per-physician *Monthly
   Volume* chart and SHAP attribution need the pipeline to run. The committed
   `*_large` aggregates make the Worklist/Analytics/OHIP tabs work out of the
   box; for full fidelity add a startup step or commit the generated data.
4. Keep the app **private** (this platform is best for an internal demo).

## Reproduce the data locally

```bash
DATASET=large python run_pipeline.py   # data + detection pipeline
python fraud_evidence.py               # revenue-inflation evidence
python moh_audit.py                    # OHIP casebook + recovery summary
streamlit run app.py
```

## Production checklist (real MOH data)

Ontario data residency · PHIPA review · IdP SSO/MFA replacing the mock auth ·
secrets in a managed vault · audit log to managed storage · authoritative
Schedule of Benefits ingestion. See `MOH_ALIGNMENT.md` §7.
