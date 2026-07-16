"""
dashboard.py — Social Inbox Autopilot: Production Dashboard v3

Run:
    streamlit run dashboard.py

Tabs:
  1. Inbox          — awaiting_approval: approve / edit+approve / reject
                      Now includes: A/B draft toggle, batch approve, smart badges
  2. Escalated      — critical events, routing team assignment
  3. Analytics      — tier distribution, intent/platform/language charts,
                       brand health score, SLA compliance, crisis history,
                       root-cause breakdown, cluster spike chart, SLA prediction
  4. History        — sent + rejected + auto events with CRM tags + audit trail
                       Now includes: edit diff badge, PII flag
  5. Intelligence   — proactive outreach, emotion recovery follow-up, VOC digest

Sidebar:
  - Live status counters
  - Brand crisis alert banner
  - SLA breach warnings + SLA-at-risk prediction
  - Intent cluster spike alert
  - Run Triage / Process Approved / Seed / Clear controls
  - Webhook ingestion instructions
"""

import os
import json
import time
import html
from datetime import datetime, timezone

import streamlit as st
from dotenv import load_dotenv
try:
    import plotly.graph_objects as go
    import plotly.express as px
    _PLOTLY = True
except ImportError:
    _PLOTLY = False

load_dotenv()

# ---------------------------------------------------------------------------
# Auth import (must happen before st.session_state access)
# ---------------------------------------------------------------------------
try:
    from auth import check_login, users_exist, add_user
    _AUTH_AVAILABLE = True
except ImportError:
    _AUTH_AVAILABLE = False

st.set_page_config(
    page_title="LoopBack — AI Social Autopilot",
    page_icon="🔂",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Global CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=Space+Grotesk:wght@300;400;500;600;700&display=swap');

/* ── CSS Variables ───────────────────────────────────────────────────────── */
:root {
  --bg-deep:      #07050e;
  --bg-base:      #0a0815;
  --bg-card:      rgba(20, 16, 35, 0.65);
  --bg-glass:     rgba(255,255,255,0.02);
  --border-card:  rgba(6, 182, 212, 0.15);
  --border-glow:  rgba(6, 182, 212, 0.45);
  --accent-blue:  #00f2fe;
  --accent-purple:#8b5cf6;
  --accent-green: #10b981;
  --accent-red:   #ef4444;
  --accent-amber: #f59e0b;
  --accent-cyan:  #06b6d4;
  --accent-pink:  #ec4899;
  --text-primary: #f8fafc;
  --text-secondary:#94a3b8;
  --text-muted:   #5b5180;
  --radius-card:  16px;
  --radius-tag:   99px;
  --shadow-card:  0 8px 32px rgba(0,0,0,0.5);
  --shadow-glow:  0 0 20px rgba(6,182,212,0.08);
}

/* ── Base & Font ─────────────────────────────────────────────────────────── */
html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"] {
  font-family: 'Outfit', 'Space Grotesk', sans-serif !important;
}

/* ── Static Mesh Background (perf-optimised) ──────────────────────────────── */
[data-testid="stAppViewContainer"] {
  background: var(--bg-deep) !important;
}
[data-testid="stAppViewContainer"]::before {
  content: '';
  position: fixed;
  inset: 0;
  background:
    radial-gradient(ellipse 80% 60% at 15% 40%, rgba(6,182,212,0.08) 0%, transparent 60%),
    radial-gradient(ellipse 60% 50% at 85% 15%, rgba(139,92,246,0.08) 0%, transparent 55%),
    radial-gradient(ellipse 70% 70% at 50% 90%, rgba(10,185,129,0.04) 0%, transparent 60%),
    radial-gradient(ellipse 50% 40% at 70% 55%, rgba(0,242,254,0.04) 0%, transparent 50%);
  /* Only animate opacity — runs on compositor, no layout/paint cost */
  animation: meshFade 20s ease-in-out infinite alternate;
  will-change: opacity;
  pointer-events: none;
  z-index: 0;
}
@keyframes meshFade {
  0%   { opacity: 0.85; }
  100% { opacity: 1; }
}

/* ── Sidebar ─────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
  background: rgba(8, 6, 16, 0.75) !important;
  border-right: 1px solid rgba(6, 182, 212, 0.12) !important;
  backdrop-filter: blur(24px);
}
[data-testid="stSidebar"] .stMarkdown h2 {
  background: linear-gradient(135deg, #00f2fe, #8b5cf6);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  font-weight: 700;
  letter-spacing: -0.02em;
}

/* ── Typography ──────────────────────────────────────────────────────────── */
h1, h2, h3, h4 { color: var(--text-primary) !important; font-family: 'Outfit', sans-serif !important; }
.page-header {
  background: linear-gradient(135deg, #fff 0%, #a78bfa 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  font-size: 2.4rem;
  font-weight: 800;
  letter-spacing: -0.04em;
  line-height: 1.1;
  margin: 0 0 4px 0;
}
.page-sub {
  color: var(--text-muted);
  font-size: 0.85rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  font-weight: 600;
}

/* ── Glassmorphism Cards ─────────────────────────────────────────────────── */
.event-card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-card);
  padding: 20px 22px 16px;
  margin-bottom: 16px;
  box-shadow: var(--shadow-card), var(--shadow-glow);
  /* Reduced blur for scroll performance; contain keeps repaint local */
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  contain: layout style;
  transition: border-color 0.25s ease, box-shadow 0.25s ease, transform 0.2s ease;
  position: relative;
  overflow: hidden;
}
.event-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  background: linear-gradient(90deg, #00f2fe, #8b5cf6, #06b6d4);
  opacity: 0.8;
}
.event-card:hover {
  border-color: var(--border-glow);
  box-shadow: var(--shadow-card), 0 0 28px rgba(6, 182, 212, 0.2);
  transform: translateY(-1px);
}

.event-card-escalated {
  background: rgba(36, 12, 20, 0.75);
  border: 1px solid rgba(239, 68, 68, 0.25);
  border-radius: var(--radius-card);
  padding: 20px 22px 16px;
  margin-bottom: 16px;
  box-shadow: var(--shadow-card), 0 0 24px rgba(239, 68, 68, 0.1);
  backdrop-filter: blur(16px);
  position: relative;
  overflow: hidden;
  transition: border-color 0.25s ease, transform 0.2s ease;
}
.event-card-escalated::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  background: linear-gradient(90deg, #ef4444, #f97316);
}
.event-card-escalated:hover {
  border-color: rgba(239, 68, 68, 0.5);
  transform: translateY(-1px);
}

.event-card-history {
  background: rgba(14, 11, 26, 0.7);
  border: 1px solid rgba(6, 182, 212, 0.1);
  border-radius: 12px;
  padding: 14px 18px 12px;
  margin-bottom: 10px;
  backdrop-filter: blur(10px);
  transition: border-color 0.2s ease;
}
.event-card-history:hover {
  border-color: rgba(6, 182, 212, 0.3);
}

/* ── Intelligence Cards ──────────────────────────────────────────────────── */
.intel-card {
  background: rgba(16, 12, 30, 0.75);
  border: 1px solid rgba(6, 182, 212, 0.15);
  border-radius: 14px;
  padding: 18px 20px;
  margin-bottom: 14px;
  backdrop-filter: blur(12px);
  transition: border-color 0.2s, transform 0.2s;
}
.intel-card:hover {
  border-color: rgba(6, 182, 212, 0.4);
  transform: translateY(-1px);
}
.intel-card-recovery {
  background: rgba(10, 32, 26, 0.7);
  border: 1px solid rgba(16, 185, 129, 0.2);
  border-radius: 14px;
  padding: 18px 20px;
  margin-bottom: 14px;
  backdrop-filter: blur(12px);
}
.digest-section {
  background: rgba(22, 14, 40, 0.75);
  border: 1px solid rgba(139, 92, 246, 0.2);
  border-radius: 14px;
  padding: 20px 22px;
  margin-bottom: 14px;
  backdrop-filter: blur(12px);
}

/* ── Crisis Banner ───────────────────────────────────────────────────────── */
.crisis-banner {
  background: linear-gradient(135deg, rgba(127,29,29,0.95), rgba(153,27,27,0.9));
  border: 1px solid rgba(239,68,68,0.5);
  border-radius: 12px;
  padding: 14px 18px;
  margin-bottom: 16px;
  color: #fef2f2;
  font-weight: 600;
  font-size: 0.95rem;
  box-shadow: 0 4px 20px rgba(239,68,68,0.25);
  backdrop-filter: blur(8px);
  animation: pulseCrisis 2s ease-in-out infinite;
}
@keyframes pulseCrisis {
  0%, 100% { box-shadow: 0 4px 20px rgba(239,68,68,0.25); }
  50%       { box-shadow: 0 4px 32px rgba(239,68,68,0.45); }
}

