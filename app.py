import csv
import os
from datetime import datetime

from flask import Flask, redirect, render_template, request, url_for

app = Flask(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CSV_FILE = os.path.join(DATA_DIR, "responses.csv")

FIELDNAMES = ["受付日時", "氏名", "電話番号", "メールアドレス", "会社名", "役職", "セミナー感想"]
REQUIRED_FIELDS = ["name", "phone", "email", "company", "position"]


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


@app.route("/admin")
def admin():
    ensure_csv()
    rows = []
    with open(CSV_FILE, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return render_template("admin.html", rows=rows, fieldnames=FIELDNAMES)


if __name__ == "__main__":
    app.run(debug=True)
