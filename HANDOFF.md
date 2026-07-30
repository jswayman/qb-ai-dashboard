# LiteLLM Agent Handoff — QuickBooks AI Dashboard

**Purpose:** Drop this document into your LiteLLM agent as a system prompt or context file.
It gives the agent full knowledge of the data schema, tool contracts, and expected behavior.

---

## What this system does

This is a QuickBooks Online financial intelligence layer. It:
1. Authenticates with QuickBooks Online via OAuth2
2. Syncs financial data into a local SQLite database
3. Exposes that data to an LLM agent via function-calling tools
4. Returns answers as text + structured chart data to a Streamlit dashboard

---

## System prompt (paste this into your LiteLLM deployment)

```
You are a financial analyst assistant for a QuickBooks Online account.
You have access to real-time financial data synced from QuickBooks into a local SQLite database.
You answer questions using SQL queries via the provided tools — never guess at financial numbers.

## Database Tables

### accounts
Columns: id, name, account_type, account_sub_type, current_balance, currency, active, classification
Purpose: Chart of accounts — bank accounts, income, expenses, liabilities, equity

### customers
Columns: id, display_name, company_name, email, phone, balance, active, currency
Purpose: All QB customers. `balance` = outstanding AR balance.

### vendors
Columns: id, display_name, company_name, email, balance, active, currency
Purpose: All QB vendors. `balance` = outstanding AP balance.

### invoices
Columns: id, doc_number, txn_date, due_date, customer_id, customer_name, total_amt, balance, status, currency
Purpose: Outgoing invoices. status = 'open' | 'paid'. txn_date format: YYYY-MM-DD.

### bills
Columns: id, doc_number, txn_date, due_date, vendor_id, vendor_name, total_amt, balance, currency
Purpose: Incoming vendor bills. balance > 0 means unpaid.

### expenses
Columns: id, txn_date, payment_type, total_amt, vendor_id, vendor_name, account_id, account_name, memo, currency
Purpose: All expense transactions (credit card, cash, check).

### payments
Columns: id, txn_date, customer_id, customer_name, total_amt, unapplied_amt, currency
Purpose: Payments received from customers.

## Available Tools

### query_financials(sql, chart_type?, x_col?, y_col?)
Execute any SQLite SELECT query. Set chart_type to "bar", "line", or "pie" to render a chart.
Use this for custom, ad-hoc financial questions.

### get_kpi_summary()
Returns: total_revenue, total_expenses, net_income, open_invoices, overdue_bills, top_customers_by_balance.
Use this for general "how is the business doing" questions.

### get_revenue_trend(year?)
Returns monthly revenue from invoices as a line chart dataset.

### get_expense_breakdown(group_by?, limit?)
Returns top expense totals grouped by vendor or account as a pie chart dataset.

## Response guidelines
- Always call a tool before stating a financial figure — never hallucinate numbers.
- Format currency as $X,XXX.XX in your text response.
- Keep answers to 2-4 sentences of insight followed by the data.
- If a table appears empty, tell the user to run a sync from the sidebar.
- For trend questions, prefer chart_type: "line". For comparisons, use "bar". For proportions, use "pie".
```

---

## Architecture overview

```
QuickBooks Online (cloud)
        │  OAuth2 + REST API
        ▼
  backend/qb_client.py       ← token management, API calls
        │
        ▼
  backend/sync.py            ← orchestrates full sync
        │
        ▼
  SQLite (./data/qb_data.db) ← local cache, never leaves your machine
        │
        ▼
  backend/llm_agent.py       ← LiteLLM + function-calling tools
        │
        ▼
  app.py (Streamlit)         ← chat UI + auto-rendered charts
```

---

## Switching from Ollama to your private LLM

In your `.env` file, change these two lines:

```bash
# From (Ollama dev):
LITELLM_MODEL=ollama/llama3.2
LITELLM_API_BASE=http://localhost:11434

# To (your private LiteLLM gateway):
LITELLM_MODEL=openai/your-model-name
LITELLM_API_BASE=https://your-litellm-gateway.example.com
LITELLM_API_KEY=your_api_key
```

LiteLLM supports OpenAI-compatible APIs, Llama.cpp, vLLM, and many others.
Your private LLM just needs to support the `/chat/completions` endpoint with `tools`.

**Model requirement:** Your LLM must support OpenAI-style function calling / tool use.
- Llama 3.1/3.2 via Ollama: ✓ supported
- Mistral 7B-Instruct: ✓ supported
- Any model served via vLLM with `--enable-auto-tool-choice`: ✓ supported
- Older models (e.g. Llama 2): ✗ not supported — use a newer model

---

## Adding new tools

1. Add a function definition to `TOOLS` list in `llm_agent.py` (OpenAI function format)
2. Implement the handler function (must return a dict with `data`, `chart_type`, `x_col`, `y_col`)
3. Register it in `TOOL_MAP`
4. Update the system prompt above with a description of the new tool

---

## QuickBooks setup checklist

- [ ] Create a free developer account at [developer.intuit.com](https://developer.intuit.com)
- [ ] Create an app → select **QuickBooks Online Accounting** scope
- [ ] Copy Client ID and Client Secret to `.env`
- [ ] Add redirect URI: `http://localhost:8501/callback`
- [ ] Use **Sandbox** company for testing (Intuit provides one pre-loaded with data)
- [ ] When ready for production: change `QB_ENVIRONMENT=production` in `.env`

---

## Local dev setup checklist

- [ ] `cp .env.example .env` and fill in your QB credentials
- [ ] `pip install -r requirements.txt`
- [ ] Install Ollama: [ollama.com](https://ollama.com)
- [ ] `ollama pull llama3.2`
- [ ] `streamlit run app.py`
- [ ] Connect QB in sidebar → Sync → Ask questions

---

## Known limitations of this prototype

| Limitation | Notes |
|---|---|
| Full sync only | No delta/incremental sync yet. Re-syncing replaces all rows. |
| Single company | One QB realm ID per deployment. Multi-company requires routing logic. |
| No historical reports | P&L and Balance Sheet APIs are stubbed in qb_client.py but not yet wired into the agent tools. |
| OAuth redirect in Streamlit | Streamlit can't intercept redirects easily — users paste the callback code manually. A FastAPI sidecar would solve this cleanly. |
| No auth on the app itself | Anyone who can reach the Streamlit URL can chat with your data. Add Streamlit's built-in auth or put it behind a VPN. |

---

## Recommended next steps (post-prototype)

1. **Delta sync** — use QB `MetaData.LastUpdatedTime` filter to sync only new/changed records
2. **Report tools** — add `get_profit_and_loss(start, end)` and `get_balance_sheet()` as LLM tools using the QB Reports API
3. **FastAPI backend** — replace Streamlit's OAuth workaround with a proper `/callback` route
4. **Scheduled sync** — cron job or Railway scheduled task to refresh data nightly
5. **Multi-company** — store realm_id per user, route queries to the right data partition
6. **Export** — add "Download as CSV" and "Email this report" buttons

---

*Generated: 2026-07-30 | Project: qb-ai-dashboard | Stack: LiteLLM + Ollama + QuickBooks Online + SQLite + Streamlit*
