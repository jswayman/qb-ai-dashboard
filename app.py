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
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from backend import db, qb_client, sync

# Data query functions live in queries.py — no litellm dependency.
# The dashboard renders even if the AI backend is unavailable.
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

# chat() depends on litellm — import lazily so a broken AI env doesn't crash the app.
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

# Copy Streamlit Cloud secrets into os.environ — must be after set_page_config.
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ[_k] = _v
except Exception:
    pass

db.init_schema()

# ─── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stChatMessage { border-radius: 12px; }
    .metric-card {
        background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
        border-radius: 12px;
        padding: 20px 16px;
        border-left: 4px solid #0066cc;
        margin-bottom: 8px;
    }
    .metric-card-danger { border-left-color: #dc3545; }
    .metric-card-success { border-left-color: #28a745; }
    .metric-card-warning { border-left-color: #ffc107; }
    .status-badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 600;
    }
    .badge-green { background: #d4edda; color: #155724; }
    .badge-red   { background: #f8d7da; color: #721c24; }
    .section-header {
        font-size: 1.1rem;
        font-weight: 600;
        color: #2c3e50;
        margin-bottom: 4px;
    }
    div[data-testid="stTabs"] button { font-weight: 500; }
    .stDataFrame { border-radius: 8px; }
</style>
""", unsafe_allow_html=True)


# ─── Session state init ───────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "sync_done" not in st.session_state:
    st.session_state.sync_done = False
if "dashboard_year" not in st.session_state:
    st.session_state.dashboard_year = datetime.date.today().year

# ─── Auto-handle OAuth2 callback ─────────────────────────────────────────────
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


# ─── Sidebar: Auth + Sync ─────────────────────────────────────────────────────
with st.sidebar:
    st.image(
        "https://upload.wikimedia.org/wikipedia/commons/thumb/4/40/QuickBooks_logo.svg/200px-QuickBooks_logo.svg.png",
        width=140,
    )
    st.title("QB AI Dashboard")
    st.caption("Powered by LiteLLM + Ollama")
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
        st.markdown('<span class="status-badge badge-green">✓ Connected</span>', unsafe_allow_html=True)
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
        st.dataframe(sync_status[["entity", "last_sync", "row_count"]], hide_index=True, use_container_width=True)

    if qb_client.is_authenticated():
        if st.button("Sync Now", type="primary", use_container_width=True):
            log_container = st.empty()
            log_lines = []

            def progress(msg):
                log_lines.append(msg)
                log_container.code("\n".join(log_lines))

            sync.sync_all(progress_cb=progress)
            st.session_state.sync_done = True
            st.success("Sync complete!")
            st.rerun()
    else:
        st.button("Sync Now", disabled=True, use_container_width=True, help="Connect QuickBooks first")

    st.divider()

    # Year selector — affects all trend charts
    st.subheader("3. Dashboard Settings")
    current_year = datetime.date.today().year
    st.session_state.dashboard_year = st.selectbox(
        "Trend year",
        options=list(range(current_year, current_year - 6, -1)),
        index=0,
    )

    st.divider()
    st.caption("Data stored locally in SQLite. Nothing leaves your machine except QB API calls.")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _safe(fn, *args, **kwargs):
    """Call a data function and return its result, or None on any error."""
    try:
        result = fn(*args, **kwargs)
        return None if "error" in result else result
    except Exception:
        return None


def _fmt_currency(val: float) -> str:
    if abs(val) >= 1_000_000:
        return f"${val/1_000_000:.1f}M"
    if abs(val) >= 1_000:
        return f"${val/1_000:.1f}K"
    return f"${val:,.0f}"


CHART_COLORS = px.colors.qualitative.Set2
PRIMARY_COLOR = "#0066cc"
DANGER_COLOR = "#dc3545"
SUCCESS_COLOR = "#28a745"

CHART_LAYOUT = dict(margin=dict(l=0, r=0, t=24, b=0), height=300, plot_bgcolor="rgba(0,0,0,0)")


def _render_chart(result: dict, key: str = ""):
    """Render a chart from a tool result dict if chart data is present."""
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
    # Use a hash of the data as a stable unique key when none is provided
    import hashlib
    chart_key = key or f"ai_chart_{hashlib.md5((chart_type + x_col + y_col + str(result.get('sql',''))).encode()).hexdigest()[:8]}"
    try:
        if chart_type == "bar" and x_col and y_col:
            fig = px.bar(df, x=x_col, y=y_col, color_discrete_sequence=[PRIMARY_COLOR])
        elif chart_type == "line" and x_col and y_col:
            fig = px.line(df, x=x_col, y=y_col, markers=True,
                          color_discrete_sequence=[PRIMARY_COLOR])
        elif chart_type == "pie" and x_col and y_col:
            fig = px.pie(df, names=x_col, values=y_col,
                         color_discrete_sequence=CHART_COLORS)
        else:
            st.dataframe(df, use_container_width=True)
            return
        fig.update_layout(**CHART_LAYOUT)
        st.plotly_chart(fig, use_container_width=True, key=chart_key)
    except Exception:
        st.dataframe(df, use_container_width=True)


def _no_data(msg: str = "No data yet — sync QuickBooks to populate."):
    st.caption(f"_{msg}_")


# ─── Main content ─────────────────────────────────────────────────────────────
st.title("📊 QuickBooks AI Dashboard")

if not qb_client.is_authenticated():
    st.info("Connect your QuickBooks account in the sidebar to get started.")

# ─── KPI Row (always rendered when connected) ─────────────────────────────────
kpis = _safe(_tool_get_kpi_summary)
cash_data = _safe(_tool_get_cash_balance)

year = st.session_state.dashboard_year

if kpis:
    total_cash = cash_data.get("total_cash", 0.0) if cash_data else 0.0
    ar_balance = sum(
        r.get("balance", 0) for r in (_safe(_tool_get_recent_open_invoices, limit=500) or {}).get("data", [])
    )

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Total Revenue", _fmt_currency(kpis["total_revenue"]))
    k2.metric("Total Expenses", _fmt_currency(kpis["total_expenses"]))

    net = kpis["net_income"]
    k3.metric(
        "Net Income",
        _fmt_currency(net),
        delta="profit" if net >= 0 else "loss",
        delta_color="normal" if net >= 0 else "inverse",
    )
    k4.metric("Cash & Bank", _fmt_currency(total_cash))
    k5.metric(
        "Open Invoices",
        kpis["open_invoices"],
        delta=f"${kpis.get('open_invoice_value', 0):,.0f} AR" if kpis.get("open_invoice_value") else None,
    )
    k6.metric(
        "Overdue Bills",
        kpis["overdue_bills"],
        delta="overdue" if kpis["overdue_bills"] > 0 else None,
        delta_color="inverse" if kpis["overdue_bills"] > 0 else "normal",
    )

st.divider()

# ─── Tabs ─────────────────────────────────────────────────────────────────────
tab_overview, tab_revenue, tab_expenses, tab_customers, tab_ai = st.tabs([
    "📈 Overview",
    "💰 Revenue & Cash",
    "🧾 Expenses & Payables",
    "🤝 Customers & Vendors",
    "🤖 AI Assistant",
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
with tab_overview:
    row1_l, row1_r = st.columns(2)

    with row1_l:
        st.markdown('<p class="section-header">Monthly Revenue vs Expenses</p>', unsafe_allow_html=True)
        cashflow = _safe(_tool_get_monthly_cashflow, year=year)
        if cashflow and cashflow.get("data"):
            df_cf = pd.DataFrame(cashflow["data"])
            fig = go.Figure()
            if "revenue" in df_cf.columns:
                fig.add_trace(go.Bar(name="Revenue", x=df_cf["month"], y=df_cf["revenue"],
                                     marker_color=SUCCESS_COLOR))
            if "expenses" in df_cf.columns:
                fig.add_trace(go.Bar(name="Expenses", x=df_cf["month"], y=df_cf["expenses"],
                                     marker_color=DANGER_COLOR))
            fig.update_layout(**CHART_LAYOUT, barmode="group",
                              legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
            st.plotly_chart(fig, use_container_width=True, key="ov_cashflow")
        else:
            _no_data()

    with row1_r:
        st.markdown('<p class="section-header">Expense Breakdown by Account</p>', unsafe_allow_html=True)
        exp_acct = _safe(_tool_get_expense_breakdown, group_by="account", limit=8)
        if exp_acct and exp_acct.get("data"):
            df_ea = pd.DataFrame(exp_acct["data"])
            fig = px.pie(df_ea, names="label", values="total",
                         color_discrete_sequence=CHART_COLORS, hole=0.35)
            fig.update_layout(**CHART_LAYOUT)
            st.plotly_chart(fig, use_container_width=True, key="ov_exp_acct")
        else:
            _no_data()

    st.divider()
    row2_l, row2_r = st.columns(2)

    with row2_l:
        st.markdown('<p class="section-header">Revenue Trend ({year})</p>'.replace("{year}", str(year)),
                    unsafe_allow_html=True)
        trend = _safe(_tool_get_revenue_trend, year=year)
        if trend and trend.get("data"):
            df_trend = pd.DataFrame(trend["data"])
            fig = px.line(df_trend, x="month", y="revenue", markers=True,
                          color_discrete_sequence=[PRIMARY_COLOR])
            fig.update_layout(**CHART_LAYOUT)
            st.plotly_chart(fig, use_container_width=True, key="ov_rev_trend")
        else:
            _no_data()

    with row2_r:
        st.markdown('<p class="section-header">Invoice Status</p>', unsafe_allow_html=True)
        inv_status = _safe(_tool_get_invoice_status_breakdown)
        if inv_status and inv_status.get("data"):
            df_inv = pd.DataFrame(inv_status["data"])
            fig = px.pie(df_inv, names="status", values="count",
                         color_discrete_sequence=[SUCCESS_COLOR, DANGER_COLOR, "#ffc107"], hole=0.35)
            fig.update_layout(**CHART_LAYOUT)
            st.plotly_chart(fig, use_container_width=True, key="ov_inv_status")
        else:
            _no_data()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — REVENUE & CASH
# ══════════════════════════════════════════════════════════════════════════════
with tab_revenue:
    row1_l, row1_r = st.columns(2)

    with row1_l:
        st.markdown('<p class="section-header">Monthly Revenue ({year})</p>'.replace("{year}", str(year)),
                    unsafe_allow_html=True)
        trend = _safe(_tool_get_revenue_trend, year=year)
        if trend and trend.get("data"):
            df_trend = pd.DataFrame(trend["data"])
            fig = px.area(df_trend, x="month", y="revenue",
                          color_discrete_sequence=[PRIMARY_COLOR])
            fig.update_traces(fill="tozeroy", fillcolor="rgba(0,102,204,0.15)")
            fig.update_layout(**CHART_LAYOUT)
            st.plotly_chart(fig, use_container_width=True, key="rev_monthly")
        else:
            _no_data()

    with row1_r:
        st.markdown('<p class="section-header">Cash & Bank Balances</p>', unsafe_allow_html=True)
        cash_data = _safe(_tool_get_cash_balance)
        if cash_data and cash_data.get("data"):
            df_cash = pd.DataFrame(cash_data["data"])
            fig = px.bar(df_cash, x="account", y="balance",
                         color_discrete_sequence=[PRIMARY_COLOR])
            fig.update_layout(**CHART_LAYOUT)
            fig.update_xaxes(tickangle=-30)
            st.plotly_chart(fig, use_container_width=True, key="rev_cash_bank")
            st.caption(f"Total: **{_fmt_currency(cash_data.get('total_cash', 0))}**")
        else:
            _no_data()

    st.divider()

    st.markdown('<p class="section-header">Open Invoices (by due date)</p>', unsafe_allow_html=True)
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
        st.markdown('<p class="section-header">Top Vendors by Spend</p>', unsafe_allow_html=True)
        top_vendors = _safe(_tool_get_top_vendors, limit=10)
        if top_vendors and top_vendors.get("data"):
            df_tv = pd.DataFrame(top_vendors["data"])
            fig = px.bar(df_tv, x="total_spend", y="vendor", orientation="h",
                         color_discrete_sequence=[DANGER_COLOR])
            fig.update_layout(**CHART_LAYOUT)
            fig.update_yaxes(categoryorder="total ascending")
            st.plotly_chart(fig, use_container_width=True, key="exp_top_vendors")
        else:
            _no_data()

    with row1_r:
        st.markdown('<p class="section-header">Expense by Account</p>', unsafe_allow_html=True)
        exp_acct = _safe(_tool_get_expense_breakdown, group_by="account", limit=10)
        if exp_acct and exp_acct.get("data"):
            df_ea = pd.DataFrame(exp_acct["data"])
            fig = px.pie(df_ea, names="label", values="total",
                         color_discrete_sequence=CHART_COLORS, hole=0.35)
            fig.update_layout(**CHART_LAYOUT)
            st.plotly_chart(fig, use_container_width=True, key="exp_by_acct")
        else:
            _no_data()

    st.divider()
    row2_l, row2_r = st.columns(2)

    with row2_l:
        st.markdown('<p class="section-header">Monthly Bills ({year})</p>'.replace("{year}", str(year)),
                    unsafe_allow_html=True)
        bills_trend = _safe(_tool_get_bills_trend, year=year)
        if bills_trend and bills_trend.get("data"):
            df_bt = pd.DataFrame(bills_trend["data"])
            fig = px.line(df_bt, x="month", y="bills", markers=True,
                          color_discrete_sequence=[DANGER_COLOR])
            fig.update_layout(**CHART_LAYOUT)
            st.plotly_chart(fig, use_container_width=True, key="exp_bills_trend")
        else:
            _no_data()

    with row2_r:
        st.markdown('<p class="section-header">Expense by Vendor (Pie)</p>', unsafe_allow_html=True)
        exp_vendor = _safe(_tool_get_expense_breakdown, group_by="vendor", limit=8)
        if exp_vendor and exp_vendor.get("data"):
            df_ev = pd.DataFrame(exp_vendor["data"])
            fig = px.pie(df_ev, names="label", values="total",
                         color_discrete_sequence=px.colors.qualitative.Pastel, hole=0.35)
            fig.update_layout(**CHART_LAYOUT)
            st.plotly_chart(fig, use_container_width=True, key="exp_by_vendor")
        else:
            _no_data()

    st.divider()

    st.markdown('<p class="section-header">Overdue Bills</p>', unsafe_allow_html=True)
    overdue = _safe(_tool_get_overdue_bills_detail, limit=20)
    if overdue and overdue.get("data"):
        df_ob = pd.DataFrame(overdue["data"])
        df_ob["total_amt"] = df_ob["total_amt"].apply(lambda x: f"${x:,.2f}")
        df_ob["balance"] = df_ob["balance"].apply(lambda x: f"${x:,.2f}")
        df_ob.columns = [c.replace("_", " ").title() for c in df_ob.columns]
        st.dataframe(df_ob, use_container_width=True, hide_index=True)
    else:
        _no_data("No overdue bills. Great!")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — CUSTOMERS & VENDORS
# ══════════════════════════════════════════════════════════════════════════════
with tab_customers:
    row1_l, row1_r = st.columns(2)

    with row1_l:
        st.markdown('<p class="section-header">Top Customers by Revenue</p>', unsafe_allow_html=True)
        top_cust_rev = _safe(_tool_get_top_customers_by_revenue, limit=10)
        if top_cust_rev and top_cust_rev.get("data"):
            df_tcr = pd.DataFrame(top_cust_rev["data"])
            fig = px.bar(df_tcr, x="total_invoiced", y="customer", orientation="h",
                         color_discrete_sequence=[PRIMARY_COLOR])
            fig.update_layout(**CHART_LAYOUT)
            fig.update_yaxes(categoryorder="total ascending")
            st.plotly_chart(fig, use_container_width=True, key="cust_top_by_rev")
        else:
            _no_data()

    with row1_r:
        st.markdown('<p class="section-header">Top Customers by Balance Owed</p>', unsafe_allow_html=True)
        kpis_data = _safe(_tool_get_kpi_summary)
        if kpis_data and kpis_data.get("top_customers_by_balance"):
            df_tcb = pd.DataFrame(kpis_data["top_customers_by_balance"])
            fig = px.bar(df_tcb, x="balance", y="display_name", orientation="h",
                         color_discrete_sequence=["#6f42c1"])
            fig.update_layout(**CHART_LAYOUT)
            fig.update_yaxes(categoryorder="total ascending")
            st.plotly_chart(fig, use_container_width=True, key="cust_top_by_balance")
        else:
            _no_data()

    st.divider()
    row2_l, row2_r = st.columns(2)

    with row2_l:
        st.markdown('<p class="section-header">Top Vendors by Total Spend</p>', unsafe_allow_html=True)
        top_vendors = _safe(_tool_get_top_vendors, limit=10)
        if top_vendors and top_vendors.get("data"):
            df_tv = pd.DataFrame(top_vendors["data"])
            fig = px.bar(df_tv, x="total_spend", y="vendor", orientation="h",
                         color_discrete_sequence=[DANGER_COLOR])
            fig.update_layout(**CHART_LAYOUT)
            fig.update_yaxes(categoryorder="total ascending")
            st.plotly_chart(fig, use_container_width=True, key="cust_vendors_spend")
        else:
            _no_data()

    with row2_r:
        st.markdown('<p class="section-header">Revenue Share by Customer</p>', unsafe_allow_html=True)
        if top_cust_rev and top_cust_rev.get("data"):
            df_share = pd.DataFrame(top_cust_rev["data"])
            fig = px.pie(df_share, names="customer", values="total_invoiced",
                         color_discrete_sequence=CHART_COLORS, hole=0.35)
            fig.update_layout(**CHART_LAYOUT)
            st.plotly_chart(fig, use_container_width=True, key="cust_rev_share")
        else:
            _no_data()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — AI ASSISTANT
# ══════════════════════════════════════════════════════════════════════════════
with tab_ai:
    st.subheader("💬 Ask Anything About Your Financials")
    st.caption("The AI has access to all your synced QuickBooks data and can build custom visualizations.")

    if not _ai_available:
        st.error(
            f"AI assistant is unavailable — the LLM backend failed to load.\n\n"
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
