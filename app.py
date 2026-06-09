"""Phase 7 — Streamlit Audit Dashboard (Enhanced UI).

Single-screen decision-support tool for human billing auditors.
NEVER makes automated decisions — all outputs are for human review only.
"""

import json
import os

from dotenv import load_dotenv
load_dotenv()

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import auth_mock

# ── SVG icon helpers ───────────────────────────────────────────────────────────
# Heroicons v2 outline (24×24 viewBox, stroke-width 1.5)
_ICON_PATHS: dict[str, str] = {
    "exclamation-triangle": "M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z",
    "chart-bar":            "M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z",
    "cpu-chip":             "M8.25 3v1.5M4.5 8.25H3m18 0h-1.5M4.5 12H3m18 0h-1.5m-15 3.75H3m18 0h-1.5M8.25 19.5V21M12 3v1.5m0 15V21m3.75-18v1.5m0 15V21m-9-1.5h10.5a2.25 2.25 0 002.25-2.25V6.75a2.25 2.25 0 00-2.25-2.25H6.75A2.25 2.25 0 004.5 6.75v10.5a2.25 2.25 0 002.25 2.25zm.75-12h9v9h-9v-9z",
    "arrows-right-left":    "M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5",
    "arrow-trending-up":    "M2.25 18L9 11.25l4.306 4.307a11.95 11.95 0 015.814-5.519l2.74-1.22m0 0l-5.94-2.28m5.94 2.28l-2.28 5.941",
    "arrow-path":           "M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99",
    "banknotes":            "M2.25 18.75a60.07 60.07 0 0115.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 013 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 00-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 01-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 003 15h-.75M15 10.5a3 3 0 11-6 0 3 3 0 016 0zm3 0h.008v.008H18V10.5zm-12 0h.008v.008H6V10.5z",
    "bell-alert":           "M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0M3.124 7.5A8.969 8.969 0 015.292 3m13.416 0a8.969 8.969 0 012.168 4.5",
    "magnifying-glass":     "M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 15.803 7.5 7.5 0 0016.803 15.803z",
    "map-pin":              "M15 10.5a3 3 0 11-6 0 3 3 0 016 0zM19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1115 0z",
    "plus-circle":          "M12 9v6m3-3H9m12 0a9 9 0 11-18 0 9 9 0 0118 0z",
    "lock-closed":          "M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z",
    "arrow-down-tray":      "M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3",
    "calendar":             "M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5m-9-6h.008v.008H12v-.008zM12 15h.008v.008H12V15zm0 2.25h.008v.008H12v-.008zM9.75 15h.008v.008H9.75V15zm0 2.25h.008v.008H9.75v-.008zM7.5 15h.008v.008H7.5V15zm0 2.25h.008v.008H7.5v-.008zm6.75-4.5h.008v.008h-.008v-.008zm0 2.25h.008v.008h-.008V15zm0 2.25h.008v.008h-.008v-.008zm2.25-4.5h.008v.008H18v-.008zm0 2.25h.008v.008H18V15z",
    "clipboard-list":       "M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25zM6.75 12h.008v.008H6.75V12zm0 3h.008v.008H6.75V15zm0 3h.008v.008H6.75V18z",
    "chart-bar-square":     "M7.5 14.25v2.25m3-4.5v4.5m3-6.75v6.75m3-9v9M6 20.25h12A2.25 2.25 0 0020.25 18V6A2.25 2.25 0 0018 3.75H6A2.25 2.25 0 003.75 6v12A2.25 2.25 0 006 20.25z",
    "document-text":        "M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z",
}

