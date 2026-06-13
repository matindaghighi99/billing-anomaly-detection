"""
tests/test_auth_bypass.py — Auth tests for auth_mock.py (real auth model).

Covers password verification, TOTP MFA, HMAC server-signed sessions, and the
privilege-escalation resistance that the signed sessions provide. We mock
st.session_state as a plain dict so tests run without a live Streamlit server.
"""

import base64
import json
import sys
import time
import types
import unittest
from unittest.mock import MagicMock

import pyotp


# ---------------------------------------------------------------------------
# Streamlit session_state stub — installed before importing auth_mock
# ---------------------------------------------------------------------------
class _SessionState(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)

    def __setattr__(self, k, v):
        self[k] = v


_session_state = _SessionState()

_st_stub = types.ModuleType("streamlit")
_st_stub.session_state = _session_state
_st_stub.stop    = MagicMock()
_st_stub.rerun   = MagicMock()
_st_stub.error   = MagicMock()
_st_stub.warning = MagicMock()
_st_stub.markdown = MagicMock()
_st_stub.columns  = MagicMock(return_value=(MagicMock(), MagicMock(), MagicMock()))
_st_stub.form     = MagicMock()
_st_stub.text_input = MagicMock(return_value="")
_st_stub.form_submit_button = MagicMock(return_value=False)

sys.modules["streamlit"] = _st_stub

import auth_mock   # noqa: E402  (must come after stub install)


def _code(user: str) -> str:
    """Current TOTP code for a demo user."""
    return pyotp.TOTP(auth_mock._USERS[user]["totp_secret"]).now()


def _login(user: str, pwd: str) -> dict:
    """Full login with the correct current MFA code."""
    return auth_mock.login(user, pwd, _code(user))


def _reset():
    _session_state.clear()
    _st_stub.rerun.reset_mock()
    _st_stub.stop.reset_mock()


class TestUnauthenticated(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_not_authenticated_by_default(self):
        self.assertFalse(auth_mock.is_authenticated())

    def test_role_user_none_when_logged_out(self):
        self.assertIsNone(auth_mock.current_role())
        self.assertIsNone(auth_mock.current_user())

    def test_has_permission_always_false_unauthenticated(self):
        for perm in auth_mock.PERMISSIONS["admin"]:
            self.assertFalse(auth_mock.has_permission(perm))

    def test_require_permission_raises_when_not_logged_in(self):
        with self.assertRaises(PermissionError):
            auth_mock.require_permission("view_worklist")


class TestPasswordAndMFA(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_verify_password(self):
        self.assertTrue(auth_mock.verify_password("auditor1", "demo_auditor1"))
        self.assertFalse(auth_mock.verify_password("auditor1", "wrong"))
        self.assertFalse(auth_mock.verify_password("ghost", "x"))

    def test_verify_password_does_not_establish_session(self):
        auth_mock.verify_password("auditor1", "demo_auditor1")
        self.assertFalse(auth_mock.is_authenticated())

    def test_password_only_requires_mfa(self):
        res = auth_mock.login("admin1", "demo_admin1")  # no code
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "mfa_required")
        self.assertFalse(auth_mock.is_authenticated())

    def test_wrong_mfa_code_rejected(self):
        res = auth_mock.login("admin1", "demo_admin1", "000000")
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "bad_mfa")
        self.assertFalse(auth_mock.is_authenticated())

    def test_correct_password_and_code_logs_in(self):
        res = _login("admin1", "demo_admin1")
        self.assertTrue(res["ok"])
        self.assertTrue(auth_mock.is_authenticated())
        self.assertEqual(auth_mock.current_role(), "admin")
        self.assertEqual(auth_mock.current_user(), "admin1")

    def test_unknown_user_bad_credentials(self):
        res = auth_mock.login("hacker", "anything", "123456")
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "bad_credentials")


