from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash, session
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

users = {}  # Simple in-memory user store

@app.route('/')
def home():
    if 'username' in session:
        files = os.listdir(UPLOAD_FOLDER)
        return render_template('index.html', files=files)
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        uname = request.form['username']
        pwd = request.form['password']
        if uname in users and users[uname] == pwd:
            session['username'] = uname
            return redirect(url_for('home'))
        flash("Invalid credentials", "danger")
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        uname = request.form['username']
        pwd = request.form['password']
        if uname in users:
            flash("User already exists", "danger")
        else:
            users[uname] = pwd
            flash("Signup successful. Please log in.", "success")
            return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/upload', methods=['POST'])
def upload():
    if 'username' not in session:
        return redirect(url_for('login'))

    if 'file' not in request.files:
        return redirect(url_for('home'))
    file = request.files['file']
    if file.filename == '':
        return redirect(url_for('home'))
    filename = secure_filename(file.filename)
    file.save(os.path.join(UPLOAD_FOLDER, filename))
    return redirect(url_for('home'))

@app.route('/delete/<filename>')
def delete(filename):
    if 'username' not in session:
        return redirect(url_for('login'))

    file_path = os.path.join(UPLOAD_FOLDER, filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    return redirect(url_for('home'))

@app.route('/rename/<filename>', methods=['POST'])
def rename(filename):
    if 'username' not in session:
        return redirect(url_for('login'))

    new_name = secure_filename(request.form['new_name'])
    old_path = os.path.join(UPLOAD_FOLDER, filename)
    new_path = os.path.join(UPLOAD_FOLDER, new_name)
    if os.path.exists(old_path):
        os.rename(old_path, new_path)
    return redirect(url_for('home'))

@app.route('/uploads/<filename>')
def serve_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)

# Run the app
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
