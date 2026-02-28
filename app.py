import os
import re
import secrets
import time
from collections import defaultdict
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, send_file, session, g, jsonify
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from database import get_db, close_db, init_db
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import CSRFProtect
from forms import RegistrationForm, LoginForm
from functools import wraps
from datetime import datetime, timedelta
import qrcode
import io
import base64
import zipfile
from storage import save_file, save_zip, get_file_response, delete_file as storage_delete_file
import hashlib
from app_paths import get_user_data_dir

USER_DATA = get_user_data_dir()

# Simple in-memory rate limiter for login attempts
login_attempts = defaultdict(list)  # IP -> list of timestamps
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300  # 5 minutes

# Load environment variables
load_dotenv(os.path.join(USER_DATA, '.env'))

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY') or secrets.token_hex(32)
app.config['WTF_CSRF_ENABLED'] = True
csrf = CSRFProtect(app)

@app.before_request
def logged_in_user():
    g.user = session.get("user_id", None)

@app.before_request
def load_profile_picture():
    if "user_id" in session:
        db = get_db()
        row = db.execute(
            "SELECT profile_picture, is_admin FROM users WHERE user_id = ?",
            (session["user_id"],)
        ).fetchone()
        g.profile_picture = row["profile_picture"] if row and row["profile_picture"] else None
        g.is_admin = bool(row["is_admin"]) if row else False
    else:
        g.profile_picture = None
        g.is_admin = False

def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login", next=request.url))
        return view(*args, **kwargs)
    return wrapped_view

def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login", next=request.url))
        if not g.is_admin:
            flash('You do not have admin access.', 'error')
            return redirect(url_for('index'))
        return view(*args, **kwargs)
    return wrapped_view

@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("index"))
    
    form = RegistrationForm()
    if form.validate_on_submit():
        user_id = form.user_id.data
        salt = base64.b64encode(os.urandom(32)).decode('utf-8')
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
                (user_id, salt, generate_password_hash(password + salt))
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
        # Rate limiting: check recent failed attempts from this IP
        client_ip = request.remote_addr
        now = time.time()
        login_attempts[client_ip] = [
            t for t in login_attempts[client_ip]
            if now - t < LOGIN_WINDOW_SECONDS
        ]
        if len(login_attempts[client_ip]) >= MAX_LOGIN_ATTEMPTS:
            flash("Too many login attempts. Please try again in a few minutes.", "error")
            return render_template("login.html", form=form)

        user_id = form.user_id.data
        password = form.password.data

        db = get_db()
        user = db.execute(
            """SELECT * FROM users WHERE user_id = ?;""",
            (user_id,)
        ).fetchone()

        if user is None or not check_password_hash(user["password"], password + user["salt"]):
            login_attempts[client_ip].append(now)
            form.password.errors.append("Username or password incorrect")
        else:
            # Clear failed attempts on successful login
            login_attempts.pop(client_ip, None)
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

ALLOWED_PROFILE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_PROFILE_SIZE = 5 * 1024 * 1024  # 5MB

@app.route("/profile-picture", methods=["POST"])
@login_required
def upload_profile_picture():
    if "picture" not in request.files:
        flash("No file selected", "error")
        return redirect(url_for("settings"))
    file = request.files["picture"]
    if file.filename == "":
        flash("No file selected", "error")
        return redirect(url_for("settings"))

    # Validate file extension
    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_PROFILE_EXTENSIONS:
        flash("Invalid image format. Allowed: PNG, JPG, JPEG, GIF, WEBP", "error")
        return redirect(url_for("settings"))

    # Validate file size
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_PROFILE_SIZE:
        flash("Profile picture must be under 5MB", "error")
        return redirect(url_for("settings"))

    filename = secure_filename(g.user + "_" + file.filename)
    profiles_dir = os.path.join(USER_DATA, "static", "profiles")
    os.makedirs(profiles_dir, exist_ok=True)

    # Delete old profile picture if it exists
    db = get_db()
    old_pic = db.execute(
        "SELECT profile_picture FROM users WHERE user_id = ?", (g.user,)
    ).fetchone()
    if old_pic and old_pic["profile_picture"]:
        old_path = os.path.join(profiles_dir, old_pic["profile_picture"])
        if os.path.exists(old_path):
            os.remove(old_path)

    save_path = os.path.join(profiles_dir, filename)
    file.save(save_path)

    db.execute("UPDATE users SET profile_picture = ? WHERE user_id = ?", (filename, g.user))
    db.commit()

    flash("Profile picture updated!", "success")
    return redirect(url_for("settings"))



