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

# Default storage if not set for user (in bytes)
DEFAULT_STORAGE_LIMIT = 300 * 1024 * 1024
# Activation code details
ACTIVATION_CODES = {
    "FREE2GB": {
        "bonus_bytes": 2 * 1024 * 1024 * 1024, # 2 GiB
        "reusable": False # Can this code be used multiple times?
    }
    # Add more codes here if needed
}


app.config['UPLOAD_FOLDER'] = 'uploads'
# Max content length should be the absolute maximum possible after upgrades
# Set it higher than the default + potential upgrades, or remove if uploads checked against user quota only
# Let's set it generously, e.g., 10GB, actual limit is per-user now.
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 * 1024

# --- Firebase Initialization ---
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

def get_user_ref(uid):
    """Get Firebase reference for a user's data."""
    return db.reference(f"users/{uid}")

def get_user_data(uid):
    """Gets all data for a user, setting defaults if needed."""
    user_ref = get_user_ref(uid)
    try:
        data = user_ref.get()
        if data is None:
            data = {} # User node might not exist yet

        # --- Set defaults if fields are missing ---
        if 'total_storage' not in data:
            data['total_storage'] = DEFAULT_STORAGE_LIMIT
            # Persist the default back to DB? Optional, depends on desired behavior.
            # user_ref.update({'total_storage': DEFAULT_STORAGE_LIMIT})
        if 'files' not in data:
            data['files'] = {}
        if 'redeemed_codes' not in data:
             data['redeemed_codes'] = [] # Initialize if missing

        return data
    except fb_exceptions.FirebaseError as e:
        app.logger.error(f"Firebase error getting user data for {uid}: {e}")
        # Return defaults on error to avoid breaking functionality
        return {
            'total_storage': DEFAULT_STORAGE_LIMIT,
            'files': {},
            'redeemed_codes': []
        }


def get_user_storage_used(user_files_data):
    """Calculate user's used storage from files data."""
    return sum(f.get("size", 0) for f in user_files_data.values())

# --- Authentication Verification ---
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
    """Gets metadata and storage info for the authenticated user."""
    decoded_token, error_response = verify_auth_token(request)
    if error_response:
        return error_response

    uid = decoded_token["uid"]
    try:
        user_data = get_user_data(uid)
        total_storage = user_data.get('total_storage', DEFAULT_STORAGE_LIMIT) # Use fetched or default total storage
        files_data = user_data.get('files', {})
        used = get_user_storage_used(files_data)
        remaining = max(0, total_storage - used)

        files = []
        for file_id, meta in files_data.items():
            saved_name = meta.get("saved_name")
            # Handle cases where saved_name might be missing (e.g., older data)
            if not saved_name:
                 original_filename = meta.get("name", "unknown_file")
                 saved_name = f"{file_id}_{secure_filename(original_filename)}"

            download_url = url_for("download_file", filename=saved_name, _external=True)
            share_url = url_for("share_file", file_id=saved_name, _external=True)

            files.append({
                "id": file_id,
                "name": meta.get("name", "Unnamed File"),
                "url": download_url,
                "share_url": share_url,
                "size": meta.get("size", 0),
                "saved_name": saved_name
            })

        return jsonify(
            storage_used=used,
            storage_remaining=remaining,
            total_storage=total_storage, # Send total storage to frontend
            files=files
        )

    except Exception as e:
        app.logger.error(f"Error in /files for {uid}: {e}", exc_info=True)
        return jsonify(error="Internal server error fetching files"), 500


@app.route("/upload", methods=["POST"])
def upload_file():
    """Handles file uploads, checking against user's quota."""
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
        # Get user's current usage and total limit BEFORE saving
        user_data = get_user_data(uid)
        total_storage = user_data.get('total_storage', DEFAULT_STORAGE_LIMIT)
        files_data = user_data.get('files', {})
        used = get_user_storage_used(files_data)

        # Estimate file size (more reliable than Content-Length sometimes)
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)

        if file_size == 0:
             return jsonify(error="File appears to be empty"), 400

        # Check against user's specific quota
        if used + file_size > total_storage:
            limit_mb = total_storage / (1024*1024)
            return jsonify(error=f"Storage limit ({limit_mb:.1f} MB) exceeded"), 413 # 413 Payload Too Large

        # Proceed with saving if quota check passes
        filename = secure_filename(file.filename)
        file_id = str(uuid.uuid4())
        saved_name = f"{file_id}_{filename}"
        path = os.path.join(app.config['UPLOAD_FOLDER'], saved_name)

        file.save(path)
        actual_size = os.path.getsize(path) # Get actual size after saving

        # Final check in case of discrepancies (optional but safer)
        if used + actual_size > total_storage:
             os.remove(path) # Clean up saved file
             limit_mb = total_storage / (1024*1024)
             app.logger.warning(f"Upload cancelled post-save for user {uid} due to size discrepancy. Limit: {limit_mb:.1f} MB")
             return jsonify(error=f"Storage limit ({limit_mb:.1f} MB) exceeded after save"), 413

        download_url = url_for("download_file", filename=saved_name, _external=True)
        share_url = url_for("share_file", file_id=saved_name, _external=True)

        meta = {
            "id": file_id,
            "name": filename,
            "size": actual_size,
            "saved_name": saved_name,
            "url": download_url,
            "share_url": share_url,
            "uploaded_at": datetime.datetime.utcnow().isoformat() + "Z"
        }

        # Write metadata to Firebase DB under the user's files node
        db.reference(f"users/{uid}/files/{file_id}").set(meta)

        return jsonify(message="File uploaded successfully", file=meta), 200

    except Exception as e:
        if 'path' in locals() and os.path.exists(path):
             try: os.remove(path)
             except OSError as rm_err: app.logger.error(f"Failed cleanup {path}: {rm_err}")
        app.logger.error(f"Error in /upload for {uid}: {e}", exc_info=True)
        return jsonify(error="Internal server error during upload"), 500

