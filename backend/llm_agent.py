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

def _model() -> str:
    return os.getenv("LITELLM_MODEL", "ollama/llama3.2")

def _api_base() -> str:
    return os.getenv("LITELLM_API_BASE", "")

def _api_key() -> str:
    return os.getenv("LITELLM_API_KEY", "ollama")  # dummy value for local Ollama

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
    {
        "type": "function",
        "function": {
            "name": "get_monthly_cashflow",
            "description": "Return monthly revenue vs expenses for a given year — useful for grouped bar chart comparisons.",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer", "description": "Four-digit year. Defaults to current year."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_customers_by_revenue",
            "description": "Return top customers ranked by total invoiced amount.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Top N customers. Default 10."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_invoice_status_breakdown",
            "description": "Return count and value of invoices broken down by status (paid vs open).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_vendors",
            "description": "Return top vendors by total spend from expenses.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Top N vendors. Default 10."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_bills_trend",
            "description": "Return monthly bills trend for a given year.",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer", "description": "Four-digit year. Defaults to current year."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cash_balance",
            "description": "Return current balances for bank and asset accounts.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_open_invoices",
            "description": "Return a table of the most recent open/unpaid invoices sorted by due date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Number of invoices to return. Default 10."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_overdue_bills_detail",
            "description": "Return a table of overdue unpaid bills with days overdue.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Number of bills to return. Default 10."},
                },
            },
        },
    },
]


# ─── Tool implementations ─────────────────────────────────────────────────────

def _tool_query_financials(sql: str, chart_type: str = "none",
                           x_col: str = "", y_col: str = "", **kwargs) -> dict:
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


def _tool_get_revenue_trend(year: Optional[int] = None, **kwargs) -> dict:
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


def _tool_get_expense_breakdown(group_by: str = "vendor", limit: int = 10, **kwargs) -> dict:
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


def _tool_get_monthly_cashflow(year: Optional[int] = None, **kwargs) -> dict:
    """Return monthly revenue vs expenses side-by-side for grouped bar chart."""
    import datetime
    year = year or datetime.date.today().year
    try:
        rev = db.run_sql(f"""
            SELECT strftime('%Y-%m', txn_date) as month, SUM(total_amt) as revenue
            FROM invoices WHERE txn_date LIKE '{year}%'
            GROUP BY month ORDER BY month
        """)
        exp = db.run_sql(f"""
            SELECT strftime('%Y-%m', txn_date) as month, SUM(total_amt) as expenses
            FROM expenses WHERE txn_date LIKE '{year}%'
            GROUP BY month ORDER BY month
        """)
        merged = rev.merge(exp, on="month", how="outer").fillna(0).sort_values("month")
        return {
            "data": merged.to_dict(orient="records"),
            "chart_type": "bar",
            "x_col": "month",
        }
    except Exception as e:
        return {"error": str(e)}


def _tool_get_top_customers_by_revenue(limit: int = 10, **kwargs) -> dict:
    """Return top customers ranked by total invoiced amount."""
    try:
        df = db.run_sql(f"""
            SELECT customer_name as customer, SUM(total_amt) as total_invoiced
            FROM invoices
            WHERE customer_name IS NOT NULL
            GROUP BY customer_name
            ORDER BY total_invoiced DESC
            LIMIT {limit}
        """)
        return {
            "data": df.to_dict(orient="records"),
            "chart_type": "bar",
            "x_col": "customer",
            "y_col": "total_invoiced",
        }
    except Exception as e:
        return {"error": str(e)}


def _tool_get_invoice_status_breakdown(**kwargs) -> dict:
    """Return count of invoices by status (paid vs open)."""
    try:
        df = db.run_sql("""
            SELECT status, COUNT(*) as count, SUM(total_amt) as total_value
            FROM invoices
            GROUP BY status
        """)
        return {
            "data": df.to_dict(orient="records"),
            "chart_type": "pie",
            "x_col": "status",
            "y_col": "count",
        }
    except Exception as e:
        return {"error": str(e)}


