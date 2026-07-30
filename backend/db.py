"""
SQLite persistence layer for synced QuickBooks data.

All QB data is normalized into flat tables so the LLM agent
can query them directly with SQL via the tools in llm_agent.py.
"""

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "./data/qb_data.db")
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)


def _exec(sql: str, params: dict | None = None):
    with engine.begin() as conn:
        conn.execute(text(sql), params or {})


def init_schema():
    """Create all tables if they don't exist."""
    _exec("""
        CREATE TABLE IF NOT EXISTS sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity TEXT NOT NULL,
            synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            row_count INTEGER
        )
    """)
    _exec("""
        CREATE TABLE IF NOT EXISTS accounts (
            id TEXT PRIMARY KEY,
            name TEXT,
            account_type TEXT,
            account_sub_type TEXT,
            current_balance REAL,
            currency TEXT,
            active INTEGER,
            classification TEXT
        )
    """)
    _exec("""
        CREATE TABLE IF NOT EXISTS customers (
            id TEXT PRIMARY KEY,
            display_name TEXT,
            company_name TEXT,
            email TEXT,
            phone TEXT,
            balance REAL,
            active INTEGER,
            currency TEXT
        )
    """)
    _exec("""
        CREATE TABLE IF NOT EXISTS vendors (
            id TEXT PRIMARY KEY,
            display_name TEXT,
            company_name TEXT,
            email TEXT,
            balance REAL,
            active INTEGER,
            currency TEXT
        )
    """)
    _exec("""
        CREATE TABLE IF NOT EXISTS invoices (
            id TEXT PRIMARY KEY,
            doc_number TEXT,
            txn_date TEXT,
            due_date TEXT,
            customer_id TEXT,
            customer_name TEXT,
            total_amt REAL,
            balance REAL,
            status TEXT,
            currency TEXT
        )
    """)
    _exec("""
        CREATE TABLE IF NOT EXISTS bills (
            id TEXT PRIMARY KEY,
            doc_number TEXT,
            txn_date TEXT,
            due_date TEXT,
            vendor_id TEXT,
            vendor_name TEXT,
            total_amt REAL,
            balance REAL,
            currency TEXT
        )
    """)
    _exec("""
        CREATE TABLE IF NOT EXISTS expenses (
            id TEXT PRIMARY KEY,
            txn_date TEXT,
            payment_type TEXT,
            total_amt REAL,
            vendor_id TEXT,
            vendor_name TEXT,
            account_id TEXT,
            account_name TEXT,
            memo TEXT,
            currency TEXT
        )
    """)
    _exec("""
        CREATE TABLE IF NOT EXISTS payments (
            id TEXT PRIMARY KEY,
            txn_date TEXT,
            customer_id TEXT,
            customer_name TEXT,
            total_amt REAL,
            unapplied_amt REAL,
            currency TEXT
        )
    """)


# ─── Upsert helpers ───────────────────────────────────────────────────────────

def upsert_accounts(rows: list[dict]):
    data = []
    for r in rows:
        data.append({
            "id": r.get("Id"),
            "name": r.get("Name"),
            "account_type": r.get("AccountType"),
            "account_sub_type": r.get("AccountSubType"),
            "current_balance": r.get("CurrentBalance", 0),
            "currency": r.get("CurrencyRef", {}).get("value", "USD"),
            "active": 1 if r.get("Active", True) else 0,
            "classification": r.get("Classification"),
        })
    df = pd.DataFrame(data)
    if not df.empty:
        df.to_sql("accounts", engine, if_exists="replace", index=False)
    _log_sync("accounts", len(data))


def upsert_customers(rows: list[dict]):
    data = []
    for r in rows:
        data.append({
            "id": r.get("Id"),
            "display_name": r.get("DisplayName"),
            "company_name": r.get("CompanyName"),
            "email": r.get("PrimaryEmailAddr", {}).get("Address"),
            "phone": r.get("PrimaryPhone", {}).get("FreeFormNumber"),
            "balance": r.get("Balance", 0),
            "active": 1 if r.get("Active", True) else 0,
            "currency": r.get("CurrencyRef", {}).get("value", "USD"),
        })
    df = pd.DataFrame(data)
    if not df.empty:
        df.to_sql("customers", engine, if_exists="replace", index=False)
    _log_sync("customers", len(data))