# --- Public download/share routes (no auth needed) ---
@app.route("/download/<filename>")
def download_file(filename):
    """Serves a file for download."""
    if '..' in filename or filename.startswith('/'):
        return "Invalid filename", 400
    try:
        return send_from_directory(
            app.config['UPLOAD_FOLDER'], filename, as_attachment=True
        )
    except FileNotFoundError:
        app.logger.warning(f"Download attempt for non-existent file: {filename}")
        return "File not found", 404
    except Exception as e:
        app.logger.error(f"Error downloading file {filename}: {e}", exc_info=True)
        return "Error downloading file", 500

@app.route("/share/<file_id>")
def share_file(file_id):
    """Redirects a share link to the download route."""
    return redirect(url_for("download_file", filename=file_id))

# --- Authenticated action routes ---
@app.route("/delete/<file_id>", methods=["DELETE"])
def delete_file(file_id):
    """Deletes a file for the authenticated user."""
    decoded_token, error_response = verify_auth_token(request)
    if error_response: return error_response
    uid = decoded_token["uid"]

    file_ref = db.reference(f"users/{uid}/files/{file_id}")
    try:
        meta = file_ref.get()
        if not meta:
            return jsonify(error="File not found or you don't have permission"), 404

        saved_name = meta.get("saved_name")
        if not saved_name:
             filename = meta.get("name", "unknown")
             saved_name = f"{file_id}_{secure_filename(filename)}"
             app.logger.warning(f"saved_name missing for file {file_id}, reconstructed as {saved_name}")

        # 1. Delete from Firebase
        file_ref.delete()

        # 2. Delete from filesystem
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], saved_name)
        if os.path.exists(file_path):
            try: os.remove(file_path)
            except OSError as e: app.logger.error(f"Error removing file {file_path}: {e}")
        else: app.logger.warning(f"File not found on disk for deletion: {file_path}")

        return jsonify(message="File deleted successfully"), 200

    except Exception as e:
        app.logger.error(f"Error deleting file {file_id} for {uid}: {e}", exc_info=True)
        return jsonify(error="Internal server error during deletion"), 500


@app.route("/redeem-code", methods=["POST"])
def redeem_code():
    """Redeems an activation code to increase storage."""
    decoded_token, error_response = verify_auth_token(request)
    if error_response: return error_response
    uid = decoded_token["uid"]

    try:
        req_data = request.get_json()
        if not req_data or 'activation_code' not in req_data:
             return jsonify(error="Missing 'activation_code' in request body"), 400

        code = req_data['activation_code'].strip()

        if not code:
            return jsonify(error="Activation code cannot be empty"), 400

        # Check if code exists in our defined codes
        if code not in ACTIVATION_CODES:
            return jsonify(error="Invalid activation code"), 400

        code_details = ACTIVATION_CODES[code]
        bonus_bytes = code_details["bonus_bytes"]
        is_reusable = code_details["reusable"]

        user_ref = get_user_ref(uid)
        user_data = get_user_data(uid) # Get data including defaults and redeemed list
        current_total_storage = user_data.get('total_storage', DEFAULT_STORAGE_LIMIT)
        redeemed_codes = user_data.get('redeemed_codes', [])

        # Check if already redeemed (if not reusable)
        if not is_reusable and code in redeemed_codes:
            return jsonify(error="This code has already been redeemed"), 400

        # Apply the bonus
        new_total_storage = current_total_storage + bonus_bytes

        # Update Firebase atomically (or as close as possible)
        update_payload = {
            'total_storage': new_total_storage
        }
        # Add code to redeemed list if it's not reusable
        if not is_reusable:
             updated_redeemed = redeemed_codes + [code]
             update_payload['redeemed_codes'] = updated_redeemed

        user_ref.update(update_payload)

        new_limit_gb = new_total_storage / (1024*1024*1024)
        return jsonify(
             message=f"Code redeemed successfully! Your new storage limit is {new_limit_gb:.2f} GB.",
             new_total_storage=new_total_storage # Send back new limit
        ), 200

    except json.JSONDecodeError:
        return jsonify(error="Invalid JSON format in request body"), 400
    except fb_exceptions.FirebaseError as e:
        app.logger.error(f"Firebase error redeeming code for {uid}: {e}", exc_info=True)
        return jsonify(error="Database error processing code"), 500
    except Exception as e:
        app.logger.error(f"Error redeeming code for {uid}: {e}", exc_info=True)
        return jsonify(error="Internal server error processing code"), 500


# --- Run the app ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=False, host="0.0.0.0", port=port) # Debug=False for production