class TestSignedSessionTamperResistance(unittest.TestCase):
    """The role comes only from the HMAC-signed token, so client-side state
    edits and forged/edited tokens cannot escalate privileges."""

    def setUp(self):
        _reset()

    def test_overwriting_session_keys_does_not_escalate(self):
        _login("auditor1", "demo_auditor1")
        self.assertEqual(auth_mock.current_role(), "auditor")
        # Attacker writes the old-style keys directly — must be ignored.
        _session_state["_auth_role"] = "admin"
        _session_state["role"] = "admin"
        _session_state["_auth_verified"] = True
        self.assertEqual(auth_mock.current_role(), "auditor")
        self.assertFalse(auth_mock.has_permission("view_audit_trail"))

    def test_forged_token_rejected(self):
        payload = {"user": "x", "role": "admin", "display": "X",
                   "iat": 0, "exp": 9999999999}
        body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        _session_state["_auth_token"] = body + "." + ("deadbeef" * 8)
        self.assertFalse(auth_mock.is_authenticated())
        self.assertIsNone(auth_mock.current_role())

    def test_edited_payload_with_old_signature_rejected(self):
        _login("auditor1", "demo_auditor1")
        tok = _session_state["_auth_token"]
        body, sig = tok.rsplit(".", 1)
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        payload["role"] = "admin"                      # privilege bump
        new_body = base64.urlsafe_b64encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).decode().rstrip("=")
        _session_state["_auth_token"] = new_body + "." + sig   # stale signature
        self.assertIsNone(auth_mock.current_role())
        self.assertFalse(auth_mock.is_authenticated())

    def test_expired_token_rejected(self):
        now = int(time.time())
        expired = auth_mock._sign({"user": "auditor1", "role": "auditor",
                                   "display": "A", "iat": now - 100, "exp": now - 1})
        _session_state["_auth_token"] = expired
        self.assertFalse(auth_mock.is_authenticated())

    def test_valid_token_accepted(self):
        now = int(time.time())
        good = auth_mock._sign({"user": "auditor1", "role": "auditor",
                                "display": "A", "iat": now, "exp": now + 3600})
        _session_state["_auth_token"] = good
        self.assertTrue(auth_mock.is_authenticated())
        self.assertEqual(auth_mock.current_role(), "auditor")


class TestRequirePermission(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_auditor_blocked_from_supervisor_perms(self):
        _login("auditor1", "demo_auditor1")
        for perm in ("view_audit_trail", "view_model_card",
                     "export_audit_log", "verify_integrity"):
            with self.assertRaises(PermissionError):
                auth_mock.require_permission(perm)

    def test_auditor_allowed_take_action_and_worklist(self):
        _login("auditor1", "demo_auditor1")
        auth_mock.require_permission("take_action")
        auth_mock.require_permission("view_worklist")

    def test_supervisor_allowed_elevated_perms(self):
        _login("supervisor1", "demo_supervisor1")
        for perm in ("view_audit_trail", "export_audit_log", "verify_integrity"):
            auth_mock.require_permission(perm)

    def test_admin_allowed_all(self):
        _login("admin1", "demo_admin1")
        for perm in auth_mock.PERMISSIONS["admin"]:
            auth_mock.require_permission(perm)

    def test_unknown_permission_raises(self):
        _login("admin1", "demo_admin1")
        with self.assertRaises(PermissionError):
            auth_mock.require_permission("nonexistent_permission")


class TestLogout(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_logout_clears_session(self):
        _login("supervisor1", "demo_supervisor1")
        self.assertTrue(auth_mock.is_authenticated())
        auth_mock.logout()
        self.assertFalse(auth_mock.is_authenticated())
        self.assertIsNone(auth_mock.current_role())

    def test_logout_clears_non_auth_state(self):
        _login("auditor1", "demo_auditor1")
        _session_state["sb_spec"] = "Cardiology"
        auth_mock.logout()
        self.assertNotIn("sb_spec", _session_state)
        self.assertNotIn("_auth_token", _session_state)

    def test_no_role_bleed_after_relogin(self):
        _login("supervisor1", "demo_supervisor1")
        self.assertEqual(auth_mock.current_role(), "supervisor")
        auth_mock.logout()
        _reset()
        _login("auditor1", "demo_auditor1")
        self.assertEqual(auth_mock.current_role(), "auditor")
        self.assertFalse(auth_mock.has_permission("view_audit_trail"))


class TestBadCredentials(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_wrong_password_writes_no_session(self):
        res = auth_mock.login("auditor1", "wrong", _code("auditor1"))
        self.assertFalse(res["ok"])
        self.assertFalse(auth_mock.is_authenticated())
        self.assertNotIn("_auth_token", _session_state)

    def test_empty_credentials(self):
        self.assertFalse(auth_mock.login("", "", "").get("ok"))


class TestPermissionMatrix(unittest.TestCase):
    _EXPECTED = {
        "view_worklist":    (True,  True,  True),
        "view_analytics":   (True,  True,  True),
        "view_model_card":  (False, True,  True),
        "view_audit_trail": (False, True,  True),
        "take_action":      (True,  True,  True),
        "export_audit_log": (False, True,  True),
        "verify_integrity": (False, True,  True),
    }
    _LOGINS = [
        ("auditor1",    "demo_auditor1",    0),
        ("supervisor1", "demo_supervisor1", 1),
        ("admin1",      "demo_admin1",      2),
    ]

    def test_full_matrix(self):
        for perm, expected in self._EXPECTED.items():
            for user, pwd, idx in self._LOGINS:
                _reset()
                _login(user, pwd)
                self.assertEqual(auth_mock.has_permission(perm), expected[idx],
                                 f"{perm} for index {idx}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
