# Role-Access Gating Audit Report — Billing Anomaly Demo Dashboard

**Date:** 2026-06-09  
**Branch:** `hardening`  
**Scope:** Role-based access control coherence in `auth_mock.py` + `app.py`.  
**What was tested:** UI-layer gates, function-level gates, session-state bypass
attempts, URL-parameter injection simulation, logout completeness, role bleed
between sessions.  
**Test suite:** `tests/test_auth_bypass.py` — 30 tests, **30 passed**.

---

> **FRAMING NOTE**
>
> The authentication here is a **mock for demo UX, not real security**.
> `auth_mock.py` uses hardcoded plaintext credentials and Streamlit server-side
> session dicts. All findings are assessed in that context: the question is
> whether the mock gating is *coherent and internally consistent*, not whether
> it is suitable for production.

---

## Pre-Audit State

`auth_mock.py` **did not exist** before this audit. `app.py` had **zero role
logic**: no login screen, no role variable, no permission checks anywhere. The
only identity concept was a free-text "Your ID" field in the sidebar, which
accepted any string and never validated it.

This audit both created the role-gating system and tested it.

---

## Role Matrix Implemented

| Permission | `auditor` | `supervisor` | `admin` |
|-----------|:---------:|:------------:|:-------:|
| `view_worklist` | ✓ | ✓ | ✓ |
| `view_analytics` | ✓ | ✓ | ✓ |
| `view_model_card` | ✗ | ✓ | ✓ |
| `view_audit_trail` | ✗ | ✓ | ✓ |
| `take_action` (confirm/clear/investigating) | ✓ | ✓ | ✓ |
| `export_audit_log` | ✗ | ✓ | ✓ |
| `verify_integrity` | ✗ | ✓ | ✓ |

`admin` mirrors `supervisor` for current UI features; the role is reserved for
future additions (user management, threshold configuration).

---

## Bypass Findings — Severity Ranked

---

### B-1 · MEDIUM · Post-login session-state overwrite escalates role

**Status: Known limitation, documented and tested. Cannot be fixed within the
Streamlit session-dict model.**

**Description:**  
After a legitimate auditor login, an attacker who can write to
`st.session_state` (e.g. via a malicious Streamlit component, a future
`st.query_params` vulnerability, or direct browser devtools in a hypothetical
future client-state Streamlit model) can overwrite `_auth_role`:

```python
import streamlit as st
st.session_state["_auth_role"] = "supervisor"
```

Because `_auth_verified` is already `True` from the real login, the next call
to `has_permission("view_audit_trail")` returns `True`.

**Reproduction (test `test_auditor_cannot_escalate_to_supervisor_via_state`):**
```python
auth_mock.attempt_login("auditor1", "demo_auditor1")  # role = "auditor"
st.session_state["_auth_role"] = "supervisor"         # state overwrite
assert auth_mock.current_role() == "supervisor"       # PASSES — escalation succeeded
assert auth_mock.has_permission("view_audit_trail")   # PASSES — bypass confirmed
```

**Root cause:**  
Streamlit session state is a server-side Python dict, but it is readable and
writable by any code running in the same process, including components. The
role is not signed or encrypted — it is trusted at face value on every read.

**Why it cannot be fixed in a demo:**  
Fixing this requires a cryptographically signed session token that the server
verifies on every sensitive operation, without trusting any client-writable
dict. That is an identity-provider concern (OAuth/SAML), not a Streamlit dict
concern.

**Mitigation in the demo:**  
Raising the bar: the attacker needs code execution in the server process, not
just browser access. All production deployments must replace this with
signed tokens (see production note at end of report).

---

### B-2 · LOW · `_auth_role` alone (without `_auth_verified`) grants no access — CONFIRMED BLOCKED

**Status: Blocked. Tested.**

Setting `_auth_role = "admin"` without `_auth_verified = True` is rejected:
`is_authenticated()` checks `_auth_verified` first; `current_role()` returns
`None` if not authenticated; `has_permission()` returns `False`.

