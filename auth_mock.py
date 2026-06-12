"""
auth_mock.py — Mock role-based access control for the Billing Anomaly Dashboard.

⚠ THIS IS A DEMO MOCK, NOT REAL SECURITY.
  Credentials are hardcoded, sessions are Streamlit server-side dicts,
  and passwords are compared in plaintext.

  Production requirements before handling real healthcare data:
    • SSO/OAuth 2.0 or SAML 2.0 identity provider (e.g. Okta, Azure AD)
    • MFA enforced for every login
    • Server-signed, encrypted session tokens (not client-visible state)
    • Passwords hashed with bcrypt or argon2 — never stored or compared in plaintext
    • Session expiry, rotation on privilege change, and idle timeout
    • Rate-limiting and lockout on failed login attempts
    • All auth events (login, logout, failures) recorded in the audit trail
"""

import hashlib
import hmac
import json
import os
import time

import streamlit as st

# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------
# Passwords are NEVER stored in plaintext. Each record holds a PBKDF2-HMAC-SHA256
# salt + hash; attempt_login() recomputes the hash and compares in constant time.
#
# For real deployments, override the user store entirely via the BAAD_USERS_JSON
# environment variable (a JSON object of the same shape):
#   {"alice": {"salt": "<hex>", "hash": "<hex>", "role": "supervisor",
#              "display": "Alice A."}}
# Generate records with:  python -c "import auth_mock,sys;
#   print(auth_mock.make_user_record(*sys.argv[1:]))"  <password> <role> <name>
#
# This remains a DEMO mock (session-dict RBAC). Production still requires a real
# IdP (SSO/OAuth/SAML) with server-signed sessions — see MOH_ALIGNMENT.md §7.
# ---------------------------------------------------------------------------

_PBKDF2_ITERATIONS = 200_000

# Login throttling (configurable via env). Enforced in render_login_screen().
_MAX_FAILS = int(os.environ.get("BAAD_MAX_LOGIN_FAILS", "5"))
_LOCKOUT_SECONDS = int(os.environ.get("BAAD_LOCKOUT_SECONDS", "60"))

# Hide the on-screen demo-credential hint in production deployments.
_HIDE_DEMO_CREDS = os.environ.get("HIDE_DEMO_CREDS", "").strip().lower() \
    not in ("", "0", "false", "no")

_DEMO_USERS: dict[str, dict] = {
    "auditor1":    {"salt": "9213dbdab5577b620a9173520e739d58", "hash": "026a3cfd9db5e2d4b14c2429d765331e40601cfc5b03677e19def470745c5638", "role": "auditor",    "display": "Alex Auditor"},    # pragma: allowlist secret
    "supervisor1": {"salt": "c6927a10fca0e48f16e3803e9e30bec4", "hash": "f7e9bb242eea2b14caddea63be30a9271a964fef61beaab2d75429c3de19dfb1", "role": "supervisor", "display": "Sam Supervisor"},  # pragma: allowlist secret
    "admin1":      {"salt": "7390674ea4874089de59c0ce0299d7b4", "hash": "2f2efdb0fe6f05dba51f3bed5b62f02f7ddf0b17414d9a34684b72e039221136", "role": "admin",      "display": "Admin User"},      # pragma: allowlist secret
}


def _hash_pw(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                               _PBKDF2_ITERATIONS).hex()


def make_user_record(password: str, role: str, display: str) -> str:
    """Print a JSON user record (salt+hash) for use in BAAD_USERS_JSON."""
    salt = os.urandom(16)
    return json.dumps({"salt": salt.hex(), "hash": _hash_pw(password, salt),
                       "role": role, "display": display})


def _load_users() -> dict:
    """Demo store by default; full override via BAAD_USERS_JSON env var."""
    raw = os.environ.get("BAAD_USERS_JSON")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return _DEMO_USERS
    return _DEMO_USERS


_USERS = _load_users()

# ---------------------------------------------------------------------------
# Permission matrix
# ---------------------------------------------------------------------------
# Roles in ascending privilege order: auditor < supervisor < admin.
# admin currently mirrors supervisor for UI features; the distinction exists
# for future extension (e.g. user management, threshold configuration).
# ---------------------------------------------------------------------------
PERMISSIONS: dict[str, dict[str, bool]] = {
    "auditor": {
        "view_worklist":    True,
        "view_analytics":   True,
        "view_model_card":  False,   # methodology detail — supervisor+ only
        "view_audit_trail": False,   # audit log — supervisor+ only
        "take_action":      True,    # confirm / clear / investigating
        "export_audit_log": False,
        "verify_integrity": False,
    },
    "supervisor": {
        "view_worklist":    True,
        "view_analytics":   True,
        "view_model_card":  True,
        "view_audit_trail": True,
        "take_action":      True,
        "export_audit_log": True,
        "verify_integrity": True,
    },
    "admin": {
        "view_worklist":    True,
        "view_analytics":   True,
        "view_model_card":  True,
        "view_audit_trail": True,
        "take_action":      True,
        "export_audit_log": True,
        "verify_integrity": True,
    },
}

