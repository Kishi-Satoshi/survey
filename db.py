"""Persistent storage using PostgreSQL.

When POSTGRES_URL (or DATABASE_URL) is set, data is stored in PostgreSQL.
Otherwise falls back to local CSV storage.
"""

import csv
import io
import os
from urllib.parse import urlparse

try:
    import pg8000.native
except ImportError:
    pg8000 = None

FIELDNAMES = ["受付日時", "氏名", "電話番号", "メールアドレス", "会社名", "役職", "セミナー感想"]

_DB_COLS = ["submitted_at", "name", "phone", "email", "company", "position", "comment"]
_JP_TO_DB = dict(zip(FIELDNAMES, _DB_COLS))
_DB_TO_JP = dict(zip(_DB_COLS, FIELDNAMES))


def _get_url():
    return os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL") or ""


def _get_conn():
    if pg8000 is None:
        return None
    url = _get_url()
    if not url:
        return None
    p = urlparse(url)
    return pg8000.native.Connection(
        user=p.username,
        password=p.password,
        host=p.hostname,
        port=p.port or 5432,
        database=p.path.lstrip("/"),
        ssl_context=True,
    )


def init_db():
    try:
        conn = _get_conn()
    except Exception:
        return False
    if conn is None:
        return False
    try:
        conn.run("""
            CREATE TABLE IF NOT EXISTS responses (
                id SERIAL PRIMARY KEY,
                submitted_at TEXT NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT NOT NULL,
                company TEXT NOT NULL,
                position TEXT NOT NULL,
                comment TEXT NOT NULL DEFAULT ''
            )
        """)
        return True
    except Exception:
        return False
    finally:
        conn.close()


def save_response(data: dict):
    """Save a survey response. data keys are Japanese field names."""
    try:
        conn = _get_conn()
    except Exception:
        return False
    if conn is None:
        return False
    try:
        row = {_JP_TO_DB[k]: v for k, v in data.items()}
        conn.run(
            "INSERT INTO responses (submitted_at, name, phone, email, company, position, comment)"
            " VALUES (:submitted_at, :name, :phone, :email, :company, :position, :comment)",
            **row,
        )
        return True
    except Exception:
        return False
    finally:
        conn.close()


def load_responses():
    """Load all responses. Returns list of dicts with Japanese keys, or None on failure."""
    try:
        conn = _get_conn()
    except Exception:
        return None
    if conn is None:
        return None
    try:
        result = conn.run(
            "SELECT submitted_at, name, phone, email, company, position, comment"
            " FROM responses ORDER BY id"
        )
        rows = []
        for r in result:
            rows.append({_DB_TO_JP[col]: val for col, val in zip(_DB_COLS, r)})
        return rows
    except Exception:
        return None
    finally:
        conn.close()


def responses_to_csv_string():
    """Return all responses as a BOM-prefixed CSV string."""
    rows = load_responses()
    if rows is None:
        return None
    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.DictWriter(buf, fieldnames=FIELDNAMES)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()
