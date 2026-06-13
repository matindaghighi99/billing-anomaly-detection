# Secrets & API-Key Hardening Report

**Date:** 2026-06-09
**Branch:** `hardening`
**Scope:** Full git history scan + current code audit + prevention setup.

---

## 1. Git History Scan — CLEAR

**Tool:** `git log --all -p -S "sk-ant-api"` (pickaxe) + regex grep over full diff output.

**Patterns searched:**
- `sk-ant-api` — Anthropic key prefix
- `ANTHROPIC_API_KEY\s*=\s*["'][^"']{5,}` — inline assignment with value
- `api_key`, `secret`, `token`, `password` — broad keyword sweep

**Result: No real secrets found in any commit.**

All matches were either:
- References to the env var *name* (`ANTHROPIC_API_KEY`) without a value, or
- The `# Set ANTHROPIC_API_KEY=sk-ant-...` placeholder in README (no real key), or
- Demo-credential strings in `auth_mock.py` (intentional, documented as mock-only).

The `.env` file was **never committed** — confirmed by
`git log --all --diff-filter=A -- ".env"` returning no output.

**Action required:** None. No rotation needed.

---

## 2. Rotation Guidance (for future reference)

> **If a real `sk-ant-` key ever appears in history, treat it as CRITICAL.**
>
> Deleting the file or even rewriting history with `git filter-repo` is **not
> sufficient** — anyone who cloned or forked the repo before the rewrite already
> has the key in their local `.git/objects`. The only safe remediation is:
>
> 1. **Rotate immediately** in the [Anthropic Console → API Keys](https://console.anthropic.com/settings/keys).
>    Rotation invalidates the leaked key server-side regardless of who holds it.
> 2. Rewrite history with `git filter-repo --replace-text` to scrub the value
>    from all objects, then force-push and ask GitHub to invalidate the old pack.
> 3. Audit spend logs for the period the key was exposed.
>
> *Deletion alone is insufficient once a secret is in history.*

---

## 3. Current Code — API Key Read from Environment Only ✓

All accesses confirmed environment-only, never hardcoded:

| File | Line | Pattern |
|------|------|---------|
| `app.py` | 10–11 | `load_dotenv()` then `os.environ.get("ANTHROPIC_API_KEY")` |
| `explain.py` | 315 | `api_key = os.environ.get("ANTHROPIC_API_KEY", "")` |
| `explain.py` | 349 | `use_api = use_api and bool(os.environ.get("ANTHROPIC_API_KEY"))` |
| `explain.py` | 381 | `use_api = bool(os.environ.get("ANTHROPIC_API_KEY"))` |

`load_dotenv()` in `app.py` loads `.env` at startup; `.env` is gitignored.
No hardcoded key string exists anywhere in the codebase.

---

## 4. `.gitignore` — Already Correct ✓ / `.env.example` — Created

`.gitignore` already contained:
```
# Environment — NEVER commit API keys
.env
.env.*
*.env
```

**Added:** `.env.example` — committed template with variable name and no value:
```
ANTHROPIC_API_KEY=
```

Developers copy this to `.env` and fill in their own key. `.env` stays local.

---

## 5. Pre-Commit Hook — Installed

**Files created:**

- `.pre-commit-config.yaml` — runs `detect-secrets` + standard safety hooks on
  every `git commit`
- `.secrets.baseline` — baseline of known false-positives (the three demo
  credential strings in `auth_mock.py`, annotated with `# pragma: allowlist secret`)

**Hooks configured:**

| Hook | Purpose |
|------|---------|
| `detect-secrets` (v1.5.0) | Blocks commits containing API keys, tokens, high-entropy strings |
| `detect-private-key` | Blocks PEM private keys |
| `check-added-large-files` (500 KB limit) | Prevents accidental binary/data commits |
| `check-merge-conflict` | Catches unresolved conflict markers |

**To activate after cloning:**
```bash
pip install pre-commit detect-secrets
pre-commit install
```

> If `pre-commit install` fails with *"Cowardly refusing … core.hooksPath"*,
> your global git config has `core.hooksPath` set. Fix it with:
> ```bash
> git config --global --unset-all core.hooksPath
> pre-commit install
> ```

The `auth_mock.py` demo credentials are marked `# pragma: allowlist secret` and
excluded from the baseline — the hook will not block them on future commits.

---

## 6. LLM Call Hygiene — `explain.py` ✓

**What is sent to the API (`_call_anthropic`, lines 312–341):**

- The provider's `template_text` — a multi-line string built entirely from
  **synthetic CSV outputs** (provider_id, specialty, risk score, billing stats).
- No real patient names, DOB, SSN, claim IDs, or any PHI.
- The prompt instructs Claude to rewrite it as two prose paragraphs.

**Error handling:**
```python
except Exception:
    return template_text   # always falls back to template on any failure
```
Any network error, rate-limit, or API error silently falls back — the dashboard
never crashes and always shows at least the template explanation.

**Key-absent guard:**
```python
api_key = os.environ.get("ANTHROPIC_API_KEY", "")
if not api_key:
    return template_text
```
The API is never called when the key is absent.

**Minor finding — no timeout on API call:**
The `client.messages.create()` call has no explicit `timeout` parameter. If the
Anthropic API hangs, the Streamlit spinner will block indefinitely. This is a
UX concern, not a security issue. Recommended fix:
```python
client = anthropic.Anthropic(api_key=api_key, timeout=30.0)
```

---

## 7. Manual Checklist (Owner Actions)

The following items require your action in the Anthropic Console — they cannot
be automated from this repo.

- [ ] **Verify the API key is not leaked** — the history scan found nothing,
      but confirm by checking [Console → API Keys](https://console.anthropic.com/settings/keys)
      for any unexpected recent usage.

- [ ] **Set a spend limit** — in [Console → Billing → Limits](https://console.anthropic.com/settings/limits),
      set a monthly spend cap appropriate for demo usage (e.g. $5–10/month).
      This bounds the blast radius if the key is ever compromised.

- [ ] **Run `pre-commit install`** after cloning on each machine where you develop:
      ```bash
      git config --global --unset-all core.hooksPath   # if needed
      pre-commit install
      ```

- [ ] **Rotate the key periodically** — even if not leaked, rotating API keys
      every 90 days is good hygiene. Old keys can be revoked in the Console
      without downtime if you update `.env` first.

- [ ] **(Optional) Add a timeout to `_call_anthropic`** — change line 320 in
      `explain.py` to:
      ```python
      client = anthropic.Anthropic(api_key=api_key, timeout=30.0)
      ```

---

## Summary

| Item | Status |
|------|--------|
| Real key in git history | **CLEAR** — none found |
| `.env` ever committed | **CLEAR** — never staged |
| Key hardcoded in source | **CLEAR** — env-only reads |
| `.gitignore` covers `.env` | ✓ Already present |
| `.env.example` template | ✓ Created and committed |
| `detect-secrets` baseline | ✓ 0 unaudited findings |
| `.pre-commit-config.yaml` | ✓ Created |
| Pre-commit hook installed | ⚠ Requires `pre-commit install` (see above) |
| LLM call sends only synthetic data | ✓ Confirmed |
| LLM call falls back on error | ✓ Confirmed |
| API call timeout | ⚠ Not set (UX risk, not security) |

*No CRITICAL findings. No key rotation required based on history scan.*