# Internal session-state keys — prefixed with "_auth_" to signal they are
# owned by this module.  app.py must not set these directly.
_KEY_VERIFIED = "_auth_verified"
_KEY_ROLE     = "_auth_role"
_KEY_USER     = "_auth_user"
_KEY_DISPLAY  = "_auth_display"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_authenticated() -> bool:
    """True only when the current session completed a successful login."""
    return bool(st.session_state.get(_KEY_VERIFIED, False))


def current_role() -> str | None:
    """Role string for the active session, or None if not logged in."""
    if not is_authenticated():
        return None
    return st.session_state.get(_KEY_ROLE)


def current_user() -> str | None:
    """Username for the active session, or None if not logged in."""
    if not is_authenticated():
        return None
    return st.session_state.get(_KEY_USER)


def current_display_name() -> str:
    """Human-readable display name, or 'Unknown' if not logged in."""
    return st.session_state.get(_KEY_DISPLAY, "Unknown")


def has_permission(permission: str) -> bool:
    """Return True if the current session has the named permission.

    Returns False — not an exception — so callers can branch on it.
    Always returns False when not authenticated, even if permission is valid.
    """
    role = current_role()
    if role is None:
        return False
    return PERMISSIONS.get(role, {}).get(permission, False)


def require_permission(permission: str) -> None:
    """Raise PermissionError if the current session lacks *permission*.

    Call this inside every action handler (button callbacks, exports) that
    guards a sensitive operation.  The UI visibility check is the first line
    of defence; this is the second line that remains effective even if the
    UI guard is bypassed.
    """
    if not is_authenticated():
        raise PermissionError("Not authenticated.")
    if not has_permission(permission):
        role = current_role()
        raise PermissionError(
            f"Role '{role}' does not have permission '{permission}'."
        )


def attempt_login(username: str, password: str) -> bool:
    """Validate credentials and, on success, write session state.

    The auth keys (_auth_verified, _auth_role, _auth_user, _auth_display)
    are ONLY ever written here.  They are never read from URL parameters,
    form hidden fields, or any other client-supplied source.

    Returns True on success, False on bad credentials.
    """
    user_record = _USERS.get(username)
    # Always run a PBKDF2 verification — even for unknown usernames against a
    # throwaway salt — so response time does not reveal whether a username
    # exists (mitigates username enumeration via timing).
    if user_record is None:
        _hash_pw(password, b"\x00" * 16)  # dummy work
        return False
    computed = _hash_pw(password, bytes.fromhex(user_record["salt"]))
    if not hmac.compare_digest(computed, user_record["hash"]):
        return False

    st.session_state[_KEY_VERIFIED] = True
    st.session_state[_KEY_ROLE]     = user_record["role"]
    st.session_state[_KEY_USER]     = username
    st.session_state[_KEY_DISPLAY]  = user_record["display"]
    st.session_state["auditor_id"]  = username   # used by audit log trail
    return True


def logout() -> None:
    """Clear ALL session state and rerun.

    Using st.session_state.clear() rather than deleting only the auth keys
    is intentional: Streamlit reuses websocket sessions across browser-tab
    reloads, so partial clears leave cached filter values, selected provider
    IDs, and other state from the previous user visible to the next login.
    """
    st.session_state.clear()
    st.rerun()


# ---------------------------------------------------------------------------
# Login UI
# ---------------------------------------------------------------------------

