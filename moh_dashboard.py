"""moh_dashboard.py — OHIP Casebook tab for the Streamlit dashboard.

Surfaces the Ministry of Health post-payment audit workflow inside the app,
driven by the artefacts produced by moh_audit.py:

    moh_recovery_summary.csv   per-physician recovery + recommended pathway
    fraud_evidence.csv         per-(physician, concern) evidence

It renders the four client-facing integration points:
  1. Ministry terminology — "Potential Billing Concern", HIA s.18(8) basis.
  2. Statutorily recoverable amount on the worklist (ranked by it).
  3. A GM's-Opinion-style case file per physician, with one-click export.
  4. A three-stage case-status tracker with the published SLA targets.

All interpolated free-text is HTML-escaped before being passed to
unsafe_allow_html, consistent with the project's security posture.
"""

import html
import os

import pandas as pd
import streamlit as st

from moh_audit import HIA_S18_8, SLA, classify

RECOVERY_CSV = "moh_recovery_summary.csv"
EVIDENCE_CSV = "fraud_evidence.csv"

STAGES = ["Initial Action", "Full Audit Review", "Board Hearing"]
STAGE_SLA = {
    "Initial Action": "Preliminary claims-data review complete. Outcomes: no action, "
                      "billing education, self-correction, or proceed to full audit.",
    "Full Audit Review": (
        f"Records request ({SLA['records_request_months'][0]}–{SLA['records_request_months'][1]} mo) "
        f"→ review ({SLA['records_review_months'][0]}–{SLA['records_review_months'][1]} mo) "
        f"→ GM's Opinion ({SLA['gm_opinion_months'][0]}–{SLA['gm_opinion_months'][1]} mo). "
        f"Physician acknowledgement requested within {SLA['physician_ack_weeks']} weeks."),
    "Board Hearing": "HSARB referral (independent tribunal). Recovery only by order or "
                     "negotiated settlement; appeal to Divisional Court.",
}


# ── Loaders ───────────────────────────────────────────────────────────────────

@st.cache_data
def load_recovery() -> pd.DataFrame:
    if not os.path.exists(RECOVERY_CSV):
        return pd.DataFrame()
    return pd.read_csv(RECOVERY_CSV, dtype={"provider_id": str})


@st.cache_data
def load_evidence() -> pd.DataFrame:
    if not os.path.exists(EVIDENCE_CSV):
        return pd.DataFrame()
    return pd.read_csv(EVIDENCE_CSV, dtype={"provider_id": str})


# ── Case-file export ────────────────────────────────────────────────────────────

def single_case_markdown(row: pd.Series, ev_rows: pd.DataFrame) -> str:
    """Build a GM's-Opinion-style dossier for one physician (download payload)."""
    L = [
        f"# OHIP Provider Audit — Case File: {row['provider_id']}",
        "",
        "> Decision-support, synthetic data. No determination is made here — under "
        "the HIA only the OHIP General Manager forms an Opinion and only the HSARB "
        "can order recovery.",
        "",
        f"- **Physician:** {row['provider_id']}",
        f"- **Specialty:** {row['specialty']}",
        f"- **Stage:** Initial Action complete (preliminary claims-data review).",
        f"- **Recommended next step:** {row['recommended_next_step']}",
        f"- **Potential outcome:** {row['potential_outcome']}",
        f"- **Estimated exposure:** ${row['estimated_exposure']:,.0f}",
        f"- **Statutorily recoverable (HSARB 24-mo / 5-yr cap):** "
        f"${row['statutory_recoverable']:,.0f} "
        f"(window {row['recovery_window_start']} → {row['recovery_window_end']})",
    ]
    if row.get("barred_by_statute", 0):
        L.append(f"- **Barred by statutory limit:** ${row['barred_by_statute']:,.0f}")
    L += ["", "## Potential Billing Concerns", ""]
    for _, f in ev_rows.iterrows():
        cls = classify(f["scheme"])
        hia = "; ".join(f"s.18(8)({k})" for k in cls["hia"])
        L.append(f"### {f['scheme']} — {cls['pbc']}")
        L.append(f"- Evidence: {f['evidence']} "
                 f"(est. ${f['estimated_extra_revenue']:,.0f}, "
                 f"{int(f['support_claims'])} claims/events).")
        L.append(f"- Legal basis: {hia} — {cls['evidence_basis']} evidence"
                 f"{' · medical consult required' if cls['needs_medical_consult'] else ''}.")
        if cls.get("note"):
            L.append(f"- Note: {cls['note']}")
        L.append("")
    return "\n".join(L)


# ── Renderers ───────────────────────────────────────────────────────────────────

