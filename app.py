import os
import secrets
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, session, g
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from database import get_db, init_db
from werkzeug.security import generate_password_hash, check_password_hash
from forms import RegistrationForm, LoginForm
from functools import wraps
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key')
app.config['WTF_CSRF_ENABLED'] = False

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
        password = form.password.data

        db = get_db()
        clashing_user = db.execute(
            """SELECT * FROM users WHERE user_id = ?;""",
            (user_id,)
        ).fetchone()

        if clashing_user is not None:
            form.user_id.errors.append("Username already exists")
            db.close()
        else:
            db.execute(
                """INSERT INTO users (user_id, password) VALUES (?, ?);""",
                (user_id, generate_password_hash(password))
            )
            db.commit()
            db.close()
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
        db.close()

        if user is None:
            form.password.errors.append("No such user")
        elif not check_password_hash(user["password"], password):
            form.password.errors.append("incorrect password")
        else:
            session.clear()
            session["user_id"] = user_id
            next_page = request.args.get("next")
            if not next_page:
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

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_token():
    """Generate a unique random token for sharing"""
    return secrets.token_urlsafe(16)

# Homepage route
@app.route('/')
def index():
    return render_template('Reg_Log_index.html')

# Upload route
@app.route('/upload', methods=['GET', 'POST'])
@login_required
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
        
        # Get expiration time from form (in hours)
        expiry_hours = int(request.form.get('expiry', 24))  # Default 24 hours
        expiry_date = datetime.now() + timedelta(hours=expiry_hours)

        
        # Save to database
        db = get_db()
        db.execute(
            'INSERT INTO files (filename, original_filename, file_size, share_token, expiry_date) VALUES (?, ?, ?, ?, ?)',
            (saved_filename, original_filename, file_size, token, expiry_date)
        )
        db.commit()
        db.close()
        
        # Redirect to success page with token
        return redirect(url_for('upload_success', token=token))
    
    return render_template('upload.html')

# Upload success page - shows the shareable link
@app.route('/success/<token>')
@login_required
def upload_success(token):
    db = get_db()
    file_info = db.execute('SELECT * FROM files WHERE share_token = ?', (token,)).fetchone()
    db.close()
    
    if file_info is None:
        flash('File not found', 'error')
        return redirect(url_for('index'))
    
    return render_template('success.html', file_info=file_info, token=token)

@app.route('/download/<token>')
@login_required
def download(token):
    db = get_db()
    file_info = db.execute('SELECT * FROM files WHERE share_token = ?', (token,)).fetchone()
    
    if file_info is None:
        flash('File not found or link expired', 'error')
        db.close()
        return redirect(url_for('index'))
    
    # Check if link has expired
    expiry_date = datetime.fromisoformat(file_info['expiry_date'])
    if datetime.now() > expiry_date:
        flash('This link has expired', 'error')
        db.close()
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