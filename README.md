# QuickBooks AI Dashboard

Chat with your QuickBooks financials using natural language.
Powered by LiteLLM + Ollama (swap to your private LLM when ready).

![Stack: Python + Streamlit + LiteLLM + QuickBooks Online]

## Quick start

```bash
# 1. Clone / navigate to this folder
cd qb-ai-dashboard

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — add your QB_CLIENT_ID and QB_CLIENT_SECRET

# 4. Install and start Ollama (local LLM)
# → https://ollama.com
ollama pull llama3.2
ollama serve   # runs on localhost:11434

# 5. Launch the dashboard
streamlit run app.py
```

Open http://localhost:8501, connect QuickBooks in the sidebar, sync, and start asking questions.

## Getting QuickBooks API credentials (5 min)

1. Go to [developer.intuit.com](https://developer.intuit.com) and sign in with your Intuit account
2. Click **Create an app** → select **QuickBooks Online and Payments**
3. Choose **QuickBooks Online Accounting** scope
4. Under **Keys & OAuth** → copy your **Client ID** and **Client Secret**
5. Add redirect URI: `http://localhost:8501/callback`
6. Intuit gives you a free **Sandbox company** with test data — use that first

## Example questions

- "What's my net income this year?"
- "Show me monthly revenue for 2024 as a line chart"
- "Which vendors am I spending the most with?"
- "How many open invoices do I have?"
- "Who are my top 5 customers by balance?"
- "Show me all overdue bills"

## Switching to your private LLM

Edit `.env`:

```bash
LITELLM_MODEL=openai/your-model-name
LITELLM_API_BASE=https://your-litellm-gateway.example.com
LITELLM_API_KEY=your_key
```

That's the only change needed. See `HANDOFF.md` for full architecture docs.

## Project structure

```
qb-ai-dashboard/
├── app.py                  # Streamlit dashboard
├── requirements.txt
├── .env.example
├── README.md
├── HANDOFF.md              # LiteLLM agent handoff document
└── backend/
    ├── qb_client.py        # QuickBooks OAuth2 + API
    ├── db.py               # SQLite schema + queries
    ├── sync.py             # Full data sync orchestration
    └── llm_agent.py        # LiteLLM + function-calling tools
```
