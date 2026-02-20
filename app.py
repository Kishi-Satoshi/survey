import csv
import os
import secrets
from datetime import datetime

from flask import Flask, abort, redirect, render_template, request, url_for

app = Flask(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CSV_FILE = os.path.join(DATA_DIR, "responses.csv")

FIELDNAMES = ["受付日時", "氏名", "電話番号", "メールアドレス", "会社名", "役職", "セミナー感想"]
REQUIRED_FIELDS = ["name", "phone", "email", "company", "position"]

TOKEN_FILE = os.path.join(DATA_DIR, "admin_token.txt")


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


def ensure_csv():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()


def save_response(data: dict):
    ensure_csv()
    with open(CSV_FILE, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writerow(data)


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
    save_response(row)

    return redirect(url_for("thanks"))


@app.route("/thanks")
def thanks():
    return render_template("thanks.html")


def render_admin(share_url):
    ensure_csv()
    rows = []
    with open(CSV_FILE, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return render_template("admin.html", rows=rows, fieldnames=FIELDNAMES, share_url=share_url)


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


if __name__ == "__main__":
    token = get_or_create_admin_token()
    print(f"\n{'=' * 50}")
    print(f"  管理画面の共有リンク:")
    print(f"  http://localhost:5000/admin/{token}")
    print(f"{'=' * 50}\n")
    app.run(host="0.0.0.0", port=5000, debug=True)
