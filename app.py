import os
import json
import uuid
import datetime
from flask import Flask, request, jsonify, send_from_directory, render_template, redirect, url_for, session
from werkzeug.utils import secure_filename
import firebase_admin
from firebase_admin import credentials, auth, db

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Session key for session management
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 300 * 1024 * 1024  # 300MB limit

# Initialize Firebase using credentials from environment variable
firebase_key_json = json.loads(os.environ["FIREBASE_KEY"])
cred = credentials.Certificate(firebase_key_json)
firebase_admin.initialize_app(cred, {
    'databaseURL': os.environ.get('FIREBASE_DB_URL')  # make sure to set this in Render too
})

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Utility function to get total used space by a user
def get_user_storage_used(uid):
    ref = db.reference(f"users/{uid}/files")
    files = ref.get() or {}
    total = sum(file.get("size", 0) for file in files.values())
    return total

# Route for displaying the index page (home page after login)
@app.route("/")
def index():
    user_email = session.get("user_email")
    if user_email:
        # Check if the user is logged in and fetch storage data
        uid = auth.get_user_by_email(user_email).uid
        total_used = get_user_storage_used(uid)
        total_free = 300 * 1024 * 1024 - total_used  # 300MB limit
        files_ref = db.reference(f"users/{uid}/files")
        files = files_ref.get() or {}
        return render_template("index.html", email=user_email, used=total_used / (1024 * 1024), files=files)
    else:
        return redirect(url_for("login"))  # Redirect to login if not logged in

# Route for getting user's file data (used storage and files)
@app.route("/files")
def get_user_files():
    token = request.headers.get('Authorization')
    if not token:
        return jsonify({"error": "Missing token"}), 401
    try:
        decoded_token = auth.verify_id_token(token.split(" ")[1])  # Extract token from 'Bearer <token>'
        uid = decoded_token["uid"]
    except Exception:
        return jsonify({"error": "Invalid token"}), 401

    # Get used storage and file data
    used_storage = get_user_storage_used(uid)
    total_storage = 300 * 1024 * 1024  # 300MB limit
    remaining_storage = total_storage - used_storage

    files_ref = db.reference(f"users/{uid}/files")
    files = files_ref.get() or {}

    file_data = []
    for file_id, file_info in files.items():
        file_data.append({
            "name": file_info["name"],
            "url": file_info["url"],
            "size": file_info["size"]
        })

    return jsonify({
        "storage_used": used_storage,
        "storage_remaining": remaining_storage,
        "files": file_data
    })

# Route for uploading a file
@app.route("/upload", methods=["POST"])
def upload_file():
    token = request.headers.get("Authorization")
    if not token:
        return jsonify({"error": "Missing token"}), 401
    try:
        decoded_token = auth.verify_id_token(token.split(" ")[1])  # Extract token from 'Bearer <token>'
        uid = decoded_token["uid"]
    except Exception:
        return jsonify({"error": "Invalid token"}), 401

    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    filename = secure_filename(file.filename)
    file_id = str(uuid.uuid4())
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], file_id + "_" + filename)
    file.save(filepath)

    filesize = os.path.getsize(filepath)
    used = get_user_storage_used(uid)
    if used + filesize > 300 * 1024 * 1024:
        os.remove(filepath)
        return jsonify({"error": "Storage limit exceeded"}), 400

    file_url = url_for("download_file", filename=file_id + "_" + filename, _external=True)
    share_url = url_for("share_file", file_id=file_id + "_" + filename, _external=True)

    file_meta = {
        "id": file_id,
        "name": filename,
        "size": filesize,
        "url": file_url,
        "share_url": share_url,
        "uploaded_at": datetime.datetime.now().isoformat()
    }

    ref = db.reference(f"users/{uid}/files/{file_id}")
    ref.set(file_meta)

    return jsonify({"message": "File uploaded successfully", "file": file_meta}), 200

# Route for downloading a file
@app.route("/download/<filename>")
def download_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=True)

# Route for sharing a file via a link
@app.route("/share/<file_id>")
def share_file(file_id):
    return redirect(url_for("download_file", filename=file_id))

# Route for logging out
@app.route("/logout")
def logout():
    session.pop("user_email", None)
    return redirect(url_for("login"))

# Run the app
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
