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


def configure_logging(level: str | None = None) -> None:
    """Install a JSON stdout formatter once (idempotent)."""
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
            if record.exc_info:
                payload["exc"] = self.formatException(record.exc_info)
            return json.dumps(payload)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, lvl, logging.INFO))
    root._baad_configured = True


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