def _tool_get_top_vendors(limit: int = 10, **kwargs) -> dict:
    """Return top vendors by total spend from expenses."""
    try:
        df = db.run_sql(f"""
            SELECT vendor_name as vendor, SUM(total_amt) as total_spend
            FROM expenses
            WHERE vendor_name IS NOT NULL
            GROUP BY vendor_name
            ORDER BY total_spend DESC
            LIMIT {limit}
        """)
        return {
            "data": df.to_dict(orient="records"),
            "chart_type": "bar",
            "x_col": "vendor",
            "y_col": "total_spend",
        }
    except Exception as e:
        return {"error": str(e)}


def _tool_get_bills_trend(year: Optional[int] = None, **kwargs) -> dict:
    """Return monthly bills trend for a given year."""
    import datetime
    year = year or datetime.date.today().year
    try:
        df = db.run_sql(f"""
            SELECT strftime('%Y-%m', txn_date) as month, SUM(total_amt) as bills
            FROM bills WHERE txn_date LIKE '{year}%'
            GROUP BY month ORDER BY month
        """)
        return {
            "data": df.to_dict(orient="records"),
            "chart_type": "line",
            "x_col": "month",
            "y_col": "bills",
        }
    except Exception as e:
        return {"error": str(e)}


def _tool_get_cash_balance(**kwargs) -> dict:
    """Return current balances for bank and asset accounts."""
    try:
        df = db.run_sql("""
            SELECT name as account, current_balance as balance
            FROM accounts
            WHERE account_type IN ('Bank', 'Other Current Asset', 'Fixed Asset')
              AND active = 1
              AND current_balance != 0
            ORDER BY balance DESC
            LIMIT 15
        """)
        total = float(df["balance"].sum()) if not df.empty else 0.0
        return {
            "data": df.to_dict(orient="records"),
            "total_cash": total,
            "chart_type": "bar",
            "x_col": "account",
            "y_col": "balance",
        }
    except Exception as e:
        return {"error": str(e)}


def _tool_get_recent_open_invoices(limit: int = 10, **kwargs) -> dict:
    """Return most recent open invoices sorted by due date."""
    try:
        df = db.run_sql(f"""
            SELECT doc_number, txn_date, due_date, customer_name, total_amt, balance
            FROM invoices
            WHERE status = 'open'
            ORDER BY due_date ASC
            LIMIT {limit}
        """)
        return {"data": df.to_dict(orient="records")}
    except Exception as e:
        return {"error": str(e)}


def _tool_get_overdue_bills_detail(limit: int = 10, **kwargs) -> dict:
    """Return overdue unpaid bills sorted by days overdue."""
    try:
        df = db.run_sql(f"""
            SELECT doc_number, txn_date, due_date, vendor_name, total_amt, balance,
                   CAST(julianday('now') - julianday(due_date) AS INTEGER) as days_overdue
            FROM bills
            WHERE balance > 0 AND due_date < date('now')
            ORDER BY days_overdue DESC
            LIMIT {limit}
        """)
        return {"data": df.to_dict(orient="records")}
    except Exception as e:
        return {"error": str(e)}


def _tool_get_accounts_receivable_balance(**kwargs) -> dict:
    """Return total AR balance from open invoices."""
    try:
        df = db.run_sql("SELECT COALESCE(SUM(balance), 0) as ar_balance FROM invoices WHERE status = 'open'")
        return {"ar_balance": float(df["ar_balance"].iloc[0])}
    except Exception as e:
        return {"error": str(e)}


