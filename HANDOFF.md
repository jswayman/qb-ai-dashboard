# LiteLLM Agent Handoff — QuickBooks AI Dashboard

**Purpose:** Drop this document into your LiteLLM agent as a system prompt or context file.
It gives the agent full knowledge of the data schema, tool contracts, and expected behavior.

---

## What this system does

This is a QuickBooks Online financial intelligence layer. It:
1. Authenticates with QuickBooks Online via OAuth2
2. Syncs financial data into a local SQLite database
3. Exposes that data to an LLM agent via function-calling tools (or direct data injection for Ollama)
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
  backend/qb_client.py       ← token management, API calls (all credentials lazy-loaded)
        │
        ▼
  backend/sync.py            ← orchestrates full sync
        │
        ▼
  SQLite (./data/qb_data.db) ← local cache, never leaves your machine
        │
        ▼
  backend/llm_agent.py       ← dual-path agent (see below)
        │
        ▼
  app.py (Streamlit)         ← chat UI + auto-rendered charts
```

---

## Dual-path agent (critical for Ollama users)

The agent automatically detects which LLM backend is configured and adjusts its behavior:

| Backend | Strategy | Why |
|---|---|---|
| `ollama/*` | **Data injection** — pre-runs all tools, injects results into the prompt | Ollama/Llama does not reliably support OpenAI-style function calling |
| `groq/*`, `openai/*`, `your private LLM` | **Tool calling** — agentic loop with function calls | Full tool calling support, more accurate for ad-hoc queries |

If tool calling fails for any reason (e.g. model capability mismatch), the agent automatically falls back to data injection.

**If your private LLM supports tool calling** (OpenAI-compatible `/chat/completions` with `tools` parameter), the full agentic loop will be used. If not, set the model name to start with `ollama/` and it will use data injection.

---

## Switching LLM backends

Edit `.env` locally or Streamlit Cloud secrets:

```bash
# Local Ollama (data injection mode):
LITELLM_MODEL=ollama/llama3.2
LITELLM_API_BASE=http://localhost:11434

# Groq free tier (tool calling, recommended for cloud):
LITELLM_MODEL=groq/llama-3.3-70b-versatile
LITELLM_API_KEY=gsk_your-groq-key
# (no LITELLM_API_BASE needed)

# Your private LiteLLM gateway (tool calling):
LITELLM_MODEL=openai/your-model-name
LITELLM_API_BASE=https://your-litellm-gateway.example.com
LITELLM_API_KEY=your_api_key

# OpenAI fallback:
LITELLM_MODEL=gpt-4o-mini
LITELLM_API_KEY=sk-your-openai-key
# (no LITELLM_API_BASE needed)
```

**Model requirement for tool calling:** Must support OpenAI-style function calling.
- Llama 3.3 70B via Groq: ✓
- GPT-4o / GPT-4o-mini: ✓
- Llama 3.1 8B (Groq): ✗ unreliable — use 70B instead
- Llama 3.2 via Ollama: ✗ use data injection mode (automatic)
- Private LLM via vLLM with `--enable-auto-tool-choice`: ✓

---

## Local dev setup (for coworkers running their own Ollama)

```bash
# 1. Clone the repo
git clone https://github.com/jswayman/qb-ai-dashboard.git
cd qb-ai-dashboard

# 2. Install dependencies (Python 3.9+ required)
pip3 install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — fill in QB_CLIENT_ID and QB_CLIENT_SECRET

# 4. Install Ollama → https://ollama.com
ollama pull llama3.2
# Ollama starts automatically on macOS; if not: ollama serve

# 5. Launch
python3 -m streamlit run app.py
```

Open http://localhost:8501 → Connect QuickBooks → Sync → Ask questions.

**Note:** Use `python3 -m streamlit` not `streamlit` directly — macOS doesn't add the pip bin path automatically.

---

## QuickBooks setup checklist

- [ ] Create a free developer account at [developer.intuit.com](https://developer.intuit.com)
- [ ] Create an app → select **QuickBooks Online Accounting** scope
- [ ] Under **Keys & Credentials**, copy the **Development** Client ID and Secret (NOT Production)
- [ ] Under **Settings → Redirect URIs → Development tab**, add your redirect URI(s):
  - Local: `http://localhost:8501`
  - Cloud: `https://your-app.streamlit.app`
- [ ] Use the **Sandbox** company for testing (Intuit provides one pre-loaded with data)
- [ ] Set `QB_ENVIRONMENT=sandbox` in `.env` while testing
- [ ] When going to production: use Production keys + `QB_ENVIRONMENT=production`

**Common OAuth gotchas learned during setup:**
- "undefined didn't connect" = wrong Client ID (make sure to use Development key, not Production)
- "redirect_uri is invalid" = URI not registered under Settings → Redirect URIs → Development tab
- Intuit is strict about exact URI matching — no trailing slash

---

## Streamlit Cloud deployment

Live URL: **https://qb-ai-dashboard-b6carf4pchvwndd2nctely.streamlit.app**
GitHub: **https://github.com/jswayman/qb-ai-dashboard**

Secrets (set via Streamlit Cloud → app → ⋮ → Settings → Secrets):
```toml
QB_CLIENT_ID = "your_development_client_id"
QB_CLIENT_SECRET = "your_development_client_secret"
QB_REDIRECT_URI = "https://qb-ai-dashboard-b6carf4pchvwndd2nctely.streamlit.app"
QB_ENVIRONMENT = "sandbox"
APP_SECRET_KEY = "your-random-secret"
DB_PATH = "./data/qb_data.db"
TOKEN_PATH = "./data/qb_tokens.json"
LITELLM_MODEL = "groq/llama-3.3-70b-versatile"
LITELLM_API_KEY = "gsk_your-groq-key"
```

**Important:** On Streamlit Cloud, `os.environ` is populated from `st.secrets` at startup (in `app.py`). Do not rely on `.env` files on Cloud.

---

## Python version compatibility

This project requires **Python 3.9+**. All type hints use `Optional[X]` from `typing` instead of `X | None` syntax (which requires 3.10+). Do not introduce `X | Y` union syntax — it will break on Python 3.9.

---

## Adding new tools

1. Add a function definition to `TOOLS` list in `llm_agent.py` (OpenAI function format)
2. Implement the handler — must return a dict with `data`, `chart_type`, `x_col`, `y_col`
3. Add `**kwargs` to the handler signature to absorb extra args different LLMs may send
4. Register it in `TOOL_MAP`
5. Update the system prompt above with a description of the new tool
6. The Ollama data injection path (`use_tools=False`) runs pre-built tools only — add your new tool there too if it should always be available

---

## Known limitations

| Limitation | Notes |
|---|---|
| Full sync only | No delta/incremental sync. Re-syncing replaces all rows. |
| Single company | One QB realm ID per deployment. |
| Ephemeral storage on Cloud | Streamlit Cloud filesystem resets on redeploy — re-sync after restarts. |
| Shared session | All users on the Cloud URL share the same QB connection and data. Add auth before using with multiple clients. |
| No historical reports | P&L and Balance Sheet APIs are in `qb_client.py` but not yet wired into agent tools. |
| Ollama = no charts | Data injection mode answers questions but chart rendering depends on the LLM correctly returning structured data. Works best with Groq/OpenAI tool calling. |

---

## Recommended next steps

1. **Delta sync** — filter by `MetaData.LastUpdatedTime` to only pull new/changed records
2. **P&L and Balance Sheet tools** — wire `get_profit_and_loss()` and `get_balance_sheet()` from `qb_client.py` into the agent
3. **Scheduled sync** — nightly cron to keep data fresh without manual sync
4. **User auth** — add Streamlit's built-in auth or a simple password before sharing with clients
5. **Persistent token storage** — store QB tokens in a DB instead of the local filesystem so they survive Streamlit Cloud restarts
6. **Multi-company** — route by realm_id to support multiple QB accounts

---

*Last updated: 2026-07-30 | Stack: LiteLLM + Groq (cloud) / Ollama (local) + QuickBooks Online + SQLite + Streamlit*
*Repo: github.com/jswayman/qb-ai-dashboard*
