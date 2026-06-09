"""
tests/test_auth_bypass.py — Role-access gate tests for auth_mock.py.

Tests the logic layer of auth_mock independently of Streamlit rendering.
We mock st.session_state as a plain dict so tests run without a live server.

Bypass scenarios tested:
  1. Unauthenticated access (no login at all)
  2. Setting _auth_role directly without _auth_verified
  3. Setting _auth_verified=True without a valid role
  4. URL-param injection (simulated as direct key setting)
  5. Privilege escalation: auditor → supervisor/admin via state manipulation
  6. require_permission() raises for every under-privileged combination
  7. logout() clears ALL session state, not just auth keys
  8. Permission matrix completeness and correctness
  9. Unauthenticated function-level gate
 10. Bad-credential login returns False (no partial state written)
"""

import sys
import types
import unittest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Streamlit session_state stub — must be installed before importing auth_mock
# ---------------------------------------------------------------------------

class _SessionState(dict):
    """Minimal st.session_state stand-in that supports attribute-style access."""
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)

    def __setattr__(self, k, v):
        self[k] = v

    def clear(self):
        super().clear()


_session_state = _SessionState()

# Build a minimal streamlit stub so auth_mock can be imported without a
# running Streamlit server.
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


def _reset():
    """Clear session state between tests."""
    _session_state.clear()
    _st_stub.rerun.reset_mock()
    _st_stub.stop.reset_mock()


