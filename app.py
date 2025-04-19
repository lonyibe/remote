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
from firebase_admin import credentials, auth, db, exceptions as fb_exceptions

app = Flask(__name__)

# 300 MB upload limit
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 300 * 1024 * 1024

# Load Firebase credentials from environment variable (JSON string)
# Ensure FIREBASE_KEY and FIREBASE_DB_URL environment variables are set
try:
    firebase_key_json = json.loads(os.environ["FIREBASE_KEY"])
    cred = credentials.Certificate(firebase_key_json)
    firebase_admin.initialize_app(cred, {
        'databaseURL': os.environ["FIREBASE_DB_URL"]
    })
except KeyError as e:
    print(f"ERROR: Missing environment variable {e}. Please set FIREBASE_KEY and FIREBASE_DB_URL.")
    exit(1)
except json.JSONDecodeError:
    print("ERROR: Could not decode FIREBASE_KEY JSON. Ensure it's a valid JSON string.")
    exit(1)
except Exception as e:
    print(f"ERROR: Failed to initialize Firebase: {e}")
    exit(1)


# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- Helper Functions ---
def get_user_storage_used(uid):
    """Calculate user's used storage."""
    ref = db.reference(f"users/{uid}/files")
    try:
        files = ref.get() or {}
    except fb_exceptions.FirebaseError as e:
        app.logger.error(f"Firebase error getting storage for {uid}: {e}")
        return 0 # Assume 0 if DB error occurs
    return sum(f.get("size", 0) for f in files.values())

def get_file_ref(uid, file_id):
    """Get Firebase reference for a specific file."""
    return db.reference(f"users/{uid}/files/{file_id}")

