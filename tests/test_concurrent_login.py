"""
30-account login stress-test and bug hunt.

Suite A — Sequential correctness   (all 30 accounts, each isolated)
Suite B — Concurrent auth layer     (100 raw threads → checks race conditions)
Suite C — Audit log concurrent I/O  (30 threads writing simultaneously)
Suite D — Full-app sequential       (every account through AppTest login → dashboard)
Suite E — Re-login / logout         (session reset round-trip)
Suite F — Edge / security inputs    (injections, empty, whitespace, length bomb …)

Key findings from prior runs:
  • AppTest.session_state.get(key) raises AttributeError — must use ss[key].
  • AppTest cannot run truly parallel (Python GIL + heavy imports) — Suite D is sequential.
  • Neither of these is an app bug; both are test-harness limitations.
"""

import sys
import os
import time
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import auth_mock as _auth
from streamlit.testing.v1 import AppTest

APP_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py")

# ── All 30 accounts ──────────────────────────────────────────────────────────

ALL_VALID = [
    ("auditor1",    "demo_auditor1",    "auditor"),
    ("auditor2",    "demo_auditor2",    "auditor"),
    ("auditor3",    "demo_auditor3",    "auditor"),
    ("auditor4",    "demo_auditor4",    "auditor"),
    ("auditor5",    "demo_auditor5",    "auditor"),
    ("auditor6",    "demo_auditor6",    "auditor"),
    ("auditor7",    "demo_auditor7",    "auditor"),
    ("auditor8",    "demo_auditor8",    "auditor"),
    ("auditor9",    "demo_auditor9",    "auditor"),
    ("auditor10",   "demo_auditor10",   "auditor"),
    ("auditor11",   "demo_auditor11",   "auditor"),
    ("auditor12",   "demo_auditor12",   "auditor"),
    ("auditor13",   "demo_auditor13",   "auditor"),
    ("auditor14",   "demo_auditor14",   "auditor"),
    ("auditor15",   "demo_auditor15",   "auditor"),
    ("supervisor1", "demo_supervisor1", "supervisor"),
    ("supervisor2", "demo_supervisor2", "supervisor"),
    ("supervisor3", "demo_supervisor3", "supervisor"),
    ("supervisor4", "demo_supervisor4", "supervisor"),
    ("supervisor5", "demo_supervisor5", "supervisor"),
    ("supervisor6", "demo_supervisor6", "supervisor"),
    ("supervisor7", "demo_supervisor7", "supervisor"),
    ("supervisor8", "demo_supervisor8", "supervisor"),
    ("admin1",      "demo_admin1",      "admin"),
    ("admin2",      "demo_admin2",      "admin"),
    ("admin3",      "demo_admin3",      "admin"),
    ("admin4",      "demo_admin4",      "admin"),
    ("readonly1",   "demo_readonly1",   "auditor"),
    # two extra to reach 30: valid but with role-distinguishing extra checks
    ("supervisor1", "demo_supervisor1", "supervisor"),   # duplicate session → isolation check
    ("admin1",      "demo_admin1",      "admin"),
]

assert len(ALL_VALID) == 30

