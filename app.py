"""Phase 7 — Streamlit Audit Dashboard.

Single-screen decision-support tool for human billing auditors.
NEVER makes automated decisions — all outputs are for human review only.
"""

import json
import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

SCORES_CSV  = "risk_scores.csv"
RULES_CSV   = "rules_flags.csv"
PEER_CSV    = "peer_flags.csv"
ML_CSV      = "ml_scores.csv"
METRICS_CSV = "provider_metrics.csv"
EXPLS_JSON  = "explanations.json"
CLAIMS_CSV  = "claims.csv"

RISK_THRESHOLD = 5   # minimum risk score to appear in worklist

st.set_page_config(
    page_title="Billing Anomaly Audit Dashboard",
    page_icon=":stethoscope:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Styles ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .banner {
    background: #7B1111; color: white;
    padding: 12px 20px; border-radius: 6px;
    font-weight: 600; font-size: 1.0rem; text-align: center;
    margin-bottom: 18px;
  }
  .metric-card {
    background: #1E1E2E; border: 1px solid #3a3a5a;
    padding: 16px; border-radius: 8px; text-align: center;
  }
  .metric-label { font-size: 0.8rem; color: #aaa; text-transform: uppercase; }
  .metric-value { font-size: 2.0rem; font-weight: 700; color: #E8C547; }
  .signal-chip {
    display: inline-block;
    padding: 2px 8px; border-radius: 4px;
    font-size: 0.75rem; font-weight: 600; margin: 2px;
  }
  .chip-rule { background:#8B0000; color:#fff; }
  .chip-peer { background:#004080; color:#fff; }
  .chip-ml   { background:#005000; color:#fff; }
</style>
""", unsafe_allow_html=True)


# ── Data loaders (cached) ─────────────────────────────────────────────────────

@st.cache_data
def load_scores():
    if not os.path.exists(SCORES_CSV):
        return pd.DataFrame()
    return pd.read_csv(SCORES_CSV, dtype={"provider_id": str})

@st.cache_data
def load_rules():
    if not os.path.exists(RULES_CSV):
        return pd.DataFrame()
    return pd.read_csv(RULES_CSV, dtype={"provider_id": str})

@st.cache_data
def load_peer():
    if not os.path.exists(PEER_CSV):
        return pd.DataFrame()
    return pd.read_csv(PEER_CSV, dtype={"provider_id": str})

@st.cache_data
def load_ml():
    if not os.path.exists(ML_CSV):
        return pd.DataFrame()
    return pd.read_csv(ML_CSV, dtype={"provider_id": str})

@st.cache_data
def load_metrics():
    if not os.path.exists(METRICS_CSV):
        return pd.DataFrame()
    return pd.read_csv(METRICS_CSV, dtype={"provider_id": str})

@st.cache_data
def load_explanations():
    if not os.path.exists(EXPLS_JSON):
        return {}
    with open(EXPLS_JSON) as f:
        return json.load(f)

@st.cache_data
def load_claims_sample():
    if not os.path.exists(CLAIMS_CSV):
        return pd.DataFrame()
    return pd.read_csv(CLAIMS_CSV, parse_dates=["service_date"],
                       dtype={"fee_code": str, "provider_id": str,
                              "patient_id": str})


# ── Chart helpers ─────────────────────────────────────────────────────────────

METRIC_LABELS = {
    "avg_billed":           "Avg Billed ($)",
    "claims_per_day":       "Claims / Day",
    "top_tier_share":       "Top-Tier Code %",
    "services_per_patient": "Services / Patient",
    "avg_minutes":          "Avg Service Min",
}

def peer_comparison_chart(provider_id: str, metrics_df: pd.DataFrame,
                           peer_flags_df: pd.DataFrame):
    """Horizontal bar chart: provider vs peer median for each benchmarked metric."""
    prow = metrics_df[metrics_df["provider_id"] == provider_id]
    if prow.empty:
        return None

    specialty = prow.iloc[0]["specialty"]
    peers     = metrics_df[metrics_df["specialty"] == specialty]
    peer_med  = peers[list(METRIC_LABELS.keys())].median()

    metrics   = list(METRIC_LABELS.keys())
    labels    = [METRIC_LABELS[m] for m in metrics]
    prov_vals = [float(prow.iloc[0].get(m, 0)) for m in metrics]
    med_vals  = [float(peer_med.get(m, 0)) for m in metrics]

    # Normalise to peer median for visual comparison
    ratio = [(p / m if m > 0 else 1.0) for p, m in zip(prov_vals, med_vals)]

    fig = go.Figure()
    colors = ["#E55" if r > 1.5 else "#E8C547" if r > 1.0 else "#4CAF50"
              for r in ratio]
    fig.add_trace(go.Bar(
        x=ratio, y=labels, orientation="h",
        marker_color=colors,
        text=[f"{v:.2f} (med {m:.2f})" for v, m in zip(prov_vals, med_vals)],
        textposition="outside",
        name="Provider / Peer Median",
    ))
    fig.add_vline(x=1.0, line_dash="dash", line_color="white", opacity=0.5)
    fig.update_layout(
        title=f"Provider vs Peer Median  ({specialty})",
        xaxis_title="Ratio to Peer Median (1.0 = peer average)",
        height=280,
        margin=dict(l=10, r=80, t=40, b=30),
        paper_bgcolor="#0E1117",
        plot_bgcolor="#1E1E2E",
        font_color="white",
        showlegend=False,
    )
    return fig


def monthly_claims_chart(provider_id: str, claims_df: pd.DataFrame):
    """Monthly claim count and total billed for this provider."""
    pdata = claims_df[claims_df["provider_id"] == provider_id].copy()
    if pdata.empty:
        return None
    pdata["month"] = pdata["service_date"].dt.to_period("M").astype(str)
    monthly = pdata.groupby("month").agg(
        n_claims=("claim_id", "count"),
        total_billed=("amount_billed", "sum")
    ).reset_index()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=monthly["month"], y=monthly["n_claims"],
        name="Claims", marker_color="#4A90D9",
    ))
    fig.add_trace(go.Scatter(
        x=monthly["month"], y=monthly["total_billed"],
        name="Total Billed ($)", yaxis="y2",
        line=dict(color="#E8C547", width=2),
    ))
    fig.update_layout(
        title="Monthly Billing Volume",
        height=230,
        yaxis=dict(title="Claims"),
        yaxis2=dict(title="Billed ($)", overlaying="y", side="right"),
        margin=dict(l=10, r=60, t=40, b=30),
        paper_bgcolor="#0E1117",
        plot_bgcolor="#1E1E2E",
        font_color="white",
        legend=dict(orientation="h", y=-0.25),
    )
    return fig


# ── Signal badges ─────────────────────────────────────────────────────────────

def signal_badges(pid: str, rules_df, peer_df, ml_df) -> str:
    badges = []
    if not rules_df.empty:
        rules_hit = rules_df[rules_df["provider_id"] == pid]["rule"].unique()
        for r in rules_hit:
            label = r.replace("_", " ").title()
            badges.append(f'<span class="signal-chip chip-rule">{label}</span>')
    if not peer_df.empty:
        n_peer = len(peer_df[peer_df["provider_id"] == pid])
        if n_peer:
            badges.append(f'<span class="signal-chip chip-peer">Peer Outlier ({n_peer} metrics)</span>')
    if not ml_df.empty:
        ml_row = ml_df[ml_df["provider_id"] == pid]
        if not ml_row.empty and ml_row.iloc[0]["ml_is_anomaly"]:
            score = ml_row.iloc[0]["ml_score"]
            badges.append(f'<span class="signal-chip chip-ml">ML Anomaly ({score:.0f}/100)</span>')
    return " ".join(badges) if badges else "<em>No specific signal</em>"


# ── Main app ──────────────────────────────────────────────────────────────────

def main():
    # ── Banner ────────────────────────────────────────────────────────────────
    st.markdown(
        '<div class="banner">&#9888; SYNTHETIC DATA &mdash; '
        'This dashboard is a decision-SUPPORT tool for human auditors. '
        'No automated decisions or penalties are applied. '
        'All data is entirely fictional.</div>',
        unsafe_allow_html=True,
    )

    st.title("Physician Billing Anomaly Detection")
    st.caption("Proactive, dollar-ranked audit worklist  |  "
               "Three detection layers: Rules, Peer Benchmarking, ML Isolation Forest")

    # ── Load data ─────────────────────────────────────────────────────────────
    scores   = load_scores()
    rules    = load_rules()
    peer     = load_peer()
    ml       = load_ml()
    metrics  = load_metrics()
    expls    = load_explanations()
    claims   = load_claims_sample()

    if scores.empty:
        st.error("No scoring data found. Run scoring.py first.")
        return

    worklist = scores[scores["risk_score"] >= RISK_THRESHOLD].copy()

    # ── Summary metrics ───────────────────────────────────────────────────────
    total_exposure  = worklist["estimated_exposure"].sum()
    n_flagged       = len(worklist)

    # "Surfaced by stats/ML only" = no rule flag but has peer or ML signal
    stats_ml_only = worklist[
        (worklist["rules_score"] == 0) &
        ((worklist["peer_score"] > 0) | (worklist["ml_is_anomaly"] == 1))
    ]
    n_proactive = len(stats_ml_only)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">Total Flagged Exposure</div>'
            f'<div class="metric-value">${total_exposure:,.0f}</div></div>',
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">Providers Flagged</div>'
            f'<div class="metric-value">{n_flagged}</div></div>',
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f'<div class="metric-card"><div class="metric-label">Proactive Finds'
            f'<br><small style="font-weight:400">(stats/ML, not complaints)</small></div>'
            f'<div class="metric-value">{n_proactive}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Filters ───────────────────────────────────────────────────────────────
    with st.expander("Filters", expanded=False):
        specs = ["All"] + sorted(worklist["specialty"].unique().tolist())
        sel_spec = st.selectbox("Specialty", specs)
        min_score = st.slider("Minimum risk score", 0, 100, RISK_THRESHOLD, 5)

    if sel_spec != "All":
        worklist = worklist[worklist["specialty"] == sel_spec]
    worklist = worklist[worklist["risk_score"] >= min_score]

    # ── Worklist table ────────────────────────────────────────────────────────
    st.subheader(f"Audit Worklist  ({len(worklist)} providers, ranked by risk x exposure)")

    display_cols = {
        "provider_id":        "Provider ID",
        "provider_name":      "Name",
        "specialty":          "Specialty",
        "risk_score":         "Risk Score",
        "estimated_exposure": "Est. Exposure ($)",
        "top_reason":         "Top Reason",
    }
    table = worklist[list(display_cols.keys())].rename(columns=display_cols).reset_index(drop=True)
    table.index = table.index + 1   # 1-based rank
    st.dataframe(
        table.style
             .background_gradient(subset=["Risk Score"], cmap="YlOrRd")
             .format({"Est. Exposure ($)": "${:,.0f}", "Risk Score": "{:.1f}"}),
        use_container_width=True,
        height=min(600, 40 + len(table) * 35),
    )

    # ── Expandable detail rows ────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Provider Detail View")
    st.caption("Select a provider below to see full evidence, peer comparison, and explanation.")

    pid_options = worklist["provider_id"].tolist()
    name_map    = dict(zip(worklist["provider_id"], worklist["provider_name"]))
    spec_map    = dict(zip(worklist["provider_id"], worklist["specialty"]))
    score_map   = dict(zip(worklist["provider_id"], worklist["risk_score"]))

    selected_pid = st.selectbox(
        "Select provider",
        pid_options,
        format_func=lambda p: f"{p} — {name_map.get(p, '')} ({spec_map.get(p, '')})  |  Score: {score_map.get(p, 0):.0f}",
    )

    if selected_pid:
        _render_provider_detail(
            selected_pid, rules, peer, ml, metrics, expls, claims,
            worklist, score_map,
        )


def _render_provider_detail(pid, rules, peer, ml, metrics, expls, claims,
                             worklist, score_map):
    prow = worklist[worklist["provider_id"] == pid].iloc[0]

    st.markdown(f"### {prow['provider_name']} &nbsp; `{pid}`")
    st.markdown(
        f"**Specialty:** {prow['specialty']} &nbsp;&nbsp; "
        f"**Risk Score:** `{prow['risk_score']:.0f}/100` &nbsp;&nbsp; "
        f"**Estimated Exposure:** `${prow['estimated_exposure']:,.2f}`",
        unsafe_allow_html=True,
    )

    # Signal badges
    st.markdown("**Signals fired:**", unsafe_allow_html=True)
    st.markdown(signal_badges(pid, rules, peer, ml), unsafe_allow_html=True)

    tab1, tab2, tab3, tab4 = st.tabs(
        ["Rule Evidence", "Peer Comparison", "Monthly Volume", "Explanation"]
    )

    # ── Tab 1: Rule Evidence ─────────────────────────────────────────────────
    with tab1:
        rule_rows = rules[rules["provider_id"] == pid] if not rules.empty else pd.DataFrame()
        if rule_rows.empty:
            st.info("No deterministic rule violations found for this provider.")
        else:
            for _, r in rule_rows.iterrows():
                with st.container():
                    st.markdown(
                        f"**Rule:** `{r['rule'].replace('_', ' ').upper()}`  |  "
                        f"**Exposure:** ${r['estimated_exposure']:,.2f}"
                    )
                    st.markdown(f"> {r['evidence']}")

        peer_rows = peer[peer["provider_id"] == pid] if not peer.empty else pd.DataFrame()
        if not peer_rows.empty:
            st.markdown("**Peer-Stat Flags (|z| > 3):**")
            for _, r in peer_rows.sort_values("z_score", key=abs, ascending=False).iterrows():
                direction = "above" if r["z_score"] > 0 else "below"
                st.markdown(
                    f"- **{r['metric']}**: `{r['provider_value']:.2f}` &nbsp; "
                    f"(z = `{r['z_score']:.2f}`, peer median `{r['peer_median']:.2f}`, "
                    f"{abs(r['z_score']):.1f}σ {direction})"
                )

    # ── Tab 2: Peer Comparison Chart ─────────────────────────────────────────
    with tab2:
        if not metrics.empty:
            fig = peer_comparison_chart(pid, metrics, peer)
            if fig:
                st.plotly_chart(fig, use_container_width=True)
                st.caption(
                    "Bars > 1.0 = above peer median; > 1.5 shown in red. "
                    "Values in red indicate metrics that drove peer-stat flags."
                )
        else:
            st.info("Metrics data not found. Run peer_stats.py first.")

    # ── Tab 3: Monthly Volume ─────────────────────────────────────────────────
    with tab3:
        if not claims.empty:
            fig2 = monthly_claims_chart(pid, claims)
            if fig2:
                st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Claims data not found.")

    # ── Tab 4: Explanation ────────────────────────────────────────────────────
    with tab4:
        if pid in expls:
            st.text_area(
                "Audit explanation (template-based; set ANTHROPIC_API_KEY for AI-enriched):",
                value=expls[pid]["explanation"],
                height=280,
                key=f"expl_{pid}",
            )
        else:
            st.info("Explanation not generated for this provider. "
                    "Run explain.py for the top-N providers.")


if __name__ == "__main__":
    main()
