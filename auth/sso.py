"""auth/sso.py — enterprise identity provider (SSO) for production.

Provider-agnostic. Resolves the authenticated user from EITHER:

  (a) Trusted request headers injected by an authenticating reverse proxy
      (oauth2-proxy, Azure App Service "Easy Auth", an API gateway) that has
      already completed the OIDC/SAML flow with the ministry IdP, OR
  (b) A signed JWT (ID/access token) presented in a request header, validated
      here (HS256 with a shared secret out of the box; RS256/JWKS via PyJWT if
      installed).

Selected with AUTH_PROVIDER=sso. In demo mode (the default) this module is
dormant and auth_mock's password + TOTP flow is used instead.

The IdP owns authentication and MFA. This module only:
  1. extracts the verified identity from the request,
  2. maps the IdP group/role claim to one of the app's roles, and
  3. returns a session payload of the SAME shape auth_mock issues,
so the rest of the app — the PERMISSIONS matrix, require_permission(), and the
dashboards — is untouched.

SECURITY — header-trust mode only:
  Trusting X-Forwarded-* headers is safe ONLY when the app is unreachable
  except through the proxy, and the proxy strips any client-supplied copies of
  those headers. As defence in depth, set SSO_PROXY_SHARED_SECRET so a request
  must also carry a secret header that only the proxy knows; requests without
  it are rejected, so a direct connection that bypasses the proxy cannot spoof
  identity.

Configuration (environment variables):
  AUTH_PROVIDER            mock (default) | sso
  # Header-trust mode
  SSO_USER_HEADER          default "X-Forwarded-Email" (falls back to X-Forwarded-User)
  SSO_DISPLAY_HEADER       default "X-Forwarded-Preferred-Username"
  SSO_GROUPS_HEADER        default "X-Forwarded-Groups"
  SSO_GROUPS_SEPARATOR     default ","
  SSO_PROXY_SHARED_SECRET  optional anti-spoofing secret the proxy must send
  SSO_PROXY_SECRET_HEADER  default "X-Proxy-Secret"
  # Role mapping
  SSO_GROUP_ROLE_MAP       JSON {"<idp-group>": "auditor|supervisor|admin", ...}
  SSO_DEFAULT_ROLE         role for an authenticated user whose groups map to
                           nothing (default "" = deny access)
  # JWT mode (used when SSO_JWT_HEADER is set)
  SSO_JWT_HEADER           e.g. "Authorization" or "X-Forwarded-Access-Token"
  SSO_JWT_SECRET           shared secret for HS256 validation
  SSO_JWT_ISSUER           expected "iss" (optional)
  SSO_JWT_AUDIENCE         expected "aud" (optional)
  SSO_JWT_USER_CLAIM       default "email" (falls back to "preferred_username"/"sub")
  SSO_JWT_DISPLAY_CLAIM    default "name"
  SSO_JWT_GROUPS_CLAIM     default "groups"
"""

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Mapping, Optional

# Roles the app understands, in ascending privilege order. Kept local so this
# module has no import cycle with auth_mock.
ROLE_PRIORITY = {"auditor": 1, "supervisor": 2, "admin": 3}
VALID_ROLES = set(ROLE_PRIORITY)

AUTH_PROVIDER = os.environ.get("AUTH_PROVIDER", "mock").strip().lower()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def is_sso() -> bool:
    return AUTH_PROVIDER == "sso"


def _group_role_map() -> dict:
    raw = _env("SSO_GROUP_ROLE_MAP")
    if not raw:
        return {}
    try:
        m = json.loads(raw)
        return {str(k): str(v).strip().lower() for k, v in m.items()}
    except (json.JSONDecodeError, AttributeError):
        return {}


def _highest_role(groups: list[str]) -> Optional[str]:
    """Best (highest-privilege) role among the user's mapped groups."""
    gmap = _group_role_map()
    roles = [gmap[g] for g in groups if g in gmap and gmap[g] in VALID_ROLES]
    if not roles:
        default = _env("SSO_DEFAULT_ROLE").strip().lower()
        return default if default in VALID_ROLES else None
    return max(roles, key=lambda r: ROLE_PRIORITY[r])


# ---------------------------------------------------------------------------
# JWT (HS256 via stdlib; RS256/JWKS via PyJWT when available)
# ---------------------------------------------------------------------------

def _b64url_decode(seg: str) -> bytes:
    return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))


def _decode_jwt_hs256(token: str, secret: str) -> Optional[dict]:
    """Validate an HS256 JWT with stdlib only; return claims or None."""
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
    except ValueError:
        return None
    try:
        header = json.loads(_b64url_decode(header_b64))
    except Exception:
        return None
    if header.get("alg") != "HS256":
        return None
    signing_input = f"{header_b64}.{payload_b64}".encode()
    expected = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    try:
        provided = _b64url_decode(sig_b64)
    except Exception:
        return None
    if not hmac.compare_digest(expected, provided):
        return None
    try:
        return json.loads(_b64url_decode(payload_b64))
    except Exception:
        return None


