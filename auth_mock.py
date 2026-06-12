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
    # ── original accounts ──
    "auditor1":    {"password": "demo_auditor1",    "role": "auditor",    "display": "Alex Auditor"},       # pragma: allowlist secret
    "supervisor1": {"password": "demo_supervisor1", "role": "supervisor", "display": "Sam Supervisor"},     # pragma: allowlist secret
    "admin1":      {"password": "demo_admin1",      "role": "admin",      "display": "Admin User"},         # pragma: allowlist secret
    # ── auditors (accounts 2-15) ──
    "auditor2":    {"password": "demo_auditor2",    "role": "auditor",    "display": "Blake Auditor"},      # pragma: allowlist secret
    "auditor3":    {"password": "demo_auditor3",    "role": "auditor",    "display": "Casey Auditor"},      # pragma: allowlist secret
    "auditor4":    {"password": "demo_auditor4",    "role": "auditor",    "display": "Dana Auditor"},       # pragma: allowlist secret
    "auditor5":    {"password": "demo_auditor5",    "role": "auditor",    "display": "Ellis Auditor"},      # pragma: allowlist secret
    "auditor6":    {"password": "demo_auditor6",    "role": "auditor",    "display": "Finley Auditor"},     # pragma: allowlist secret
    "auditor7":    {"password": "demo_auditor7",    "role": "auditor",    "display": "Gray Auditor"},       # pragma: allowlist secret
    "auditor8":    {"password": "demo_auditor8",    "role": "auditor",    "display": "Harper Auditor"},     # pragma: allowlist secret
    "auditor9":    {"password": "demo_auditor9",    "role": "auditor",    "display": "Indira Auditor"},     # pragma: allowlist secret
    "auditor10":   {"password": "demo_auditor10",   "role": "auditor",    "display": "Jordan Auditor"},     # pragma: allowlist secret
    "auditor11":   {"password": "demo_auditor11",   "role": "auditor",    "display": "Kai Auditor"},        # pragma: allowlist secret
    "auditor12":   {"password": "demo_auditor12",   "role": "auditor",    "display": "Lee Auditor"},        # pragma: allowlist secret
    "auditor13":   {"password": "demo_auditor13",   "role": "auditor",    "display": "Morgan Auditor"},     # pragma: allowlist secret
    "auditor14":   {"password": "demo_auditor14",   "role": "auditor",    "display": "Nico Auditor"},       # pragma: allowlist secret
    "auditor15":   {"password": "demo_auditor15",   "role": "auditor",    "display": "Oakley Auditor"},     # pragma: allowlist secret
    # ── supervisors (accounts 2-8) ──
    "supervisor2": {"password": "demo_supervisor2", "role": "supervisor", "display": "Pat Supervisor"},     # pragma: allowlist secret
    "supervisor3": {"password": "demo_supervisor3", "role": "supervisor", "display": "Quinn Supervisor"},   # pragma: allowlist secret
    "supervisor4": {"password": "demo_supervisor4", "role": "supervisor", "display": "Riley Supervisor"},   # pragma: allowlist secret
    "supervisor5": {"password": "demo_supervisor5", "role": "supervisor", "display": "Sage Supervisor"},    # pragma: allowlist secret
    "supervisor6": {"password": "demo_supervisor6", "role": "supervisor", "display": "Taylor Supervisor"},  # pragma: allowlist secret
    "supervisor7": {"password": "demo_supervisor7", "role": "supervisor", "display": "Uma Supervisor"},     # pragma: allowlist secret
    "supervisor8": {"password": "demo_supervisor8", "role": "supervisor", "display": "Val Supervisor"},     # pragma: allowlist secret
    # ── admins (accounts 2-4) ──
    "admin2":      {"password": "demo_admin2",      "role": "admin",      "display": "Winter Admin"},       # pragma: allowlist secret
    "admin3":      {"password": "demo_admin3",      "role": "admin",      "display": "Xander Admin"},       # pragma: allowlist secret
    "admin4":      {"password": "demo_admin4",      "role": "admin",      "display": "Yara Admin"},         # pragma: allowlist secret
    # ── read-only service account ──
    "readonly1":   {"password": "demo_readonly1",   "role": "auditor",    "display": "Read Only"},          # pragma: allowlist secret
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
  @import url('https://fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,300;0,14..32,400;0,14..32,500;0,14..32,600;0,14..32,700;0,14..32,800&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

  /* ── Keyframes ── */
  @keyframes orbDrift1 {
    0%,100% { transform: translate(0,0) scale(1); }
    25%     { transform: translate(90px,-70px) scale(1.12); }
    50%     { transform: translate(-50px,80px) scale(0.9); }
    75%     { transform: translate(70px,50px) scale(1.07); }
  }
  @keyframes orbDrift2 {
    0%,100% { transform: translate(0,0) scale(1); }
    33%     { transform: translate(-110px,60px) scale(1.1); }
    66%     { transform: translate(80px,-90px) scale(1.18); }
  }
  @keyframes orbDrift3 {
    0%,100% { transform: translate(0,0) scale(1); }
    50%     { transform: translate(60px,70px) scale(1.12); }
  }
  @keyframes cardRise {
    from { opacity: 0; transform: translateY(28px) scale(0.97); filter: blur(3px); }
    to   { opacity: 1; transform: translateY(0)    scale(1);    filter: blur(0); }
  }
  @keyframes logoGlow {
    0%,100% { box-shadow: 0 0 0 0   rgba(99,102,241,0.5),
                          0 0 32px  rgba(99,102,241,0.2),
                          inset 0 1px 0 rgba(255,255,255,0.12); }
    50%     { box-shadow: 0 0 0 16px rgba(99,102,241,0),
                          0 0 60px  rgba(99,102,241,0.4),
                          inset 0 1px 0 rgba(255,255,255,0.12); }
  }
  @keyframes ringPop {
    0%   { transform: scale(0.8); opacity: 0.7; }
    100% { transform: scale(2.0); opacity: 0; }
  }
  @keyframes gradTitle {
    0%,100% { background-position: 0% 50%; }
    50%     { background-position: 100% 50%; }
  }
  @keyframes shimmerBtn {
    0%   { transform: translateX(-120%); }
    100% { transform: translateX(120%); }
  }
  @keyframes fadeUp {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  @keyframes scanLine {
    0%   { top: -2px; }
    100% { top: 100%; }
  }

  /* ── Page reset ── */
  [data-testid="stSidebar"] { display: none !important; }
  .stAppHeader { visibility: hidden !important; height: 0 !important; min-height: 0 !important; overflow: hidden !important; }

  .stApp {
    background: #02020C !important;
    min-height: 100vh;
    font-family: 'Inter', system-ui, -apple-system, sans-serif !important;
  }
  [data-testid="stAppViewContainer"] > section[data-testid="stMain"] {
    margin-left: 0 !important; width: 100% !important; min-width: 100% !important;
  }
  div[data-testid="stMainBlockContainer"] {
    max-width: 460px !important;
    padding: 0 1.5rem 2.5rem !important;
    margin-left: auto !important;
    margin-right: auto !important;
    position: relative; z-index: 10;
  }

  /* ── Ambient background ── */
  .lg-bg {
    position: fixed; inset: 0; overflow: hidden;
    pointer-events: none; z-index: 0;
  }
  .lg-noise {
    position: absolute; inset: 0;
    background-image:
      linear-gradient(rgba(99,102,241,0.035) 1px, transparent 1px),
      linear-gradient(90deg, rgba(99,102,241,0.035) 1px, transparent 1px);
    background-size: 52px 52px;
    mask-image: radial-gradient(ellipse 90% 80% at 50% 50%, black 20%, transparent 75%);
  }
  .lg-orb {
    position: absolute; border-radius: 50%;
    filter: blur(90px); will-change: transform;
  }
  .lg-orb-a {
    width: 700px; height: 700px;
    background: radial-gradient(circle at 40% 40%, #6366F1 0%, #4338CA 40%, transparent 70%);
    top: -280px; left: -200px; opacity: 0.45;
    animation: orbDrift1 20s ease-in-out infinite;
  }
  .lg-orb-b {
    width: 600px; height: 600px;
    background: radial-gradient(circle at 60% 60%, #06B6D4 0%, #0891B2 40%, transparent 70%);
    bottom: -200px; right: -150px; opacity: 0.35;
    animation: orbDrift2 26s ease-in-out infinite;
  }
  .lg-orb-c {
    width: 400px; height: 400px;
    background: radial-gradient(circle at 50% 50%, #8B5CF6 0%, #7C3AED 40%, transparent 70%);
    top: 38%; left: 52%; opacity: 0.3;
    animation: orbDrift3 17s ease-in-out infinite;
  }
  .lg-orb-d {
    width: 280px; height: 280px;
    background: radial-gradient(circle at 50% 50%, #F43F5E 0%, transparent 70%);
    top: 10%; right: 15%; opacity: 0.18;
    animation: orbDrift1 23s ease-in-out infinite reverse;
  }

  /* ── Logo area ── */
  .lg-hero {
    text-align: center;
    padding-top: 64px;
    margin-bottom: 40px;
    animation: fadeUp 0.7s ease both;
  }
  .lg-ring-wrap {
    display: inline-block; position: relative; margin-bottom: 22px;
  }
  .lg-ring {
    position: absolute; inset: -12px; border-radius: 50%;
    border: 1px solid rgba(99,102,241,0.45);
    animation: ringPop 3.2s ease-out infinite;
  }
  .lg-ring:nth-child(2) { inset: -8px;  animation-delay: 1.1s; }
  .lg-ring:nth-child(3) { inset: -4px;  animation-delay: 2.2s; border-color: rgba(6,182,212,0.3); }
  .lg-icon-box {
    position: relative; z-index: 1;
    display: inline-flex; align-items: center; justify-content: center;
    width: 76px; height: 76px;
    background: linear-gradient(145deg, #1E1B55 0%, #2D2A7A 50%, #1E1B55 100%);
    border-radius: 24px;
    border: 1px solid rgba(99,102,241,0.55);
    box-shadow: 0 0 0 1px rgba(99,102,241,0.1),
                0 0 40px rgba(99,102,241,0.25),
                inset 0 1px 0 rgba(255,255,255,0.1);
    animation: logoGlow 4.5s ease-in-out infinite;
  }
  .lg-app-name {
    font-size: 1.75rem; font-weight: 800;
    letter-spacing: -0.6px; line-height: 1.1;
    background: linear-gradient(135deg, #EEF0FF 0%, #A5B4FC 40%, #67E8F9 80%, #A5B4FC 100%);
    background-size: 300% 300%;
    -webkit-background-clip: text; background-clip: text;
    -webkit-text-fill-color: transparent;
    animation: gradTitle 5s ease infinite;
    margin-bottom: 8px;
  }
  .lg-tagline {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.62rem; color: #2D3760;
    letter-spacing: 2.5px; text-transform: uppercase;
  }
  .lg-tagline em { color: #6366F1; font-style: normal; }

  /* ── Form card ── */
  [data-testid="stForm"] {
    position: relative; overflow: hidden;
    background: linear-gradient(160deg, #0A0A20 0%, #06061A 100%) !important;
    border-radius: 20px !important;
    padding: 38px 34px 32px !important;
    border: 1px solid rgba(99,102,241,0.25) !important;
    box-shadow:
      0 0 0 1px rgba(6,182,212,0.08),
      0 0 80px rgba(99,102,241,0.12),
      0 40px 80px rgba(0,0,0,0.75),
      inset 0 1px 0 rgba(255,255,255,0.04) !important;
    animation: cardRise 0.75s cubic-bezier(0.16,1,0.3,1) 0.05s both !important;
  }
  [data-testid="stForm"]::before {
    content: '';
    position: absolute; top: 0; left: 18px; right: 18px; height: 1px;
    background: linear-gradient(90deg, transparent, rgba(99,102,241,0.7), rgba(6,182,212,0.5), transparent);
  }
  /* subtle scan-line shimmer over the card */
  [data-testid="stForm"]::after {
    content: '';
    position: absolute; left: 0; right: 0; height: 40px;
    background: linear-gradient(transparent, rgba(99,102,241,0.04), transparent);
    pointer-events: none;
    animation: scanLine 5s linear infinite;
  }

  /* ── Labels ── */
  [data-testid="stForm"] label p {
    font-size: 0.71rem !important; font-weight: 600 !important;
    color: #3D4870 !important;
    letter-spacing: 1.2px; text-transform: uppercase;
    margin-bottom: 7px;
  }

  /* ── Inputs ── */
  [data-testid="stForm"] input {
    background: rgba(255,255,255,0.025) !important;
    border: 1px solid #181D40 !important;
    border-radius: 10px !important;
    color: #C8D4F8 !important;
    padding: 13px 16px !important;
    font-size: 0.9rem !important;
    font-family: 'Inter', sans-serif !important;
    transition: border-color 0.2s, box-shadow 0.2s, background 0.2s !important;
    caret-color: #6366F1;
  }
  [data-testid="stForm"] input::placeholder { color: #222840 !important; }
  [data-testid="stForm"] input:focus {
    background: rgba(99,102,241,0.05) !important;
    border-color: #6366F1 !important;
    box-shadow: 0 0 0 3px rgba(99,102,241,0.18), 0 0 20px rgba(99,102,241,0.12) !important;
    outline: none !important;
  }

  /* ── Password toggle ── */
  [data-testid="stForm"] [data-testid="InputInstructions"] { display: none !important; }
  [data-testid="stForm"] button[kind="secondary"],
  [data-testid="stForm"] [data-testid="baseButton-secondary"] {
    background: transparent !important; border: none !important; color: #303660 !important;
  }
  [data-testid="stForm"] button[kind="secondary"]:hover { color: #6366F1 !important; }

  /* ── Sign-in button ── */
  [data-testid="stFormSubmitButton"] button {
    position: relative; overflow: hidden;
    background: linear-gradient(135deg, #6366F1 0%, #4F46E5 60%, #4338CA 100%) !important;
    color: #FFFFFF !important;
    border: 1px solid rgba(99,102,241,0.4) !important;
    border-radius: 11px !important;
    font-weight: 700 !important; font-size: 0.92rem !important;
    font-family: 'Inter', sans-serif !important;
    padding: 14px !important;
    margin-top: 12px; width: 100%;
    letter-spacing: 0.2px;
    transition: transform 0.15s, box-shadow 0.2s !important;
    cursor: pointer;
    box-shadow: 0 0 24px rgba(99,102,241,0.35),
                0 4px 12px rgba(0,0,0,0.3),
                inset 0 1px 0 rgba(255,255,255,0.18) !important;
  }
  [data-testid="stFormSubmitButton"] button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 0 40px rgba(99,102,241,0.55),
                0 8px 24px rgba(0,0,0,0.35),
                inset 0 1px 0 rgba(255,255,255,0.18) !important;
  }
  [data-testid="stFormSubmitButton"] button:active { transform: translateY(0) scale(0.985) !important; }
  [data-testid="stFormSubmitButton"] button::after {
    content: '';
    position: absolute; top: 0; left: -100%; width: 55%; height: 100%;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.18), transparent);
    animation: shimmerBtn 3.5s ease infinite;
  }

  /* ── Divider ── */
  .lg-divider {
    display: flex; align-items: center; gap: 12px;
    margin: 22px 0 14px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.6rem; color: #1A2048; letter-spacing: 2px; text-transform: uppercase;
    animation: fadeUp 0.9s ease 0.3s both;
  }
  .lg-divider::before, .lg-divider::after {
    content: ''; flex: 1; height: 1px;
    background: linear-gradient(90deg, transparent, #151A3A, transparent);
  }

  /* ── Credential pills ── */
  .lg-pill-row {
    display: flex; justify-content: center; gap: 8px; flex-wrap: wrap;
    animation: fadeUp 0.9s ease 0.4s both;
  }
  .lg-pill {
    display: inline-flex; align-items: center; gap: 6px;
    background: rgba(99,102,241,0.07);
    border: 1px solid rgba(99,102,241,0.18);
    border-radius: 999px; padding: 5px 13px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.63rem; color: #3D4870; cursor: default;
    transition: border-color 0.2s, background 0.2s;
  }
  .lg-pill:hover { border-color: rgba(99,102,241,0.4); background: rgba(99,102,241,0.12); color: #6878B8; }
  .lg-pill-dot {
    width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0;
  }

  /* ── Warning notice ── */
  .lg-notice {
    display: flex; align-items: flex-start; gap: 10px;
    background: rgba(245,158,11,0.04);
    border: 1px solid rgba(245,158,11,0.13);
    border-radius: 11px; padding: 12px 15px;
    margin-top: 22px;
    font-size: 0.7rem; color: #5A4A20; line-height: 1.65;
    animation: fadeUp 1s ease 0.5s both;
  }

  /* ── Error/success alerts ── */
  [data-testid="stAlertContainer"] {
    border-radius: 10px !important; margin-top: 10px !important;
    animation: fadeUp 0.3s ease both !important;
  }

  /* ── Scrollbar ── */
  ::-webkit-scrollbar { width: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: #1A1F3A; border-radius: 4px; }

  /* ── Reduced motion ── */
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation: none !important; transition: none !important; }
  }
</style>
""", unsafe_allow_html=True)

    # Ambient animated background
    st.markdown("""
<div class="lg-bg">
  <div class="lg-noise"></div>
  <div class="lg-orb lg-orb-a"></div>
  <div class="lg-orb lg-orb-b"></div>
  <div class="lg-orb lg-orb-c"></div>
  <div class="lg-orb lg-orb-d"></div>
</div>
""", unsafe_allow_html=True)

    # JS: force container width + hide header after React hydration
    import streamlit.components.v1 as _components
    _components.html("""
<script>
(function() {
  function applyStyles() {
    var s = document.createElement('style');
    s.innerHTML = `
      .stAppHeader { visibility: hidden !important; height: 0 !important; min-height: 0 !important; overflow: hidden !important; }
      div[data-testid="stMainBlockContainer"] { max-width: 460px !important; margin-left: auto !important; margin-right: auto !important; padding-top: 0 !important; }
    `;
    document.head.appendChild(s);
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', applyStyles); }
  else { applyStyles(); }
  setTimeout(applyStyles, 200);
  setTimeout(applyStyles, 700);
})();
</script>
""", height=0)

    # Hero / branding
    st.markdown("""
<div class="lg-hero">
  <div class="lg-ring-wrap">
    <div class="lg-ring"></div>
    <div class="lg-ring"></div>
    <div class="lg-ring"></div>
    <div class="lg-icon-box">
      <svg xmlns="http://www.w3.org/2000/svg" width="34" height="34" viewBox="0 0 24 24"
           fill="none" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
        <defs>
          <linearGradient id="g1" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#A5B4FC"/>
            <stop offset="100%" stop-color="#67E8F9"/>
          </linearGradient>
        </defs>
        <path stroke="url(#g1)"
          d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25zM6.75 12h.008v.008H6.75V12zm0 3h.008v.008H6.75V15zm0 3h.008v.008H6.75V18z"/>
      </svg>
    </div>
  </div>
  <div class="lg-app-name">Billing Anomaly Audit</div>
  <div class="lg-tagline">Decision Support &nbsp;<em>·</em>&nbsp; Synthetic Data Only</div>
</div>
""", unsafe_allow_html=True)

    # Login form
    with st.form("login_form", clear_on_submit=False):
        username  = st.text_input("Username", placeholder="Enter username")
        password  = st.text_input("Password", type="password", placeholder="••••••••••••")
        submitted = st.form_submit_button("Sign In  →", use_container_width=True, type="primary")

    if submitted:
        if attempt_login(username, password):
            st.rerun()
        else:
            st.error("Invalid username or password.")

    # Demo credentials + disclaimer
    st.markdown("""
<div class="lg-divider">Demo Access</div>
<div class="lg-pill-row">
  <span class="lg-pill"><span class="lg-pill-dot" style="background:#6366F1;"></span>auditor1</span>
  <span class="lg-pill"><span class="lg-pill-dot" style="background:#F59E0B;"></span>supervisor1</span>
  <span class="lg-pill"><span class="lg-pill-dot" style="background:#F43F5E;"></span>admin1</span>
</div>
<div class="lg-notice">
  <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24"
       fill="none" stroke="#D97706" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"
       style="flex-shrink:0;margin-top:2px;">
    <path d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"/>
  </svg>
  <span>Mock authentication only — demo credentials, not suitable for real healthcare data. All providers and claims are entirely fictional.</span>
</div>
""", unsafe_allow_html=True)

    st.stop()   # halt page rendering until login succeeds and st.rerun() fires
