# QuickBooks AI Dashboard

An executive financial dashboard that connects directly to QuickBooks Online, pre-renders key KPIs and charts, and lets you ask natural-language questions about your financials.

**Live app:** https://qb-ai-dashboard-b6carf4pchvwndd2nctely.streamlit.app
**GitHub:** https://github.com/jswayman/qb-ai-dashboard

---

## What it does

- **Pre-rendered KPI cards** — Total Revenue, Total Expenses, Net Income, Cash & Bank, Open Invoices, Overdue Bills — visible the moment the page loads
- **Period filtering** — view any KPI by Month, Quarter, YTD, or full Year
- **Period-over-period comparisons** — each KPI card shows MoM/QoQ/YoY delta badges with color-coded direction
- **Time-frame labels** — every card shows the exact period it represents (e.g. `Jun 2026`, `Q2 2026`, `YTD 2026`)
- **Four analytics tabs** — Overview, Revenue & Cash, Expenses & Payables, Customers & Vendors
- **AI Assistant tab** — natural-language Q&A with chart generation powered by LiteLLM
- **Dark executive theme** — Inter font, dark palette, Plotly dark charts

See `HANDOFF.md` for full architecture, KPI calculation glossary, and deployment details.

---

## Quick start (local)

```bash
# 1. Clone
git clone https://github.com/jswayman/qb-ai-dashboard.git
cd qb-ai-dashboard

# 2. Install dependencies (Python 3.9+ required)
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — add QB_CLIENT_ID, QB_CLIENT_SECRET, and your LLM key

# 4. (Optional) Install Ollama for a local LLM — https://ollama.com
ollama pull llama3.2

# 5. Launch
python3 -m streamlit run app.py
```

Open http://localhost:8501 → connect QuickBooks in the sidebar → Sync → explore.

---

## Getting QuickBooks API credentials (~5 min)

1. Go to [developer.intuit.com](https://developer.intuit.com) and sign in
2. Click **Create an app** → **QuickBooks Online and Payments**
3. Choose scope: **QuickBooks Online Accounting**
4. Under **Keys & OAuth** → copy **Client ID** and **Client Secret** (Development tab)
5. Under **Settings → Redirect URIs → Development tab**, add:
   - Local: `http://localhost:8501`
   - Cloud: `https://your-app.streamlit.app`
6. Use the free **Sandbox** company Intuit provides for initial testing

---

## Period filters

The left sidebar controls the time window for all KPI cards:

| Period | What it covers |
|---|---|
| **YTD** | January 1 of the selected year through today (or Dec 31 if a past year) |
| **Month** | The selected calendar month |
| **Quarter** | Q1 = Jan–Mar, Q2 = Apr–Jun, Q3 = Jul–Sep, Q4 = Oct–Dec |
| **Year** | Full calendar year (Jan 1 – Dec 31) |

Charts on the Overview, Revenue & Cash, and other tabs use the selected Year for their trend views.

---

## KPI cards at a glance

Each card shows three layers of information:

```
┌─────────────────────────────┐
│ TOTAL REVENUE      Jun 2026 │  ← metric label + period badge
│ $4.2K                       │  ← value for the selected period
│ +326.0% MoM  +12.4% YoY    │  ← period-over-period delta badges
└─────────────────────────────┘
```

Delta color coding:
- **Green** = improvement (revenue up, expenses down, etc.)
- **Red** = deterioration
- **Amber** = caution (outstanding invoices)
- **Grey** = no prior data available

See the **KPI & Calculation Glossary** section in `HANDOFF.md` for a full breakdown of how each number is calculated and where it comes from.

---

## AI Assistant example questions

- "What's my net income this year?"
- "Show me monthly revenue for 2024 as a line chart"
- "Which vendors am I spending the most with?"
- "How many open invoices do I have?"
- "Who are my top 5 customers by balance?"
- "Show me all overdue bills"

---

## Switching your LLM backend

Edit `.env` (local) or Streamlit Cloud Secrets (cloud):

```bash
# Local Ollama (data injection mode — no function calling required):
LITELLM_MODEL=ollama/llama3.2
LITELLM_API_BASE=http://localhost:11434

# Groq free tier (recommended for cloud — full tool calling):
LITELLM_MODEL=groq/llama-3.3-70b-versatile
LITELLM_API_KEY=gsk_your-groq-key

# OpenAI:
LITELLM_MODEL=gpt-4o-mini
LITELLM_API_KEY=sk-your-openai-key

# Private LiteLLM gateway:
LITELLM_MODEL=openai/your-model-name
LITELLM_API_BASE=https://your-gateway.example.com
LITELLM_API_KEY=your_key
```

---

## Project structure

```
qb-ai-dashboard/
├── app.py                  # Streamlit dashboard (UI, KPIs, charts, AI chat)
├── requirements.txt
├── .env.example
├── runtime.txt             # Python version pin for Streamlit Cloud
├── README.md               # This file
├── HANDOFF.md              # Full architecture + KPI glossary + deployment guide
├── .streamlit/
│   └── config.toml         # Dark theme configuration
└── backend/
    ├── qb_client.py        # QuickBooks OAuth2 + REST API client
    ├── db.py               # SQLite schema init + run_sql helper
    ├── sync.py             # Full data sync orchestration
    ├── queries.py          # All data query functions (_tool_* helpers)
    └── llm_agent.py        # LiteLLM agent + tool definitions
```

---

*Last updated: 2026-07-31 | Stack: Streamlit + LiteLLM + QuickBooks Online + SQLite*