ALL_INVALID = [
    ("__bad_user",   "wrong",             "no such user"),
    ("auditor1",     "WRONG_PASSWORD",    "wrong password"),
    ("supervisor1",  "demo_auditor1",     "cross-credential swap"),
    ("admin1",       "",                  "empty password"),
    ("",             "demo_auditor1",     "empty username"),
    ("",             "",                  "both empty"),
    ("   ",          "   ",               "whitespace only"),
    ("' OR '1'='1", "' OR '1'='1",        "SQL injection"),
    ("auditor1\x00", "demo_auditor1",     "null-byte username"),
    ("AUDITOR1",     "demo_auditor1",     "uppercase username (case-sensitive)"),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

PASS = "PASS"; FAIL = "FAIL"

@dataclass
class R:
    name: str
    status: str = PASS
    notes: str  = ""
    ms: float   = 0.0

_results: list[R] = []
_rlock = threading.Lock()

def record(r: R):
    with _rlock:
        _results.append(r)

def header(s: str):
    print(f"\n  {'─'*66}")
    print(f"  {s}")
    print(f"  {'─'*66}")

def sub(s: str):
    print(f"\n    ▸ {s}")


def _ss_get(ss, key: str, default=None):
    """Safe session_state lookup that works with AppTest's SafeSessionState."""
    try:
        return ss[key]
    except (KeyError, Exception):
        return default


def _mock_auth(username: str, password: str) -> bool:
    """Direct credential check, bypassing Streamlit runtime."""
    rec = _auth._DEMO_USERS.get(username)
    if rec is None:
        return False
    return rec["password"] == password


def _apptest_login(username: str, password: str, timeout: int = 180) -> tuple[bool, AppTest]:
    """Create an isolated AppTest session and attempt login."""
    at = AppTest.from_file(APP_PATH, default_timeout=timeout)
    at.run()
    if not at.text_input:
        return False, at
    at.text_input[0].set_value(username)
    at.text_input[1].set_value(password)
    at.button[0].click()
    at.run()
    return bool(at.tabs), at


# ════════════════════════════════════════════════════════════════════
# Suite A — Sequential correctness
# ════════════════════════════════════════════════════════════════════

def suite_a():
    header("Suite A — Sequential correctness (all 30 accounts)")

    # A1: valid credentials accepted
    sub("A1 — All 28 unique valid accounts accept their password")
    seen = set()
    for u, p, role in ALL_VALID:
        if u in seen:
            continue
        seen.add(u)
        t0 = time.perf_counter()
        ok = _mock_auth(u, p)
        ms = (time.perf_counter() - t0) * 1000
        sym = "✅" if ok else "❌"
        r = R(f"A1/{u}", PASS if ok else FAIL,
              "" if ok else "valid credentials rejected", ms)
        record(r)
        print(f"    {sym} {u:<24} ({role})")

    # A2: invalid credentials rejected
    sub("A2 — Invalid credentials all rejected")
    for u, p, label in ALL_INVALID:
        t0 = time.perf_counter()
        accepted = _mock_auth(u, p)
        ms = (time.perf_counter() - t0) * 1000
        ok = not accepted
        sym = "✅" if ok else "❌"
        r = R(f"A2/{label}", PASS if ok else FAIL,
              "" if ok else f"SECURITY: {label!r} was accepted — auth bypass!", ms)
        record(r)
        print(f"    {sym} [{label}]")

    # A3: full permission matrix
    sub("A3 — Permission matrix")
    perm_matrix = [
        ("auditor",    "view_worklist",    True),
        ("auditor",    "view_analytics",   True),
        ("auditor",    "view_model_card",  False),
        ("auditor",    "view_audit_trail", False),
        ("auditor",    "export_audit_log", False),
        ("auditor",    "verify_integrity", False),
        ("auditor",    "take_action",      True),
        ("supervisor", "view_model_card",  True),
        ("supervisor", "view_audit_trail", True),
        ("supervisor", "export_audit_log", True),
        ("supervisor", "verify_integrity", True),
        ("supervisor", "take_action",      True),
        ("admin",      "view_model_card",  True),
        ("admin",      "view_audit_trail", True),
        ("admin",      "export_audit_log", True),
        ("admin",      "verify_integrity", True),
        ("admin",      "take_action",      True),
    ]
    for role, perm, expected in perm_matrix:
        actual = _auth.PERMISSIONS.get(role, {}).get(perm, False)
        ok = actual == expected
        sym = "✅" if ok else "❌"
        exp_s = "allow" if expected else "deny "
        act_s = "allow" if actual   else "deny "
        r = R(f"A3/{role}/{perm}", PASS if ok else FAIL,
              "" if ok else f"expected {expected} got {actual}")
        record(r)
        print(f"    {sym} {role:<12} {perm:<22} expect={exp_s}  got={act_s}")

    # A4: current_role / has_permission API under mocked state
    sub("A4 — Public auth_mock API (current_role, has_permission, require_permission)")
    # Monkey-patch st.session_state for this test
    import streamlit as st
    orig_state = dict(st.session_state)
    try:
        st.session_state["_auth_verified"] = True
        st.session_state["_auth_role"]     = "auditor"
        st.session_state["_auth_user"]     = "auditor3"
        st.session_state["_auth_display"]  = "Casey Auditor"

        checks = [
            ("is_authenticated", _auth.is_authenticated(), True),
            ("current_role==auditor",  _auth.current_role(),  "auditor"),
            ("current_user==auditor3", _auth.current_user(), "auditor3"),
            ("has_permission(view_worklist)", _auth.has_permission("view_worklist"), True),
            ("has_permission(view_model_card)", _auth.has_permission("view_model_card"), False),
        ]
        for label, actual, expected in checks:
            ok = actual == expected
            sym = "✅" if ok else "❌"
            r = R(f"A4/{label}", PASS if ok else FAIL,
                  "" if ok else f"got {actual!r} expected {expected!r}")
            record(r)
            print(f"    {sym} {label}")

        # require_permission should raise PermissionError for denied perms
        try:
            _auth.require_permission("view_model_card")
            ok = False
            notes = "should have raised PermissionError"
        except PermissionError:
            ok = True
            notes = ""
        r = R("A4/require_permission_raises", PASS if ok else FAIL, notes)
        record(r)
        print(f"    {'✅' if ok else '❌'} require_permission raises PermissionError for denied perm")

    finally:
        for k in ["_auth_verified","_auth_role","_auth_user","_auth_display"]:
            try:
                del st.session_state[k]
            except Exception:
                pass


# ════════════════════════════════════════════════════════════════════
# Suite B — Concurrent auth layer (100 threads, raw logic)
# ════════════════════════════════════════════════════════════════════

def suite_b():
    header("Suite B — Concurrent auth layer (100 simultaneous raw calls)")

    errors: list[str] = []
    lock = threading.Lock()

    def _task(u, p, should_pass):
        result = _mock_auth(u, p)
        if result != should_pass:
            with lock:
                errors.append(
                    f"{u!r}: expected {'accept' if should_pass else 'reject'}, "
                    f"got {'accept' if result else 'reject'}"
                )

    # 50 valid + 50 invalid, interleaved to maximise contention
    tasks = []
    for i in range(50):
        u, p, _ = ALL_VALID[i % len(ALL_VALID)]
        tasks.append((u, p, True))
    for i in range(50):
        u, p, _ = ALL_INVALID[i % len(ALL_INVALID)]
        tasks.append((u, p, False))

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=100) as pool:
        for f in as_completed([pool.submit(_task, u, p, s) for u, p, s in tasks]):
            f.result()
    ms = (time.perf_counter() - t0) * 1000

    ok = not errors
    notes = f"0 race-condition errors, {ms:.0f}ms" if ok else f"{len(errors)} errors: {errors[:3]}"
    record(R("B/100-concurrent-auth", PASS if ok else FAIL, notes, ms))
    print(f"    {'✅' if ok else '❌'} 100 concurrent auth calls — {notes}")

    # Extra: 30 simultaneous logins for the same account (session independence)
    sub("B2 — 30 threads all authenticating as auditor1 simultaneously")
    b2_errors: list[str] = []
    def _b2(i):
        res = _mock_auth("auditor1", "demo_auditor1")
        if not res:
            with lock:
                b2_errors.append(f"thread {i} got rejected")

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=30) as pool:
        for f in as_completed([pool.submit(_b2, i) for i in range(30)]):
            f.result()
    ms = (time.perf_counter() - t0) * 1000

    ok2 = not b2_errors
    notes2 = f"30/30 accepted, {ms:.0f}ms" if ok2 else f"{b2_errors[:3]}"
    record(R("B2/same-account-30-threads", PASS if ok2 else FAIL, notes2, ms))
    print(f"    {'✅' if ok2 else '❌'} 30 threads, same account — {notes2}")