def _kpi(icon, label, value, sub):
    return f"""
    <div class="kpi-card">
      <div class="kpi-icon">{icon}</div>
      <div class="kpi-label">{html.escape(label)}</div>
      <div class="kpi-value">{html.escape(value)}</div>
      <div class="kpi-sub">{html.escape(sub)}</div>
    </div>"""


def _stage_tracker(current: str) -> str:
    chips = []
    reached = True
    for i, s in enumerate(STAGES):
        active = (s == current)
        done = STAGES.index(current) > i
        if active:
            bg, col, bd = "rgba(37,99,235,0.18)", "#9DBCFF", "#2563EB"
        elif done:
            bg, col, bd = "rgba(20,140,40,0.16)", "#70DD80", "rgba(20,140,40,0.5)"
        else:
            bg, col, bd = "rgba(120,120,160,0.10)", "#7878A0", "#2D2D4E"
        chips.append(
            f'<span style="padding:6px 14px;border-radius:999px;background:{bg};'
            f'color:{col};border:1px solid {bd};font-size:0.78rem;font-weight:600;">'
            f'{i+1}. {html.escape(s)}</span>')
        if i < len(STAGES) - 1:
            chips.append('<span style="color:#3A3A5A;">→</span>')
    return ('<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;'
            'margin:6px 0 12px;">' + "".join(chips) + "</div>")


