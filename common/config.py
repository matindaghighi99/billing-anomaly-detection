"""config.py — central configuration, storage paths, and production gates.

Twelve-factor: all secrets and storage locations come from the environment, so a
managed secrets vault (Azure Key Vault, AWS Secrets Manager, HashiCorp Vault,
GCP Secret Manager) can inject them at runtime without code changes. Nothing
secret is stored in the repo.

In production (APP_ENV=production) the app validates that the security-critical
settings are present and safe, and fails fast otherwise — so a misconfigured
deployment never silently serves with an ephemeral signing key, MFA off, or the
demo accounts exposed.

Persistent storage paths default to DATA_DIR (point this at a mounted managed
volume / persistent disk so the audit trail and case state survive restarts).
"""

import os

APP_ENV = os.environ.get("APP_ENV", "demo").strip().lower()   # demo | production
IS_PRODUCTION = APP_ENV == "production"

# Durable storage. On a managed host, set DATA_DIR to a persistent disk mount
# (e.g. /data) so SQLite-backed stores are not lost when the container restarts.
DATA_DIR      = os.environ.get("DATA_DIR", ".")
AUDIT_DB_PATH = os.environ.get("AUDIT_DB_PATH", os.path.join(DATA_DIR, "audit_log.db"))
CASE_DB_PATH  = os.environ.get("CASE_DB_PATH",  os.path.join(DATA_DIR, "audit_cases.db"))
CLINICAL_DB_PATH = os.environ.get("CLINICAL_DB_PATH", os.path.join(DATA_DIR, "clinical_reviews.db"))
BACKUP_DIR    = os.environ.get("BACKUP_DIR",    os.path.join(DATA_DIR, "backups"))

# Real adjudicated outcomes (provider_id, outcome[, recovered_amount]) for
# accuracy validation. When present, validation is on REAL labels, not synthetic.
VALIDATION_OUTCOMES_CSV = os.environ.get("VALIDATION_OUTCOMES_CSV",
                                         "adjudicated_outcomes.csv")
# Treat auditor dispositions / outcomes as trusted real labels (off by default,
# since demo dispositions are seeded from the synthetic answer key).
VALIDATION_TRUSTED = os.environ.get("VALIDATION_TRUSTED", "").strip().lower() \
    in ("1", "true", "yes")


def _is_off(name: str, default: str = "") -> bool:
    return os.environ.get(name, default).strip().lower() in ("", "0", "false", "no")


def validate() -> list[str]:
    """Return a list of production-readiness problems (empty list = OK).

    Only enforced when APP_ENV=production; in demo mode this is advisory. The
    checks depend on AUTH_PROVIDER: the built-in password+TOTP path and the
    enterprise SSO path have different security-critical settings.
    """
    problems: list[str] = []
    if not IS_PRODUCTION:
        return problems

    provider = os.environ.get("AUTH_PROVIDER", "mock").strip().lower()

    if provider == "sso":
        # Authentication, MFA, and the user directory are owned by the enterprise
        # IdP, so the local-auth settings do not apply. The CRITICAL app-side
        # requirement is that proxy-header trust is only safe behind the
        # authenticating proxy. SSO_PROXY_SHARED_SECRET is the in-app safeguard
        # that rejects forged identity headers if a request ever bypasses the
        # proxy; without it the app relies SOLELY on network isolation, which it
        # cannot verify — so in production we refuse to start.
        jwt_mode = bool(os.environ.get("SSO_JWT_HEADER"))
        if not jwt_mode and not os.environ.get("SSO_PROXY_SHARED_SECRET"):
            problems.append(
                "AUTH_PROVIDER=sso uses proxy-header trust but "
                "SSO_PROXY_SHARED_SECRET is not set. The app MUST be unreachable "
                "except through the authenticating proxy; the shared secret blocks "
                "forged identity headers if a request bypasses it. Set "
                "SSO_PROXY_SHARED_SECRET (and enforce network isolation), or use "
                "JWT mode (SSO_JWT_HEADER) where signatures are verified in-app.")
        return problems

    # Built-in password + TOTP authentication.
    secret = os.environ.get("SESSION_SECRET", "")
    if not secret:
        problems.append("SESSION_SECRET is not set — sessions would use an "
                        "ephemeral per-process key (forgeable across restarts).")
    elif len(secret) < 32:
        problems.append("SESSION_SECRET is too short (use ≥ 32 random chars).")

    if _is_off("MFA_ENABLED", "1") and os.environ.get("MFA_ENABLED", "1").lower() \
            in ("0", "false", "no"):
        problems.append("MFA_ENABLED is off in production.")

    if _is_off("HIDE_DEMO_CREDS"):
        problems.append("HIDE_DEMO_CREDS is not set — demo credentials and live "
                        "MFA codes would be shown on the login screen.")

    if not os.environ.get("BAAD_USERS_JSON"):
        problems.append("BAAD_USERS_JSON is not set — only the built-in demo "
                        "accounts exist; configure real users.")

    return problems


def enforce() -> list[str]:
    """Raise in production if misconfigured; return the problem list otherwise."""
    problems = validate()
    if IS_PRODUCTION and problems:
        raise RuntimeError(
            "Refusing to start: production configuration errors:\n  - "
            + "\n  - ".join(problems)
        )
    return problems


def summary() -> dict:
    """Non-secret config snapshot for the self-check / admin diagnostics."""
    return {
        "app_env": APP_ENV,
        "production": IS_PRODUCTION,
        "auth_provider": os.environ.get("AUTH_PROVIDER", "mock").strip().lower(),
        "data_dir": DATA_DIR,
        "audit_db": AUDIT_DB_PATH,
        "case_db": CASE_DB_PATH,
        "backup_dir": BACKUP_DIR,
        "mfa_enabled": not _is_off("MFA_ENABLED", "1"),
        "session_secret_set": bool(os.environ.get("SESSION_SECRET")),
        "users_configured": bool(os.environ.get("BAAD_USERS_JSON")),
        "config_problems": validate(),
    }