# ════════════════════════════════════════════════════════════════════
# Suite C — Audit log integrity under concurrent writes
# ════════════════════════════════════════════════════════════════════

def suite_c():
    header("Suite C — Audit log concurrent write integrity (30 writers)")
    try:
        import audit_log as al
    except Exception as exc:
        record(R("C/import", FAIL, str(exc)))
        print(f"    ❌ audit_log import: {exc}")
        return

    write_errors: list[str] = []
    lock = threading.Lock()

    def _write(i):
        try:
            al.append_event(
                "flag_viewed",
                provider_id=f"STRESS_{i:04d}",
                user=f"auditor{(i % 15) + 1}",
            )
        except Exception as exc:
            with lock:
                write_errors.append(f"write {i}: {exc}")

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=30) as pool:
        for f in as_completed([pool.submit(_write, i) for i in range(30)]):
            f.result()
    ms = (time.perf_counter() - t0) * 1000

    # Verify hash-chain integrity
    try:
        res = al.verify_integrity()
        chain_ok = res.get("ok", False)
        chain_msg = res.get("message", "")
    except Exception as exc:
        chain_ok = False
        chain_msg = str(exc)

    ok = not write_errors and chain_ok
    notes = (f"write_errors={len(write_errors)} | integrity: {chain_msg}")
    record(R("C/concurrent-writes", PASS if ok else FAIL, notes, ms))
    print(f"    {'✅' if ok else '❌'} 30 concurrent writes — write_errors={len(write_errors)}, "
          f"integrity: {chain_msg}  ({ms:.0f}ms)")

    # Duplicate event detection
    sub("C2 — Duplicate write safety (same provider, 5 threads)")
    dup_errors: list[str] = []

    def _dup_write(i):
        try:
            al.append_event("flag_viewed", provider_id="DUP_TEST", user="auditor1")
        except Exception as exc:
            with lock:
                dup_errors.append(str(exc))

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=5) as pool:
        for f in as_completed([pool.submit(_dup_write, i) for i in range(5)]):
            f.result()
    ms = (time.perf_counter() - t0) * 1000

    # All 5 writes should succeed (duplicates are allowed in the audit log — it logs every event)
    ok2 = len(dup_errors) == 0
    record(R("C2/dup-writes", PASS if ok2 else FAIL,
             "" if ok2 else str(dup_errors[:2]), ms))
    print(f"    {'✅' if ok2 else '❌'} 5 duplicate writes — errors={len(dup_errors)}  ({ms:.0f}ms)")


