"""
QuickBooks AI Dashboard — Streamlit app.

Run:
  streamlit run app.py

Flow:
  1. Connect QuickBooks via OAuth2 (sidebar)
  2. Sync data
  3. View pre-rendered KPIs and charts, or ask AI questions
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import datetime
import hashlib
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from backend import db, qb_client, sync
from backend.queries import (
    _tool_get_bills_trend,
    _tool_get_cash_balance,
    _tool_get_expense_breakdown,
    _tool_get_invoice_status_breakdown,
    _tool_get_kpi_summary,
    _tool_get_monthly_cashflow,
    _tool_get_overdue_bills_detail,
    _tool_get_recent_open_invoices,
    _tool_get_revenue_trend,
    _tool_get_top_customers_by_revenue,
    _tool_get_top_vendors,
)

try:
    from backend.llm_agent import chat as _chat
    _ai_available = True
except Exception as _ai_err:
    _chat = None
    _ai_available = False
    _ai_err_msg = str(_ai_err)

load_dotenv()

st.set_page_config(
    page_title="QB AI Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ[_k] = _v
except Exception:
    pass

db.init_schema()


# ─── Design tokens ────────────────────────────────────────────────────────────
BG          = "#070C18"
SURFACE     = "#0F1629"
SURFACE_2   = "#182035"
BORDER      = "#1E2D4F"
BORDER_2    = "#2A3E6B"
TEXT_1      = "#E2E8F8"
TEXT_2      = "#8B9CC8"
TEXT_3      = "#4A5680"
ACCENT      = "#4F8EF7"
GREEN       = "#34D399"
RED         = "#F87171"
AMBER       = "#FBBF24"
VIOLET      = "#A78BFA"

CHART_COLORS = [ACCENT, GREEN, RED, AMBER, VIOLET, "#F472B6", "#22D3EE", "#FB923C"]


# ─── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown(f"""
<style>
/* ── Fonts ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
html, body, [class*="css"], * {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
}}

/* ── App shell ── */
[data-testid="stAppViewContainer"] {{
    background: {BG} !important;
}}
[data-testid="stMain"] .block-container {{
    padding-top: 1.5rem !important;
    padding-bottom: 2rem !important;
    max-width: 100% !important;
}}
[data-testid="stHeader"] {{
    background: {BG} !important;
    border-bottom: 1px solid {BORDER};
}}
[data-testid="stToolbar"] {{
    right: 1rem !important;
}}

/* ── Sidebar ── */
[data-testid="stSidebar"] {{
    background: {SURFACE} !important;
    border-right: 1px solid {BORDER} !important;
}}
[data-testid="stSidebar"] * {{
    color: {TEXT_2} !important;
}}
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {{
    color: {TEXT_1} !important;
}}
[data-testid="stSidebar"] .stButton > button {{
    background: {ACCENT} !important;
    color: #fff !important;
    border: none !important;
    font-weight: 600 !important;
    border-radius: 7px !important;
    transition: opacity .15s ease !important;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
    opacity: .85 !important;
}}

/* ── Page title ── */
h1 {{
    color: {TEXT_1} !important;
    font-weight: 600 !important;
    font-size: 1.45rem !important;
    letter-spacing: -0.025em !important;
    margin-bottom: 0.25rem !important;
}}

/* ── Dividers ── */
hr {{
    border: none !important;
    border-top: 1px solid {BORDER} !important;
    margin: 1.25rem 0 !important;
}}

/* ── Tabs ── */
[data-testid="stTabs"] > div:first-child {{
    border-bottom: 1px solid {BORDER};
    gap: 0;
}}
button[data-testid="stTab"] {{
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    color: {TEXT_3} !important;
    padding: 0.5rem 1.1rem !important;
    border-radius: 0 !important;
    background: transparent !important;
    border: none !important;
    border-bottom: 2px solid transparent !important;
    transition: color .15s ease, border-color .15s ease !important;
    letter-spacing: 0.01em !important;
}}
button[data-testid="stTab"]:hover {{
    color: {TEXT_2} !important;
    background: rgba(79,142,247,.05) !important;
}}
button[data-testid="stTab"][aria-selected="true"] {{
    color: {ACCENT} !important;
    border-bottom-color: {ACCENT} !important;
    background: transparent !important;
    font-weight: 600 !important;
}}

