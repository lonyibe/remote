import os
import base64
import requests
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_file
from werkzeug.utils import secure_filename
from firebase_admin import credentials, initialize_app, auth, db
from io import BytesIO

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.urandom(24)

# Firebase Admin SDK initialization
cred = credentials.Certificate("firebase_key.json")
initialize_app(cred, {
    "databaseURL": "https://storage-9f5d9-default-rtdb.firebaseio.com/"
})

# Constants
MAX_STORAGE_MB = 300
IMGUR_CLIENT_ID = os.getenv("IMGUR_CLIENT_ID")

@app.route("/")
def index():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")

@app.route("/signup")
def signup():
    return render_template("signup.html")

@app.route("/login")
def login():
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("index"))

@app.route("/setuser", methods=["POST"])
def set_user():
    data = request.get_json()
    email = data.get("email")
    uid = data.get("uid")

    if not email or not uid:
        return jsonify({"error": "Email and UID are required"}), 400

    try:
        user_ref = db.reference("users").child(uid)
        user_ref.set({"email": email})
        return jsonify({"message": "User saved successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/session", methods=["POST"])
def set_session():
    data = request.get_json()
    session["user"] = data
    return jsonify({"message": "Session set"}), 200

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    uid = session["user"]["uid"]
    files_ref = db.reference("files").child(uid)
    files = files_ref.get() or {}

    total_size = sum(file["size"] for file in files.values())
    remaining = MAX_STORAGE_MB * 1024 * 1024 - total_size

    return render_template("dashboard.html", files=files, used=total_size, remaining=remaining)

@app.route("/upload", methods=["POST"])
def upload():
    if "user" not in session:
        return redirect(url_for("login"))

    file = request.files["file"]
    if not file:
        return "No file uploaded", 400

    uid = session["user"]["uid"]
    files_ref = db.reference("files").child(uid)
    files = files_ref.get() or {}

    total_size = sum(f["size"] for f in files.values())
    if total_size + len(file.read()) > MAX_STORAGE_MB * 1024 * 1024:
        return "Storage limit exceeded", 400
    file.seek(0)

    headers = {"Authorization": f"Client-ID {IMGUR_CLIENT_ID}"}
    encoded_image = base64.b64encode(file.read()).decode("utf-8")
    data = {"image": encoded_image, "type": "base64", "name": secure_filename(file.filename)}

    res = requests.post("https://api.imgur.com/3/image", headers=headers, data=data)
    if res.status_code != 200:
        return "Imgur upload failed", 500

    file_url = res.json()["data"]["link"]
    file_size = res.json()["data"]["size"]

    files_ref.child(secure_filename(file.filename)).set({
        "url": file_url,
        "size": file_size
    })

    return redirect(url_for("dashboard"))

@app.route("/download/<filename>")
def download(filename):
    if "user" not in session:
        return redirect(url_for("login"))

    uid = session["user"]["uid"]
    file_ref = db.reference("files").child(uid).child(filename)
    file_data = file_ref.get()

    if not file_data:
        return "File not found", 404

    file_url = file_data["url"]
    res = requests.get(file_url)
    return send_file(BytesIO(res.content), as_attachment=True, download_name=filename)

@app.route("/delete/<filename>")
def delete_file(filename):
    if "user" not in session:
        return redirect(url_for("login"))

    uid = session["user"]["uid"]
    db.reference("files").child(uid).child(filename).delete()
    return redirect(url_for("dashboard"))

# Run the app
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
