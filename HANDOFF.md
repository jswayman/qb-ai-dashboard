# QuickBooks AI Dashboard — Handoff & Architecture Guide

**Purpose:** Full reference for developers, client stakeholders, or LLM agents working with this codebase.
Covers architecture, data flow, KPI calculation glossary, deployment, and extension points.

**Live app:** https://qb-ai-dashboard-b6carf4pchvwndd2nctely.streamlit.app
**GitHub:** https://github.com/jswayman/qb-ai-dashboard

---

## Table of contents

1. [What this system does](#what-this-system-does)
2. [Architecture overview](#architecture-overview)
3. [Data model](#data-model)
4. [KPI & Calculation Glossary](#kpi--calculation-glossary)
5. [Period filtering logic](#period-filtering-logic)
6. [LLM agent system prompt](#llm-agent-system-prompt)
7. [Dual-path agent (Ollama vs tool calling)](#dual-path-agent)
8. [Switching LLM backends](#switching-llm-backends)
9. [QuickBooks setup checklist](#quickbooks-setup-checklist)
10. [Streamlit Cloud deployment](#streamlit-cloud-deployment)
11. [Local dev setup](#local-dev-setup)
12. [Adding new tools](#adding-new-tools)
13. [Known limitations](#known-limitations)
14. [Recommended next steps](#recommended-next-steps)

---

## What this system does

1. Authenticates with QuickBooks Online via OAuth2
2. Syncs financial data (invoices, bills, expenses, payments, accounts, customers, vendors) into a local SQLite database
3. Pre-renders an executive dashboard with KPI cards and charts filtered to the selected time period
4. Exposes all data to an LLM agent for natural-language Q&A with chart generation

---

## Architecture overview

```
QuickBooks Online (cloud)
        │  OAuth2 + REST API
        ▼
  backend/qb_client.py     ← token management, API calls
        │
        ▼
  backend/sync.py          ← orchestrates full data sync
        │
        ▼
  SQLite (./data/qb_data.db)  ← local cache, 7 tables
        │
        ├──► backend/queries.py   ← all _tool_* data functions (no LLM dependency)
        │         │
        │         ├──► app.py (Streamlit)   ← KPI cards, charts, period filters
        │         │
        │         └──► backend/llm_agent.py ← LiteLLM tool definitions + chat loop
        │
        └──► app.py (AI Assistant tab)  ← chat UI + auto-rendered charts
```

### Module responsibilities

| File | Role |
|---|---|
| `app.py` | Streamlit UI: sidebar filters, KPI cards, chart tabs, AI chat interface, custom CSS |
| `backend/qb_client.py` | QuickBooks OAuth2 token flow + all API calls |
| `backend/sync.py` | Orchestrates full sync: calls QB API, upserts into SQLite |
| `backend/db.py` | SQLite schema initialization + `run_sql(query) → DataFrame` helper |
| `backend/queries.py` | All `_tool_*` data functions — pure Python/pandas, no LLM dependency |
| `backend/llm_agent.py` | LiteLLM agent: TOOLS list, TOOL_MAP, `chat()` function |
| `.streamlit/config.toml` | Dark executive theme (base, colors, font) |

**Key design decision:** `queries.py` is intentionally separated from `llm_agent.py` so the dashboard can import data functions without pulling in the `litellm` dependency. This prevents import errors on Streamlit Cloud if the LLM backend is unavailable.

---

## Data model

All data lives in `./data/qb_data.db` (SQLite). Tables are created by `backend/db.py` on first run.

### `accounts`
```
id, name, account_type, account_sub_type, current_balance, currency, active, classification
```
QuickBooks Chart of Accounts. Includes bank accounts, credit cards, income accounts, expense accounts, liability accounts, equity. `current_balance` = live QB balance at time of last sync.

### `customers`
```
id, display_name, company_name, email, phone, balance, active, currency
```
All QB customers. `balance` = outstanding accounts receivable balance per QB.

### `vendors`
```
id, display_name, company_name, email, balance, active, currency
```
All QB vendors. `balance` = outstanding accounts payable balance per QB.

### `invoices`
```
id, doc_number, txn_date, due_date, customer_id, customer_name, total_amt, balance, status, currency
```
Outgoing invoices. `status` = `'open'` or `'paid'`. `total_amt` = invoice total. `balance` = unpaid amount remaining. `txn_date` format: `YYYY-MM-DD`.

### `bills`
```
id, doc_number, txn_date, due_date, vendor_id, vendor_name, total_amt, balance, currency
```
Incoming vendor bills. `balance > 0` means the bill has an unpaid balance. A bill is "overdue" when `balance > 0 AND due_date < today`.

### `expenses`
```
id, txn_date, payment_type, total_amt, vendor_id, vendor_name, account_id, account_name, memo, currency
```
All expense transactions (credit card charges, checks, cash). `account_name` maps to an expense category in the chart of accounts.

### `payments`
```
id, txn_date, customer_id, customer_name, total_amt, unapplied_amt, currency
```
Payments received from customers and applied to invoices.

---

## KPI & Calculation Glossary

This section explains exactly how each KPI is calculated, what data it comes from, and what the comparison deltas mean. Use this to explain numbers to the client.

---

### Total Revenue

**What it shows:** The sum of all invoice amounts billed to customers in the selected period.

**Data source:** `invoices` table, `total_amt` column.

**SQL:**
```sql
SELECT SUM(total_amt) FROM invoices
WHERE txn_date BETWEEN '{start_date}' AND '{end_date}'
```

**Important caveats:**
- This counts invoices by their **transaction date** (`txn_date`), not when payment was received. An invoice dated in June is counted in June even if paid in July.
- Includes both `open` (unpaid) and `paid` invoices. It measures what was billed, not what was collected.
- Does not include payments received in the period that were applied to prior-period invoices — those are tracked separately in the `payments` table.

**When to use:** Revenue performance, billing volume, top-line growth.

---

### Total Expenses

**What it shows:** The sum of all expense transactions in the selected period.

**Data source:** `expenses` table, `total_amt` column.

**SQL:**
```sql
SELECT SUM(total_amt) FROM expenses
WHERE txn_date BETWEEN '{start_date}' AND '{end_date}'
```

**Important caveats:**
- Covers cash, check, and credit card expenses synced from QB.
- Does **not** include vendor bill amounts (those are in the `bills` table). This is cash/card spending, not accrued payables.
- If the client records most costs as bills rather than direct expenses, Total Expenses will undercount actual spending.

**When to use:** Cost control, expense trend analysis, profitability analysis.

---

### Net Income

**What it shows:** The period profit or loss — Total Revenue minus Total Expenses.

**Formula:**
```
Net Income = Total Revenue − Total Expenses
```

**Data source:** Derived from `invoices` and `expenses` tables (same date filter as above).

**Color coding:**
- Green card = positive (profit)
- Red card = negative (loss)

**Important caveats:**
- This is a cash-basis approximation, not a GAAP accrual P&L. QuickBooks' official P&L report may differ because it accounts for accrued income and expenses on vendor bills.
- The official QuickBooks P&L is available via the Reports API and can be wired in as a future enhancement.

**When to use:** Overall business health, profitability trends, executive summary.

---

### Cash & Bank

**What it shows:** The total current balance across all bank and cash accounts in QuickBooks at the time of the last sync.

**Data source:** `accounts` table, `current_balance` column, filtered to bank/cash account types.

**SQL:**
```sql
SELECT SUM(current_balance) FROM accounts
WHERE account_type IN ('Bank', 'Other Current Asset')
AND account_sub_type IN ('Checking', 'Savings', 'MoneyMarket', 'CashAndCashEquivalents')
```

**Why this card always shows "Current" regardless of period filter:**
The balance API returns a single point-in-time number — what the account balance is right now. QuickBooks does not provide historical balance snapshots via the standard sync API. The balance updates each time you run a sync from the sidebar.

**Delta badges (MoM / YoY):**
Since historical balances aren't available, the delta badges show the **change in net cash generation** (net income) between the selected period and the prior period. This answers: "Did the business generate more or less cash this period compared to last?"

- Formula: `Current period Net Income − Prior period Net Income`
- Displayed as an absolute dollar change (e.g. `+$1.2K MoM`) rather than a percentage, because percentages are misleading when net income crosses zero.

**When to use:** Liquidity check, treasury position, cash runway assessment.

---

### Open Invoices

**What it shows:** The count of invoices with `status = 'open'` (not yet fully paid) that were created in the selected period.

**Data source:** `invoices` table.

**SQL:**
```sql
SELECT COUNT(*) FROM invoices
WHERE status = 'open'
AND txn_date BETWEEN '{start_date}' AND '{end_date}'
```

**Color coding:**
- Amber = one or more open invoices (needs attention)
- Blue = no open invoices

**Delta badges:** Percentage change in open invoice count vs. prior period and prior year. A **decrease** is good (fewer uncollected invoices), so the delta is inverted — a drop in count shows as green.

**When to use:** AR management, collection follow-up, billing discipline.

---

### Overdue Bills

**What it shows:** The count of vendor bills with an unpaid balance where the due date has already passed.

**Data source:** `bills` table.

**SQL:**
```sql
SELECT COUNT(*) FROM bills
WHERE balance > 0
AND due_date < date('now')
AND txn_date BETWEEN '{start_date}' AND '{end_date}'
```

**Period filter note:** The period filter applies to the bill's `txn_date` (when the bill was created), not `due_date`. Bills created in the selected period that are now past due are shown. Bills created in a prior period that are still overdue will not appear unless those prior periods are selected.

**Color coding:**
- Red = overdue bills exist
- Green = all clear

**Delta badges:** Percentage change in overdue bill count. A **decrease** is good, so the delta is inverted — fewer overdue bills shows as green. Displayed as "As of today" since it reflects current outstanding status.

**When to use:** AP management, vendor relationship health, cash obligation awareness.

---

### MoM (Month-over-Month) Delta

**What it shows:** How a KPI value changed compared to the immediately preceding calendar month.

**When it appears:** Only when the Period filter is set to **Month**.

**Prior period dates:**
- If current period = June 2026 → prior period = May 2026
- If current period = January 2026 → prior period = December 2025

**Format:** `+12.3% MoM` (percentage) or `+$1.2K MoM` (absolute, for Cash & Bank).

---

### QoQ (Quarter-over-Quarter) Delta

**What it shows:** How a KPI changed compared to the immediately preceding calendar quarter.

**When it appears:** Only when the Period filter is set to **Quarter**.

**Prior period dates:**
- Q2 2026 → prior period = Q1 2026
- Q1 2026 → prior period = Q4 2025

**Format:** `+12.3% QoQ`

---

### YoY (Year-over-Year) Delta

**What it shows:** How a KPI changed compared to the same period exactly one year earlier.

**When it appears:** Always shown alongside MoM or QoQ when data is available. For **Year** and **YTD** period types, the PoP delta badge IS the YoY delta (comparing to the same period last year), so only one badge appears.

**Prior year date calculation:**
- Jun 2026 → Jun 2025 (same month, prior year)
- Q2 2026 → Q2 2025
- YTD 2026 (Jan–Jul 2026) → Jan–Jul 2025
- FY 2025 → FY 2024

**Edge case:** Feb 29 in a leap year compares to Feb 28 of the prior year.

**Format:** `+8.5% YoY`

---

### How delta color coding works

| Delta direction | Default | Inverted (Expenses, Open Invoices, Overdue Bills) |
|---|---|---|
| Positive (value went up) | 🟢 Green | 🔴 Red |
| Negative (value went down) | 🔴 Red | 🟢 Green |
| No prior data | ⬜ Grey | ⬜ Grey |

Expenses, Open Invoices, and Overdue Bills are "inverted" because a decrease in those metrics is a good outcome.

---

## Period filtering logic

All KPI data is filtered using `txn_date BETWEEN '{start_date}' AND '{end_date}'`.

| Period type | Start date | End date | Example label |
|---|---|---|---|
| Year | Jan 1 of selected year | Dec 31 of selected year | `FY 2025` |
| YTD | Jan 1 of selected year | Today (if current year) or Dec 31 | `YTD 2026` |
| Quarter | First day of selected quarter | Last day of selected quarter | `Q2 2026` |
| Month | First day of selected month | Last day of selected month | `Jun 2026` |

### Prior period (PoP) date calculation

| Current period | Prior period |
|---|---|
| Any Month | Previous calendar month |
| Any Quarter | Previous calendar quarter |
| Year / YTD | Same date range, year − 1 |

### Prior year (YoY) date calculation

For all period types: same `start_date` and `end_date`, but with `year − 1`. February 29 edge cases resolve to February 28.

---

## LLM agent system prompt

Paste this into your LiteLLM deployment as the system prompt:

```
You are a financial analyst assistant for a QuickBooks Online account.
You have access to real-time financial data synced from QuickBooks into a local SQLite database.
You answer questions using SQL queries via the provided tools — never guess at financial numbers.

## Database Tables

### accounts
Columns: id, name, account_type, account_sub_type, current_balance, currency, active, classification
Purpose: Chart of accounts — bank accounts, income, expenses, liabilities, equity. current_balance = live QB balance.

### customers
Columns: id, display_name, company_name, email, phone, balance, active, currency
Purpose: All QB customers. balance = outstanding AR balance.

### vendors
Columns: id, display_name, company_name, email, balance, active, currency
Purpose: All QB vendors. balance = outstanding AP balance.

### invoices
Columns: id, doc_number, txn_date, due_date, customer_id, customer_name, total_amt, balance, status, currency
Purpose: Outgoing invoices. status = 'open' | 'paid'. txn_date format: YYYY-MM-DD.

### bills
Columns: id, doc_number, txn_date, due_date, vendor_id, vendor_name, total_amt, balance, currency
Purpose: Incoming vendor bills. balance > 0 means unpaid. Overdue = balance > 0 AND due_date < date('now').

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
Returns: total_revenue, total_expenses, net_income, open_invoices, overdue_bills.
All-time totals. For period-specific totals, use query_financials with a date filter.

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
- Revenue = invoices.total_amt (billed, not collected). Expenses = expenses.total_amt (direct spend, not vendor bills).
```

---

## Dual-path agent

The agent auto-detects the LLM backend and adjusts:

| Backend | Strategy | Why |
|---|---|---|
| `ollama/*` | **Data injection** — pre-runs all tools, injects results into the prompt | Ollama/Llama does not reliably support OpenAI-style function calling |
| `groq/*`, `openai/*`, custom | **Tool calling** — agentic loop with function calls | Full tool calling, more accurate for ad-hoc queries |

If tool calling fails (model capability mismatch), the agent falls back to data injection automatically.

---

## Switching LLM backends

Edit `.env` locally or Streamlit Cloud Secrets:

```bash
# Local Ollama (data injection mode):
LITELLM_MODEL=ollama/llama3.2
LITELLM_API_BASE=http://localhost:11434

# Groq free tier (recommended for cloud):
LITELLM_MODEL=groq/llama-3.3-70b-versatile
LITELLM_API_KEY=gsk_your-groq-key

# OpenAI:
LITELLM_MODEL=gpt-4o-mini
LITELLM_API_KEY=sk-your-openai-key

# Private LiteLLM gateway:
LITELLM_MODEL=openai/your-model-name
LITELLM_API_BASE=https://your-gateway.example.com
LITELLM_API_KEY=your_api_key
```

**Model requirements for tool calling:**
- Groq Llama 3.3 70B: ✓
- GPT-4o / GPT-4o-mini: ✓
- Llama 3.1 8B (Groq): ✗ unreliable — use 70B
- Llama 3.2 via Ollama: ✗ use data injection (automatic)
- Private vLLM with `--enable-auto-tool-choice`: ✓

---

## QuickBooks setup checklist

- [ ] Create a free developer account at [developer.intuit.com](https://developer.intuit.com)
- [ ] Create an app → scope: **QuickBooks Online Accounting**
- [ ] Copy **Development** Client ID and Secret (not Production)
- [ ] Under **Settings → Redirect URIs → Development tab**, add:
  - Local: `http://localhost:8501`
  - Cloud: `https://your-app.streamlit.app`
- [ ] Use the **Sandbox** company for testing (pre-loaded with data)
- [ ] Set `QB_ENVIRONMENT=sandbox` in `.env` while testing
- [ ] For production: use Production keys + `QB_ENVIRONMENT=production`

**Common OAuth errors:**
- "undefined didn't connect" → wrong Client ID (use Development, not Production)
- "redirect_uri is invalid" → URI not registered in Settings → Redirect URIs → Development tab
- Intuit requires exact URI matching — no trailing slash

---

## Streamlit Cloud deployment

**Live URL:** https://qb-ai-dashboard-b6carf4pchvwndd2nctely.streamlit.app

Set secrets via: Streamlit Cloud → app → ⋮ → Settings → Secrets

```toml
QB_CLIENT_ID        = "your_development_client_id"
QB_CLIENT_SECRET    = "your_development_client_secret"
QB_REDIRECT_URI     = "https://qb-ai-dashboard-b6carf4pchvwndd2nctely.streamlit.app"
QB_ENVIRONMENT      = "sandbox"
APP_SECRET_KEY      = "your-random-secret"
DB_PATH             = "./data/qb_data.db"
TOKEN_PATH          = "./data/qb_tokens.json"
LITELLM_MODEL       = "groq/llama-3.3-70b-versatile"
LITELLM_API_KEY     = "gsk_your-groq-key"
```

**Note:** On Streamlit Cloud, `os.environ` is populated from `st.secrets` at startup (handled in `app.py`). Do not rely on `.env` files on Cloud. The SQLite database and token file are ephemeral — re-sync after each redeploy or app restart.

---

## Local dev setup

```bash
git clone https://github.com/jswayman/qb-ai-dashboard.git
cd qb-ai-dashboard
pip3 install -r requirements.txt
cp .env.example .env
# Edit .env — fill in QB_CLIENT_ID, QB_CLIENT_SECRET, and LLM credentials

# Optional: local Ollama
ollama pull llama3.2

python3 -m streamlit run app.py
```

Use `python3 -m streamlit` — macOS may not have `streamlit` on PATH after pip install.

---

## Adding new tools

1. Implement a `_tool_your_function(**kwargs) -> dict` in `backend/queries.py`
   - Must return a dict with at minimum `data` (list of dicts)
   - Optional keys: `chart_type` (`"bar"`, `"line"`, `"pie"`, `"none"`), `x_col`, `y_col`
2. Add it to the `TOOLS` list in `llm_agent.py` (OpenAI function format)
3. Register it in `TOOL_MAP` in `llm_agent.py`
4. Import it in `app.py` if it should appear in the pre-rendered dashboard
5. Update the system prompt above with a description of the new tool
6. If using Ollama data injection mode, add the tool call to the `use_tools=False` block in `llm_agent.py`

**Python version note:** This project requires Python 3.9+. Use `Optional[X]` from `typing` instead of `X | None` syntax (which requires 3.10+).

---

## Known limitations

| Limitation | Notes |
|---|---|
| Full sync only | No delta/incremental sync. Re-syncing replaces all rows. |
| Single company | One QB realm ID per deployment. |
| Ephemeral storage on Cloud | Streamlit Cloud filesystem resets on redeploy — re-sync after restarts. |
| Shared session | All users on the Cloud URL share the same QB connection. Add auth before using with multiple clients. |
| Cash & Bank is point-in-time | Live account balance only — no historical balance snapshots from the QB sync API. Period deltas use net income as a proxy. |
| Revenue = billed, not collected | Invoices are recorded on `txn_date`. Uncollected invoices still count as revenue in that period. |
| Expenses ≠ full GAAP cost | `expenses` table captures direct spend; vendor bills (`bills` table) are not included in Total Expenses. |
| No official P&L or Balance Sheet | QuickBooks Reports API (P&L, Balance Sheet) is available in `qb_client.py` but not wired into the dashboard tools yet. |
| Ollama = less reliable charts | Data injection mode answers questions but chart quality depends on the model returning well-structured data. |

---

## Recommended next steps

1. **Official P&L tool** — wire `get_profit_and_loss()` from `qb_client.py` into the agent for GAAP-accurate income statements
2. **Balance Sheet tool** — same pattern, for assets/liabilities/equity snapshot
3. **Delta sync** — filter by `MetaData.LastUpdatedTime` to only pull new/changed records instead of full replace
4. **Historical cash balance snapshots** — store account balances to a `balance_snapshots` table on each sync so Cash & Bank MoM/YoY can use real numbers
5. **Scheduled sync** — nightly cron to keep data fresh without manual button clicks
6. **User auth** — add Streamlit's built-in auth or a simple password gate before sharing with clients
7. **Persistent token storage** — store QB OAuth tokens in a DB table (not filesystem) so they survive Streamlit Cloud restarts
8. **Multi-company support** — route by `realm_id` to support multiple QB accounts from one deployment
9. **Include bills in Total Expenses** — add `bills.total_amt` to the expenses calculation for a more complete picture of accrued costs

---

*Last updated: 2026-07-31*
*Stack: Streamlit + LiteLLM + Groq (cloud) / Ollama (local) + QuickBooks Online + SQLite*
*Repo: github.com/jswayman/qb-ai-dashboard*