TOOL_MAP = {
    "query_financials": lambda args: _tool_query_financials(**args),
    "get_kpi_summary": lambda args: _tool_get_kpi_summary(),
    "get_revenue_trend": lambda args: _tool_get_revenue_trend(**args),
    "get_expense_breakdown": lambda args: _tool_get_expense_breakdown(**args),
    "get_monthly_cashflow": lambda args: _tool_get_monthly_cashflow(**args),
    "get_top_customers_by_revenue": lambda args: _tool_get_top_customers_by_revenue(**args),
    "get_invoice_status_breakdown": lambda args: _tool_get_invoice_status_breakdown(),
    "get_top_vendors": lambda args: _tool_get_top_vendors(**args),
    "get_bills_trend": lambda args: _tool_get_bills_trend(**args),
    "get_cash_balance": lambda args: _tool_get_cash_balance(),
    "get_recent_open_invoices": lambda args: _tool_get_recent_open_invoices(**args),
    "get_overdue_bills_detail": lambda args: _tool_get_overdue_bills_detail(**args),
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

    model = _model()
    api_base = _api_base()
    api_key = _api_key()

    # Ollama models don't reliably support function calling —
    # fall back to a plain prompt with the data injected directly.
    use_tools = not model.startswith("ollama/")

    kwargs = dict(model=model, messages=messages)
    if use_tools:
        kwargs["tools"] = TOOLS
        kwargs["tool_choice"] = "auto"
    if api_base:
        kwargs["api_base"] = api_base
    if api_key:
        kwargs["api_key"] = api_key

    if not use_tools:
        # For Ollama: run all pre-built tools and inject results into the prompt
        kpi = _tool_get_kpi_summary()
        trend = _tool_get_revenue_trend()
        breakdown = _tool_get_expense_breakdown()
        context = f"""
Current QuickBooks data:
- KPIs: {json.dumps(kpi)}
- Revenue trend: {json.dumps(trend.get('data', []))}
- Expense breakdown: {json.dumps(breakdown.get('data', []))}

Answer the user's question using this data. Be concise and specific with numbers.
"""
        messages[-1]["content"] = context + "\n\nUser question: " + question
        response = litellm.completion(**kwargs)
        return AgentResponse(
            text=response.choices[0].message.content or "",
            tool_results=[kpi, trend, breakdown],
        )

    # Agentic loop for models that support tool calling (Groq, OpenAI, etc.)
    for _ in range(5):
        try:
            response = litellm.completion(**kwargs)
        except Exception as e:
            # Model doesn't support tool calling — fall back to data injection
            if "tool" in str(e).lower() or "function" in str(e).lower():
                kpi = _tool_get_kpi_summary()
                trend = _tool_get_revenue_trend()
                breakdown = _tool_get_expense_breakdown()
                context = f"QuickBooks data: KPIs={json.dumps(kpi)}, Revenue trend={json.dumps(trend.get('data',[]))}, Expenses={json.dumps(breakdown.get('data',[]))}\n\nAnswer: {question}"
                fallback_kwargs = {k: v for k, v in kwargs.items() if k not in ("tools", "tool_choice")}
                fallback_kwargs["messages"] = [{"role": "system", "content": _build_system_prompt()}, {"role": "user", "content": context}]
                resp = litellm.completion(**fallback_kwargs)
                return AgentResponse(text=resp.choices[0].message.content or "", tool_results=[kpi, trend, breakdown])
            raise
        msg = response.choices[0].message

        if not msg.tool_calls:
            return AgentResponse(
                text=msg.content or "",
                tool_results=tool_results_accumulated,
            )

        messages.append(msg)
        for tc in msg.tool_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments or "{}") or {}
            handler = TOOL_MAP.get(fn_name)
            result = handler(fn_args) if handler else {"error": f"Unknown tool: {fn_name}"}
            tool_results_accumulated.append(result)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id or f"call_{fn_name}",
                "content": json.dumps(result),
            })
        kwargs["messages"] = messages

    return AgentResponse(
        text="I wasn't able to fully answer that. Try asking a more specific question.",
        tool_results=tool_results_accumulated,
    )
