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
    _tool_get_expenses_for_period,
    _tool_get_invoice_aging,
    _tool_get_invoice_status_breakdown,
    _tool_get_invoices_for_period,
    _tool_get_kpi_summary,
    _tool_get_kpi_summary_ranged,
    _tool_get_monthly_cashflow,
    _tool_get_overdue_bills_detail,
    _tool_get_recent_open_invoices,
    _tool_get_revenue_trend,
    _tool_get_top_customers_by_revenue,
    _tool_get_top_customers_for_period,
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
@import url('https://fonts.googleapis.com/icon?family=Material+Icons');
html, body, [class*="css"] {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
}}
/* Exclude icon elements from the font override */
.material-icons, [data-testid="stSidebarNavCollapseButton"] *, button[kind="header"] * {{
    font-family: 'Material Icons' !important;
}}

/* ── App shell ── */
[data-testid="stAppViewContainer"] {{
    background: {BG} !important;
}}
[data-testid="stMain"] .block-container {{
    padding-top: 3.5rem !important;
    padding-bottom: 2rem !important;
    max-width: 100% !important;
}}
/* Keep header rendered so sidebar toggle button stays accessible */
[data-testid="stHeader"] {{
    background: {BG} !important;
    border-bottom: none !important;
}}
[data-testid="stDecoration"] {{
    display: none !important;
}}
[data-testid="stToolbar"] {{
    right: 1rem !important;
}}

/* ── Sidebar ── */
[data-testid="stSidebar"] {{
    background: #1A1F2E !important;
    border-right: 1px solid {BORDER} !important;
}}
[data-testid="stSidebar"] * {{
    color: #C8D0E8 !important;
}}
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {{
    color: #E8ECF8 !important;
}}
[data-testid="stSidebar"] label, [data-testid="stSidebar"] p,
[data-testid="stSidebar"] .stCaption, [data-testid="stSidebar"] small {{
    color: #A0AABB !important;
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
    min-height: 112px;
    display: flex;
    flex-direction: column;
}}
.kpi-card:hover {{ border-color: {BORDER_2}; }}
.kpi-card.accent-green {{ border-top: 2px solid {GREEN}; }}
.kpi-card.accent-red   {{ border-top: 2px solid {RED};   }}
.kpi-card.accent-blue  {{ border-top: 2px solid {ACCENT}; }}
.kpi-card.accent-amber {{ border-top: 2px solid {AMBER};  }}

