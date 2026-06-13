"""observability.py — structured logging + a readiness self-check.

Structured (JSON) logs to stdout are picked up by any managed log drain
(Render log streams, CloudWatch, Azure Monitor, Datadog, …). self_check()
returns a machine-readable health/readiness snapshot for monitoring probes and
the in-app admin diagnostics panel, beyond Streamlit's /_stcore/health.
"""

import json
import logging
import os
import sys
import uuid

# Standard LogRecord attributes — anything else attached via `extra=` is treated
# as a structured field and emitted in the JSON payload.
_STD_LOGRECORD = set(vars(logging.makeLogRecord({})))

# Dedicated logger for the security/audit event stream a SIEM subscribes to.
audit_logger = logging.getLogger("baad.audit")


def configure_logging(level: str | None = None) -> None:
    """Install a JSON stdout formatter once (idempotent).

    Emits one JSON object per line to stdout — the 12-factor convention — so the
    platform's log drain forwards it to a SIEM (Splunk / Microsoft Sentinel /
    ELK). Any keyword passed via `extra=` (actor, action, correlation_id, …)
    appears as a top-level field, so security events are queryable downstream.
    """
    root = logging.getLogger()
    if getattr(root, "_baad_configured", False):
        return
    lvl = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()

    class _JsonFormatter(logging.Formatter):
        def format(self, record):
            payload = {
                "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            }
            # Promote structured `extra=` fields to the top level.
            for k, v in record.__dict__.items():
                if k not in _STD_LOGRECORD and not k.startswith("_"):
                    payload[k] = v
            if record.exc_info:
                payload["exc"] = self.formatException(record.exc_info)
            return json.dumps(payload, default=str)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, lvl, logging.INFO))
    root._baad_configured = True


def correlation_id() -> str:
    """A stable id for the current Streamlit session, for log correlation.

    Ties every event from one user session together in the SIEM. Falls back to
    a fresh uuid when no Streamlit session is available (CLI/tests).
    """
    try:
        import streamlit as st
        cid = st.session_state.get("_correlation_id")
        if not cid:
            cid = uuid.uuid4().hex
            st.session_state["_correlation_id"] = cid
        return cid
    except Exception:
        return uuid.uuid4().hex


def _actor() -> dict:
    """Best-effort identity of the acting user, from the verified session."""
    try:
        import auth_mock
        return {"actor": auth_mock.current_user() or "anonymous",
                "actor_role": auth_mock.current_role() or "none"}
    except Exception:
        return {"actor": "system", "actor_role": "none"}


def action_event(action: str, *, target: str | None = None,
                 outcome: str = "ok", **extra) -> dict:
    """Build the structured payload for a privileged-action audit event."""
    payload = {"event": "user_action", "action": action, "outcome": outcome,
               "correlation_id": correlation_id(), **_actor()}
    if target is not None:
        payload["target"] = target
    payload.update(extra)
    return payload


def log_action(action: str, *, target: str | None = None,
               outcome: str = "ok", **extra) -> dict:
    """Emit a structured audit event (who did what, to what, in which session).

    This is the operational SIEM stream — complementary to the tamper-evident
    hash-chained trail in audit_log.py. Call it from privileged handlers
    (exports, dispositions, stage changes, integrity checks).
    """
    payload = action_event(action, target=target, outcome=outcome, **extra)
    audit_logger.info(action, extra=payload)
    return payload


def self_check() -> dict:
    """Readiness snapshot: data present, stores reachable, audit intact, config OK."""
    checks: dict = {"ok": True, "checks": {}}

    def _set(name, ok, detail=""):
        checks["checks"][name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            checks["ok"] = False

    # Scored worklist present?
    try:
        from dataset_config import out
        scores = out("risk_scores.csv")
        _set("scored_data", os.path.exists(scores), scores)
    except Exception as exc:
        _set("scored_data", False, str(exc))

    # Audit trail reachable + intact?
    try:
        import audit_log
        res = audit_log.verify_integrity()
        _set("audit_integrity", res.get("ok"), res.get("message", ""))
    except Exception as exc:
        _set("audit_integrity", False, str(exc))

    # Case store reachable?
    try:
        import case_management
        case_management._open().close()
        _set("case_store", True, case_management.DB_PATH)
    except Exception as exc:
        _set("case_store", False, str(exc))

    # Fee-schedule provenance / figure defensibility.
    try:
        import fee_schedule as fs
        _set("fee_schedule", True,
             f"{fs.provenance_label()} · figures {fs.figure_status()}")
    except Exception as exc:
        _set("fee_schedule", False, str(exc))

    # Production configuration.
    try:
        import config
        problems = config.validate()
        _set("config", not problems, "; ".join(problems) or "ok")
    except Exception as exc:
        _set("config", False, str(exc))

    return checks


def main():
    configure_logging()
    print(json.dumps(self_check(), indent=2))


if __name__ == "__main__":
    main()