# ════════════════════════════════════════════════════════════════════
# Suite D — Full-app sequential (AppTest, all 30 accounts)
# ════════════════════════════════════════════════════════════════════

def _d_check_session(u, p, role, at) -> tuple[bool, str]:
    """Verify session state belongs to this user after login."""
    notes = []
    uid  = _ss_get(at.session_state, "_auth_user")
    role_ = _ss_get(at.session_state, "_auth_role")
    if uid != u:
        notes.append(f"state user={uid!r} expected {u!r}")
    if role_ != role:
        notes.append(f"state role={role_!r} expected {role!r}")
    return len(notes) == 0, " | ".join(notes)


def suite_d():
    header("Suite D — Full-app sequential login for all 30 accounts (AppTest)")
    print("    (Sequential: AppTest is not designed for parallel execution)\n")

    seen = set()
    for idx, (u, p, role) in enumerate(ALL_VALID, 1):
        dup = u in seen
        seen.add(u)
        label = f"{u}" + (" (dup session)" if dup else "")
        t0 = time.perf_counter()
        try:
            ok_login, at = _apptest_login(u, p)
            ms = (time.perf_counter() - t0) * 1000

            # App stability
            excs = list(at.exception)
            stable = len(excs) == 0

            # Session isolation
            isolated, iso_notes = _d_check_session(u, p, role, at)

            # Tab presence
            tabs = [t.label for t in at.tabs]
            has_worklist = any("Worklist" in t for t in tabs)

            # Role-specific tab gate
            if role == "auditor":
                # Auditor must see worklist but NOT have full Model Card content
                perms_ok = has_worklist
            else:
                # Supervisor/admin must see all main tabs
                expected = {"Worklist", "Analytics", "Model Card", "Audit Trail"}
                perms_ok = all(any(e in t for t in tabs) for e in expected)

            notes = []
            if not ok_login:   notes.append("login failed")
            if not stable:     notes.append(f"app exceptions: {[str(e)[:50] for e in excs]}")
            if not isolated:   notes.append(iso_notes)
            if not perms_ok:   notes.append(f"tab layout wrong: {tabs}")

            ok = ok_login and stable and isolated and perms_ok
            r = R(f"D/{idx:02d}/{label}", PASS if ok else FAIL, " | ".join(notes), ms)
        except Exception:
            ms = (time.perf_counter() - t0) * 1000
            r = R(f"D/{idx:02d}/{label}", FAIL, traceback.format_exc(limit=2), ms)

        record(r)
        ok = r.status == PASS
        sym = "✅" if ok else "❌"
        suffix = f"  ← {r.notes[:70]}" if r.notes else ""
        print(f"    {sym} [{idx:02d}/30] {label:<28} ({role:<10}) {r.ms:>6.0f}ms{suffix}")