```python
st.session_state["_auth_role"] = "admin"
assert not auth_mock.is_authenticated()       # True — blocked
assert auth_mock.current_role() is None       # True — blocked
assert not auth_mock.has_permission("verify_integrity")  # True — blocked
```

---

### B-3 · LOW · URL-parameter role injection — CONFIRMED BLOCKED

**Status: Blocked. Tested.**

`auth_mock` never reads `st.query_params`. Auth keys are written exclusively
inside `attempt_login()`. Simulating URL-param injection by writing the role
key directly to session state without `_auth_verified` is blocked by B-2.

```python
st.session_state["role"]       = "admin"   # URL param injection
st.session_state["_auth_role"] = "admin"   # escalated copy
assert not auth_mock.is_authenticated()    # blocked — no _auth_verified
```

If a future code change adds `st.query_params` reading that populates
`_auth_role`, this becomes a Critical bypass. The audit notes this risk
explicitly so future authors do not introduce it.

---

### B-4 · LOW · Invented role string grants no permissions — CONFIRMED BLOCKED

**Status: Blocked. Tested.**

A role string not present in `PERMISSIONS` (e.g. `"superadmin"`, `"god"`)
causes `PERMISSIONS.get(role, {})` to return an empty dict, so all permission
lookups return `False`.

---

### B-5 · LOW · `_auth_verified=True` without a role causes graceful None return — CONFIRMED SAFE

**Status: Handled.**

If `_auth_verified` is `True` but `_auth_role` is absent, `current_role()`
returns `None`, and `PERMISSIONS.get(None, {})` returns `{}` — all permissions
`False`. The session is technically "authenticated" (the flag is set) but has
no capabilities. Not exploitable.

---

### B-6 · LOW · Logout incompleteness (role bleed) — CONFIRMED BLOCKED

**Status: Blocked. Tested.**

`logout()` calls `st.session_state.clear()` — it wipes **all** keys, not just
the auth keys. Tested scenarios:

```
supervisor logs in
  → UI state accumulates (_last_viewed_pid, sb_spec, auditor_id, ...)
supervisor logs out
  → ALL keys gone
auditor logs in
  → role = "auditor", no supervisor permissions, no residual UI state
```

A partial `del st.session_state["_auth_verified"]` pattern would have left
`_last_viewed_pid`, `auditor_id` (set to "supervisor1"), and filter values
from the prior session visible to the next user. The full `clear()` prevents
this.

---

### B-7 · INFO · Function-level gates implemented for all sensitive actions

**Status: Confirmed present.**

Every sensitive action handler now calls `require_permission()` as a second
line of defence, independent of whether the UI element was hidden:

| Handler | Gate |
|---------|------|
| Verify Integrity button | `require_permission("verify_integrity")` |
| Export to CSV button | `require_permission("export_audit_log")` |
| Confirm flag button | `require_permission("take_action")` |
| Clear flag button | `require_permission("take_action")` |
| Investigating button | `require_permission("take_action")` |
| Model Card tab body | `has_permission("view_model_card")` + `st.stop()` |
| Audit Trail tab body | `has_permission("view_audit_trail")` + `st.stop()` |

The Model Card and Audit Trail use `st.stop()` at the top of the tab block,
which halts Streamlit rendering before any sensitive content is emitted.
Even if a user reaches the tab (they can click it), they see only an
access-denied message.

---

### B-8 · INFO · Bad credentials write no partial session state — CONFIRMED

**Status: Confirmed.**

`attempt_login()` writes auth keys only after the credential check passes. A
failed login leaves `st.session_state` completely empty.

---

## What Streamlit's Architecture Means for Tab Access

Streamlit tabs are **not routes**. All four tabs render on every page load;
Streamlit simply hides non-selected tabs. There is no URL-based deep link that
triggers only one tab's code block.

