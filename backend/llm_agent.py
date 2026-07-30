"""
LiteLLM agent with QuickBooks function-calling tools.

The agent receives a natural language question, decides which tool(s) to call,
executes SQL against the local SQLite DB, and returns a structured answer
with optional chart data.

Swapping the LLM backend:
  - Ollama (dev):    LITELLM_MODEL=ollama/llama3.2  LITELLM_API_BASE=http://localhost:11434
  - Private LLM:     LITELLM_MODEL=openai/your-model  LITELLM_API_BASE=https://your-gateway
  - OpenAI fallback: LITELLM_MODEL=gpt-4o  (no API_BASE needed)
"""

import json
import os
from typing import Optional

import litellm
import pandas as pd
from dotenv import load_dotenv

from . import db

load_dotenv()

MODEL = os.getenv("LITELLM_MODEL", "ollama/llama3.2")
API_BASE = os.getenv("LITELLM_API_BASE", "")
API_KEY = os.getenv("LITELLM_API_KEY", "ollama")  # dummy value for local Ollama

litellm.set_verbose = False


# ─── Tool definitions (OpenAI function-calling format) ────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_financials",
            "description": (
                "Execute a SQL SELECT query against the local QuickBooks database. "
                "Tables available: accounts, customers, vendors, invoices, bills, expenses, payments. "
                "Use this to answer any financial question. Always use SELECT only — no writes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "A valid SQLite SELECT statement.",
                    },
                    "chart_type": {
                        "type": "string",
                        "enum": ["none", "bar", "line", "pie"],
                        "description": "Optional chart to render from the query results.",
                    },
                    "x_col": {
                        "type": "string",
                        "description": "Column name to use as the X axis (for bar/line charts).",
                    },
                    "y_col": {
                        "type": "string",
                        "description": "Column name to use as the Y axis (for bar/line charts).",
                    },
                },
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_kpi_summary",
            "description": (
                "Return a pre-built KPI summary: total revenue, total expenses, "
                "net income, open invoices, overdue bills, and top 5 customers by balance."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_revenue_trend",
            "description": "Return monthly revenue trend from invoices for charting.",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {
                        "type": "integer",
                        "description": "Four-digit year, e.g. 2024. Defaults to current year.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_expense_breakdown",
            "description": "Return expense totals grouped by vendor or account for a pie/bar chart.",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_by": {
                        "type": "string",
                        "enum": ["vendor", "account"],
                        "description": "Group expenses by vendor name or account name.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Top N groups to return. Default 10.",
                    },
                },
            },
        },
    },
]


# ─── Tool implementations ─────────────────────────────────────────────────────

def _tool_query_financials(sql: str, chart_type: str = "none",
                           x_col: str = "", y_col: str = "") -> dict:
    try:
        df = db.run_sql(sql)
        return {
            "data": df.to_dict(orient="records"),
            "columns": list(df.columns),
            "row_count": len(df),
            "chart_type": chart_type,
            "x_col": x_col,
            "y_col": y_col,
            "sql": sql,
        }
    except Exception as e:
        return {"error": str(e), "sql": sql}


def _tool_get_kpi_summary() -> dict:
    try:
        revenue = db.run_sql(
            "SELECT COALESCE(SUM(total_amt),0) as v FROM invoices"
        )["v"].iloc[0]
        expenses = db.run_sql(
            "SELECT COALESCE(SUM(total_amt),0) as v FROM expenses"
        )["v"].iloc[0]
        open_invoices = db.run_sql(
            "SELECT COUNT(*) as v FROM invoices WHERE status='open'"
        )["v"].iloc[0]
        overdue_bills = db.run_sql(
            "SELECT COUNT(*) as v FROM bills WHERE balance > 0 AND due_date < date('now')"
        )["v"].iloc[0]
        top_customers = db.run_sql(
            "SELECT display_name, balance FROM customers ORDER BY balance DESC LIMIT 5"
        ).to_dict(orient="records")
        return {
            "total_revenue": float(revenue),
            "total_expenses": float(expenses),
            "net_income": float(revenue) - float(expenses),
            "open_invoices": int(open_invoices),
            "overdue_bills": int(overdue_bills),
            "top_customers_by_balance": top_customers,
        }
    except Exception as e:
        return {"error": str(e)}


