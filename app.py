from flask import Flask, render_template, request, redirect, url_for, session, flash
from firebase_admin import credentials, initialize_app, auth, storage
import firebase_admin
import os

# Initialize Flask app
app = Flask(__name__)
app.secret_key = "your_secret_key_here"  # Required for session management

# Initialize Firebase Admin SDK
cred = credentials.Certificate("path/to/your/firebase-admin-sdk.json")
firebase_admin.initialize_app(cred, {'storageBucket': 'your-app-id.appspot.com'})

# Routes
@app.route('/')
def index():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    # Calculate the used storage (You can fetch this from Firebase Storage or another method)
    used_storage = 0  # Dummy value, update with actual usage logic
    total_storage = 300  # 300MB

    # Calculate remaining storage
    remaining_storage = total_storage - used_storage

    return render_template('index.html', used_storage=used_storage, remaining_storage=remaining_storage)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        try:
            user = auth.get_user_by_email(email)
            # Assuming password verification is handled by Firebase
            session['user'] = user.uid
            return redirect(url_for('index'))
        except Exception as e:
            flash("Login failed: " + str(e), "error")
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        try:
            user = auth.create_user(email=email, password=password)
            session['user'] = user.uid
            return redirect(url_for('index'))
        except Exception as e:
            flash("Signup failed: " + str(e), "error")
    return render_template('signup.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'user' not in session:
        return redirect(url_for('login'))

    file = request.files['file']
    if file:
        # Check the file size (dummy check, you can add validation logic here)
        file_size = len(file.read()) / (1024 * 1024)  # in MB
        if file_size > 300:
            flash("File is too large, please upload files smaller than 300MB.", "error")
            return redirect(url_for('index'))

        # Save the file to Firebase Storage
        bucket = storage.bucket()
        blob = bucket.blob(file.filename)
        blob.upload_from_file(file)

        flash("File uploaded successfully!", "success")
        return redirect(url_for('index'))

    flash("No file selected.", "error")
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5000)
