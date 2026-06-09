"""Phase 7 — Streamlit Audit Dashboard (Enhanced UI).

Single-screen decision-support tool for human billing auditors.
NEVER makes automated decisions — all outputs are for human review only.
"""

import json
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

SCORES_CSV  = "risk_scores.csv"
RULES_CSV   = "rules_flags.csv"
PEER_CSV    = "peer_flags.csv"
ML_CSV      = "ml_scores.csv"
METRICS_CSV = "provider_metrics.csv"
EXPLS_JSON  = "explanations.json"
CLAIMS_CSV  = "claims.csv"
SHAP_CSV    = "shap_explanations.csv"

RISK_THRESHOLD = 10

CONF_COLOR = {"HIGH": "#FF6B6B", "MEDIUM": "#FFD93D", "LOW": "#6BCB77"}
CONF_BG    = {"HIGH": "rgba(180,20,20,0.18)", "MEDIUM": "rgba(180,150,0,0.18)", "LOW": "rgba(20,140,20,0.18)"}

st.set_page_config(
    page_title="Billing Anomaly Audit Dashboard",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* ── base ── */
  html, body, [class*="css"] { font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; }

  /* ── warning banner ── */
  .banner {
    background: linear-gradient(90deg, #7B1111 0%, #9B2525 100%);
    color: #FFD0D0; padding: 10px 20px; border-radius: 8px;
    font-weight: 600; font-size: 0.88rem; text-align: center;
    margin-bottom: 4px; border-left: 4px solid #FF4444;
    letter-spacing: 0.2px;
  }

  /* ── KPI cards ── */
  .kpi-card {
    background: linear-gradient(135deg, #1A1A2E 0%, #16213E 100%);
    border: 1px solid #2D2D4E; border-radius: 12px;
    padding: 22px 24px; position: relative; overflow: hidden;
    transition: border-color 0.2s;
  }
  .kpi-card:hover { border-color: #4A4A7A; }
  .kpi-accent {
    position: absolute; top: 0; left: 0;
    width: 4px; height: 100%;
  }
  .kpi-icon { font-size: 1.5rem; margin-bottom: 10px; opacity: 0.85; }
  .kpi-label {
    font-size: 0.7rem; color: #7878A8; text-transform: uppercase;
    letter-spacing: 1.2px; margin-bottom: 8px; font-weight: 500;
  }
  .kpi-value { font-size: 2.1rem; font-weight: 700; color: #E8E8FF; line-height: 1.1; }
  .kpi-sub   { font-size: 0.73rem; color: #5A5A8A; margin-top: 8px; }

  /* ── section headings ── */
  .section-title {
    font-size: 1.0rem; font-weight: 600; color: #B0B0D8;
    padding-bottom: 10px; margin: 28px 0 16px;
    border-bottom: 1px solid #2D2D4E;
    display: flex; align-items: center; gap: 8px;
  }
  .section-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: #5A5AFF; display: inline-block; flex-shrink: 0;
  }

  /* ── signal chips ── */
  .signal-chip {
    display: inline-block; padding: 3px 10px; border-radius: 20px;
    font-size: 0.71rem; font-weight: 600; margin: 2px 2px 4px;
    letter-spacing: 0.2px;
  }
  .chip-rule     { background: rgba(200,30,30,0.2);  color: #FF8080; border: 1px solid rgba(200,30,30,0.4); }
  .chip-peer     { background: rgba(30,100,200,0.2); color: #80AAFF; border: 1px solid rgba(30,100,200,0.4); }
  .chip-ml       { background: rgba(0,140,80,0.2);   color: #60DDA0; border: 1px solid rgba(0,140,80,0.4); }
  .chip-temporal { background: rgba(200,110,0,0.2);  color: #FFAA55; border: 1px solid rgba(200,110,0,0.4); }
  .chip-feedback { background: rgba(120,0,200,0.2);  color: #CC88FF; border: 1px solid rgba(120,0,200,0.4); }

  /* ── confidence pill ── */
  .conf-pill {
    display: inline-block; padding: 2px 10px; border-radius: 20px;
    font-size: 0.78rem; font-weight: 700;
  }
  .conf-HIGH   { background: rgba(180,20,20,0.25);  color: #FF7070; border: 1px solid rgba(180,20,20,0.5); }
  .conf-MEDIUM { background: rgba(180,150,0,0.25);  color: #FFD040; border: 1px solid rgba(180,150,0,0.5); }
  .conf-LOW    { background: rgba(20,140,40,0.25);  color: #70DD80; border: 1px solid rgba(20,140,40,0.5); }

  /* ── provider header card ── */
  .prov-header {
    background: linear-gradient(135deg, #14142A 0%, #1C1C38 100%);
    border: 1px solid #32325A; border-radius: 12px;
    padding: 22px 26px; margin-bottom: 18px;
  }
  .prov-name { font-size: 1.45rem; font-weight: 700; color: #E0E0FF; }
  .prov-pid  { font-size: 0.82rem; color: #6A6A9A; margin-top: 2px; font-family: monospace; }
  .prov-stats {
    display: flex; gap: 0; margin-top: 18px;
    border-top: 1px solid #2A2A4A; padding-top: 16px; flex-wrap: wrap;
  }
  .prov-stat { flex: 1; min-width: 110px; padding: 0 20px 0 0; }
  .prov-stat + .prov-stat { border-left: 1px solid #2A2A4A; padding-left: 20px; }
  .prov-stat-label { font-size: 0.68rem; color: #6A6A9A; text-transform: uppercase; letter-spacing: 0.9px; }
  .prov-stat-value { font-size: 1.12rem; font-weight: 600; color: #D0D0F0; margin-top: 3px; }

  /* ── evidence cards ── */
  .ev-card {
    background: #13131F; border-left: 3px solid;
    border-radius: 0 8px 8px 0; padding: 12px 16px; margin-bottom: 10px;
  }
  .ev-rule    { border-color: #C83232; }
  .ev-peer    { border-color: #2050C8; }
  .ev-rule-label { font-size: 0.75rem; font-weight: 700; color: #FF7070; text-transform: uppercase; letter-spacing: 0.6px; }
  .ev-peer-label { font-size: 0.75rem; font-weight: 700; color: #6A9FFF; text-transform: uppercase; letter-spacing: 0.6px; }
  .ev-exposure { font-size: 0.78rem; color: #E8C547; font-weight: 600; float: right; }
  .ev-text    { font-size: 0.86rem; color: #AAAAC0; margin-top: 6px; line-height: 1.5; }

  /* ── sidebar accent ── */
  [data-testid="stSidebar"] {
    background: #0D0D1A;
    border-right: 1px solid #1E1E36;
  }

  /* ── scrollbar ── */
  ::-webkit-scrollbar       { width: 5px; height: 5px; }
  ::-webkit-scrollbar-track { background: #0E1117; }
  ::-webkit-scrollbar-thumb { background: #2A2A4A; border-radius: 3px; }
  ::-webkit-scrollbar-thumb:hover { background: #3A3A6A; }
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
def load_shap_explanations():
    if not os.path.exists(SHAP_CSV):
        return pd.DataFrame()
    return pd.read_csv(SHAP_CSV, dtype={"provider_id": str})

@st.cache_data
def load_claims_sample():
    if not os.path.exists(CLAIMS_CSV):
        return pd.DataFrame()
    return pd.read_csv(CLAIMS_CSV, parse_dates=["service_date"],
                       dtype={"fee_code": str, "provider_id": str, "patient_id": str})


# ── Chart helpers ─────────────────────────────────────────────────────────────

METRIC_LABELS = {
    "avg_billed":           "Avg Billed ($)",
    "claims_per_day":       "Claims / Day",
    "top_tier_share":       "Top-Tier Code %",
    "services_per_patient": "Services / Patient",
    "avg_minutes":          "Avg Service Min",
}

_CHART_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="#13131F",
    font=dict(color="#AAAAC0", size=12),
    margin=dict(l=10, r=10, t=40, b=30),
)


def peer_comparison_chart(provider_id: str, metrics_df: pd.DataFrame,
                           peer_flags_df: pd.DataFrame):
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
    ratio     = [(p / m if m > 0 else 1.0) for p, m in zip(prov_vals, med_vals)]

    colors = ["#FF6B6B" if r > 1.5 else "#FFD93D" if r > 1.0 else "#6BCB77" for r in ratio]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=ratio, y=labels, orientation="h",
        marker=dict(color=colors, line=dict(color="rgba(255,255,255,0.05)", width=0.5)),
        text=[f"{v:.2f} (peer {m:.2f})" for v, m in zip(prov_vals, med_vals)],
        textposition="outside",
        textfont=dict(size=11, color="#AAAAC0"),
        hovertemplate="%{y}: %{x:.2f}x peer median<extra></extra>",
    ))
    fig.add_vline(x=1.0, line_dash="dot", line_color="rgba(255,255,255,0.3)")
    fig.update_layout(
        **_CHART_LAYOUT,
        title=dict(text=f"<b>{specialty}</b> — Provider vs Peer Median", font=dict(size=13)),
        xaxis=dict(
            title="Ratio to Peer Median", gridcolor="#1E1E36",
            zerolinecolor="#2A2A4A",
        ),
        yaxis=dict(gridcolor="#1E1E36"),
        height=300,
        margin=dict(l=10, r=100, t=44, b=30),
        showlegend=False,
    )
    return fig


def monthly_claims_chart(provider_id: str, claims_df: pd.DataFrame):
    pdata = claims_df[claims_df["provider_id"] == provider_id].copy()
    if pdata.empty:
        return None
    pdata["month"] = pdata["service_date"].dt.to_period("M").astype(str)
    monthly = pdata.groupby("month").agg(
        n_claims=("claim_id", "count"),
        total_billed=("amount_billed", "sum"),
    ).reset_index()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=monthly["month"], y=monthly["n_claims"],
        name="Claims",
        marker=dict(color="#4A90D9", opacity=0.85),
        hovertemplate="%{x}: %{y} claims<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=monthly["month"], y=monthly["total_billed"],
        name="Total Billed ($)", yaxis="y2",
        line=dict(color="#E8C547", width=2.5),
        mode="lines+markers",
        marker=dict(size=5),
        hovertemplate="%{x}: $%{y:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        **_CHART_LAYOUT,
        title=dict(text="<b>Monthly Billing Volume</b>", font=dict(size=13)),
        height=260,
        xaxis=dict(gridcolor="#1E1E36"),
        yaxis=dict(title="Claims", gridcolor="#1E1E36"),
        yaxis2=dict(title="Billed ($)", overlaying="y", side="right"),
        margin=dict(l=10, r=70, t=44, b=30),
        legend=dict(orientation="h", y=-0.25, font=dict(size=11)),
    )
    return fig


def risk_gauge(score: float, confidence: str) -> go.Figure:
    color = CONF_COLOR.get(confidence, "#E8C547")
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        number=dict(suffix="/100", font=dict(size=28, color=color)),
        gauge=dict(
            axis=dict(range=[0, 100], tickfont=dict(size=10, color="#7070A0"),
                      tickvals=[0, 25, 50, 75, 100]),
            bar=dict(color=color, thickness=0.25),
            bgcolor="rgba(0,0,0,0)",
            bordercolor="rgba(0,0,0,0)",
            steps=[
                dict(range=[0, 33],  color="#0D0D20"),
                dict(range=[33, 66], color="#12122A"),
                dict(range=[66, 100], color="#18183A"),
            ],
            threshold=dict(
                line=dict(color="white", width=2),
                thickness=0.8, value=score,
            ),
        ),
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#AAAAC0"),
        height=160,
        margin=dict(l=10, r=10, t=10, b=10),
    )
    return fig


def exposure_by_specialty_chart(worklist: pd.DataFrame) -> go.Figure:
    grp = (worklist.groupby("specialty")["estimated_exposure"]
           .sum().sort_values(ascending=False).head(8).reset_index())
    fig = go.Figure(go.Bar(
        x=grp["estimated_exposure"], y=grp["specialty"],
        orientation="h",
        marker=dict(
            color=grp["estimated_exposure"],
            colorscale=[[0, "#1A1A4A"], [0.5, "#4A4AFF"], [1, "#FF6B6B"]],
            showscale=False,
        ),
        text=["${:,.0f}".format(v) for v in grp["estimated_exposure"]],
        textposition="outside",
        textfont=dict(size=11, color="#AAAAC0"),
        hovertemplate="%{y}: $%{x:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        **_CHART_LAYOUT,
        title=dict(text="<b>Estimated Exposure by Specialty</b>", font=dict(size=13)),
        xaxis=dict(title="Estimated Exposure ($)", gridcolor="#1E1E36"),
        yaxis=dict(gridcolor="rgba(0,0,0,0)"),
        height=300,
        margin=dict(l=10, r=90, t=44, b=30),
    )
    return fig


def confidence_breakdown_chart(worklist: pd.DataFrame) -> go.Figure:
    counts = worklist["confidence"].value_counts().reindex(
        ["HIGH", "MEDIUM", "LOW"], fill_value=0
    )
    colors = [CONF_COLOR.get(c, "#888") for c in counts.index]
    fig = go.Figure(go.Pie(
        labels=counts.index.tolist(),
        values=counts.values.tolist(),
        marker=dict(colors=colors, line=dict(color="#0D0D1A", width=2)),
        textinfo="label+percent",
        textfont=dict(size=12),
        hole=0.55,
        hovertemplate="%{label}: %{value} providers (%{percent})<extra></extra>",
    ))
    fig.update_layout(
        **_CHART_LAYOUT,
        title=dict(text="<b>Confidence Tier Breakdown</b>", font=dict(size=13)),
        height=300,
        legend=dict(orientation="h", y=-0.1, font=dict(size=11)),
        margin=dict(l=10, r=10, t=44, b=30),
    )
    return fig


def score_distribution_chart(worklist: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Histogram(
        x=worklist["risk_score"],
        nbinsx=20,
        marker=dict(
            color=worklist["risk_score"],
            colorscale=[[0, "#1A2A4A"], [0.5, "#4A6AFF"], [1, "#FF5050"]],
            line=dict(color="#0D0D1A", width=0.5),
        ),
        hovertemplate="Score %{x}: %{y} providers<extra></extra>",
    ))
    fig.update_layout(
        **_CHART_LAYOUT,
        title=dict(text="<b>Risk Score Distribution</b>", font=dict(size=13)),
        xaxis=dict(title="Risk Score", gridcolor="#1E1E36"),
        yaxis=dict(title="Providers",  gridcolor="#1E1E36"),
        height=280,
        margin=dict(l=10, r=10, t=44, b=30),
        bargap=0.06,
    )
    return fig


def shap_bar_chart(features: list, values: list) -> go.Figure:
    colors = ["#FF6B6B" if v > 0 else "#6BCB77" for v in values]
    fig = go.Figure(go.Bar(
        x=values, y=features, orientation="h",
        marker=dict(color=colors, opacity=0.85),
        text=[f"{v:+.4f}" for v in values],
        textposition="outside",
        textfont=dict(size=11, color="#AAAAC0"),
        hovertemplate="%{y}: %{x:+.4f}<extra></extra>",
    ))
    fig.add_vline(x=0, line_color="rgba(255,255,255,0.25)")
    fig.update_layout(
        **_CHART_LAYOUT,
        title=dict(text="<b>SHAP Feature Attribution</b>", font=dict(size=13)),
        xaxis=dict(title="SHAP value (anomaly contribution)", gridcolor="#1E1E36"),
        yaxis=dict(gridcolor="rgba(0,0,0,0)"),
        height=220,
        margin=dict(l=10, r=80, t=44, b=30),
        showlegend=False,
    )
    return fig


# ── Signal badges ─────────────────────────────────────────────────────────────

def signal_badges(pid: str, rules_df, peer_df, ml_df, worklist_row=None) -> str:
    badges = []
    if not rules_df.empty:
        for r in rules_df[rules_df["provider_id"] == pid]["rule"].unique():
            label = r.replace("_", " ").title()
            badges.append(f'<span class="signal-chip chip-rule">⚠ {label}</span>')
    if not peer_df.empty:
        n_peer = len(peer_df[peer_df["provider_id"] == pid])
        if n_peer:
            badges.append(f'<span class="signal-chip chip-peer">📊 Peer Outlier ({n_peer} metrics)</span>')
    if not ml_df.empty:
        ml_row = ml_df[ml_df["provider_id"] == pid]
        if not ml_row.empty and ml_row.iloc[0]["ml_is_anomaly"]:
            score = ml_row.iloc[0]["ml_score"]
            badges.append(f'<span class="signal-chip chip-ml">🤖 ML Anomaly ({score:.0f}/100)</span>')
    if worklist_row is not None:
        if worklist_row.get("codemix_flag", 0):
            kl = worklist_row.get("kl_divergence", 0)
            badges.append(f'<span class="signal-chip chip-temporal">🔀 Code-Mix Drift (KL={kl:.3f})</span>')
        if worklist_row.get("temporal_flag", 0):
            badges.append('<span class="signal-chip chip-temporal">📈 Temporal Change-Point</span>')
        fb = worklist_row.get("feedback_score", 0)
        if fb and float(fb) > 0:
            badges.append(f'<span class="signal-chip chip-feedback">🔁 Feedback Model ({float(fb):.1f} pts)</span>')
    return " ".join(badges) if badges else '<span style="color:#555;font-size:0.85rem;font-style:italic">No specific signal</span>'


# ── Sidebar ───────────────────────────────────────────────────────────────────

def render_sidebar(scores: pd.DataFrame):
    with st.sidebar:
        st.markdown("""
        <div style="text-align:center; padding: 10px 0 18px;">
          <div style="font-size:2rem;">🏥</div>
          <div style="font-size:1.0rem; font-weight:700; color:#C0C0F0; margin-top:6px;">Billing Anomaly<br>Audit System</div>
          <div style="font-size:0.7rem; color:#5050A0; margin-top:4px; letter-spacing:0.8px;">DECISION SUPPORT ONLY</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")
        st.markdown('<div style="font-size:0.75rem; font-weight:600; color:#7070A0; text-transform:uppercase; letter-spacing:1px; margin-bottom:10px;">FILTERS</div>', unsafe_allow_html=True)

        specs = ["All"] + sorted(scores["specialty"].unique().tolist())
        sel_spec = st.selectbox("Specialty", specs, key="sb_spec")

        conf_opts = ["All", "HIGH", "MEDIUM", "LOW"]
        sel_conf = st.selectbox("Confidence Tier", conf_opts, key="sb_conf")

        min_score = st.slider("Min Risk Score", 0, 100, RISK_THRESHOLD, 5, key="sb_score")

        st.markdown("---")
        st.markdown('<div style="font-size:0.75rem; font-weight:600; color:#7070A0; text-transform:uppercase; letter-spacing:1px; margin-bottom:10px;">QUICK STATS</div>', unsafe_allow_html=True)

        flagged = scores[scores["risk_score"] >= RISK_THRESHOLD]
        hi = len(flagged[flagged["confidence"] == "HIGH"])
        me = len(flagged[flagged["confidence"] == "MEDIUM"])
        lo = len(flagged[flagged["confidence"] == "LOW"])

        st.markdown(f"""
        <div style="display:flex; flex-direction:column; gap:6px; font-size:0.82rem;">
          <div style="display:flex; justify-content:space-between;">
            <span style="color:#FF6B6B; font-weight:600;">HIGH</span>
            <span style="color:#CCC;">{hi} providers</span>
          </div>
          <div style="display:flex; justify-content:space-between;">
            <span style="color:#FFD93D; font-weight:600;">MEDIUM</span>
            <span style="color:#CCC;">{me} providers</span>
          </div>
          <div style="display:flex; justify-content:space-between;">
            <span style="color:#6BCB77; font-weight:600;">LOW</span>
            <span style="color:#CCC;">{lo} providers</span>
          </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")
        if st.button("🔄  Clear Cache & Reload", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        st.markdown('<div style="font-size:0.65rem; color:#333355; text-align:center; margin-top:20px;">SYNTHETIC DATA ONLY<br>All providers and claims are fictional.</div>', unsafe_allow_html=True)

    return sel_spec, sel_conf, min_score


# ── Main app ──────────────────────────────────────────────────────────────────

def main():
    scores  = load_scores()
    rules   = load_rules()
    peer    = load_peer()
    ml      = load_ml()
    metrics = load_metrics()
    expls   = load_explanations()
    claims  = load_claims_sample()

    if scores.empty:
        st.error("No scoring data found. Run `python scoring.py` first.")
        return

    sel_spec, sel_conf, min_score = render_sidebar(scores)

    # Apply filters
    worklist = scores[scores["risk_score"] >= min_score].copy()
    if sel_spec != "All":
        worklist = worklist[worklist["specialty"] == sel_spec]
    if sel_conf != "All":
        worklist = worklist[worklist["confidence"] == sel_conf]

    # ── Warning banner ────────────────────────────────────────────────────────
    st.markdown(
        '<div class="banner">⚠ SYNTHETIC DATA — Decision-support tool for human auditors. '
        'No automated decisions or penalties are applied. All providers and claims are entirely fictional.</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div style="height:6px;"></div>', unsafe_allow_html=True)

    # ── Page header ───────────────────────────────────────────────────────────
    col_h, col_sub = st.columns([3, 1])
    with col_h:
        st.markdown('<h1 style="font-size:1.7rem; font-weight:700; color:#D0D0FF; margin:0;">Physician Billing Anomaly Detection</h1>', unsafe_allow_html=True)
        st.markdown('<p style="font-size:0.82rem; color:#5A5A8A; margin-top:4px;">Dollar-ranked proactive audit worklist · Rules + Peer Stats + ML Ensemble</p>', unsafe_allow_html=True)

    # ── KPI cards ─────────────────────────────────────────────────────────────
    all_flagged = scores[scores["risk_score"] >= RISK_THRESHOLD]
    total_exposure = all_flagged["estimated_exposure"].sum()
    n_flagged      = len(all_flagged)
    n_proactive    = len(all_flagged[
        (all_flagged["rules_score"] == 0) &
        ((all_flagged["peer_score"] > 0) | (all_flagged["ml_is_anomaly"] == 1))
    ])
    top_exposure = all_flagged["estimated_exposure"].max()

    st.markdown('<div style="height:14px;"></div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    kpis = [
        (c1, "💰", "Total Flagged Exposure", f"${total_exposure:,.0f}", "exposure", "sum of est. exposure for all flagged providers"),
        (c2, "🚨", "Providers Flagged",       str(n_flagged),            "flagged",  f"risk score ≥ {RISK_THRESHOLD}"),
        (c3, "🔍", "Proactive Finds",          str(n_proactive),          "proactive","stats/ML — not complaint-driven"),
        (c4, "📌", "Top Single Exposure",      f"${top_exposure:,.0f}",   "exposure", "highest individual estimated exposure"),
    ]
    for col, icon, label, value, cls, sub in kpis:
        with col:
            st.markdown(f"""
            <div class="kpi-card">
              <div class="kpi-icon">{icon}</div>
              <div class="kpi-label">{label}</div>
              <div class="kpi-value">{value}</div>
              <div class="kpi-sub">{sub}</div>
            </div>
            """, unsafe_allow_html=True)

    # ── Tabs ─────────────────────────────────────────────────────────────────
    st.markdown('<div style="height:20px;"></div>', unsafe_allow_html=True)
    tab_wl, tab_analytics, tab_model = st.tabs(["📋  Worklist", "📊  Analytics", "📖  Model Card"])

    # ═══════════════ WORKLIST TAB ═════════════════════════════════════════════
    with tab_wl:
        st.markdown(
            f'<div class="section-title"><span class="section-dot"></span>'
            f'Audit Worklist — <span style="color:#7070A0">{len(worklist)} providers shown</span>, ranked by risk × exposure</div>',
            unsafe_allow_html=True,
        )

        if worklist.empty:
            st.info("No providers match the current filters.")
        else:
            display_cols = {
                "provider_id":        "Provider ID",
                "provider_name":      "Name",
                "specialty":          "Specialty",
                "risk_score":         "Risk Score",
                "confidence":         "Confidence",
                "expected_recovery":  "Exp. Recovery ($)",
                "estimated_exposure": "Est. Exposure ($)",
                "top_reason":         "Top Reason",
            }
            table = worklist[list(display_cols.keys())].rename(columns=display_cols).reset_index(drop=True)
            table.index = table.index + 1

            def conf_style(val):
                css = {"HIGH": "color:#FF6B6B; font-weight:700",
                       "MEDIUM": "color:#FFD93D; font-weight:700",
                       "LOW": "color:#6BCB77; font-weight:700"}
                return css.get(val, "")

            styled = (
                table.style
                     .background_gradient(subset=["Risk Score"], cmap="YlOrRd", vmin=0, vmax=100)
                     .map(conf_style, subset=["Confidence"])
                     .format({
                         "Est. Exposure ($)":  "${:,.0f}",
                         "Exp. Recovery ($)":  "${:,.0f}",
                         "Risk Score":         "{:.1f}",
                     })
            )
            st.dataframe(styled, use_container_width=True,
                         height=min(620, 44 + len(table) * 36))

        # ── Provider Detail ────────────────────────────────────────────────
        st.markdown(
            '<div class="section-title"><span class="section-dot"></span>Provider Detail View</div>',
            unsafe_allow_html=True,
        )

        if worklist.empty:
            st.info("No providers to display with current filters.")
            return

        pid_options = worklist["provider_id"].tolist()
        name_map    = dict(zip(worklist["provider_id"], worklist["provider_name"]))
        spec_map    = dict(zip(worklist["provider_id"], worklist["specialty"]))
        score_map   = dict(zip(worklist["provider_id"], worklist["risk_score"]))
        conf_map    = dict(zip(worklist["provider_id"], worklist["confidence"]))

        selected_pid = st.selectbox(
            "Select provider",
            pid_options,
            format_func=lambda p: (
                f"[{conf_map.get(p, '?'):6s}] {score_map.get(p, 0):5.1f}/100 — "
                f"{p}  {name_map.get(p, '')}  ({spec_map.get(p, '')})"
            ),
            label_visibility="collapsed",
        )

        if selected_pid:
            _render_provider_detail(
                selected_pid, rules, peer, ml, metrics, expls, claims,
                worklist, score_map,
            )

    # ═══════════════ ANALYTICS TAB ════════════════════════════════════════════
    with tab_analytics:
        st.markdown(
            '<div class="section-title"><span class="section-dot"></span>Detection Overview</div>',
            unsafe_allow_html=True,
        )

        flagged_for_analytics = scores[scores["risk_score"] >= RISK_THRESHOLD]

        row1_l, row1_r = st.columns(2)
        with row1_l:
            st.plotly_chart(exposure_by_specialty_chart(flagged_for_analytics),
                            use_container_width=True)
        with row1_r:
            st.plotly_chart(confidence_breakdown_chart(flagged_for_analytics),
                            use_container_width=True)

        st.plotly_chart(score_distribution_chart(flagged_for_analytics),
                        use_container_width=True)

        # Detection layer contribution table
        st.markdown(
            '<div class="section-title"><span class="section-dot"></span>Detection Layer Coverage</div>',
            unsafe_allow_html=True,
        )
        layer_data = {
            "Layer":        ["Rules", "Peer Stats", "ML Ensemble", "Code-Mix", "Temporal", "Feedback"],
            "Providers Hit": [
                int((flagged_for_analytics["rules_score"] > 0).sum()),
                int((flagged_for_analytics["peer_score"] > 0).sum()),
                int((flagged_for_analytics["ml_is_anomaly"] == 1).sum()),
                int((flagged_for_analytics["codemix_flag"] == 1).sum()),
                int((flagged_for_analytics["temporal_flag"] == 1).sum()),
                int((flagged_for_analytics.get("feedback_score", pd.Series([0]*len(flagged_for_analytics))) > 0).sum()),
            ],
            "Max Score Pts": [50, 25, 15, 10, 5, 10],
            "Description":  [
                "Impossible days, duplicates, unbundling",
                "MAD z-score within specialty cohort",
                "IsolationForest + LOF + OC-SVM majority vote",
                "KL divergence + cosine distance vs cohort",
                "CUSUM change-point + spike detection",
                "Semi-supervised XGBoost on auditor labels",
            ],
        }
        st.dataframe(pd.DataFrame(layer_data), hide_index=True, use_container_width=True)

    # ═══════════════ MODEL CARD TAB ═══════════════════════════════════════════
    with tab_model:
        st.markdown("""
<div style="max-width:780px;">

### System Overview

| Field | Value |
|---|---|
| **System name** | Physician Billing Anomaly Detection Demo |
| **Version** | Phase 11 (all upgrades) |
| **Purpose** | Decision-SUPPORT for human billing auditors |
| **Automated decisions** | None — human review required for all flags |
| **Data** | SYNTHETIC — all providers and claims are fictional |

---

### Detection Layers

| Layer | Method | Max pts | Notes |
|---|---|---|---|
| Rules | Deterministic: impossible day, duplicate billing, unbundling | 50 | HIGH confidence; binary violations |
| Peer stats | MAD modified z-score within specialty + practice-setting cohort | 25 | One-sided (over-billing only) |
| ML ensemble | IsolationForest 50% + LOF 30% + OC-SVM 20%, majority vote | 15 | Requires ≥ 2/3 detectors to agree |
| Code-mix drift | KL divergence + cosine distance vs specialty cohort median | 10 | Catches unusual code pattern shifts |
| Temporal | CUSUM change-point on monthly volume + spike detection | 5 | Catches sudden-onset billing increases |
| Feedback | Semi-supervised XGBoost on auditor-confirmed dispositions | 10 | Active only when ≥ 6 labelled examples exist |

**Total max score:** 100 (clipped)

---

### Confidence Tiers & Expected Recovery

| Tier | Criteria | Recovery Likelihood |
|---|---|---|
| **HIGH** | Rule violation (any) | 70% |
| **MEDIUM** | ≥ 2 stat signals, or 1 signal + ML anomaly | 40% |
| **LOW** | Single weak signal | 15% |

Expected recovery = estimated exposure × likelihood. Worklist is ranked by `risk_score × log(1 + expected_recovery / 1000)`.

---

### Known Limitations & Fairness

- **TRAP03 (sub-threshold marathoner):** Flagged as false positive (peer stats). Long individual days are statistically unusual even when clinically explainable. Auditor judgement required.
- **Fairness audit (Phase 9):** No statistically significant over-flagging by specialty or clinic detected (chi-square p > 0.05 for all groups).
- **Feedback model:** Trained on a small seed of 11 dispositions; classification confidence improves with more auditor labels.
- **All data is SYNTHETIC.** This system is a demo only and is not suitable for production use without significant additional validation.

---

### Explainability

SHAP TreeExplainer (IsolationForest) provides per-provider feature attribution. Top-3 driving features shown in the Explanation tab. Full SHAP matrix saved to `shap_values.csv`.

</div>
""")


# ── Provider detail ───────────────────────────────────────────────────────────

def _render_provider_detail(pid, rules, peer, ml, metrics, expls, claims,
                             worklist, score_map):
    prow       = worklist[worklist["provider_id"] == pid].iloc[0]
    confidence = prow.get("confidence", "N/A")
    exp_rec    = float(prow.get("expected_recovery", prow.get("estimated_exposure", 0)))
    exposure   = float(prow.get("estimated_exposure", 0))
    risk_score = float(prow.get("risk_score", 0))

    # ── Provider header card ──────────────────────────────────────────────────
    conf_class = f"conf-{confidence}"
    st.markdown(f"""
    <div class="prov-header">
      <div style="display:flex; align-items:flex-start; justify-content:space-between; flex-wrap:wrap; gap:12px;">
        <div>
          <div class="prov-name">{prow['provider_name']}</div>
          <div class="prov-pid">{pid} · {prow['specialty']}</div>
        </div>
        <span class="conf-pill conf-{confidence}">{confidence} CONFIDENCE</span>
      </div>
      <div class="prov-stats">
        <div class="prov-stat">
          <div class="prov-stat-label">Risk Score</div>
          <div class="prov-stat-value" style="color:{{'HIGH':'#FF6B6B','MEDIUM':'#FFD93D','LOW':'#6BCB77'}}.get('{confidence}','#CCC')">{risk_score:.0f} / 100</div>
        </div>
        <div class="prov-stat">
          <div class="prov-stat-label">Est. Exposure</div>
          <div class="prov-stat-value">${exposure:,.0f}</div>
        </div>
        <div class="prov-stat">
          <div class="prov-stat-label">Expected Recovery</div>
          <div class="prov-stat-value">${exp_rec:,.0f}</div>
        </div>
        <div class="prov-stat">
          <div class="prov-stat-label">Specialty</div>
          <div class="prov-stat-value">{prow['specialty']}</div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Signals
    st.markdown("**Active signals:**")
    st.markdown(signal_badges(pid, rules, peer, ml, prow), unsafe_allow_html=True)
    st.markdown('<div style="height:10px;"></div>', unsafe_allow_html=True)

    # Risk gauge + tabs layout
    gauge_col, tabs_col = st.columns([1, 3])
    with gauge_col:
        st.plotly_chart(risk_gauge(risk_score, confidence), use_container_width=True)
        st.markdown(f'<div style="text-align:center; font-size:0.7rem; color:#5A5A8A; margin-top:-10px;">Risk Score</div>', unsafe_allow_html=True)

    with tabs_col:
        tab1, tab2, tab3, tab4 = st.tabs(
            ["⚠ Rule Evidence", "📊 Peer Comparison", "📅 Monthly Volume", "🔍 Explanation"]
        )

        # ── Tab 1: Rule Evidence ─────────────────────────────────────────────
        with tab1:
            rule_rows = rules[rules["provider_id"] == pid] if not rules.empty else pd.DataFrame()
            if rule_rows.empty:
                st.info("No deterministic rule violations for this provider.")
            else:
                for _, r in rule_rows.iterrows():
                    st.markdown(f"""
                    <div class="ev-card ev-rule">
                      <span class="ev-rule-label">⚠ {r['rule'].replace('_', ' ').upper()}</span>
                      <span class="ev-exposure">${r['estimated_exposure']:,.2f}</span>
                      <div class="ev-text">{r['evidence']}</div>
                    </div>
                    """, unsafe_allow_html=True)

            peer_rows = peer[peer["provider_id"] == pid] if not peer.empty else pd.DataFrame()
            if not peer_rows.empty:
                st.markdown('<div style="margin-top:14px; font-size:0.82rem; font-weight:600; color:#80AAFF;">Peer-Stat Flags (|z| &gt; 3):</div>', unsafe_allow_html=True)
                for _, r in peer_rows.sort_values("z_score", key=abs, ascending=False).iterrows():
                    direction = "above" if r["z_score"] > 0 else "below"
                    st.markdown(f"""
                    <div class="ev-card ev-peer">
                      <span class="ev-peer-label">📊 {r['metric'].replace('_', ' ').upper()}</span>
                      <div class="ev-text">
                        Provider: <strong style="color:#D0D0F0">{r['provider_value']:.2f}</strong> &nbsp;·&nbsp;
                        z = <strong style="color:#FFD93D">{r['z_score']:.2f}</strong> &nbsp;·&nbsp;
                        peer median: {r['peer_median']:.2f} &nbsp;·&nbsp;
                        {abs(r['z_score']):.1f}σ {direction}
                      </div>
                    </div>
                    """, unsafe_allow_html=True)

        # ── Tab 2: Peer Comparison ───────────────────────────────────────────
        with tab2:
            if not metrics.empty:
                fig = peer_comparison_chart(pid, metrics, peer)
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
                    st.caption("Bars > 1.0 = above peer median. Red = > 1.5× (strong outlier), yellow = 1.0–1.5×, green = at or below.")
            else:
                st.info("Metrics data not found. Run `peer_stats.py` first.")

        # ── Tab 3: Monthly Volume ────────────────────────────────────────────
        with tab3:
            if not claims.empty:
                fig2 = monthly_claims_chart(pid, claims)
                if fig2:
                    st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("Claims data not found.")

        # ── Tab 4: Explanation ───────────────────────────────────────────────
        with tab4:
            shap_df = load_shap_explanations()
            if not shap_df.empty:
                shap_row = shap_df[shap_df["provider_id"] == pid]
                if not shap_row.empty:
                    feats = shap_row.iloc[0]["top_features"].split(";")[:3]
                    vals  = [float(shap_row.iloc[0].get(f"shap_top{i}_val", 0))
                             for i in range(1, len(feats) + 1)]
                    clean_feats = [f.strip() for f in feats]
                    if any(v != 0 for v in vals):
                        st.plotly_chart(shap_bar_chart(clean_feats, vals),
                                        use_container_width=True)
                    st.caption("Positive SHAP = feature pushes toward anomaly; negative = away from anomaly.")
                    st.markdown("---")

            if pid in expls:
                st.text_area(
                    "Audit summary (set ANTHROPIC_API_KEY for AI-enriched):",
                    value=expls[pid]["explanation"],
                    height=260,
                    key=f"expl_{pid}",
                )
            else:
                st.info("Full explanation not pre-generated for this provider.")
                if st.button("Generate explanation now", key=f"gen_expl_{pid}"):
                    with st.spinner("Running explain.py…"):
                        from explain import build_explanations
                        build_explanations()
                        st.cache_data.clear()
                    st.rerun()


if __name__ == "__main__":
    main()