# Configuration — use absolute paths for PythonAnywhere compatibility
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(USER_DATA, 'uploads')
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'zip', 'doc', 'docx', 'mp3', 'mp4', 'wav', 'mov', 'avi', 'csv', 'xlsx', 'pptx'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# Create uploads folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize database
init_db()

# Close DB connections automatically at end of request
app.teardown_appcontext(close_db)

ALLOWED_MIME_TYPES = {
    'text/plain', 'application/pdf', 'image/png', 'image/jpeg', 'image/gif',
    'application/zip', 'application/x-zip-compressed',
    'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'audio/mpeg', 'video/mp4', 'audio/wav', 'video/quicktime', 'video/x-msvideo',
    'text/csv', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'application/octet-stream',  # fallback for encrypted files
}

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def allowed_mime_type(mimetype):
    """Check if the MIME type is allowed. Returns True if mimetype is empty/None (fallback to extension check)."""
    if not mimetype or mimetype == 'application/octet-stream':
        return True  # Fall back to extension-based check
    return mimetype in ALLOWED_MIME_TYPES

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

def create_notification(user_id, message, link=None):
    db = get_db()
    db.execute(
        "INSERT INTO notifications (user_id, message, link) VALUES (?, ?, ?)",
        (user_id, message, link)
    )
    db.commit()


def compute_checksum(file_obj, chunk_size=8192):
    """Return SHA256 hex digest for a file-like object."""
    h = hashlib.sha256()
    file_obj.seek(0)
    while True:
        chunk = file_obj.read(chunk_size)
        if not chunk:
            break
        h.update(chunk)
    file_obj.seek(0)
    return h.hexdigest()

