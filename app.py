import os
import json
import uuid
import datetime
from flask import (
    Flask, request, jsonify,
    send_from_directory, render_template,
    redirect, url_for
)
from werkzeug.utils import secure_filename
import firebase_admin
from firebase_admin import credentials, auth, db

app = Flask(__name__)

# 300 MB upload limit
app.config['UPLOAD_FOLDER']      = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 300 * 1024 * 1024

# Initialize Firebase Admin from JSON in env var
firebase_key_json = json.loads(os.environ["FIREBASE_KEY"])
cred = credentials.Certificate(firebase_key_json)
firebase_admin.initialize_app(cred, {
    'databaseURL': os.environ["FIREBASE_DB_URL"]
})

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


def get_user_storage_used(uid):
    ref   = db.reference(f"users/{uid}/files")
    files = ref.get() or {}
    return sum(f.get("size", 0) for f in files.values())


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/login")
def login():
    return render_template("login.html")


@app.route("/signup")
def signup():
    return render_template("signup.html")


@app.route("/files")
def get_user_files():
    try:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return jsonify(error="Missing or malformed Authorization header"), 401

        token = auth_header.split()[1]
        decoded = auth.verify_id_token(token)
        uid = decoded["uid"]

        used = get_user_storage_used(uid)
        remaining = (300 * 1024 * 1024) - used
        raw = db.reference(f"users/{uid}/files").get() or {}

        files = [
            {"name": f["name"], "url": f["url"], "size": f["size"]}
            for f in raw.values()
        ]
        return jsonify(
            storage_used=used,
            storage_remaining=remaining,
            files=files
        )
    except Exception as e:
        app.logger.error("Error in /files", exc_info=True)
        return jsonify(error="Internal server error fetching files"), 500


@app.route("/upload", methods=["POST"])
def upload_file():
    try:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return jsonify(error="Missing or malformed Authorization header"), 401

        token = auth_header.split()[1]
        decoded = auth.verify_id_token(token)
        uid = decoded["uid"]

        if 'file' not in request.files:
            return jsonify(error="No file part"), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify(error="No selected file"), 400

        filename = secure_filename(file.filename)
        file_id = str(uuid.uuid4())
        saved_name = f"{file_id}_{filename}"
        path = os.path.join(app.config['UPLOAD_FOLDER'], saved_name)
        file.save(path)

        size = os.path.getsize(path)
        used = get_user_storage_used(uid)
        if used + size > 300 * 1024 * 1024:
            os.remove(path)
            return jsonify(error="Storage limit exceeded"), 400

        download_url = url_for("download_file", filename=saved_name, _external=True)
        share_url    = url_for("share_file",   file_id=saved_name,  _external=True)
        meta = {
            "id":           file_id,
            "name":         filename,
            "size":         size,
            "url":          download_url,
            "share_url":    share_url,
            "uploaded_at":  datetime.datetime.utcnow().isoformat()
        }
        db.reference(f"users/{uid}/files/{file_id}").set(meta)

        return jsonify(message="File uploaded", file=meta), 200

    except Exception as e:
        app.logger.error("Error in /upload", exc_info=True)
        return jsonify(error="Internal server error uploading file"), 500


@app.route("/download/<filename>")
def download_file(filename):
    return send_from_directory(
        app.config['UPLOAD_FOLDER'],
        filename,
        as_attachment=True
    )


@app.route("/share/<file_id>")
def share_file(file_id):
    return redirect(url_for("download_file", filename=file_id))


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