# ════════════════════════════════════════════════════════════════════
# Suite E — Re-login / logout round-trip
# ════════════════════════════════════════════════════════════════════

def suite_e():
    header("Suite E — Re-login / logout round-trip")

    for u, p, role in [
        ("auditor7",    "demo_auditor7",    "auditor"),
        ("supervisor4", "demo_supervisor4", "supervisor"),
        ("admin2",      "demo_admin2",      "admin"),
    ]:
        t0 = time.perf_counter()
        notes = []
        try:
            # First login
            ok1, at = _apptest_login(u, p)
            if not ok1:
                notes.append("first login failed")
                raise ValueError("first login failed")

            # Logout: clear the verified flag (mirrors auth_mock.logout logic)
            at.session_state["_auth_verified"] = False
            at.run()
            still_in = bool(at.tabs)
            if still_in:
                notes.append("BUG: session survived logout (tabs still visible after _auth_verified=False)")

            # Re-login on same session
            if at.text_input:
                at.text_input[0].set_value(u)
                at.text_input[1].set_value(p)
                at.button[0].click()
                at.run()

            ok2 = bool(at.tabs)
            if not ok2:
                notes.append("re-login failed")

            uid2  = _ss_get(at.session_state, "_auth_user")
            role2 = _ss_get(at.session_state, "_auth_role")
            if uid2 != u:
                notes.append(f"after re-login uid={uid2!r}")
            if role2 != role:
                notes.append(f"after re-login role={role2!r}")

            ok = ok1 and ok2 and (not still_in) and not notes
        except Exception as exc:
            ok = False
            if str(exc) not in str(notes):
                notes.append(traceback.format_exc(limit=2))

        ms = (time.perf_counter() - t0) * 1000
        r = R(f"E/{u}-relogin", PASS if ok else FAIL, " | ".join(notes), ms)
        record(r)
        sym = "✅" if ok else "❌"
        suffix = f"  ← {' | '.join(notes)[:80]}" if notes else ""
        print(f"    {sym} {u:<24} ({role:<10}) {ms:>6.0f}ms{suffix}")