# Homepage route
@app.route('/')
def index():
    db = get_db()
    stats = {}
    user_stats = {}
    recent_files = []
    friend_count = 0

    try:
        stats['total_files'] = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        stats['total_users'] = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        stats['total_downloads'] = db.execute("SELECT COALESCE(SUM(download_count), 0) FROM files").fetchone()[0]
        stats['encrypted_files'] = db.execute("SELECT COUNT(*) FROM files WHERE is_encrypted = 1").fetchone()[0]
    except Exception:
        stats = {'total_files': 0, 'total_users': 0, 'total_downloads': 0, 'encrypted_files': 0}

    if g.user:
        try:
            user_id = session.get('user_id')
            user_stats['my_files'] = db.execute(
                "SELECT COUNT(*) FROM files WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
            user_stats['my_downloads'] = db.execute(
                "SELECT COALESCE(SUM(download_count), 0) FROM files WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
            user_stats['active_files'] = db.execute(
                "SELECT COUNT(*) FROM files WHERE user_id = ? AND expiry_date > ?",
                (user_id, datetime.now().isoformat())
            ).fetchone()[0]
            user_stats['expired_files'] = user_stats['my_files'] - user_stats['active_files']

            friend_count = db.execute(
                "SELECT COUNT(*) FROM friends WHERE (user_id = ? OR friend_id = ?) AND status = 'accepted'",
                (user_id, user_id)
            ).fetchone()[0]

            recent_files = db.execute(
                """SELECT original_filename, file_size, upload_date, share_token, expiry_date,
                          is_encrypted, download_count
                   FROM files WHERE user_id = ?
                   ORDER BY upload_date DESC LIMIT 5""",
                (user_id,)
            ).fetchall()
        except Exception:
            user_stats = {'my_files': 0, 'my_downloads': 0, 'active_files': 0, 'expired_files': 0}

    return render_template('Reg_Log_index.html', stats=stats, user_stats=user_stats,
                           recent_files=recent_files, friend_count=friend_count,
                           now=datetime.now().isoformat())

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
            salt = base64.b64encode(os.urandom(32)).decode('utf-8')
            password_hash = generate_password_hash(password + salt)
        
        # If single file, save normally
        if len(files) == 1:
            file = files[0]

            # Check if file type is allowed
            if not allowed_file(file.filename) or not allowed_mime_type(file.mimetype):
                flash('File type not allowed', 'error')
                return redirect(request.url)
            
            original_filename = secure_filename(file.filename)
            saved_filename = f"{token}_{original_filename}"

            # compute checksum before saving (function resets file pointer)
            checksum = compute_checksum(file)
            file_size = save_file(file, saved_filename, app.config['UPLOAD_FOLDER'])
        
        # If multiple files, create a zip
        else:
            # Create zip filename
            original_filename = f"files_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
            saved_filename = f"{token}_{original_filename}"

            # Collect files for zipping
            zip_entries = []
            for file in files:
                if file and file.filename:
                    if not allowed_file(file.filename):
                        flash(f'File type not allowed: {file.filename}', 'error')
                        continue
                    filename = secure_filename(file.filename)
                    file_data = file.read()
                    zip_entries.append((filename, file_data))

            file_size = save_zip(zip_entries, saved_filename, app.config['UPLOAD_FOLDER'])
            # compute checksum on the resulting zip file
            with open(os.path.join(app.config['UPLOAD_FOLDER'], saved_filename), 'rb') as fobj:
                checksum = compute_checksum(fobj)
            flash(f'Created zip file with {len(files)} files', 'success')
        
        # Check if file was encrypted client-side
        is_encrypted = request.form.get('is_encrypted', '0') == '1'

        # Save to database
        db = get_db()
        db.execute(
            'INSERT INTO files (filename, original_filename, file_size, share_token, user_id, expiry_date, checksum, salt, password_hash, is_encrypted) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (saved_filename, original_filename, file_size, token, user_id, expiry_date, checksum, salt, password_hash, is_encrypted)
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

        return redirect(url_for('dashboard'))
    
    # Check if link has expired
    expiry_date = datetime.fromisoformat(file_info['expiry_date'])
    if datetime.now() > expiry_date:
        flash('This link has expired', 'error')

        return redirect(url_for('dashboard'))
    
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
    
    # Verify file integrity before allowing download
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], file_info['filename'])
    try:
        with open(filepath, 'rb') as f:
            file_checksum = compute_checksum(f)
        if file_checksum != file_info['checksum']:
            flash('File integrity check failed. The file may be corrupted.', 'error')
            return redirect(url_for('dashboard'))
    except Exception:
        flash('Error verifying file integrity.', 'error')
        return redirect(url_for('dashboard'))
    
    # Increment download countf
    db.execute('UPDATE files SET download_count = download_count + 1 WHERE share_token = ?', (token,))
    db.commit()

    # For encrypted files, render client-side decryption page
    if file_info['is_encrypted']:
        return render_template('download_encrypted.html', file_info=file_info, token=token)

    # Send the file directly for non-encrypted files
    return get_file_response(
        file_info['filename'],
        file_info['original_filename'],
        app.config['UPLOAD_FOLDER'],
        as_attachment=True
    )



# User Dashboard - view all uploaded files
@app.route('/dashboard')
@login_required
def dashboard():
    user_id = session.get('user_id')
    
    db = get_db()
    
    search_query = request.args.get("q", "").strip()
    sort_option = request.args.get("sort", "newest")

    query = "SELECT * FROM files WHERE user_id = ?"
    params = [user_id]

    if search_query:
        query += " AND original_filename LIKE ?"
        params.append(f"%{search_query}%")

    if sort_option == "newest":
        query += " ORDER BY upload_date DESC"
    elif sort_option == "oldest":
        query += " ORDER BY upload_date ASC"
    elif sort_option == "largest":
        query += " ORDER BY file_size DESC"
    elif sort_option == "popular":
        query += " ORDER BY download_count DESC"
    else:
        query += " ORDER BY upload_date DESC"

    files = db.execute(query, params).fetchall()
    
    # Incoming friend requests
    incoming_requests = db.execute(
        """SELECT f.*, u.profile_picture FROM friends f
           JOIN users u ON u.user_id = f.user_id
           WHERE f.friend_id = ? AND f.status = 'pending'""",
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
        SELECT f.*, 
               CASE 
                   WHEN f.user_id = ? THEN u_friend.profile_picture
                   ELSE u_user.profile_picture
               END AS friend_profile_picture
        FROM friends f
        LEFT JOIN users u_user ON u_user.user_id = f.user_id
        LEFT JOIN users u_friend ON u_friend.user_id = f.friend_id
        WHERE (f.user_id = ? OR f.friend_id = ?) AND f.status = 'accepted'
        """,
        (user_id, user_id, user_id)
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

    row = db.execute(
        "SELECT profile_picture FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    user_profile_picture = row["profile_picture"] or None if row else None


    return render_template(
        "dashboard.html",
        files=files,
        friends=friends,
        incoming_requests=incoming_requests,
        outgoing_requests=outgoing_requests,
        shared_with_me=shared_with_me,
        user_profile_picture=user_profile_picture,
        now=datetime.now().isoformat()
    )

@app.route("/settings")
@login_required
def settings():
    user_id = session.get('user_id')
    db = get_db()

    row = db.execute(
        "SELECT profile_picture FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    user_profile_picture = row["profile_picture"] if row else None

    return render_template("settings.html", user_profile_picture=user_profile_picture)

@app.route("/change-password", methods=["POST"])
@login_required
def change_password():
    user_id = session.get('user_id')
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

    if not user or not check_password_hash(user["password"], current_password + user["salt"]):
        flash("Current password is incorrect", "error")
        return redirect(url_for("settings"))

    if new_password != confirm_password:
        flash("New passwords do not match", "error")
        return redirect(url_for("settings"))

    if len(new_password) < 6:
        flash("Password must be at least 6 characters long", "error")
        return redirect(url_for("settings"))

    if not re.search(r'\d', new_password):
        flash("Password must include at least one digit", "error")
        return redirect(url_for("settings"))
    if not re.search(r'[A-Z]', new_password):
        flash("Password must include at least one uppercase letter", "error")
        return redirect(url_for("settings"))
    if not re.search(r'[a-z]', new_password):
        flash("Password must include at least one lowercase letter", "error")
        return redirect(url_for("settings"))
    if not re.search(r'[^A-Za-z0-9]', new_password):
        flash("Password must include at least one symbol", "error")
        return redirect(url_for("settings"))

    salt = base64.b64encode(os.urandom(32)).decode('utf-8')
    password_hash = generate_password_hash(new_password + salt)

    db.execute(
        "UPDATE users SET password = ?, salt = ? WHERE user_id = ?",
        (password_hash, salt, user_id)
    )
    db.commit()

    flash("Password updated successfully", "success")
    return redirect(url_for("settings"))

# Admin dashboard
@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()

    # System stats
    stats = {}
    stats['total_users'] = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    stats['total_files'] = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    stats['total_downloads'] = db.execute("SELECT COALESCE(SUM(download_count), 0) FROM files").fetchone()[0]
    stats['encrypted_files'] = db.execute("SELECT COUNT(*) FROM files WHERE is_encrypted = 1").fetchone()[0]
    stats['active_files'] = db.execute(
        "SELECT COUNT(*) FROM files WHERE expiry_date > ?",
        (datetime.now().isoformat(),)
    ).fetchone()[0]
    stats['expired_files'] = stats['total_files'] - stats['active_files']
    stats['total_shares'] = db.execute("SELECT COUNT(*) FROM shared_files").fetchone()[0]
    stats['total_messages'] = db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    stats['total_friendships'] = db.execute(
        "SELECT COUNT(*) FROM friends WHERE status = 'accepted'"
    ).fetchone()[0]

    # Storage usage
    storage_bytes = db.execute("SELECT COALESCE(SUM(file_size), 0) FROM files").fetchone()[0]
    stats['storage_used_mb'] = round(storage_bytes / 1024 / 1024, 2)
    stats['storage_used_gb'] = round(storage_bytes / 1024 / 1024 / 1024, 2)

    # Most active users (by upload count)
    top_uploaders = db.execute("""
        SELECT user_id, COUNT(*) as file_count,
               COALESCE(SUM(file_size), 0) as total_size,
               COALESCE(SUM(download_count), 0) as total_downloads
        FROM files GROUP BY user_id
        ORDER BY file_count DESC LIMIT 10
    """).fetchall()

    # Recent uploads (last 20)
    recent_files = db.execute("""
        SELECT original_filename, file_size, user_id, upload_date, expiry_date,
               is_encrypted, download_count, share_token
        FROM files ORDER BY upload_date DESC LIMIT 20
    """).fetchall()

    # All users with their stats
    users = db.execute("""
        SELECT u.user_id, u.is_admin, u.profile_picture,
               COUNT(f.id) as file_count,
               COALESCE(SUM(f.file_size), 0) as total_size
        FROM users u
        LEFT JOIN files f ON u.user_id = f.user_id
        GROUP BY u.user_id
        ORDER BY file_count DESC
    """).fetchall()

    # Largest files
    largest_files = db.execute("""
        SELECT original_filename, file_size, user_id, upload_date, share_token
        FROM files ORDER BY file_size DESC LIMIT 10
    """).fetchall()

    return render_template("admin.html",
                           stats=stats,
                           top_uploaders=top_uploaders,
                           recent_files=recent_files,
                           users=users,
                           largest_files=largest_files,
                           now=datetime.now().isoformat())

# Toggle admin status for a user
@app.route("/admin/toggle-admin/<user_id>", methods=["POST"])
@admin_required
def toggle_admin(user_id):
    if user_id == session.get('user_id'):
        flash("You cannot change your own admin status.", "error")
        return redirect(url_for('admin_dashboard'))

    db = get_db()
    user = db.execute("SELECT is_admin FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if user is None:
        flash("User not found.", "error")
        return redirect(url_for('admin_dashboard'))

    new_status = 0 if user['is_admin'] else 1
    db.execute("UPDATE users SET is_admin = ? WHERE user_id = ?", (new_status, user_id))
    db.commit()

    action = "granted" if new_status else "revoked"
    flash(f"Admin access {action} for {user_id}.", "success")
    return redirect(url_for('admin_dashboard'))

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

    create_notification(friend_id, f"{user_id} sent you a friend request", link="/dashboard")

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

    # Notify the original sender
    sender = db.execute("SELECT requested_by FROM friends WHERE id=?", (request_id,)).fetchone()
    if sender:
        create_notification(sender["requested_by"], f"{user_id} accepted your friend request", link="/dashboard")

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
        storage_delete_file(file_info['filename'], app.config['UPLOAD_FOLDER'])
    except Exception:
        flash('Error deleting file', 'error')
    
    # Delete related shared_files and messages referencing this file
    file_id = file_info['id']
    db.execute('DELETE FROM shared_files WHERE file_id = ?', (file_id,))
    db.execute('UPDATE messages SET file_id = NULL WHERE file_id = ?', (file_id,))

    # Delete from database
    db.execute('DELETE FROM files WHERE share_token = ? AND user_id = ?', (token, user_id))
    db.commit()

    
    flash('File deleted successfully', 'success')
    return redirect(url_for('dashboard'))

# Download all files as ZIP
@app.route("/download-all")
@login_required
def download_all():
    user_id = session.get('user_id')
    db = get_db()

    # fetch checksum as well so we can verify integrity before zipping
    files = db.execute(
        """SELECT filename, original_filename, checksum FROM files
           WHERE user_id = ? AND expiry_date > ? AND is_encrypted = 0""",
        (user_id, datetime.now().isoformat())
    ).fetchall()

    if not files:
        flash('No downloadable files found. Encrypted files cannot be bulk-downloaded.', 'error')
        return redirect(url_for('dashboard'))

    zip_buffer = io.BytesIO()
    upload_folder = app.config['UPLOAD_FOLDER']
    use_cloud = os.getenv('USE_CLOUD_STORAGE', 'false').lower() == 'true'

    # Verify file integrity before adding to zip
    corrupted_files = []
    valid_files = []
    
    for f in files:
        filepath = os.path.join(upload_folder, f['filename'])
        try:
            with open(filepath, 'rb') as file_obj:
                file_checksum = compute_checksum(file_obj)
            if file_checksum != f['checksum']:
                corrupted_files.append(f['original_filename'])
            else:
                valid_files.append(f)
        except Exception:
            corrupted_files.append(f['original_filename'])
    
    if corrupted_files:
        flash(f'Cannot download. Corrupted files: {", ".join(corrupted_files)}', 'error')
        return redirect(url_for('dashboard'))
    
    files = valid_files
    
    if not files:
        flash('No valid files to download', 'error')
        return redirect(url_for('dashboard'))

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for f in files:
            if use_cloud:
                try:
                    from storage import _get_s3_client, _get_bucket
                    client = _get_s3_client()
                    bucket = _get_bucket()
                    obj = client.get_object(Bucket=bucket, Key=f['filename'])
                    zipf.writestr(f['original_filename'], obj['Body'].read())
                except Exception:
                    continue
            else:
                filepath = os.path.join(upload_folder, f['filename'])
                if os.path.exists(filepath):
                    zipf.write(filepath, f['original_filename'])

    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'sharelink-files-{user_id}.zip'
    )

# Rename a file
@app.route("/rename/<token>", methods=["POST"])
@login_required
def rename_file(token):
    user_id = session.get('user_id')
    new_name = request.form.get('new_name', '').strip()

    if not new_name:
        return jsonify({'success': False, 'error': 'Name cannot be empty'}), 400

    # Preserve the original file extension
    db = get_db()
    file_info = db.execute(
        'SELECT * FROM files WHERE share_token = ? AND user_id = ?',
        (token, user_id)
    ).fetchone()

    if file_info is None:
        return jsonify({'success': False, 'error': 'File not found'}), 404

    old_name = file_info['original_filename']
    old_ext = old_name.rsplit('.', 1)[1].lower() if '.' in old_name else ''

    # If user didn't include extension, add the original one
    if '.' not in new_name and old_ext:
        new_name = new_name + '.' + old_ext

    db.execute(
        'UPDATE files SET original_filename = ? WHERE share_token = ? AND user_id = ?',
        (new_name, token, user_id)
    )
    db.commit()

    return jsonify({'success': True, 'new_name': new_name})

# Share a file with one or more friends
@app.route("/share/<token>", methods=["POST"])
@login_required
def share_file(token):
    sender_id = session.get("user_id")
    receiver_ids = request.form.getlist("friend_ids")

    if not receiver_ids:
        flash("Please select at least one friend to share with", "error")
        return redirect(url_for("dashboard"))

    db = get_db()

    file = db.execute(
        "SELECT * FROM files WHERE share_token = ? AND user_id = ?",
        (token, sender_id)
    ).fetchone()

    if file is None:
        flash("You cannot share this file", "error")
        return redirect(url_for("dashboard"))

    shared_with = []
    skipped = []

    for receiver_id in receiver_ids:
        # Verify receiver is an accepted friend
        friendship = db.execute(
            """SELECT * FROM friends
            WHERE ((user_id = ? AND friend_id = ?) OR (user_id = ? AND friend_id = ?))
            AND status = 'accepted'""",
            (sender_id, receiver_id, receiver_id, sender_id)
        ).fetchone()

        if friendship is None:
            skipped.append(receiver_id)
            continue

        # Prevent duplicate shares
        existing = db.execute(
            "SELECT id FROM shared_files WHERE file_id = ? AND sender_id = ? AND receiver_id = ?",
            (file["id"], sender_id, receiver_id)
        ).fetchone()

        if existing:
            skipped.append(receiver_id)
            continue

        db.execute(
            "INSERT INTO shared_files (file_id, sender_id, receiver_id) VALUES (?, ?, ?)",
            (file["id"], sender_id, receiver_id)
        )
        create_notification(receiver_id, f"{sender_id} shared a file with you", link=f"/download/{token}")
        shared_with.append(receiver_id)

    db.commit()

    if shared_with:
        flash(f"File shared with: {', '.join(shared_with)}", "success")
    if skipped:
        flash(f"Could not share with: {', '.join(skipped)} (not friends or already shared)", "error")

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
    
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], file_info['filename'])
    try:
        with open(filepath, 'rb') as f:
            file_checksum = compute_checksum(f)
        if file_checksum != file_info['checksum']:
            flash('The file may be corrupted, and cannot be previewed.', 'error')
            return redirect(url_for('dashboard'))
    except Exception:
        flash('Error verifying file integrity.', 'error')
        return redirect(url_for('dashboard'))
    
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
    is_video = file_ext in ['mp4', 'mov', 'avi', 'webm']
    is_audio = file_ext in ['mp3', 'wav', 'ogg', 'flac']

    return render_template('preview.html', file_info=file_info, token=token,
                          is_image=is_image, is_pdf=is_pdf,
                          is_video=is_video, is_audio=is_audio,
                          file_ext=file_ext,
                          encryption_key=file_info['encryption_key'] or '')


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

    # Block serving if file is password-protected and not encrypted
    # (encrypted files need to be served for client-side decryption after password check)
    if file_info['password_hash'] and not file_info['is_encrypted']:
        return "This file is password protected", 403

    # Serve the file (but not as attachment, so browser can display it)
    return get_file_response(
        file_info['filename'],
        file_info['original_filename'],
        app.config['UPLOAD_FOLDER'],
        as_attachment=False
    )

# ===== Chat API Endpoints =====

def are_friends(db, user_a, user_b):
    """Check if two users have an accepted friendship."""
    return db.execute(
        """SELECT * FROM friends
           WHERE ((user_id = ? AND friend_id = ?) OR (user_id = ? AND friend_id = ?))
           AND status = 'accepted'""",
        (user_a, user_b, user_b, user_a)
    ).fetchone()



@app.route('/api/chat/friends')
@login_required
def chat_friends():
    user_id = session.get('user_id')
    db = get_db()

    friends_rows = db.execute(
        """SELECT * FROM friends
           WHERE (user_id = ? OR friend_id = ?) AND status = 'accepted'""",
        (user_id, user_id)
    ).fetchall()

    friends = []
    for f in friends_rows:
        friend_id = f['friend_id'] if f['user_id'] == user_id else f['user_id']

        unread = db.execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE sender_id = ? AND receiver_id = ? AND is_read = 0",
            (friend_id, user_id)
        ).fetchone()['cnt']

        last_msg = db.execute(
            """SELECT content, timestamp, file_id FROM messages
               WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
               ORDER BY timestamp DESC LIMIT 1""",
            (user_id, friend_id, friend_id, user_id)
        ).fetchone()

        preview = None
        if last_msg:
            if last_msg['content']:
                preview = last_msg['content']
            elif last_msg['file_id']:
                preview = '📎 Shared a file'

        friend_row = db.execute(
            "SELECT profile_picture FROM users WHERE user_id = ?",
            (friend_id,)
        ).fetchone()

        friends.append({
            'user_id': friend_id,
            'unread_count': unread,
            'last_message': preview,
            'last_message_time': last_msg['timestamp'] if last_msg else None,
            'profile_picture': friend_row['profile_picture'] if friend_row and friend_row['profile_picture'] else None
        })

    friends.sort(key=lambda x: x['last_message_time'] or '', reverse=True)
    return jsonify({'friends': friends})


@app.route('/api/chat/messages/<friend_id>')
@login_required
def chat_messages(friend_id):
    user_id = session.get('user_id')
    db = get_db()

    if not are_friends(db, user_id, friend_id):
        return jsonify({'error': 'Not friends'}), 403

    after_id = request.args.get('after', 0, type=int)

    rows = db.execute(
        """SELECT m.id, m.sender_id, m.content, m.file_id, m.timestamp,
                  f.original_filename, f.share_token
           FROM messages m
           LEFT JOIN files f ON m.file_id = f.id
           WHERE ((m.sender_id = ? AND m.receiver_id = ?)
                  OR (m.sender_id = ? AND m.receiver_id = ?))
           AND m.id > ?
           ORDER BY m.timestamp ASC""",
        (user_id, friend_id, friend_id, user_id, after_id)
    ).fetchall()

    # Mark messages from this friend as read
    db.execute(
        "UPDATE messages SET is_read = 1 WHERE sender_id = ? AND receiver_id = ? AND is_read = 0",
        (friend_id, user_id)
    )
    db.commit()

    messages = []
    for row in rows:
        messages.append({
            'id': row['id'],
            'sender_id': row['sender_id'],
            'content': row['content'],
            'file_id': row['file_id'],
            'file_name': row['original_filename'],
            'file_token': row['share_token'],
            'timestamp': row['timestamp'],
            'is_mine': row['sender_id'] == user_id
        })

    return jsonify({'messages': messages})


@app.route('/api/chat/send', methods=['POST'])
@login_required
def chat_send():
    user_id = session.get('user_id')
    db = get_db()
    data = request.get_json()

    if not data or not data.get('content', '').strip():
        return jsonify({'error': 'Message content required'}), 400

    receiver_id = data.get('receiver_id', '')
    content = data['content'].strip()

    if len(content) > 2000:
        return jsonify({'error': 'Message too long'}), 400

    if not are_friends(db, user_id, receiver_id):
        return jsonify({'error': 'Not friends'}), 403

    cursor = db.execute(
        "INSERT INTO messages (sender_id, receiver_id, content) VALUES (?, ?, ?)",
        (user_id, receiver_id, content)
    )
    db.commit()

    create_notification(receiver_id, f"New message from {user_id}", link=f"/dashboard")

    return jsonify({
        'success': True,
        'message': {
            'id': cursor.lastrowid,
            'sender_id': user_id,
            'content': content,
            'file_id': None,
            'file_name': None,
            'file_token': None,
            'timestamp': datetime.now().isoformat(),
            'is_mine': True
        }
    })


@app.route('/api/chat/share-file', methods=['POST'])
@login_required
def chat_share_file():
    user_id = session.get('user_id')
    db = get_db()
    data = request.get_json()

    receiver_id = data.get('receiver_id', '')
    file_id = data.get('file_id')

    if not file_id:
        return jsonify({'error': 'file_id required'}), 400

    if not are_friends(db, user_id, receiver_id):
        return jsonify({'error': 'Not friends'}), 403

    file_info = db.execute(
        "SELECT * FROM files WHERE id = ? AND user_id = ?",
        (file_id, user_id)
    ).fetchone()

    if not file_info:
        return jsonify({'error': 'File not found'}), 404

    cursor = db.execute(
        "INSERT INTO messages (sender_id, receiver_id, file_id) VALUES (?, ?, ?)",
        (user_id, receiver_id, file_id)
    )

    db.execute(
        "INSERT INTO shared_files (file_id, sender_id, receiver_id) VALUES (?, ?, ?)",
        (file_id, user_id, receiver_id)
    )
    db.commit()

    return jsonify({
        'success': True,
        'message': {
            'id': cursor.lastrowid,
            'sender_id': user_id,
            'content': None,
            'file_id': file_id,
            'file_name': file_info['original_filename'],
            'file_token': file_info['share_token'],
            'timestamp': datetime.now().isoformat(),
            'is_mine': True
        }
    })


@app.route('/api/chat/unread-count')
@login_required
def chat_unread_count():
    user_id = session.get('user_id')
    db = get_db()
    count = db.execute(
        "SELECT COUNT(*) as cnt FROM messages WHERE receiver_id = ? AND is_read = 0",
        (user_id,)
    ).fetchone()['cnt']
    return jsonify({'unread_count': count})


@app.route('/api/chat/my-files')
@login_required
def chat_my_files():
    user_id = session.get('user_id')
    db = get_db()
    files = db.execute(
        """SELECT id, original_filename, share_token FROM files
           WHERE user_id = ? AND expiry_date > ?
           ORDER BY upload_date DESC""",
        (user_id, datetime.now().isoformat())
    ).fetchall()
    return jsonify({
        'files': [{'id': f['id'], 'original_filename': f['original_filename'], 'share_token': f['share_token']} for f in files]
    })



def cleanup_expired_files():
    """Remove expired files from storage and database."""
    import sqlite3
    from database import DATABASE
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    expired = conn.execute(
        "SELECT * FROM files WHERE expiry_date < ?",
        (datetime.now().isoformat(),)
    ).fetchall()

    for f in expired:
        try:
            storage_delete_file(f['filename'], UPLOAD_FOLDER)
        except Exception:
            pass
        conn.execute('DELETE FROM shared_files WHERE file_id = ?', (f['id'],))
        conn.execute('UPDATE messages SET file_id = NULL WHERE file_id = ?', (f['id'],))
        conn.execute('DELETE FROM files WHERE id = ?', (f['id'],))

    conn.commit()
    conn.close()
    return len(expired)

@app.route('/api/notifications')
@login_required
def get_notifications():
    user_id = session.get("user_id")
    db = get_db()

    rows = db.execute(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY timestamp DESC LIMIT 20",
        (user_id,)
    ).fetchall()

    return jsonify({
        "notifications": [
            {
                "id": r["id"],
                "message": r["message"],
                "link": r["link"],
                "is_read": r["is_read"],
                "timestamp": r["timestamp"]
            }
            for r in rows
        ]
    })


@app.route('/api/notifications/mark-read', methods=['POST'])
@login_required
def mark_notifications_read():
    user_id = session.get("user_id")
    db = get_db()
    db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (user_id,))
    db.commit()
    return jsonify({"success": True})



if __name__ == '__main__':
    # Clean up expired files on startup
    with app.app_context():
        removed = cleanup_expired_files()
        if removed:
            print(f"Cleaned up {removed} expired file(s)")
    app.run(debug=os.getenv('FLASK_DEBUG', 'false').lower() == 'true')