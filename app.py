from flask import Flask, render_template, request, jsonify, redirect, url_for
import os
import json
import firebase_admin
from firebase_admin import credentials, firestore, auth, storage
from dotenv import load_dotenv
import requests
from werkzeug.utils import secure_filename

# Load environment variables from .env file
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Initialize Firebase Admin with JSON loaded from environment variable
firebase_creds_json = os.getenv("FIREBASE_CREDENTIALS")
if not firebase_creds_json:
    raise ValueError("Missing FIREBASE_CREDENTIALS environment variable.")

firebase_creds_dict = json.loads(firebase_creds_json)
cred = credentials.Certificate(firebase_creds_dict)
firebase_admin.initialize_app(cred, {
    'storageBucket': os.getenv("FIREBASE_STORAGE_BUCKET")
})

# Firebase Firestore client
db = firestore.client()

# Firebase Storage client
bucket = storage.bucket()

# Imgur API credentials
IMGUR_CLIENT_ID = os.getenv("IMGUR_CLIENT_ID")

# Max file size for uploads (5MB)
MAX_CONTENT_LENGTH = 5 * 1024 * 1024
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# Route for serving the login page
@app.route('/')
def login():
    return render_template('login.html')  # Serve the login.html file

# Route for user authentication
@app.route('/setuser', methods=['POST'])
def set_user():
    data = request.json
    email = data.get("email")
    if email:
        # Save the email to Firebase Firestore (or other logic if necessary)
        user_ref = db.collection('users').document(email)
        user_ref.set({"email": email})
        return jsonify({"message": "User set successfully."}), 200
    return jsonify({"error": "Email not provided."}), 400

# Route for signup page
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        try:
            user = auth.create_user(
                email=email,
                password=password
            )
            return redirect(url_for('login'))
        except firebase_admin.auth.EmailAlreadyExistsError:
            return jsonify({"error": "Email already exists."}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return render_template('signup.html')  # Serve the signup page

# Run the app
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
