import csv
import io
import os
import secrets
import tempfile
from datetime import datetime
from urllib.parse import urlparse

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, url_for

# --- PostgreSQL (pg8000) ---
try:
    import pg8000.native
    _HAS_PG = True
except Exception:
    _HAS_PG = False

# Vercel serverless: use /tmp for writable storage (CSV fallback)
DATA_DIR = os.path.join(tempfile.gettempdir(), "survey_data")
CSV_FILE = os.path.join(DATA_DIR, "responses.csv")

# Templates are one level up from api/
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")

app = Flask(__name__, template_folder=TEMPLATE_DIR)

FIELDNAMES = ["受付日時", "氏名", "電話番号", "メールアドレス", "会社名", "役職", "セミナー感想"]
REQUIRED_FIELDS = ["name", "phone", "email", "company", "position"]

_DB_COLS = ["submitted_at", "name", "phone", "email", "company", "position", "comment"]
_JP_TO_DB = dict(zip(FIELDNAMES, _DB_COLS))
_DB_TO_JP = dict(zip(_DB_COLS, FIELDNAMES))

TOKEN_FILE = os.path.join(DATA_DIR, "admin_token.txt")


# --- Database helpers ---

def _pg_url():
    return os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL") or ""


def _pg_conn():
    if not _HAS_PG:
        return None
    url = _pg_url()
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


def _init_pg():
    try:
        conn = _pg_conn()
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


_use_pg = _init_pg()


def _pg_save(data: dict):
    try:
        conn = _pg_conn()
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


def _pg_load():
    try:
        conn = _pg_conn()
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


# --- Token ---

def get_or_create_admin_token():
    env_token = os.environ.get("ADMIN_TOKEN")
    if env_token:
        return env_token.strip()
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            return f.read().strip()
    token = secrets.token_urlsafe(32)
    with open(TOKEN_FILE, "w") as f:
        f.write(token)
    return token


# --- CSV fallback ---

def ensure_csv():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()


def save_response_csv(data: dict):
    ensure_csv()
    with open(CSV_FILE, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writerow(data)


def load_responses_csv():
    ensure_csv()
    with open(CSV_FILE, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# --- Routes ---

@app.route("/health")
def health():
    pg_url = _pg_url()
    return jsonify({
        "status": "ok",
        "pg8000_imported": _HAS_PG,
        "postgres_url_set": bool(pg_url),
        "postgres_connected": _use_pg,
    })


@app.route("/")
def index():
    return render_template("form.html", errors={}, values={})


@app.route("/submit", methods=["POST"])
def submit():
    values = {
        "name": request.form.get("name", "").strip(),
        "phone": request.form.get("phone", "").strip(),
        "email": request.form.get("email", "").strip(),
        "company": request.form.get("company", "").strip(),
        "position": request.form.get("position", "").strip(),
        "comment": request.form.get("comment", "").strip(),
    }

    errors = {}
    for field in REQUIRED_FIELDS:
        if not values[field]:
            errors[field] = "この項目は必須です。"

    if errors:
        return render_template("form.html", errors=errors, values=values)

    row = {
        "受付日時": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "氏名": values["name"],
        "電話番号": values["phone"],
        "メールアドレス": values["email"],
        "会社名": values["company"],
        "役職": values["position"],
        "セミナー感想": values["comment"],
    }

    if _use_pg:
        _pg_save(row)
    else:
        save_response_csv(row)

    return redirect(url_for("thanks"))


@app.route("/thanks")
def thanks():
    return render_template("thanks.html")


def render_admin(share_url):
    if _use_pg:
        rows = _pg_load() or []
    else:
        rows = load_responses_csv()
    csv_url = share_url.rstrip("/") + "/csv" if share_url else None
    return render_template("admin.html", rows=rows, fieldnames=FIELDNAMES, share_url=share_url, csv_url=csv_url)


@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        token = request.form.get("token", "").strip()
        if token == get_or_create_admin_token():
            return render_admin(request.host_url.rstrip("/") + "/admin/" + token)
        return render_template("login.html", error="トークンが正しくありません。"), 403
    return render_template("login.html", error=None)


@app.route("/admin/<token>")
def admin(token):
    if token != get_or_create_admin_token():
        return abort(403)
    return render_admin(request.url)


@app.route("/admin/<token>/csv")
def admin_csv(token):
    if token != get_or_create_admin_token():
        return abort(403)

    if _use_pg:
        rows = _pg_load() or []
    else:
        rows = load_responses_csv()

    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.DictWriter(buf, fieldnames=FIELDNAMES)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=responses.csv"},
    )