def render_ohip_tab(icon):
    """Main entry point. `icon` is app._icon for visual consistency."""
    rec = load_recovery()
    ev = load_evidence()

    st.markdown(
        '<div class="section-title"><span class="section-dot"></span>'
        'OHIP Post-Payment Audit Casebook — Potential Billing Concerns</div>',
        unsafe_allow_html=True,
    )

    if rec.empty:
        st.info(
            "No OHIP casebook found. Generate it with:\n\n"
            "```\npython data_gen_large.py && python fraud_evidence.py && python moh_audit.py\n```"
        )
        return

    st.caption(
        "Aligned to the Ministry of Health *Physician Fee-for-Service Post-Payment "
        "Audit Process*. Findings are framed as Potential Billing Concerns and mapped "
        "to Health Insurance Act s.18(8). Decision-support only — no determinations."
    )

    # ── Portfolio KPIs ─────────────────────────────────────────────────────────
    exposure    = float(rec["estimated_exposure"].sum())
    recoverable = float(rec["statutory_recoverable"].sum())
    barred      = float(rec.get("barred_by_statute", pd.Series([0])).sum())
    c1, c2, c3, c4 = st.columns(4)
    cards = [
        (c1, icon("clipboard-list", 28, "#90B8FF"), "Physicians w/ Concern", str(len(rec)), "≥1 Potential Billing Concern"),
        (c2, icon("banknotes", 28, "#A0D8A0"), "Estimated Exposure", f"${exposure:,.0f}", "billing above cohort baseline"),
        (c3, icon("lock-closed", 28, "#FFB060"), "Statutorily Recoverable", f"${recoverable:,.0f}", "HSARB 24-mo / 5-yr cap applied"),
        (c4, icon("exclamation-triangle", 28, "#FF9090"), "Barred by Statute", f"${barred:,.0f}", "outside recoverable window"),
    ]
    for col, ic, label, value, sub in cards:
        with col:
            st.markdown(_kpi(ic, label, value, sub), unsafe_allow_html=True)

    st.markdown('<div style="height:18px;"></div>', unsafe_allow_html=True)

    # ── Worklist ranked by recoverable ─────────────────────────────────────────
    st.markdown(
        '<div class="section-title"><span class="section-dot"></span>'
        'Audit Worklist — ranked by statutorily recoverable amount</div>',
        unsafe_allow_html=True,
    )
    table = rec.sort_values("statutory_recoverable", ascending=False).copy()
    show = pd.DataFrame({
        "Physician":       table["provider_id"],
        "Specialty":       table["specialty"],
        "Recoverable ($)": table["statutory_recoverable"],
        "Exposure ($)":    table["estimated_exposure"],
        "Concerns":        table["n_concerns"],
        "HIA s.18(8)":     table["hia_circumstances"],
        "Next step":       table["recommended_next_step"],
    }).reset_index(drop=True)
    show.index = show.index + 1
    styled = (show.style
                  .background_gradient(subset=["Recoverable ($)"], cmap="YlOrRd")
                  .format({"Recoverable ($)": "${:,.0f}", "Exposure ($)": "${:,.0f}"}))
    st.dataframe(styled, use_container_width=True,
                 height=min(560, 60 + len(show) * 36))

    # ── Case file ───────────────────────────────────────────────────────────────
    st.markdown(
        '<div class="section-title"><span class="section-dot"></span>'
        "Case File — GM's-Opinion-style dossier</div>",
        unsafe_allow_html=True,
    )

    order = table["provider_id"].tolist()
    pid = st.selectbox(
        "Select physician",
        order,
        format_func=lambda p: (
            f"${_lookup(table, p, 'statutory_recoverable'):,.0f} recoverable — "
            f"{p} ({_lookup(table, p, 'specialty')})"
        ),
        label_visibility="collapsed",
    )
    if not pid:
        return

    row = table[table["provider_id"] == pid].iloc[0]
    ev_rows = ev[ev["provider_id"] == pid] if not ev.empty else pd.DataFrame()

    # three-stage tracker (session-state; honest demo of the workflow)
    skey = f"moh_stage_{pid}"
    current = st.session_state.get(skey, STAGES[0])
    st.markdown(_stage_tracker(current), unsafe_allow_html=True)
    cset, cinfo = st.columns([1, 3])
    with cset:
        new_stage = st.selectbox("Case stage", STAGES, index=STAGES.index(current),
                                 key=f"sel_{skey}")
        st.session_state[skey] = new_stage
    with cinfo:
        st.caption(STAGE_SLA[new_stage] +
                   f"  ·  Ministry target: entire audit < {SLA['total_target_months']} months.")

    # header card
    barred_line = (f'<span class="prov-stat"><div class="prov-stat-label">Barred by statute</div>'
                   f'<div class="prov-stat-value">${row["barred_by_statute"]:,.0f}</div></span>'
                   if row.get("barred_by_statute", 0) else "")
    st.markdown(f"""
    <div class="prov-header">
      <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:12px;">
        <div>
          <div class="prov-name">{html.escape(str(pid))}</div>
          <div class="prov-pid">{html.escape(str(row['specialty']))} · {int(row['n_concerns'])} Potential Billing Concern(s)</div>
        </div>
        <span class="conf-pill conf-HIGH">${row['statutory_recoverable']:,.0f} RECOVERABLE</span>
      </div>
      <div class="prov-stats">
        <div class="prov-stat"><div class="prov-stat-label">Estimated Exposure</div>
          <div class="prov-stat-value">${row['estimated_exposure']:,.0f}</div></div>
        <div class="prov-stat"><div class="prov-stat-label">Recovery Window</div>
          <div class="prov-stat-value" style="font-size:0.9rem;">{html.escape(str(row['recovery_window_start']))} → {html.escape(str(row['recovery_window_end']))}</div></div>
        <div class="prov-stat"><div class="prov-stat-label">HIA s.18(8)</div>
          <div class="prov-stat-value">{html.escape(str(row['hia_circumstances']))}</div></div>
        {barred_line}
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"**Recommended next step:** {html.escape(str(row['recommended_next_step']))}")
    st.markdown(f"**Potential outcome:** {html.escape(str(row['potential_outcome']))}")
    if bool(row.get("needs_medical_consult", False)):
        st.markdown('<span class="signal-chip chip-temporal">Medical consultant review required '
                    '(HIA s.18(8)(e))</span>', unsafe_allow_html=True)

    # concern evidence cards
    st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)
    st.markdown("**Potential Billing Concerns & evidence:**")
    if ev_rows.empty:
        st.info("No itemised evidence rows found for this physician.")
    else:
        for _, f in ev_rows.sort_values("estimated_extra_revenue", ascending=False).iterrows():
            cls = classify(f["scheme"])
            hia = "; ".join(f"s.18(8)({k})" for k in cls["hia"])
            consult = " · medical consult required" if cls["needs_medical_consult"] else ""
            st.markdown(f"""
            <div class="ev-card ev-rule">
              <span class="ev-rule-label">{html.escape(f['scheme'])}</span>
              <span class="ev-exposure">${f['estimated_extra_revenue']:,.0f}</span>
              <div class="ev-text">{html.escape(str(f['evidence']))}</div>
              <div class="ev-text" style="color:#8AA0C8;">
                {html.escape(cls['pbc'])} · {html.escape(hia)} · {html.escape(cls['evidence_basis'])} evidence{html.escape(consult)}
              </div>
            </div>
            """, unsafe_allow_html=True)

    # records-to-request hint (Stage 2)
    if bool(row.get("needs_medical_consult", False)) or "Full Audit" in str(row["recommended_next_step"]):
        st.caption(
            "Records to request (Stage 2): medical records for the flagged service "
            "dates to confirm services rendered, complexity, medical necessity and "
            f"documentation per s.17.4. Physician acknowledgement within "
            f"{SLA['physician_ack_weeks']} weeks.")

    # one-click export
    md = single_case_markdown(row, ev_rows)
    st.download_button(
        "Export case file (Markdown)",
        data=md,
        file_name=f"OHIP_case_{pid}.md",
        mime="text/markdown",
        icon=":material/download:",
        use_container_width=False,
    )


def _lookup(df: pd.DataFrame, pid: str, col: str):
    r = df[df["provider_id"] == pid]
    return r.iloc[0][col] if not r.empty else ""
