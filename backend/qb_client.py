"""
QuickBooks Online OAuth2 client + API wrapper.

OAuth2 flow:
  1. Call get_auth_url() → redirect user to Intuit
  2. Intuit redirects back with ?code=...&realmId=...
  3. Call exchange_code(code, realm_id) → saves tokens
  4. All subsequent calls use refresh_tokens() automatically
"""

import json
import os
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
from intuitlib.client import AuthClient
from intuitlib.enums import Scopes

load_dotenv()

def _secret(key: str, default: str = "") -> str:
    """Read from Streamlit secrets if available, otherwise fall back to env vars."""
    try:
        import streamlit as st
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)

CLIENT_ID = _secret("QB_CLIENT_ID")
CLIENT_SECRET = _secret("QB_CLIENT_SECRET")
REDIRECT_URI = _secret("QB_REDIRECT_URI", "http://localhost:8501")
ENVIRONMENT = _secret("QB_ENVIRONMENT", "sandbox")
TOKEN_PATH = Path(os.getenv("TOKEN_PATH", "./data/qb_tokens.json"))

BASE_URL = (
    "https://sandbox-quickbooks.api.intuit.com"
    if ENVIRONMENT == "sandbox"
    else "https://quickbooks.api.intuit.com"
)


def _auth_client() -> AuthClient:
    return AuthClient(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        environment=ENVIRONMENT,
    )


def get_auth_url() -> str:
    auth = _auth_client()
    scopes = [Scopes.ACCOUNTING]
    return auth.get_authorization_url(scopes)


def exchange_code(code: str, realm_id: str) -> dict:
    """Exchange authorization code for tokens and persist them."""
    auth = _auth_client()
    auth.get_bearer_token(code, realm_id=realm_id)
    tokens = {
        "access_token": auth.access_token,
        "refresh_token": auth.refresh_token,
        "realm_id": realm_id,
        "expires_at": time.time() + 3600,
    }
    _save_tokens(tokens)
    return tokens


def _save_tokens(tokens: dict):
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(tokens, indent=2))


def _load_tokens() -> Optional[dict]:
    if not TOKEN_PATH.exists():
        return None
    return json.loads(TOKEN_PATH.read_text())


def _refresh_if_needed(tokens: dict) -> dict:
    if time.time() < tokens.get("expires_at", 0) - 60:
        return tokens
    auth = _auth_client()
    auth.refresh(refresh_token=tokens["refresh_token"])
    tokens["access_token"] = auth.access_token
    tokens["refresh_token"] = auth.refresh_token
    tokens["expires_at"] = time.time() + 3600
    _save_tokens(tokens)
    return tokens


def is_authenticated() -> bool:
    return _load_tokens() is not None


def _get(endpoint: str, params: Optional[dict] = None) -> dict:
    tokens = _load_tokens()
    if not tokens:
        raise RuntimeError("Not authenticated. Complete OAuth2 flow first.")
    tokens = _refresh_if_needed(tokens)
    realm_id = tokens["realm_id"]
    url = f"{BASE_URL}/v3/company/{realm_id}/{endpoint}"
    headers = {
        "Authorization": f"Bearer {tokens['access_token']}",
        "Accept": "application/json",
    }
    resp = requests.get(url, headers=headers, params=params or {})
    resp.raise_for_status()
    return resp.json()


# ─── QB Entity fetchers ───────────────────────────────────────────────────────

def query(sql: str) -> list[dict]:
    """Run a QB SQL-like query and return rows."""
    data = _get("query", {"query": sql})
    qr = data.get("QueryResponse", {})
    # QueryResponse has a key matching the entity name
    for key, val in qr.items():
        if isinstance(val, list):
            return val
    return []


def get_accounts() -> list[dict]:
    return query("SELECT * FROM Account MAXRESULTS 1000")


def get_customers() -> list[dict]:
    return query("SELECT * FROM Customer MAXRESULTS 1000")


def get_vendors() -> list[dict]:
    return query("SELECT * FROM Vendor MAXRESULTS 1000")


def get_invoices(max_results: int = 500) -> list[dict]:
    return query(f"SELECT * FROM Invoice ORDERBY MetaData.LastUpdatedTime DESC MAXRESULTS {max_results}")


def get_bills(max_results: int = 500) -> list[dict]:
    return query(f"SELECT * FROM Bill ORDERBY MetaData.LastUpdatedTime DESC MAXRESULTS {max_results}")


def get_payments() -> list[dict]:
    return query("SELECT * FROM Payment ORDERBY MetaData.LastUpdatedTime DESC MAXRESULTS 500")


def get_expenses() -> list[dict]:
    return query("SELECT * FROM Purchase ORDERBY MetaData.LastUpdatedTime DESC MAXRESULTS 500")


def get_profit_and_loss(start_date: str = "2024-01-01", end_date: str = "2024-12-31") -> dict:
    """Fetch P&L summary report from QB Reports API."""
    tokens = _load_tokens()
    if not tokens:
        raise RuntimeError("Not authenticated.")
    tokens = _refresh_if_needed(tokens)
    realm_id = tokens["realm_id"]
    url = f"{BASE_URL}/v3/company/{realm_id}/reports/ProfitAndLoss"
    headers = {
        "Authorization": f"Bearer {tokens['access_token']}",
        "Accept": "application/json",
    }
    params = {"start_date": start_date, "end_date": end_date, "accounting_method": "Accrual"}
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    return resp.json()


def get_balance_sheet(as_of_date: str = "2024-12-31") -> dict:
    tokens = _load_tokens()
    if not tokens:
        raise RuntimeError("Not authenticated.")
    tokens = _refresh_if_needed(tokens)
    realm_id = tokens["realm_id"]
    url = f"{BASE_URL}/v3/company/{realm_id}/reports/BalanceSheet"
    headers = {
        "Authorization": f"Bearer {tokens['access_token']}",
        "Accept": "application/json",
    }
    params = {"date_macro": "This Fiscal Year-to-date"}
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    return resp.json()


def get_company_info() -> dict:
    tokens = _load_tokens()
    if not tokens:
        raise RuntimeError("Not authenticated.")
    realm_id = tokens["realm_id"]
    data = _get(f"companyinfo/{realm_id}")
    return data.get("CompanyInfo", {})
