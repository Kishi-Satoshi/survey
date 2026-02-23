import csv
import html
import io
import os
import secrets
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import Flask, Response, abort, redirect, render_template, request, url_for

import db

app = Flask(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CSV_FILE = os.path.join(DATA_DIR, "responses.csv")

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


# --- Email ---

def send_confirmation_email(to_email: str, values: dict, submitted_at: str) -> bool:
    """アンケート回答者に回答内容を送信する。SMTP設定が未定義の場合は何もしない。"""
    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    smtp_from = os.environ.get("SMTP_FROM", smtp_user)

    if not all([smtp_host, smtp_user, smtp_password]):
        return False  # SMTP未設定の場合はスキップ

    name = values["name"]
    phone = values["phone"]
    email_addr = values["email"]
    company = values["company"]
    position = values["position"]
    comment = values["comment"] or "（なし）"

    # プレーンテキスト本文
    text_body = (
        f"{name} 様\n\n"
        "このたびはアンケートにご回答いただきありがとうございました。\n"
        "以下の内容で受け付けました。\n\n"
        f"■ 受付日時　　: {submitted_at}\n"
        f"■ 氏名　　　　: {name}\n"
        f"■ 電話番号　　: {phone}\n"
        f"■ メールアドレス: {email_addr}\n"
        f"■ 会社名　　　: {company}\n"
        f"■ 役職　　　　: {position}\n"
        f"■ セミナー感想: {comment}\n\n"
        "今後のセミナーの参考にさせていただきます。\n"
        "引き続きよろしくお願いいたします。\n"
    )

    # HTML本文（ユーザー入力はエスケープ）
    def e(s: str) -> str:
        return html.escape(s)

    td_label = 'style="padding:8px 12px;border:1px solid #dee2e6;font-weight:bold;white-space:nowrap;"'
    td_value = 'style="padding:8px 12px;border:1px solid #dee2e6;"'
    tr_odd = 'style="background:#f8f9fa;"'

    html_body = f"""<!DOCTYPE html>
<html lang="ja">
<head><meta charset="UTF-8"></head>
<body style="font-family:sans-serif;color:#333;max-width:600px;margin:0 auto;padding:20px;">
  <h2 style="color:#0d6efd;">アンケートご回答ありがとうございました</h2>
  <p>{e(name)} 様</p>
  <p>このたびはアンケートにご回答いただきありがとうございました。<br>
     以下の内容で受け付けました。</p>
  <table style="border-collapse:collapse;width:100%;margin:20px 0;">
    <tr {tr_odd}><td {td_label}>受付日時</td><td {td_value}>{e(submitted_at)}</td></tr>
    <tr><td {td_label}>氏名</td><td {td_value}>{e(name)}</td></tr>
    <tr {tr_odd}><td {td_label}>電話番号</td><td {td_value}>{e(phone)}</td></tr>
    <tr><td {td_label}>メールアドレス</td><td {td_value}>{e(email_addr)}</td></tr>
    <tr {tr_odd}><td {td_label}>会社名</td><td {td_value}>{e(company)}</td></tr>
    <tr><td {td_label}>役職</td><td {td_value}>{e(position)}</td></tr>
    <tr {tr_odd}><td {td_label}>セミナー感想</td><td {td_value}>{e(comment)}</td></tr>
  </table>
  <p>今後のセミナーの参考にさせていただきます。<br>引き続きよろしくお願いいたします。</p>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "アンケートご回答ありがとうございました"
    msg["From"] = smtp_from
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_from, to_email, msg.as_string())
        return True
    except Exception:
        return False  # メール送信失敗でもフォーム送信は成功扱い


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

    send_confirmation_email(values["email"], values, row["受付日時"])

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


if __name__ == "__main__":
    token = get_or_create_admin_token()
    print(f"\n{'=' * 50}")
    print(f"  管理画面の共有リンク:")
    print(f"  http://localhost:5000/admin/{token}")
    if _use_pg:
        print(f"  ストレージ: PostgreSQL")
    else:
        print(f"  ストレージ: CSV (ローカル)")
    print(f"{'=' * 50}\n")
    app.run(host="0.0.0.0", port=5000, debug=True)