/* ── KPI grid ── */
.kpi-grid {{
    display: grid;
    grid-template-columns: repeat(6, 1fr);
    gap: 10px;
    margin: 0 0 0.25rem;
}}
@media (max-width: 1280px) {{ .kpi-grid {{ grid-template-columns: repeat(3, 1fr); }} }}
@media (max-width:  768px) {{ .kpi-grid {{ grid-template-columns: repeat(2, 1fr); }} }}

.kpi-card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 14px 16px 12px;
    position: relative;
    transition: border-color .2s ease;
}}
.kpi-card:hover {{ border-color: {BORDER_2}; }}
.kpi-card.accent-green {{ border-top: 2px solid {GREEN}; }}
.kpi-card.accent-red   {{ border-top: 2px solid {RED};   }}
.kpi-card.accent-blue  {{ border-top: 2px solid {ACCENT}; }}
.kpi-card.accent-amber {{ border-top: 2px solid {AMBER};  }}

.kpi-label {{
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: {TEXT_3};
    margin-bottom: 7px;
}}
.kpi-value {{
    font-size: 1.55rem;
    font-weight: 600;
    color: {TEXT_1};
    letter-spacing: -0.03em;
    line-height: 1.1;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.kpi-delta {{
    display: inline-flex;
    align-items: center;
    gap: 3px;
    margin-top: 6px;
    font-size: 0.7rem;
    font-weight: 500;
    padding: 2px 7px;
    border-radius: 4px;
    font-variant-numeric: tabular-nums;
}}
.kpi-delta.pos  {{ color: {GREEN}; background: rgba(52,211,153,.1); }}
.kpi-delta.neg  {{ color: {RED};   background: rgba(248,113,113,.1); }}
.kpi-delta.warn {{ color: {AMBER}; background: rgba(251,191,36,.1); }}
.kpi-delta.mute {{ color: {TEXT_3}; background: rgba(74,86,128,.12); }}

/* ── Section headers ── */
.chart-title {{
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: {TEXT_3};
    margin: 0 0 0.5rem;
    padding: 0;
}}

/* ── Empty state ── */
.empty-state {{
    color: {TEXT_3};
    font-size: 0.82rem;
    padding: 2rem 1rem;
    text-align: center;
    border: 1px dashed {BORDER};
    border-radius: 8px;
    margin: 0.25rem 0;
}}

/* ── Status badges ── */
.status-badge {{
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 3px 10px;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.02em;
}}
.badge-green {{
    background: rgba(52,211,153,.12);
    color: {GREEN};
    border: 1px solid rgba(52,211,153,.25);
}}
.badge-red {{
    background: rgba(248,113,113,.12);
    color: {RED};
    border: 1px solid rgba(248,113,113,.25);
}}

/* ── DataFrames ── */
[data-testid="stDataFrame"] {{
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid {BORDER} !important;
}}
[data-testid="stDataFrame"] * {{
    font-variant-numeric: tabular-nums;
}}

/* ── Chat ── */
[data-testid="stChatMessage"] {{
    background: {SURFACE} !important;
    border: 1px solid {BORDER} !important;
    border-radius: 10px !important;
}}

/* ── Expander ── */
[data-testid="stExpander"] {{
    background: {SURFACE} !important;
    border: 1px solid {BORDER} !important;
    border-radius: 8px !important;
}}

/* ── Metrics (fallback, used nowhere now) ── */
[data-testid="stMetric"] {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 14px 16px !important;
}}
[data-testid="stMetricLabel"] {{ color: {TEXT_3} !important; font-size: 0.72rem !important; }}
[data-testid="stMetricValue"] {{ color: {TEXT_1} !important; font-size: 1.55rem !important; }}
[data-testid="stMetricDelta"] {{ font-size: 0.72rem !important; }}

/* ── Caption / small text ── */
.stCaption, small {{ color: {TEXT_3} !important; }}

/* ── Scrollbar ── */
::-webkit-scrollbar {{ width: 6px; height: 6px; }}
::-webkit-scrollbar-track {{ background: {BG}; }}
::-webkit-scrollbar-thumb {{ background: {BORDER_2}; border-radius: 3px; }}
::-webkit-scrollbar-thumb:hover {{ background: {TEXT_3}; }}
</style>
""", unsafe_allow_html=True)


# ─── Session state ────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "sync_done" not in st.session_state:
    st.session_state.sync_done = False
if "dashboard_year" not in st.session_state:
    st.session_state.dashboard_year = datetime.date.today().year


# ─── OAuth2 callback ──────────────────────────────────────────────────────────
_params = st.query_params
if "code" in _params and "realmId" in _params and not qb_client.is_authenticated():
    with st.spinner("Completing QuickBooks connection..."):
        try:
            qb_client.exchange_code(_params["code"], _params["realmId"])
            st.query_params.clear()
            st.success("QuickBooks connected!")
            st.rerun()
        except Exception as e:
            st.error(f"OAuth exchange failed: {e}")


# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image(
        "https://upload.wikimedia.org/wikipedia/commons/thumb/4/40/QuickBooks_logo.svg/200px-QuickBooks_logo.svg.png",
        width=130,
    )
    st.title("QB AI Dashboard")
    st.caption("Financial intelligence, powered by AI")
    st.divider()

    st.subheader("1. Connect QuickBooks")
    _cid = os.environ.get("QB_CLIENT_ID", "")
    _uri = os.environ.get("QB_REDIRECT_URI", "NOT SET")
    if _cid:
        st.caption(f"Client ID: {_cid[:6]}...")
    else:
        st.error("QB_CLIENT_ID not found!")
    st.caption(f"Redirect URI: {_uri}")

    if qb_client.is_authenticated():
        st.markdown('<span class="status-badge badge-green">&#10003; Connected</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="status-badge badge-red">Not connected</span>', unsafe_allow_html=True)
        try:
            auth_url = qb_client.get_auth_url()
            st.link_button("Connect QuickBooks Online", auth_url,
                           type="primary", use_container_width=True)
            with st.expander("Debug: view auth URL"):
                st.code(auth_url)
            st.info("After clicking, Intuit will ask you to sign in and authorize. "
                    "You'll be redirected back here automatically.")
        except Exception as e:
            st.error(f"Could not generate auth URL: {e}")

        with st.expander("Paste OAuth callback parameters"):
            code = st.text_input("Authorization code")
            realm_id = st.text_input("Realm ID (company ID)")
            if st.button("Exchange & Connect") and code and realm_id:
                with st.spinner("Connecting..."):
                    qb_client.exchange_code(code, realm_id)
                st.success("Connected!")
                st.rerun()

    st.divider()
    st.subheader("2. Sync Data")
    sync_status = db.get_sync_status() if qb_client.is_authenticated() else None
    if sync_status is not None and not sync_status.empty:
        st.dataframe(sync_status[["entity", "last_sync", "row_count"]],
                     hide_index=True, use_container_width=True)

    if qb_client.is_authenticated():
        if st.button("Sync Now", type="primary", use_container_width=True):
            log_container = st.empty()
            log_lines: list[str] = []

            def progress(msg: str) -> None:
                log_lines.append(msg)
                log_container.code("\n".join(log_lines))

            sync.sync_all(progress_cb=progress)
            st.session_state.sync_done = True
            st.success("Sync complete!")
            st.rerun()
    else:
        st.button("Sync Now", disabled=True, use_container_width=True,
                  help="Connect QuickBooks first")

    st.divider()
    st.subheader("3. Settings")
    current_year = datetime.date.today().year
    st.session_state.dashboard_year = st.selectbox(
        "Trend year",
        options=list(range(current_year, current_year - 6, -1)),
        index=0,
    )
    st.divider()
    st.caption("Data stored locally in SQLite.")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _safe(fn, *args, **kwargs):
    try:
        result = fn(*args, **kwargs)
        return None if "error" in result else result
    except Exception:
        return None


def _fmt_currency(val: float) -> str:
    if abs(val) >= 1_000_000:
        return f"${val/1_000_000:.2f}M"
    if abs(val) >= 1_000:
        return f"${val/1_000:.1f}K"
    return f"${val:,.0f}"


def _section(title: str) -> None:
    st.markdown(f'<p class="chart-title">{title}</p>', unsafe_allow_html=True)


def _no_data(msg: str = "No data yet — sync QuickBooks to populate.") -> None:
    st.markdown(f'<div class="empty-state">{msg}</div>', unsafe_allow_html=True)


def _theme_fig(fig: go.Figure, height: int = 300) -> go.Figure:
    """Apply the executive dark theme to any Plotly figure."""
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, -apple-system, sans-serif", color=TEXT_2, size=11),
        margin=dict(l=0, r=0, t=28, b=0),
        height=height,
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            bordercolor=BORDER,
            font=dict(color=TEXT_2, size=11),
        ),
        hoverlabel=dict(
            bgcolor=SURFACE_2,
            bordercolor=BORDER_2,
            font=dict(color=TEXT_1, size=12),
        ),
        colorway=CHART_COLORS,
    )
    fig.update_xaxes(
        gridcolor=BORDER,
        linecolor=BORDER,
        tickcolor=TEXT_3,
        tickfont=dict(color=TEXT_2),
        zerolinecolor=BORDER,
    )
    fig.update_yaxes(
        gridcolor=BORDER,
        linecolor=BORDER,
        tickcolor=TEXT_3,
        tickfont=dict(color=TEXT_2),
        zerolinecolor=BORDER,
    )
    return fig


def _kpi_card(label: str, value: str, delta: str = "", delta_cls: str = "mute") -> str:
    accent_map = {
        "pos": "accent-green",
        "neg": "accent-red",
        "warn": "accent-amber",
        "mute": "accent-blue",
    }
    top_cls = accent_map.get(delta_cls, "accent-blue")
    delta_html = (
        f'<div class="kpi-delta {delta_cls}">{delta}</div>' if delta else ""
    )
    return f"""
    <div class="kpi-card {top_cls}">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
        {delta_html}
    </div>"""


def _render_chart(result: dict, key: str = "") -> None:
    if not result or result.get("error") or not result.get("data"):
        return
    chart_type = result.get("chart_type", "none")
    x_col = result.get("x_col", "")
    y_col = result.get("y_col", "")
    df = pd.DataFrame(result["data"])
    if df.empty or chart_type == "none":
        if not df.empty:
            st.dataframe(df, use_container_width=True)
        return
    chart_key = key or f"ai_{hashlib.md5((chart_type+x_col+y_col+str(result.get('sql',''))).encode()).hexdigest()[:8]}"
    try:
        if chart_type == "bar" and x_col and y_col:
            fig = px.bar(df, x=x_col, y=y_col, color_discrete_sequence=[ACCENT])
        elif chart_type == "line" and x_col and y_col:
            fig = px.line(df, x=x_col, y=y_col, markers=True,
                          color_discrete_sequence=[ACCENT])
        elif chart_type == "pie" and x_col and y_col:
            fig = px.pie(df, names=x_col, values=y_col,
                         color_discrete_sequence=CHART_COLORS, hole=0.35)
        else:
            st.dataframe(df, use_container_width=True)
            return
        st.plotly_chart(_theme_fig(fig), use_container_width=True, key=chart_key)
    except Exception:
        st.dataframe(df, use_container_width=True)


# ─── Page header ──────────────────────────────────────────────────────────────
st.markdown("""
<div style="display:flex;align-items:center;gap:10px;margin-bottom:0.5rem;">
  <span style="font-size:1.4rem;font-weight:700;color:#E2E8F8;letter-spacing:-0.025em;">
    QuickBooks AI Dashboard
  </span>
  <span style="font-size:0.72rem;font-weight:500;color:#4A5680;margin-top:3px;">
    Executive Overview
  </span>
</div>
""", unsafe_allow_html=True)

if not qb_client.is_authenticated():
    st.info("Connect your QuickBooks account in the sidebar to get started.")


# ─── KPI Row ──────────────────────────────────────────────────────────────────
kpis      = _safe(_tool_get_kpi_summary)
cash_data = _safe(_tool_get_cash_balance)
year      = st.session_state.dashboard_year

if kpis:
    total_cash = cash_data.get("total_cash", 0.0) if cash_data else 0.0
    net        = kpis["net_income"]
    overdue    = kpis["overdue_bills"]

    cards = "".join([
        _kpi_card("Total Revenue",   _fmt_currency(kpis["total_revenue"]),
                  delta_cls="pos"),
        _kpi_card("Total Expenses",  _fmt_currency(kpis["total_expenses"]),
                  delta_cls="neg"),
        _kpi_card("Net Income",      _fmt_currency(net),
                  delta="Profit" if net >= 0 else "Loss",
                  delta_cls="pos" if net >= 0 else "neg"),
        _kpi_card("Cash & Bank",     _fmt_currency(total_cash),
                  delta_cls="pos" if total_cash >= 0 else "neg"),
        _kpi_card("Open Invoices",   str(kpis["open_invoices"]),
                  delta=f"{kpis['open_invoices']} pending",
                  delta_cls="warn" if kpis["open_invoices"] > 0 else "mute"),
        _kpi_card("Overdue Bills",   str(overdue),
                  delta=f"{overdue} overdue" if overdue > 0 else "All clear",
                  delta_cls="neg" if overdue > 0 else "pos"),
    ])
    st.markdown(f'<div class="kpi-grid">{cards}</div>', unsafe_allow_html=True)

st.divider()


# ─── Tabs ─────────────────────────────────────────────────────────────────────
tab_overview, tab_revenue, tab_expenses, tab_customers, tab_ai = st.tabs([
    "Overview",
    "Revenue & Cash",
    "Expenses & Payables",
    "Customers & Vendors",
    "AI Assistant",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
with tab_overview:
    row1_l, row1_r = st.columns(2)

    with row1_l:
        _section("Revenue vs Expenses — Monthly")
        cashflow = _safe(_tool_get_monthly_cashflow, year=year)
        if cashflow and cashflow.get("data"):
            df_cf = pd.DataFrame(cashflow["data"])
            fig = go.Figure()
            if "revenue" in df_cf.columns:
                fig.add_trace(go.Bar(name="Revenue", x=df_cf["month"], y=df_cf["revenue"],
                                     marker_color=GREEN))
            if "expenses" in df_cf.columns:
                fig.add_trace(go.Bar(name="Expenses", x=df_cf["month"], y=df_cf["expenses"],
                                     marker_color=RED))
            _theme_fig(fig)
            fig.update_layout(
                barmode="group",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig, use_container_width=True, key="ov_cashflow")
        else:
            _no_data()

    with row1_r:
        _section("Expense Breakdown by Account")
        exp_acct = _safe(_tool_get_expense_breakdown, group_by="account", limit=8)
        if exp_acct and exp_acct.get("data"):
            df_ea = pd.DataFrame(exp_acct["data"])
            fig = px.pie(df_ea, names="label", values="total",
                         color_discrete_sequence=CHART_COLORS, hole=0.4)
            fig.update_traces(textfont_color=TEXT_1, textfont_size=11)
            st.plotly_chart(_theme_fig(fig), use_container_width=True, key="ov_exp_acct")
        else:
            _no_data()

    st.divider()
    row2_l, row2_r = st.columns(2)

    with row2_l:
        _section(f"Revenue Trend — {year}")
        trend = _safe(_tool_get_revenue_trend, year=year)
        if trend and trend.get("data"):
            df_trend = pd.DataFrame(trend["data"])
            fig = px.area(df_trend, x="month", y="revenue",
                          color_discrete_sequence=[ACCENT])
            fig.update_traces(fill="tozeroy",
                              fillcolor=f"rgba(79,142,247,0.12)",
                              line_width=2)
            st.plotly_chart(_theme_fig(fig), use_container_width=True, key="ov_rev_trend")
        else:
            _no_data()

    with row2_r:
        _section("Invoice Status")
        inv_status = _safe(_tool_get_invoice_status_breakdown)
        if inv_status and inv_status.get("data"):
            df_inv = pd.DataFrame(inv_status["data"])
            fig = px.pie(df_inv, names="status", values="count",
                         color_discrete_sequence=[GREEN, RED, AMBER], hole=0.4)
            fig.update_traces(textfont_color=TEXT_1, textfont_size=11)
            st.plotly_chart(_theme_fig(fig), use_container_width=True, key="ov_inv_status")
        else:
            _no_data()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — REVENUE & CASH
# ══════════════════════════════════════════════════════════════════════════════
with tab_revenue:
    row1_l, row1_r = st.columns(2)

    with row1_l:
        _section(f"Monthly Revenue — {year}")
        trend = _safe(_tool_get_revenue_trend, year=year)
        if trend and trend.get("data"):
            df_trend = pd.DataFrame(trend["data"])
            fig = px.area(df_trend, x="month", y="revenue",
                          color_discrete_sequence=[GREEN])
            fig.update_traces(fill="tozeroy",
                              fillcolor="rgba(52,211,153,0.10)",
                              line_width=2)
            st.plotly_chart(_theme_fig(fig), use_container_width=True, key="rev_monthly")
        else:
            _no_data()

    with row1_r:
        _section("Cash & Bank Balances")
        cash_data = _safe(_tool_get_cash_balance)
        if cash_data and cash_data.get("data"):
            df_cash = pd.DataFrame(cash_data["data"])
            fig = px.bar(df_cash, x="account", y="balance",
                         color_discrete_sequence=[ACCENT])
            fig.update_layout(xaxis_tickangle=-30)
            st.plotly_chart(_theme_fig(fig), use_container_width=True, key="rev_cash_bank")
            st.caption(f"Total: **{_fmt_currency(cash_data.get('total_cash', 0))}**")
        else:
            _no_data()

    st.divider()
    _section("Open Invoices — by Due Date")
    open_inv = _safe(_tool_get_recent_open_invoices, limit=20)
    if open_inv and open_inv.get("data"):
        df_oi = pd.DataFrame(open_inv["data"])
        df_oi["total_amt"] = df_oi["total_amt"].apply(lambda x: f"${x:,.2f}")
        df_oi["balance"] = df_oi["balance"].apply(lambda x: f"${x:,.2f}")
        df_oi.columns = [c.replace("_", " ").title() for c in df_oi.columns]
        st.dataframe(df_oi, use_container_width=True, hide_index=True)
    else:
        _no_data("No open invoices found.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — EXPENSES & PAYABLES
# ══════════════════════════════════════════════════════════════════════════════
with tab_expenses:
    row1_l, row1_r = st.columns(2)

    with row1_l:
        _section("Top Vendors by Spend")
        top_vendors = _safe(_tool_get_top_vendors, limit=10)
        if top_vendors and top_vendors.get("data"):
            df_tv = pd.DataFrame(top_vendors["data"])
            fig = px.bar(df_tv, x="total_spend", y="vendor", orientation="h",
                         color_discrete_sequence=[RED])
            fig.update_yaxes(categoryorder="total ascending")
            st.plotly_chart(_theme_fig(fig), use_container_width=True, key="exp_top_vendors")
        else:
            _no_data()

    with row1_r:
        _section("Expense by Account")
        exp_acct = _safe(_tool_get_expense_breakdown, group_by="account", limit=10)
        if exp_acct and exp_acct.get("data"):
            df_ea = pd.DataFrame(exp_acct["data"])
            fig = px.pie(df_ea, names="label", values="total",
                         color_discrete_sequence=CHART_COLORS, hole=0.4)
            fig.update_traces(textfont_color=TEXT_1, textfont_size=11)
            st.plotly_chart(_theme_fig(fig), use_container_width=True, key="exp_by_acct")
        else:
            _no_data()

    st.divider()
    row2_l, row2_r = st.columns(2)

    with row2_l:
        _section(f"Monthly Bills — {year}")
        bills_trend = _safe(_tool_get_bills_trend, year=year)
        if bills_trend and bills_trend.get("data"):
            df_bt = pd.DataFrame(bills_trend["data"])
            fig = px.line(df_bt, x="month", y="bills", markers=True,
                          color_discrete_sequence=[RED])
            fig.update_traces(line_width=2, marker_size=6)
            st.plotly_chart(_theme_fig(fig), use_container_width=True, key="exp_bills_trend")
        else:
            _no_data()

    with row2_r:
        _section("Expense by Vendor")
        exp_vendor = _safe(_tool_get_expense_breakdown, group_by="vendor", limit=8)
        if exp_vendor and exp_vendor.get("data"):
            df_ev = pd.DataFrame(exp_vendor["data"])
            fig = px.pie(df_ev, names="label", values="total",
                         color_discrete_sequence=CHART_COLORS, hole=0.4)
            fig.update_traces(textfont_color=TEXT_1, textfont_size=11)
            st.plotly_chart(_theme_fig(fig), use_container_width=True, key="exp_by_vendor")
        else:
            _no_data()

    st.divider()
    _section("Overdue Bills")
    overdue = _safe(_tool_get_overdue_bills_detail, limit=20)
    if overdue and overdue.get("data"):
        df_ob = pd.DataFrame(overdue["data"])
        df_ob["total_amt"] = df_ob["total_amt"].apply(lambda x: f"${x:,.2f}")
        df_ob["balance"] = df_ob["balance"].apply(lambda x: f"${x:,.2f}")
        df_ob.columns = [c.replace("_", " ").title() for c in df_ob.columns]
        st.dataframe(df_ob, use_container_width=True, hide_index=True)
    else:
        _no_data("No overdue bills.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — CUSTOMERS & VENDORS
# ══════════════════════════════════════════════════════════════════════════════
with tab_customers:
    row1_l, row1_r = st.columns(2)

    with row1_l:
        _section("Top Customers by Revenue")
        top_cust_rev = _safe(_tool_get_top_customers_by_revenue, limit=10)
        if top_cust_rev and top_cust_rev.get("data"):
            df_tcr = pd.DataFrame(top_cust_rev["data"])
            fig = px.bar(df_tcr, x="total_invoiced", y="customer", orientation="h",
                         color_discrete_sequence=[ACCENT])
            fig.update_yaxes(categoryorder="total ascending")
            st.plotly_chart(_theme_fig(fig), use_container_width=True, key="cust_top_by_rev")
        else:
            _no_data()

    with row1_r:
        _section("Top Customers by Balance Owed")
        kpis_data = _safe(_tool_get_kpi_summary)
        if kpis_data and kpis_data.get("top_customers_by_balance"):
            df_tcb = pd.DataFrame(kpis_data["top_customers_by_balance"])
            fig = px.bar(df_tcb, x="balance", y="display_name", orientation="h",
                         color_discrete_sequence=[VIOLET])
            fig.update_yaxes(categoryorder="total ascending")
            st.plotly_chart(_theme_fig(fig), use_container_width=True, key="cust_top_by_balance")
        else:
            _no_data()

    st.divider()
    row2_l, row2_r = st.columns(2)

    with row2_l:
        _section("Top Vendors by Spend")
        top_vendors = _safe(_tool_get_top_vendors, limit=10)
        if top_vendors and top_vendors.get("data"):
            df_tv = pd.DataFrame(top_vendors["data"])
            fig = px.bar(df_tv, x="total_spend", y="vendor", orientation="h",
                         color_discrete_sequence=[RED])
            fig.update_yaxes(categoryorder="total ascending")
            st.plotly_chart(_theme_fig(fig), use_container_width=True, key="cust_vendors_spend")
        else:
            _no_data()

    with row2_r:
        _section("Revenue Share by Customer")
        if top_cust_rev and top_cust_rev.get("data"):
            df_share = pd.DataFrame(top_cust_rev["data"])
            fig = px.pie(df_share, names="customer", values="total_invoiced",
                         color_discrete_sequence=CHART_COLORS, hole=0.4)
            fig.update_traces(textfont_color=TEXT_1, textfont_size=11)
            st.plotly_chart(_theme_fig(fig), use_container_width=True, key="cust_rev_share")
        else:
            _no_data()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — AI ASSISTANT
# ══════════════════════════════════════════════════════════════════════════════
with tab_ai:
    st.subheader("Ask Anything About Your Financials")
    st.caption("The AI has access to all your synced QuickBooks data and can build custom visualizations on demand.")

    if not _ai_available:
        st.error(
            f"AI assistant unavailable — the LLM backend failed to load.\n\n"
            f"Make sure `litellm` is installed and Ollama is running (`ollama serve`).\n\n"
            f"Error: `{_ai_err_msg}`"
        )

    EXAMPLE_PROMPTS = [
        "What are my top 5 customers by revenue?",
        "Show me monthly revenue for this year as a bar chart",
        "Which vendors am I spending the most with?",
        "How many open invoices do I have and what's the total value?",
        "What's my net income this year?",
        "Show me overdue bills",
        "Compare revenue vs expenses by month as a chart",
        "Which accounts have the highest balances?",
        "What's my accounts receivable total?",
        "Show me expense trend over the last 6 months",
        "Who are my newest customers?",
        "What is my biggest expense category?",
    ]

    with st.expander("Example questions", expanded=True):
        cols = st.columns(3)
        for i, prompt in enumerate(EXAMPLE_PROMPTS):
            if cols[i % 3].button(prompt, use_container_width=True, key=f"eg_{i}"):
                st.session_state.pending_prompt = prompt

    st.divider()

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if "charts" in msg:
                for chart in msg["charts"]:
                    _render_chart(chart)

    pending = st.session_state.pop("pending_prompt", None)

    user_input = st.chat_input(
        "Ask anything about your financials…",
        disabled=not qb_client.is_authenticated() or not _ai_available,
    )
    prompt = pending or user_input

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                history = [
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.messages[:-1]
                ]
                try:
                    agent_resp = _chat(prompt, history=history)
                    st.write(agent_resp.text)
                    charts_rendered = []
                    for tr in agent_resp.tool_results:
                        _render_chart(tr)
                        charts_rendered.append(tr)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": agent_resp.text,
                        "charts": charts_rendered,
                    })
                except Exception as e:
                    err_msg = (
                        f"Error: {e}\n\n"
                        "Make sure Ollama is running (`ollama serve`) and the model is pulled "
                        "(`ollama pull llama3.2`)."
                    )
                    st.error(err_msg)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": err_msg,
                    })

    if st.session_state.messages:
        if st.button("Clear chat history", use_container_width=False):
            st.session_state.messages = []
            st.rerun()

    if not qb_client.is_authenticated():
        st.info("Connect your QuickBooks account in the sidebar to enable the AI assistant.")
