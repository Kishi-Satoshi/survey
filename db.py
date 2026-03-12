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

FIELDNAMES = [
    "受付日時", "氏名", "電話番号", "メールアドレス", "会社名", "部署名", "役職",
    "A3-2 満足度", "A3-2 感想", "H4-1 満足度", "H4-1 感想", "不具合クイズ", "テクバンへのご要望",
]

_DB_COLS = [
    "submitted_at", "name", "phone", "email", "company", "department", "position",
    "seminar1_rating", "seminar1_comment", "seminar2_rating", "seminar2_comment", "quiz_answer", "request",
]
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
                department TEXT NOT NULL DEFAULT '',
                position TEXT NOT NULL,
                seminar1_rating TEXT NOT NULL DEFAULT '',
                seminar1_comment TEXT NOT NULL DEFAULT '',
                seminar2_rating TEXT NOT NULL DEFAULT '',
                seminar2_comment TEXT NOT NULL DEFAULT '',
                quiz_answer TEXT NOT NULL DEFAULT '',
                request TEXT NOT NULL DEFAULT ''
            )
        """)
        # Migrate existing table: add new columns if they don't exist
        for col in ["department", "seminar1_rating", "seminar1_comment",
                     "seminar2_rating", "seminar2_comment", "quiz_answer", "request"]:
            try:
                conn.run(f"ALTER TABLE responses ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
            except Exception:
                pass  # column already exists
        # Drop old comment column if it exists
        try:
            conn.run("ALTER TABLE responses DROP COLUMN IF EXISTS comment")
        except Exception:
            pass
        # Archive table for soft-deleted responses (30-day retention)
        conn.run("""
            CREATE TABLE IF NOT EXISTS archived_responses (
                id SERIAL PRIMARY KEY,
                original_id INTEGER NOT NULL,
                deleted_at TIMESTAMP NOT NULL DEFAULT NOW(),
                submitted_at TEXT NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT NOT NULL,
                company TEXT NOT NULL DEFAULT '',
                department TEXT NOT NULL DEFAULT '',
                position TEXT NOT NULL,
                seminar1_rating TEXT NOT NULL DEFAULT '',
                seminar1_comment TEXT NOT NULL DEFAULT '',
                seminar2_rating TEXT NOT NULL DEFAULT '',
                seminar2_comment TEXT NOT NULL DEFAULT '',
                quiz_answer TEXT NOT NULL DEFAULT '',
                request TEXT NOT NULL DEFAULT ''
            )
        """)
        # Purge archived responses older than 30 days
        conn.run("DELETE FROM archived_responses WHERE deleted_at < NOW() - INTERVAL '30 days'")
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
            "INSERT INTO responses (submitted_at, name, phone, email, company, department, position,"
            " seminar1_rating, seminar1_comment, seminar2_rating, seminar2_comment, quiz_answer, request)"
            " VALUES (:submitted_at, :name, :phone, :email, :company, :department, :position,"
            " :seminar1_rating, :seminar1_comment, :seminar2_rating, :seminar2_comment, :quiz_answer, :request)",
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
            "SELECT id, submitted_at, name, phone, email, company, department, position,"
            " seminar1_rating, seminar1_comment, seminar2_rating, seminar2_comment, quiz_answer, request"
            " FROM responses ORDER BY id"
        )
        rows = []
        for r in result:
            row = {"id": r[0]}
            row.update({_DB_TO_JP[col]: val for col, val in zip(_DB_COLS, r[1:])})
            rows.append(row)
        return rows
    except Exception:
        return None
    finally:
        conn.close()


def delete_response(response_id):
    """Soft-delete: move a response to the archive table."""
    try:
        conn = _get_conn()
    except Exception:
        return False
    if conn is None:
        return False
    try:
        conn.run(
            "INSERT INTO archived_responses (original_id, submitted_at, name, phone, email,"
            " company, department, position, seminar1_rating, seminar1_comment,"
            " seminar2_rating, seminar2_comment, quiz_answer, request)"
            " SELECT id, submitted_at, name, phone, email, company, department, position,"
            " seminar1_rating, seminar1_comment, seminar2_rating, seminar2_comment, quiz_answer, request"
            " FROM responses WHERE id = :id",
            id=response_id,
        )
        conn.run("DELETE FROM responses WHERE id = :id", id=response_id)
        return True
    except Exception:
        return False
    finally:
        conn.close()


def load_archived():
    """Load archived responses. Returns list of dicts with Japanese keys + id/deleted_at."""
    try:
        conn = _get_conn()
    except Exception:
        return None
    if conn is None:
        return None
    try:
        # Purge old entries first
        conn.run("DELETE FROM archived_responses WHERE deleted_at < NOW() - INTERVAL '30 days'")
        result = conn.run(
            "SELECT id, deleted_at, submitted_at, name, phone, email, company, department,"
            " position, seminar1_rating, seminar1_comment, seminar2_rating,"
            " seminar2_comment, quiz_answer, request"
            " FROM archived_responses ORDER BY deleted_at DESC"
        )
        rows = []
        for r in result:
            row = {"id": r[0], "deleted_at": r[1].strftime("%Y-%m-%d %H:%M") if r[1] else ""}
            row.update({_DB_TO_JP[col]: val for col, val in zip(_DB_COLS, r[2:])})
            rows.append(row)
        return rows
    except Exception:
        return None
    finally:
        conn.close()


def restore_response(archive_id):
    """Restore an archived response back to the responses table."""
    try:
        conn = _get_conn()
    except Exception:
        return False
    if conn is None:
        return False
    try:
        conn.run(
            "INSERT INTO responses (submitted_at, name, phone, email, company, department,"
            " position, seminar1_rating, seminar1_comment, seminar2_rating,"
            " seminar2_comment, quiz_answer, request)"
            " SELECT submitted_at, name, phone, email, company, department, position,"
            " seminar1_rating, seminar1_comment, seminar2_rating, seminar2_comment, quiz_answer, request"
            " FROM archived_responses WHERE id = :id",
            id=archive_id,
        )
        conn.run("DELETE FROM archived_responses WHERE id = :id", id=archive_id)
        return True
    except Exception:
        return False
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
        csv_row = {k: row[k] for k in FIELDNAMES}
        writer.writerow(csv_row)
    return buf.getvalue()
