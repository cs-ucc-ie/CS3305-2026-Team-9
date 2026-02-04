import os
import secrets
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, session, g
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from database import get_db, close_db, init_db
from werkzeug.security import generate_password_hash, check_password_hash
from forms import RegistrationForm, LoginForm
from functools import wraps
from datetime import datetime, timedelta
import qrcode
import io
import base64
import zipfile

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')
if not app.secret_key:
    raise RuntimeError("SECRET_KEY environment variable is not set")
app.config['WTF_CSRF_ENABLED'] = True

@app.before_request
def logged_in_user():
    g.user = session.get("user_id", None)
    
def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login", next=request.url))
        return view(*args, **kwargs)
    return wrapped_view

@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("index"))
    
    form = RegistrationForm()
    if form.validate_on_submit():
        user_id = form.user_id.data
        salt = str(base64.b64encode(os.urandom(32)))
        password = form.password.data

        db = get_db()
        clashing_user = db.execute(
            """SELECT * FROM users WHERE user_id = ?;""",
            (user_id,)
        ).fetchone()

        if clashing_user is not None:
            form.user_id.errors.append("Username already exists")
        else:
            db.execute(
                """INSERT INTO users (user_id, salt, password) VALUES (?, ?, ?);""",
                (user_id, salt, generate_password_hash(password+salt))
            )
            db.commit()
            return redirect(url_for("login"))
    return render_template("register.html", form=form)

@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("index"))

    form = LoginForm()
    if form.validate_on_submit():
        user_id = form.user_id.data
        password = form.password.data

        db = get_db()
        user = db.execute(
            """SELECT * FROM users WHERE user_id = ?;""",
            (user_id,)
        ).fetchone()

        if user is None or not check_password_hash(user["password"], password+user["salt"]):
            form.password.errors.append("Username or password incorrect")
        else:
            session.clear()
            session["user_id"] = user_id
            next_page = request.args.get("next")
            if not next_page or not next_page.startswith("/") or next_page.startswith("//"):
                next_page = url_for("index")
            return redirect(next_page)
    return render_template("login.html", form=form)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))



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

# Close DB connections automatically at end of request
app.teardown_appcontext(close_db)

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_token():
    """Generate a unique random token for sharing"""
    return secrets.token_urlsafe(16)

