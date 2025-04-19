import os
import json
from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore, storage
from dotenv import load_dotenv
import requests
import base64
import imghdr
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

# Function to upload images to Imgur
def upload_to_imgur(file_path):
    headers = {'Authorization': f'Client-ID {IMGUR_CLIENT_ID}'}
    with open(file_path, 'rb') as file:
        img_data = file.read()
    url = 'https://api.imgur.com/3/image'
    response = requests.post(url, headers=headers, files={'image': img_data})
    if response.status_code == 200:
        return response.json()['data']['link']
    else:
        return None

# Upload file to Firebase Storage
def upload_to_firebase(file):
    blob = bucket.blob(secure_filename(file.filename))
    blob.upload_from_file(file)
    blob.make_public()
    return blob.public_url

# Route for uploading files
@app.route('/upload', methods=['POST'])
def upload_file():
    file = request.files.get('file')
    if file:
        file_ext = imghdr.what(file)
        if not file_ext:
            return jsonify({"error": "Invalid file format. Only image files are supported."}), 400
        
        file_path = f"./uploads/{secure_filename(file.filename)}"
        file.save(file_path)

        # Upload the file to Firebase Storage or Imgur based on your choice
        upload_choice = request.form.get("upload_choice", "firebase")
        if upload_choice == "imgur":
            imgur_url = upload_to_imgur(file_path)
            if imgur_url:
                return jsonify({"message": "File uploaded to Imgur successfully!", "url": imgur_url})
            else:
                return jsonify({"error": "Failed to upload to Imgur."}), 500
        else:
            firebase_url = upload_to_firebase(file)
            return jsonify({"message": "File uploaded to Firebase Storage successfully!", "url": firebase_url})

    return jsonify({"error": "No file uploaded."}), 400

# Route for getting uploaded files (List from Firebase Firestore)
@app.route('/files', methods=['GET'])
def list_files():
    files_ref = db.collection('files')
    files = files_ref.stream()
    file_urls = []
    for file in files:
        file_urls.append(file.to_dict())
    return jsonify(file_urls)

# Route for deleting uploaded files from Firebase Storage
@app.route('/delete', methods=['POST'])
def delete_file():
    file_url = request.json.get("url")
    if file_url:
        file_name = file_url.split('/')[-1]
        blob = bucket.blob(file_name)
        blob.delete()
        return jsonify({"message": "File deleted successfully."}), 200
    return jsonify({"error": "No file URL provided."}), 400

# Route for the home page
@app.route('/')
def home():
    return "Welcome to the File Manager API!"  # Basic welcome message to test the app

# Run the app
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