.kpi-header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 7px;
}}
.kpi-label {{
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: {TEXT_3};
}}
.kpi-period {{
    font-size: 0.6rem;
    font-weight: 500;
    color: {TEXT_3};
    background: rgba(74,86,128,.18);
    padding: 1px 5px;
    border-radius: 3px;
    white-space: nowrap;
    margin-left: 4px;
    flex-shrink: 0;
}}
.kpi-value {{
    font-size: 1.45rem;
    font-weight: 600;
    color: {TEXT_1};
    letter-spacing: -0.03em;
    line-height: 1.1;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.kpi-deltas {{
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 7px;
    min-height: 22px;
}}
.kpi-delta {{
    display: inline-flex;
    align-items: center;
    gap: 3px;
    font-size: 0.63rem;
    font-weight: 500;
    padding: 2px 6px;
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

/* ── KPI detail buttons — subtle card-footer override ── */
[data-testid="stMain"] button[data-testid="baseButton-primary"] {{
    background: rgba(79,142,247,.07) !important;
    color: {TEXT_3} !important;
    border: 1px solid {BORDER} !important;
    border-top: none !important;
    border-radius: 0 0 9px 9px !important;
    font-size: 0.6rem !important;
    font-weight: 600 !important;
    padding: 4px 0 !important;
    margin-top: -2px !important;
    letter-spacing: 0.08em !important;
    text-transform: uppercase !important;
    transition: background .15s, color .15s, border-color .15s !important;
    width: 100% !important;
}}
[data-testid="stMain"] button[data-testid="baseButton-primary"]:hover {{
    background: rgba(79,142,247,.14) !important;
    color: {ACCENT} !important;
    border-color: {BORDER_2} !important;
}}

/* ── Dialog / modal ── */
[data-testid="stModal"] > div > div {{
    background: {SURFACE} !important;
    border: 1px solid {BORDER_2} !important;
    border-radius: 12px !important;
}}
/* Title — catch every heading variant Streamlit might use */
[data-testid="stModal"] h1,
[data-testid="stModal"] h2,
[data-testid="stModal"] h3 {{
    color: {TEXT_1} !important;
    font-size: 1rem !important;
    font-weight: 600 !important;
}}
/* Section headers (.chart-title) inside the modal */
[data-testid="stModal"] .chart-title {{
    color: {TEXT_2} !important;
}}
/* General body text inside modal */
[data-testid="stModal"] p,
[data-testid="stModal"] label,
[data-testid="stModal"] .stMarkdown p {{
    color: {TEXT_2} !important;
}}
/* Close button — target by aria-label and by Streamlit's kind attr */
[data-testid="stModal"] button[aria-label="Close"],
[data-testid="stModal"] button[kind="header"],
[data-testid="stModal"] button[data-testid$="headerNoPadding"] {{
    color: {TEXT_2} !important;
    background: rgba(74,86,128,.12) !important;
    border-radius: 6px !important;
    opacity: 1 !important;
}}
[data-testid="stModal"] button[aria-label="Close"]:hover,
[data-testid="stModal"] button[kind="header"]:hover,
[data-testid="stModal"] button[data-testid$="headerNoPadding"]:hover {{
    color: {TEXT_1} !important;
    background: rgba(79,142,247,.15) !important;
}}

/* ── Dialog KPI strip ── */
.dlg-kpi-strip {{
    display: flex;
    gap: 10px;
    margin-bottom: 1rem;
}}
.dlg-kpi {{
    flex: 1;
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 10px 14px;
}}
.dlg-kpi-label {{
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: {TEXT_2};
    margin-bottom: 4px;
}}
.dlg-kpi-value {{
    font-size: 1.25rem;
    font-weight: 600;
    color: {TEXT_1};
    letter-spacing: -0.03em;
    font-variant-numeric: tabular-nums;
}}
.dlg-kpi-value.green {{ color: {GREEN}; }}
.dlg-kpi-value.red   {{ color: {RED};   }}
.dlg-kpi-value.amber {{ color: {AMBER}; }}
.dlg-period-badge {{
    display: inline-block;
    font-size: 0.65rem;
    font-weight: 500;
    color: {TEXT_1};
    background: rgba(79,142,247,.12);
    border: 1px solid rgba(79,142,247,.2);
    padding: 2px 8px;
    border-radius: 4px;
    margin-bottom: 0.75rem;
}}
</style>
""", unsafe_allow_html=True)


# ─── Session state ────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "sync_done" not in st.session_state:
    st.session_state.sync_done = False
if "dashboard_year" not in st.session_state:
    st.session_state.dashboard_year = datetime.date.today().year
if "period_type" not in st.session_state:
    st.session_state.period_type = "YTD"
if "dashboard_quarter" not in st.session_state:
    st.session_state.dashboard_quarter = ((datetime.date.today().month - 1) // 3) + 1
if "dashboard_month" not in st.session_state:
    st.session_state.dashboard_month = datetime.date.today().month


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
    st.subheader("3. Filters")
    current_year = datetime.date.today().year
    today = datetime.date.today()

    period_type = st.radio(
        "Period",
        ["YTD", "Month", "Quarter", "Year"],
        index=["YTD", "Month", "Quarter", "Year"].index(st.session_state.period_type),
        horizontal=True,
    )
    st.session_state.period_type = period_type

    sel_year = st.selectbox(
        "Year",
        options=list(range(current_year, current_year - 7, -1)),
        index=0,
        key="sel_year",
    )
    st.session_state.dashboard_year = sel_year

    if period_type == "Quarter":
        current_q = ((today.month - 1) // 3) + 1
        q_opts = ["Q1", "Q2", "Q3", "Q4"]
        default_q = min(current_q, 4) - 1 if sel_year == current_year else 0
        sel_q = st.selectbox("Quarter", q_opts, index=default_q, key="sel_quarter")
        st.session_state.dashboard_quarter = int(sel_q[1])

    elif period_type == "Month":
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        default_m = (today.month - 2) % 12  # default to last completed month
        if sel_year < current_year:
            default_m = 11  # December
        sel_m = st.selectbox("Month", month_names, index=default_m, key="sel_month")
        st.session_state.dashboard_month = month_names.index(sel_m) + 1

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


def _get_period_dates(period_type: str, year: int, quarter: int = 1, month: int = 1):
    """Return (start_date, end_date, period_label) strings."""
    import calendar
    today = datetime.date.today()
    if period_type == "Year":
        return f"{year}-01-01", f"{year}-12-31", f"FY {year}"
    elif period_type == "YTD":
        end = today.strftime("%Y-%m-%d") if year == today.year else f"{year}-12-31"
        return f"{year}-01-01", end, f"YTD {year}"
    elif period_type == "Quarter":
        q_sm = {1: 1, 2: 4, 3: 7, 4: 10}[quarter]
        q_em = {1: 3, 2: 6, 3: 9, 4: 12}[quarter]
        ed = calendar.monthrange(year, q_em)[1]
        return f"{year}-{q_sm:02d}-01", f"{year}-{q_em:02d}-{ed:02d}", f"Q{quarter} {year}"
    elif period_type == "Month":
        ed = calendar.monthrange(year, month)[1]
        mn = ["Jan","Feb","Mar","Apr","May","Jun",
              "Jul","Aug","Sep","Oct","Nov","Dec"][month - 1]
        return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{ed:02d}", f"{mn} {year}"
    return f"{year}-01-01", f"{year}-12-31", f"FY {year}"


def _prior_period_dates(period_type: str, year: int, quarter: int = 1, month: int = 1):
    """Return (start, end) for the immediately preceding comparable period."""
    import calendar
    if period_type == "Month":
        py, pm = (year - 1, 12) if month == 1 else (year, month - 1)
        ed = calendar.monthrange(py, pm)[1]
        return f"{py}-{pm:02d}-01", f"{py}-{pm:02d}-{ed:02d}"
    elif period_type == "Quarter":
        pq, py = (4, year - 1) if quarter == 1 else (quarter - 1, year)
        q_sm = {1: 1, 2: 4, 3: 7, 4: 10}[pq]
        q_em = {1: 3, 2: 6, 3: 9, 4: 12}[pq]
        ed = calendar.monthrange(py, q_em)[1]
        return f"{py}-{q_sm:02d}-01", f"{py}-{q_em:02d}-{ed:02d}"
    else:  # Year / YTD — prior period IS prior year
        s, e, _ = _get_period_dates(period_type, year - 1, quarter, month)
        return s, e


def _prior_year_dates(start_date: str, end_date: str):
    """Same date range shifted back 1 year."""
    s = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
    e = datetime.datetime.strptime(end_date,   "%Y-%m-%d").date()
    try:
        ps = s.replace(year=s.year - 1)
    except ValueError:
        ps = s.replace(year=s.year - 1, day=28)
    try:
        pe = e.replace(year=e.year - 1)
    except ValueError:
        pe = e.replace(year=e.year - 1, day=28)
    return ps.strftime("%Y-%m-%d"), pe.strftime("%Y-%m-%d")


def _pct_delta(current: float, prior: float):
    """Return (formatted_string, css_class) for a % change."""
    if prior == 0:
        return None, "mute"
    pct = (current - prior) / abs(prior) * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%", ("pos" if pct >= 0 else "neg")


def _abs_delta(current: float, prior: float):
    """Return (formatted_string, css_class) for an absolute-dollar change.
    Used where % is misleading (e.g. net income swinging through zero)."""
    diff = current - prior
    if diff == 0:
        return None, "mute"
    sign = "+" if diff >= 0 else ""
    cls  = "pos" if diff >= 0 else "neg"
    return f"{sign}{_fmt_currency(diff)}", cls


def _section(title: str) -> None:
    st.markdown(f'<p class="chart-title">{title}</p>', unsafe_allow_html=True)


# ─── KPI Detail Dialogs ────────────────────────────────────────────────────────

@st.experimental_dialog("Revenue Detail", width="large")
def _dlg_revenue(start: str, end: str, label: str) -> None:
    st.markdown(f'<span class="dlg-period-badge">{label} &nbsp;·&nbsp; {start} → {end}</span>',
                unsafe_allow_html=True)
    inv_data  = _safe(_tool_get_invoices_for_period,  start_date=start, end_date=end, limit=100)
    cust_data = _safe(_tool_get_top_customers_for_period, start_date=start, end_date=end, limit=10)
    trend     = _safe(_tool_get_revenue_trend, year=int(start[:4]))

    # KPI strip
    total_rev = 0.0
    inv_count = 0
    avg_inv   = 0.0
    if inv_data and inv_data.get("data"):
        df_inv = pd.DataFrame(inv_data["data"])
        total_rev = float(df_inv["total_amt"].sum())
        inv_count = len(df_inv)
        avg_inv   = total_rev / inv_count if inv_count else 0.0
    st.markdown(
        f'<div class="dlg-kpi-strip">'
        f'<div class="dlg-kpi"><div class="dlg-kpi-label">Total Revenue</div>'
        f'<div class="dlg-kpi-value green">{_fmt_currency(total_rev)}</div></div>'
        f'<div class="dlg-kpi"><div class="dlg-kpi-label">Invoices</div>'
        f'<div class="dlg-kpi-value">{inv_count:,}</div></div>'
        f'<div class="dlg-kpi"><div class="dlg-kpi-label">Avg Invoice</div>'
        f'<div class="dlg-kpi-value">{_fmt_currency(avg_inv)}</div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Charts
    c1, c2 = st.columns(2)
    with c1:
        _section(f"Revenue by Month — {start[:4]}")
        if trend and trend.get("data"):
            df_t = pd.DataFrame(trend["data"])
            fig = px.area(df_t, x="month", y="revenue", color_discrete_sequence=[GREEN])
            fig.update_traces(fill="tozeroy", fillcolor="rgba(52,211,153,0.10)", line_width=2)
            st.plotly_chart(_theme_fig(fig, height=240), use_container_width=True, key="dlg_rev_trend")
        else:
            _no_data()
    with c2:
        _section("Top Customers")
        if cust_data and cust_data.get("data"):
            df_c = pd.DataFrame(cust_data["data"])
            fig = px.bar(df_c, x="total_invoiced", y="customer", orientation="h",
                         color_discrete_sequence=[ACCENT])
            fig.update_yaxes(categoryorder="total ascending")
            st.plotly_chart(_theme_fig(fig, height=240), use_container_width=True, key="dlg_rev_cust")
        else:
            _no_data()

    # Detail table
    st.divider()
    _section("Invoice List")
    if inv_data and inv_data.get("data"):
        df_show = pd.DataFrame(inv_data["data"]).copy()
        df_show["total_amt"] = df_show["total_amt"].apply(lambda x: f"${x:,.2f}")
        df_show["balance"]   = df_show["balance"].apply(lambda x: f"${x:,.2f}")
        df_show.columns = [c.replace("_", " ").title() for c in df_show.columns]
        st.dataframe(df_show, use_container_width=True, hide_index=True)
    else:
        _no_data("No invoices for this period.")


@st.experimental_dialog("Expenses Detail", width="large")
def _dlg_expenses(start: str, end: str, label: str) -> None:
    st.markdown(f'<span class="dlg-period-badge">{label} &nbsp;·&nbsp; {start} → {end}</span>',
                unsafe_allow_html=True)
    exp_data    = _safe(_tool_get_expenses_for_period, start_date=start, end_date=end, limit=100)
    by_acct     = _safe(_tool_get_expense_breakdown, group_by="account", limit=10)
    top_vendors = _safe(_tool_get_top_vendors, limit=10)

    # KPI strip
    total_exp = 0.0
    exp_count = 0
    largest   = 0.0
    if exp_data and exp_data.get("data"):
        df_exp  = pd.DataFrame(exp_data["data"])
        total_exp = float(df_exp["total_amt"].sum())
        exp_count = len(df_exp)
        largest   = float(df_exp["total_amt"].max()) if not df_exp.empty else 0.0
    st.markdown(
        f'<div class="dlg-kpi-strip">'
        f'<div class="dlg-kpi"><div class="dlg-kpi-label">Total Expenses</div>'
        f'<div class="dlg-kpi-value red">{_fmt_currency(total_exp)}</div></div>'
        f'<div class="dlg-kpi"><div class="dlg-kpi-label">Transactions</div>'
        f'<div class="dlg-kpi-value">{exp_count:,}</div></div>'
        f'<div class="dlg-kpi"><div class="dlg-kpi-label">Largest Single</div>'
        f'<div class="dlg-kpi-value">{_fmt_currency(largest)}</div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Charts
    c1, c2 = st.columns(2)
    with c1:
        _section("By Account")
        if by_acct and by_acct.get("data"):
            df_a = pd.DataFrame(by_acct["data"])
            fig = px.pie(df_a, names="label", values="total",
                         color_discrete_sequence=CHART_COLORS, hole=0.4)
            fig.update_traces(textfont_color=TEXT_1, textfont_size=11)
            st.plotly_chart(_theme_fig(fig, height=240), use_container_width=True, key="dlg_exp_acct")
        else:
            _no_data()
    with c2:
        _section("Top Vendors")
        if top_vendors and top_vendors.get("data"):
            df_v = pd.DataFrame(top_vendors["data"])
            fig = px.bar(df_v, x="total_spend", y="vendor", orientation="h",
                         color_discrete_sequence=[RED])
            fig.update_yaxes(categoryorder="total ascending")
            st.plotly_chart(_theme_fig(fig, height=240), use_container_width=True, key="dlg_exp_vendors")
        else:
            _no_data()

    # Detail table
    st.divider()
    _section("Expense List")
    if exp_data and exp_data.get("data"):
        df_show = pd.DataFrame(exp_data["data"]).copy()
        df_show["total_amt"] = df_show["total_amt"].apply(lambda x: f"${x:,.2f}")
        df_show.columns = [c.replace("_", " ").title() for c in df_show.columns]
        st.dataframe(df_show, use_container_width=True, hide_index=True)
    else:
        _no_data("No expenses for this period.")


@st.experimental_dialog("Net Income Detail", width="large")
def _dlg_net_income(start: str, end: str, label: str,
                    revenue: float, expenses: float) -> None:
    st.markdown(f'<span class="dlg-period-badge">{label} &nbsp;·&nbsp; {start} → {end}</span>',
                unsafe_allow_html=True)
    net = revenue - expenses
    net_cls = "green" if net >= 0 else "red"
    margin  = (net / revenue * 100) if revenue else 0.0
    st.markdown(
        f'<div class="dlg-kpi-strip">'
        f'<div class="dlg-kpi"><div class="dlg-kpi-label">Revenue</div>'
        f'<div class="dlg-kpi-value green">{_fmt_currency(revenue)}</div></div>'
        f'<div class="dlg-kpi"><div class="dlg-kpi-label">Expenses</div>'
        f'<div class="dlg-kpi-value red">{_fmt_currency(expenses)}</div></div>'
        f'<div class="dlg-kpi"><div class="dlg-kpi-label">Net Income</div>'
        f'<div class="dlg-kpi-value {net_cls}">{_fmt_currency(net)}</div></div>'
        f'<div class="dlg-kpi"><div class="dlg-kpi-label">Margin</div>'
        f'<div class="dlg-kpi-value {net_cls}">{margin:.1f}%</div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    yr = int(start[:4])
    cashflow = _safe(_tool_get_monthly_cashflow, year=yr)
    _section(f"Revenue vs Expenses — {yr}")
    if cashflow and cashflow.get("data"):
        df_cf = pd.DataFrame(cashflow["data"])
        fig = go.Figure()
        if "revenue" in df_cf.columns:
            fig.add_trace(go.Bar(name="Revenue",  x=df_cf["month"], y=df_cf["revenue"],
                                 marker_color=GREEN))
        if "expenses" in df_cf.columns:
            fig.add_trace(go.Bar(name="Expenses", x=df_cf["month"], y=df_cf["expenses"],
                                 marker_color=RED))
        _theme_fig(fig, height=260)
        fig.update_layout(
            barmode="group",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig, use_container_width=True, key="dlg_ni_cashflow")
    else:
        _no_data()

    # Month-by-month P&L table
    st.divider()
    _section("Monthly P&L")
    if cashflow and cashflow.get("data"):
        df_pl = pd.DataFrame(cashflow["data"]).copy()
        if "revenue" in df_pl.columns and "expenses" in df_pl.columns:
            df_pl["net_income"] = df_pl["revenue"] - df_pl["expenses"]
            df_pl["margin_%"]   = df_pl.apply(
                lambda r: f"{r['net_income']/r['revenue']*100:.1f}%" if r["revenue"] else "—",
                axis=1,
            )
            df_pl["revenue"]    = df_pl["revenue"].apply(lambda x: f"${x:,.0f}")
            df_pl["expenses"]   = df_pl["expenses"].apply(lambda x: f"${x:,.0f}")
            df_pl["net_income"] = df_pl["net_income"].apply(lambda x: f"${x:,.0f}")
            df_pl.columns = [c.replace("_", " ").title() for c in df_pl.columns]
            st.dataframe(df_pl, use_container_width=True, hide_index=True)
    else:
        _no_data()


@st.experimental_dialog("Cash & Bank Detail", width="large")
def _dlg_cash(start: str, end: str, label: str) -> None:
    st.markdown(f'<span class="dlg-period-badge">As of today</span>', unsafe_allow_html=True)
    cash = _safe(_tool_get_cash_balance)

    total_cash = cash.get("total_cash", 0.0) if cash else 0.0
    acct_count = len(cash.get("data", [])) if cash else 0
    st.markdown(
        f'<div class="dlg-kpi-strip">'
        f'<div class="dlg-kpi"><div class="dlg-kpi-label">Total Cash & Bank</div>'
        f'<div class="dlg-kpi-value {"green" if total_cash >= 0 else "red"}">'
        f'{_fmt_currency(total_cash)}</div></div>'
        f'<div class="dlg-kpi"><div class="dlg-kpi-label">Accounts</div>'
        f'<div class="dlg-kpi-value">{acct_count}</div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    _section("Account Balances")
    if cash and cash.get("data"):
        df_cash = pd.DataFrame(cash["data"])
        fig = px.bar(df_cash, x="account", y="balance",
                     color_discrete_sequence=[ACCENT])
        fig.update_layout(xaxis_tickangle=-30)
        st.plotly_chart(_theme_fig(fig, height=260), use_container_width=True, key="dlg_cash_bar")

        st.divider()
        _section("Account Breakdown")
        df_show = df_cash.copy()
        df_show["balance"] = df_show["balance"].apply(lambda x: f"${x:,.2f}")
        df_show.columns = [c.replace("_", " ").title() for c in df_show.columns]
        st.dataframe(df_show, use_container_width=True, hide_index=True)
    else:
        _no_data("No bank/asset account data found. Ensure accounts are synced.")


@st.experimental_dialog("Open Invoices Detail", width="large")
def _dlg_invoices(start: str, end: str, label: str) -> None:
    st.markdown(f'<span class="dlg-period-badge">{label} &nbsp;·&nbsp; {start} → {end}</span>',
                unsafe_allow_html=True)
    open_inv = _safe(_tool_get_recent_open_invoices, limit=100)
    aging    = _safe(_tool_get_invoice_aging)

    # KPI strip
    total_bal  = 0.0
    inv_count  = 0
    if open_inv and open_inv.get("data"):
        df_oi    = pd.DataFrame(open_inv["data"])
        inv_count  = len(df_oi)
        total_bal  = float(df_oi["balance"].sum())
    st.markdown(
        f'<div class="dlg-kpi-strip">'
        f'<div class="dlg-kpi"><div class="dlg-kpi-label">Open Invoices</div>'
        f'<div class="dlg-kpi-value amber">{inv_count:,}</div></div>'
        f'<div class="dlg-kpi"><div class="dlg-kpi-label">Total Balance Owed</div>'
        f'<div class="dlg-kpi-value">{_fmt_currency(total_bal)}</div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Aging chart
    _section("AR Aging")
    if aging and aging.get("data"):
        df_age = pd.DataFrame(aging["data"])
        order  = ["Current", "1-30 Days", "31-60 Days", "61-90 Days", "90+ Days"]
        df_age["bucket"] = pd.Categorical(df_age["bucket"], categories=order, ordered=True)
        df_age = df_age.sort_values("bucket")
        bucket_colors = [GREEN, AMBER, "#FB923C", RED, "#C53030"]
        fig = px.bar(df_age, x="bucket", y="total_balance",
                     color="bucket",
                     color_discrete_sequence=bucket_colors)
        fig.update_layout(showlegend=False)
        st.plotly_chart(_theme_fig(fig, height=220), use_container_width=True, key="dlg_inv_aging")

        df_age_show = df_age.copy()
        df_age_show["total_balance"] = df_age_show["total_balance"].apply(lambda x: f"${x:,.2f}")
        df_age_show.columns = [c.replace("_", " ").title() for c in df_age_show.columns]
        st.dataframe(df_age_show, use_container_width=True, hide_index=True)
    else:
        _no_data()

    st.divider()
    _section("All Open Invoices")
    if open_inv and open_inv.get("data"):
        df_show = pd.DataFrame(open_inv["data"]).copy()
        df_show["total_amt"] = df_show["total_amt"].apply(lambda x: f"${x:,.2f}")
        df_show["balance"]   = df_show["balance"].apply(lambda x: f"${x:,.2f}")
        df_show.columns = [c.replace("_", " ").title() for c in df_show.columns]
        st.dataframe(df_show, use_container_width=True, hide_index=True)
    else:
        _no_data("No open invoices.")


@st.experimental_dialog("Overdue Bills Detail", width="large")
def _dlg_bills(start: str, end: str, label: str) -> None:
    st.markdown(f'<span class="dlg-period-badge">As of today</span>', unsafe_allow_html=True)
    overdue = _safe(_tool_get_overdue_bills_detail, limit=100)

    total_overdue = 0.0
    bill_count    = 0
    worst_days    = 0
    if overdue and overdue.get("data"):
        df_ob      = pd.DataFrame(overdue["data"])
        bill_count    = len(df_ob)
        total_overdue = float(df_ob["balance"].sum())
        worst_days    = int(df_ob["days_overdue"].max()) if "days_overdue" in df_ob.columns else 0
    st.markdown(
        f'<div class="dlg-kpi-strip">'
        f'<div class="dlg-kpi"><div class="dlg-kpi-label">Overdue Bills</div>'
        f'<div class="dlg-kpi-value red">{bill_count:,}</div></div>'
        f'<div class="dlg-kpi"><div class="dlg-kpi-label">Total Amount Overdue</div>'
        f'<div class="dlg-kpi-value red">{_fmt_currency(total_overdue)}</div></div>'
        f'<div class="dlg-kpi"><div class="dlg-kpi-label">Most Days Overdue</div>'
        f'<div class="dlg-kpi-value amber">{worst_days:,}d</div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Vendor breakdown
    if overdue and overdue.get("data"):
        df_ob = pd.DataFrame(overdue["data"])
        if "vendor_name" in df_ob.columns and not df_ob.empty:
            _section("Overdue by Vendor")
            df_vend = (
                df_ob.groupby("vendor_name", as_index=False)["balance"]
                .sum()
                .sort_values("balance", ascending=True)
            )
            fig = px.bar(df_vend, x="balance", y="vendor_name", orientation="h",
                         color_discrete_sequence=[RED])
            st.plotly_chart(_theme_fig(fig, height=220), use_container_width=True, key="dlg_bill_vend")

    st.divider()
    _section("All Overdue Bills")
    if overdue and overdue.get("data"):
        df_show = pd.DataFrame(overdue["data"]).copy()
        df_show["total_amt"] = df_show["total_amt"].apply(lambda x: f"${x:,.2f}")
        df_show["balance"]   = df_show["balance"].apply(lambda x: f"${x:,.2f}")
        df_show.columns = [c.replace("_", " ").title() for c in df_show.columns]
        st.dataframe(df_show, use_container_width=True, hide_index=True)
    else:
        _no_data("No overdue bills — great news!")




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


def _kpi_card(label: str, value: str, period_label: str = "",
              pop_delta: str = "", pop_cls: str = "mute", pop_tag: str = "",
              yoy_delta: str = "", yoy_cls: str = "mute",
              accent_cls: str = "accent-blue") -> str:
    """Compact single-line HTML KPI card with period label + delta badges."""
    period_html = f'<span class="kpi-period">{period_label}</span>' if period_label else ""
    deltas = ""
    if pop_delta and pop_tag:
        deltas += f'<span class="kpi-delta {pop_cls}">{pop_delta} {pop_tag}</span>'
    if yoy_delta:
        deltas += f'<span class="kpi-delta {yoy_cls}">{yoy_delta} YoY</span>'
    delta_row = f'<div class="kpi-deltas">{deltas}</div>'
    return (f'<div class="kpi-card {accent_cls}">'
            f'<div class="kpi-header"><span class="kpi-label">{label}</span>{period_html}</div>'
            f'<div class="kpi-value">{value}</div>'
            f'{delta_row}'
            f'</div>')


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
period_type = st.session_state.get("period_type", "YTD")
year        = st.session_state.get("dashboard_year", datetime.date.today().year)
quarter     = st.session_state.get("dashboard_quarter", 1)
month       = st.session_state.get("dashboard_month", datetime.date.today().month)

cur_start, cur_end, period_label = _get_period_dates(period_type, year, quarter, month)
pp_start,  pp_end                = _prior_period_dates(period_type, year, quarter, month)
yoy_start, yoy_end               = _prior_year_dates(cur_start, cur_end)

pop_tag = {"Month": "MoM", "Quarter": "QoQ"}.get(period_type, "YoY")

kpis_cur  = _safe(_tool_get_kpi_summary_ranged, start_date=cur_start,  end_date=cur_end)
kpis_pp   = _safe(_tool_get_kpi_summary_ranged, start_date=pp_start,   end_date=pp_end)
kpis_yoy  = _safe(_tool_get_kpi_summary_ranged, start_date=yoy_start,  end_date=yoy_end)
cash_data = _safe(_tool_get_cash_balance)

if kpis_cur:
    total_cash = cash_data.get("total_cash", 0.0) if cash_data else 0.0
    net        = kpis_cur["net_income"]
    overdue    = kpis_cur["overdue_bills"]

    def _kpi_deltas(metric: str, invert: bool = False):
        """Return (pop_delta, pop_cls, yoy_delta, yoy_cls) for a metric."""
        cur = kpis_cur.get(metric, 0.0)
        pd_str, pd_cls = _pct_delta(cur, kpis_pp.get(metric, 0.0)) if kpis_pp else (None, "mute")
        yd_str, yd_cls = _pct_delta(cur, kpis_yoy.get(metric, 0.0)) if kpis_yoy else (None, "mute")
        if invert:
            pd_cls = "neg" if pd_cls == "pos" else ("pos" if pd_cls == "neg" else "mute")
            yd_cls = "neg" if yd_cls == "pos" else ("pos" if yd_cls == "neg" else "mute")
        return (pd_str or "", pd_cls, yd_str or "", yd_cls)

    rev_pd, rev_pc, rev_yd, rev_yc   = _kpi_deltas("total_revenue")
    exp_pd, exp_pc, exp_yd, exp_yc   = _kpi_deltas("total_expenses", invert=True)
    net_pd, net_pc, net_yd, net_yc   = _kpi_deltas("net_income")
    inv_pd, inv_pc, inv_yd, inv_yc   = _kpi_deltas("open_invoices", invert=True)
    bill_pd, bill_pc, bill_yd, bill_yc = _kpi_deltas("overdue_bills", invert=True)

    card_specs = [
        ("Total Revenue",  _fmt_currency(kpis_cur["total_revenue"]), period_label,
         rev_pd,  rev_pc,  pop_tag, rev_yd,  rev_yc,  "accent-green"),
        ("Total Expenses", _fmt_currency(kpis_cur["total_expenses"]), period_label,
         exp_pd,  exp_pc,  pop_tag, exp_yd,  exp_yc,  "accent-red"),
        ("Net Income",     _fmt_currency(net), period_label,
         net_pd,  net_pc,  pop_tag, net_yd,  net_yc,
         "accent-green" if net >= 0 else "accent-red"),
        ("Cash & Bank",    _fmt_currency(total_cash), "Current",
         *(_abs_delta(kpis_cur["net_income"], kpis_pp["net_income"])  if kpis_pp  else ("", "mute")),
         pop_tag,
         *(_abs_delta(kpis_cur["net_income"], kpis_yoy["net_income"]) if kpis_yoy else ("", "mute")),
         "accent-green" if total_cash >= 0 else "accent-red"),
        ("Open Invoices",  str(kpis_cur["open_invoices"]), period_label,
         inv_pd,  inv_pc,  pop_tag, inv_yd,  inv_yc,
         "accent-amber" if kpis_cur["open_invoices"] > 0 else "accent-blue"),
        ("Overdue Bills",  str(overdue), "As of today",
         bill_pd, bill_pc, pop_tag, bill_yd, bill_yc,
         "accent-red" if overdue > 0 else "accent-green"),
    ]

    dialog_configs = [
        ("revenue",  _dlg_revenue,
         (cur_start, cur_end, period_label)),
        ("expenses", _dlg_expenses,
         (cur_start, cur_end, period_label)),
        ("net",      _dlg_net_income,
         (cur_start, cur_end, period_label,
          kpis_cur["total_revenue"], kpis_cur["total_expenses"])),
        ("cash",     _dlg_cash,
         (cur_start, cur_end, period_label)),
        ("invoices", _dlg_invoices,
         (cur_start, cur_end, period_label)),
        ("bills",    _dlg_bills,
         (cur_start, cur_end, period_label)),
    ]

    k_cols = st.columns(6)
    for col, spec, (key, dlg_fn, args) in zip(k_cols, card_specs, dialog_configs):
        (lbl, val, plabel, pdelta, pcls, ptag, ydelta, ycls, acls) = spec
        with col:
            st.markdown(
                _kpi_card(lbl, val, plabel, pdelta, pcls, ptag, ydelta, ycls, acls),
                unsafe_allow_html=True,
            )
            if st.button("Details →", key=f"kpi_det_{key}",
                         use_container_width=True, type="primary"):
                dlg_fn(*args)

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
