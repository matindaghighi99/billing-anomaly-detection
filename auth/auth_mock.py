"""auth_mock.py — DEPRECATED. Superseded by the production `auth` package.

The demo mock (hardcoded plaintext credentials, client-readable role state) has
been replaced by `auth`: Argon2id hashing, TOTP MFA, failed-login lockout, and
signed server-side sessions whose role is resolved from the database — not from
any client-writable key. `app.py` now imports `auth` directly.

This module remains only as a thin re-export so any lingering `import auth_mock`
keeps working. New code should `import auth`.
"""

from auth import (  # noqa: F401
    PERMISSIONS,
    attempt_login,
    current_display_name,
    current_role,
    current_user,
    has_permission,
    is_authenticated,
    logout,
    render_login_screen,
    require_permission,
)
