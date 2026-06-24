"""ux.py — user-facing observability for the dashboard.

The backend already emits structured logs (observability.py). This module is the
*visible* half: it turns failures and slow steps into calm, useful messages for
the auditor instead of raw Streamlit tracebacks, and surfaces a health panel.

  • error_boundary()  wrap the whole page; on an unexpected error show a short
    message with a correlation id (also logged) instead of a red traceback.
  • timed()           wrap a slow step: spinner + duration log + friendly error,
    with a note when it runs longer than expected.
  • diagnostics()     admin-only expander backed by observability.self_check().
"""

from __future__ import annotations

import contextlib
import time
import uuid

import streamlit as st

try:
    import observability as _obs
except Exception:        # observability is optional; degrade gracefully
    _obs = None


def _is_control_flow(exc: BaseException) -> bool:
    """Streamlit's rerun/stop signals are control flow, not errors."""
    return type(exc).__name__ in {"RerunException", "StopException", "RerunData"}


def _log(action: str, **fields) -> None:
    if _obs is not None and hasattr(_obs, "log_action"):
        try:
            _obs.log_action(action, **fields)
        except Exception:
            pass


@contextlib.contextmanager
def error_boundary(area: str = "page"):
    """Catch unexpected errors anywhere inside and show a calm message."""
    try:
        yield
    except BaseException as exc:           # noqa: BLE001 - deliberate boundary
        if _is_control_flow(exc):
            raise
        cid = uuid.uuid4().hex[:8]
        _log("ui_error", target=area, outcome="error",
             error=type(exc).__name__, correlation_id=cid)
        st.error(
            "Something went wrong while loading this view, and it has been "
            f"logged. If it keeps happening, quote reference **{cid}**.",
            icon="⚠️",
        )
        st.stop()


@contextlib.contextmanager
def timed(label: str, *, slow_after: float = 4.0, area: str = ""):
    """Spinner + timing + friendly error around a slow step (errors swallowed)."""
    t0 = time.perf_counter()
    ok = True
    try:
        with st.spinner(f"{label}…"):
            yield
    except BaseException as exc:           # noqa: BLE001
        if _is_control_flow(exc):
            raise
        ok = False
        cid = uuid.uuid4().hex[:8]
        _log("op_error", target=area or label, outcome="error",
             error=type(exc).__name__, correlation_id=cid)
        st.error(f"“{label}” couldn’t complete (ref {cid}). "
                 "Please retry, or use Clear Cache & Reload.", icon="⚠️")
    finally:
        dt_ms = round((time.perf_counter() - t0) * 1000)
        _log("op_timing", target=area or label,
             outcome="ok" if ok else "error", duration_ms=dt_ms)
        if ok and dt_ms > slow_after * 1000:
            st.caption(f"⏳ “{label}” took {dt_ms/1000:.1f}s — longer than usual.")


def diagnostics() -> None:
    """Admin-only system-health panel backed by observability.self_check()."""
    if _obs is None or not hasattr(_obs, "self_check"):
        return
    with st.expander("🩺 System status (diagnostics)", expanded=False):
        try:
            chk = _obs.self_check()
        except Exception as exc:           # noqa: BLE001
            st.warning(f"Diagnostics unavailable: {exc}")
            return
        overall = chk.get("ok", False)
        st.markdown(f"**Overall:** {'🟢 Healthy' if overall else '🔴 Attention needed'}")
        for name, c in (chk.get("checks") or {}).items():
            mark = "🟢" if c.get("ok") else "🔴"
            detail = c.get("detail", "")
            st.markdown(f"{mark} **{name}** — <span style='color:#6A78A8'>{detail}</span>",
                        unsafe_allow_html=True)