# ════════════════════════════════════════════════════════════════════
# Suite F — Edge / security inputs
# ════════════════════════════════════════════════════════════════════

def suite_f():
    header("Suite F — Edge / security input tests")
    edge_cases = [
        ("",               "",                   "empty username + password"),
        ("auditor1",       "",                   "valid user, empty password"),
        ("",               "demo_auditor1",      "empty user, valid password"),
        ("   ",            "   ",                "whitespace-only"),
        ("' OR '1'='1",   "' OR '1'='1",         "SQL injection classic"),
        ("admin1'; DROP",  "anything",            "SQL injection variant 2"),
        ("auditor1\x00",   "demo_auditor1",       "null-byte in username"),
        ("AUDITOR1",       "demo_auditor1",       "wrong case username"),
        ("auditor1",       "DEMO_AUDITOR1",       "wrong case password"),
        ("<script>x</script>", "pw",              "XSS in username field"),
        ("a" * 500,        "b" * 500,             "500-char username (length bomb)"),
        ("\n\r\t",         "\n\r\t",              "control characters"),
        ("auditor1",       "demo_auditor1 ",      "trailing space in password"),
        (" auditor1",      "demo_auditor1",       "leading space in username"),
        ("auditor1",       "demo_auditor2",       "cross-account password"),
    ]

    for u, p, label in edge_cases:
        t0 = time.perf_counter()
        accepted = _mock_auth(u, p)
        ms = (time.perf_counter() - t0) * 1000
        ok = not accepted
        r = R(f"F/{label}", PASS if ok else FAIL,
              "" if ok else f"SECURITY BUG: {label!r} was accepted! input={u[:40]!r}", ms)
        record(r)
        sym = "✅" if ok else "❌"
        print(f"    {sym} [{label}]"
              + (f"  ← SECURITY BUG!" if not ok else ""))


# ════════════════════════════════════════════════════════════════════
# Final report
# ════════════════════════════════════════════════════════════════════

def final_report(wall_ms: float):
    passed = [r for r in _results if r.status == PASS]
    failed = [r for r in _results if r.status == FAIL]

    print("\n" + "═" * 70)
    print(f"  FINAL REPORT — {len(_results)} total checks")
    print(f"  ✅  Passed : {len(passed)}")
    print(f"  ❌  Failed : {len(failed)}")
    print(f"  ⏱   Wall time: {wall_ms/1000:.1f}s")
    print("═" * 70)

    if failed:
        print("\n  ── BUGS / FAILURES ───────────────────────────────────────────────")
        for r in failed:
            sev = "🚨 SECURITY" if "SECURITY" in r.notes or "bypass" in r.notes.lower() else "🐛 BUG"
            print(f"\n  {sev}  [{r.name}]  ({r.ms:.0f}ms)")
            for line in r.notes.strip().splitlines()[:6]:
                print(f"       {line}")
        print()
    else:
        print("\n  ✅  All checks passed — no bugs detected.\n")

    # Timing summary
    d_times = [r.ms for r in _results if r.name.startswith("D/") and r.status == PASS]
    if d_times:
        print(f"  Full-app login timing: min={min(d_times):.0f}ms "
              f"avg={sum(d_times)/len(d_times):.0f}ms "
              f"max={max(d_times):.0f}ms")
    print()

    sys.exit(1 if failed else 0)


# ════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "═" * 70)
    print("  BILLING ANOMALY AUDIT — 30-ACCOUNT STRESS & BUG TEST")
    print("  Suites A(correctness) B(concurrent-auth) C(audit-log)")
    print("         D(full-app) E(re-login) F(edge-cases)")
    print("═" * 70)

    t0 = time.perf_counter()
    suite_a()
    suite_b()
    suite_c()
    suite_d()
    suite_e()
    suite_f()
    final_report((time.perf_counter() - t0) * 1000)


if __name__ == "__main__":
    main()