def _icon(name: str, size: int = 16, color: str = "currentColor", style: str = "") -> str:
    """Return an inline SVG string for the named Heroicons outline icon."""
    path = _ICON_PATHS.get(name, "")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.5" '
        f'stroke-linecap="round" stroke-linejoin="round" '
        f'style="vertical-align:middle;flex-shrink:0;{style}">'
        f'<path d="{path}"/></svg>'
    )

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
    padding: 22px 24px; position: relative;
    transition: border-color 0.2s;
  }
  .kpi-card:hover { border-color: #4A4A7A; }
  .kpi-accent {
    position: absolute; top: 0; left: 0;
    width: 4px; height: 100%;
  }
  .kpi-icon { margin-bottom: 10px; opacity: 0.9; display:flex; align-items:center; }
  .kpi-label {
    font-size: 0.7rem; color: #9090B8; text-transform: uppercase;
    letter-spacing: 1.2px; margin-bottom: 8px; font-weight: 500;
  }
  /* clamp scales value text across sidebar-open/closed layouts without wrapping */
  .kpi-value {
    font-size: clamp(1.2rem, 1.4vw, 1.9rem); font-weight: 700;
    color: #E8E8FF; line-height: 1.1; white-space: nowrap; overflow: visible;
  }
  .kpi-sub   { font-size: 0.73rem; color: #7878A0; margin-top: 8px; }

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

  /* ── reduced-motion: disable decorative transitions ── */
  @media (prefers-reduced-motion: reduce) {
    .kpi-card { transition: none; }
  }
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
    # margin intentionally omitted — every chart passes its own margin explicitly
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
            title="Ratio to Peer Median", gridcolor="#181828",
            zerolinecolor="#2A2A4A",
        ),
        yaxis=dict(gridcolor="#181828"),
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
        xaxis=dict(gridcolor="#181828"),
        yaxis=dict(title="Claims", gridcolor="#181828"),
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
        xaxis=dict(title="Estimated Exposure ($)", gridcolor="#181828"),
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
        xaxis=dict(title="Risk Score", gridcolor="#181828"),
        yaxis=dict(title="Providers",  gridcolor="#181828"),
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
        xaxis=dict(title="SHAP value (anomaly contribution)", gridcolor="#181828"),
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
            badges.append(f'<span class="signal-chip chip-rule">{_icon("exclamation-triangle",11,"#FF8080","margin-right:3px;")} {label}</span>')
    if not peer_df.empty:
        n_peer = len(peer_df[peer_df["provider_id"] == pid])
        if n_peer:
            badges.append(f'<span class="signal-chip chip-peer">{_icon("chart-bar",11,"#80AAFF","margin-right:3px;")} Peer Outlier ({n_peer} metrics)</span>')
    if not ml_df.empty:
        ml_row = ml_df[ml_df["provider_id"] == pid]
        if not ml_row.empty and ml_row.iloc[0]["ml_is_anomaly"]:
            score = ml_row.iloc[0]["ml_score"]
            badges.append(f'<span class="signal-chip chip-ml">{_icon("cpu-chip",11,"#60DDA0","margin-right:3px;")} ML Anomaly ({score:.0f}/100)</span>')
    if worklist_row is not None:
        if worklist_row.get("codemix_flag", 0):
            kl = worklist_row.get("kl_divergence", 0)
            badges.append(f'<span class="signal-chip chip-temporal">{_icon("arrows-right-left",11,"#FFAA55","margin-right:3px;")} Code-Mix Drift (KL={kl:.3f})</span>')
        if worklist_row.get("temporal_flag", 0):
            badges.append(f'<span class="signal-chip chip-temporal">{_icon("arrow-trending-up",11,"#FFAA55","margin-right:3px;")} Temporal Change-Point</span>')
        fb = worklist_row.get("feedback_score", 0)
        if fb and float(fb) > 0:
            badges.append(f'<span class="signal-chip chip-feedback">{_icon("arrow-path",11,"#CC88FF","margin-right:3px;")} Feedback Model ({float(fb):.1f} pts)</span>')
    return " ".join(badges) if badges else '<span style="color:#555;font-size:0.85rem;font-style:italic">No specific signal</span>'


# ── Sidebar ───────────────────────────────────────────────────────────────────

def render_sidebar(scores: pd.DataFrame):
    with st.sidebar:
        st.markdown(f"""
        <div style="text-align:center; padding: 10px 0 18px;">
          <div style="display:flex;justify-content:center;margin-bottom:6px;">{_icon("plus-circle", 40, "#8080D8")}</div>
          <div style="font-size:1.0rem; font-weight:700; color:#C0C0F0; margin-top:6px;">Billing Anomaly<br>Audit System</div>
          <div style="font-size:0.7rem; color:#8080B8; margin-top:4px; letter-spacing:0.8px;">DECISION SUPPORT ONLY</div>
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

        # ── Logged-in user + role badge ───────────────────────────────────
        _role    = auth_mock.current_role() or "?"
        _display = auth_mock.current_display_name()
        _role_colors = {
            "auditor":    ("#4A4AFF", "#1A1A5A"),
            "supervisor": ("#FF9F40", "#4A2A00"),
            "admin":      ("#FF5A5A", "#4A0000"),
        }
        _rc, _bg = _role_colors.get(_role, ("#888", "#222"))
        st.markdown(f"""
<div style="background:{_bg}; border:1px solid {_rc}44; border-radius:8px;
     padding:8px 12px; margin-bottom:8px;">
  <div style="font-size:0.68rem; color:#6A6A9A; text-transform:uppercase;
       letter-spacing:0.8px; margin-bottom:3px;">SIGNED IN AS</div>
  <div style="font-size:0.88rem; font-weight:600; color:#D0D0F0;">{_display}</div>
  <div style="font-size:0.7rem; color:{_rc}; margin-top:2px; font-family:monospace;
       text-transform:uppercase; letter-spacing:0.5px;">{_role}</div>
</div>
""", unsafe_allow_html=True)

        if st.button("Sign Out", icon=":material/logout:", use_container_width=True, key="btn_logout"):
            auth_mock.logout()   # clears ALL session state, then st.rerun()

        st.markdown("---")
        st.markdown('<div style="font-size:0.75rem; font-weight:600; color:#7070A0; text-transform:uppercase; letter-spacing:1px; margin-bottom:6px;">AUDITOR ID</div>', unsafe_allow_html=True)
        # Auditor ID is pre-filled from the logged-in username; allow override for
        # cases where a shared account acts on behalf of another named auditor.
        auditor_id = st.text_input(
            "Your ID (for audit log)",
            value=st.session_state.get("auditor_id", auth_mock.current_user() or "auditor"),
            key="sb_auditor_id",
            label_visibility="collapsed",
        )
        st.session_state["auditor_id"] = auditor_id

        st.markdown("---")
        if st.button("Clear Cache & Reload", icon=":material/refresh:", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        st.markdown('<div style="font-size:0.65rem; color:#6060A0; text-align:center; margin-top:20px;">SYNTHETIC DATA ONLY<br>All providers and claims are fictional.</div>', unsafe_allow_html=True)

    return sel_spec, sel_conf, min_score


# ── Main app ──────────────────────────────────────────────────────────────────

def main():
    # ── Authentication gate ───────────────────────────────────────────────────
    if not auth_mock.is_authenticated():
        auth_mock.render_login_screen()   # calls st.stop() if not yet logged in

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
        f'<div class="banner">{_icon("exclamation-triangle",15,"#FFD0D0","margin-right:6px;")} SYNTHETIC DATA — Decision-support tool for human auditors. '
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
        (c1, _icon("banknotes",28,"#A0D8A0"),         "Total Flagged Exposure", f"${total_exposure:,.0f}", "exposure", "sum of est. exposure for all flagged providers"),
        (c2, _icon("bell-alert",28,"#FF9090"),        "Providers Flagged",       str(n_flagged),            "flagged",  f"risk score ≥ {RISK_THRESHOLD}"),
        (c3, _icon("magnifying-glass",28,"#90B8FF"),  "Proactive Finds",          str(n_proactive),          "proactive","stats/ML — not complaint-driven"),
        (c4, _icon("map-pin",28,"#FFB060"),           "Top Single Exposure",      f"${top_exposure:,.0f}",   "exposure", "highest individual estimated exposure"),
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
    tab_wl, tab_analytics, tab_model, tab_audit = st.tabs(
        ["Worklist", "Analytics", "Model Card", "Audit Trail"]
    )
    # Role labels for the access-denied banners below
    _can_model = auth_mock.has_permission("view_model_card")
    _can_audit = auth_mock.has_permission("view_audit_trail")

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
            # Log flag_viewed once per unique provider per session
            _prev = st.session_state.get("_last_viewed_pid")
            if selected_pid != _prev:
                st.session_state["_last_viewed_pid"] = selected_pid
                try:
                    import audit_log as _al
                    _al.append_event(
                        "flag_viewed",
                        provider_id=selected_pid,
                        user=st.session_state.get("auditor_id", "auditor"),
                    )
                except Exception:
                    pass

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
        # ── Role gate — use else block, NOT st.stop(), so subsequent tabs still render
        if not _can_model:
            st.warning(
                f"Access restricted — Role **{auth_mock.current_role()}** "
                "cannot view the Model Card. Supervisor or Admin role required."
            )
        else:

            # ── Model registry section ───────────────────────────────────────
            st.markdown(
                '<div class="section-title"><span class="section-dot"></span>'
                'Feedback Model Registry</div>',
                unsafe_allow_html=True,
            )
            try:
                import model_registry as _mr
                versions = _mr.list_versions()
                if not versions:
                    st.info(
                        "No model versions registered yet. "
                        "Run `python feedback.py --seed-demo` to train the first version."
                    )
                else:
                    cur = versions[-1]
                    val = cur.get
                    det = cur.get("val_detection_rate")
                    fpr = cur.get("val_false_pos_rate")
                    st.markdown(f"""
<div style="background:#13131F; border:1px solid #2D2D4E; border-radius:10px; padding:18px 22px; max-width:720px; margin-bottom:12px;">
  <div style="font-size:0.75rem; color:#7070A0; text-transform:uppercase; letter-spacing:1px; margin-bottom:10px;">Current model version</div>
  <div style="display:flex; flex-wrap:wrap; gap:24px;">
    <div><div style="font-size:0.68rem; color:#5A5A8A;">Version</div><div style="font-size:1.1rem; font-weight:700; color:#D0D0F0; font-family:monospace;">{cur['version_id']}</div></div>
    <div><div style="font-size:0.68rem; color:#5A5A8A;">Trained</div><div style="font-size:0.88rem; color:#B0B0D0;">{cur['utc_timestamp'][:19].replace('T',' ')} UTC</div></div>
    <div><div style="font-size:0.68rem; color:#5A5A8A;">Model type</div><div style="font-size:0.88rem; color:#B0B0D0;">{cur['model_type']}</div></div>
    <div><div style="font-size:0.68rem; color:#5A5A8A;">Labels</div><div style="font-size:0.88rem; color:#B0B0D0;">{cur['n_total_labels']} ({cur['n_confirmed']} confirmed, {cur['n_cleared']} cleared)</div></div>
  </div>
  <div style="margin-top:14px; border-top:1px solid #2A2A4A; padding-top:12px; display:flex; gap:24px; flex-wrap:wrap;">
    <div><div style="font-size:0.68rem; color:#5A5A8A;">Training data hash</div><div style="font-size:0.78rem; color:#7070A0; font-family:monospace;">{cur['training_data_hash'][:32]}...</div></div>
    <div><div style="font-size:0.68rem; color:#5A5A8A;">Detection rate (val)</div><div style="font-size:0.88rem; color:#{'6BCB77' if det and det >= 0.8 else 'FFD93D' if det else '6A6A9A'};">{f"{det:.1%}" if det is not None else "N/A"}</div></div>
    <div><div style="font-size:0.68rem; color:#5A5A8A;">FP rate (val)</div><div style="font-size:0.88rem; color:#{'6BCB77' if fpr is not None and fpr <= 0.1 else 'FF6B6B' if fpr else '6A6A9A'};">{f"{fpr:.1%}" if fpr is not None else "N/A"}</div></div>
  </div>
</div>
""", unsafe_allow_html=True)

                    if len(versions) > 1:
                        st.caption(f"{len(versions)} total versions in registry.")
                        ver_df = pd.DataFrame([{
                            "Version":    v["version_id"],
                            "Trained":    v["utc_timestamp"][:19].replace("T", " "),
                            "Model":      v["model_type"],
                            "Labels":     v["n_total_labels"],
                            "Det. rate":  f"{v['val_detection_rate']:.1%}" if v.get("val_detection_rate") is not None else "N/A",
                            "FP rate":    f"{v['val_false_pos_rate']:.1%}"  if v.get("val_false_pos_rate")  is not None else "N/A",
                            "Data hash":  v["training_data_hash"][:16] + "...",
                        } for v in versions])
                        st.dataframe(ver_df, hide_index=True, use_container_width=True)
            except Exception as exc:
                st.warning(f"Model registry unavailable: {exc}")

            st.markdown("---")

            # ── Static methodology card ──────────────────────────────────────
            st.markdown("""
<div style="max-width:780px;">

### System overview

| Field | Value |
|---|---|
| **System name** | Physician Billing Anomaly Detection Demo |
| **Version** | Security-enhanced (audit trail + model registry + privacy noise) |
| **Purpose** | Decision-support for human billing auditors |
| **Automated decisions** | None — human review required for all flags |
| **Data** | Synthetic — all providers and claims are fictional |

---

### Detection layers

| Layer | Method | Max pts | Notes |
|---|---|---|---|
| Rules | Deterministic: impossible day, duplicate billing, unbundling | 50 | HIGH confidence; binary violations |
| Peer stats | MAD modified z-score within specialty + practice-setting cohort | 25 | One-sided (over-billing only) |
| ML ensemble | IsolationForest 50% + LOF 30% + OC-SVM 20%, majority vote | 15 | Requires >= 2/3 detectors to agree |
| Code-mix drift | KL divergence + cosine distance vs specialty cohort median | 10 | Catches unusual code pattern shifts |
| Temporal | CUSUM change-point on monthly volume + spike detection | 5 | Catches sudden-onset billing increases |
| Feedback | Semi-supervised XGBoost on auditor-confirmed dispositions | 10 | Active only when >= 6 labelled examples exist |

**Total max score:** 100 (clipped)

---

### Confidence tiers & expected recovery

| Tier | Criteria | Recovery likelihood |
|---|---|---|
| **HIGH** | Rule violation (any) | 70% |
| **MEDIUM** | >= 2 stat signals, or 1 signal + ML anomaly | 40% |
| **LOW** | Single weak signal | 15% |

---

### Known limitations & fairness

- **TRAP03 (sub-threshold marathoner):** Flagged as false positive (peer stats). Long individual days are statistically unusual even when clinically explainable. Auditor judgement required.
- **Fairness audit:** No statistically significant over-flagging by specialty or clinic detected (chi-square p > 0.05 for all groups).
- **Feedback model:** Trained on a small seed of dispositions; classification confidence improves with more auditor labels.
- **All data is synthetic.** This system is a demo only and is not suitable for production use without significant additional validation.

---

### Explainability & privacy

SHAP TreeExplainer (IsolationForest) provides per-provider feature attribution. Top-3 driving features are shown in the Explanation tab.

**Privacy notice:** Displayed SHAP contribution values include calibrated Laplace noise (epsilon shown per explanation). This is a demo-grade privacy measure, NOT a formal differential-privacy guarantee across all queries. Formal DP requires a managed privacy budget across all queries.

</div>
""")

    # ═══════════════ AUDIT TRAIL TAB ══════════════════════════════════════════
    with tab_audit:
        # ── Role gate — use else block, NOT st.stop(), so subsequent tabs still render
        if not _can_audit:
            st.warning(
                f"Access restricted — Role **{auth_mock.current_role()}** "
                "cannot view the Audit Trail. Supervisor or Admin role required."
            )
        else:
            st.markdown(
                '<div class="section-title"><span class="section-dot"></span>'
                'Immutable Audit Trail</div>',
                unsafe_allow_html=True,
            )
            st.caption(
                "Append-only event log. Every flag, view, and auditor action is "
                "recorded with a SHA-256 hash chain. Verify Integrity checks that "
                "no record has been altered or deleted."
            )

            col_v, col_e, col_spacer = st.columns([1, 1, 4])
            with col_v:
                if st.button("Verify Integrity", icon=":material/shield:", key="audit_verify"):
                    try:
                        # ── Function-level gate (second line of defence) ──────
                        auth_mock.require_permission("verify_integrity")
                        import audit_log as _al
                        res = _al.verify_integrity()
                        if res["ok"]:
                            st.success(res['message'])
                        else:
                            st.error(res['message'])
                    except PermissionError as pe:
                        st.error(f"Access denied: {pe}")
                    except Exception as exc:
                        st.error(f"Audit log error: {exc}")
            with col_e:
                if st.button("Export to CSV", icon=":material/download:", key="audit_export"):
                    try:
                        # ── Function-level gate (second line of defence) ──────
                        auth_mock.require_permission("export_audit_log")
                        import audit_log as _al
                        n = _al.export_to_csv()
                        st.success(f"Exported {n} records → audit_log_export.csv")
                    except PermissionError as pe:
                        st.error(f"Access denied: {pe}")
                    except Exception as exc:
                        st.error(f"Export error: {exc}")

            st.markdown('<div style="height:10px;"></div>', unsafe_allow_html=True)

            try:
                import audit_log as _al
                recent = _al.get_recent(200)
                if not recent:
                    st.info(
                        "No audit events recorded yet. Run `python scoring.py` to "
                        "generate the first batch of flag_generated events."
                    )
                else:
                    df_log = pd.DataFrame(recent)
                    # Friendly column order
                    show_cols = [c for c in
                        ["id", "utc_timestamp", "event_type", "user", "provider_id",
                         "model_version", "action_taken", "signals_shown", "reasoning"]
                        if c in df_log.columns]
                    st.dataframe(
                        df_log[show_cols],
                        use_container_width=True,
                        height=500,
                        hide_index=True,
                    )
                    st.caption(f"{len(recent)} most recent events shown (newest first).")
            except Exception as exc:
                st.warning(f"Could not load audit log: {exc}")


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

    # ── Auditor action buttons ────────────────────────────────────────────────
    st.markdown(
        '<div style="font-size:0.78rem; font-weight:600; color:#7070A0; '
        'margin-bottom:6px;">Record disposition (logged to audit trail):</div>',
        unsafe_allow_html=True,
    )
    _user = st.session_state.get("auditor_id", "auditor")

    # Build signals list for the audit log entry
    _sigs = []
    if not rules.empty and not rules[rules["provider_id"] == pid].empty:
        _sigs += rules[rules["provider_id"] == pid]["rule"].tolist()
    if prow.get("peer_score", 0) > 0:
        _sigs.append("peer_stats")
    if prow.get("ml_is_anomaly", 0):
        _sigs.append(f"ml_ensemble:{prow.get('ml_score', 0):.0f}")

    btn_c, btn_cl, btn_i, _ = st.columns([1.5, 1.5, 2, 3])

    with btn_c:
        if st.button("Confirm", icon=":material/check:", key=f"btn_confirm_{pid}", type="primary"):
            try:
                auth_mock.require_permission("take_action")   # function-level gate
                import audit_log as _al
                from feedback import record_disposition
                _al.append_event(
                    "action_taken",
                    provider_id=pid,
                    user=_user,
                    signals_shown=_sigs,
                    action_taken="confirmed",
                    reasoning=f"Auditor {_user} confirmed flag",
                )
                record_disposition(pid, "confirmed",
                                   notes=f"Confirmed via dashboard by {_user}",
                                   source="dashboard")
                st.success(f"Recorded: {pid} confirmed")
            except PermissionError as pe:
                st.error(f"Access denied: {pe}")
            except Exception as exc:
                st.error(f"Error: {exc}")

    with btn_cl:
        if st.button("Clear", icon=":material/close:", key=f"btn_clear_{pid}"):
            try:
                auth_mock.require_permission("take_action")   # function-level gate
                import audit_log as _al
                from feedback import record_disposition
                _al.append_event(
                    "action_taken",
                    provider_id=pid,
                    user=_user,
                    signals_shown=_sigs,
                    action_taken="cleared",
                    reasoning=f"Auditor {_user} cleared flag",
                )
                record_disposition(pid, "cleared",
                                   notes=f"Cleared via dashboard by {_user}",
                                   source="dashboard")
                st.success(f"Recorded: {pid} cleared")
            except PermissionError as pe:
                st.error(f"Access denied: {pe}")
            except Exception as exc:
                st.error(f"Error: {exc}")

    with btn_i:
        if st.button("Investigating", icon=":material/flag:", key=f"btn_invest_{pid}"):
            try:
                auth_mock.require_permission("take_action")   # function-level gate
                import audit_log as _al
                _al.append_event(
                    "action_taken",
                    provider_id=pid,
                    user=_user,
                    signals_shown=_sigs,
                    action_taken="investigating",
                    reasoning=f"Auditor {_user} opened investigation",
                )
                st.info(f"Recorded: {pid} under investigation")
            except PermissionError as pe:
                st.error(f"Access denied: {pe}")
            except Exception as exc:
                st.error(f"Error: {exc}")

    st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)

    # Risk gauge + tabs layout
    gauge_col, tabs_col = st.columns([1, 3])
    with gauge_col:
        st.plotly_chart(risk_gauge(risk_score, confidence), use_container_width=True)
        st.markdown(f'<div style="text-align:center; font-size:0.7rem; color:#5A5A8A; margin-top:-10px;">Risk Score</div>', unsafe_allow_html=True)

    with tabs_col:
        tab1, tab2, tab3, tab4 = st.tabs(
            ["Rule Evidence", "Peer Comparison", "Monthly Volume", "Explanation"]
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
                      <span class="ev-rule-label">{_icon("exclamation-triangle",12,"#FF7070","margin-right:3px;")} {r['rule'].replace('_', ' ').upper()}</span>
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
                      <span class="ev-peer-label">{_icon("chart-bar",12,"#6A9FFF","margin-right:3px;")} {r['metric'].replace('_', ' ').upper()}</span>
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

                    # ── Privacy noise indicator ──────────────────────────────
                    _eps  = shap_row.iloc[0].get("privacy_epsilon")
                    _note = shap_row.iloc[0].get("privacy_note", "")
                    if _eps and not pd.isna(_eps):
                        st.markdown(
                            f'<div style="background:rgba(80,60,0,0.25); border:1px solid '
                            f'rgba(200,150,0,0.4); border-radius:6px; padding:8px 12px; '
                            f'font-size:0.75rem; color:#C8A020; margin-top:4px;">'
                            f'<strong>Privacy notice (epsilon={float(_eps):.1f}):</strong> '
                            f'Explanation values include calibrated Laplace privacy noise. '
                            f'This is a <em>demo-grade</em> privacy measure, NOT a formal '
                            f'differential-privacy guarantee across all queries.</div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.caption(
                            "Privacy noise: not applied "
                            "(run explain.py to regenerate with privacy.py)."
                        )
                    st.caption(
                        "Positive SHAP = feature pushes toward anomaly; "
                        "negative = away from anomaly."
                    )
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