def verify_auth_token(request):
    """Verifies Firebase ID token from Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return None, (jsonify(error="Missing or malformed Authorization header"), 401)
    token = auth_header.split(" ", 1)[1]
    try:
        decoded_token = auth.verify_id_token(token)
        return decoded_token, None
    except auth.InvalidIdTokenError as e:
        app.logger.warning(f"Invalid ID Token: {e}")
        return None, (jsonify(error="Invalid or expired token"), 401)
    except Exception as e:
        app.logger.error(f"Token verification error: {e}", exc_info=True)
        return None, (jsonify(error="Token verification failed"), 401)

# --- Routes ---

@app.route("/")
def index():
    """Serves the main file manager page."""
    return render_template("index.html")

@app.route("/login")
def login():
    """Serves the login page."""
    return render_template("login.html")

@app.route("/signup")
def signup():
    """Serves the signup page."""
    return render_template("signup.html")

@app.route("/files")
def get_user_files():
    """Gets metadata for all files owned by the authenticated user."""
    decoded_token, error_response = verify_auth_token(request)
    if error_response:
        return error_response

    uid = decoded_token["uid"]
    try:
        used = get_user_storage_used(uid)
        remaining = max(0, (app.config['MAX_CONTENT_LENGTH']) - used) # Ensure remaining is not negative

        ref = db.reference(f"users/{uid}/files")
        raw_files = ref.get() or {}

        # Prepare file list including file_id and share_url
        files = []
        for file_id, meta in raw_files.items():
             # Ensure saved_name is generated correctly or stored if different from file_id
             # Assuming saved_name is constructed as {file_id}_{original_filename}
             # If not, you might need to store 'saved_name' in metadata during upload
            original_filename = meta.get("name", "unknown_file")
            saved_name = f"{file_id}_{secure_filename(original_filename)}" # Reconstruct or retrieve from meta if stored
            download_url = url_for("download_file", filename=saved_name, _external=True)
            share_url = url_for("share_file", file_id=saved_name, _external=True) # Use the unique name for sharing

            files.append({
                "id": file_id, # The unique ID from Firebase key
                "name": meta.get("name", "Unnamed File"),
                "url": download_url, # Direct download URL
                "share_url": share_url, # Shareable link URL
                "size": meta.get("size", 0),
                "saved_name": saved_name # Needed for delete on filesystem
            })

        return jsonify(
            storage_used=used,
            storage_remaining=remaining,
            files=files
        )

    except fb_exceptions.FirebaseError as e:
         app.logger.error(f"Firebase error fetching files for {uid}: {e}", exc_info=True)
         return jsonify(error="Database error fetching files"), 500
    except Exception as e:
        app.logger.error(f"Error in /files for {uid}: {e}", exc_info=True)
        return jsonify(error="Internal server error fetching files"), 500


@app.route("/upload", methods=["POST"])
def upload_file():
    """Handles file uploads for authenticated users."""
    decoded_token, error_response = verify_auth_token(request)
    if error_response:
        return error_response

    uid = decoded_token["uid"]

    if 'file' not in request.files:
        return jsonify(error="No file part"), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify(error="No selected file"), 400

    try:
        filename = secure_filename(file.filename)
        file_id = str(uuid.uuid4()) # Unique ID for this file upload
        saved_name = f"{file_id}_{filename}" # Unique name on the filesystem
        path = os.path.join(app.config['UPLOAD_FOLDER'], saved_name)

        # Check storage before saving the file
        file_size = int(request.headers.get('Content-Length', 0)) # Get size before saving if possible
        if file_size == 0 and file: # Fallback if Content-Length is missing
             file.seek(0, os.SEEK_END)
             file_size = file.tell()
             file.seek(0) # Reset file pointer

        if file_size > app.config['MAX_CONTENT_LENGTH']:
             return jsonify(error=f"File exceeds maximum size of {app.config['MAX_CONTENT_LENGTH']//(1024*1024)} MB"), 413 # Payload Too Large

        used = get_user_storage_used(uid)
        if used + file_size > app.config['MAX_CONTENT_LENGTH']:
            return jsonify(error="Storage limit exceeded"), 400 # Use 413? Maybe 400 is better contextually

        # Save the file *after* checks
        file.save(path)
        actual_size = os.path.getsize(path) # Verify actual size after saving

        # Generate URLs using the *saved_name* for file system access
        download_url = url_for("download_file", filename=saved_name, _external=True)
        share_url = url_for("share_file", file_id=saved_name, _external=True) # Share link uses the unique saved name

        meta = {
            "id": file_id, # Keep the original unique ID for DB key
            "name": filename,
            "size": actual_size,
            "saved_name": saved_name, # Store the name used on disk
            "url": download_url, # For direct download button
            "share_url": share_url, # For share button
            "uploaded_at": datetime.datetime.utcnow().isoformat() + "Z" # ISO 8601 format
        }

        # Write metadata to Firebase Realtime DB using the file_id as key
        db.reference(f"users/{uid}/files/{file_id}").set(meta)

        return jsonify(message="File uploaded successfully", file=meta), 200

    except Exception as e:
        # Clean up potentially saved file if error occurs after saving
        if 'path' in locals() and os.path.exists(path):
             try:
                 os.remove(path)
             except OSError as rm_err:
                 app.logger.error(f"Failed to cleanup partial upload {path}: {rm_err}")
        app.logger.error(f"Error in /upload for {uid}: {e}", exc_info=True)
        return jsonify(error="Internal server error during upload"), 500


@app.route("/download/<filename>")
def download_file(filename):
    """Serves a file for download. Publicly accessible."""
    # Basic security check: prevent path traversal
    if '..' in filename or filename.startswith('/'):
        return "Invalid filename", 400
    try:
        return send_from_directory(
            app.config['UPLOAD_FOLDER'],
            filename,
            as_attachment=True # Force download dialog
        )
    except FileNotFoundError:
        app.logger.warning(f"Download attempt for non-existent file: {filename}")
        return "File not found", 404
    except Exception as e:
        app.logger.error(f"Error downloading file {filename}: {e}", exc_info=True)
        return "Error downloading file", 500


@app.route("/share/<file_id>")
def share_file(file_id):
    """Redirects a share link to the actual download route. Publicly accessible."""
    # Note: file_id here is actually the 'saved_name' from the file metadata
    # Redirect to the download function using the same unique filename
    return redirect(url_for("download_file", filename=file_id))


@app.route("/delete/<file_id>", methods=["DELETE"])
def delete_file(file_id):
    """Deletes a file for the authenticated user."""
    decoded_token, error_response = verify_auth_token(request)
    if error_response:
        return error_response

    uid = decoded_token["uid"]
    file_ref = get_file_ref(uid, file_id)

    try:
        meta = file_ref.get()
        if not meta:
            return jsonify(error="File not found or you don't have permission"), 404

        saved_name = meta.get("saved_name")
        if not saved_name:
             # Fallback if saved_name wasn't stored (older uploads?) - attempt reconstruction
             filename = meta.get("name", "unknown")
             saved_name = f"{file_id}_{secure_filename(filename)}"
             app.logger.warning(f"saved_name missing for file {file_id}, reconstructed as {saved_name}")


        # 1. Delete from Firebase
        file_ref.delete()

        # 2. Delete from filesystem
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], saved_name)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError as e:
                # Log error but proceed, DB entry is already removed
                app.logger.error(f"Error removing file from disk {file_path} for user {uid}: {e}")
                # Optionally: Could implement a cleanup job later for orphaned files
                # For now, we prioritize removing the DB record.
        else:
             app.logger.warning(f"File not found on disk for deletion: {file_path} (User: {uid})")


        return jsonify(message="File deleted successfully"), 200

    except fb_exceptions.FirebaseError as e:
        app.logger.error(f"Firebase error deleting file {file_id} for {uid}: {e}", exc_info=True)
        return jsonify(error="Database error during deletion"), 500
    except Exception as e:
        app.logger.error(f"Error deleting file {file_id} for {uid}: {e}", exc_info=True)
        return jsonify(error="Internal server error during deletion"), 500


# --- Run the app ---
if __name__ == "__main__":
    # Use 0.0.0.0 to be accessible on the network, debug=False for production
    # Port can be configured via environment variable or default to 8080
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=False, host="0.0.0.0", port=port)