# ShareLink

A secure file-sharing web application built with Flask. Upload files, generate shareable links with QR codes, and share directly with friends via built-in chat. Supports optional end-to-end encryption, cloud storage (Cloudflare R2), and runs as a desktop app via Electron.

## Features

- **File Sharing** — Upload files, get a shareable link and QR code. Set expiry times (24h, 7d, 30d).
- **End-to-End Encryption** — Optional password-based encryption (PBKDF2) performed client-side before upload.
- **Password Protection** — Optionally require a password to download files.
- **Social Features** — Add friends, share files directly, and chat in real time.
- **Cloud Storage** — Store files locally or on Cloudflare R2.
- **Theming** — 5 built-in themes (Dark, Light, Dracula, Solarized, Cherry Blossom).
- **Admin Dashboard** — Manage users and monitor the system.
- **Desktop App** — Runs as a native desktop app via Electron + PyInstaller.
- **File Integrity** — SHA-256 checksums verify files haven't been tampered with.

## Tech Stack

| Layer     | Technology                          |
|-----------|-------------------------------------|
| Backend   | Flask 3.0, SQLite, Python 3        |
| Frontend  | Jinja2, vanilla JS, CSS            |
| Storage   | Local filesystem / Cloudflare R2   |
| Desktop   | Electron 40, PyInstaller           |
| Security  | bcrypt, CSRF protection, AES-256-GCM |

## Setup

### Prerequisites

- Python 3.10+
- Node.js 20+ (only for desktop app)

### Installation

```bash
# Clone the repo
git clone https://github.com/cs-ucc-ie/CS3305-2026-Team-9.git
cd CS3305-2026-Team-9

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration

```bash
# Copy the example env file
cp .env.example .env
```

Edit `.env` and set your values:

```
SECRET_KEY=generate-a-random-key-here
FLASK_DEBUG=false
USE_CLOUD_STORAGE=false

# Cloudflare R2 (only if USE_CLOUD_STORAGE=true)
R2_ACCESS_KEY_ID=your-access-key
R2_SECRET_ACCESS_KEY=your-secret-key
R2_ENDPOINT_URL=https://your-account-id.r2.cloudflarestorage.com
R2_BUCKET_NAME=your-bucket-name
```

### Run (Web)

```bash
python app.py
```

The app starts at `http://127.0.0.1:5000/`.

### Run (Desktop)

```bash
npm install
npm start
```

### Build Desktop App

```bash
# macOS
npm run build:mac

# Windows
npm run build:win
```

## Project Structure

```
├── app.py              # Main Flask application
├── database.py         # SQLite schema and initialization
├── storage.py          # Storage abstraction (local / R2)
├── forms.py            # WTForms for login and registration
├── app_paths.py        # Path resolution (dev vs PyInstaller)
├── wsgi.py             # WSGI entry point for deployment
├── main.js             # Electron main process
├── requirements.txt    # Python dependencies
├── package.json        # Node.js config and build scripts
├── templates/          # Jinja2 HTML templates
└── static/             # CSS, JS, icons
```

## Team

- Dylan Bennett
- Jamie O Donovan
- Robin Dowd
- Luka Nergadze
