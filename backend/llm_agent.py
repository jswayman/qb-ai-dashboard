"""
QB AI agent — OpenAI-compatible SDK (replaces LiteLLM for lighter cloud deploys).

Supports any OpenAI-compatible backend via the LITELLM_MODEL / LITELLM_API_BASE /
LITELLM_API_KEY env vars (same names kept for backwards compatibility with existing
Streamlit secrets).

Provider routing (set LITELLM_MODEL to one of):
  groq/llama-3.3-70b-versatile   → Groq API  (recommended for cloud, free tier)
  ollama/llama3.2                 → local Ollama (data-injection mode, no tool calls)
  gpt-4o-mini                     → OpenAI
  openai/your-model               → OpenAI-compatible gateway (set LITELLM_API_BASE)

NOTE: queries.py has no openai/LLM dependency so the dashboard charts load
independently of the AI backend.
"""

import json
import os
from typing import Optional

from dotenv import load_dotenv

from . import db
from .queries import (
    _tool_get_accounts_receivable_balance,
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
    _tool_query_financials,
)

load_dotenv()


# ─── Client factory ───────────────────────────────────────────────────────────

def _get_client_and_model():
    """
    Parse LITELLM_MODEL and return (OpenAI client, resolved model name, raw model).
    Provider prefixes (groq/, ollama/, openai/) are stripped and used to set
    the correct base_url automatically.
    """
    from openai import OpenAI  # lazy import keeps startup instant

    raw_model = os.getenv("LITELLM_MODEL", "ollama/llama3.2")
    api_key   = os.getenv("LITELLM_API_KEY", "ollama")
    api_base  = os.getenv("LITELLM_API_BASE", "")

    if raw_model.startswith("groq/"):
        model    = raw_model[len("groq/"):]
        base_url = api_base or "https://api.groq.com/openai/v1"
        api_key  = api_key or "groq-key-required"
    elif raw_model.startswith("ollama/"):
        model    = raw_model[len("ollama/"):]
        base_url = api_base or "http://localhost:11434/v1"
        api_key  = "ollama"
    elif raw_model.startswith("openai/"):
        model    = raw_model[len("openai/"):]
        base_url = api_base or None
    else:
        model    = raw_model
        base_url = api_base or None

    client = OpenAI(
        api_key=api_key or "sk-no-key",
        base_url=base_url,
    )
    return client, model, raw_model


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
            "description": "Return monthly revenue vs expenses for a given year.",
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


# ─── Tool map (name → callable) ───────────────────────────────────────────────

TOOL_MAP = {
    "query_financials":           lambda args: _tool_query_financials(**args),
    "get_kpi_summary":            lambda args: _tool_get_kpi_summary(),
    "get_revenue_trend":          lambda args: _tool_get_revenue_trend(**args),
    "get_expense_breakdown":      lambda args: _tool_get_expense_breakdown(**args),
    "get_monthly_cashflow":       lambda args: _tool_get_monthly_cashflow(**args),
    "get_top_customers_by_revenue": lambda args: _tool_get_top_customers_by_revenue(**args),
    "get_invoice_status_breakdown": lambda args: _tool_get_invoice_status_breakdown(),
    "get_top_vendors":            lambda args: _tool_get_top_vendors(**args),
    "get_bills_trend":            lambda args: _tool_get_bills_trend(**args),
    "get_cash_balance":           lambda args: _tool_get_cash_balance(),
    "get_recent_open_invoices":   lambda args: _tool_get_recent_open_invoices(**args),
    "get_overdue_bills_detail":   lambda args: _tool_get_overdue_bills_detail(**args),
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
    def __init__(self, text: str, tool_results: list):
        self.text = text
        self.tool_results = tool_results


def chat(question: str, history: Optional[list] = None) -> "AgentResponse":
    """
    Send a question to the LLM agent. Supports multi-turn via history.
    Returns AgentResponse with .text and .tool_results (list of dicts for chart rendering).
    """
    client, model, raw_model = _get_client_and_model()

    messages = [{"role": "system", "content": _build_system_prompt()}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": question})

    tool_results_accumulated = []

    # Ollama models don't reliably support function calling —
    # fall back to a plain prompt with data injected directly.
    use_tools = not raw_model.startswith("ollama/")

    if not use_tools:
        kpi       = _tool_get_kpi_summary()
        trend     = _tool_get_revenue_trend()
        breakdown = _tool_get_expense_breakdown()
        context = (
            f"Current QuickBooks data:\n"
            f"- KPIs: {json.dumps(kpi)}\n"
            f"- Revenue trend: {json.dumps(trend.get('data', []))}\n"
            f"- Expense breakdown: {json.dumps(breakdown.get('data', []))}\n\n"
            f"Answer the user's question using this data. Be concise and specific with numbers.\n\n"
            f"User question: {question}"
        )
        messages[-1]["content"] = context
        response = client.chat.completions.create(model=model, messages=messages)
        return AgentResponse(
            text=response.choices[0].message.content or "",
            tool_results=[kpi, trend, breakdown],
        )

    # Agentic tool-calling loop (Groq, OpenAI, compatible gateways)
    for _ in range(5):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
            )
        except Exception as e:
            err = str(e).lower()
            if "tool" in err or "function" in err or "unsupported" in err:
                # Model doesn't support function calling — fall back to data injection
                kpi       = _tool_get_kpi_summary()
                trend     = _tool_get_revenue_trend()
                breakdown = _tool_get_expense_breakdown()
                context = (
                    f"QuickBooks data: KPIs={json.dumps(kpi)}, "
                    f"Revenue trend={json.dumps(trend.get('data', []))}, "
                    f"Expenses={json.dumps(breakdown.get('data', []))}\n\nAnswer: {question}"
                )
                fb_response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": _build_system_prompt()},
                        {"role": "user",   "content": context},
                    ],
                )
                return AgentResponse(
                    text=fb_response.choices[0].message.content or "",
                    tool_results=[kpi, trend, breakdown],
                )
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
            result  = handler(fn_args) if handler else {"error": f"Unknown tool: {fn_name}"}
            tool_results_accumulated.append(result)
            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id or f"call_{fn_name}",
                "content":      json.dumps(result),
            })

    return AgentResponse(
        text="I wasn't able to fully answer that. Try asking a more specific question.",
        tool_results=tool_results_accumulated,
    )
