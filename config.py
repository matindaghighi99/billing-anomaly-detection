"""config.py — Runtime environment and production-readiness preflight.

Centralises the "is this safe to run for real?" checks so the same logic is
used by the app at startup and by CI. The system ships in DEMO mode by default
(synthetic data, built-in credentials). Setting APP_ENV=production turns the
preflight into a hard gate: the app refuses to start while any insecure default
is still in place.

Environment variables consulted:
  APP_ENV                    development (default) | demo | staging | production
  AUTH_USERS_JSON            real credential store (absence ⇒ demo accounts)
  AUTH_PWD_SALT              per-deployment password salt
  MODEL_REGISTRY_HMAC_KEY    HMAC key for model-artifact integrity tags

This module intentionally has NO heavy dependencies so it can be imported and
run in any environment (including CI) without numpy/pandas/streamlit.
"""

import os
import sys

# Values of APP_ENV that mean "treat misconfiguration as fatal".
_PRODUCTION_ENVS = {"production", "prod"}


def app_env() -> str:
    """Normalised deployment environment name."""
    return os.environ.get("APP_ENV", "development").strip().lower()


def is_production() -> bool:
    """True when running in a production-grade environment."""
    return app_env() in _PRODUCTION_ENVS


def production_issues() -> list[str]:
    """Return a list of configuration problems that block a production launch.

    An empty list means every check this module knows about has passed. This is
    NOT a complete production-readiness certification (see PRODUCTION_READINESS.md)
    — it only covers machine-checkable configuration defaults.
    """
    issues: list[str] = []

    # ── Authentication ────────────────────────────────────────────────────────
    # auth_mock imports streamlit; import lazily so config stays dependency-free
    # for callers (e.g. CI) that only need the env helpers.
    try:
        import auth_mock
        if auth_mock.using_demo_credentials():
            issues.append(
                "Auth is using the built-in DEMO credentials. Provide a real "
                "credential store via AUTH_USERS_JSON (and prefer an external IdP)."
            )
        if auth_mock.using_default_salt():
            issues.append(
                "AUTH_PWD_SALT is the shipped default. Set a unique, secret "
                "per-deployment salt."
            )
    except Exception as exc:  # pragma: no cover - defensive
        issues.append(f"Could not evaluate auth configuration: {exc}")

    # ── Model-artifact integrity ──────────────────────────────────────────────
    if not os.environ.get("MODEL_REGISTRY_HMAC_KEY"):
        issues.append(
            "MODEL_REGISTRY_HMAC_KEY is not set. Model artifacts are protected by "
            "a plain SHA-256 tag only, which an attacker who can also rewrite the "
            "registry can forge. Set an HMAC key kept outside the registry dir."
        )

    return issues


def production_preflight() -> list[str]:
    """Raise RuntimeError in production when insecure defaults remain.

    Returns the list of issues (empty when clean). In non-production
    environments issues are returned but not raised, so the demo still runs.
    """
    issues = production_issues()
    if is_production() and issues:
        raise RuntimeError(
            "Refusing to start in production (APP_ENV=" + app_env() + ") due to "
            "insecure configuration:\n  - " + "\n  - ".join(issues)
        )
    return issues


def _main() -> int:
    """CLI entry point: print the environment status. Exit non-zero if a
    production environment has unresolved issues (useful as a deploy gate)."""
    issues = production_issues()
    print(f"APP_ENV         : {app_env()}")
    print(f"Production mode : {is_production()}")
    if not issues:
        print("Preflight       : OK — no insecure configuration defaults detected.")
        return 0
    print("Preflight       : ISSUES")
    for i in issues:
        print(f"  - {i}")
    # Only fail the process when we're actually in a production environment.
    return 1 if is_production() else 0


if __name__ == "__main__":
    sys.exit(_main())