This means:
- A user cannot deep-link directly to `?tab=audit` and bypass the gate.
- The gate is enforced in the `with tab_audit:` block, which executes on every
  render; the content is hidden by Streamlit's JS before the role check, but
  the Python check runs regardless.
- Using `st.stop()` inside the tab block prevents any content below the gate
  from being sent to the client even if Streamlit's JS tab-hiding were somehow
  bypassed.

---

## Test Results

```
tests/test_auth_bypass.py — 30 tests, 30 passed (0.17s)

  TestUnauthenticated           5/5   ✓
  TestBypassViaDirectState      5/5   ✓  (B-1 documented as known limitation)
  TestRequirePermission        11/11  ✓
  TestLogout                    4/4   ✓
  TestBadCredentials            4/4   ✓
  TestPermissionMatrix          1/1   ✓  (exhaustive — all 21 role×permission cells)
```

---

## Changes Made in This Audit

| File | Change |
|------|--------|
| `auth_mock.py` (new) | Role definitions, permission matrix, `attempt_login()`, `logout()`, `require_permission()`, `render_login_screen()` |
| `app.py` | Import `auth_mock`; authentication gate at top of `main()`; role badge + Sign Out button in sidebar; `st.stop()` gates on Model Card and Audit Trail tabs; `require_permission()` inside all five action buttons |
| `tests/test_auth_bypass.py` (new) | 30 tests covering all bypass scenarios including the documented B-1 weakness |

---

## Summary Statements

### (a) Is the mock role-gating coherent for the demo?

**Yes, with one documented limitation.**

The gating is internally consistent: every role has a clear permission set,
all sensitive actions are protected by both a UI-layer hide and a function-level
`require_permission()` call, logout clears all session state without residue,
bad credentials write no state, and invented roles and isolated state-key
injections are all blocked. The one inherent weakness (B-1: post-login
session-state overwrite) is a fundamental property of any in-process mutable
dict used as a session store — it cannot be fixed at the mock layer. It is
documented, tested, and the test clearly labels it as a known limitation rather
than a suppressed failure.

For a synthetic-data demo shown to a small, trusted audience, this level of
gating is coherent and appropriate.

---

### (b) What production requires that this demo does not implement

**This demo's authentication is NOT suitable for real healthcare data under
any circumstances.** Before handling real patient records, provider identities,
or billing data, the following must be replaced:

| Demo behaviour | Production requirement |
|----------------|------------------------|
| Hardcoded plaintext credentials in `auth_mock.py` | Identity provider (Okta, Azure AD, AWS Cognito) via OAuth 2.0 / OIDC or SAML 2.0 |
| Plaintext password comparison | Passwords hashed with bcrypt or argon2; ideally no passwords stored at all (SSO only) |
| Streamlit session dict as session store | Server-signed, encrypted session tokens (e.g. JWT with HS256/RS256) that the server validates on every request |
| No MFA | MFA enforced for all roles — TOTP minimum, hardware keys for admin |
| No session expiry | Idle timeout (≤ 15 min for healthcare), absolute session lifetime, session rotation on login |
| No login rate-limiting | Account lockout after N failed attempts; IP-based rate limiting |
| No audit logging of auth events | Every login, logout, and failed attempt logged to the immutable audit trail |
| `_auth_role` writable by any in-process code | Role embedded in a server-validated, client-opaque token that no Python code in the app process can forge |
| Role definitions in source code | Roles managed in the identity provider or a separate RBAC service |
| No HTTPS enforcement | TLS 1.2+ required; HSTS header; secure + HttpOnly cookies |

**Healthcare-specific:** In jurisdictions with PHIPA (Ontario), HIPAA (USA), or
equivalent regulations, access control to systems that process real health data
must be documented, audited, and reviewed regularly. A hardcoded demo mock does
not satisfy any of these requirements.

---

*Report generated 2026-06-09. Automated tests + manual code review. Not a
professional penetration test. Does not cover network-layer, OS-level, or
infrastructure security.*