def _validate_jwt(token: str) -> Optional[dict]:
    """Validate a JWT and return its claims, or None. HS256 via stdlib; other
    algorithms (RS256/JWKS) delegated to PyJWT if it is installed."""
    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    secret = _env("SSO_JWT_SECRET")
    issuer = _env("SSO_JWT_ISSUER")
    audience = _env("SSO_JWT_AUDIENCE")

    claims: Optional[dict] = None
    if secret:
        # Shared-secret HS256 is handled by stdlib and is DEFINITIVE — we never
        # fall through to the optional PyJWT path (which would needlessly import
        # heavy crypto deps just to re-reject an already-invalid token).
        claims = _decode_jwt_hs256(token, secret)
        if claims is None:
            return None
    else:
        # No shared secret configured → RS256/ES256 via JWKS, handled by PyJWT
        # if it is installed. BaseException is caught because a missing native
        # crypto backend can surface as a non-Exception panic.
        try:
            import jwt  # type: ignore
            from jwt import PyJWKClient  # type: ignore
            jwks_url = _env("SSO_JWT_JWKS_URL")
            if not jwks_url:
                return None
            key = PyJWKClient(jwks_url).get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256", "ES256"],
                                audience=audience or None, issuer=issuer or None,
                                options={"verify_aud": bool(audience)})
        except BaseException:
            return None
    if claims is None:
        return None

    # Manual claim checks for the stdlib path.
    now = int(time.time())
    if int(claims.get("exp", 0)) and now >= int(claims["exp"]):
        return None
    if issuer and claims.get("iss") != issuer:
        return None
    if audience:
        aud = claims.get("aud")
        aud_ok = audience == aud or (isinstance(aud, list) and audience in aud)
        if not aud_ok:
            return None
    return claims


def _identity_from_jwt(headers: Mapping[str, str]) -> Optional[dict]:
    header_name = _env("SSO_JWT_HEADER")
    if not header_name:
        return None
    token = _get(headers, header_name)
    if not token:
        return None
    claims = _validate_jwt(token)
    if not claims:
        return None
    user_claim = _env("SSO_JWT_USER_CLAIM", "email")
    user = (claims.get(user_claim) or claims.get("preferred_username")
            or claims.get("email") or claims.get("sub"))
    if not user:
        return None
    display = claims.get(_env("SSO_JWT_DISPLAY_CLAIM", "name")) or user
    groups_claim = claims.get(_env("SSO_JWT_GROUPS_CLAIM", "groups"), [])
    if isinstance(groups_claim, str):
        groups = [g.strip() for g in groups_claim.split(",") if g.strip()]
    else:
        groups = [str(g) for g in (groups_claim or [])]
    role = _highest_role(groups)
    if role is None:
        return None
    return _payload(user, role, display, via="jwt")


# ---------------------------------------------------------------------------
# Header-trust mode
# ---------------------------------------------------------------------------

def _get(headers: Mapping[str, str], name: str) -> Optional[str]:
    """Case-insensitive header lookup."""
    if not name:
        return None
    if name in headers:
        return headers[name]
    lower = name.lower()
    for k, v in headers.items():
        if k.lower() == lower:
            return v
    return None


def _proxy_secret_ok(headers: Mapping[str, str]) -> bool:
    """If a shared proxy secret is configured, the matching header must match."""
    expected = _env("SSO_PROXY_SHARED_SECRET")
    if not expected:
        return True
    provided = _get(headers, _env("SSO_PROXY_SECRET_HEADER", "X-Proxy-Secret"))
    return bool(provided) and hmac.compare_digest(provided, expected)


def _identity_from_headers(headers: Mapping[str, str]) -> Optional[dict]:
    user = (_get(headers, _env("SSO_USER_HEADER", "X-Forwarded-Email"))
            or _get(headers, "X-Forwarded-User"))
    if not user:
        return None
    display = _get(headers, _env("SSO_DISPLAY_HEADER",
                                 "X-Forwarded-Preferred-Username")) or user
    raw_groups = _get(headers, _env("SSO_GROUPS_HEADER", "X-Forwarded-Groups")) or ""
    sep = _env("SSO_GROUPS_SEPARATOR", ",")
    groups = [g.strip() for g in raw_groups.split(sep) if g.strip()]
    role = _highest_role(groups)
    if role is None:
        return None
    return _payload(user, role, display, via="proxy-header")


def _payload(user: str, role: str, display: str, via: str) -> dict:
    now = int(time.time())
    return {"user": user, "role": role, "display": display,
            "iat": now, "exp": now + 300, "via": via}


# ---------------------------------------------------------------------------
# Public resolution API
# ---------------------------------------------------------------------------

def resolve_from_headers(headers: Mapping[str, str]) -> Optional[dict]:
    """Resolve a verified identity from request headers, or None.

    Pure function over a headers mapping (no Streamlit dependency) so it is
    unit-testable. JWT mode takes precedence when SSO_JWT_HEADER is configured;
    otherwise trusted proxy headers are used.
    """
    if headers is None:
        return None
    if not _proxy_secret_ok(headers):
        return None
    if _env("SSO_JWT_HEADER"):
        ident = _identity_from_jwt(headers)
        if ident is not None:
            return ident
    return _identity_from_headers(headers)


def _request_headers() -> Mapping[str, str]:
    """Inbound HTTP headers for the current Streamlit request (best effort)."""
    try:
        import streamlit as st
        return dict(st.context.headers or {})
    except Exception:
        return {}


def sso_identity() -> Optional[dict]:
    """Resolve the current request's identity payload (Streamlit-aware)."""
    return resolve_from_headers(_request_headers())
