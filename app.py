from flask import Flask, render_template, request, redirect, url_for, send_from_directory, session, jsonify
from werkzeug.utils import secure_filename
import os
from flask_cors import CORS
from functools import wraps

app = Flask(__name__)
app.secret_key = 'supersecretkey'
CORS(app)

UPLOAD_FOLDER = 'uploads'
MAX_STORAGE_MB = 300

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Check login
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_email' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def get_user_folder():
    return os.path.join(app.config['UPLOAD_FOLDER'], session['user_email'])

def get_storage_usage_mb():
    total_size = 0
    user_folder = get_user_folder()
    if os.path.exists(user_folder):
        for f in os.listdir(user_folder):
            fp = os.path.join(user_folder, f)
            if os.path.isfile(fp):
                total_size += os.path.getsize(fp)
    return round(total_size / (1024 * 1024), 2)

@app.route('/')
@login_required
def index():
    user_folder = get_user_folder()
    if not os.path.exists(user_folder):
        os.makedirs(user_folder)
    files = os.listdir(user_folder)
    used = get_storage_usage_mb()
    remaining = MAX_STORAGE_MB - used
    return render_template('index.html', files=files, used=used, remaining=remaining, email=session['user_email'])

@app.route('/upload', methods=['POST'])
@login_required
def upload():
    if 'file' not in request.files:
        return redirect('/')
    file = request.files['file']
    if file.filename == '':
        return redirect('/')
    filename = secure_filename(file.filename)
    user_folder = get_user_folder()

    if not os.path.exists(user_folder):
        os.makedirs(user_folder)

    # Check size limit
    if get_storage_usage_mb() + (len(file.read()) / (1024 * 1024)) > MAX_STORAGE_MB:
        return 'Storage limit exceeded!', 403
    file.seek(0)  # Reset after read
    file.save(os.path.join(user_folder, filename))
    return redirect('/')

@app.route('/delete/<filename>')
@login_required
def delete(filename):
    file_path = os.path.join(get_user_folder(), filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    return redirect('/')

@app.route('/download/<email>/<filename>')
def download(email, filename):
    return send_from_directory(os.path.join(UPLOAD_FOLDER, email), filename, as_attachment=True)

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/setuser', methods=['POST'])
def setuser():
    data = request.get_json()
    session['user_email'] = data['email']
    return jsonify({'status': 'ok'})

@app.route('/logout')
def logout():
    session.pop('user_email', None)
    return redirect('/login')

# Run the app
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
