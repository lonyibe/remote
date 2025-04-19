import os
import io
import base64
import requests
from flask import Flask, render_template, request, redirect, session, url_for, jsonify
from werkzeug.utils import secure_filename
import firebase_admin
from firebase_admin import credentials, auth, db
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Firebase Setup
cred = credentials.Certificate("firebase-admin.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': os.environ.get("FIREBASE_DB_URL")
})

IMGUR_CLIENT_ID = os.environ.get("IMGUR_CLIENT_ID")
MAX_STORAGE_BYTES = 300 * 1024 * 1024  # 300MB

# Auth Decorator
def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapped

@app.route("/")
@login_required
def index():
    user_email = session["user"]
    ref = db.reference(f"users/{user_email.replace('.', '_')}/files")
    files = ref.get() or {}

    total_size = sum(file['size'] for file in files.values())
    remaining = MAX_STORAGE_BYTES - total_size

    return render_template("index.html", files=files, used=total_size, remaining=remaining)

@app.route("/upload", methods=["POST"])
@login_required
def upload():
    file = request.files["file"]
    if not file:
        return "No file selected", 400

    filename = secure_filename(file.filename)
    file_bytes = file.read()

    # Size Check
    user_email = session["user"]
    ref = db.reference(f"users/{user_email.replace('.', '_')}/files")
    files = ref.get() or {}
    total_size = sum(f["size"] for f in files.values())

    if total_size + len(file_bytes) > MAX_STORAGE_BYTES:
        return "Upload exceeds 300MB quota.", 403

    # Upload to Imgur
    imgur_response = requests.post(
        "https://api.imgur.com/3/upload",
        headers={"Authorization": f"Client-ID {IMGUR_CLIENT_ID}"},
        data={
            "image": base64.b64encode(file_bytes),
            "type": "base64",
            "name": filename,
            "title": filename
        }
    )

    imgur_data = imgur_response.json()
    if not imgur_data.get("success"):
        return "Imgur upload failed", 500

    file_url = imgur_data["data"]["link"]
    ref.child(filename).set({
        "name": filename,
        "url": file_url,
        "size": len(file_bytes)
    })

    return redirect(url_for("index"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        try:
            user = auth.get_user_by_email(email)
            session["user"] = email
            return redirect(url_for("index"))
        except Exception as e:
            return render_template("login.html", error="Login failed")
    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        try:
            auth.create_user(email=email, password=password)
            return redirect(url_for("login"))
        except Exception as e:
            return render_template("signup.html", error="Signup failed")
    return render_template("signup.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

@app.route("/delete/<filename>", methods=["POST"])
@login_required
def delete_file(filename):
    user_email = session["user"]
    ref = db.reference(f"users/{user_email.replace('.', '_')}/files/{filename}")
    ref.delete()
    return redirect(url_for("index"))

# Run the app
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
