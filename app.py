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

import auth

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
  @import url('https://fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,300;0,14..32,400;0,14..32,500;0,14..32,600;0,14..32,700;0,14..32,800&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

  /* ── Keyframes ── */
  @keyframes riseIn {
    from { opacity: 0; transform: translateY(12px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  @keyframes bannerSweep {
    0%   { background-position: -200% 0; }
    100% { background-position: 300% 0; }
  }
  @keyframes dotGlow {
    0%,100% { box-shadow: 0 0 0 0 rgba(99,102,241,0.6); opacity: 1; }
    50%     { box-shadow: 0 0 0 6px rgba(99,102,241,0); opacity: 0.7; }
  }
  @keyframes gradientBorder {
    0%   { background-position: 0% 50%; }
    50%  { background-position: 100% 50%; }
    100% { background-position: 0% 50%; }
  }
  @keyframes kpiShimmer {
    0%   { transform: translateX(-100%); }
    100% { transform: translateX(200%); }
  }

  /* ── Design tokens ── */
  :root {
    --bg-0: #020209;
    --bg-1: #06061A;
    --bg-2: #0A0A1E;
    --bg-3: #0E0E26;

    --indigo:    #6366F1;
    --indigo-lo: rgba(99,102,241,0.12);
    --cyan:      #06B6D4;
    --cyan-lo:   rgba(6,182,212,0.12);
    --violet:    #8B5CF6;
    --violet-lo: rgba(139,92,246,0.12);
    --rose:      #F43F5E;
    --rose-lo:   rgba(244,63,94,0.12);
    --amber:     #F59E0B;
    --amber-lo:  rgba(245,158,11,0.12);
    --emerald:   #10B981;
    --emerald-lo:rgba(16,185,129,0.12);

    --txt-hi:  #EEF0FF;
    --txt-mid: #8A96C8;
    --txt-lo:  #3D4870;

    --stroke:    #131830;
    --stroke-hi: #252D58;

    --shadow-sm: 0 1px 4px rgba(0,0,0,0.55);
    --shadow-md: 0 4px 20px rgba(0,0,0,0.5), 0 1px 4px rgba(0,0,0,0.55);
    --shadow-lg: 0 16px 56px rgba(0,0,0,0.65), 0 4px 16px rgba(0,0,0,0.55);
    --glow-ind:  0 0 24px rgba(99,102,241,0.3);
    --glow-cyn:  0 0 24px rgba(6,182,212,0.3);

    --ease: cubic-bezier(0.16, 1, 0.3, 1);
    --t-fast: 0.14s var(--ease);
    --t-med:  0.26s var(--ease);

    --r-sm:   8px;
    --r-md:   12px;
    --r-lg:   16px;
    --r-xl:   20px;
    --r-pill: 999px;
  }

  /* ── Base ── */
  html, body, [class*="css"] {
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    text-rendering: optimizeLegibility;
  }

  /* ── App background ── */
  .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"],
  [data-testid="stMainBlockContainer"] {
    background: var(--bg-0) !important;
  }

  /* ── Warning banner ── */
  .banner {
    position: relative; overflow: hidden;
    background: linear-gradient(90deg, #4A0A14 0%, #6B1020 50%, #4A0A14 100%);
    background-size: 200% 100%;
    color: #FFB8C0; padding: 11px 22px; border-radius: var(--r-md);
    font-size: 0.82rem; font-weight: 500; text-align: center;
    margin-bottom: 6px;
    border: 1px solid rgba(244,63,94,0.25);
    border-left: 3px solid rgba(244,63,94,0.8);
    box-shadow: 0 0 30px rgba(244,63,94,0.08), var(--shadow-md);
    letter-spacing: 0.15px;
  }
  .banner::after {
    content: ""; position: absolute; inset: 0;
    background: linear-gradient(105deg, transparent 25%, rgba(255,255,255,0.07) 50%, transparent 75%);
    background-size: 250% 100%;
    animation: bannerSweep 7s linear infinite;
    pointer-events: none;
  }

  /* ── KPI cards ── */
  .kpi-card {
    position: relative; overflow: hidden;
    background: linear-gradient(145deg, var(--bg-2) 0%, var(--bg-1) 100%);
    border: 1px solid var(--stroke);
    border-radius: var(--r-lg);
    padding: 22px 22px 20px;
    box-shadow: var(--shadow-md), inset 0 1px 0 rgba(255,255,255,0.03);
    transition: transform var(--t-med), border-color var(--t-med), box-shadow var(--t-med);
    animation: riseIn 0.5s var(--ease) both;
    cursor: default;
  }
  /* gradient top-edge that reveals on hover */
  .kpi-card::before {
    content: ""; position: absolute; top: 0; left: 0; right: 0; height: 1px;
    background: linear-gradient(90deg, transparent 0%, var(--kpi-accent, var(--indigo)) 50%, transparent 100%);
    opacity: 0; transition: opacity var(--t-med);
  }
  /* shimmer sweep */
  .kpi-card::after {
    content: ""; position: absolute;
    top: 0; left: -60%; width: 40%; height: 100%;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.04), transparent);
    transition: none;
  }
  .kpi-card:hover {
    transform: translateY(-5px);
    border-color: var(--stroke-hi);
    box-shadow: var(--shadow-lg), 0 0 0 1px var(--stroke-hi), 0 0 40px rgba(99,102,241,0.1);
  }
  .kpi-card:hover::before { opacity: 1; }
  .kpi-card:hover::after {
    left: 120%; transition: left 0.6s ease;
  }
  .kpi-icon {
    margin-bottom: 12px; display: flex; align-items: center;
    transition: transform var(--t-med);
  }
  .kpi-card:hover .kpi-icon { transform: scale(1.1) translateX(2px); }
  .kpi-label {
    font-size: 0.65rem; color: var(--txt-lo);
    text-transform: uppercase; letter-spacing: 1.4px;
    margin-bottom: 8px; font-weight: 600;
  }
  .kpi-value {
    font-size: clamp(1.15rem, 1.45vw, 1.85rem);
    font-weight: 800; color: var(--txt-hi);
    line-height: 1.1; letter-spacing: -0.3px;
    font-family: 'Inter', sans-serif;
  }
  .kpi-sub { font-size: 0.7rem; color: var(--txt-lo); margin-top: 8px; }

  /* ── Section headings ── */
  .section-title {
    font-size: 0.82rem; font-weight: 700; color: var(--txt-lo);
    padding-bottom: 10px; margin: 28px 0 18px;
    border-bottom: 1px solid var(--stroke);
    display: flex; align-items: center; gap: 10px;
    text-transform: uppercase; letter-spacing: 1.1px;
  }
  .section-dot {
    width: 7px; height: 7px; border-radius: 50%;
    background: var(--indigo); display: inline-block; flex-shrink: 0;
    animation: dotGlow 2.8s var(--ease) infinite;
    box-shadow: 0 0 8px rgba(99,102,241,0.6);
  }

  /* ── Signal chips ── */
  .signal-chip {
    display: inline-flex; align-items: center; padding: 4px 12px;
    border-radius: var(--r-pill);
    font-size: 0.68rem; font-weight: 700; margin: 2px 3px 4px;
    letter-spacing: 0.3px; font-family: 'Inter', sans-serif;
    transition: transform var(--t-fast), box-shadow var(--t-fast), filter var(--t-fast);
    cursor: default; white-space: nowrap;
  }
  .signal-chip:hover { transform: translateY(-2px); filter: brightness(1.15); }

  .chip-rule     { background: rgba(244,63,94,0.12);  color: #FB7185; border: 1px solid rgba(244,63,94,0.3); }
  .chip-rule:hover     { box-shadow: 0 4px 16px rgba(244,63,94,0.25); }
  .chip-peer     { background: rgba(99,102,241,0.12); color: #A5B4FC; border: 1px solid rgba(99,102,241,0.3); }
  .chip-peer:hover     { box-shadow: 0 4px 16px rgba(99,102,241,0.25); }
  .chip-ml       { background: rgba(16,185,129,0.12); color: #6EE7B7; border: 1px solid rgba(16,185,129,0.3); }
  .chip-ml:hover       { box-shadow: 0 4px 16px rgba(16,185,129,0.25); }
  .chip-temporal { background: rgba(245,158,11,0.12); color: #FCD34D; border: 1px solid rgba(245,158,11,0.3); }
  .chip-temporal:hover { box-shadow: 0 4px 16px rgba(245,158,11,0.25); }
  .chip-feedback { background: rgba(139,92,246,0.12); color: #C4B5FD; border: 1px solid rgba(139,92,246,0.3); }
  .chip-feedback:hover { box-shadow: 0 4px 16px rgba(139,92,246,0.25); }

  /* ── Confidence pills ── */
  .conf-pill {
    display: inline-block; padding: 4px 14px; border-radius: var(--r-pill);
    font-size: 0.72rem; font-weight: 800; letter-spacing: 0.8px;
    text-transform: uppercase; font-family: 'JetBrains Mono', monospace;
  }
  .conf-HIGH   { background: rgba(244,63,94,0.15);  color: #FB7185; border: 1px solid rgba(244,63,94,0.4);
                 box-shadow: 0 0 16px rgba(244,63,94,0.2); }
  .conf-MEDIUM { background: rgba(245,158,11,0.15); color: #FCD34D; border: 1px solid rgba(245,158,11,0.4);
                 box-shadow: 0 0 16px rgba(245,158,11,0.2); }
  .conf-LOW    { background: rgba(16,185,129,0.15); color: #6EE7B7; border: 1px solid rgba(16,185,129,0.4);
                 box-shadow: 0 0 16px rgba(16,185,129,0.2); }

  /* ── Provider header card ── */
  .prov-header {
    position: relative; overflow: hidden;
    background:
      radial-gradient(160% 120% at 100% 0%, rgba(99,102,241,0.1) 0%, transparent 55%),
      radial-gradient(100% 100% at 0% 100%, rgba(6,182,212,0.06) 0%, transparent 50%),
      linear-gradient(145deg, #0C0C24 0%, #080818 100%);
    border: 1px solid var(--stroke-hi);
    border-radius: var(--r-xl);
    padding: 26px 28px;
    margin-bottom: 20px;
    box-shadow: var(--shadow-lg), inset 0 1px 0 rgba(255,255,255,0.04);
    animation: riseIn 0.45s var(--ease) both;
  }
  .prov-header::before {
    content: ""; position: absolute;
    top: 0; left: 0; right: 0; height: 1px;
    background: linear-gradient(90deg, transparent, rgba(99,102,241,0.6), rgba(6,182,212,0.4), transparent);
  }
  .prov-name {
    font-size: 1.5rem; font-weight: 800; color: var(--txt-hi);
    letter-spacing: -0.4px; font-family: 'Inter', sans-serif;
  }
  .prov-pid {
    font-size: 0.75rem; color: var(--txt-lo); margin-top: 3px;
    font-family: 'JetBrains Mono', monospace; letter-spacing: 0.5px;
  }
  .prov-stats {
    display: flex; gap: 0; margin-top: 20px;
    border-top: 1px solid var(--stroke); padding-top: 18px; flex-wrap: wrap;
  }
  .prov-stat { flex: 1; min-width: 100px; padding: 0 20px 0 0; }
  .prov-stat + .prov-stat { border-left: 1px solid var(--stroke); padding-left: 20px; }
  .prov-stat-label { font-size: 0.63rem; color: var(--txt-lo); text-transform: uppercase; letter-spacing: 1px; font-weight: 600; }
  .prov-stat-value { font-size: 1.1rem; font-weight: 700; color: var(--txt-hi); margin-top: 4px; font-family: 'Inter', sans-serif; }

  /* ── Evidence cards ── */
  .ev-card {
    position: relative;
    background: linear-gradient(135deg, var(--bg-2) 0%, var(--bg-1) 100%);
    border-left: 2px solid;
    border-radius: 0 var(--r-md) var(--r-md) 0;
    padding: 14px 18px; margin-bottom: 10px;
    box-shadow: var(--shadow-sm);
    transition: transform var(--t-fast), box-shadow var(--t-fast), background var(--t-fast);
  }
  .ev-card:hover {
    transform: translateX(5px);
    background: linear-gradient(135deg, var(--bg-3) 0%, var(--bg-2) 100%);
    box-shadow: var(--shadow-md);
  }
  .ev-rule { border-color: #F43F5E; }
  .ev-rule:hover { box-shadow: -4px 0 20px -6px rgba(244,63,94,0.5), var(--shadow-md); }
  .ev-peer { border-color: #6366F1; }
  .ev-peer:hover { box-shadow: -4px 0 20px -6px rgba(99,102,241,0.5), var(--shadow-md); }
  .ev-rule-label { font-size: 0.7rem; font-weight: 800; color: #FB7185; text-transform: uppercase; letter-spacing: 0.8px; font-family: 'JetBrains Mono', monospace; }
  .ev-peer-label { font-size: 0.7rem; font-weight: 800; color: #A5B4FC; text-transform: uppercase; letter-spacing: 0.8px; font-family: 'JetBrains Mono', monospace; }
  .ev-exposure { font-size: 0.76rem; color: #FCD34D; font-weight: 700; float: right; font-family: 'JetBrains Mono', monospace; }
  .ev-text { font-size: 0.84rem; color: var(--txt-mid); margin-top: 7px; line-height: 1.55; }

  /* ── Sidebar ── */
  [data-testid="stSidebar"] {
    background:
      radial-gradient(140% 80% at 50% 0%, rgba(99,102,241,0.12) 0%, transparent 60%),
      linear-gradient(180deg, #07071E 0%, #050510 100%);
    border-right: 1px solid var(--stroke);
    box-shadow: 4px 0 32px rgba(0,0,0,0.4);
  }

  /* ── Buttons ── */
  .stButton > button {
    border-radius: var(--r-md) !important;
    border: 1px solid var(--stroke) !important;
    background: linear-gradient(180deg, var(--bg-3), var(--bg-2)) !important;
    color: var(--txt-mid) !important;
    font-weight: 600 !important; font-family: 'Inter', sans-serif !important;
    font-size: 0.83rem !important;
    transition: transform var(--t-fast), border-color var(--t-fast),
                box-shadow var(--t-fast), background var(--t-fast) !important;
    box-shadow: var(--shadow-sm) !important;
  }
  .stButton > button:hover {
    border-color: var(--stroke-hi) !important;
    color: var(--txt-hi) !important;
    transform: translateY(-1px) !important;
    box-shadow: var(--shadow-md), 0 0 16px rgba(99,102,241,0.12) !important;
  }
  .stButton > button:active { transform: translateY(0) scale(0.985) !important; }
  .stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #6366F1, #4F46E5) !important;
    border-color: rgba(99,102,241,0.4) !important; color: #fff !important;
    box-shadow: 0 0 20px rgba(99,102,241,0.3) !important;
  }
  .stButton > button[kind="primary"]:hover {
    box-shadow: 0 0 32px rgba(99,102,241,0.5), 0 8px 20px rgba(0,0,0,0.3) !important;
  }

  /* ── Inputs / selects ── */
  [data-baseweb="select"] > div, .stTextInput input, .stNumberInput input {
    background: rgba(255,255,255,0.02) !important;
    border-color: var(--stroke) !important;
    border-radius: var(--r-md) !important;
    color: var(--txt-hi) !important;
    transition: border-color var(--t-fast), box-shadow var(--t-fast) !important;
  }
  [data-baseweb="select"] > div:focus-within,
  .stTextInput input:focus, .stNumberInput input:focus {
    border-color: var(--indigo) !important;
    box-shadow: 0 0 0 3px rgba(99,102,241,0.18) !important;
  }

  /* ── Slider ── */
  [data-testid="stSlider"] [data-baseweb="slider"] [role="slider"] {
    box-shadow: 0 0 0 4px rgba(99,102,241,0.2), var(--shadow-sm) !important;
    background: var(--indigo) !important;
    transition: box-shadow var(--t-fast) !important;
  }
  [data-testid="stSlider"] [data-baseweb="slider"] [role="slider"]:hover {
    box-shadow: 0 0 0 7px rgba(99,102,241,0.25), var(--glow-ind) !important;
  }

  /* ── Dataframe ── */
  [data-testid="stDataFrame"] {
    border-radius: var(--r-lg) !important;
    overflow: hidden;
    box-shadow: var(--shadow-md);
    border: 1px solid var(--stroke) !important;
  }

  /* ── Charts ── */
  [data-testid="stPlotlyChart"] {
    border-radius: var(--r-lg);
    overflow: hidden;
    box-shadow: var(--shadow-sm);
    border: 1px solid var(--stroke);
    background: var(--bg-1);
    transition: box-shadow var(--t-med), border-color var(--t-med);
  }
  [data-testid="stPlotlyChart"]:hover {
    box-shadow: var(--shadow-md);
    border-color: var(--stroke-hi);
  }

  /* ── Alerts ── */
  [data-testid="stAlertContainer"] {
    border-radius: var(--r-md) !important;
    box-shadow: var(--shadow-sm) !important;
  }

  /* ── Tabs ── */
  [data-testid="stTabs"] [role="tablist"] {
    border-bottom: 1px solid var(--stroke);
    gap: 2px; background: transparent;
  }
  [data-testid="stTabs"] [role="tab"] {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.82rem !important; font-weight: 500 !important;
    color: var(--txt-lo) !important;
    padding: 9px 18px !important;
    border-radius: 8px 8px 0 0;
    border-bottom: 2px solid transparent;
    transition: color 0.15s, border-color 0.15s, background 0.15s;
  }
  [data-testid="stTabs"] [role="tab"]:hover {
    color: var(--txt-mid) !important;
    background: rgba(99,102,241,0.05) !important;
  }
  [data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: #C8D4FF !important;
    border-bottom: 2px solid var(--indigo) !important;
    background: rgba(99,102,241,0.08) !important;
    font-weight: 700 !important;
  }

  /* ── Focus ring ── */
  :focus-visible {
    outline: 2px solid var(--indigo) !important;
    outline-offset: 2px !important;
  }

  /* ── Scrollbar ── */
  ::-webkit-scrollbar       { width: 4px; height: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--stroke-hi); border-radius: 4px; }
  ::-webkit-scrollbar-thumb:hover { background: #3D4A8A; }

  /* ── Responsive ── */
  @media (max-width: 768px) {
    .kpi-card { padding: 16px 18px; }
    .kpi-value { font-size: 1.3rem !important; }
    .prov-stats { flex-direction: column; gap: 12px; }
    .prov-stat + .prov-stat { border-left: none; padding-left: 0; border-top: 1px solid var(--stroke); padding-top: 12px; }
  }

  /* ── Reduced motion ── */
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation: none !important; transition: none !important; }
    .kpi-card:hover { transform: none; }
    .ev-card:hover  { transform: none; }
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
    plot_bgcolor="rgba(6,6,20,0.0)",
    font=dict(family="Inter, system-ui, sans-serif", color="#6A78A8", size=11),
)
_AXIS_STYLE = dict(gridcolor="#0E1230", zerolinecolor="#1A2050", linecolor="#0E1230")


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

    colors = ["#F43F5E" if r > 1.5 else "#F59E0B" if r > 1.0 else "#10B981" for r in ratio]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=ratio, y=labels, orientation="h",
        marker=dict(color=colors, line=dict(color="rgba(255,255,255,0.03)", width=0.5),
                    opacity=0.85),
        text=[f"{v:.2f} (peer {m:.2f})" for v, m in zip(prov_vals, med_vals)],
        textposition="outside",
        textfont=dict(size=11, color="#6A78A8", family="JetBrains Mono"),
        hovertemplate="%{y}: %{x:.2f}x peer median<extra></extra>",
    ))
    fig.add_vline(x=1.0, line_dash="dot", line_color="rgba(99,102,241,0.4)")
    fig.update_layout(
        **_CHART_LAYOUT,
        title=dict(text=f"<b>{specialty}</b> — Provider vs Peer Median",
                   font=dict(size=13, color="#8A96C8")),
        xaxis=dict(title="Ratio to Peer Median", **_AXIS_STYLE),
        yaxis=dict(**_AXIS_STYLE),
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
        marker=dict(color="#6366F1", opacity=0.75,
                    line=dict(color="rgba(99,102,241,0.3)", width=0.5)),
        hovertemplate="%{x}: %{y} claims<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=monthly["month"], y=monthly["total_billed"],
        name="Total Billed ($)", yaxis="y2",
        line=dict(color="#06B6D4", width=2.5),
        mode="lines+markers",
        marker=dict(size=5, color="#06B6D4"),
        hovertemplate="%{x}: $%{y:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        **_CHART_LAYOUT,
        title=dict(text="<b>Monthly Billing Volume</b>", font=dict(size=13, color="#8A96C8")),
        height=260,
        yaxis=dict(title="Claims", **_AXIS_STYLE),
        yaxis2=dict(title="Billed ($)", overlaying="y", side="right", **_AXIS_STYLE),
        margin=dict(l=10, r=70, t=44, b=30),
        legend=dict(orientation="h", y=-0.25, font=dict(size=11, color="#6A78A8")),
    )
    return fig


_CONF_COLOR_NEW = {"HIGH": "#F43F5E", "MEDIUM": "#F59E0B", "LOW": "#10B981"}

def risk_gauge(score: float, confidence: str) -> go.Figure:
    color = _CONF_COLOR_NEW.get(confidence, "#6366F1")
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        number=dict(suffix="/100", font=dict(size=26, color=color,
                    family="JetBrains Mono")),
        gauge=dict(
            axis=dict(range=[0, 100],
                      tickfont=dict(size=9, color="#3D4870", family="JetBrains Mono"),
                      tickvals=[0, 25, 50, 75, 100]),
            bar=dict(color=color, thickness=0.28),
            bgcolor="rgba(0,0,0,0)",
            bordercolor="rgba(0,0,0,0)",
            steps=[
                dict(range=[0, 33],   color="#08081C"),
                dict(range=[33, 66],  color="#0A0A22"),
                dict(range=[66, 100], color="#0E0E2A"),
            ],
            threshold=dict(
                line=dict(color=color, width=2),
                thickness=0.85, value=score,
            ),
        ),
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#6A78A8", family="Inter"),
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
            colorscale=[[0, "#1A1A4A"], [0.4, "#6366F1"], [0.75, "#8B5CF6"], [1, "#F43F5E"]],
            showscale=False,
            opacity=0.85,
        ),
        text=["${:,.0f}".format(v) for v in grp["estimated_exposure"]],
        textposition="outside",
        textfont=dict(size=11, color="#6A78A8", family="JetBrains Mono"),
        hovertemplate="%{y}: $%{x:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        **_CHART_LAYOUT,
        title=dict(text="<b>Estimated Exposure by Specialty</b>",
                   font=dict(size=13, color="#8A96C8")),
        xaxis=dict(title="Estimated Exposure ($)", **_AXIS_STYLE),
        yaxis=dict(gridcolor="rgba(0,0,0,0)"),
        height=300,
        margin=dict(l=10, r=90, t=44, b=30),
    )
    return fig


def confidence_breakdown_chart(worklist: pd.DataFrame) -> go.Figure:
    counts = worklist["confidence"].value_counts().reindex(
        ["HIGH", "MEDIUM", "LOW"], fill_value=0
    )
    new_colors = {"HIGH": "#F43F5E", "MEDIUM": "#F59E0B", "LOW": "#10B981"}
    colors = [new_colors.get(c, "#6366F1") for c in counts.index]
    fig = go.Figure(go.Pie(
        labels=counts.index.tolist(),
        values=counts.values.tolist(),
        marker=dict(colors=colors, line=dict(color="#06061A", width=3)),
        textinfo="label+percent",
        textfont=dict(size=11, family="Inter"),
        hole=0.6,
        hovertemplate="%{label}: %{value} providers (%{percent})<extra></extra>",
    ))
    fig.update_layout(
        **_CHART_LAYOUT,
        title=dict(text="<b>Confidence Tier Breakdown</b>",
                   font=dict(size=13, color="#8A96C8")),
        height=300,
        legend=dict(orientation="h", y=-0.1, font=dict(size=11, color="#6A78A8")),
        margin=dict(l=10, r=10, t=44, b=30),
    )
    return fig


def score_distribution_chart(worklist: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Histogram(
        x=worklist["risk_score"],
        nbinsx=20,
        marker=dict(
            color=worklist["risk_score"],
            colorscale=[[0, "#1A1A4A"], [0.45, "#6366F1"], [0.75, "#8B5CF6"], [1, "#F43F5E"]],
            line=dict(color="#06061A", width=0.5),
            opacity=0.85,
        ),
        hovertemplate="Score %{x}: %{y} providers<extra></extra>",
    ))
    fig.update_layout(
        **_CHART_LAYOUT,
        title=dict(text="<b>Risk Score Distribution</b>",
                   font=dict(size=13, color="#8A96C8")),
        xaxis=dict(title="Risk Score", **_AXIS_STYLE),
        yaxis=dict(title="Providers",  **_AXIS_STYLE),
        height=280,
        margin=dict(l=10, r=10, t=44, b=30),
        bargap=0.06,
    )
    return fig


def shap_bar_chart(features: list, values: list) -> go.Figure:
    colors = ["#F43F5E" if v > 0 else "#10B981" for v in values]
    fig = go.Figure(go.Bar(
        x=values, y=features, orientation="h",
        marker=dict(color=colors, opacity=0.82,
                    line=dict(color="rgba(0,0,0,0.2)", width=0.5)),
        text=[f"{v:+.4f}" for v in values],
        textposition="outside",
        textfont=dict(size=11, color="#6A78A8", family="JetBrains Mono"),
        hovertemplate="%{y}: %{x:+.4f}<extra></extra>",
    ))
    fig.add_vline(x=0, line_color="rgba(99,102,241,0.35)")
    fig.update_layout(
        **_CHART_LAYOUT,
        title=dict(text="<b>SHAP Feature Attribution</b>",
                   font=dict(size=13, color="#8A96C8")),
        xaxis=dict(title="SHAP value (anomaly contribution)", **_AXIS_STYLE),
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
            badges.append(f'<span class="signal-chip chip-rule">{_icon("exclamation-triangle",11,"#FB7185","margin-right:4px;")} {label}</span>')
    if not peer_df.empty:
        n_peer = len(peer_df[peer_df["provider_id"] == pid])
        if n_peer:
            badges.append(f'<span class="signal-chip chip-peer">{_icon("chart-bar",11,"#A5B4FC","margin-right:4px;")} Peer Outlier ({n_peer} metrics)</span>')
    if not ml_df.empty:
        ml_row = ml_df[ml_df["provider_id"] == pid]
        if not ml_row.empty and ml_row.iloc[0]["ml_is_anomaly"]:
            score = ml_row.iloc[0]["ml_score"]
            badges.append(f'<span class="signal-chip chip-ml">{_icon("cpu-chip",11,"#6EE7B7","margin-right:4px;")} ML Anomaly ({score:.0f}/100)</span>')
    if worklist_row is not None:
        if worklist_row.get("codemix_flag", 0):
            kl = worklist_row.get("kl_divergence", 0)
            badges.append(f'<span class="signal-chip chip-temporal">{_icon("arrows-right-left",11,"#FCD34D","margin-right:4px;")} Code-Mix Drift (KL={kl:.3f})</span>')
        if worklist_row.get("temporal_flag", 0):
            badges.append(f'<span class="signal-chip chip-temporal">{_icon("arrow-trending-up",11,"#FCD34D","margin-right:4px;")} Temporal Change-Point</span>')
        fb = worklist_row.get("feedback_score", 0)
        if fb and float(fb) > 0:
            badges.append(f'<span class="signal-chip chip-feedback">{_icon("arrow-path",11,"#C4B5FD","margin-right:4px;")} Feedback Model ({float(fb):.1f} pts)</span>')
    return " ".join(badges) if badges else '<span style="color:#2D3760;font-size:0.82rem;font-style:italic">No specific signal detected</span>'


# ── Sidebar ───────────────────────────────────────────────────────────────────

def render_sidebar(scores: pd.DataFrame):
    with st.sidebar:
        # ── Brand header ──────────────────────────────────────────────────
        st.markdown(f"""
<div style="padding:20px 4px 18px; text-align:center;">
  <div style="display:inline-flex;align-items:center;justify-content:center;
       width:52px;height:52px;
       background:linear-gradient(145deg,#1E1B55,#2D2A7A);
       border-radius:16px;
       border:1px solid rgba(99,102,241,0.4);
       box-shadow:0 0 24px rgba(99,102,241,0.2);
       margin-bottom:12px;">
    {_icon("clipboard-list", 24, "url(#sb-grad)")}
    <svg width="0" height="0"><defs>
      <linearGradient id="sb-grad" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="#A5B4FC"/><stop offset="100%" stop-color="#67E8F9"/>
      </linearGradient>
    </defs></svg>
  </div>
  <div style="font-size:0.95rem;font-weight:800;
       background:linear-gradient(130deg,#EEF0FF,#A5B4FC 60%,#67E8F9);
       -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;
       letter-spacing:-0.3px;line-height:1.2;margin-bottom:4px;">
    Billing Anomaly<br>Audit System
  </div>
  <div style="font-size:0.58rem;color:#2D3760;letter-spacing:2px;text-transform:uppercase;
       font-family:'JetBrains Mono',monospace;">
    Decision Support Only
  </div>
</div>
<div style="height:1px;background:linear-gradient(90deg,transparent,#1A2050,transparent);margin:0 4px 18px;"></div>
""", unsafe_allow_html=True)

        # ── Filters ───────────────────────────────────────────────────────
        st.markdown('<div style="font-size:0.6rem;font-weight:700;color:#2D3760;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:12px;font-family:\'JetBrains Mono\',monospace;">Filters</div>', unsafe_allow_html=True)

        specs = ["All"] + sorted(scores["specialty"].unique().tolist())
        sel_spec = st.selectbox("Specialty", specs, key="sb_spec")

        conf_opts = ["All", "HIGH", "MEDIUM", "LOW"]
        sel_conf = st.selectbox("Confidence Tier", conf_opts, key="sb_conf")

        min_score = st.slider("Min Risk Score", 0, 100, RISK_THRESHOLD, 5, key="sb_score")

        # ── Quick stats ───────────────────────────────────────────────────
        st.markdown("""<div style="height:1px;background:linear-gradient(90deg,transparent,#1A2050,transparent);margin:18px 4px 16px;"></div>""", unsafe_allow_html=True)
        st.markdown('<div style="font-size:0.6rem;font-weight:700;color:#2D3760;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:12px;font-family:\'JetBrains Mono\',monospace;">Confidence Breakdown</div>', unsafe_allow_html=True)

        flagged = scores[scores["risk_score"] >= RISK_THRESHOLD]
        hi = len(flagged[flagged["confidence"] == "HIGH"])
        me = len(flagged[flagged["confidence"] == "MEDIUM"])
        lo = len(flagged[flagged["confidence"] == "LOW"])
        total = hi + me + lo or 1

        for label, count, color, bg in [
            ("High",   hi, "#FB7185", "rgba(244,63,94,0.1)"),
            ("Medium", me, "#FCD34D", "rgba(245,158,11,0.1)"),
            ("Low",    lo, "#6EE7B7", "rgba(16,185,129,0.1)"),
        ]:
            pct = int(count / total * 100)
            st.markdown(f"""
<div style="margin-bottom:8px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
    <span style="font-size:0.72rem;font-weight:700;color:{color};letter-spacing:0.5px;">{label}</span>
    <span style="font-size:0.72rem;color:#3D4870;font-family:'JetBrains Mono',monospace;">{count}</span>
  </div>
  <div style="background:{bg};border-radius:999px;height:4px;overflow:hidden;">
    <div style="width:{pct}%;height:100%;background:{color};border-radius:999px;
         box-shadow:0 0 8px {color}66;transition:width 0.6s;"></div>
  </div>
</div>
""", unsafe_allow_html=True)

        # ── User card ─────────────────────────────────────────────────────
        st.markdown("""<div style="height:1px;background:linear-gradient(90deg,transparent,#1A2050,transparent);margin:18px 4px 16px;"></div>""", unsafe_allow_html=True)

        _role    = auth.current_role() or "?"
        _display = auth.current_display_name()
        _role_meta = {
            "auditor":    ("#6366F1", "rgba(99,102,241,0.08)"),
            "supervisor": ("#F59E0B", "rgba(245,158,11,0.08)"),
            "admin":      ("#F43F5E", "rgba(244,63,94,0.08)"),
        }
        _rc, _rbg = _role_meta.get(_role, ("#888", "rgba(100,100,100,0.08)"))
        _initials = "".join(p[0].upper() for p in _display.split()[:2])
        st.markdown(f"""
<div style="background:{_rbg};border:1px solid {_rc}30;border-radius:12px;
     padding:12px 14px;margin-bottom:10px;">
  <div style="display:flex;align-items:center;gap:10px;">
    <div style="width:34px;height:34px;border-radius:10px;
         background:linear-gradient(135deg,{_rc}30,{_rc}18);
         border:1px solid {_rc}40;
         display:flex;align-items:center;justify-content:center;
         font-size:0.72rem;font-weight:800;color:{_rc};flex-shrink:0;">
      {_initials}
    </div>
    <div>
      <div style="font-size:0.82rem;font-weight:700;color:#C8D4F0;letter-spacing:-0.1px;">{_display}</div>
      <div style="font-size:0.6rem;color:{_rc};font-family:'JetBrains Mono',monospace;
           text-transform:uppercase;letter-spacing:1px;margin-top:1px;">{_role}</div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

        if st.button("Sign Out", icon=":material/logout:", use_container_width=True, key="btn_logout"):
            auth.logout()

        st.markdown("""<div style="height:1px;background:linear-gradient(90deg,transparent,#1A2050,transparent);margin:16px 4px 14px;"></div>""", unsafe_allow_html=True)
        st.markdown('<div style="font-size:0.6rem;font-weight:700;color:#2D3760;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:8px;font-family:\'JetBrains Mono\',monospace;">Auditor ID</div>', unsafe_allow_html=True)
        auditor_id = st.text_input(
            "Your ID (for audit log)",
            value=st.session_state.get("auditor_id", auth.current_user() or "auditor"),
            key="sb_auditor_id",
            label_visibility="collapsed",
        )
        st.session_state["auditor_id"] = auditor_id

        st.markdown("""<div style="height:1px;background:linear-gradient(90deg,transparent,#1A2050,transparent);margin:14px 4px 14px;"></div>""", unsafe_allow_html=True)
        if st.button("Clear Cache & Reload", icon=":material/refresh:", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        st.markdown('<div style="font-size:0.58rem;color:#1A2050;text-align:center;margin-top:20px;font-family:\'JetBrains Mono\',monospace;letter-spacing:0.5px;">SYNTHETIC DATA ONLY<br>All entities are fictional.</div>', unsafe_allow_html=True)

    return sel_spec, sel_conf, min_score


# ── Main app ──────────────────────────────────────────────────────────────────

def main():
    # ── Authentication gate ───────────────────────────────────────────────────
    if not auth.is_authenticated():
        auth.render_login_screen()   # calls st.stop() if not yet logged in

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
        f'<div class="banner">{_icon("exclamation-triangle",14,"#FCA5A5","margin-right:7px;")} '
        '<strong>SYNTHETIC DATA</strong> — Decision-support tool for human auditors only. '
        'No automated decisions or penalties are applied. All providers and claims are entirely fictional.</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div style="height:4px;"></div>', unsafe_allow_html=True)

    # ── Page header ───────────────────────────────────────────────────────────
    st.markdown("""
<div style="padding: 18px 0 6px;">
  <div style="display:flex; align-items:baseline; gap:10px; flex-wrap:wrap;">
    <h1 style="font-size:clamp(1.5rem,2.2vw,2.1rem); font-weight:800; margin:0;
               letter-spacing:-0.6px; line-height:1.1;
               background:linear-gradient(130deg,#EEF0FF 0%,#A5B4FC 38%,#67E8F9 72%,#A5B4FC 100%);
               background-size:300%;
               -webkit-background-clip:text; background-clip:text;
               -webkit-text-fill-color:transparent;">
      Physician Billing Anomaly Detection
    </h1>
  </div>
  <p style="font-size:0.78rem; color:#2D3760; margin-top:6px; letter-spacing:0.2px;">
    Dollar-ranked proactive audit worklist &nbsp;·&nbsp; Rules + Peer Stats + ML Ensemble &nbsp;·&nbsp; Human review required for all flags
  </p>
</div>
""", unsafe_allow_html=True)

    # ── KPI cards ─────────────────────────────────────────────────────────────
    all_flagged = scores[scores["risk_score"] >= RISK_THRESHOLD]
    total_exposure = all_flagged["estimated_exposure"].sum()
    n_flagged      = len(all_flagged)
    n_proactive    = len(all_flagged[
        (all_flagged["rules_score"] == 0) &
        ((all_flagged["peer_score"] > 0) | (all_flagged["ml_is_anomaly"] == 1))
    ])
    top_exposure = all_flagged["estimated_exposure"].max()

    st.markdown('<div style="height:10px;"></div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    kpis = [
        (c1, _icon("banknotes",26,"#6EE7B7"),          "#10B981", "Total Flagged Exposure", f"${total_exposure:,.0f}", "Sum of est. exposure for all flagged providers"),
        (c2, _icon("bell-alert",26,"#FB7185"),         "#F43F5E", "Providers Flagged",       str(n_flagged),            f"Risk score ≥ {RISK_THRESHOLD}"),
        (c3, _icon("magnifying-glass",26,"#A5B4FC"),   "#6366F1", "Proactive Finds",          str(n_proactive),          "Stats/ML — not complaint-driven"),
        (c4, _icon("map-pin",26,"#FCD34D"),            "#F59E0B", "Top Single Exposure",      f"${top_exposure:,.0f}",   "Highest individual estimated exposure"),
    ]
    for col, icon, accent, label, value, sub in kpis:
        with col:
            st.markdown(f"""
            <div class="kpi-card" style="--kpi-accent:{accent};">
              <div style="position:absolute;top:0;left:0;bottom:0;width:3px;
                background:linear-gradient(180deg,{accent},transparent);border-radius:4px 0 0 4px;"></div>
              <div class="kpi-icon">{icon}</div>
              <div class="kpi-label">{label}</div>
              <div class="kpi-value">{value}</div>
              <div class="kpi-sub">{sub}</div>
            </div>
            """, unsafe_allow_html=True)

    # ── Tabs ─────────────────────────────────────────────────────────────────
    st.markdown('<div style="height:16px;"></div>', unsafe_allow_html=True)
    tab_wl, tab_analytics, tab_model, tab_audit = st.tabs(
        ["🗂 Worklist", "📊 Analytics", "🧠 Model Card", "📋 Audit Trail"]
    )
    # Role labels for the access-denied banners below
    _can_model = auth.has_permission("view_model_card")
    _can_audit = auth.has_permission("view_audit_trail")

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
                f"Access restricted — Role **{auth.current_role()}** "
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
                f"Access restricted — Role **{auth.current_role()}** "
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

            col_v, col_e, col_spacer = st.columns([3, 3, 4])
            with col_v:
                _vi_clicked = st.button("Verify Integrity", icon=":material/shield:", key="audit_verify", use_container_width=True)
            with col_e:
                _ex_clicked = st.button("Export to CSV", icon=":material/download:", key="audit_export", use_container_width=True)

            if _vi_clicked:
                try:
                    # ── Function-level gate (second line of defence) ──────
                    auth.require_permission("verify_integrity")
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

            if _ex_clicked:
                try:
                    # ── Function-level gate (second line of defence) ──────
                    auth.require_permission("export_audit_log")
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
    # Convert to dict so .get() calls below are dict lookups, not the deprecated
    # pd.Series.get() which raises FutureWarning in pandas 2.1+ and is removed in 3.0.
    prow       = worklist[worklist["provider_id"] == pid].iloc[0].to_dict()
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
          <div class="prov-stat-value" style="color:{{'HIGH':'#FB7185','MEDIUM':'#FCD34D','LOW':'#6EE7B7'}}.get('{confidence}','#CCC')">{risk_score:.0f} / 100</div>
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
    st.markdown('<div style="font-size:0.62rem;font-weight:700;color:#2D3760;text-transform:uppercase;letter-spacing:1.3px;margin-bottom:8px;font-family:\'JetBrains Mono\',monospace;">Active Signals</div>', unsafe_allow_html=True)
    st.markdown(signal_badges(pid, rules, peer, ml, prow), unsafe_allow_html=True)
    st.markdown('<div style="height:12px;"></div>', unsafe_allow_html=True)

    # ── Auditor action buttons ────────────────────────────────────────────────
    st.markdown(
        '<div style="font-size:0.62rem;font-weight:700;color:#2D3760;text-transform:uppercase;'
        'letter-spacing:1.3px;margin-bottom:8px;font-family:\'JetBrains Mono\',monospace;">'
        'Record Disposition (logged to audit trail)</div>',
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

    btn_c, btn_cl, btn_i, _ = st.columns([2, 2, 3, 2])

    with btn_c:
        _confirm_clicked = st.button("Confirm", icon=":material/check:", key=f"btn_confirm_{pid}", type="primary", use_container_width=True)
    with btn_cl:
        _clear_clicked = st.button("Clear", icon=":material/close:", key=f"btn_clear_{pid}", use_container_width=True)
    with btn_i:
        _invest_clicked = st.button("Investigating", icon=":material/flag:", key=f"btn_invest_{pid}", use_container_width=True)

    if _confirm_clicked:
        try:
            auth.require_permission("take_action")   # function-level gate
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

    if _clear_clicked:
        try:
            auth.require_permission("take_action")   # function-level gate
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

    if _invest_clicked:
        try:
            auth.require_permission("take_action")   # function-level gate
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
            ["⚠ Rule Evidence", "📈 Peer Comparison", "📅 Monthly Volume", "🔍 Explanation"]
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
                    shap_r = shap_row.iloc[0].to_dict()
                    feats  = shap_r["top_features"].split(";")[:3]
                    vals   = [float(shap_r.get(f"shap_top{i}_val", 0))
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

            _has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
            _expl_label = (
                "Audit summary (AI-enriched via Claude):"
                if _has_key else
                "Audit summary (template — set ANTHROPIC_API_KEY for AI-enriched):"
            )
            if pid in expls:
                _is_ai = "[Generated with Anthropic API]" in expls[pid]["explanation"]
                if _has_key and not _is_ai:
                    if st.button("Regenerate with Claude", icon=":material/auto_awesome:", key=f"regen_expl_{pid}"):
                        with st.spinner("Calling Claude…"):
                            from explain import build_explanations
                            build_explanations(use_api=True)
                            st.cache_data.clear()
                        st.rerun()
                st.text_area(
                    _expl_label,
                    value=expls[pid]["explanation"],
                    height=260,
                    key=f"expl_{pid}",
                )
            else:
                st.info("Explanation not pre-generated for this provider.")
                if st.button("Generate explanation now", icon=":material/auto_awesome:", key=f"gen_expl_{pid}"):
                    with st.spinner("Calling Claude…" if _has_key else "Building template…"):
                        from explain import build_explanations
                        build_explanations(use_api=_has_key)
                        st.cache_data.clear()
                    st.rerun()


if __name__ == "__main__":
    main()
