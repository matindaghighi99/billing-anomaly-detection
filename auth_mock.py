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

import streamlit as st

# ---------------------------------------------------------------------------
# Demo credentials — readable by anyone with file access; that is intentional
# for a demo.  In production these would live in an identity provider, not here.
# ---------------------------------------------------------------------------
_DEMO_USERS: dict[str, dict] = {
    "auditor1":    {"password": "demo_auditor1",    "role": "auditor",    "display": "Alex Auditor"},
    "supervisor1": {"password": "demo_supervisor1", "role": "supervisor", "display": "Sam Supervisor"},
    "admin1":      {"password": "demo_admin1",      "role": "admin",      "display": "Admin User"},
}

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
    user_record = _DEMO_USERS.get(username)
    if user_record is None or user_record["password"] != password:
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
  [data-testid="stSidebar"] { display: none; }
  .login-card {
    max-width: 380px; margin: 60px auto 0;
    background: linear-gradient(135deg, #1A1A2E 0%, #16213E 100%);
    border: 1px solid #2D2D4E; border-radius: 14px; padding: 38px 34px;
  }
  .login-title  { font-size:1.3rem; font-weight:700; color:#E0E0FF; text-align:center; margin-bottom:4px; }
  .login-sub    { font-size:0.75rem; color:#5A5A8A; text-align:center; margin-bottom:26px; }
  .login-notice {
    font-size:0.71rem; color:#8A6A00;
    background:rgba(160,120,0,0.12); border:1px solid rgba(160,120,0,0.3);
    border-radius:6px; padding:8px 12px; margin-top:16px; text-align:center;
  }
  .demo-creds   { font-size:0.68rem; color:#383870; text-align:center; margin-top:8px; }
</style>
""", unsafe_allow_html=True)

    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        st.markdown('<div class="login-card">', unsafe_allow_html=True)
        st.markdown(
            '<div class="login-title">'
            '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" '
            'fill="none" stroke="#C0C0F8" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" '
            'style="vertical-align:middle;margin-right:6px;">'
            '<path d="M12 9v6m3-3H9m12 0a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>'
            'Billing Anomaly Audit</div>',
            unsafe_allow_html=True,
        )
        st.markdown('<div class="login-sub">DECISION SUPPORT ONLY — SYNTHETIC DATA</div>', unsafe_allow_html=True)

        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", use_container_width=True, type="primary")

        if submitted:
            if attempt_login(username, password):
                st.rerun()
            else:
                st.error("Invalid username or password.")

        st.markdown("""
<div class="login-notice">
  <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#C08000" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-right:4px;"><path d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"/></svg>
  MOCK AUTHENTICATION — demo credentials only.<br>
  Not suitable for real healthcare data.
</div>
<div class="demo-creds">
  auditor1 / supervisor1 / admin1
</div>
""", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    st.stop()   # halt page rendering until login succeeds and st.rerun() fires