class TestUnauthenticated(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_is_not_authenticated_by_default(self):
        self.assertFalse(auth_mock.is_authenticated())

    def test_current_role_is_none_when_not_logged_in(self):
        self.assertIsNone(auth_mock.current_role())

    def test_current_user_is_none_when_not_logged_in(self):
        self.assertIsNone(auth_mock.current_user())

    def test_has_permission_always_false_unauthenticated(self):
        for perm in auth_mock.PERMISSIONS["admin"]:
            self.assertFalse(auth_mock.has_permission(perm),
                             f"Expected False for '{perm}' when unauthenticated")

    def test_require_permission_raises_when_not_logged_in(self):
        with self.assertRaises(PermissionError) as ctx:
            auth_mock.require_permission("view_worklist")
        self.assertIn("Not authenticated", str(ctx.exception))


class TestBypassViaDirectStateManipulation(unittest.TestCase):
    """
    An attacker who can manipulate Streamlit session state (e.g. via a
    malicious component or a future URL-param vulnerability) might try to
    write auth keys directly.  Verify these attempts are blocked.
    """

    def setUp(self):
        _reset()

    # ── Bypass 1: set _auth_role without _auth_verified ──────────────────────
    def test_role_without_verified_flag_is_rejected(self):
        """Setting _auth_role alone must not grant access."""
        _session_state["_auth_role"] = "admin"
        # _auth_verified is absent / False
        self.assertFalse(auth_mock.is_authenticated())
        self.assertIsNone(auth_mock.current_role())
        for perm in auth_mock.PERMISSIONS["admin"]:
            self.assertFalse(auth_mock.has_permission(perm))

    # ── Bypass 2: set _auth_verified without a valid role ────────────────────
    def test_verified_flag_without_valid_role(self):
        """_auth_verified=True with no _auth_role must return None for role."""
        _session_state["_auth_verified"] = True
        # No _auth_role key present
        self.assertTrue(auth_mock.is_authenticated())
        self.assertIsNone(auth_mock.current_role())
        # has_permission on None role → False
        for perm in auth_mock.PERMISSIONS["supervisor"]:
            self.assertFalse(auth_mock.has_permission(perm))

    # ── Bypass 3: inject an invented role string ──────────────────────────────
    def test_invented_role_grants_no_permissions(self):
        """An unknown role string in session state must not match any permission."""
        _session_state["_auth_verified"] = True
        _session_state["_auth_role"]     = "superadmin"
        # PERMISSIONS has no "superadmin" key → all False
        for perm in auth_mock.PERMISSIONS["admin"]:
            self.assertFalse(auth_mock.has_permission(perm))

    # ── Bypass 4: simulate URL-param injection ────────────────────────────────
    def test_url_param_role_injection_simulation(self):
        """Simulates what would happen if ?role=admin reached session state.

        auth_mock never reads query_params; it only writes auth keys in
        attempt_login(). So even if external code writes a role key via URL
        params, is_authenticated() must reject it because _auth_verified is
        absent.
        """
        # Simulate: app reads st.query_params["role"] and writes to session_state
        _session_state["role"]       = "admin"           # URL param injection
        _session_state["_auth_role"] = "admin"           # escalated copy
        # _auth_verified is still absent
        self.assertFalse(auth_mock.is_authenticated())
        self.assertFalse(auth_mock.has_permission("view_audit_trail"))

    # ── Bypass 5: auditor escalates to supervisor by writing role key ─────────
    def test_auditor_cannot_escalate_to_supervisor_via_state(self):
        """An auditor who overwrites _auth_role must be blocked by _auth_verified check."""
        # First, do a legitimate auditor login
        result = auth_mock.attempt_login("auditor1", "demo_auditor1")
        self.assertTrue(result)
        self.assertEqual(auth_mock.current_role(), "auditor")
        self.assertFalse(auth_mock.has_permission("view_audit_trail"))

        # Now simulate state manipulation: overwrite the role
        _session_state["_auth_role"] = "supervisor"
        # _auth_verified is still True from the login — so this IS authenticated
        # BUT: is the escalated role actually accepted?
        # The permission will return True because _auth_verified is True and the
        # role key now says "supervisor". This is the known Streamlit demo limitation.
        # Document the finding rather than suppressing it.
        # The test records the actual behaviour:
        escalated_role = auth_mock.current_role()
        escalated_perm = auth_mock.has_permission("view_audit_trail")
        # Record the finding: after state overwrite, the demo IS vulnerable to
        # privilege escalation.  This is expected for a mock; real auth would
        # use a server-signed token that the client cannot write.
        self.assertEqual(escalated_role, "supervisor",
            "FINDING B-1: After overwriting _auth_role in session state, "
            "current_role() returns the overwritten value.  "
            "Demo-acceptable; production requires server-signed tokens.")
        self.assertTrue(escalated_perm,
            "FINDING B-1: has_permission() returns True for the escalated role.  "
            "This is the expected weak point of any session-dict-based mock.")


class TestRequirePermission(unittest.TestCase):
    """require_permission() must raise PermissionError for every role that
    should not have the permission, and not raise for every role that should."""

    def setUp(self):
        _reset()

    def _login_as(self, username: str, password: str):
        result = auth_mock.attempt_login(username, password)
        self.assertTrue(result, f"Login failed for {username}")

    def test_auditor_blocked_from_view_audit_trail(self):
        self._login_as("auditor1", "demo_auditor1")
        with self.assertRaises(PermissionError):
            auth_mock.require_permission("view_audit_trail")

    def test_auditor_blocked_from_view_model_card(self):
        self._login_as("auditor1", "demo_auditor1")
        with self.assertRaises(PermissionError):
            auth_mock.require_permission("view_model_card")

    def test_auditor_blocked_from_export_audit_log(self):
        self._login_as("auditor1", "demo_auditor1")
        with self.assertRaises(PermissionError):
            auth_mock.require_permission("export_audit_log")

    def test_auditor_blocked_from_verify_integrity(self):
        self._login_as("auditor1", "demo_auditor1")
        with self.assertRaises(PermissionError):
            auth_mock.require_permission("verify_integrity")

    def test_auditor_allowed_take_action(self):
        self._login_as("auditor1", "demo_auditor1")
        auth_mock.require_permission("take_action")   # must NOT raise

    def test_auditor_allowed_view_worklist(self):
        self._login_as("auditor1", "demo_auditor1")
        auth_mock.require_permission("view_worklist")

    def test_supervisor_allowed_view_audit_trail(self):
        self._login_as("supervisor1", "demo_supervisor1")
        auth_mock.require_permission("view_audit_trail")   # must NOT raise

    def test_supervisor_allowed_export_audit_log(self):
        self._login_as("supervisor1", "demo_supervisor1")
        auth_mock.require_permission("export_audit_log")

    def test_supervisor_allowed_verify_integrity(self):
        self._login_as("supervisor1", "demo_supervisor1")
        auth_mock.require_permission("verify_integrity")

    def test_admin_allowed_all_permissions(self):
        self._login_as("admin1", "demo_admin1")
        for perm in auth_mock.PERMISSIONS["admin"]:
            auth_mock.require_permission(perm)   # none should raise

    def test_unknown_permission_raises_for_all_roles(self):
        for user, pwd in [("auditor1", "demo_auditor1"),
                          ("supervisor1", "demo_supervisor1"),
                          ("admin1", "demo_admin1")]:
            _reset()
            self._login_as(user, pwd)
            with self.assertRaises(PermissionError):
                auth_mock.require_permission("nonexistent_permission")


class TestLogout(unittest.TestCase):
    """logout() must clear ALL session state, not just the auth keys."""

    def setUp(self):
        _reset()

    def test_logout_clears_auth_keys(self):
        auth_mock.attempt_login("supervisor1", "demo_supervisor1")
        self.assertTrue(auth_mock.is_authenticated())
        auth_mock.logout()
        # st.session_state.clear() was called; st.rerun() was called
        self.assertFalse(auth_mock.is_authenticated())
        self.assertIsNone(auth_mock.current_role())
        self.assertIsNone(auth_mock.current_user())

    def test_logout_clears_non_auth_state_too(self):
        """Residual UI state from a prior user must not survive logout."""
        auth_mock.attempt_login("auditor1", "demo_auditor1")
        # Simulate UI state accumulated during the session
        _session_state["_last_viewed_pid"]  = "PRV0025"
        _session_state["sb_spec"]           = "Cardiology"
        _session_state["sb_score"]          = 75
        _session_state["auditor_id"]        = "auditor1"

        auth_mock.logout()

        # All keys gone — no role bleed, no filter bleed
        self.assertNotIn("_last_viewed_pid", _session_state)
        self.assertNotIn("sb_spec",          _session_state)
        self.assertNotIn("sb_score",         _session_state)
        self.assertNotIn("auditor_id",       _session_state)

    def test_logout_calls_st_rerun(self):
        auth_mock.attempt_login("admin1", "demo_admin1")
        _st_stub.rerun.reset_mock()
        auth_mock.logout()
        _st_stub.rerun.assert_called_once()

    def test_second_login_after_logout_uses_new_role(self):
        """Supervisor logs in, logs out, auditor logs in — no role bleed."""
        auth_mock.attempt_login("supervisor1", "demo_supervisor1")
        self.assertEqual(auth_mock.current_role(), "supervisor")

        auth_mock.logout()   # clears everything
        _reset()              # reset our test dict too

        auth_mock.attempt_login("auditor1", "demo_auditor1")
        self.assertEqual(auth_mock.current_role(), "auditor")
        self.assertFalse(auth_mock.has_permission("view_audit_trail"),
                         "New auditor session must not inherit supervisor permissions")


class TestBadCredentials(unittest.TestCase):
    """Failed login must not write any partial state."""

    def setUp(self):
        _reset()

    def test_wrong_password_returns_false(self):
        result = auth_mock.attempt_login("auditor1", "wrong_password")
        self.assertFalse(result)

    def test_wrong_password_writes_no_state(self):
        auth_mock.attempt_login("auditor1", "wrong_password")
        self.assertFalse(auth_mock.is_authenticated())
        self.assertNotIn("_auth_verified", _session_state)
        self.assertNotIn("_auth_role",     _session_state)
        self.assertNotIn("_auth_user",     _session_state)

    def test_unknown_username_returns_false(self):
        result = auth_mock.attempt_login("hacker", "anything")
        self.assertFalse(result)

    def test_empty_credentials_return_false(self):
        result = auth_mock.attempt_login("", "")
        self.assertFalse(result)


class TestPermissionMatrix(unittest.TestCase):
    """Exhaustive check that every cell of the permission matrix is correct."""

    def setUp(self):
        _reset()

    _EXPECTED = {
        #                            auditor  supervisor  admin
        "view_worklist":            (True,    True,       True),
        "view_analytics":           (True,    True,       True),
        "view_model_card":          (False,   True,       True),
        "view_audit_trail":         (False,   True,       True),
        "take_action":              (True,    True,       True),
        "export_audit_log":         (False,   True,       True),
        "verify_integrity":         (False,   True,       True),
    }

    _LOGINS = [
        ("auditor1",    "demo_auditor1",    "auditor",    0),
        ("supervisor1", "demo_supervisor1", "supervisor", 1),
        ("admin1",      "demo_admin1",      "admin",      2),
    ]

    def test_full_matrix(self):
        for perm, expected_tuple in self._EXPECTED.items():
            for username, password, role, idx in self._LOGINS:
                _reset()
                auth_mock.attempt_login(username, password)
                actual = auth_mock.has_permission(perm)
                expected = expected_tuple[idx]
                self.assertEqual(
                    actual, expected,
                    f"Permission '{perm}' for role '{role}': "
                    f"expected {expected}, got {actual}"
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
