import sqlite3
import os

DATABASE = 'sharelink.db'

def get_db():
    """Connect to the database"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row  # Return rows as dictionaries
    return conn

def init_db():
    """Initialize the database with tables"""
    conn = get_db()
    cursor = conn.cursor()

    # create user table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            salt TEXT NOT NULL,
            password TEXT NOT NULL
        )
                   ''')
    
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
        password_hash TEXT
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
    
    conn.commit()
    conn.close()
    print("Database initialized successfully!")

if __name__ == '__main__':
    init_db()
