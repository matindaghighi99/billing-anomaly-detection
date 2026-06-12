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
| `HIDE_DEMO_CREDS` | Hide the on-screen demo-credential hint | unset (shown) |
| `BAAD_USERS_JSON` | Override the user store (JSON, salted PBKDF2 hashes) | unset (demo users) |
| `BAAD_MAX_LOGIN_FAILS` | Failed logins before lockout | `5` |
| `BAAD_LOCKOUT_SECONDS` | Lockout duration after too many fails | `60` |
| `ANTHROPIC_API_KEY` | Enables AI-enriched explanations (optional) | unset (templates) |

Generate a real user record (no plaintext stored):

```bash
python -c "import auth_mock; print(auth_mock.make_user_record('S0me-Strong-Pass','supervisor','Jane Q. Auditor'))"
# → {"salt": "...", "hash": "...", "role": "supervisor", "display": "Jane Q. Auditor"}
```

Then set, e.g.:

```bash
export BAAD_USERS_JSON='{"jane": {"salt":"...","hash":"...","role":"supervisor","display":"Jane Q. Auditor"}}'
export HIDE_DEMO_CREDS=1
```

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
