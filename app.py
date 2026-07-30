"""
QuickBooks AI Dashboard — Streamlit app.

Run:
  streamlit run app.py

Flow:
  1. Connect QuickBooks via OAuth2 (sidebar)
  2. Sync data
  3. Chat with your financials using natural language
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import os

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

from backend import db, qb_client, sync
from backend.llm_agent import chat

load_dotenv()

st.set_page_config(
    page_title="QB AI Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Copy Streamlit Cloud secrets into os.environ — must be after set_page_config.
# Silent locally (no secrets.toml needed for local dev — .env handles it).
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
        background: #f8f9fa;
        border-radius: 10px;
        padding: 16px;
        border-left: 4px solid #0066cc;
    }
    .status-badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 600;
    }
    .badge-green { background: #d4edda; color: #155724; }
    .badge-red   { background: #f8d7da; color: #721c24; }
</style>
""", unsafe_allow_html=True)


# ─── Session state init ───────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "sync_done" not in st.session_state:
    st.session_state.sync_done = False

# ─── Auto-handle OAuth2 callback ─────────────────────────────────────────────
# When Intuit redirects back, the URL contains ?code=...&realmId=...
# Streamlit exposes these via st.query_params — exchange them automatically.
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
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/4/40/QuickBooks_logo.svg/200px-QuickBooks_logo.svg.png", width=140)
    st.title("QB AI Dashboard")
    st.caption("Powered by LiteLLM + Ollama")
    st.divider()

    # OAuth2 flow
    st.subheader("1. Connect QuickBooks")

    # Temporary debug — remove once working
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
        if st.button("Connect QuickBooks Online", type="primary", use_container_width=True):
            auth_url = qb_client.get_auth_url()
            st.markdown(f"[Click here to authorize QuickBooks]({auth_url})")
            st.info("After authorizing, you'll be redirected. Copy the `code` and `realmId` from the URL.")

        # Manual code exchange (for Streamlit's redirect limitation)
        with st.expander("Paste OAuth callback parameters"):
            code = st.text_input("Authorization code")
            realm_id = st.text_input("Realm ID (company ID)")
            if st.button("Exchange & Connect") and code and realm_id:
                with st.spinner("Connecting..."):
                    qb_client.exchange_code(code, realm_id)
                st.success("Connected!")
                st.rerun()

    st.divider()

    # Data sync
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

            results = sync.sync_all(progress_cb=progress)
            st.session_state.sync_done = True
            st.success("Sync complete!")
            st.rerun()
    else:
        st.button("Sync Now", disabled=True, use_container_width=True, help="Connect QuickBooks first")

    st.divider()
    st.caption("Data is stored locally in SQLite. Nothing leaves your machine except QB API calls.")


# ─── Main content ─────────────────────────────────────────────────────────────
st.title("📊 QuickBooks AI Dashboard")

# KPI row
if qb_client.is_authenticated():
    try:
        from backend.llm_agent import _tool_get_kpi_summary
        kpis = _tool_get_kpi_summary()
        if "error" not in kpis:
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Total Revenue", f"${kpis['total_revenue']:,.2f}")
            k2.metric("Total Expenses", f"${kpis['total_expenses']:,.2f}")
            k3.metric("Net Income", f"${kpis['net_income']:,.2f}",
                      delta="profit" if kpis['net_income'] >= 0 else "loss")
            k4.metric("Open Invoices", kpis['open_invoices'])
            k5.metric("Overdue Bills", kpis['overdue_bills'],
                      delta_color="inverse" if kpis['overdue_bills'] > 0 else "normal")
    except Exception:
        pass

st.divider()

# Quick chart row
col1, col2 = st.columns(2)
with col1:
    st.subheader("Revenue Trend")
    try:
        from backend.llm_agent import _tool_get_revenue_trend
        trend = _tool_get_revenue_trend()
        if "data" in trend and trend["data"]:
            df_trend = pd.DataFrame(trend["data"])
            fig = px.line(df_trend, x="month", y="revenue", markers=True,
                          color_discrete_sequence=["#0066cc"])
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=280)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No invoice data yet. Sync QuickBooks to see revenue trends.")
    except Exception as e:
        st.info("Sync data to see revenue trends.")

with col2:
    st.subheader("Expense Breakdown")
    try:
        from backend.llm_agent import _tool_get_expense_breakdown
        breakdown = _tool_get_expense_breakdown(group_by="vendor", limit=8)
        if "data" in breakdown and breakdown["data"]:
            df_exp = pd.DataFrame(breakdown["data"])
            fig = px.pie(df_exp, names="label", values="total",
                         color_discrete_sequence=px.colors.qualitative.Set2)
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=280)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No expense data yet. Sync QuickBooks to see breakdown.")
    except Exception:
        st.info("Sync data to see expense breakdown.")

st.divider()

# ─── Chat interface ───────────────────────────────────────────────────────────
st.subheader("💬 Ask a Question")

EXAMPLE_PROMPTS = [
    "What are my top 5 customers by revenue?",
    "Show me monthly revenue for 2024 as a bar chart",
    "Which vendors am I spending the most with?",
    "How many open invoices do I have and what's the total value?",
    "What's my net income this year?",
    "Show me overdue bills",
]

cols = st.columns(3)
for i, prompt in enumerate(EXAMPLE_PROMPTS):
    if cols[i % 3].button(prompt, use_container_width=True, key=f"eg_{i}"):
        st.session_state.pending_prompt = prompt

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if "charts" in msg:
            for chart in msg["charts"]:
                _render_chart(chart)  # noqa: F821 — defined below


def _render_chart(result: dict):
    """Render a chart from a tool result dict if chart data is present."""
    if result.get("error") or not result.get("data"):
        return
    chart_type = result.get("chart_type", "none")
    x_col = result.get("x_col", "")
    y_col = result.get("y_col", "")
    df = pd.DataFrame(result["data"])
    if df.empty or chart_type == "none":
        if not df.empty:
            st.dataframe(df, use_container_width=True)
        return
    try:
        if chart_type == "bar" and x_col and y_col:
            fig = px.bar(df, x=x_col, y=y_col, color_discrete_sequence=["#0066cc"])
        elif chart_type == "line" and x_col and y_col:
            fig = px.line(df, x=x_col, y=y_col, markers=True,
                          color_discrete_sequence=["#0066cc"])
        elif chart_type == "pie" and x_col and y_col:
            fig = px.pie(df, names=x_col, values=y_col,
                         color_discrete_sequence=px.colors.qualitative.Set2)
        else:
            st.dataframe(df, use_container_width=True)
            return
        fig.update_layout(margin=dict(l=0, r=0, t=20, b=0), height=320)
        st.plotly_chart(fig, use_container_width=True)
    except Exception:
        st.dataframe(df, use_container_width=True)


# Handle example prompt click
pending = st.session_state.pop("pending_prompt", None)

user_input = st.chat_input(
    "Ask anything about your financials…",
    disabled=not qb_client.is_authenticated(),
)
prompt = pending or user_input

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            # Build history (exclude chart metadata for LLM)
            history = [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state.messages[:-1]
            ]
            try:
                agent_resp = chat(prompt, history=history)
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
                err_msg = f"Error: {e}\n\nMake sure Ollama is running (`ollama serve`) and the model is pulled (`ollama pull llama3.2`)."
                st.error(err_msg)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": err_msg,
                })

if not qb_client.is_authenticated():
    st.info("Connect your QuickBooks account in the sidebar to get started.")
