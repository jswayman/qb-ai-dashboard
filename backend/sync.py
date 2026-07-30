"""
Full data sync: pulls all entities from QuickBooks and stores them in SQLite.
Call sync_all() to refresh. Progress is reported via a callback so
Streamlit can display it in real time.
"""

from typing import Callable, Optional

from . import db, qb_client


def sync_all(progress_cb: Optional[Callable[[str], None]] = None) -> dict:
    """
    Sync all supported QB entities to local SQLite.
    Returns a dict of {entity: row_count}.
    """
    db.init_schema()
    results = {}

    steps = [
        ("accounts",  qb_client.get_accounts,  db.upsert_accounts),
        ("customers", qb_client.get_customers, db.upsert_customers),
        ("vendors",   qb_client.get_vendors,   db.upsert_vendors),
        ("invoices",  qb_client.get_invoices,  db.upsert_invoices),
        ("bills",     qb_client.get_bills,     db.upsert_bills),
        ("expenses",  qb_client.get_expenses,  db.upsert_expenses),
        ("payments",  qb_client.get_payments,  db.upsert_payments),
    ]

    for entity, fetch_fn, upsert_fn in steps:
        if progress_cb:
            progress_cb(f"Syncing {entity}...")
        try:
            rows = fetch_fn()
            upsert_fn(rows)
            results[entity] = len(rows)
            if progress_cb:
                progress_cb(f"  ✓ {entity}: {len(rows)} rows")
        except Exception as e:
            results[entity] = f"ERROR: {e}"
            if progress_cb:
                progress_cb(f"  ✗ {entity}: {e}")

    return results
