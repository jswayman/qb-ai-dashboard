"""
Pre-built SQL query functions for the QB AI Dashboard.

These functions are intentionally free of litellm / LLM dependencies so the
dashboard charts can load without requiring the AI backend to be healthy.
They are also registered as LLM tool implementations in llm_agent.py.
"""

import datetime
from typing import Optional

import pandas as pd

from . import db


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


def _tool_get_invoices_for_period(start_date: str, end_date: str, limit: int = 100) -> dict:
    """Return invoices for a specific date range, newest first."""
    try:
        df = db.run_sql(f"""
            SELECT doc_number, txn_date, due_date, customer_name, total_amt, balance, status
            FROM invoices
            WHERE txn_date BETWEEN '{start_date}' AND '{end_date}'
            ORDER BY txn_date DESC
            LIMIT {limit}
        """)
        return {"data": df.to_dict(orient="records")}
    except Exception as e:
        return {"error": str(e)}


def _tool_get_expenses_for_period(start_date: str, end_date: str, limit: int = 100) -> dict:
    """Return expenses for a specific date range, newest first."""
    try:
        df = db.run_sql(f"""
            SELECT txn_date, vendor_name, account_name, total_amt
            FROM expenses
            WHERE txn_date BETWEEN '{start_date}' AND '{end_date}'
            ORDER BY txn_date DESC
            LIMIT {limit}
        """)
        return {"data": df.to_dict(orient="records")}
    except Exception as e:
        return {"error": str(e)}


def _tool_get_invoice_aging() -> dict:
    """Return AR aging buckets for open invoices."""
    try:
        df = db.run_sql("""
            SELECT
                CASE
                    WHEN julianday(due_date) >= julianday('now') THEN 'Current'
                    WHEN julianday('now') - julianday(due_date) <= 30 THEN '1-30 Days'
                    WHEN julianday('now') - julianday(due_date) <= 60 THEN '31-60 Days'
                    WHEN julianday('now') - julianday(due_date) <= 90 THEN '61-90 Days'
                    ELSE '90+ Days'
                END as bucket,
                COUNT(*) as count,
                COALESCE(SUM(balance), 0) as total_balance
            FROM invoices
            WHERE status = 'open'
            GROUP BY bucket
        """)
        return {"data": df.to_dict(orient="records")}
    except Exception as e:
        return {"error": str(e)}


def _tool_get_top_customers_for_period(start_date: str, end_date: str, limit: int = 10) -> dict:
    """Return top customers by revenue for a specific date range."""
    try:
        df = db.run_sql(f"""
            SELECT customer_name as customer,
                   COUNT(*) as invoice_count,
                   SUM(total_amt) as total_invoiced
            FROM invoices
            WHERE txn_date BETWEEN '{start_date}' AND '{end_date}'
              AND customer_name IS NOT NULL
            GROUP BY customer_name
            ORDER BY total_invoiced DESC
            LIMIT {limit}
        """)
        return {"data": df.to_dict(orient="records")}
    except Exception as e:
        return {"error": str(e)}


def _tool_get_kpi_summary_ranged(start_date: str, end_date: str) -> dict:
    """Get KPI metrics filtered to a specific date range (YYYY-MM-DD strings)."""
    try:
        revenue = db.run_sql(f"""
            SELECT COALESCE(SUM(total_amt), 0) as v FROM invoices
            WHERE txn_date BETWEEN '{start_date}' AND '{end_date}'
        """)["v"].iloc[0]

        expenses = db.run_sql(f"""
            SELECT COALESCE(SUM(total_amt), 0) as v FROM expenses
            WHERE txn_date BETWEEN '{start_date}' AND '{end_date}'
        """)["v"].iloc[0]

        open_invoices = db.run_sql(f"""
            SELECT COUNT(*) as v FROM invoices
            WHERE status = 'open' AND txn_date BETWEEN '{start_date}' AND '{end_date}'
        """)["v"].iloc[0]

        overdue_bills = db.run_sql(f"""
            SELECT COUNT(*) as v FROM bills
            WHERE balance > 0 AND due_date < date('now')
            AND txn_date BETWEEN '{start_date}' AND '{end_date}'
        """)["v"].iloc[0]

        return {
            "total_revenue":  float(revenue),
            "total_expenses": float(expenses),
            "net_income":     float(revenue) - float(expenses),
            "open_invoices":  int(open_invoices),
            "overdue_bills":  int(overdue_bills),
        }
    except Exception as e:
        return {"error": str(e)}
