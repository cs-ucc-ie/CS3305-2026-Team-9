import sqlite3
import os
from flask import g

# Use absolute path so it works on PythonAnywhere
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, 'sharelink.db')

def get_db():
    """Get database connection, reusing per-request if available"""
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

def close_db(e=None):
    """Close database connection at end of request"""
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    """Initialize the database with tables"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # create user table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            salt TEXT NOT NULL,
            password TEXT NOT NULL
        )
                   ''')
    
    #Add profile picture
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN profile_picture TEXT")
    except Exception:
        pass  # Column already exists

    # Add is_admin column
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
    except Exception:
        pass  # Column already exists
    
    # Create files table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        original_filename TEXT NOT NULL,
        file_size INTEGER NOT NULL,
        share_token TEXT UNIQUE NOT NULL,
        user_id TEXT NOT NULL,
        upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        download_count INTEGER DEFAULT 0,
        expiry_date TIMESTAMP NOT NULL,
        salt TEXT,
        password_hash TEXT,
        is_encrypted BOOLEAN DEFAULT 0
    )
''')
    
    # Add a friend table
    cursor.execute(''' 
    CREATE TABLE IF NOT EXISTS friends (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        friend_id TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        requested_by TEXT NOT NULL       
    )
    ''')

    # Shared files table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS shared_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER NOT NULL,
        sender_id TEXT NOT NULL,
        receiver_id TEXT NOT NULL,
        shared_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Messages table for chat
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id TEXT NOT NULL,
        receiver_id TEXT NOT NULL,
        content TEXT,
        file_id INTEGER,
        is_read INTEGER DEFAULT 0,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Migration: add is_encrypted column to existing databases
    try:
        cursor.execute('ALTER TABLE files ADD COLUMN is_encrypted BOOLEAN DEFAULT 0')
    except Exception:
        pass  # Column already exists

    # Migration: add encryption_key column to existing databases
    try:
        cursor.execute('ALTER TABLE files ADD COLUMN encryption_key TEXT')
    except Exception:
        pass  # Column already exists

    conn.commit()
    conn.close()
    print("Database initialized successfully!")

if __name__ == '__main__':
    init_db()
