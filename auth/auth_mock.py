"""
auth_mock.py — Authentication & role-based access control.

Real authentication layer (the filename is kept only for import stability):
  • Passwords  — PBKDF2-HMAC-SHA256 salted hashes, constant-time compare.
  • MFA        — TOTP second factor (RFC 6238) via an authenticator app (pyotp).
  • Sessions   — HMAC server-signed tokens with absolute expiry. The role lives
                 INSIDE the signed payload and is re-verified on every request,
                 so editing client-side session state can no longer escalate
                 privileges (forging a token requires the server SESSION_SECRET).
  • Throttling — lockout after repeated failed logins.

This is NOT yet a full enterprise IdP: there is no SSO/OAuth federation, no
central user directory, and no audited self-service password reset. For real
PHI, federate to the ministry IdP (SAML/OAuth); this layer is designed to sit
behind one. See MOH_ALIGNMENT.md §7.

Configuration (environment variables):
  SESSION_SECRET       HMAC key for signing sessions. REQUIRED in production
                       (an ephemeral per-process key is generated if unset, so
                       sessions reset on restart and cannot be shared).
  SESSION_TTL_SECONDS  Absolute session lifetime (default 28800 = 8h).
  MFA_ENABLED          Enforce the TOTP second factor (default "1"/on).
  BAAD_USERS_JSON      Override the user store (see make_user_record()).
  HIDE_DEMO_CREDS      Hide on-screen demo credentials/codes in production.
  BAAD_MAX_LOGIN_FAILS / BAAD_LOCKOUT_SECONDS   Login throttling.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

import pyotp
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

# Authentication provider: "mock" = built-in password + TOTP (demo); "sso" =
# federate to an enterprise IdP behind a reverse proxy (see auth/sso.py).
_AUTH_PROVIDER = os.environ.get("AUTH_PROVIDER", "mock").strip().lower()

_PBKDF2_ITERATIONS = 200_000

# Login throttling (configurable via env). Enforced in render_login_screen().
_MAX_FAILS = int(os.environ.get("BAAD_MAX_LOGIN_FAILS", "5"))
_LOCKOUT_SECONDS = int(os.environ.get("BAAD_LOCKOUT_SECONDS", "60"))

# Session lifetime and MFA enforcement.
SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", str(8 * 3600)))
MFA_ENABLED = os.environ.get("MFA_ENABLED", "1").strip().lower() \
    not in ("0", "false", "no")

# Hide the on-screen demo-credential hint in production deployments.
_HIDE_DEMO_CREDS = os.environ.get("HIDE_DEMO_CREDS", "").strip().lower() \
    not in ("", "0", "false", "no")

# Server secret for signing session tokens. Set SESSION_SECRET in production so
# sessions survive restarts and cannot be forged; otherwise a random ephemeral
# key is used (sessions reset when the process restarts).
_USING_EPHEMERAL_SECRET = not os.environ.get("SESSION_SECRET")
_SESSION_SECRET = os.environ.get("SESSION_SECRET") or secrets.token_hex(32)
_SECRET_BYTES = _SESSION_SECRET.encode("utf-8")

# Demo accounts. totp_secret is shown on the login screen in demo mode so the
# second factor is usable without enrolling a device; in production it is never
# displayed and real per-user secrets are supplied via BAAD_USERS_JSON.
_DEMO_USERS: dict[str, dict] = {
    "auditor1":    {"salt": "9213dbdab5577b620a9173520e739d58", "hash": "026a3cfd9db5e2d4b14c2429d765331e40601cfc5b03677e19def470745c5638", "totp_secret": "LXJA7BARGWJZKIPEZ7ZOXLPA55DTBDW2", "role": "auditor",    "display": "Alex Auditor"},    # pragma: allowlist secret
    "supervisor1": {"salt": "c6927a10fca0e48f16e3803e9e30bec4", "hash": "f7e9bb242eea2b14caddea63be30a9271a964fef61beaab2d75429c3de19dfb1", "totp_secret": "62WBQBWHFCU5TM3OHADCAW53K7FJXBIP", "role": "supervisor", "display": "Sam Supervisor"},  # pragma: allowlist secret
    "admin1":      {"salt": "7390674ea4874089de59c0ce0299d7b4", "hash": "2f2efdb0fe6f05dba51f3bed5b62f02f7ddf0b17414d9a34684b72e039221136", "totp_secret": "FFEUGF425RD4QYT2IYT2H5EDQGD6TTDG", "role": "admin",      "display": "Admin User"},      # pragma: allowlist secret
}


def _hash_pw(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                               _PBKDF2_ITERATIONS).hex()


def make_user_record(password: str, role: str, display: str) -> str:
    """Return a JSON user record (salt + PBKDF2 hash + TOTP secret) for
    BAAD_USERS_JSON, and print the authenticator enrolment URI to stderr.
    """
    salt = os.urandom(16)
    totp_secret = pyotp.random_base32()
    rec = {"salt": salt.hex(), "hash": _hash_pw(password, salt),
           "totp_secret": totp_secret, "role": role, "display": display}
    return json.dumps(rec)


def provisioning_uri(username: str, totp_secret: str) -> str:
    """otpauth:// URI to enrol a TOTP secret in an authenticator app."""
    return pyotp.TOTP(totp_secret).provisioning_uri(
        name=username, issuer_name="OHIP Billing Audit")


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
        "clinical_review":  False,   # medical-necessity opinion — clinician/supervisor+
    },
    "supervisor": {
        "view_worklist":    True,
        "view_analytics":   True,
        "view_model_card":  True,
        "view_audit_trail": True,
        "take_action":      True,
        "export_audit_log": True,
        "verify_integrity": True,
        "clinical_review":  True,
    },
    "admin": {
        "view_worklist":    True,
        "view_analytics":   True,
        "view_model_card":  True,
        "view_audit_trail": True,
        "take_action":      True,
        "export_audit_log": True,
        "verify_integrity": True,
        "clinical_review":  True,
    },
}

