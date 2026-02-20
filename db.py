"""Persistent storage using PostgreSQL.

When POSTGRES_URL is set, data is stored in PostgreSQL (Vercel Postgres / Neon).
Otherwise falls back to local CSV storage.
"""

import csv
import io
import os

import psycopg2
import psycopg2.extras

FIELDNAMES = ["受付日時", "氏名", "電話番号", "メールアドレス", "会社名", "役職", "セミナー感想"]

# Column mapping: Japanese display name -> DB column name
_DB_COLUMNS = {
    "受付日時": "submitted_at",
    "氏名": "name",
    "電話番号": "phone",
    "メールアドレス": "email",
    "会社名": "company",
    "役職": "position",
    "セミナー感想": "comment",
}
_DB_TO_JP = {v: k for k, v in _DB_COLUMNS.items()}


def _get_conn():
    url = os.environ.get("POSTGRES_URL", "")
    if not url:
        return None
    return psycopg2.connect(url, sslmode="require")


def init_db():
    conn = _get_conn()
    if conn is None:
        return False
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
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
    finally:
        conn.close()


def save_response(data: dict):
    """Save a survey response. data keys are Japanese field names."""
    conn = _get_conn()
    if conn is None:
        return False
    try:
        row = {_DB_COLUMNS[k]: v for k, v in data.items()}
        with conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO responses (submitted_at, name, phone, email, company, position, comment)
                   VALUES (%(submitted_at)s, %(name)s, %(phone)s, %(email)s, %(company)s, %(position)s, %(comment)s)""",
                row,
            )
        return True
    finally:
        conn.close()


def load_responses():
    """Load all responses. Returns list of dicts with Japanese keys."""
    conn = _get_conn()
    if conn is None:
        return None
    try:
        with conn, conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                "SELECT submitted_at, name, phone, email, company, position, comment FROM responses ORDER BY id"
            )
            rows = []
            for r in cur.fetchall():
                rows.append({_DB_TO_JP[col]: r[col] for col in _DB_COLUMNS.values()})
            return rows
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