def _tool_get_revenue_trend(year: Optional[int] = None) -> dict:
    import datetime
    year = year or datetime.date.today().year
    try:
        df = db.run_sql(f"""
            SELECT
                strftime('%Y-%m', txn_date) as month,
                SUM(total_amt) as revenue
            FROM invoices
            WHERE txn_date LIKE '{year}%'
            GROUP BY month
            ORDER BY month
        """)
        return {
            "data": df.to_dict(orient="records"),
            "chart_type": "line",
            "x_col": "month",
            "y_col": "revenue",
        }
    except Exception as e:
        return {"error": str(e)}


def _tool_get_expense_breakdown(group_by: str = "vendor", limit: int = 10) -> dict:
    col = "vendor_name" if group_by == "vendor" else "account_name"
    try:
        df = db.run_sql(f"""
            SELECT {col} as label, SUM(total_amt) as total
            FROM expenses
            WHERE {col} IS NOT NULL
            GROUP BY label
            ORDER BY total DESC
            LIMIT {limit}
        """)
        return {
            "data": df.to_dict(orient="records"),
            "chart_type": "pie",
            "x_col": "label",
            "y_col": "total",
        }
    except Exception as e:
        return {"error": str(e)}


TOOL_MAP = {
    "query_financials": lambda args: _tool_query_financials(**args),
    "get_kpi_summary": lambda args: _tool_get_kpi_summary(),
    "get_revenue_trend": lambda args: _tool_get_revenue_trend(**args),
    "get_expense_breakdown": lambda args: _tool_get_expense_breakdown(**args),
}


# ─── System prompt ────────────────────────────────────────────────────────────

def _build_system_prompt() -> str:
    counts = db.get_table_summary()
    schema = "\n".join(f"  - {t}: {n} rows" for t, n in counts.items())
    return f"""You are a financial analyst assistant for a QuickBooks Online account.
You have access to real-time financial data synced from QuickBooks into a local SQLite database.

## Database schema
Tables and current row counts:
{schema}

### accounts  (id, name, account_type, account_sub_type, current_balance, currency, active, classification)
### customers (id, display_name, company_name, email, phone, balance, active, currency)
### vendors   (id, display_name, company_name, email, balance, active, currency)
### invoices  (id, doc_number, txn_date, due_date, customer_id, customer_name, total_amt, balance, status, currency)
### bills     (id, doc_number, txn_date, due_date, vendor_id, vendor_name, total_amt, balance, currency)
### expenses  (id, txn_date, payment_type, total_amt, vendor_id, vendor_name, account_id, account_name, memo, currency)
### payments  (id, txn_date, customer_id, customer_name, total_amt, unapplied_amt, currency)

## Your behavior
- Always use the provided tools to answer questions — do not guess at numbers.
- When asked for trends, use get_revenue_trend or query_financials with a chart_type.
- For "show me X as a chart", set chart_type appropriately in query_financials.
- Format currency values with $ and commas in your written response.
- Keep answers concise: 2-4 sentences of insight, then the data.
- If data is missing or the table is empty, say so clearly and suggest running a sync.
"""


# ─── Main agent entry point ───────────────────────────────────────────────────

class AgentResponse:
    def __init__(self, text: str, tool_results: list[dict]):
        self.text = text
        self.tool_results = tool_results  # each has data, chart_type, x_col, y_col


def chat(question: str, history: Optional[list] = None) -> AgentResponse:
    """
    Send a question to the LLM agent. Supports multi-turn via history.
    Returns AgentResponse with text and any chart data.
    """
    messages = [{"role": "system", "content": _build_system_prompt()}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": question})

    tool_results_accumulated = []

    kwargs = dict(
        model=MODEL,
        messages=messages,
        tools=TOOLS,
        tool_choice="auto",
    )
    if API_BASE:
        kwargs["api_base"] = API_BASE
    if API_KEY:
        kwargs["api_key"] = API_KEY

    # Agentic loop: keep going until no more tool calls
    for _ in range(5):
        response = litellm.completion(**kwargs)
        msg = response.choices[0].message

        if not msg.tool_calls:
            return AgentResponse(
                text=msg.content or "",
                tool_results=tool_results_accumulated,
            )

        # Execute each tool call
        messages.append(msg)
        for tc in msg.tool_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments or "{}")
            handler = TOOL_MAP.get(fn_name)
            if handler:
                result = handler(fn_args)
            else:
                result = {"error": f"Unknown tool: {fn_name}"}

            tool_results_accumulated.append(result)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })
        kwargs["messages"] = messages

    return AgentResponse(
        text="Reached tool call limit. Please rephrase your question.",
        tool_results=tool_results_accumulated,
    )
