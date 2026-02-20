import csv
import io
import os
import secrets
import sys
import tempfile
from datetime import datetime

from flask import Flask, Response, abort, redirect, render_template, request, url_for

# Make project root importable so we can use shared db module
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import db

# Vercel serverless: use /tmp for writable storage (CSV fallback)
DATA_DIR = os.path.join(tempfile.gettempdir(), "survey_data")
CSV_FILE = os.path.join(DATA_DIR, "responses.csv")

# Templates are one level up from api/
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")

app = Flask(__name__, template_folder=TEMPLATE_DIR)

FIELDNAMES = db.FIELDNAMES
REQUIRED_FIELDS = ["name", "phone", "email", "company", "position"]

TOKEN_FILE = os.path.join(DATA_DIR, "admin_token.txt")

# Try to initialise Postgres on startup; remember whether it's available
_use_pg = db.init_db()


def get_or_create_admin_token():
    # Prefer environment variable so token survives Vercel cold starts
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


# --- CSV fallback helpers (used only when POSTGRES_URL is not set) ---

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
        db.save_response(row)
    else:
        save_response_csv(row)

    return redirect(url_for("thanks"))


@app.route("/thanks")
def thanks():
    return render_template("thanks.html")


def render_admin(share_url):
    if _use_pg:
        rows = db.load_responses() or []
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
        csv_data = db.responses_to_csv_string() or ""
    else:
        ensure_csv()
        buf = io.StringIO()
        buf.write("\ufeff")  # BOM for Excel
        writer = csv.DictWriter(buf, fieldnames=FIELDNAMES)
        writer.writeheader()
        with open(CSV_FILE, "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                writer.writerow(row)
        csv_data = buf.getvalue()

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=responses.csv"},
    )