def generate_qr_code(url):
    """Generate QR code as base64 string"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Convert to base64 for embedding in HTML
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    img_str = base64.b64encode(buffer.getvalue()).decode()
    
    return f"data:image/png;base64,{img_str}"

# Homepage route
@app.route('/')
def index():
    return render_template('Reg_Log_index.html')

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        # Check if files were uploaded
        if 'files' not in request.files:
            flash('No files selected', 'error')
            return redirect(request.url)
        
        files = request.files.getlist('files')
        
        # Check if any files were actually selected
        if not files or files[0].filename == '':
            flash('No files selected', 'error')
            return redirect(request.url)
        
        # Generate unique token
        token = generate_token()
        user_id = session.get('user_id')
        
        # Get expiration time and password
        ALLOWED_EXPIRY_HOURS = {24, 168, 720}
        try:
            expiry_hours = int(request.form.get('expiry', 24))
        except (ValueError, TypeError):
            expiry_hours = 24
        if expiry_hours not in ALLOWED_EXPIRY_HOURS:
            expiry_hours = 24
        expiry_date = datetime.now() + timedelta(hours=expiry_hours)
        password = request.form.get('password', '').strip()
        salt = None
        password_hash = None
        if password:
            salt = str(base64.b64encode(os.urandom(32)))
            password_hash = generate_password_hash(password+salt)
        
        # If single file, save normally
        if len(files) == 1:
            file = files[0]
            
            # Check if file type is allowed
            if not allowed_file(file.filename):
                flash('File type not allowed', 'error')
                return redirect(request.url)
            
            original_filename = secure_filename(file.filename)
            saved_filename = f"{token}_{original_filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], saved_filename)
            
            file.save(filepath)
            file_size = os.path.getsize(filepath)
        
        # If multiple files, create a zip
        else:
            # Create zip filename
            original_filename = f"files_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
            saved_filename = f"{token}_{original_filename}"
            zip_path = os.path.join(app.config['UPLOAD_FOLDER'], saved_filename)
            
            # Create zip file
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file in files:
                    if file and file.filename:
                        # Check file type
                        if not allowed_file(file.filename):
                            flash(f'File type not allowed: {file.filename}', 'error')
                            continue
                        
                        # Save to zip
                        filename = secure_filename(file.filename)
                        file_data = file.read()
                        zipf.writestr(filename, file_data)
            
            file_size = os.path.getsize(zip_path)
            flash(f'Created zip file with {len(files)} files', 'success')
        
        # Save to database
        db = get_db()
        db.execute(
            'INSERT INTO files (filename, original_filename, file_size, share_token, user_id, expiry_date, salt, password_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (saved_filename, original_filename, file_size, token, user_id, expiry_date, salt, password_hash)
        )
        db.commit()

        return redirect(url_for('upload_success', token=token))
    
    return render_template('upload.html')

@app.route('/success/<token>')
@login_required
def upload_success(token):
    db = get_db()
    file_info = db.execute('SELECT * FROM files WHERE share_token = ?', (token,)).fetchone()

    if file_info is None:
        flash('File not found', 'error')
        return redirect(url_for('index'))

    # Generate QR code for the download link
    download_url = request.url_root + 'download/' + token
    qr_code = generate_qr_code(download_url)
    
    return render_template('success.html', file_info=file_info, token=token, qr_code=qr_code)

@app.route('/download/<token>', methods=['GET', 'POST'])
@login_required
def download(token):
    db = get_db()
    file_info = db.execute('SELECT * FROM files WHERE share_token = ?', (token,)).fetchone()
    
    if file_info is None:
        flash('File not found or link expired', 'error')

        return redirect(url_for('index'))
    
    # Check if link has expired
    expiry_date = datetime.fromisoformat(file_info['expiry_date'])
    if datetime.now() > expiry_date:
        flash('This link has expired', 'error')

        return redirect(url_for('index'))
    
    # Check if password protected
    if file_info['password_hash']:
        # If GET request, show password form
        if request.method == 'GET':
    
            return render_template('password_check.html', token=token)
        
        # If POST request, check password
        if request.method == 'POST':
            entered_password = request.form.get('password', '')
            salt = file_info['salt'] or ''
            if not check_password_hash(file_info['password_hash'], entered_password + salt):
                flash('Incorrect password', 'error')
        
                return render_template('password_check.html', token=token)
            # Password correct, continue to download

    # Increment download count
    db.execute('UPDATE files SET download_count = download_count + 1 WHERE share_token = ?', (token,))
    db.commit()

    
    # Send the file
    return send_from_directory(
        app.config['UPLOAD_FOLDER'],
        file_info['filename'],
        as_attachment=True,
        download_name=file_info['original_filename']
    )



# User Dashboard - view all uploaded files
@app.route('/dashboard')
@login_required
def dashboard():
    user_id = session.get('user_id')
    
    db = get_db()
    
    # files I uploaded
    files = db.execute(
        "SELECT * FROM files Where user_id = ? ORDER BY upload_date DESC",
        (user_id,)
    ).fetchall()

    # Incoming friend requests
    incoming_requests = db.execute(
        "SELECT * FROM friends WHERE friend_id = ? AND status = 'pending'",
        (user_id,)
    ).fetchall()

    # Outgoing friend requests 
    outgoing_requests = db.execute(
        "SELECT * FROM friends WHERE user_id = ? AND status = 'pending'",
        (user_id,)
    ).fetchall()

    # Accepted friends
    friends = db.execute(
        """
        SELECT * FROM friends
        WHERE (user_id = ? OR friend_id = ?) AND status = 'accepted'
        """,
        (user_id, user_id)
    ).fetchall()

    # Files shared with me
    shared_with_me = db.execute(
        """
        SELECT files.*, shared_files.sender_id
        FROM shared_files
        JOIN files ON shared_files.file_id = files.id
        WHERE shared_files.receiver_id = ?
        ORDER BY shared_files.shared_date DESC
        """,
        (user_id,)
    ).fetchall()



    return render_template(
        "dashboard.html",
        files=files,
        friends=friends,
        incoming_requests=incoming_requests,
        outgoing_requests=outgoing_requests,
        shared_with_me=shared_with_me,
        now=datetime.now().isoformat()
    )

# Add a friend
@app.route('/add_friend', methods=['POST'])
@login_required
def add_friend():
    user_id = session.get("user_id")
    friend_id = request.form.get("friend_id")

    if user_id == friend_id:
        flash("You cannot add yourself", "error")
        return redirect(url_for("dashboard"))
    
    db = get_db()

    # Check if friends exist
    friend = db.execute(
        "SELECT * FROM users WHERE user_id = ?",
        (friend_id,)
    ).fetchone()

    if friend is None:
        flash("User does not exist", "error")
        return redirect(url_for("dashboard"))
    
    # Check if friendship exists in either direction
    existing = db.execute(
        "SELECT * FROM friends WHERE (user_id = ? AND friend_id = ?) OR (user_id = ? AND friend_id = ?)",
        (user_id, friend_id, friend_id, user_id)
    ).fetchone()

    if existing:
        flash("Friend request already sent or already friends", "error")

        return redirect(url_for("dashboard"))

    # Create pending request
    db.execute(
        "INSERT INTO friends (user_id, friend_id, status, requested_by) VALUES (?, ?, ?, ?)",
        (user_id, friend_id, "pending", user_id)
    )
    db.commit()


    flash("Friend request sent", "success")
    return redirect(url_for("dashboard"))

@app.route("/accept_friend/<int:request_id>", methods=["POST"])
@login_required
def accept_friend(request_id):
    user_id = session.get("user_id")
    db = get_db()

    db.execute(
        "UPDATE friends SET status='accepted' WHERE id=? AND friend_id=?",
        (request_id, user_id)
    )
    db.commit()


    flash("Friend request accepted", "success")
    return redirect(url_for("dashboard"))

@app.route("/decline_friend/<int:request_id>", methods=["POST"])
@login_required
def decline_friend(request_id):
    user_id = session.get("user_id")
    db = get_db()

    db.execute(
        "DELETE FROM friends WHERE id=? AND friend_id=?",
        (request_id, user_id)
    )
    db.commit()


    flash("Friend request declined", "success")
    return redirect(url_for("dashboard"))

@app.route("/unfriend/<friend_id>", methods=["POST"])
@login_required
def unfriend(friend_id):
    user_id = session.get("user_id")
    db = get_db()

    db.execute(
        "DELETE FROM friends WHERE (user_id=? and friend_id=?) OR (user_id=? AND friend_id=?)",
        (user_id, friend_id, friend_id, user_id)
    )
    db.commit()


    flash("Friend removed", "success")
    return redirect(url_for("dashboard"))

# Delete file route
@app.route('/delete/<token>', methods=['POST'])
@login_required
def delete_file(token):
    user_id = session.get('user_id')
    
    db = get_db()
    # Get the file info
    file_info = db.execute(
        'SELECT * FROM files WHERE share_token = ? AND user_id = ?',
        (token, user_id)
    ).fetchone()
    
    if file_info is None:
        flash('File not found or you do not have permission to delete it', 'error')

        return redirect(url_for('dashboard'))
    
    # Delete the physical file
    try:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_info['filename'])
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        flash('Error deleting file', 'error')
    
    # Delete from database
    db.execute('DELETE FROM files WHERE share_token = ? AND user_id = ?', (token, user_id))
    db.commit()

    
    flash('File deleted successfully', 'success')
    return redirect(url_for('dashboard'))

# Share a file with a friend
@app.route("/share/<token>", methods=["POST"])
@login_required
def share_file(token):
    sender_id = session.get("user_id")
    receiver_id = request.form.get("friend_id")

    db = get_db()

    file = db.execute(
        "SELECT * FROM files WHERE share_token = ? and user_id = ?",
        (token, sender_id)
    ).fetchone()

    if file is None:
        flash("You cannot share this file", "error")

        return redirect(url_for("dashboard"))

    # Verify receiver is an accepted friend
    friendship = db.execute(
        """SELECT * FROM friends
        WHERE ((user_id = ? AND friend_id = ?) OR (user_id = ? AND friend_id = ?))
        AND status = 'accepted'""",
        (sender_id, receiver_id, receiver_id, sender_id)
    ).fetchone()

    if friendship is None:
        flash("You can only share files with friends", "error")

        return redirect(url_for("dashboard"))

    db.execute(
        "INSERT INTO shared_files (file_id, sender_id, receiver_id) VALUES (?, ?, ?)",
        (file["id"], sender_id, receiver_id)
    )
    db.commit()


    flash("File shared", "success")
    return redirect(url_for("dashboard"))

# File preview route
@app.route('/preview/<token>', methods=['GET', 'POST'])
@login_required
def preview(token):
    db = get_db()
    file_info = db.execute('SELECT * FROM files WHERE share_token = ?', (token,)).fetchone()
    
    if file_info is None:
        flash('File not found', 'error')

        return redirect(url_for('index'))
    
    # Check if link has expired
    expiry_date = datetime.fromisoformat(file_info['expiry_date'])
    if datetime.now() > expiry_date:
        flash('This link has expired', 'error')

        return redirect(url_for('index'))
    
    # Check if password protected
    if file_info['password_hash']:
        if request.method == 'GET':
    
            return render_template('password_check.html', token=token, preview=True)
        
        if request.method == 'POST':
            entered_password = request.form.get('password', '')
            salt = file_info['salt'] or ''
            if not check_password_hash(file_info['password_hash'], entered_password + salt):
                flash('Incorrect password', 'error')
        
                return render_template('password_check.html', token=token, preview=True)


    
    # Determine if file is previewable
    file_ext = file_info['original_filename'].rsplit('.', 1)[1].lower() if '.' in file_info['original_filename'] else ''
    is_image = file_ext in ['jpg', 'jpeg', 'png', 'gif']
    is_pdf = file_ext == 'pdf'
    
    return render_template('preview.html', file_info=file_info, token=token, 
                          is_image=is_image, is_pdf=is_pdf, file_ext=file_ext)


# Serve file for preview (images/PDFs)
@app.route('/serve/<token>')
@login_required
def serve_file(token):
    db = get_db()
    file_info = db.execute('SELECT * FROM files WHERE share_token = ?', (token,)).fetchone()


    if file_info is None:
        return "File not found", 404

    # Check if link has expired
    expiry_date = datetime.fromisoformat(file_info['expiry_date'])
    if datetime.now() > expiry_date:
        return "This link has expired", 403

    # Block serving if file is password-protected (must use preview flow)
    if file_info['password_hash']:
        return "This file is password protected", 403

    # Serve the file (but not as attachment, so browser can display it)
    return send_from_directory(
        app.config['UPLOAD_FOLDER'],
        file_info['filename']
    )

if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_DEBUG', 'false').lower() == 'true')