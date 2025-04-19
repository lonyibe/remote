import os
import json
import uuid
import datetime
from flask import Flask, request, jsonify, send_from_directory, render_template, redirect, url_for, session
from werkzeug.utils import secure_filename
import firebase_admin
from firebase_admin import credentials, auth, db

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 300 * 1024 * 1024  # 300MB limit

# Initialize Firebase Admin SDK
firebase_key_json = json.loads(os.environ["FIREBASE_KEY"])
cred = credentials.Certificate(firebase_key_json)
firebase_admin.initialize_app(cred, {
    'databaseURL': os.environ.get('FIREBASE_DB_URL')
})

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def get_user_storage_used(uid):
    ref = db.reference(f"users/{uid}/files")
    files = ref.get() or {}
    return sum(file.get("size", 0) for file in files.values())

@app.route("/")
def index():
    user_email = session.get("user_email")
    if not user_email:
        return redirect(url_for("login"))

    # Fetch user data
    uid = auth.get_user_by_email(user_email).uid
    total_used = get_user_storage_used(uid)
    total_free = 300 * 1024 * 1024 - total_used
    files = db.reference(f"users/{uid}/files").get() or {}

    return render_template(
        "index.html",
        email=user_email,
        used=total_used / (1024 * 1024),
        files=files
    )

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        try:
            # (In real use you would verify the password via Firebase Auth REST API or client-side SDK)
            user = auth.get_user_by_email(email)
            session["user_email"] = user.email
            return redirect(url_for("index"))
        except Exception as e:
            return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        try:
            # Create the new user in Firebase
            user = auth.create_user(email=email, password=password)
            # Optionally, auto-log them in:
            session["user_email"] = user.email
            return redirect(url_for("index"))
        except Exception as e:
            return render_template("signup.html", error=str(e))
    return render_template("signup.html")

@app.route("/logout")
def logout():
    session.pop("user_email", None)
    return redirect(url_for("login"))

@app.route("/files")
def get_user_files():
    token = request.headers.get("Authorization")
    if not token:
        return jsonify({"error": "Missing token"}), 401
    try:
        uid = auth.verify_id_token(token.split()[1])["uid"]
    except Exception:
        return jsonify({"error": "Invalid token"}), 401

    used = get_user_storage_used(uid)
    remaining = 300 * 1024 * 1024 - used
    raw = db.reference(f"users/{uid}/files").get() or {}

    files = [{"name": f["name"], "url": f["url"], "size": f["size"]} for f in raw.values()]
    return jsonify({
        "storage_used": used,
        "storage_remaining": remaining,
        "files": files
    })

@app.route("/upload", methods=["POST"])
def upload_file():
    token = request.headers.get("Authorization")
    if not token:
        return jsonify({"error": "Missing token"}), 401
    try:
        uid = auth.verify_id_token(token.split()[1])["uid"]
    except Exception:
        return jsonify({"error": "Invalid token"}), 401

    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    filename = secure_filename(file.filename)
    file_id = str(uuid.uuid4())
    full_name = f"{file_id}_{filename}"
    path = os.path.join(app.config['UPLOAD_FOLDER'], full_name)
    file.save(path)

    size = os.path.getsize(path)
    used = get_user_storage_used(uid)
    if used + size > 300 * 1024 * 1024:
        os.remove(path)
        return jsonify({"error": "Storage limit exceeded"}), 400

    url = url_for("download_file", filename=full_name, _external=True)
    share = url_for("share_file", file_id=full_name, _external=True)
    meta = {
        "id": file_id,
        "name": filename,
        "size": size,
        "url": url,
        "share_url": share,
        "uploaded_at": datetime.datetime.utcnow().isoformat()
    }
    db.reference(f"users/{uid}/files/{file_id}").set(meta)
    return jsonify({"message": "File uploaded", "file": meta}), 200

@app.route("/download/<filename>")
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

@app.route("/share/<file_id>")
def share_file(file_id):
    return redirect(url_for("download_file", filename=file_id))

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
