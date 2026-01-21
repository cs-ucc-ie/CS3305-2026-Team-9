import os
import secrets
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from database import get_db, init_db

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key')

# Configuration
UPLOAD_FOLDER = 'uploads'
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'zip', 'doc', 'docx'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# Create uploads folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize database
init_db()

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_token():
    """Generate a unique random token for sharing"""
    return secrets.token_urlsafe(16)

# Homepage route
@app.route('/')
def index():
    return render_template('index.html')

# Upload route
@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        # Check if file was uploaded
        if 'file' not in request.files:
            flash('No file selected', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        
        # Check if filename is empty
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(request.url)
        
        # Check if file type is allowed
        if not allowed_file(file.filename):
            flash('File type not allowed', 'error')
            return redirect(request.url)
        
        # Generate unique token and filename
        token = generate_token()
        original_filename = secure_filename(file.filename)
        saved_filename = f"{token}_{original_filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], saved_filename)
        
        # Save the file
        file.save(filepath)
        file_size = os.path.getsize(filepath)
        
        # Save to database
        db = get_db()
        db.execute(
            'INSERT INTO files (filename, original_filename, file_size, share_token) VALUES (?, ?, ?, ?)',
            (saved_filename, original_filename, file_size, token)
        )
        db.commit()
        db.close()
        
        # Redirect to success page with token
        return redirect(url_for('upload_success', token=token))
    
    return render_template('upload.html')

# Upload success page - shows the shareable link
@app.route('/success/<token>')
def upload_success(token):
    db = get_db()
    file_info = db.execute('SELECT * FROM files WHERE share_token = ?', (token,)).fetchone()
    db.close()
    
    if file_info is None:
        flash('File not found', 'error')
        return redirect(url_for('index'))
    
    return render_template('success.html', file_info=file_info, token=token)

# Download route
@app.route('/download/<token>')
def download(token):
    db = get_db()
    file_info = db.execute('SELECT * FROM files WHERE share_token = ?', (token,)).fetchone()
    
    if file_info is None:
        flash('File not found or link expired', 'error')
        return redirect(url_for('index'))
    
    # Increment download count
    db.execute('UPDATE files SET download_count = download_count + 1 WHERE share_token = ?', (token,))
    db.commit()
    db.close()
    
    # Send the file
    return send_from_directory(
        app.config['UPLOAD_FOLDER'],
        file_info['filename'],
        as_attachment=True,
        download_name=file_info['original_filename']
    )

if __name__ == '__main__':
    app.run(debug=True)