def render_login_screen() -> None:
    """Render the full-page login form.  Calls st.stop() until login succeeds."""
    st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@500;600;700&family=Fira+Sans:wght@300;400;500;600&display=swap');

  /* ── motion ── */
  @keyframes lgRise  { from { opacity: 0; transform: translateY(14px); }
                       to   { opacity: 1; transform: translateY(0); } }
  @keyframes lgGlow  { 0%,100% { box-shadow: 0 0 22px rgba(37,99,235,0.18),
                                              inset 0 0 0 1px rgba(96,160,232,0.12); }
                       50%     { box-shadow: 0 0 34px rgba(37,99,235,0.34),
                                              inset 0 0 0 1px rgba(96,160,232,0.22); } }
  @keyframes lgFloat { 0%,100% { transform: translateY(0); }
                       50%     { transform: translateY(-3px); } }

  /* ── page chrome ── */
  [data-testid="stSidebar"]  { display: none !important; }
  .stAppHeader               { visibility: hidden !important; height: 0 !important; min-height: 0 !important; overflow: hidden !important; }
  .stApp                     { background: #060610 !important; min-height: 100vh; font-family: 'Fira Sans', system-ui, sans-serif !important; }

  /* ── remove sidebar space so main takes full width ── */
  [data-testid="stAppViewContainer"] > section[data-testid="stMain"] {
    margin-left: 0 !important;
    width: 100% !important;
    min-width: 100% !important;
  }

  /* ── centre the content column ── */
  div[data-testid="stMainBlockContainer"] {
    max-width: 440px !important;
    padding: 40px 1.5rem 2rem !important;
    margin-left: auto !important;
    margin-right: auto !important;
  }

  /* ── logo / title block ── */
  .lg-header {
    text-align: center;
    margin-bottom: 32px;
  }
  .lg-icon {
    display: inline-flex; align-items: center; justify-content: center;
    width: 56px; height: 56px;
    background: linear-gradient(135deg, #0F2744, #1E3A5F);
    border: 1px solid #2563EB44;
    border-radius: 16px;
    margin-bottom: 16px;
    box-shadow: 0 0 20px rgba(37,99,235,0.15);
    animation: lgGlow 4s ease-in-out infinite, lgFloat 6s ease-in-out infinite;
  }
  .lg-title {
    font-family: 'Fira Code', monospace !important;
    font-size: 1.4rem; font-weight: 600;
    color: #E8EEFF; letter-spacing: -0.3px;
    margin-bottom: 6px;
  }
  .lg-sub {
    font-size: 0.68rem; color: #4A5A7A;
    letter-spacing: 1.2px; text-transform: uppercase;
  }

  /* ── form card ── */
  [data-testid="stForm"] {
    position: relative;
    background: linear-gradient(160deg, #0C0C20 0%, #090916 100%);
    border: 1px solid #1E2848;
    border-radius: 16px;
    padding: 32px 28px 28px !important;
    box-shadow: 0 18px 50px rgba(0,0,0,0.65), 0 0 0 1px rgba(37,99,235,0.08);
    animation: lgRise 0.55s cubic-bezier(0.22, 1, 0.36, 1) both;
  }
  /* a faint top hairline gives the card a crafted, lit-from-above edge */
  [data-testid="stForm"]::before {
    content: ""; position: absolute; top: 0; left: 16px; right: 16px; height: 1px;
    background: linear-gradient(90deg, transparent, rgba(96,160,232,0.55), transparent);
  }

  /* ── input labels ── */
  [data-testid="stForm"] label p {
    color: #6878A8 !important;
    font-size: 0.78rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    margin-bottom: 6px;
  }

  /* ── text inputs ── */
  [data-testid="stForm"] input {
    background: #07071A !important;
    border: 1px solid #1E2848 !important;
    border-radius: 8px !important;
    color: #D0D8F0 !important;
    padding: 11px 14px !important;
    font-size: 0.9rem !important;
    font-family: 'Fira Sans', sans-serif !important;
    transition: border-color 0.2s, box-shadow 0.2s;
  }
  [data-testid="stForm"] input:focus {
    border-color: #2563EB !important;
    box-shadow: 0 0 0 3px rgba(37,99,235,0.2) !important;
    outline: none !important;
  }

  /* ── password eye toggle — match input background ── */
  [data-testid="stForm"] [data-testid="InputInstructions"] { display: none !important; }
  [data-testid="stForm"] button[kind="secondary"],
  [data-testid="stForm"] [data-testid="baseButton-secondary"] {
    background: #07071A !important;
    border: none !important;
    color: #4A5A7A !important;
  }
  [data-testid="stForm"] button[kind="secondary"]:hover {
    background: #0E0E2A !important;
    color: #8898C8 !important;
  }

  /* ── sign-in button (professional trust-blue) ── */
  [data-testid="stFormSubmitButton"] button {
    background: #2563EB !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 9px !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    font-family: 'Fira Sans', sans-serif !important;
    padding: 12px !important;
    margin-top: 8px;
    width: 100%;
    letter-spacing: 0.4px;
    transition: background 0.2s, transform 0.1s;
    cursor: pointer;
  }
  [data-testid="stFormSubmitButton"] button:hover {
    background: #1D4ED8 !important;
  }
  [data-testid="stFormSubmitButton"] button:active {
    transform: scale(0.99) !important;
  }

  /* ── notice banner ── */
  .lg-notice {
    display: flex; align-items: flex-start; gap: 10px;
    background: rgba(120,90,0,0.09);
    border: 1px solid rgba(120,90,0,0.22);
    border-radius: 10px;
    padding: 11px 14px;
    margin-top: 16px;
    font-size: 0.71rem; color: #8A7020; line-height: 1.6;
  }
  .lg-creds {
    text-align: center;
    font-size: 0.67rem; color: #2A2A50;
    margin-top: 10px; letter-spacing: 0.3px;
  }

  /* ── error state ── */
  [data-testid="stAlertContainer"] {
    border-radius: 8px !important; margin-top: 8px !important;
  }

  /* ── reduced motion ── */
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation: none !important; transition: none !important; }
  }
</style>
""", unsafe_allow_html=True)

    # ── JS injection: runs after Emotion, guarantees header/container override ─
    import streamlit.components.v1 as _components
    _components.html("""
<script>
(function() {
  function applyStyles() {
    var s = document.createElement('style');
    s.innerHTML = `
      .stAppHeader { visibility: hidden !important; height: 0 !important; min-height: 0 !important; overflow: hidden !important; }
      div[data-testid="stMainBlockContainer"] { max-width: 440px !important; margin-left: auto !important; margin-right: auto !important; padding-top: 32px !important; }
    `;
    document.head.appendChild(s);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', applyStyles);
  } else {
    applyStyles();
  }
  // Re-apply after short delay to beat React re-renders
  setTimeout(applyStyles, 300);
  setTimeout(applyStyles, 800);
})();
</script>
""", height=0)

    # ── logo + title (pure HTML — renders fine as markdown) ──────────────────
    st.markdown("""
<div class="lg-header">
  <div class="lg-icon">
    <svg xmlns="http://www.w3.org/2000/svg" width="26" height="26" viewBox="0 0 24 24"
         fill="none" stroke="#60A0E8" stroke-width="1.5"
         stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 9v6m3-3H9m12 0a9 9 0 11-18 0 9 9 0 0118 0z"/>
    </svg>
  </div>
  <div class="lg-title">Billing Anomaly Audit</div>
  <div class="lg-sub">Decision support only &nbsp;·&nbsp; Synthetic data</div>
</div>
""", unsafe_allow_html=True)

    # ── form (Streamlit renders this in [data-testid="stForm"], styled above) ─
    with st.form("login_form", clear_on_submit=False):
        username  = st.text_input("Username")
        password  = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", use_container_width=True, type="primary")

    if submitted:
        now = time.time()
        lock_until = st.session_state.get("_login_lock_until", 0)
        if now < lock_until:
            st.error(f"Too many failed attempts. Try again in "
                     f"{int(lock_until - now)}s.")
        elif attempt_login(username, password):
            st.session_state.pop("_login_fails", None)
            st.session_state.pop("_login_lock_until", None)
            st.rerun()
        else:
            fails = st.session_state.get("_login_fails", 0) + 1
            if fails >= _MAX_FAILS:
                st.session_state["_login_lock_until"] = now + _LOCKOUT_SECONDS
                st.session_state["_login_fails"] = 0
                st.error(f"Too many failed attempts. Locked for "
                         f"{_LOCKOUT_SECONDS}s.")
            else:
                st.session_state["_login_fails"] = fails
                st.error(f"Invalid username or password. "
                         f"({_MAX_FAILS - fails} attempt(s) left)")

    # ── disclaimer ────────────────────────────────────────────────────────────
    st.markdown("""
<div class="lg-notice">
  <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24"
       fill="none" stroke="#9A7820" stroke-width="1.5"
       stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;margin-top:1px;">
    <path d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"/>
  </svg>
  <span>Mock authentication — demo credentials only. Not suitable for real healthcare data.</span>
</div>
""", unsafe_allow_html=True)

    # Demo-credential hint — suppressed in production (HIDE_DEMO_CREDS=1)
    if not _HIDE_DEMO_CREDS:
        st.markdown(
            '<div class="lg-creds">auditor1 &nbsp;/&nbsp; supervisor1 '
            '&nbsp;/&nbsp; admin1</div>',
            unsafe_allow_html=True,
        )

    st.stop()   # halt page rendering until login succeeds and st.rerun() fires