def upsert_vendors(rows: list[dict]):
    data = []
    for r in rows:
        data.append({
            "id": r.get("Id"),
            "display_name": r.get("DisplayName"),
            "company_name": r.get("CompanyName"),
            "email": r.get("PrimaryEmailAddr", {}).get("Address"),
            "balance": r.get("Balance", 0),
            "active": 1 if r.get("Active", True) else 0,
            "currency": r.get("CurrencyRef", {}).get("value", "USD"),
        })
    df = pd.DataFrame(data)
    if not df.empty:
        df.to_sql("vendors", engine, if_exists="replace", index=False)
    _log_sync("vendors", len(data))


def upsert_invoices(rows: list[dict]):
    data = []
    for r in rows:
        customer_ref = r.get("CustomerRef", {})
        data.append({
            "id": r.get("Id"),
            "doc_number": r.get("DocNumber"),
            "txn_date": r.get("TxnDate"),
            "due_date": r.get("DueDate"),
            "customer_id": customer_ref.get("value"),
            "customer_name": customer_ref.get("name"),
            "total_amt": r.get("TotalAmt", 0),
            "balance": r.get("Balance", 0),
            "status": "paid" if r.get("Balance", 1) == 0 else "open",
            "currency": r.get("CurrencyRef", {}).get("value", "USD"),
        })
    df = pd.DataFrame(data)
    if not df.empty:
        df.to_sql("invoices", engine, if_exists="replace", index=False)
    _log_sync("invoices", len(data))


def upsert_bills(rows: list[dict]):
    data = []
    for r in rows:
        vendor_ref = r.get("VendorRef", {})
        data.append({
            "id": r.get("Id"),
            "doc_number": r.get("DocNumber"),
            "txn_date": r.get("TxnDate"),
            "due_date": r.get("DueDate"),
            "vendor_id": vendor_ref.get("value"),
            "vendor_name": vendor_ref.get("name"),
            "total_amt": r.get("TotalAmt", 0),
            "balance": r.get("Balance", 0),
            "currency": r.get("CurrencyRef", {}).get("value", "USD"),
        })
    df = pd.DataFrame(data)
    if not df.empty:
        df.to_sql("bills", engine, if_exists="replace", index=False)
    _log_sync("bills", len(data))


def upsert_expenses(rows: list[dict]):
    data = []
    for r in rows:
        entity_ref = r.get("EntityRef", {})
        account_ref = r.get("AccountRef", {})
        data.append({
            "id": r.get("Id"),
            "txn_date": r.get("TxnDate"),
            "payment_type": r.get("PaymentType"),
            "total_amt": r.get("TotalAmt", 0),
            "vendor_id": entity_ref.get("value"),
            "vendor_name": entity_ref.get("name"),
            "account_id": account_ref.get("value"),
            "account_name": account_ref.get("name"),
            "memo": r.get("PrivateNote"),
            "currency": r.get("CurrencyRef", {}).get("value", "USD"),
        })
    df = pd.DataFrame(data)
    if not df.empty:
        df.to_sql("expenses", engine, if_exists="replace", index=False)
    _log_sync("expenses", len(data))


def upsert_payments(rows: list[dict]):
    data = []
    for r in rows:
        customer_ref = r.get("CustomerRef", {})
        data.append({
            "id": r.get("Id"),
            "txn_date": r.get("TxnDate"),
            "customer_id": customer_ref.get("value"),
            "customer_name": customer_ref.get("name"),
            "total_amt": r.get("TotalAmt", 0),
            "unapplied_amt": r.get("UnappliedAmt", 0),
            "currency": r.get("CurrencyRef", {}).get("value", "USD"),
        })
    df = pd.DataFrame(data)
    if not df.empty:
        df.to_sql("payments", engine, if_exists="replace", index=False)
    _log_sync("payments", len(data))


def _log_sync(entity: str, count: int):
    _exec(
        "INSERT INTO sync_log (entity, row_count) VALUES (:entity, :count)",
        {"entity": entity, "count": count},
    )


# ─── Query helpers (used by LLM tools) ───────────────────────────────────────

def run_sql(sql: str) -> pd.DataFrame:
    """Execute a read-only SQL query and return a DataFrame."""
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn)


def get_sync_status() -> pd.DataFrame:
    return run_sql("""
        SELECT entity, MAX(synced_at) as last_sync, row_count
        FROM sync_log
        GROUP BY entity
        ORDER BY entity
    """)


def get_table_summary() -> dict:
    """Return row counts for all tables — used in the LLM system prompt."""
    tables = ["accounts", "customers", "vendors", "invoices", "bills", "expenses", "payments"]
    summary = {}
    for t in tables:
        try:
            df = run_sql(f"SELECT COUNT(*) as n FROM {t}")
            summary[t] = int(df["n"].iloc[0])
        except Exception:
            summary[t] = 0
    return summary