# Single session-state key: a signed, self-describing token. The role/user are
# read ONLY from the verified payload, never from separately-writable keys.
_KEY_TOKEN = "_auth_token"


def _sign(payload: dict) -> str:
    raw  = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    sig  = hmac.new(_SECRET_BYTES, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _verify(token) -> dict | None:
    """Return the payload iff the signature is valid and unexpired, else None."""
    if not isinstance(token, str) or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    expected = hmac.new(_SECRET_BYTES, body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        pad = "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(body + pad))
    except Exception:
        return None
    if int(time.time()) >= int(payload.get("exp", 0)):
        return None
    return payload


def _session() -> dict | None:
    # In production SSO mode the identity comes from the reverse proxy / IdP
    # (see auth/sso.py), resolved fresh from the request on every call. In demo
    # mode it comes from the locally-issued, HMAC-signed session token.
    if _AUTH_PROVIDER == "sso":
        import sso
        return sso.sso_identity()
    return _verify(st.session_state.get(_KEY_TOKEN))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_authenticated() -> bool:
    """True only when the session holds a valid, unexpired signed token."""
    return _session() is not None


def current_role() -> str | None:
    """Role string from the verified session token, or None if not logged in."""
    s = _session()
    return s.get("role") if s else None


def current_user() -> str | None:
    """Username from the verified session token, or None if not logged in."""
    s = _session()
    return s.get("user") if s else None


def current_display_name() -> str:
    """Human-readable display name from the verified token, or 'Unknown'."""
    s = _session()
    return s.get("display", "Unknown") if s else "Unknown"


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


def verify_password(username: str, password: str) -> bool:
    """Constant-time password check. Does NOT establish a session."""
    rec = _USERS.get(username)
    # Always run a PBKDF2 verification — even for unknown usernames against a
    # throwaway salt — so response time does not reveal whether a username
    # exists (mitigates username enumeration via timing).
    if rec is None:
        _hash_pw(password, b"\x00" * 16)  # dummy work
        return False
    return hmac.compare_digest(_hash_pw(password, bytes.fromhex(rec["salt"])),
                               rec["hash"])


def user_requires_mfa(username: str) -> bool:
    """True if MFA is enabled and this user has an enrolled TOTP secret."""
    rec = _USERS.get(username)
    return bool(MFA_ENABLED and rec and rec.get("totp_secret"))


def verify_totp(username: str, code: str) -> bool:
    """Verify a 6-digit TOTP code (±1 step of clock skew)."""
    rec = _USERS.get(username)
    if not rec or not rec.get("totp_secret"):
        return not MFA_ENABLED   # no secret enrolled → only OK when MFA is off
    if not code:
        return False
    return pyotp.TOTP(rec["totp_secret"]).verify(str(code).strip(), valid_window=1)


def _establish_session(username: str) -> None:
    """Issue a signed session token carrying the role (server-trusted)."""
    rec = _USERS[username]
    now = int(time.time())
    token = _sign({
        "user":    username,
        "role":    rec["role"],
        "display": rec["display"],
        "iat":     now,
        "exp":     now + SESSION_TTL_SECONDS,
    })
    st.session_state[_KEY_TOKEN]   = token
    st.session_state["auditor_id"] = username   # used by audit log trail


def login(username: str, password: str, totp_code: str | None = None) -> dict:
    """Full login: password → (TOTP if required) → signed session.

    Returns {"ok": True} on success, otherwise {"ok": False, "error": ...}
    where error is one of: bad_credentials | mfa_required | bad_mfa.
    """
    if not verify_password(username, password):
        return {"ok": False, "error": "bad_credentials"}
    if user_requires_mfa(username):
        if not totp_code:
            return {"ok": False, "error": "mfa_required", "mfa_required": True}
        if not verify_totp(username, totp_code):
            return {"ok": False, "error": "bad_mfa", "mfa_required": True}
    _establish_session(username)
    return {"ok": True}


def attempt_login(username: str, password: str,
                  totp_code: str | None = None) -> bool:
    """Backwards-compatible boolean wrapper around login()."""
    return login(username, password, totp_code).get("ok", False)


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
    """Render the login UI.  Calls st.stop() until access is established.

    In SSO mode the reverse proxy / IdP performs authentication, so reaching
    this screen means the request carried no recognised identity (or the user's
    IdP groups map to no role). We show an access notice instead of a password
    form — there is nothing to type here.
    """
    if _AUTH_PROVIDER == "sso":
        st.error(
            "**Access not established.** This deployment authenticates through "
            "your organisation's single sign-on. You have reached the "
            "application without a recognised identity, or your account is not "
            "assigned an audit role. Contact the system administrator to be "
            "granted access."
        )
        st.stop()
        return

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
        totp_code = ""
        if MFA_ENABLED:
            totp_code = st.text_input(
                "Authenticator code (6 digits)", placeholder="123456",
                max_chars=6, help="Time-based one-time code from your authenticator app.")
        submitted = st.form_submit_button("Sign In  →", use_container_width=True, type="primary")

    if submitted:
        now = time.time()
        lock_until = st.session_state.get("_login_lock_until", 0)
        if now < lock_until:
            st.error(f"Too many failed attempts. Try again in "
                     f"{int(lock_until - now)}s.")
        else:
            result = login(username, password, totp_code)
            if result["ok"]:
                st.session_state.pop("_login_fails", None)
                st.session_state.pop("_login_lock_until", None)
                st.rerun()
            elif result["error"] == "mfa_required":
                st.warning("Enter the 6-digit code from your authenticator app to continue.")
            elif result["error"] == "bad_mfa":
                # A wrong second factor counts toward lockout.
                fails = st.session_state.get("_login_fails", 0) + 1
                st.session_state["_login_fails"] = fails
                st.error("Incorrect authenticator code.")
            else:  # bad_credentials
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

    # Demo credentials (with live MFA codes) — suppressed in production.
    if not _HIDE_DEMO_CREDS and _USERS is _DEMO_USERS:
        pills = []
        for uname, colour in (("auditor1", "#6366F1"), ("supervisor1", "#F59E0B"),
                              ("admin1", "#F43F5E")):
            code = pyotp.TOTP(_DEMO_USERS[uname]["totp_secret"]).now() if MFA_ENABLED else "—"
            pills.append(
                f'<span class="lg-pill"><span class="lg-pill-dot" '
                f'style="background:{colour};"></span>{uname}'
                + (f' &nbsp;<b style="color:#7C8AD6;letter-spacing:1px;">{code}</b>'
                   if MFA_ENABLED else "") + '</span>')
        mfa_note = ("password is the username prefixed with <code>demo_</code> · "
                    "the bold 6-digit code is the live MFA code (refreshes every 30s)"
                    if MFA_ENABLED else
                    "password is the username prefixed with <code>demo_</code>")
        st.markdown(
            '<div class="lg-divider">Demo Access</div>'
            '<div class="lg-pill-row">' + "".join(pills) + '</div>'
            f'<div style="text-align:center;font-size:0.6rem;color:#3D4870;'
            f'margin-top:10px;font-family:JetBrains Mono,monospace;">{mfa_note}</div>',
            unsafe_allow_html=True,
        )

    st.markdown("""
<div class="lg-notice">
  <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24"
       fill="none" stroke="#D97706" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"
       style="flex-shrink:0;margin-top:2px;">
    <path d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"/>
  </svg>
  <span>Demonstration system — synthetic data only. Password + TOTP MFA with
  server-signed sessions; for real PHI, federate to an enterprise IdP (see
  MOH_ALIGNMENT.md §7).</span>
</div>
""", unsafe_allow_html=True)

    st.stop()   # halt page rendering until login succeeds and st.rerun() fires
