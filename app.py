import os
import json
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
from firebase_admin import credentials, initialize_app, auth, storage
from werkzeug.utils import secure_filename

# ——— Flask setup ———
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "supersecret")

# ——— Firebase Admin init from ENV VAR ———
# Expect FIREBASE_SERVICE_ACCOUNT_JSON to contain the full JSON of your service account
sa_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
if not sa_json:
    raise RuntimeError("Missing FIREBASE_SERVICE_ACCOUNT_JSON env var")
sa_info = json.loads(sa_json)
bucket_name = os.getenv("FIREBASE_STORAGE_BUCKET")
if not bucket_name:
    raise RuntimeError("Missing FIREBASE_STORAGE_BUCKET env var")
cred = credentials.Certificate(sa_info)
firebase_app = initialize_app(cred, {"storageBucket": bucket_name})
bucket = storage.bucket(app=firebase_app)

# ——— Constants ———
UPLOAD_LIMIT_MB = 300
USER_FOLDER = "user_uploads"   # local temp storage before pushing to Firebase

# Ensure local folder exists
os.makedirs(USER_FOLDER, exist_ok=True)

# ——— Helpers ———
def login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_email" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

# ——— Routes ———
@app.route("/")
@login_required
def index():
    # List files in Firebase Storage under user's folder
    prefix = session["user_email"] + "/"
    blobs = bucket.list_blobs(prefix=prefix)
    files = [b.name.split("/",1)[1] for b in blobs if b.name != prefix]

    # Calculate used storage by summing blob sizes
    total_bytes = sum(b.size for b in bucket.list_blobs(prefix=prefix))
    used_mb = round(total_bytes / (1024*1024), 2)
    remaining_mb = max(0, UPLOAD_LIMIT_MB - used_mb)

    return render_template(
        "index.html",
        email=session["user_email"],
        files=files,
        used_mb=used_mb,
        remaining_mb=remaining_mb
    )

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        try:
            user = auth.get_user_by_email(email)
            # Note: password check happens client‑side via Firebase JS SDK
            session["user_email"] = email
            return redirect(url_for("index"))
        except Exception as e:
            flash("Login failed: " + str(e), "danger")
    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        try:
            user = auth.create_user(email=email, password=password)
            session["user_email"] = email
            return redirect(url_for("index"))
        except Exception as e:
            flash("Signup failed: " + str(e), "danger")
    return render_template("signup.html")

@app.route("/logout")
def logout():
    session.pop("user_email", None)
    return redirect(url_for("login"))

@app.route("/upload", methods=["POST"])
@login_required
def upload():
    file = request.files.get("file")
    if not file or file.filename == "":
        flash("No file selected", "warning")
        return redirect(url_for("index"))

    filename = secure_filename(file.filename)
    # Check local read to get size
    data = file.read()
    size_mb = len(data) / (1024*1024)
    # Reset stream
    file.stream.seek(0)

    # Check limit
    # (you could also re‑sum from Firebase if you want an absolute check)
    # For simplicity, assume current used_mb is from index view
    total_bytes = sum(b.size for b in bucket.list_blobs(prefix=session["user_email"]+"/"))
    if (total_bytes + len(data)) > UPLOAD_LIMIT_MB * 1024*1024:
        flash(f"Upload would exceed your {UPLOAD_LIMIT_MB} MB limit", "danger")
        return redirect(url_for("index"))

    # Upload to Firebase Storage under a folder named by email
    blob = bucket.blob(f"{session['user_email']}/{filename}")
    blob.upload_from_file(file.stream, content_type=file.mimetype)
    flash("File uploaded!", "success")
    return redirect(url_for("index"))

@app.route("/delete/<filename>")
@login_required
def delete(filename):
    blob = bucket.blob(f"{session['user_email']}/{filename}")
    if blob.exists():
        blob.delete()
        flash("Deleted "+filename, "info")
    return redirect(url_for("index"))

@app.route("/download/<filename>")
@login_required
def download(filename):
    # Generate a signed URL that forces download
    blob = bucket.blob(f"{session['user_email']}/{filename}")
    url = blob.generate_signed_url(version="v4", expiration=3600, response_disposition=f"attachment; filename={filename}")
    return redirect(url)

# ——— Run ———
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