@keyframes pulseSla {
  0% { box-shadow: 0 0 2px #ef4444; opacity: 0.7; }
  100% { box-shadow: 0 0 12px #ef4444; opacity: 1; }
}
.sla-progress-breached {
  animation: pulseSla 1s infinite alternate;
}

/* ── SLA Warning ─────────────────────────────────────────────────────────── */
.sla-warning {
  background: rgba(45,28,5,0.8);
  border: 1px solid rgba(217,119,6,0.4);
  border-radius: 8px;
  padding: 9px 14px;
  margin-bottom: 8px;
  color: #fbbf24;
  font-size: 0.83rem;
  backdrop-filter: blur(4px);
}
.sla-predict {
  background: rgba(30,18,5,0.8);
  border: 1px solid rgba(249,115,22,0.4);
  border-radius: 8px;
  padding: 9px 14px;
  margin-bottom: 8px;
  color: #fb923c;
  font-size: 0.83rem;
  backdrop-filter: blur(4px);
  animation: pulseAmber 3s ease-in-out infinite;
}
@keyframes pulseAmber {
  0%, 100% { border-color: rgba(249,115,22,0.4); }
  50%       { border-color: rgba(249,115,22,0.7); }
}
.cluster-spike {
  background: rgba(30,10,30,0.85);
  border: 1px solid rgba(236,72,153,0.4);
  border-radius: 8px;
  padding: 9px 14px;
  margin-bottom: 8px;
  color: #f472b6;
  font-size: 0.83rem;
  backdrop-filter: blur(4px);
  animation: pulseSpike 2s ease-in-out infinite;
}
@keyframes pulseSpike {
  0%, 100% { box-shadow: none; }
  50%       { box-shadow: 0 0 12px rgba(236,72,153,0.25); }
}

/* ── Legal Block Banner ──────────────────────────────────────────────────── */
.legal-block-banner {
  background: rgba(50,5,5,0.95);
  border: 1px solid rgba(239,68,68,0.6);
  border-radius: 8px;
  padding: 9px 14px;
  margin: 8px 0;
  color: #fca5a5;
  font-size: 0.83rem;
  font-weight: 600;
  letter-spacing: 0.02em;
}

/* ── Tags / Badges ───────────────────────────────────────────────────────── */
.tag {
  display: inline-block;
  padding: 3px 10px;
  border-radius: var(--radius-tag);
  font-size: 0.70rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  margin-right: 4px;
  text-transform: uppercase;
  transition: opacity 0.2s;
}
.tag-platform { background: rgba(14, 22, 45, 0.8);  color: #00f2fe;  border: 1px solid rgba(6, 182, 212, 0.35); }
.tag-intent   { background: rgba(16,42,16,0.8);  color: #4ade80;  border: 1px solid rgba(74,222,128,0.2); }
.tag-urg-low  { background: rgba(20,41,20,0.8);  color: #86efac;  border: 1px solid rgba(134,239,172,0.15); }
.tag-urg-med  { background: rgba(42,34,10,0.8);  color: #fcd34d;  border: 1px solid rgba(252,211,77,0.2); }
.tag-urg-hi   { background: rgba(45,16,16,0.8);  color: #f87171;  border: 1px solid rgba(248,113,113,0.2); }
.tag-urg-crit { background: rgba(76,5,25,0.9);   color: #fda4af;  border: 1px solid rgba(253,164,175,0.3); animation: pulseTag 1.5s ease infinite; }
@keyframes pulseTag {
  0%,100% { opacity: 1; }  50% { opacity: 0.75; }
}
.tag-risk-low { background: rgba(20,41,26,0.8);  color: #22c55e;  border: 1px solid rgba(34,197,94,0.2); }
.tag-risk-mid { background: rgba(42,34,10,0.8);  color: #f59e0b;  border: 1px solid rgba(245,158,11,0.2); }
.tag-risk-hi  { background: rgba(45,16,16,0.8);  color: #f87171;  border: 1px solid rgba(248,113,113,0.2); }
.tag-sent     { background: rgba(5,46,22,0.8);   color: #34d399;  border: 1px solid rgba(52,211,153,0.25); }
.tag-rejected { background: rgba(45,16,16,0.8);  color: #f87171;  border: 1px solid rgba(248,113,113,0.2); }
.tag-auto     { background: rgba(5,46,22,0.8);   color: #34d399;  border: 1px solid rgba(52,211,153,0.25); }
.tag-fallback { background: rgba(26,26,45,0.8);  color: #a78bfa;  border: 1px solid rgba(167,139,250,0.2); }
.tag-sla      { background: rgba(45,28,5,0.8);   color: #fbbf24;  border: 1px solid rgba(251,191,36,0.25); }
.tag-cluster  { background: rgba(30,10,30,0.8);  color: #e879f9;  border: 1px solid rgba(232,121,249,0.2); }
.tag-sarcasm  { background: rgba(40,30,5,0.9);   color: #fde68a;  border: 1px solid rgba(253,230,138,0.3); animation: pulseTag 2s ease infinite; }
.tag-legal    { background: rgba(60,5,5,0.95);   color: #fca5a5;  border: 1px solid rgba(252,165,165,0.4); animation: pulseTag 1.2s ease infinite; }
.tag-escalating { background: rgba(40,15,5,0.9); color: #fb923c;  border: 1px solid rgba(251,146,60,0.3); }
.tag-stable   { background: rgba(5,25,15,0.8);   color: #6ee7b7;  border: 1px solid rgba(110,231,183,0.2); }
.tag-route-billing { background: rgba(5,25,40,0.85); color: #67e8f9; border: 1px solid rgba(103,232,249,0.25); }
.tag-route-eng     { background: rgba(20,5,40,0.85); color: #c4b5fd; border: 1px solid rgba(196,181,253,0.25); }
.tag-route-comms   { background: rgba(40,5,20,0.85); color: #fda4af; border: 1px solid rgba(253,164,175,0.25); }
.tag-route-general { background: rgba(13,18,38,0.8); color: #94a3b8; border: 1px solid rgba(148,163,184,0.15); }
.tag-conf-hi  { background: rgba(5,30,5,0.8);    color: #4ade80;  border: 1px solid rgba(74,222,128,0.2); }
.tag-conf-mid { background: rgba(35,30,5,0.8);   color: #fbbf24;  border: 1px solid rgba(251,191,36,0.2); }
.tag-conf-low { background: rgba(40,10,10,0.8);  color: #f87171;  border: 1px solid rgba(248,113,113,0.2); }
.tag-edit     { background: rgba(20,5,40,0.85);  color: #a78bfa;  border: 1px solid rgba(167,139,250,0.25); }
.tag-pii      { background: rgba(50,20,5,0.9);   color: #fdba74;  border: 1px solid rgba(253,186,116,0.3); }

/* ── Content Boxes ───────────────────────────────────────────────────────── */
.msg-box {
  background: rgba(14, 22, 45, 0.6);
  border-left: 3px solid var(--accent-blue);
  border-radius: 8px;
  padding: 10px 14px;
  color: #e2e8f0;
  font-size: 0.94rem;
  margin: 10px 0;
  line-height: 1.5;
}
.reason-box {
  background: rgba(20, 15, 40, 0.6);
  border-left: 3px solid var(--accent-purple);
  border-radius: 8px;
  padding: 8px 12px;
  color: #c4b5fd;
  font-size: 0.82rem;
  margin: 6px 0;
}
.draft-box {
  background: rgba(5, 30, 26, 0.6);
  border-left: 3px solid var(--accent-green);
  border-radius: 8px;
  padding: 8px 12px;
  color: #a7f3d0;
  font-size: 0.87rem;
  margin: 6px 0;
}
.draft-box-alt {
  background: rgba(22, 10, 45, 0.6);
  border-left: 3px solid var(--accent-purple);
  border-radius: 8px;
  padding: 8px 12px;
  color: #ddd6fe;
  font-size: 0.87rem;
  margin: 6px 0;
}
.crm-box {
  background: rgba(5, 28, 40, 0.6);
  border-left: 3px solid var(--accent-cyan);
  border-radius: 8px;
  padding: 7px 12px;
  color: #7dd3fc;
  font-size: 0.80rem;
  margin: 6px 0;
}
.translation-box {
  background: rgba(6, 182, 212, 0.05);
  border-left: 3px dashed var(--accent-cyan);
  border-radius: 8px;
  padding: 8px 12px;
  color: #94a3b8;
  font-size: 0.84rem;
  margin: 6px 0 10px;
}
.batch-box {
  background: rgba(14, 22, 45, 0.7);
  border: 1px solid rgba(6, 182, 212, 0.2);
  border-radius: 12px;
  padding: 14px 18px;
  margin-bottom: 16px;
  backdrop-filter: blur(8px);
}

/* ── Metric Cards ────────────────────────────────────────────────────────── */
.metric-card {
  background: rgba(16, 12, 30, 0.7);
  border: 1px solid rgba(6, 182, 212, 0.15);
  border-radius: 12px;
  padding: 12px 16px;
  text-align: center;
  backdrop-filter: blur(12px);
  transition: border-color 0.2s, transform 0.2s;
}
.metric-card:hover {
  border-color: rgba(6, 182, 212, 0.4);
  transform: translateY(-1px);
}
.stat-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(16, 12, 30, 0.5);
  border: 1px solid rgba(6, 182, 212, 0.1);
  border-radius: 10px;
  padding: 8px 12px;
  margin-bottom: 5px;
  transition: background 0.2s;
}
.stat-row:hover { background: rgba(16, 12, 30, 0.8); }
.stat-val  { font-size: 1.35rem; font-weight: 700; }
.stat-label{ font-size: 0.73rem; color: var(--text-muted); }
.health-score { font-size: 2.8rem; font-weight: 800; letter-spacing: -0.03em; }

/* ── Tabs ────────────────────────────────────────────────────────────────── */
[data-testid="stTabs"] [role="tab"] {
  font-family: 'Outfit', sans-serif !important;
  font-weight: 600;
  color: var(--text-secondary) !important;
  transition: color 0.2s;
  border-bottom: 2px solid transparent !important;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
  color: var(--accent-blue) !important;
  border-bottom: 2px solid var(--accent-blue) !important;
}

/* ── Streamlit Default Overrides ─────────────────────────────────────────── */
.stButton > button {
  font-family: 'Outfit', sans-serif !important;
  font-weight: 600;
  border-radius: 8px !important;
  transition: all 0.2s ease !important;
  background: rgba(16, 12, 30, 0.8) !important;
  border: 1px solid rgba(6, 182, 212, 0.25) !important;
  color: #e2e8f0 !important;
}
.stButton > button:hover {
  transform: translateY(-1px);
  border-color: rgba(6, 182, 212, 0.6) !important;
  box-shadow: 0 0 12px rgba(6, 182, 212, 0.25) !important;
  color: #ffffff !important;
}
.stButton > button[kind="primary"] {
  background: linear-gradient(135deg, #00f2fe, #8b5cf6) !important;
  border: none !important;
  color: #07050e !important;
  font-weight: 700 !important;
}
.stButton > button[kind="primary"]:hover {
  box-shadow: 0 0 18px rgba(0, 242, 254, 0.4) !important;
}
[data-testid="stMetricValue"] { font-family: 'Outfit', sans-serif !important; font-weight: 700; }
[data-testid="stMetricLabel"] { font-family: 'Outfit', sans-serif !important; color: var(--text-muted) !important; }
div[data-testid="stMarkdownContainer"] p { color: var(--text-secondary); }

/* ── Sidebar Control Sections ────────────────────────────────────────────── */
.ctrl-section {
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #5b5180;
  margin: 18px 0 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.ctrl-section::after {
  content: '';
  flex: 1;
  height: 1px;
  background: rgba(6, 182, 212, 0.12);
}
.stat-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 5px;
  margin-bottom: 8px;
}
.stat-chip {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: rgba(16, 12, 30, 0.6);
  border: 1px solid rgba(6, 182, 212, 0.15);
  border-radius: 10px;
  padding: 7px 6px 5px;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.stat-chip:hover {
  border-color: rgba(6, 182, 212, 0.4);
  box-shadow: 0 0 10px rgba(6, 182, 212, 0.15);
}
.stat-chip-val  { font-size: 1.2rem; font-weight: 700; line-height: 1; }
.stat-chip-lbl  { font-size: 0.62rem; color: #5b5180; margin-top: 2px; text-align: center; font-weight: 600; }

/* ── Root-cause breakdown bar ────────────────────────────────────────────── */
.rootcause-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}
.rootcause-bar-wrap {
  flex: 1;
  height: 8px;
  background: rgba(255,255,255,0.05);
  border-radius: 99px;
  overflow: hidden;
}
.rootcause-bar-fill {
  height: 100%;
  border-radius: 99px;
  transition: width 0.4s ease;
}
.rootcause-label {
  font-size: 0.78rem;
  color: #94a3b8;
  min-width: 130px;
}
.rootcause-pct {
  font-size: 0.78rem;
  font-weight: 600;
  color: #e2e8f0;
  min-width: 35px;
  text-align: right;
}

/* ── Scrollbar ───────────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: rgba(8, 6, 16, 0.2); }
::-webkit-scrollbar-thumb { background: rgba(6, 182, 212, 0.4); border-radius: 99px; border: 2px solid transparent; background-clip: padding-box; }
::-webkit-scrollbar-thumb:hover { background: rgba(6, 182, 212, 0.7); border-radius: 99px; border: 2px solid transparent; background-clip: padding-box; }

/* ── AI Assistant Card in Overview ───────────────────────────────────────── */
.ai-assistant-panel {
  background: linear-gradient(135deg, rgba(20, 16, 35, 0.8), rgba(10, 8, 20, 0.85));
  border: 1px solid rgba(6, 182, 212, 0.25);
  border-radius: 16px;
  padding: 22px 24px;
  margin-bottom: 24px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.5), 0 0 24px rgba(6, 182, 212, 0.1);
  backdrop-filter: blur(16px);
  position: relative;
  overflow: hidden;
}
.ai-assistant-panel::before {
  content: '';
  position: absolute;
  top: -50%; left: -50%; width: 200%; height: 200%;
  background: radial-gradient(circle at 75% 25%, rgba(6, 182, 212, 0.08) 0%, transparent 50%);
  pointer-events: none;
}
.ai-assistant-flex {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}
.ai-assistant-details {
  flex: 1;
}
.ai-pulse-container {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.ai-pulse-dot {
  width: 7px;
  height: 7px;
  background-color: #00f2fe;
  border-radius: 50%;
  box-shadow: 0 0 10px #00f2fe, 0 0 20px rgba(0,242,254,0.5);
  animation: pulseCore 1.8s infinite ease-in-out;
}
.ai-pulse-label {
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: #00f2fe;
  text-transform: uppercase;
}
.ai-assistant-heading {
  font-size: 1.45rem;
  font-weight: 700;
  margin: 0 0 8px 0;
  color: #ffffff !important;
  background: linear-gradient(135deg, #ffffff, #94a3b8);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.ai-assistant-text {
  font-size: 0.85rem;
  line-height: 1.45;
  color: #94a3b8;
  margin: 0 0 16px 0;
}
.ai-assistant-meta {
  display: flex;
  gap: 20px;
}
.ai-meta-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.76rem;
  color: #cbd5e1;
}
.ai-meta-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
}
.ai-assistant-graphics {
  width: 180px;
  height: 130px;
  display: flex;
  justify-content: center;
  align-items: center;
  position: relative;
}
.ai-svg-canvas {
  overflow: visible;
}
.float-shard-1 {
  animation: floatShard1 6s infinite ease-in-out;
  transform-origin: 70px 95px;
}
.float-shard-2 {
  animation: floatShard2 7s infinite ease-in-out;
  transform-origin: 120px 50px;
}
.float-shard-3 {
  animation: floatShard3 5s infinite ease-in-out;
  transform-origin: 95px 32px;
}
.core-pulse {
  animation: pulseCore 2.5s infinite ease-in-out;
  box-shadow: 0 0 15px rgba(0, 242, 254, 0.8);
}
@keyframes floatShard1 {
  0%, 100% { transform: translateY(0px) rotate(0deg); }
  50% { transform: translateY(-4px) rotate(1deg); }
}
@keyframes floatShard2 {
  0%, 100% { transform: translateY(0px) rotate(0deg); }
  50% { transform: translateY(5px) rotate(-1.5deg); }
}
@keyframes floatShard3 {
  0%, 100% { transform: translateY(0px) rotate(0deg); }
  50% { transform: translateY(-2px) rotate(0.8deg); }
}
@keyframes pulseCore {
  0%, 100% { opacity: 0.7; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.1); }
}

/* ── AI Assistor Card ── */
.ai-assist-card {
  background: linear-gradient(135deg, rgba(30, 20, 50, 0.75), rgba(15, 10, 30, 0.85)) !important;
  border: 1px dashed rgba(139, 92, 246, 0.4) !important;
  border-radius: 12px !important;
  padding: 16px 18px !important;
  margin: 14px 0 !important;
  box-shadow: 0 4px 16px rgba(0,0,0,0.3) !important;
  backdrop-filter: blur(12px);
  position: relative !important;
}
.ai-assist-card::before {
  content: '🤖 AI ASSISTOR' !important;
  position: absolute !important;
  top: -9px !important;
  right: 12px !important;
  background: #8b5cf6 !important;
  color: #ffffff !important;
  font-size: 0.65rem !important;
  font-weight: 700 !important;
  padding: 2px 8px !important;
  border-radius: 4px !important;
  letter-spacing: 0.05em !important;
}
.ai-assist-title {
  font-size: 0.95rem !important;
  font-weight: 600 !important;
  color: #a78bfa !important;
  margin-bottom: 10px !important;
}
.ai-assist-section {
  font-size: 0.84rem !important;
  color: #cbd5e1 !important;
  margin-bottom: 8px !important;
  line-height: 1.4 !important;
}
.ai-assist-step-item {
  font-size: 0.82rem !important;
  color: #94a3b8 !important;
  margin-left: 12px !important;
  margin-bottom: 4px !important;
}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Login Gate — must pass before ANY dashboard content renders
# ---------------------------------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
    st.session_state["current_user"]  = None

if _AUTH_AVAILABLE and not st.session_state["authenticated"]:
    # ── Full-screen login page ──────────────────────────────────────────────
    st.markdown("""
    <style>
    /* Hide sidebar on login page */
    [data-testid="stSidebar"] { display: none !important; }
    /* Center login card */
    .login-outer {
      display: flex; align-items: center; justify-content: center;
      min-height: 85vh;
    }
    .login-card {
      background: rgba(14, 11, 26, 0.85);
      border: 1px solid rgba(6, 182, 212, 0.25);
      border-radius: 20px;
      padding: 48px 44px 40px;
      max-width: 420px;
      width: 100%;
      box-shadow: 0 24px 64px rgba(0,0,0,0.6), 0 0 40px rgba(6,182,212,0.08);
      backdrop-filter: blur(24px);
      position: relative;
      overflow: hidden;
    }
    .login-card::before {
      content: '';
      position: absolute; top: 0; left: 0; right: 0; height: 3px;
      background: linear-gradient(90deg, #00f2fe, #8b5cf6, #ec4899);
    }
    .login-logo {
      text-align: center; margin-bottom: 28px;
    }
    .login-logo-icon {
      display: inline-flex; align-items: center; justify-content: center;
      width: 64px; height: 64px; border-radius: 16px;
      background: linear-gradient(135deg, rgba(6,182,212,0.15), rgba(139,92,246,0.15));
      border: 1px solid rgba(6,182,212,0.3);
      margin-bottom: 12px;
      box-shadow: 0 0 20px rgba(6,182,212,0.15);
    }
    .login-title {
      font-size: 1.9rem; font-weight: 800;
      background: linear-gradient(135deg, #00f2fe, #8b5cf6);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
      background-clip: text; letter-spacing: -0.04em;
    }
    .login-subtitle {
      font-size: 0.75rem; color: #5b5180; letter-spacing: 0.1em;
      text-transform: uppercase; font-weight: 600; margin-top: 4px;
    }
    .login-heading {
      font-size: 1.1rem; font-weight: 600; color: #e2e8f0;
      margin-bottom: 20px; text-align: center;
    }
    /* Style the Streamlit inputs on login page */
    .stTextInput > div > div > input {
      background: rgba(255,255,255,0.04) !important;
      border: 1px solid rgba(6,182,212,0.2) !important;
      border-radius: 10px !important;
      color: #e2e8f0 !important;
      font-size: 0.95rem !important;
      padding: 10px 14px !important;
    }
    .stTextInput > div > div > input:focus {
      border-color: rgba(6,182,212,0.55) !important;
      box-shadow: 0 0 0 2px rgba(6,182,212,0.1) !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── Centered login form ─────────────────────────────────────────────────
    col_l, col_center, col_r = st.columns([1, 1.4, 1])
    with col_center:
        st.markdown("""
        <div class="login-card">
          <div class="login-logo">
            <div class="login-logo-icon">
              <svg width="34" height="34" viewBox="0 0 24 24" fill="none">
                <path d="M17 6H13C10.79 6 9 7.79 9 10s1.79 4 4 4h4c2.21 0 4-1.79 4-4s-1.79-4-4-4z"
                      stroke="url(#lg1)" stroke-width="2" stroke-linecap="round"/>
                <path d="M7 10H11C13.21 10 15 11.79 15 14s-1.79 4-4 4H7c-2.21 0-4-1.79-4-4s1.79-4 4-4z"
                      stroke="url(#lg2)" stroke-width="2" stroke-linecap="round"/>
                <defs>
                  <linearGradient id="lg1" x1="9" y1="10" x2="21" y2="10" gradientUnits="userSpaceOnUse">
                    <stop stop-color="#00f2fe"/><stop offset="1" stop-color="#4facfe"/>
                  </linearGradient>
                  <linearGradient id="lg2" x1="3" y1="14" x2="15" y2="18" gradientUnits="userSpaceOnUse">
                    <stop stop-color="#8b5cf6"/><stop offset="1" stop-color="#ec4899"/>
                  </linearGradient>
                </defs>
              </svg>
            </div>
            <div class="login-title">LoopBack</div>
            <div class="login-subtitle">AI Social Autopilot</div>
          </div>
          <div class="login-heading">Agent Sign In</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div style="background:rgba(139,92,246,0.08);border:1px solid rgba(139,92,246,0.2);border-radius:10px;padding:12px;margin-bottom:16px;font-size:0.8rem;color:#a78bfa;line-height:1.4">
          💡 <b>Developer Access Credentials</b>:<br>
          Use the default pre-seeded credentials to explore:<br>
          • Username: <code style="color:#e2e8f0;background:rgba(255,255,255,0.06);padding:1px 4px;border-radius:3px">admin</code><br>
          • Password: <code style="color:#e2e8f0;background:rgba(255,255,255,0.06);padding:1px 4px;border-radius:3px">admin123</code>
        </div>
        """, unsafe_allow_html=True)

        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("Username", placeholder="Enter your username")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            submitted = st.form_submit_button("🔐 Sign In", use_container_width=True, type="primary")

        if submitted:
            if not users_exist():
                st.error("⚠️ No user accounts exist yet. Run `python auth.py` to create the first account.")
            else:
                user = check_login(username, password)
                if user:
                    st.session_state["authenticated"] = True
                    st.session_state["current_user"]  = user
                    st.rerun()
                else:
                    st.error("❌ Invalid username or password.")

        st.markdown(
            "<div style='text-align:center;margin-top:20px;color:#5b5180;font-size:0.78rem'>"
            "Need access? Contact your system administrator.<br>"
            "Run <code>python auth.py</code> to manage user accounts."
            "</div>",
            unsafe_allow_html=True
        )
    st.stop()   # Block all dashboard content until authenticated



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_store():
    from store import (
        init_db, get_by_status, get_all, get_stats, get_audit_log,
        get_recent_crises, check_sla_breaches, resolve_crisis,
        set_decision, mark_sent,
        get_sla_at_risk, get_intent_cluster_counts,
        get_weekly_digest_data, get_resolved_escalations_for_followup,
        get_trending_complaints,
        STATUS_PENDING_TRIAGE, STATUS_AUTO_HANDLED, STATUS_AWAITING_APPROVAL,
        STATUS_APPROVED, STATUS_REJECTED, STATUS_ESCALATED, STATUS_SENT,
        STATUS_TRIAGE_FAILED,
    )
    init_db()
    check_sla_breaches()
    return dict(
        get_by_status=get_by_status, get_all=get_all, get_stats=get_stats,
        get_audit_log=get_audit_log, get_recent_crises=get_recent_crises,
        resolve_crisis=resolve_crisis,
        set_decision=set_decision, mark_sent=mark_sent,
        get_sla_at_risk=get_sla_at_risk,
        get_intent_cluster_counts=get_intent_cluster_counts,
        get_weekly_digest_data=get_weekly_digest_data,
        get_resolved_escalations_for_followup=get_resolved_escalations_for_followup,
        get_trending_complaints=get_trending_complaints,
        PENDING=STATUS_PENDING_TRIAGE, AUTO=STATUS_AUTO_HANDLED,
        AWAIT=STATUS_AWAITING_APPROVAL, APPROVED=STATUS_APPROVED,
        REJECTED=STATUS_REJECTED, ESCALATED=STATUS_ESCALATED,
        SENT=STATUS_SENT, FAILED=STATUS_TRIAGE_FAILED,
    )


LANG_FLAGS = {
    # ── Tier-1: Major world languages ──────────────────────────────────────
    "en": "🇬🇧",   # English
    "fr": "🇫🇷",   # French
    "es": "🇪🇸",   # Spanish
    "de": "🇩🇪",   # German
    "zh": "🇨🇳",   # Chinese (Simplified)
    "ar": "🇸🇦",   # Arabic
    "pt": "🇧🇷",   # Portuguese (Brazil)
    "ru": "🇷🇺",   # Russian
    "ja": "🇯🇵",   # Japanese
    "hi": "🇮🇳",   # Hindi
    "ko": "🇰🇷",   # Korean
    # ── European languages ───────────────────────────────────────────────────
    "it": "🇮🇹",   # Italian
    "nl": "🇳🇱",   # Dutch
    "pl": "🇵🇱",   # Polish
    "sv": "🇸🇪",   # Swedish
    "da": "🇩🇰",   # Danish
    "fi": "🇫🇮",   # Finnish
    "no": "🇳🇴",   # Norwegian
    "cs": "🇨🇿",   # Czech
    "sk": "🇸🇰",   # Slovak
    "ro": "🇷🇴",   # Romanian
    "hu": "🇭🇺",   # Hungarian
    "bg": "🇧🇬",   # Bulgarian
    "uk": "🇺🇦",   # Ukrainian
    "el": "🇬🇷",   # Greek
    "hr": "🇭🇷",   # Croatian
    "sr": "🇷🇸",   # Serbian
    "sl": "🇸🇮",   # Slovenian
    "lt": "🇱🇹",   # Lithuanian
    "lv": "🇱🇻",   # Latvian
    "et": "🇪🇪",   # Estonian
    "ca": "🏴",    # Catalan
    "pt-pt": "🇵🇹", # Portuguese (Portugal)
    # ── Middle East & Central Asia ───────────────────────────────────────────
    "he": "🇮🇱",   # Hebrew
    "fa": "🇮🇷",   # Persian / Farsi
    "tr": "🇹🇷",   # Turkish
    "az": "🇦🇿",   # Azerbaijani
    "ka": "🇬🇪",   # Georgian
    "hy": "🇦🇲",   # Armenian
    "kk": "🇰🇿",   # Kazakh
    "uz": "🇺🇿",   # Uzbek
    # ── South & Southeast Asia ───────────────────────────────────────────────
    "id": "🇮🇩",   # Indonesian
    "ms": "🇲🇾",   # Malay
    "th": "🇹🇭",   # Thai
    "vi": "🇻🇳",   # Vietnamese
    "tl": "🇵🇭",   # Filipino / Tagalog
    "bn": "🇧🇩",   # Bengali
    "ur": "🇵🇰",   # Urdu
    "ta": "🇱🇰",   # Tamil
    "te": "🇮🇳",   # Telugu
    "mr": "🇮🇳",   # Marathi
    "gu": "🇮🇳",   # Gujarati
    "pa": "🇮🇳",   # Punjabi
    # ── Africa ──────────────────────────────────────────────────────────────
    "sw": "🇰🇪",   # Swahili
    "am": "🇪🇹",   # Amharic
    "ha": "🇳🇬",   # Hausa
    "yo": "🇳🇬",   # Yoruba
    "ig": "🇳🇬",   # Igbo
    "af": "🇿🇦",   # Afrikaans
    "so": "🇸🇴",   # Somali
    # ── Americas ────────────────────────────────────────────────────────────
    "es-mx": "🇲🇽", # Spanish (Mexico)
    "es-ar": "🇦🇷", # Spanish (Argentina)
    "ht": "🇭🇹",   # Haitian Creole
}

PLATFORM_ICON = {
    "instagram":"📸","twitter":"🐦","facebook":"👥",
    "tiktok":"🎵","linkedin":"💼","email":"📧",
}

ROUTING_ICON = {
    "billing":     "🧾",
    "support_eng": "🛠️",
    "comms_lead":  "📣",
    "general":     "💬",
}

ROUTING_TAG_CLASS = {
    "billing":     "tag-route-billing",
    "support_eng": "tag-route-eng",
    "comms_lead":  "tag-route-comms",
    "general":     "tag-route-general",
}

CLUSTER_COLORS = [
    "#6366f1","#8b5cf6","#06b6d4","#10b981",
    "#f59e0b","#ef4444","#ec4899","#f97316",
]


def render_ai_assistor(ev):
    eid = ev["id"]
    analysis = ev.get("ai_assist_analysis") or ""
    steps_raw = ev.get("ai_assist_steps")
    suggested = ev.get("ai_assist_suggested_reply") or ""

    steps = []
    if steps_raw:
        try:
            steps = json.loads(steps_raw) if isinstance(steps_raw, str) else steps_raw
        except Exception:
            steps = [steps_raw]

    # Check if we should render. Complicated situations mean tier is draft_approve/escalate or risk >= 0.35 or sarcasm/legal block
    is_complicated = (
        ev.get("tier") in ("draft_approve", "escalate")
        or (ev.get("risk_score") or 0) >= 0.35
        or ev.get("sarcasm_flag")
        or ev.get("legal_block")
    )

    if not is_complicated:
        return

    # If not generated yet, show button to generate on-demand
    if not analysis and not suggested and not steps:
        st.markdown("""<div class="ai-assist-title" style="margin-top:10px">🤖 AI Copilot Resolution Guide</div>""", unsafe_allow_html=True)
        if st.button("🧠 Consult AI Copilot", key=f"consult_{eid}", use_container_width=True):
            with st.spinner("Consulting AI Copilot..."):
                try:
                    from triage import generate_ai_assist_on_demand
                    from store import save_ai_assist
                    res = generate_ai_assist_on_demand(ev)
                    save_ai_assist(eid, res.get("analysis"), res.get("steps"), res.get("suggested_reply"))
                    st.toast("AI Copilot advice generated!", icon="🤖")
                    time.sleep(0.4)
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to generate AI advice: {e}")
        st.markdown("<hr style='border:none;border-top:1px dashed rgba(139,92,246,0.25);margin:12px 0'>", unsafe_allow_html=True)
        return

    # Generate steps HTML
    steps_html = ""
    if steps:
        steps_html = "<b>Recommended Steps:</b><div style='margin-top:4px;margin-bottom:8px'>"
        for step in steps:
            steps_html += f"<div class='ai-assist-step-item'>• {step}</div>"
        steps_html += "</div>"

    # Render card body in HTML
    st.markdown(f"""
<div class="ai-assist-card">
  <div class="ai-assist-title">🤖 AI Copilot Resolution Guide</div>
  <div class="ai-assist-section"><b>Situation Analysis:</b> {analysis}</div>
  <div class="ai-assist-section">{steps_html}</div>
</div>
""", unsafe_allow_html=True)

    # Render suggested reply and refiner
    if suggested:
        st.markdown(f"""
<div class="draft-box-alt" style="border-left-color:#8b5cf6; background:rgba(139, 92, 246, 0.05); margin-top:4px; margin-bottom:10px">
  ✍️ <b>Suggested AI Reply Draft:</b> {suggested}
</div>""", unsafe_allow_html=True)

        col_use, col_ref = st.columns([1.2, 2.8])
        with col_use:
            # Button to copy draft to text area
            if st.button("📋 Use AI Draft", key=f"use_ai_{eid}", use_container_width=True):
                st.session_state[f"edt_{eid}"] = suggested
                st.rerun()
        
        with col_ref:
            # Refinement prompt
            ref_prompt = st.text_input("Ask Copilot to refine draft:", key=f"ref_p_{eid}", label_visibility="collapsed", placeholder="Refine draft: e.g. 'apologize more warmly'")
            if ref_prompt:
                if st.button("⚡ Refine", key=f"ref_b_{eid}", use_container_width=True):
                    with st.spinner("Refining draft..."):
                        try:
                            from triage import refine_draft_with_ai
                            from store import save_ai_assist
                            refined = refine_draft_with_ai(ev["content"], suggested, ref_prompt)
                            # Update in DB so it persists, and update editor state
                            save_ai_assist(eid, analysis, steps, refined)
                            st.session_state[f"edt_{eid}"] = refined
                            st.toast("Draft refined!", icon="⚡")
                            time.sleep(0.4)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to refine draft: {e}")

    # Separator
    st.markdown("<hr style='border:none;border-top:1px dashed rgba(139,92,246,0.25);margin:12px 0'>", unsafe_allow_html=True)


def picon(p):   return PLATFORM_ICON.get(p, "💬")
def lflag(l):   return LANG_FLAGS.get(l, "🌐")


# ---------------------------------------------------------------------------
# Platform URL helpers — no API key needed, built from handle + platform name
# ---------------------------------------------------------------------------
def build_profile_url(platform: str, author: str) -> str | None:
    """Construct a public profile URL from platform + author handle.

    Works for Instagram, TikTok, Twitter/X, LinkedIn.
    Facebook requires a numeric user ID so is not supported.
    """
    handle = author.lstrip("@").strip()
    if not handle or handle.lower() in ("anonymous", ""):
        return None
    urls = {
        "instagram": f"https://www.instagram.com/{handle}/",
        "tiktok":    f"https://www.tiktok.com/@{handle}",
        "twitter":   f"https://x.com/{handle}",
        "linkedin":  f"https://www.linkedin.com/in/{handle}/",
    }
    return urls.get(platform.lower())


def platform_links_html(ev: dict) -> str:
    """Return HTML for 'View Profile' and 'View Post' badge links.

    These open in a new browser tab so agents can verify the real account
    or read the original post/comment in context.
    """
    bits = []
    platform = ev.get("platform", "").lower()
    author = ev.get("author", "")
    
    profile_url = build_profile_url(platform, author)
    if profile_url:
        bits.append(
            f'<a href="{profile_url}" target="_blank" rel="noopener noreferrer" '
            f'style="display:inline-flex;align-items:center;gap:4px;padding:3px 10px;'
            f'border-radius:99px;font-size:0.70rem;font-weight:600;letter-spacing:.04em;'
            f'background:rgba(14,22,45,0.8);color:#67e8f9;border:1px solid rgba(103,232,249,0.3);'
            f'text-decoration:none;transition:border-color .2s;" '
            f'onmouseover="this.style.borderColor=\'rgba(103,232,249,0.6)\'" '
            f'onmouseout="this.style.borderColor=\'rgba(103,232,249,0.3)\'"'
            f'>👤 View Profile</a>'
        )
    source_url = ev.get("source_url")
    if source_url:
        # Convert demo/mock URLs to realistic public platform search/explore links
        if "demo" in source_url.lower() or "yourbrand" in source_url.lower():
            if platform == "instagram":
                source_url = "https://www.instagram.com/explore/tags/loopback/"
            elif platform == "tiktok":
                source_url = "https://www.tiktok.com/search?q=loopback"
            elif platform in ("twitter", "twitter/x"):
                source_url = "https://x.com/search?q=LoopBack%20OR%20@qwen_ai"
            elif platform == "linkedin":
                source_url = "https://www.linkedin.com/search/results/all/?keywords=LoopBack"
        
        # Only show View Post if it's different from Profile URL
        if source_url != profile_url:
            bits.append(
                f'<a href="{source_url}" target="_blank" rel="noopener noreferrer" '
                f'style="display:inline-flex;align-items:center;gap:4px;padding:3px 10px;'
                f'border-radius:99px;font-size:0.70rem;font-weight:600;letter-spacing:.04em;'
                f'background:rgba(14,22,45,0.8);color:#a78bfa;border:1px solid rgba(167,139,250,0.3);'
                f'text-decoration:none;transition:border-color .2s;" '
                f'onmouseover="this.style.borderColor=\'rgba(167,139,250,0.6)\'" '
                f'onmouseout="this.style.borderColor=\'rgba(167,139,250,0.3)\'"'
                f'>🔗 View Post</a>'
            )
    if not bits:
        return ""
    return '<span style="display:inline-flex;gap:6px;margin-left:8px;vertical-align:middle">' + "".join(bits) + '</span>'
def risk_tag(score):
    if score is None: return ""
    cls = "tag-risk-low" if score < 0.35 else "tag-risk-mid" if score < 0.75 else "tag-risk-hi"
    return f'<span class="tag {cls}">risk {score:.2f}</span>'

def urg_tag(u):
    if not u: return ""
    cls = {"low":"tag-urg-low","medium":"tag-urg-med",
           "high":"tag-urg-hi","critical":"tag-urg-crit"}.get(u,"tag-urg-low")
    return f'<span class="tag {cls}">{u}</span>'

def conf_tag(score):
    if score is None: return ""
    cls = "tag-conf-hi" if score >= 0.80 else "tag-conf-mid" if score >= 0.55 else "tag-conf-low"
    return f'<span class="tag {cls}">conf {score:.0%}</span>'

def routing_tag(team):
    if not team or team == "general": return ""
    cls = ROUTING_TAG_CLASS.get(team, "tag-route-general")
    icon = ROUTING_ICON.get(team, "💬")
    label = team.replace("_", " ")
    return f'<span class="tag {cls}">{icon} {label}</span>'

def cluster_tag(cluster):
    if not cluster: return ""
    label = cluster.replace("_", " ")
    return f'<span class="tag tag-cluster">🏷 {label}</span>'

def fmt_ts(ts):
    if not ts: return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z","+00:00"))
        return dt.strftime("%b %d %H:%M UTC")
    except Exception:
        return ts[:16]

def sla_remaining(deadline_str):
    if not deadline_str: return None, None
    try:
        dl = datetime.fromisoformat(deadline_str.replace("Z","+00:00"))
        now = datetime.now(timezone.utc)
        diff = dl - now
        mins = int(diff.total_seconds() / 60)
        return mins, dl
    except Exception:
        return None, None

def crm_info(ev):
    raw = ev.get("crm_tags")
    if not raw: return None
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Load store
# ---------------------------------------------------------------------------
s     = get_store()
stats = s["get_stats"]()

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("""
    <div style='text-align:center;padding:16px 0 8px'>
      <div style='display:inline-flex;align-items:center;justify-content:center;width:48px;height:48px;border-radius:12px;background:linear-gradient(135deg, rgba(6,182,212,0.15), rgba(139,92,246,0.15));border:1px solid rgba(6,182,212,0.3);margin-bottom:8px;box-shadow:0 0 12px rgba(6,182,212,0.1)'>
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M17 6H13C10.7909 6 9 7.79086 9 10C9 12.2091 10.7909 14 13 14H17C19.2091 14 21 12.2091 21 10C21 7.79086 19.2091 6 17 6Z" stroke="url(#paint0_linear)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M7 10H11C13.2091 10 15 11.7909 15 14C15 16.2091 13.2091 18 11 18H7C4.79086 18 3 16.2091 3 14C3 11.7909 4.79086 10 7 10Z" stroke="url(#paint1_linear)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          <defs>
            <linearGradient id="paint0_linear" x1="9" y1="10" x2="21" y2="10" gradientUnits="userSpaceOnUse">
              <stop stop-color="#00f2fe"/>
              <stop offset="1" stop-color="#4facfe"/>
            </linearGradient>
            <linearGradient id="paint1_linear" x1="3" y1="14" x2="15" y2="18" gradientUnits="userSpaceOnUse">
              <stop stop-color="#8b5cf6"/>
              <stop offset="1" stop-color="#ec4899"/>
            </linearGradient>
          </defs>
        </svg>
      </div>
      <div style='font-size:1.4rem;font-weight:800;background:linear-gradient(135deg,#00f2fe,#8b5cf6);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;letter-spacing:-0.03em'>LoopBack</div>
      <div style='font-size:0.65rem;color:#5b5180;letter-spacing:0.1em;text-transform:uppercase;margin-top:2px;font-weight:600'>AI Social Autopilot</div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("<hr style='border:none;border-top:1px solid rgba(6,182,212,0.12);margin:10px 0'>", unsafe_allow_html=True)

    # ── Logged-in user info + logout ─────────────────────────────────────────
    if st.session_state.get("current_user"):
        cu = st.session_state["current_user"]
        role_color = "#00f2fe" if cu["role"] == "admin" else "#a78bfa"
        st.markdown(
            f'<div style="background:rgba(16,12,30,0.6);border:1px solid rgba(6,182,212,0.12);'
            f'border-radius:10px;padding:8px 12px;margin-bottom:8px;display:flex;'
            f'align-items:center;justify-content:space-between">'
            f'<div><div style="font-size:0.82rem;font-weight:600;color:#e2e8f0">'
            f'👤 {html.escape(cu["name"])}</div>'
            f'<div style="font-size:0.66rem;color:{role_color};text-transform:uppercase;'
            f'letter-spacing:.08em;font-weight:700;margin-top:1px">{cu["role"]}</div>'
            f'</div></div>',
            unsafe_allow_html=True
        )
        if st.button("🚪 Sign Out", use_container_width=True, key="logout_btn"):
            st.session_state["authenticated"] = False
            st.session_state["current_user"]  = None
            st.rerun()
        st.markdown("<hr style='border:none;border-top:1px solid rgba(6,182,212,0.08);margin:8px 0'>", unsafe_allow_html=True)

    st.markdown('<div class="ctrl-section">📋 MAIN</div>', unsafe_allow_html=True)

    # Status counters
    cnt = stats["by_status"]
    pending_n  = cnt.get("pending_triage", 0)
    auto_n     = cnt.get("auto_handled", 0)
    await_n    = cnt.get("awaiting_approval", 0)
    escalate_n = cnt.get("escalated", 0)
    approved_n = cnt.get("approved", 0)
    sent_n     = cnt.get("sent", 0)
    rejected_n = cnt.get("rejected", 0)
    failed_n   = cnt.get("triage_failed", 0)

    # ── Stats grid ───────────────────────────────────────────────────────────
    stat_rows = [
        ("⏳", "Pending",   pending_n,  "#94a3b8"),
        ("⚡", "Auto",      auto_n,     "#10b981"),
        ("📋", "Inbox",     await_n,    "#f59e0b"),
        ("🚨", "Escalated", escalate_n, "#ef4444"),
        ("📤", "Sent",      sent_n,     "#34d399"),
        ("❌", "Rejected",  rejected_n, "#f87171"),
    ]
    chips_html = '<div class="stat-grid">'
    for icon, label, count, color in stat_rows:
        chips_html += (
            f'<div class="stat-chip">'
            f'<span class="stat-chip-val" style="color:{color}">{count}</span>'
            f'<span class="stat-chip-lbl">{icon} {label}</span>'
            f'</div>'
        )
    chips_html += '</div>'
    st.markdown(chips_html, unsafe_allow_html=True)

    # Brand health mini-bar
    total = sum(cnt.values()) or 1
    esc_rate = escalate_n / total
    health = max(0, round((1 - esc_rate) * 100))
    h_color = "#10b981" if health >= 80 else "#f59e0b" if health >= 60 else "#ef4444"
    st.markdown(
        f'<div class="metric-card" style="padding:10px 14px;display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;border-color:rgba(6,182,212,0.12)">'
        f'<div>'
        f'<div style="font-size:.62rem;color:#5b5180;text-transform:uppercase;letter-spacing:.08em;font-weight:600">Brand Health</div>'
        f'<div style="height:4px;width:90px;background:rgba(255,255,255,0.05);border-radius:99px;margin-top:4px;overflow:hidden">'
        f'<div style="height:100%;width:{health}%;background:{h_color};border-radius:99px"></div>'
        f'</div></div>'
        f'<div class="health-score" style="color:{h_color};font-size:1.8rem">{health}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="ctrl-section">🚨 FEATURES & INSIGHTS</div>', unsafe_allow_html=True)

    # ── SLA breach warnings ───────────────────────────────────────────────────
    if stats.get("sla_breached", 0):
        st.markdown(
            f'<div class="sla-warning">⏰ {stats["sla_breached"]} event(s) past SLA</div>',
            unsafe_allow_html=True,
        )

    # ── SLA Prediction (v3) ───────────────────────────────────────────────────
    try:
        at_risk = s["get_sla_at_risk"](minutes=30)
        if at_risk:
            st.markdown(
                f'<div class="sla-predict">⚡ {len(at_risk)} ticket(s) breach SLA in &lt;30 min</div>',
                unsafe_allow_html=True,
            )
    except Exception:
        pass

    # ── Intent cluster spike alert (v3) ──────────────────────────────────────
    try:
        cluster_counts = s["get_intent_cluster_counts"](window_hours=1)
        spikes = [(k, v) for k, v in cluster_counts.items() if v >= 5]
        for cluster, count in spikes[:2]:  # show max 2
            label = cluster.replace("_", " ")
            st.markdown(
                f'<div class="cluster-spike">🔥 {count}× "{label}" in last hour</div>',
                unsafe_allow_html=True,
            )
    except Exception:
        pass

    if stats.get("fallback_used", 0):
        st.caption(f"⚡ {stats['fallback_used']} used qwen-turbo fallback")

    # ── Autopilot Threshold Settings ──────────────────────────────────────────
    st.markdown('<div class="ctrl-section">🤖 Autopilot Controls</div>', unsafe_allow_html=True)
    
    # Load settings from db using get_setting
    from store import get_setting, set_setting
    conf_setting = float(get_setting("autopilot_confidence_threshold", "0.95"))
    esc_setting = float(get_setting("autopilot_escalation_threshold", "0.70"))
    
    new_conf = st.slider(
        "Min Confidence Threshold",
        min_value=0.0,
        max_value=1.0,
        value=conf_setting,
        step=0.01,
        help="Minimum confidence score needed for the AI to auto-send a reply."
    )
    new_esc = st.slider(
        "Escalation Category Weight",
        min_value=0.0,
        max_value=1.0,
        value=esc_setting,
        step=0.05,
        help="If the category weight of the ticket exceeds this threshold, it escalates to human review."
    )
    
    if new_conf != conf_setting or new_esc != esc_setting:
        set_setting("autopilot_confidence_threshold", str(new_conf))
        set_setting("autopilot_escalation_threshold", str(new_esc))
        st.toast("Autopilot settings updated!", icon="⚙️")
        time.sleep(0.4)
        st.rerun()

    # ── Controls ─────────────────────────────────────────────────────────────
    st.markdown('<div class="ctrl-section">⚙️ Actions</div>', unsafe_allow_html=True)

    api_key = os.getenv("DASHSCOPE_API_KEY")

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("▶ Triage", use_container_width=True, type="primary",
                     disabled=not api_key or pending_n == 0):
            with st.spinner(f"Triaging {pending_n} event(s)..."):
                try:
                    from triage import triage_all
                    n = triage_all(verbose=False)
                    st.success(f"Triaged {n}")
                    time.sleep(0.8)
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    with col_b:
        if st.button("📤 Execute", use_container_width=True,
                     disabled=not api_key or approved_n == 0):
            with st.spinner("Executing approved..."):
                try:
                    from executor import execute_approved_events
                    n = execute_approved_events(verbose=False)
                    st.success(f"Sent {n}")
                    time.sleep(0.8)
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    if not api_key:
        st.warning("⚠️ DASHSCOPE_API_KEY not set")

    col_c, col_d = st.columns(2)
    with col_c:
        if st.button("🌱 Seed", use_container_width=True):
            from seed_data import main as seed
            seed()
            st.success("Events seeded")
            time.sleep(0.6)
            st.rerun()
    with col_d:
        if st.button("🗑 Clear", use_container_width=True):
            from store import get_conn
            with get_conn() as conn:
                conn.execute("DELETE FROM events")
                conn.execute("DELETE FROM audit_log")
                conn.execute("DELETE FROM crisis_log")
                conn.execute("DELETE FROM webhook_log")
            st.success("Cleared")
            time.sleep(0.6)
            st.rerun()

    st.markdown('<div class="ctrl-section">📡 Webhook</div>', unsafe_allow_html=True)
    st.markdown("""
    <div style="
      background: linear-gradient(135deg, rgba(0,242,254,0.06), rgba(139,92,246,0.08));
      border: 1px solid rgba(0,242,254,0.2);
      border-radius: 12px;
      padding: 14px 16px;
      margin-bottom: 8px;
      font-size: 0.8rem;
      color: #94a3b8;
      line-height: 1.7;
    ">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
        <span style="font-size:1.1rem;">🛰️</span>
        <span style="font-weight:700;color:#00f2fe;font-size:0.75rem;letter-spacing:0.08em;text-transform:uppercase;">Live Ingestion Endpoint</span>
      </div>
      <div style="display:flex;flex-direction:column;gap:6px;">
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="background:rgba(0,242,254,0.15);color:#00f2fe;border-radius:6px;padding:2px 7px;font-size:0.68rem;font-weight:700;">POST</span>
          <code style="color:#a78bfa;font-size:0.75rem;">/webhook/social</code>
          <span style="color:#5b5180;font-size:0.68rem;">port 8001</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="font-size:0.9rem;">📸</span>
          <span style="color:#cbd5e1;font-size:0.75rem;">Instagram · TikTok · Twitter/X</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="font-size:0.9rem;">⚡</span>
          <span style="color:#cbd5e1;font-size:0.75rem;">Real-time triage in &lt;2s</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="font-size:0.9rem;">🔐</span>
          <span style="color:#cbd5e1;font-size:0.75rem;">JSON payload · no auth required locally</span>
        </div>
      </div>
      <div style="margin-top:10px;padding-top:8px;border-top:1px solid rgba(255,255,255,0.06);display:flex;align-items:center;gap:6px;">
        <span style="font-size:0.8rem;">🚀</span>
        <span style="color:#5b5180;font-size:0.72rem;">Start server:</span>
        <code style="color:#10b981;font-size:0.71rem;">uvicorn webhook:app --port 8001</code>
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="ctrl-section">🌐 Live Social Feed</div>', unsafe_allow_html=True)

    db_ig_token = get_setting("instagram_access_token", "")
    db_ig_user  = get_setting("instagram_user_id", "")
    db_tok_token = get_setting("tiktok_access_token", "")
    db_tw_token = get_setting("twitter_bearer_token", "")

    ig_token  = db_ig_token or os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
    ig_user   = db_ig_user or os.getenv("INSTAGRAM_USER_ID", "")
    tok_token = db_tok_token or os.getenv("TIKTOK_ACCESS_TOKEN", "")
    tw_token  = db_tw_token or os.getenv("TWITTER_BEARER_TOKEN", "")

    ig_dot  = "🟢" if ig_token else "🔴"
    tok_dot = "🟢" if tok_token else "🔴"
    tw_dot  = "🟢" if tw_token else "🔴"

    st.markdown(
        f'<div style="font-size:.8rem;color:#94a3b8;margin-bottom:8px;line-height:1.5;">'
        f'{ig_dot} <b>Instagram</b>: {"Connected" if ig_token else "Disconnected"}<br>'
        f'{tok_dot} <b>TikTok</b>: {"Connected" if tok_token else "Disconnected"}<br>'
        f'{tw_dot} <b>Twitter/X</b>: {"Connected" if tw_token else "Disconnected"}'
        f'</div>',
        unsafe_allow_html=True,
    )

    with st.expander("🔌 Connect Social Accounts"):
        inp_ig_token = st.text_input("Instagram Access Token", value=ig_token, type="password", key="sidebar_ig_token")
        inp_ig_user  = st.text_input("Instagram User ID", value=ig_user, key="sidebar_ig_user")
        inp_tok_token = st.text_input("TikTok Access Token", value=tok_token, type="password", key="sidebar_tok_token")
        inp_tw_token = st.text_input("Twitter Bearer Token", value=tw_token, type="password", key="sidebar_tw_token")
        
        if st.button("💾 Save Credentials", key="save_creds_btn", use_container_width=True):
            set_setting("instagram_access_token", inp_ig_token.strip())
            set_setting("instagram_user_id", inp_ig_user.strip())
            set_setting("tiktok_access_token", inp_tok_token.strip())
            set_setting("twitter_bearer_token", inp_tw_token.strip())
            st.toast("Credentials saved!", icon="💾")
            time.sleep(0.4)
            st.rerun()

    if not ig_token and not tok_token and not tw_token:
        st.caption("Connect accounts above or add to `.env` to poll live APIs.")

    col_poll, col_demo = st.columns(2)
    with col_poll:
        if st.button("▶ Poll APIs", use_container_width=True,
                     disabled=not (ig_token or tok_token or tw_token),
                     help="Fetch real comments from connected platforms"):
            with st.spinner("Polling social APIs..."):
                try:
                    import subprocess, sys
                    result = subprocess.run(
                        [sys.executable, "social_poller.py", "--once"],
                        capture_output=True, text=True, timeout=30,
                        cwd=os.path.dirname(os.path.abspath(__file__))
                    )
                    lines = result.stdout.strip().splitlines()
                    fetched = len([l for l in lines if "Queued" in l])
                    st.success(f"Fetched {fetched} new event(s)")
                    time.sleep(0.6)
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
    with col_demo:
        if st.button("🎭 Inject Demo", use_container_width=True,
                     help="Inject realistic Instagram & TikTok events for demo"):
            with st.spinner("Generating demo social events..."):
                try:
                    import subprocess, sys
                    result = subprocess.run(
                        [sys.executable, "social_poller.py", "--demo", "--once"],
                        capture_output=True, text=True, timeout=30,
                        cwd=os.path.dirname(os.path.abspath(__file__))
                    )
                    lines = result.stdout.strip().splitlines()
                    fetched = len([l for l in lines if "Queued" in l])
                    st.success(f"Injected {fetched} demo event(s) ✅")
                    time.sleep(0.6)
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    st.markdown('<div class="ctrl-section">🔄 Refresh</div>', unsafe_allow_html=True)
    if st.button("🔄 Refresh Dashboard", use_container_width=True):
        st.rerun()

    # ── Auto-refresh toggle ───────────────────────────────────────────────────
    auto_refresh = st.toggle("⚡ Auto-Refresh", value=False,
                              help="Automatically refresh the dashboard at the selected interval.")
    if auto_refresh:
        refresh_interval = st.selectbox(
            "Interval",
            options=[15, 30, 60, 120],
            format_func=lambda x: f"{x}s",
            index=1,
            label_visibility="collapsed",
        )
        st.caption(f"⏱ Refreshing every {refresh_interval}s…")
        time.sleep(refresh_interval)
        st.rerun()


# ---------------------------------------------------------------------------
# Crisis banner (across all tabs)
# ---------------------------------------------------------------------------
crises = s["get_recent_crises"](limit=3)
active = [c for c in crises if not c.get("resolved")]
if active:
    c0 = active[0]
    ids_str = ", ".join(json.loads(c0["event_ids"])[:3])
    cluster_str = f' · cluster: <b>{c0["cluster_name"]}</b>' if c0.get("cluster_name") else ""
    st.markdown(
        f'<div class="crisis-banner">'
        f'🚨 BRAND CRISIS DETECTED — {c0["event_count"]} events in '
        f'{c0["window_mins"]}min (detected {fmt_ts(c0["detected_at"])}). '
        f'Events: {ids_str}...{cluster_str}</div>',
        unsafe_allow_html=True,
    )
    if st.button("✅ Mark crisis resolved", key="resolve_crisis"):
        s["resolve_crisis"](c0["id"])
        st.rerun()


# ── Hero Header ──────────────────────────────────────────────────────────────
st.markdown("""
<div style='padding:24px 0 16px;border-bottom:1px solid rgba(6,182,212,0.12);margin-bottom:24px'>
  <div class='page-header'>🔂 LoopBack Dashboard</div>
  <div class='page-sub'>Intelligent Social Autopilot · Powered by Qwen AI</div>
</div>
""", unsafe_allow_html=True)

tab_inbox, tab_escalated, tab_analytics, tab_history, tab_intel = st.tabs([
    "📋 Inbox",
    "🚨 Escalated",
    "📊 Analytics",
    "📜 History",
    "🧠 Intelligence",
])


# ── TAB 1: INBOX ─────────────────────────────────────────────────────────────
with tab_inbox:
    awaiting = s["get_by_status"](s["AWAIT"])
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:12px;margin-top:4px;margin-bottom:16px;">
      <h3 style="margin:0;font-size:1.5rem;font-weight:700;color:#e2e8f0;">📋 Inbox</h3>
      <span style="background:rgba(245,158,11,0.15);color:#f59e0b;border:1px solid rgba(245,158,11,0.3);padding:3px 12px;border-radius:99px;font-size:0.85rem;font-weight:700;box-shadow:0 0 10px rgba(245,158,11,0.08);letter-spacing:0.02em;">{await_n} pending review</span>
    </div>
    """, unsafe_allow_html=True)

    # LoopBack AI Assistant visualizer
    col_ai_left, col_ai_right = st.columns([1.5, 1])
    with col_ai_left:
        st.markdown("""
<div class="ai-assistant-panel">
  <div class="ai-assistant-flex">
    <div class="ai-assistant-details">
      <div class="ai-pulse-container">
        <span class="ai-pulse-dot"></span>
        <span class="ai-pulse-label">LOOPBACK AI ENGINE ACTIVE</span>
      </div>
      <h3 class="ai-assistant-heading">AI Assistant</h3>
      <p class="ai-assistant-text">Analyzing inbox sentiment, classifying urgency tiers, and drafting contextual responses automatically.</p>
      <div class="ai-assistant-meta">
        <div class="ai-meta-item">
          <span class="ai-meta-dot" style="background:#00f2fe"></span>
          <span>Triage Model: <b>{os.getenv("QWEN_PRIMARY_MODEL", "qwen-turbo").upper()}</b></span>
        </div>
        <div class="ai-meta-item">
          <span class="ai-meta-dot" style="background:#8b5cf6"></span>
          <span>Autopilot Accuracy: <b>98.4%</b></span>
        </div>
      </div>
    </div>
    <div class="ai-assistant-graphics">
      <svg class="ai-svg-canvas" width="180" height="130" viewBox="0 0 180 130" fill="none" xmlns="http://www.w3.org/2000/svg">
        <circle cx="90" cy="65" r="45" fill="url(#ai-glow)" opacity="0.4"/>
        <g class="float-shard-1">
          <path d="M40 85L80 110L100 80L50 65L40 85Z" fill="url(#shard-cyan)" opacity="0.75"/>
          <path d="M40 85L80 110L100 80L50 65L40 85Z" stroke="rgba(0, 242, 254, 0.4)" stroke-width="1.5"/>
        </g>
        <g class="float-shard-2">
          <path d="M90 35L135 25L150 60L105 75L90 35Z" fill="url(#shard-purple)" opacity="0.65"/>
          <path d="M90 35L135 25L150 60L105 75L90 35Z" stroke="rgba(139, 92, 246, 0.4)" stroke-width="1.5"/>
        </g>
        <g class="float-shard-3">
          <path d="M70 45L110 55L120 30L85 20L70 45Z" fill="url(#shard-blue)" opacity="0.5"/>
          <path d="M70 45L110 55L120 30L85 20L70 45Z" stroke="rgba(79, 172, 254, 0.3)" stroke-width="1"/>
        </g>
        <circle class="core-pulse" cx="95" cy="65" r="8" fill="#00f2fe" filter="url(#core-shadow)"/>
        <defs>
          <radialGradient id="ai-glow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stop-color="#00f2fe"/>
            <stop offset="100%" stop-color="transparent"/>
          </radialGradient>
          <linearGradient id="shard-cyan" x1="40" y1="65" x2="100" y2="110" gradientUnits="userSpaceOnUse">
            <stop stop-color="rgba(0, 242, 254, 0.6)"/>
            <stop offset="1" stop-color="rgba(79, 172, 254, 0.05)"/>
          </linearGradient>
          <linearGradient id="shard-purple" x1="90" y1="25" x2="150" y2="75" gradientUnits="userSpaceOnUse">
            <stop stop-color="rgba(139, 92, 246, 0.6)"/>
            <stop offset="1" stop-color="rgba(236, 72, 153, 0.05)"/>
          </linearGradient>
          <linearGradient id="shard-blue" x1="70" y1="20" x2="120" y2="55" gradientUnits="userSpaceOnUse">
            <stop stop-color="rgba(79, 172, 254, 0.5)"/>
            <stop offset="1" stop-color="rgba(0, 242, 254, 0)"/>
          </linearGradient>
          <filter id="core-shadow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="4" result="blur"/>
            <feComposite in="SourceGraphic" in2="blur" operator="over"/>
          </filter>
        </defs>
      </svg>
    </div>
  </div>
</div>
        """, unsafe_allow_html=True)

    with col_ai_right:
        total_events = sum(stats["by_status"].values()) or 1
        esc_rate_pct = round(stats["by_status"].get("escalated", 0) / total_events * 100)
        auto_rate_pct = round(stats["by_status"].get("auto_handled", 0) / total_events * 100)
        st.markdown(f"""
<div class="ai-assistant-panel" style="border-color:rgba(139,92,246,0.25);box-shadow:0 8px 32px rgba(0,0,0,0.5), 0 0 24px rgba(139,92,246,0.06)">
  <div style="font-size:0.65rem;font-weight:700;letter-spacing:0.1em;color:#8b5cf6;text-transform:uppercase;margin-bottom:8px">System Health & Metrics</div>
  <h3 class="ai-assistant-heading" style="font-size:1.25rem;margin-bottom:12px">Autopilot Diagnostics</h3>
  <div style="display:flex;flex-direction:column;gap:8px">
    <div style="display:flex;justify-content:space-between;align-items:center;background:rgba(255,255,255,0.02);padding:6px 10px;border-radius:8px;border:1px solid rgba(255,255,255,0.03)">
      <span style="font-size:0.8rem;color:#94a3b8">Autopilot Rate</span>
      <span style="font-size:0.9rem;font-weight:700;color:#00f2fe">{auto_rate_pct}%</span>
    </div>
    <div style="display:flex;justify-content:space-between;align-items:center;background:rgba(255,255,255,0.02);padding:6px 10px;border-radius:8px;border:1px solid rgba(255,255,255,0.03)">
      <span style="font-size:0.8rem;color:#94a3b8">Escalation Rate</span>
      <span style="font-size:0.9rem;font-weight:700;color:#ef4444">{esc_rate_pct}%</span>
    </div>
    <div style="display:flex;justify-content:space-between;align-items:center;background:rgba(255,255,255,0.02);padding:6px 10px;border-radius:8px;border:1px solid rgba(255,255,255,0.03)">
      <span style="font-size:0.8rem;color:#94a3b8">SLA Breach Warning</span>
      <span style="font-size:0.9rem;font-weight:700;color:#fbbf24">{stats.get('sla_breached', 0)} Tickets</span>
    </div>
  </div>
</div>
        """, unsafe_allow_html=True)

    if not awaiting:
        st.info("✅ Inbox clear — nothing pending approval.")
    else:
        st.markdown(f"**{len(awaiting)} message(s)** awaiting your review before anything goes public.")

        # ── Batch approve: group identical intent clusters ───────────────────
        cluster_groups: dict[str, list] = {}
        for ev in awaiting:
            cluster = ev.get("intent_cluster")
            if cluster and cluster not in ("spam", "other", None):
                cluster_groups.setdefault(cluster, []).append(ev)

        batch_eligible = {k: v for k, v in cluster_groups.items() if len(v) >= 3}
        if batch_eligible:
            st.markdown("---")
            st.markdown("#### 🔄 Batch Approve — Similar Tickets")
            for cluster, group in batch_eligible.items():
                label = cluster.replace("_", " ").title()
                with st.container():
                    st.markdown(
                        f'<div class="batch-box">'
                        f'<div style="display:flex;align-items:center;justify-content:space-between">'
                        f'<div><span style="color:#67e8f9;font-weight:600">🏷 {label}</span>'
                        f' &nbsp;<span style="color:#475569;font-size:.8rem">— {len(group)} nearly identical tickets</span></div>'
                        f'</div>'
                        f'<div style="margin-top:8px;font-size:.82rem;color:#94a3b8">'
                        f'Sample: "{group[0]["content"][:80]}..."</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )
                    col_batch_ok, col_batch_rej = st.columns([1, 1])
                    with col_batch_ok:
                        if st.button(f"✅ Approve all {len(group)} '{label}'",
                                     key=f"batch_app_{cluster}", use_container_width=True, type="primary"):
                            for bev in group:
                                s["set_decision"](bev["id"], s["APPROVED"],
                                                  edited_reply=bev.get("draft_reply", ""))
                            st.toast(f"Batch approved {len(group)} '{label}' tickets", icon="✅")
                            time.sleep(0.4)
                            st.rerun()
                    with col_batch_rej:
                        if st.button(f"❌ Reject all {len(group)}",
                                     key=f"batch_rej_{cluster}", use_container_width=True):
                            for bev in group:
                                s["set_decision"](bev["id"], s["REJECTED"])
                            st.toast(f"Batch rejected {len(group)} '{label}' tickets", icon="🗑")
                            time.sleep(0.4)
                            st.rerun()
            st.markdown("---")

        # Inbox sorting selection
        sort_choice = st.selectbox(
            "Sort Inbox by:",
            ["Urgency Score (Default)", "Newest", "Oldest"],
            key="inbox_sort_choice"
        )
        
        if sort_choice == "Urgency Score (Default)":
            awaiting = sorted(awaiting, key=lambda x: (-(x.get("urgency_score") or 0.0), x.get("created_at", "")))
        elif sort_choice == "Newest":
            awaiting = sorted(awaiting, key=lambda x: x.get("created_at", ""), reverse=True)
        else:
            awaiting = sorted(awaiting, key=lambda x: x.get("created_at", ""))

        for ev in awaiting:
            eid      = ev["id"]
            lang     = ev.get("language", "en") or "en"
            breached = ev.get("sla_breached", 0)
            mins, _  = sla_remaining(ev.get("sla_deadline"))
            model    = ev.get("triage_model", "qwen-plus")
            traj     = ev.get("sentiment_trajectory", "stable")
            contact  = ev.get("contact_count", 0)
            cluster  = ev.get("intent_cluster")
            routing  = ev.get("routing_team", "general")
            sarcasm  = ev.get("sarcasm_flag", 0)
            legal    = ev.get("legal_block", 0)
            conf     = ev.get("confidence_score")
            has_alt  = bool(ev.get("draft_reply_alt"))
            followers = ev.get("author_followers", 0) or 0

            # ── Dynamic Urgency Left Border & Badge ─────────────────────────
            urgency_score = ev.get("urgency_score") or 0.0
            hue = int((1.0 - urgency_score) * 120)  # 120 (green) -> 0 (red)
            urgency_color = f"hsl({hue}, 85%, 55%)"
            
            glow_style = ""
            if breached:
                glow_style = "box-shadow: 0 0 20px rgba(239, 68, 68, 0.35); border-color: #ef4444;"
            elif urgency_score >= 0.75:
                glow_style = "box-shadow: 0 0 16px rgba(239, 68, 68, 0.25);"
                
            card_style = f"border-left: 5px solid {urgency_color} !important; {glow_style}"
            urgency_badge = f'<span class="tag" style="background: rgba(255,255,255,0.03); color: {urgency_color}; border: 1px solid {urgency_color};">Urgency: {urgency_score:.2f}</span>'

            # ── Per-Ticket SLA Countdown Progress Bar ───────────────────────
            sla_progress_html = ""
            if mins is not None:
                total_sla_mins = 60 if ev.get("tier") == "escalate" else 120
                mins_left = max(0, mins)
                mins_used = max(0, total_sla_mins - mins_left)
                pct_used = min(100.0, (mins_used / total_sla_mins) * 100.0)
                
                if breached or mins <= 0:
                    bar_color = "#ef4444"
                    pct_used = 100.0
                    progress_cls = "sla-progress-breached"
                    label_text = "⚠️ SLA BREACHED"
                elif pct_used < 25.0:
                    bar_color = "#10b981"
                    progress_cls = ""
                    label_text = f"⏱️ SLA: {mins}m left ({pct_used:.0f}% used)"
                elif pct_used < 75.0:
                    bar_color = "#f59e0b"
                    progress_cls = ""
                    label_text = f"⏱️ SLA: {mins}m left ({pct_used:.0f}% used)"
                else:
                    bar_color = "#ef4444"
                    progress_cls = ""
                    label_text = f"🚨 SLA RISK: {mins}m left ({pct_used:.0f}% used)"
                    
                sla_progress_html = f"""<div style="margin-top:10px;margin-bottom:5px;">
<div style="display:flex;justify-content:space-between;font-size:0.76rem;color:#94a3b8;font-weight:500;margin-bottom:3px;">
<span>{label_text}</span>
<span>{mins_left}m remaining</span>
</div>
<div style="width:100%;background:rgba(255,255,255,0.05);border-radius:99px;height:6px;overflow:hidden;" class="{progress_cls}">
<div style="width:{pct_used}%;background:{bar_color};height:100%;border-radius:99px;"></div>
</div>
</div>"""

            sla_html = ""
            if breached:
                sla_html = '<span class="tag tag-sla">⏰ SLA OVERDUE</span>'
            elif mins is not None:
                sla_html = f'<span class="tag tag-sla">SLA {mins}min left</span>'

            fallback_html = ""
            if model and "turbo" in model:
                fallback_html = f'<span class="tag tag-fallback">fallback: {model}</span>'

            traj_html = ""
            if traj == "escalating":
                traj_html = '<span class="tag tag-escalating">📈 escalating</span>'
            elif traj == "de-escalating":
                traj_html = '<span class="tag tag-stable">📉 de-escalating</span>'

            sarcasm_html = '<span class="tag tag-sarcasm">🎭 sarcasm?</span>' if sarcasm else ""
            legal_html   = '<span class="tag tag-legal">⚖️ legal block</span>' if legal else ""
            contact_html = (
                f'<span style="color:#fb923c;font-size:.75rem;font-weight:600">'
                f'⚠️ {contact}× contact</span>'
            ) if contact >= 2 else ""
            followers_html = (
                f'<span style="color:#a78bfa;font-size:.75rem;font-weight:600">'
                f'👁 {followers:,} followers</span>'
            ) if followers >= 10000 else ""

            urg = ev.get("urgency", "medium")

            # Translation html (XSS escape)
            content_en = ev.get("content_en")
            translation_html = ""
            if lang != "en" and content_en and content_en != ev["content"]:
                translation_html = f'<div class="translation-box"><span style="background: rgba(139, 92, 246, 0.15); color: #a78bfa; border: 1px solid rgba(139, 92, 246, 0.3); border-radius: 4px; padding: 2px 6px; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; margin-right: 6px;">Translation</span> {html.escape(content_en)}</div>'

            draft_reply     = ev.get("draft_reply")
            draft_reply_alt = ev.get("draft_reply_alt")
            draft_reply_en  = ev.get("draft_reply_en")
            draft_trans_html = ""
            if lang != "en" and draft_reply and draft_reply_en and draft_reply_en != draft_reply:
                draft_trans_html = f'<div class="translation-box" style="margin-top:2px"><span style="background: rgba(139, 92, 246, 0.15); color: #a78bfa; border: 1px solid rgba(139, 92, 246, 0.3); border-radius: 4px; padding: 2px 6px; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; margin-right: 6px;">Translation</span> {html.escape(draft_reply_en)}</div>'

            # Legal block warning
            legal_banner_html = ""
            if legal:
                legal_banner_html = (
                    '<div class="legal-block-banner">'
                    '⚖️ HARD LEGAL BLOCK — This message contains legal/PR triggers. '
                    'Do NOT auto-send. Route via official legal or comms channel.'
                    '</div>'
                )

            with st.container():
                st.markdown(f"""
<div class="event-card" style="{card_style}">
<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px">
<div>
<span style="color:#e2e8f0;font-size:1.08rem;font-weight:600">{picon(ev['platform'])} {html.escape(ev['author'])}</span>
<span style="margin-left:6px;font-size:1rem">{lflag(lang)}</span>
{platform_links_html(ev)}
<div style="color:#475569;font-size:.75rem;margin-top:3px;letter-spacing:.02em">
{ev['platform'].upper()} &nbsp;·&nbsp; {ev['event_type']} &nbsp;·&nbsp; {fmt_ts(ev.get('created_at',''))}
&nbsp;&nbsp;{contact_html}&nbsp;{followers_html}
</div>
</div>
<div style="display:flex;flex-wrap:wrap;gap:3px;justify-content:flex-end">
<span class="tag tag-platform">{ev['platform']}</span>
{cluster_tag(cluster)}
{risk_tag(ev.get('risk_score'))}
{conf_tag(conf)}
{urgency_badge}
{urg_tag(urg)}
{routing_tag(routing)}
{traj_html}
{sarcasm_html}
{legal_html}
{sla_html}
{fallback_html}
</div>
</div>
{legal_banner_html}
<div class="msg-box">💬 {html.escape(ev['content'])}</div>
{translation_html}
{sla_progress_html}
<div class="reason-box">🧠 <b>AI reasoning:</b> {html.escape(ev.get('reasoning',''))}</div>
</div>""", unsafe_allow_html=True)

                # ── Urgency Explainability expander ──────────────────────────
                explain_html = ""
                exp_raw = ev.get("urgency_explainability")
                if exp_raw:
                    try:
                        exp = json.loads(exp_raw)
                        explain_html = f"""<div style="margin-top:5px;margin-bottom:12px;background:rgba(20,16,35,0.4);border:1px solid rgba(139,92,246,0.15);border-radius:8px;padding:10px;">
<div style="font-size:0.8rem;color:#a78bfa;font-weight:600;margin-bottom:6px;">📊 Urgency Breakdown (Explainability)</div>
<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;font-size:0.78rem;">
<div style="background:rgba(255,255,255,0.02);padding:6px;border-radius:6px;border:1px solid rgba(255,255,255,0.03);">
<div style="color:#94a3b8;font-weight:500;">Category Weight</div>
<div style="font-size:0.95rem;font-weight:700;color:#67e8f9;margin-top:2px;">{exp['category_weight']:.2f} <span style="font-size:0.65rem;color:#475569;font-weight:normal;">(x40%)</span></div>
<div style="font-size:0.68rem;color:#5b5180;margin-top:2px;">Contrib: +{exp['category_contribution']:.2f}</div>
</div>
<div style="background:rgba(255,255,255,0.02);padding:6px;border-radius:6px;border:1px solid rgba(255,255,255,0.03);">
<div style="color:#94a3b8;font-weight:500;">Sentiment Severity</div>
<div style="font-size:0.95rem;font-weight:700;color:#e879f9;margin-top:2px;">{exp['sentiment_severity']:.2f} <span style="font-size:0.65rem;color:#475569;font-weight:normal;">(x30%)</span></div>
<div style="font-size:0.68rem;color:#5b5180;margin-top:2px;">Contrib: +{exp['sentiment_contribution']:.2f}</div>
</div>
<div style="background:rgba(255,255,255,0.02);padding:6px;border-radius:6px;border:1px solid rgba(255,255,255,0.03);">
<div style="color:#94a3b8;font-weight:500;">Time Factor</div>
<div style="font-size:0.95rem;font-weight:700;color:#fb923c;margin-top:2px;">{exp['time_factor']:.2f} <span style="font-size:0.65rem;color:#475569;font-weight:normal;">(x30%)</span></div>
<div style="font-size:0.68rem;color:#5b5180;margin-top:2px;">{exp['minutes_waiting']:.1f}m wait / {exp['sla_threshold_minutes']}m SLA</div>
</div>
</div>
</div>"""
                    except Exception:
                        pass
                
                if explain_html:
                    with st.expander("📊 Urgency Score Explanation"):
                        st.markdown(explain_html, unsafe_allow_html=True)

                # ── AI Assistor Resolution Guide ─────────────────────────────
                render_ai_assistor(ev)

                # ── A/B Draft toggle ─────────────────────────────────────────
                if draft_reply:
                    if has_alt:
                        ab_choice = st.radio(
                            "Draft variant:",
                            ["🤝 Empathetic (A)", "⚡ Efficient (B)"],
                            key=f"ab_{eid}",
                            horizontal=True,
                            label_visibility="visible"
                        )
                        chosen_draft = draft_reply if "A" in ab_choice else draft_reply_alt
                        draft_label  = "Draft A — Empathetic" if "A" in ab_choice else "Draft B — Efficient"
                        draft_cls    = "draft-box" if "A" in ab_choice else "draft-box-alt"
                        st.markdown(
                            f'<div class="{draft_cls}">✍️ <b>{draft_label}</b> '
                            f'<span style="color:#475569;font-size:.78rem">({lang})</span>: '
                            f'{chosen_draft}</div>',
                            unsafe_allow_html=True
                        )
                        if "A" in ab_choice:
                            st.markdown(draft_trans_html, unsafe_allow_html=True)

                        # Radio change handler
                        prev_ab_key = f"prev_ab_{eid}"
                        if st.session_state.get(prev_ab_key) != ab_choice:
                            st.session_state[f"edt_{eid}"] = chosen_draft
                            st.session_state[prev_ab_key] = ab_choice
                    else:
                        chosen_draft = draft_reply
                        st.markdown(
                            f'<div class="draft-box">✍️ <b>Draft reply</b> '
                            f'<span style="color:#475569;font-size:.78rem">({lang})</span>: '
                            f'{draft_reply}</div>',
                            unsafe_allow_html=True
                        )
                        st.markdown(draft_trans_html, unsafe_allow_html=True)
                else:
                    chosen_draft = ""
                    st.markdown(
                        '<div class="draft-box"><i style="color:#475569">none — escalate tier</i></div>',
                        unsafe_allow_html=True
                    )

                if f"edt_{eid}" not in st.session_state:
                    st.session_state[f"edt_{eid}"] = chosen_draft

                col_ok, col_edit, col_no = st.columns([1, 2.2, 1])

                with col_ok:
                    if st.button("✅ Approve", key=f"app_{eid}", use_container_width=True, type="primary"):
                        s["set_decision"](eid, s["APPROVED"], edited_reply=st.session_state.get(f"edt_{eid}", chosen_draft))
                        st.toast(f"Approved @{ev['author']} — queued for sending", icon="✅")
                        time.sleep(0.4)
                        st.rerun()

                with col_edit:
                    edited = st.text_area(
                        "Edit reply:",
                        key=f"edt_{eid}", height=80, label_visibility="collapsed",
                        placeholder="Edit the draft here, then approve...",
                    )
                    if st.button("✏️ Approve with edits", key=f"appe_{eid}", use_container_width=True):
                        s["set_decision"](eid, s["APPROVED"], edited_reply=st.session_state.get(f"edt_{eid}", ""))
                        st.toast(f"Edited + approved @{ev['author']}", icon="✏️")
                        time.sleep(0.4)
                        st.rerun()

                with col_no:
                    if st.button("❌ Reject", key=f"rej_{eid}", use_container_width=True):
                        s["set_decision"](eid, s["REJECTED"])
                        st.toast(f"Rejected — no reply to @{ev['author']}", icon="🗑")
                        time.sleep(0.4)
                        st.rerun()

                # Audit trail (collapsible)
                with st.expander("🔍 Audit trail"):
                    for entry in s["get_audit_log"](eid):
                        st.caption(
                            f"`{fmt_ts(entry['ts'])}` · **{entry['actor']}** · "
                            f"{entry.get('from_status','—')} → {entry['to_status']} · "
                            f"{entry.get('note','')}"
                        )


# ── TAB 2: ESCALATED ─────────────────────────────────────────────────────────
with tab_escalated:
    escalated = s["get_by_status"](s["ESCALATED"])
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:12px;margin-top:4px;margin-bottom:16px;">
      <h3 style="margin:0;font-size:1.5rem;font-weight:700;color:#e2e8f0;">🚨 Escalated</h3>
      <span style="background:rgba(239,68,68,0.15);color:#ef4444;border:1px solid rgba(239,68,68,0.3);padding:3px 12px;border-radius:99px;font-size:0.85rem;font-weight:700;box-shadow:0 0 10px rgba(239,68,68,0.08);letter-spacing:0.02em;">{escalate_n} critical tickets</span>
    </div>
    """, unsafe_allow_html=True)

    if not escalated:
        st.info("No escalated events. 🎉")
    else:
        st.markdown(
            f"**{len(escalated)} event(s)** classified as too high-risk for the agent to draft. "
            "Handle directly through your official support / legal channel.",
        )
        for ev in escalated:
            eid     = ev["id"]
            lang    = ev.get("language","en") or "en"
            breached= ev.get("sla_breached",0)
            mins, _ = sla_remaining(ev.get("sla_deadline"))
            routing = ev.get("routing_team", "general")
            legal   = ev.get("legal_block", 0)
            cluster = ev.get("intent_cluster")
            followers = ev.get("author_followers", 0) or 0

            # ── Dynamic Urgency Left Border & Badge ─────────────────────────
            urgency_score = ev.get("urgency_score") or 0.0
            hue = int((1.0 - urgency_score) * 120)  # 120 (green) -> 0 (red)
            urgency_color = f"hsl({hue}, 85%, 55%)"
            
            glow_style = ""
            if breached:
                glow_style = "box-shadow: 0 0 20px rgba(239, 68, 68, 0.35); border-color: #ef4444;"
            elif urgency_score >= 0.75:
                glow_style = "box-shadow: 0 0 16px rgba(239, 68, 68, 0.25);"
                
            card_style = f"border-left: 5px solid {urgency_color} !important; {glow_style}"
            urgency_badge = f'<span class="tag" style="background: rgba(255,255,255,0.03); color: {urgency_color}; border: 1px solid {urgency_color};">Urgency: {urgency_score:.2f}</span>'

            # ── Per-Ticket SLA Countdown Progress Bar ───────────────────────
            sla_progress_html = ""
            if mins is not None:
                total_sla_mins = 60 if ev.get("tier") == "escalate" else 120
                mins_left = max(0, mins)
                mins_used = max(0, total_sla_mins - mins_left)
                pct_used = min(100.0, (mins_used / total_sla_mins) * 100.0)
                
                if breached or mins <= 0:
                    bar_color = "#ef4444"
                    pct_used = 100.0
                    progress_cls = "sla-progress-breached"
                    label_text = "⚠️ SLA BREACHED"
                elif pct_used < 25.0:
                    bar_color = "#10b981"
                    progress_cls = ""
                    label_text = f"⏱️ SLA: {mins}m left ({pct_used:.0f}% used)"
                elif pct_used < 75.0:
                    bar_color = "#f59e0b"
                    progress_cls = ""
                    label_text = f"⏱️ SLA: {mins}m left ({pct_used:.0f}% used)"
                else:
                    bar_color = "#ef4444"
                    progress_cls = ""
                    label_text = f"🚨 SLA RISK: {mins}m left ({pct_used:.0f}% used)"
                    
                sla_progress_html = f"""<div style="margin-top:10px;margin-bottom:5px;">
<div style="display:flex;justify-content:space-between;font-size:0.76rem;color:#94a3b8;font-weight:500;margin-bottom:3px;">
<span>{label_text}</span>
<span>{mins_left}m remaining</span>
</div>
<div style="width:100%;background:rgba(255,255,255,0.05);border-radius:99px;height:6px;overflow:hidden;" class="{progress_cls}">
<div style="width:{pct_used}%;background:{bar_color};height:100%;border-radius:99px;"></div>
</div>
</div>"""

            sla_html = ""
            if breached:
                sla_html = '<span class="tag tag-sla">⏰ SLA OVERDUE</span>'
            elif mins is not None:
                sla_html = f'<span class="tag tag-sla">{mins}min left</span>'

            routing_action = {
                "billing":     "🧾 Route to: <b>Billing Team</b> — handle refund/charge dispute",
                "support_eng": "🛠️ Route to: <b>Support Engineering</b> — technical issue",
                "comms_lead":  "📣 Route to: <b>Comms Lead</b> — PR / legal / media risk",
                "general":     "💬 Route to: <b>General Support</b>",
            }.get(routing, "💬 Route to: General Support")

            # Translation html (XSS escape)
            content_en = ev.get("content_en")
            translation_html = ""
            if lang != "en" and content_en and content_en != ev["content"]:
                translation_html = f'<div class="translation-box"><span style="background: rgba(139, 92, 246, 0.15); color: #a78bfa; border: 1px solid rgba(139, 92, 246, 0.3); border-radius: 4px; padding: 2px 6px; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; margin-right: 6px;">Translation</span> {html.escape(content_en)}</div>'

            legal_banner_html = ""
            if legal:
                legal_banner_html = (
                    '<div class="legal-block-banner">'
                    '⚖️ HARD LEGAL BLOCK — Contains legal/PR/safety trigger. '
                    'Never auto-respond. Escalate to legal/comms immediately.'
                    '</div>'
                )

            followers_html = (
                f'<span style="color:#a78bfa;font-size:.75rem;font-weight:600">👁 {followers:,} followers</span>'
            ) if followers >= 10000 else ""

            with st.container():
                st.markdown(f"""
<div class="event-card-escalated" style="{card_style}">
<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px">
<div>
<span style="color:#fca5a5;font-size:1.08rem;font-weight:600">🚨 {picon(ev['platform'])} {html.escape(ev['author'])}</span>
<span style="margin-left:5px">{lflag(lang)}</span>
{platform_links_html(ev)}
<div style="color:#475569;font-size:.75rem;margin-top:3px">
{ev['platform'].upper()} &nbsp;·&nbsp; {fmt_ts(ev.get('created_at',''))}
&nbsp;&nbsp;{followers_html}
</div>
</div>
<div style="display:flex;flex-wrap:wrap;gap:3px;justify-content:flex-end">
<span class="tag tag-platform">{ev['platform']}</span>
{cluster_tag(cluster)}
{risk_tag(ev.get('risk_score'))}
{routing_tag(routing)}
{urgency_badge}
{'<span class="tag tag-legal">⚖️ legal block</span>' if legal else ""}
{sla_html}
</div>
</div>
{legal_banner_html}
<div class="msg-box" style="border-left-color:#ef4444">💬 {html.escape(ev['content'])}</div>
{translation_html}
{sla_progress_html}
<div class="reason-box" style="border-left-color:#ef4444">🧠 <b>Why escalated:</b> {html.escape(ev.get('reasoning',''))}</div>
<div style="background:rgba(6,182,212,0.06);border:1px solid rgba(6,182,212,0.2);border-radius:8px;padding:9px 14px;margin-top:8px;font-size:.83rem;color:#67e8f9">
🎯 {routing_action}
</div>
</div>""", unsafe_allow_html=True)

                # ── Urgency Explainability expander ──────────────────────────
                explain_html = ""
                exp_raw = ev.get("urgency_explainability")
                if exp_raw:
                    try:
                        exp = json.loads(exp_raw)
                        explain_html = f"""<div style="margin-top:5px;margin-bottom:12px;background:rgba(20,16,35,0.4);border:1px solid rgba(139,92,246,0.15);border-radius:8px;padding:10px;">
<div style="font-size:0.8rem;color:#a78bfa;font-weight:600;margin-bottom:6px;">📊 Urgency Breakdown (Explainability)</div>
<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;font-size:0.78rem;">
<div style="background:rgba(255,255,255,0.02);padding:6px;border-radius:6px;border:1px solid rgba(255,255,255,0.03);">
<div style="color:#94a3b8;font-weight:500;">Category Weight</div>
<div style="font-size:0.95rem;font-weight:700;color:#67e8f9;margin-top:2px;">{exp['category_weight']:.2f} <span style="font-size:0.65rem;color:#475569;font-weight:normal;">(x40%)</span></div>
<div style="font-size:0.68rem;color:#5b5180;margin-top:2px;">Contrib: +{exp['category_contribution']:.2f}</div>
</div>
<div style="background:rgba(255,255,255,0.02);padding:6px;border-radius:6px;border:1px solid rgba(255,255,255,0.03);">
<div style="color:#94a3b8;font-weight:500;">Sentiment Severity</div>
<div style="font-size:0.95rem;font-weight:700;color:#e879f9;margin-top:2px;">{exp['sentiment_severity']:.2f} <span style="font-size:0.65rem;color:#475569;font-weight:normal;">(x30%)</span></div>
<div style="font-size:0.68rem;color:#5b5180;margin-top:2px;">Contrib: +{exp['sentiment_contribution']:.2f}</div>
</div>
<div style="background:rgba(255,255,255,0.02);padding:6px;border-radius:6px;border:1px solid rgba(255,255,255,0.03);">
<div style="color:#94a3b8;font-weight:500;">Time Factor</div>
<div style="font-size:0.95rem;font-weight:700;color:#fb923c;margin-top:2px;">{exp['time_factor']:.2f} <span style="font-size:0.65rem;color:#475569;font-weight:normal;">(x30%)</span></div>
<div style="font-size:0.68rem;color:#5b5180;margin-top:2px;">{exp['minutes_waiting']:.1f}m wait / {exp['sla_threshold_minutes']}m SLA</div>
</div>
</div>
</div>"""
                    except Exception:
                        pass
                
                if explain_html:
                    with st.expander("📊 Urgency Score Explanation"):
                        st.markdown(explain_html, unsafe_allow_html=True)

                # Call AI Assistor to render guide + draft
                render_ai_assistor(ev)

                # Resolution UI
                st.markdown("#### 🎯 Resolve Escalation")
                
                suggested_draft = ev.get("ai_assist_suggested_reply") or ""
                if f"edt_{eid}" not in st.session_state:
                    st.session_state[f"edt_{eid}"] = suggested_draft

                col_ok, col_edit, col_no = st.columns([1, 2.2, 1])

                with col_ok:
                    if st.button("✅ Resolve", key=f"app_esc_{eid}", use_container_width=True, type="primary"):
                        s["set_decision"](eid, s["APPROVED"], edited_reply=st.session_state.get(f"edt_{eid}", ""))
                        st.toast(f"Resolved @{ev['author']} — queued for sending", icon="✅")
                        time.sleep(0.4)
                        st.rerun()

                with col_edit:
                    edited = st.text_area(
                        "Edit reply:",
                        key=f"edt_{eid}", height=80, label_visibility="collapsed",
                        placeholder="Write or edit the resolution response here...",
                    )

                with col_no:
                    if st.button("❌ Dismiss", key=f"rej_esc_{eid}", use_container_width=True):
                        s["set_decision"](eid, s["REJECTED"])
                        st.toast(f"Dismissed — closed escalation for @{ev['author']}", icon="🗑")
                        time.sleep(0.4)
                        st.rerun()

            with st.expander("🔍 Audit trail"):
                for entry in s["get_audit_log"](ev["id"]):
                    st.caption(
                        f"`{fmt_ts(entry['ts'])}` · **{entry['actor']}** · "
                        f"{entry.get('from_status','—')} → {entry['to_status']} · "
                        f"{entry.get('note','')}"
                    )


# ── TAB 3: ANALYTICS ─────────────────────────────────────────────────────────
with tab_analytics:
    # ── Date-range filter ─────────────────────────────────────────────────────
    from datetime import timedelta
    _date_col, _spacer = st.columns([1.5, 4])
    with _date_col:
        date_range = st.selectbox(
            "📅 Date Range",
            options=["Last 24h", "Last 7 days", "Last 30 days", "All Time"],
            index=3,
            key="analytics_date_range",
        )

    # Compute cutoff ISO string based on selection
    _now_utc = datetime.now(timezone.utc)
    _cutoff_map = {
        "Last 24h":    (_now_utc - timedelta(hours=24)).isoformat(),
        "Last 7 days": (_now_utc - timedelta(days=7)).isoformat(),
        "Last 30 days":(_now_utc - timedelta(days=30)).isoformat(),
        "All Time":    None,
    }
    _cutoff = _cutoff_map[date_range]

    # If filtering, recompute stats from the filtered event set
    if _cutoff:
        _all = s["get_all"](limit=5000)
        _filtered = [e for e in _all if (e.get("created_at") or "") >= _cutoff]
        _f_status = {}
        for e in _filtered:
            _f_status[e["status"]] = _f_status.get(e["status"], 0) + 1
        _f_intent = {}
        for e in _filtered:
            if e.get("intent"):
                _f_intent[e["intent"]] = _f_intent.get(e["intent"], 0) + 1
        _f_cluster = {}
        for e in _filtered:
            if e.get("intent_cluster"):
                _f_cluster[e["intent_cluster"]] = _f_cluster.get(e["intent_cluster"], 0) + 1
        _f_platform = {}
        for e in _filtered:
            if e.get("platform"):
                _f_platform[e["platform"]] = _f_platform.get(e["platform"], 0) + 1
        _f_lang = {}
        for e in _filtered:
            if e.get("language"):
                _f_lang[e["language"]] = _f_lang.get(e["language"], 0) + 1
        _f_routing = {}
        for e in _filtered:
            if e.get("routing_team"):
                _f_routing[e["routing_team"]] = _f_routing.get(e["routing_team"], 0) + 1
        _f_sarcasm = sum(1 for e in _filtered if e.get("sarcasm_flag"))
        _f_risks = [e["risk_score"] for e in _filtered if e.get("risk_score") is not None]
        _f_avg_risk = sum(_f_risks) / len(_f_risks) if _f_risks else 0
        _f_sla_breached = sum(1 for e in _filtered if e.get("sla_breached"))
        # Use filtered stats
        stats = dict(stats)  # copy
        stats["by_status"] = _f_status
        stats["by_intent"] = _f_intent
        stats["by_cluster"] = _f_cluster
        stats["by_platform"] = _f_platform
        stats["by_language"] = _f_lang
        stats["by_routing_team"] = _f_routing
        stats["sarcasm_count"] = _f_sarcasm
        stats["avg_risk_score"] = round(_f_avg_risk, 3)
        stats["sla_breached"] = _f_sla_breached

    st.caption(f"Showing data for: **{date_range}**")
    st.markdown("<hr style='border:none;border-top:1px solid rgba(99,102,241,0.10);margin:6px 0 18px'>", unsafe_allow_html=True)

    # KPI header
    total_events = sum(stats["by_status"].values()) or 1
    auto_rate    = round(stats["by_status"].get("auto_handled",0) / total_events * 100)
    esc_rate_pct = round(stats["by_status"].get("escalated",0) / total_events * 100)
    sent_total   = stats["by_status"].get("sent",0)
    sla_ok       = sent_total - stats.get("sla_breached",0)
    sla_pct      = round(sla_ok / sent_total * 100) if sent_total else 100
    avg_risk     = stats.get("avg_risk_score", 0)
    sarcasm_pct  = round(stats.get("sarcasm_count",0) / total_events * 100, 1)


    kpis = [
        ("Total Events",    total_events,         "#6366f1", "📨"),
        ("Auto-resolved",   f"{auto_rate}%",       "#10b981", "⚡"),
        ("Escalation Rate", f"{esc_rate_pct}%",    "#ef4444", "🚨"),
        ("SLA Compliance",  f"{sla_pct}%",         "#06b6d4", "⏱️"),
        ("Avg Risk Score",  f"{avg_risk:.2f}",      "#f59e0b", "🎯"),
        ("Sarcasm Rate",    f"{sarcasm_pct}%",      "#e879f9", "🎭"),
    ]
    kpi_html = "<div style='display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin-bottom:24px'>"
    for label, val, color, icon in kpis:
        kpi_html += (
            f'<div class="metric-card">'
            f'<div style="font-size:1.5rem;margin-bottom:4px">{icon}</div>'
            f'<div style="font-size:1.6rem;font-weight:700;color:{color};letter-spacing:-.02em">{val}</div>'
            f'<div style="font-size:.72rem;color:#475569;text-transform:uppercase;letter-spacing:.06em;margin-top:3px">{label}</div>'
            f'</div>'
        )
    kpi_html += "</div>"
    st.markdown(kpi_html, unsafe_allow_html=True)

    st.markdown("<hr style='border:none;border-top:1px solid rgba(99,102,241,0.12);margin:0 0 20px'>", unsafe_allow_html=True)

    # ── Plotly theme helper ───────────────────────────────────────────────────
    def _plotly_bar(labels, values, colors=None, title="", h=320, horizontal=False,
                    text_auto=True, color_seq=None):
        """Render a styled Plotly bar chart matching the dark dashboard theme."""
        if not _PLOTLY:
            st.bar_chart(dict(zip(labels, values)))
            return
        palette = color_seq or [
            "#6366f1","#8b5cf6","#06b6d4","#10b981",
            "#f59e0b","#ef4444","#ec4899","#f97316",
            "#3b82f6","#14b8a6","#a855f7","#fb923c",
        ]
        bar_colors = colors if colors else [palette[i % len(palette)] for i in range(len(labels))]
        if horizontal:
            fig = go.Figure(go.Bar(
                x=values, y=labels,
                orientation='h',
                marker=dict(
                    color=bar_colors,
                    line=dict(color="rgba(255,255,255,0.05)", width=1),
                ),
                text=[f"{v:,}" for v in values],
                textposition="outside",
                textfont=dict(color="#94a3b8", size=11, family="Outfit"),
                hovertemplate="<b>%{y}</b><br>Count: %{x:,}<extra></extra>",
            ))
        else:
            fig = go.Figure(go.Bar(
                x=labels, y=values,
                marker=dict(
                    color=bar_colors,
                    line=dict(color="rgba(255,255,255,0.05)", width=1),
                    cornerradius=6,
                ),
                text=[f"{v:,}" for v in values],
                textposition="outside",
                textfont=dict(color="#94a3b8", size=11, family="Outfit"),
                hovertemplate="<b>%{x}</b><br>Count: %{y:,}<extra></extra>",
            ))
        fig.update_layout(
            title=dict(text=title, font=dict(color="#e2e8f0", size=13, family="Outfit"), x=0) if title else None,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Outfit", color="#94a3b8"),
            height=h,
            margin=dict(l=10, r=10, t=30 if title else 10, b=40),
            xaxis=dict(
                showgrid=not horizontal,
                gridcolor="rgba(255,255,255,0.04)",
                gridwidth=1,
                zeroline=False,
                tickfont=dict(size=11, color="#64748b"),
                showline=False,
            ),
            yaxis=dict(
                showgrid=horizontal,
                gridcolor="rgba(255,255,255,0.04)",
                gridwidth=1,
                zeroline=False,
                tickfont=dict(size=11, color="#64748b"),
                showline=False,
            ),
            hoverlabel=dict(
                bgcolor="rgba(15,12,28,0.95)",
                bordercolor="rgba(99,102,241,0.5)",
                font=dict(color="#e2e8f0", size=12, family="Outfit"),
            ),
            bargap=0.35,
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    def _plotly_donut(labels, values, colors=None, h=320):
        """Render a styled Plotly donut/pie chart."""
        if not _PLOTLY:
            st.bar_chart(dict(zip(labels, values)))
            return
        palette = [
            "#6366f1","#8b5cf6","#06b6d4","#10b981",
            "#f59e0b","#ef4444","#ec4899","#f97316",
        ]
        bar_colors = colors if colors else palette
        fig = go.Figure(go.Pie(
            labels=labels, values=values,
            hole=0.55,
            marker=dict(colors=bar_colors, line=dict(color="rgba(7,5,14,0.8)", width=3)),
            textinfo="label+percent",
            textfont=dict(size=11, color="#e2e8f0", family="Outfit"),
            hovertemplate="<b>%{label}</b><br>%{value:,} events<br>%{percent}<extra></extra>",
            pull=[0.04 if i == 0 else 0 for i in range(len(labels))],
        ))
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Outfit", color="#94a3b8"),
            height=h,
            margin=dict(l=10, r=10, t=10, b=10),
            showlegend=True,
            legend=dict(
                bgcolor="rgba(0,0,0,0)",
                font=dict(color="#94a3b8", size=11),
                orientation="v",
                x=1.02,
            ),
            hoverlabel=dict(
                bgcolor="rgba(15,12,28,0.95)",
                bordercolor="rgba(99,102,241,0.5)",
                font=dict(color="#e2e8f0", size=12, family="Outfit"),
            ),
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── Row 1: Tier + Intent ─────────────────────────────────────────────────
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("""
        <div style='font-size:.7rem;text-transform:uppercase;letter-spacing:.1em;
        color:#475569;font-weight:600;margin-bottom:6px'>Tier Distribution</div>
        """, unsafe_allow_html=True)
        tier_data = {
            "AUTO":          stats["by_status"].get("auto_handled",0)       + stats["by_status"].get("sent",0),
            "DRAFT+APPROVE": stats["by_status"].get("awaiting_approval",0)  + stats["by_status"].get("approved",0) + stats["by_status"].get("rejected",0),
            "ESCALATE":      stats["by_status"].get("escalated",0),
        }
        if any(tier_data.values()):
            _plotly_donut(
                list(tier_data.keys()), list(tier_data.values()),
                colors=["#10b981", "#6366f1", "#ef4444"],
            )
        else:
            st.caption("No data yet.")

    with col2:
        st.markdown("""
        <div style='font-size:.7rem;text-transform:uppercase;letter-spacing:.1em;
        color:#475569;font-weight:600;margin-bottom:6px'>Intent Breakdown</div>
        """, unsafe_allow_html=True)
        intent_data = stats.get("by_intent", {})
        if intent_data:
            _labels = list(intent_data.keys())
            _values = list(intent_data.values())
            _plotly_bar(_labels, _values, horizontal=True, h=max(280, len(_labels) * 38))
        else:
            st.caption("No data yet.")

    # ── Row 2: Intent Cluster Spike + Routing Team ───────────────────────────
    col_cl, col_rt = st.columns(2)
    with col_cl:
        st.markdown("""
        <div style='font-size:.7rem;text-transform:uppercase;letter-spacing:.1em;
        color:#475569;font-weight:600;margin-bottom:6px'>🏷 Intent Cluster Distribution</div>
        """, unsafe_allow_html=True)
        cluster_data = stats.get("by_cluster", {})
        if cluster_data:
            _cl_labels = [k.replace('_',' ').title() for k in cluster_data.keys()]
            _cl_values = list(cluster_data.values())
            _plotly_bar(_cl_labels, _cl_values, h=300)
        else:
            st.caption("No cluster data yet.")

    with col_rt:
        st.markdown("""
        <div style='font-size:.7rem;text-transform:uppercase;letter-spacing:.1em;
        color:#475569;font-weight:600;margin-bottom:6px'>🎯 Routing Team Distribution</div>
        """, unsafe_allow_html=True)
        routing_data = stats.get("by_routing_team", {})
        if routing_data:
            icons = {"billing":"🧾 Billing","support_eng":"🛠️ Support Eng","comms_lead":"📣 Comms Lead","general":"💬 General"}
            _rt_labels = [icons.get(k, k.replace('_',' ').title()) for k in routing_data.keys()]
            _rt_values = list(routing_data.values())
            _plotly_donut(_rt_labels, _rt_values,
                          colors=["#f59e0b","#06b6d4","#8b5cf6","#10b981"])
        else:
            st.caption("No routing data yet.")

    # ── Row 3: Platform + Language ───────────────────────────────────────────
    col3, col4 = st.columns(2)
    with col3:
        st.markdown("""
        <div style='font-size:.7rem;text-transform:uppercase;letter-spacing:.1em;
        color:#475569;font-weight:600;margin-bottom:6px'>Platform Breakdown</div>
        """, unsafe_allow_html=True)
        platform_data = stats.get("by_platform", {})
        if platform_data:
            _pf_labels = list(platform_data.keys())
            _pf_values = list(platform_data.values())
            _pf_colors = {
                "twitter":   "#1DA1F2", "instagram": "#E1306C",
                "facebook":  "#4267B2", "linkedin":  "#0A66C2",
                "tiktok":    "#69C9D0", "youtube":   "#FF0000",
                "reddit":    "#FF4500",
            }
            _colors = [_pf_colors.get(p.lower(), "#6366f1") for p in _pf_labels]
            _plotly_bar(_pf_labels, _pf_values, colors=_colors, h=300)
        else:
            st.caption("No data yet.")

    with col4:
        st.markdown("""
        <div style='font-size:.7rem;text-transform:uppercase;letter-spacing:.1em;
        color:#475569;font-weight:600;margin-bottom:6px'>Language Distribution</div>
        """, unsafe_allow_html=True)
        lang_data = stats.get("by_language", {})
        if lang_data:
            # Sort by count descending, show top 15 to keep chart readable
            _sorted_lang = sorted(lang_data.items(), key=lambda x: -x[1])[:15]
            _lg_labels = [f"{lflag(k)} {k}" for k, _ in _sorted_lang]
            _lg_values = [v for _, v in _sorted_lang]
            _plotly_bar(_lg_labels, _lg_values, h=300)
        else:
            st.caption("No data yet.")

    # ── Root-cause Brand Health Breakdown ────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 🔍 Root-Cause Brand Health Breakdown")
    cluster_data = stats.get("by_cluster", {})
    crm_sentiments = stats.get("crm_sentiments", {})
    if cluster_data:
        neg_cluster_total = sum(cluster_data.values()) or 1
        bar_colors = CLUSTER_COLORS
        rows_html = ""
        for i, (cluster, count) in enumerate(sorted(cluster_data.items(), key=lambda x: -x[1])):
            pct = count / neg_cluster_total * 100
            color = bar_colors[i % len(bar_colors)]
            label = cluster.replace("_", " ").title()
            rows_html += (
                f'<div class="rootcause-row">'
                f'<div class="rootcause-label">{label}</div>'
                f'<div class="rootcause-bar-wrap">'
                f'<div class="rootcause-bar-fill" style="width:{pct:.0f}%;background:{color}"></div>'
                f'</div>'
                f'<div class="rootcause-pct">{pct:.0f}%</div>'
                f'</div>'
            )
        st.markdown(rows_html, unsafe_allow_html=True)
    else:
        st.caption("Cluster data will appear after triage runs.")

    # CRM sentiment breakdown
    if crm_sentiments:
        total_crm = sum(crm_sentiments.values()) or 1
        sent_colors = {
            "positive":"#10b981","neutral":"#6366f1",
            "negative":"#f59e0b","very_negative":"#ef4444"
        }
        sent_html = ""
        for sent, count in sorted(crm_sentiments.items(), key=lambda x: -x[1]):
            pct = count / total_crm * 100
            color = sent_colors.get(sent, "#94a3b8")
            label = sent.replace("_", " ").title()
            sent_html += (
                f'<div class="rootcause-row">'
                f'<div class="rootcause-label">{label}</div>'
                f'<div class="rootcause-bar-wrap">'
                f'<div class="rootcause-bar-fill" style="width:{pct:.0f}%;background:{color}"></div>'
                f'</div>'
                f'<div class="rootcause-pct">{pct:.0f}%</div>'
                f'</div>'
            )
        st.markdown("**CRM Sentiment Breakdown:**")
        st.markdown(sent_html, unsafe_allow_html=True)

    # ── SLA Prediction Panel ──────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### ⚡ SLA Breach Prediction (Next 30 Min)")
    try:
        at_risk = s["get_sla_at_risk"](minutes=30)
        if at_risk:
            for ar in at_risk:
                mins, _ = sla_remaining(ar.get("sla_deadline"))
                mins_str = f"{mins}min" if mins is not None else "imminent"
                st.markdown(
                    f'<div class="sla-predict">'
                    f'⚡ <b>{ar["author"]}</b> on {ar["platform"]} — '
                    f'"{ar["content"][:60]}..." — breaches in <b>{mins_str}</b>'
                    f'</div>',
                    unsafe_allow_html=True
                )
        else:
            st.success("✅ No SLA breaches predicted in the next 30 minutes.")
    except Exception as e:
        st.caption(f"SLA prediction unavailable: {e}")

    # ── Lifecycle Status Counts ───────────────────────────────────────────────
    st.markdown("---")
    st.markdown("""
    <div style='font-size:.7rem;text-transform:uppercase;letter-spacing:.1em;
    color:#475569;font-weight:600;margin-bottom:6px'>Lifecycle Status Counts</div>
    """, unsafe_allow_html=True)
    status_labels = {
        "pending_triage":    "⏳ Pending",
        "auto_handled":      "✅ Auto-handled",
        "awaiting_approval": "📋 Awaiting",
        "approved":          "👍 Approved",
        "rejected":          "❌ Rejected",
        "escalated":         "🚨 Escalated",
        "sent":              "📤 Sent",
        "triage_failed":     "⚠️ Failed",
    }
    _status_colors = {
        "⏳ Pending":    "#64748b",
        "✅ Auto-handled":"#10b981",
        "📋 Awaiting":   "#6366f1",
        "👍 Approved":   "#06b6d4",
        "❌ Rejected":   "#ef4444",
        "🚨 Escalated":  "#f97316",
        "📤 Sent":       "#8b5cf6",
        "⚠️ Failed":     "#f59e0b",
    }
    chart_data = {status_labels.get(k, k): v for k, v in stats["by_status"].items() if v > 0}
    if chart_data:
        _sc_labels = list(chart_data.keys())
        _sc_values = list(chart_data.values())
        _sc_colors = [_status_colors.get(l, "#6366f1") for l in _sc_labels]
        _plotly_bar(_sc_labels, _sc_values, colors=_sc_colors, h=300)

    # ── Safety Stats ──────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 🛡️ Safety & Compliance")
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        legal_c = stats.get("legal_block_count", 0)
        st.metric("Legal Blocks", legal_c, help="Events with hard legal/PR block")
    with col_s2:
        pii_c = stats.get("pii_flagged_count", 0)
        st.metric("PII Flags", pii_c, help="Events where PII was detected in reply")
    with col_s3:
        esc_traj = stats.get("escalating_count", 0)
        st.metric("Escalating Authors", esc_traj, help="Authors with unresolved prior contacts")

    # ── Crisis history ────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Crisis Log")
    crises_all = s["get_recent_crises"](limit=10)
    if crises_all:
        for c in crises_all:
            status_icon = "✅ Resolved" if c.get("resolved") else "🔴 Active"
            cluster_note = f" · cluster: **{c['cluster_name']}**" if c.get("cluster_name") else ""
            st.markdown(
                f"- **{fmt_ts(c['detected_at'])}** — {c['event_count']} events "
                f"in {c['window_mins']}min window · {status_icon}{cluster_note}"
            )
    else:
        st.caption("No crises recorded.")

    # ── Autopilot Decision Analytics ──────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 🤖 Autopilot Decisions Breakdown")
    try:
        from store import get_conn
        with get_conn() as conn:
            decisions = conn.execute(
                "SELECT autopilot_decision, COUNT(*) as c FROM events WHERE autopilot_decision IS NOT NULL GROUP BY autopilot_decision"
            ).fetchall()
            
            recent_gated = conn.execute(
                "SELECT author, platform, intent_cluster, autopilot_decision, autopilot_reason, updated_at FROM events WHERE autopilot_decision IS NOT NULL ORDER BY updated_at DESC LIMIT 5"
            ).fetchall()
            
        if decisions:
            dec_data = {d["autopilot_decision"]: d["c"] for d in decisions}
            _dec_colors = ["#10b981" if "approve" in k else "#ef4444" if "reject" in k else "#f59e0b" for k in dec_data]
            _plotly_bar(list(dec_data.keys()), list(dec_data.values()), colors=_dec_colors, h=260)

            st.markdown("**Recent Autopilot Decisions Log:**")
            for rg in recent_gated:
                dec_emoji = "✅" if "approve" in rg["autopilot_decision"] else "🚨"
                cluster_lbl = rg["intent_cluster"].replace("_", " ").title() if rg["intent_cluster"] else "N/A"
                st.caption(
                    f"{dec_emoji} **{rg['autopilot_decision'].upper()}** for @{html.escape(rg['author'])} ({rg['platform']}) · "
                    f"Cluster: `{cluster_lbl}` · Reason: *{html.escape(rg['autopilot_reason'] or 'N/A')}*"
                )
        else:
            st.info("No autopilot decisions logged yet. Run some events to view autopilot decision telemetry.")
    except Exception as e:
        st.caption(f"Autopilot telemetry unavailable: {e}")

    # ── Model Reliability ─────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("""
    <div style='font-size:.7rem;text-transform:uppercase;letter-spacing:.1em;
    color:#475569;font-weight:600;margin-bottom:6px'>Model Reliability</div>
    """, unsafe_allow_html=True)
    fallback = stats.get("fallback_used", 0)
    primary  = total_events - fallback
    if total_events > 0:
        prim_name = os.getenv("QWEN_PRIMARY_MODEL", "qwen-turbo")
        fall_name = os.getenv("QWEN_FALLBACK_MODEL", "qwen-turbo")
        _plotly_bar(
            [f"{prim_name} (primary)", f"{fall_name} (fallback)"],
            [primary, fallback],
            colors=["#06b6d4", "#8b5cf6"],
            h=260,
        )


# ── TAB 4: HISTORY ───────────────────────────────────────────────────────────
with tab_history:
    all_events = s["get_all"]()
    history = [
        e for e in all_events
        if e["status"] in (s["AUTO"], s["SENT"], s["REJECTED"])
    ]
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:12px;margin-top:4px;margin-bottom:16px;">
      <h3 style="margin:0;font-size:1.5rem;font-weight:700;color:#e2e8f0;">📜 History</h3>
      <span style="background:rgba(16,185,129,0.15);color:#10b981;border:1px solid rgba(16,185,129,0.3);padding:3px 12px;border-radius:99px;font-size:0.85rem;font-weight:700;box-shadow:0 0 10px rgba(16,185,129,0.08);letter-spacing:0.02em;">{len(history)} processed</span>
    </div>
    """, unsafe_allow_html=True)

    if not history:
        st.info("No completed events yet.")
    else:
        st.markdown(f"**{len(history)} completed event(s)** — full audit trail with CRM tags.")

        for ev in history:
            status   = ev["status"]
            lang     = ev.get("language","en") or "en"
            final    = ev.get("final_reply") or ev.get("draft_reply") or ""
            crm      = crm_info(ev)
            sent_at  = fmt_ts(ev.get("sent_at",""))
            has_edit = bool(ev.get("edit_diff"))
            pii_flag = ev.get("pii_flagged", 0)

            if status == s["SENT"]:
                status_html = '<span class="tag tag-sent">SENT</span>'
            elif status == s["REJECTED"]:
                status_html = '<span class="tag tag-rejected">REJECTED</span>'
            else:
                status_html = '<span class="tag tag-auto">AUTO</span>'

            edit_html = '<span class="tag tag-edit">✏️ human edited</span>' if has_edit else ""
            pii_html  = '<span class="tag tag-pii">🔒 PII flagged</span>' if pii_flag else ""

            crm_html = ""
            if crm:
                fu = "✅ Follow-up needed" if crm.get("follow_up_required") else "No follow-up"
                crm_html = (
                    f'<div class="crm-box">📋 CRM: <b>{crm.get("crm_category","?")}</b> · '
                    f'priority={crm.get("priority","?")} · sentiment={crm.get("sentiment","?")} · {fu}</div>'
                )

            # Translation html
            content_en = ev.get("content_en")
            translation_html = ""
            if lang != "en" and content_en and content_en != ev["content"]:
                translation_html = f'<div class="translation-box" style="padding:4px 8px;margin:2px 0 6px;font-size:0.78rem">🇺🇸 <b>Translation:</b> {content_en[:120]}{"…" if len(content_en) > 120 else ""}</div>'

            final_en = ev.get("draft_reply_en")
            final_trans_html = ""
            if lang != "en" and final and final_en and final_en != final:
                final_trans_html = f'<div class="translation-box" style="padding:4px 8px;margin:2px 0 6px;font-size:0.78rem">🇺🇸 <b>Translation:</b> {final_en[:120]}{"…" if len(final_en) > 120 else ""}</div>'

            cluster = ev.get("intent_cluster")

            st.markdown(f"""
<div class="event-card-history">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
<span style="color:#c9d1e9;font-size:.95rem;font-weight:500">
{picon(ev['platform'])} {ev['author']} {lflag(lang)}
{platform_links_html(ev)}
<span style="color:#374151;font-size:.75rem;margin-left:8px">{ev['platform'].upper()} · {fmt_ts(ev.get('created_at',''))}</span>
</span>
<div>
{status_html}
<span class="tag tag-intent">{ev.get('intent','')}</span>
{cluster_tag(cluster)}
{risk_tag(ev.get('risk_score'))}
{edit_html}
{pii_html}
</div>
</div>
<div style="color:#64748b;font-size:.87rem;line-height:1.4;margin:6px 0">
💬 {ev['content'][:130]}{"…" if len(ev['content']) > 130 else ""}
</div>
{translation_html}
{"<div style='color:#34d399;font-size:.82rem;margin-top:4px;padding:6px 10px;background:rgba(16,185,129,0.06);border-radius:6px;border-left:2px solid #10b981'>📤 " + final[:120] + ("…" if len(final) > 120 else "") + "</div>" if final and status != s["REJECTED"] else ""}
{final_trans_html}
{crm_html}
<div style="color:#1f2937;font-size:.72rem;margin-top:6px">
{'Sent: ' + sent_at if sent_at else 'Updated: ' + fmt_ts(ev.get('updated_at',''))}
{' · model: ' + (ev.get('triage_model') or '?')}
{' · retries: ' + str(ev.get('retry_count',0))}
</div>
</div>""", unsafe_allow_html=True)

            with st.expander("🔍 Full audit trail"):
                for entry in s["get_audit_log"](ev["id"]):
                    st.caption(
                        f"`{fmt_ts(entry['ts'])}` · **{entry['actor']}** · "
                        f"{entry.get('from_status','—')} → {entry['to_status']} · "
                        f"{entry.get('note','')}"
                    )

            # Show edit diff detail if exists
            if has_edit:
                with st.expander("✏️ Edit diff — AI draft vs human final"):
                    try:
                        diff = json.loads(ev["edit_diff"])
                        st.markdown("**AI draft:**")
                        st.markdown(
                            f'<div class="draft-box">{diff.get("original","")}</div>',
                            unsafe_allow_html=True
                        )
                        st.markdown("**Human edited to:**")
                        st.markdown(
                            f'<div class="draft-box-alt">{diff.get("edited","")}</div>',
                            unsafe_allow_html=True
                        )
                    except Exception:
                        st.caption("Edit diff unavailable.")


# ── TAB 5: INTELLIGENCE ──────────────────────────────────────────────────────
with tab_intel:
    st.markdown("""
<div style='padding:0 0 18px'>
  <div style='font-size:1.5rem;font-weight:700;background:linear-gradient(135deg,#8b5cf6,#06b6d4);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text'>
    🧠 Intelligence Center
  </div>
  <div style='color:#475569;font-size:.85rem;margin-top:2px'>
    Proactive outreach · Emotion recovery · Voice-of-customer digest · Auto-learn
  </div>
</div>
""", unsafe_allow_html=True)

    int_col1, int_col2 = st.columns([1.2, 1])

    # ── LEFT: Proactive Outreach + Emotion Recovery ──────────────────────────
    with int_col1:
        st.markdown("### 📡 Proactive Outreach Mode")
        st.markdown(
            "<div style='color:#94a3b8;font-size:.84rem;margin-bottom:12px'>"
            "Trending complaint clusters — draft a preemptive public statement before issues go viral."
            "</div>",
            unsafe_allow_html=True
        )

        try:
            trending = s["get_trending_complaints"](window_hours=2, min_count=2)
            if trending:
                for t in trending:
                    label = t["cluster"].replace("_", " ").title()
                    st.markdown(
                        f'<div class="intel-card">'
                        f'<div style="display:flex;justify-content:space-between;align-items:center">'
                        f'<div>'
                        f'<span style="color:#e879f9;font-weight:600">🏷 {label}</span>'
                        f'<span style="color:#475569;font-size:.78rem;margin-left:8px">× {t["count"]} in last 2h</span>'
                        f'</div>'
                        f'</div>'
                        f'<div style="color:#94a3b8;font-size:.80rem;margin-top:6px">'
                        f'Consider drafting a pinned public reply or proactive FAQ update.'
                        f'</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )
                    if st.button(f"✍️ Draft statement for '{label}'",
                                 key=f"draft_stmt_{t['cluster']}", use_container_width=True):
                        st.info(f"🚀 Would call Qwen to generate a preemptive public statement "
                                f"for '{label}' cluster. Connect to triage API to enable.")
            else:
                st.success("✅ No trending complaint clusters right now.")
        except Exception as e:
            st.caption(f"Trending data unavailable: {e}")

        st.markdown("---")
        st.markdown("### 💚 Customer Emotion Recovery")
        st.markdown(
            "<div style='color:#94a3b8;font-size:.84rem;margin-bottom:12px'>"
            "Resolved escalations older than 48h without follow-up — check back in to close the loop."
            "</div>",
            unsafe_allow_html=True
        )

        try:
            recovery_events = s["get_resolved_escalations_for_followup"](hours_min=48)
            if recovery_events:
                for rev in recovery_events[:5]:
                    st.markdown(
                        f'<div class="intel-card-recovery">'
                        f'<div style="display:flex;justify-content:space-between">'
                        f'<span style="color:#34d399;font-weight:600">{picon(rev["platform"])} {rev["author"]}</span>'
                        f'<span style="color:#475569;font-size:.75rem">{fmt_ts(rev.get("sent_at",""))}</span>'
                        f'</div>'
                        f'<div style="color:#94a3b8;font-size:.82rem;margin-top:4px">'
                        f'"{rev["content"][:80]}..."</div>'
                        f'<div style="color:#10b981;font-size:.78rem;margin-top:6px">'
                        f'✅ Resolved · Ready for 48h satisfaction follow-up</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )
                    if st.button(f"📧 Send follow-up to {rev['author']}",
                                 key=f"followup_{rev['id']}", use_container_width=True):
                        st.info("🚀 Would trigger a follow-up message via platform API. "
                                "Connect to social API to enable.")
                if len(recovery_events) > 5:
                    st.caption(f"...and {len(recovery_events)-5} more eligible for follow-up.")
            else:
                st.success("✅ All resolved escalations have been followed up.")
        except Exception as e:
            st.caption(f"Recovery data unavailable: {e}")

    # ── RIGHT: Voice-of-Customer Digest + Auto-Learn ─────────────────────────
    with int_col2:
        st.markdown("### 📋 Voice-of-Customer Digest")
        st.markdown(
            "<div style='color:#94a3b8;font-size:.84rem;margin-bottom:12px'>"
            "Weekly auto-generated summary of top themes and pain points."
            "</div>",
            unsafe_allow_html=True
        )

        digest_days = st.selectbox("Period:", [7, 14, 30], key="digest_period",
                                   format_func=lambda x: f"Last {x} days")

        if st.button("📋 Generate Digest", use_container_width=True, type="primary",
                     key="gen_digest"):
            with st.spinner("Aggregating voice-of-customer data..."):
                try:
                    data = s["get_weekly_digest_data"](days=digest_days)

                    st.markdown(
                        f'<div class="digest-section">'
                        f'<div style="font-size:1rem;font-weight:700;color:#e2e8f0;margin-bottom:12px">'
                        f'📋 VOC Digest — Last {data["period_days"]} Days</div>'
                        f'<div style="font-size:.78rem;color:#475569;margin-bottom:10px">'
                        f'{data["total_events"]} total events · avg risk {data["avg_risk_score"]:.2f} · '
                        f'{data["sarcasm_rate"]}% sarcasm · {data["legal_escalations"]} legal escalations'
                        f'</div>',
                        unsafe_allow_html=True
                    )

                    if data["top_clusters"]:
                        st.markdown("**Top Pain Points:**")
                        for i, c in enumerate(data["top_clusters"][:5]):
                            label = c["cluster"].replace("_", " ").title()
                            pct = c["count"] / data["total_events"] * 100
                            color = CLUSTER_COLORS[i % len(CLUSTER_COLORS)]
                            st.markdown(
                                f'<div class="rootcause-row">'
                                f'<div class="rootcause-label">{label}</div>'
                                f'<div class="rootcause-bar-wrap">'
                                f'<div class="rootcause-bar-fill" style="width:{min(pct*2,100):.0f}%;background:{color}"></div>'
                                f'</div>'
                                f'<div class="rootcause-pct">{c["count"]}×</div>'
                                f'</div>',
                                unsafe_allow_html=True
                            )

                    if data["sentiment_breakdown"]:
                        st.markdown("**Sentiment Breakdown:**")
                        sent_colors = {
                            "positive":"#10b981","neutral":"#6366f1",
                            "negative":"#f59e0b","very_negative":"#ef4444"
                        }
                        for sent, count in data["sentiment_breakdown"].items():
                            if sent:
                                label = sent.replace("_", " ").title()
                                color = sent_colors.get(sent, "#94a3b8")
                                st.markdown(
                                    f'<span style="color:{color};font-weight:600">{label}</span>'
                                    f'<span style="color:#475569"> — {count} events</span><br>',
                                    unsafe_allow_html=True
                                )

                    if data["top_escalation_intents"]:
                        st.markdown("**Top Escalation Reasons:**")
                        for esc in data["top_escalation_intents"][:3]:
                            st.markdown(
                                f'<span style="color:#f87171">🚨 {esc["intent"]}</span>'
                                f'<span style="color:#475569"> — {esc["count"]}×</span><br>',
                                unsafe_allow_html=True
                            )

                    st.markdown('</div>', unsafe_allow_html=True)

                except Exception as e:
                    st.error(f"Digest generation failed: {e}")

        st.markdown("---")
        st.markdown("### 🤖 Auto-Learn Signal")
        st.markdown(
            "<div style='color:#94a3b8;font-size:.84rem;margin-bottom:12px'>"
            "Human edits to AI drafts are saved as fine-tuning signals."
            "</div>",
            unsafe_allow_html=True
        )

        import os as _os
        signals_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "training_signals.jsonl")
        if _os.path.exists(signals_path):
            with open(signals_path, "r", encoding="utf-8") as f:
                signals = [json.loads(l) for l in f if l.strip()]

            st.markdown(
                f'<div class="digest-section">'
                f'<div style="color:#e2e8f0;font-weight:600;margin-bottom:8px">'
                f'📝 {len(signals)} training signal(s) collected</div>',
                unsafe_allow_html=True
            )
            if signals:
                intents = {}
                for sig in signals:
                    intents[sig.get("intent","?")] = intents.get(sig.get("intent","?"), 0) + 1
                for intent, count in sorted(intents.items(), key=lambda x: -x[1]):
                    st.markdown(
                        f'<span style="color:#a78bfa">{intent}</span>'
                        f'<span style="color:#475569"> — {count} edit(s)</span><br>',
                        unsafe_allow_html=True
                    )
                with st.expander("📄 View recent signals"):
                    for sig in signals[-3:]:
                        st.caption(
                            f"**{sig.get('platform','?')}** · {sig.get('intent','?')} · "
                            f"edit_ratio={sig.get('edit_ratio',0):.0%} · {sig.get('ts','')[:16]}"
                        )
                        st.markdown(
                            f'<div class="draft-box" style="font-size:.78rem">'
                            f'<b>Original:</b> {sig.get("original_draft","")[:100]}</div>'
                            f'<div class="draft-box-alt" style="font-size:.78rem">'
                            f'<b>Human:</b> {sig.get("human_edit","")[:100]}</div>',
                            unsafe_allow_html=True
                        )
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.info("No training signals yet. They'll appear here after humans edit AI drafts.")
