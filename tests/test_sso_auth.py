"""tests/test_sso_auth.py — provider-agnostic SSO identity resolution.

Covers header-trust mode, JWT (HS256) mode, IdP-group → role mapping, the
anti-spoofing proxy secret, and the deny paths. resolve_from_headers() is a
pure function over a headers dict, so no Streamlit/proxy is required.
"""

import base64
import hashlib
import hmac
import json
import os
import time
import unittest


def _set_env(**kw):
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _make_hs256_jwt(claims: dict, secret: str) -> str:
    def seg(d):
        raw = json.dumps(d, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")
    header = seg({"alg": "HS256", "typ": "JWT"})
    payload = seg(claims)
    signing_input = f"{header}.{payload}".encode()
    sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{header}.{payload}.{sig_b64}"


class _Base(unittest.TestCase):
    # Keys this suite mutates; cleared between tests for isolation.
    _KEYS = ["SSO_GROUP_ROLE_MAP", "SSO_DEFAULT_ROLE", "SSO_USER_HEADER",
             "SSO_GROUPS_HEADER", "SSO_DISPLAY_HEADER", "SSO_PROXY_SHARED_SECRET",
             "SSO_PROXY_SECRET_HEADER", "SSO_JWT_HEADER", "SSO_JWT_SECRET",
             "SSO_JWT_ISSUER", "SSO_JWT_AUDIENCE", "SSO_GROUPS_SEPARATOR"]

    def setUp(self):
        for k in self._KEYS:
            os.environ.pop(k, None)
        import sso
        self.sso = sso

    def tearDown(self):
        for k in self._KEYS:
            os.environ.pop(k, None)


class HeaderTrustTests(_Base):
    def test_group_maps_to_role(self):
        _set_env(SSO_GROUP_ROLE_MAP=json.dumps({"OHIP-Auditors": "auditor"}))
        ident = self.sso.resolve_from_headers({
            "X-Forwarded-Email": "alex@moh.on.ca",
            "X-Forwarded-Groups": "OHIP-Auditors",
        })
        self.assertEqual(ident["user"], "alex@moh.on.ca")
        self.assertEqual(ident["role"], "auditor")
        self.assertEqual(ident["via"], "proxy-header")

    def test_highest_privilege_group_wins(self):
        _set_env(SSO_GROUP_ROLE_MAP=json.dumps({
            "OHIP-Auditors": "auditor", "OHIP-Admins": "admin"}))
        ident = self.sso.resolve_from_headers({
            "X-Forwarded-Email": "sam@moh.on.ca",
            "X-Forwarded-Groups": "OHIP-Auditors,OHIP-Admins",
        })
        self.assertEqual(ident["role"], "admin")

    def test_unmapped_groups_denied_by_default(self):
        _set_env(SSO_GROUP_ROLE_MAP=json.dumps({"OHIP-Auditors": "auditor"}))
        ident = self.sso.resolve_from_headers({
            "X-Forwarded-Email": "x@moh.on.ca",
            "X-Forwarded-Groups": "SomeOtherGroup",
        })
        self.assertIsNone(ident)

    def test_default_role_applied_when_set(self):
        _set_env(SSO_GROUP_ROLE_MAP=json.dumps({}), SSO_DEFAULT_ROLE="auditor")
        ident = self.sso.resolve_from_headers({"X-Forwarded-Email": "x@moh.on.ca"})
        self.assertEqual(ident["role"], "auditor")

    def test_no_identity_header_returns_none(self):
        _set_env(SSO_DEFAULT_ROLE="auditor")
        self.assertIsNone(self.sso.resolve_from_headers({"X-Other": "y"}))

    def test_case_insensitive_headers(self):
        _set_env(SSO_GROUP_ROLE_MAP=json.dumps({"g": "supervisor"}))
        ident = self.sso.resolve_from_headers({
            "x-forwarded-email": "x@moh.on.ca", "x-forwarded-groups": "g"})
        self.assertEqual(ident["role"], "supervisor")


class ProxySecretTests(_Base):
    def test_missing_secret_rejected(self):
        _set_env(SSO_GROUP_ROLE_MAP=json.dumps({"g": "auditor"}),
                 SSO_PROXY_SHARED_SECRET="topsecret")
        self.assertIsNone(self.sso.resolve_from_headers({
            "X-Forwarded-Email": "x@moh.on.ca", "X-Forwarded-Groups": "g"}))

    def test_correct_secret_accepted(self):
        _set_env(SSO_GROUP_ROLE_MAP=json.dumps({"g": "auditor"}),
                 SSO_PROXY_SHARED_SECRET="topsecret")
        ident = self.sso.resolve_from_headers({
            "X-Forwarded-Email": "x@moh.on.ca", "X-Forwarded-Groups": "g",
            "X-Proxy-Secret": "topsecret"})
        self.assertEqual(ident["role"], "auditor")

    def test_wrong_secret_rejected(self):
        _set_env(SSO_GROUP_ROLE_MAP=json.dumps({"g": "auditor"}),
                 SSO_PROXY_SHARED_SECRET="topsecret")
        self.assertIsNone(self.sso.resolve_from_headers({
            "X-Forwarded-Email": "x@moh.on.ca", "X-Forwarded-Groups": "g",
            "X-Proxy-Secret": "wrong"}))


class JwtTests(_Base):
    def test_valid_hs256_jwt(self):
        _set_env(SSO_JWT_HEADER="Authorization", SSO_JWT_SECRET="shh",
                 SSO_GROUP_ROLE_MAP=json.dumps({"OHIP-Admins": "admin"}))
        tok = _make_hs256_jwt({
            "email": "admin@moh.on.ca", "name": "Admin User",
            "groups": ["OHIP-Admins"], "exp": int(time.time()) + 600}, "shh")
        ident = self.sso.resolve_from_headers({"Authorization": f"Bearer {tok}"})
        self.assertEqual(ident["user"], "admin@moh.on.ca")
        self.assertEqual(ident["role"], "admin")
        self.assertEqual(ident["via"], "jwt")

    def test_bad_signature_rejected(self):
        _set_env(SSO_JWT_HEADER="Authorization", SSO_JWT_SECRET="shh",
                 SSO_GROUP_ROLE_MAP=json.dumps({"OHIP-Admins": "admin"}))
        tok = _make_hs256_jwt({"email": "a@moh.on.ca", "groups": ["OHIP-Admins"],
                               "exp": int(time.time()) + 600}, "WRONG-SECRET")
        self.assertIsNone(self.sso.resolve_from_headers({"Authorization": tok}))

    def test_expired_jwt_rejected(self):
        _set_env(SSO_JWT_HEADER="Authorization", SSO_JWT_SECRET="shh",
                 SSO_GROUP_ROLE_MAP=json.dumps({"OHIP-Admins": "admin"}))
        tok = _make_hs256_jwt({"email": "a@moh.on.ca", "groups": ["OHIP-Admins"],
                               "exp": int(time.time()) - 5}, "shh")
        self.assertIsNone(self.sso.resolve_from_headers({"Authorization": tok}))

    def test_issuer_mismatch_rejected(self):
        _set_env(SSO_JWT_HEADER="Authorization", SSO_JWT_SECRET="shh",
                 SSO_JWT_ISSUER="https://expected",
                 SSO_GROUP_ROLE_MAP=json.dumps({"OHIP-Admins": "admin"}))
        tok = _make_hs256_jwt({"email": "a@moh.on.ca", "iss": "https://evil",
                               "groups": ["OHIP-Admins"],
                               "exp": int(time.time()) + 600}, "shh")
        self.assertIsNone(self.sso.resolve_from_headers({"Authorization": tok}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
