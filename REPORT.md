# ShareLink: Building a Secure File-Sharing Platform

## CS3305 Team Software Project -- Team 9

Dylan Bennett (123346983), Lukan Prenderville,
Robin Bastible, Jamie O'Donovan

---

## 1. The Problem

Sharing files between people should be simple. In practice, it rarely is.
Cloud services like Google Drive and Dropbox demand accounts, impose storage
limits, and retain copies of your data indefinitely. Link-sharing tools such as
WeTransfer are convenient but offer no encryption, no friend lists, and no way
to keep track of who you have shared what with. Meanwhile, if you want the
files to live on your own machine rather than someone else's server, the
options thin out quickly.

We wanted something different: a self-contained application that lets you
upload a file, get a shareable link, and send that link to friends -- all
without surrendering your files to a third party. The files should expire
automatically, be optionally encrypted end-to-end, and the whole thing should
run as a desktop app that a non-technical user can double-click to launch.

ShareLink is our answer to that problem.

## 2. Existing Solutions and Their Gaps

We surveyed several existing tools before settling on our approach.

**Google Drive / Dropbox / OneDrive.** These are mature products with polished
UIs, but they require accounts on both ends, store files on remote servers, and
make it difficult to enforce expiration. Privacy-conscious users have
legitimate concerns about where their data lives.

**WeTransfer.** WeTransfer lets you share files via a link with no account
required on the receiver's end, which is close to what we wanted. However, it
offers no social features, no encryption beyond TLS in transit, and files are
stored on WeTransfer's infrastructure. Firefox Send was an excellent
privacy-focused alternative, but Mozilla shut it down in 2020 after abuse
problems.

## 3. Architecture Overview

ShareLink has three layers that nest inside each other like Russian dolls:

1. **Flask backend** -- a Python web server that handles all business logic:
   authentication, file storage, sharing, chat, and administration.
2. **SQLite database** -- a single file that stores users, files metadata,
   friendships, shared-file records, and chat messages.
3. **Electron shell** -- a desktop wrapper that spawns the Flask server as a
   child process and displays it in a Chromium window.

When a user launches ShareLink.app, Electron starts, spawns a bundled
PyInstaller binary of the Flask server on port 5050, polls until it responds,
and then loads `http://127.0.0.1:5050/` in a BrowserWindow. When the user
closes the window, Electron sends SIGTERM to Flask and exits. The user never
sees a terminal, a Python interpreter, or a browser address bar.

For web deployment (we also host on PythonAnywhere), the same Flask app runs
behind a WSGI server. The `app_paths.py` module resolves the correct data
directory at runtime -- `sys.executable`'s parent when frozen by PyInstaller,
or the project directory in development.

## 4. The Backend: Flask in Depth

The Flask server is the heart of ShareLink. At roughly 1,400 lines, `app.py`
contains over 20 route handlers grouped into several functional areas.

### Authentication

User registration enforces password complexity: minimum six characters with
at least one digit, one uppercase letter, one lowercase letter, and one
symbol. Passwords are hashed with bcrypt over a 32-byte random salt stored
alongside each user record. Login includes rate limiting -- five failed
attempts within five minutes locks out the IP address. Error messages are
deliberately generic to prevent username enumeration.

### File Upload and Download

Uploading is the core workflow. A user selects one or more files, optionally
sets an expiration (24 hours, 7 days, or 30 days), an access password, and
an end-to-end encryption toggle. Multiple files are automatically zipped
server-side. Every upload receives a unique share token (a 16-character
URL-safe random string) and a SHA-256 checksum computed at upload time.

On download, the server recomputes the checksum and compares it to the stored
value. If they differ, the download is blocked and the user is warned of
possible corruption. This integrity check also runs during bulk "Download All
as ZIP" operations.

### The Storage Abstraction

Early on, we knew we might want cloud storage alongside local files.
`storage.py` provides a clean abstraction: functions like `save_file()`,
`get_file_response()`, and `delete_file()` dispatch to either local filesystem
operations or Cloudflare R2 (an S3-compatible service) depending on the
`USE_CLOUD_STORAGE` environment variable. This was a deliberate decision to
keep the rest of the codebase storage-agnostic. Adding a new storage backend
would mean implementing four functions in `storage.py` without touching
`app.py`.

### End-to-End Encryption

Password protection and encryption are separate features in ShareLink.
Password protection is server-side: the server stores a bcrypt hash and
requires it before serving the file. The server can still read the file
contents. End-to-end encryption is client-side: the browser generates an
AES-256-GCM key, encrypts the file before uploading, and embeds the key in
the URL fragment (the part after `#`, which browsers never send to the
server). The recipient's browser extracts the key and decrypts locally. The
server never sees the plaintext. This means encrypted files cannot be
previewed server-side or shared through the dashboard -- the user must share
the full link directly.

## 5. Social Features: Friends and Chat

A file-sharing tool that only generates links is useful but impersonal. We
added a friends system and a chat widget to make ShareLink feel more like a
communication tool.

### Friends

Users can search for other users by username and send friend requests. The
`friends` table stores bidirectional relationships with a `status` field
(`pending` or `accepted`) and a `requested_by` field to track who initiated.
All sharing and messaging operations verify an active friendship before
proceeding.

### Chat

The chat widget lives in `base.html` as a floating panel available on every
page. It polls the server every three seconds for new messages and every ten
seconds for the unread badge count.

Messages can include file attachments. When a user shares a file through the
chat, the server creates both a `messages` row (with a `file_id` reference)
and a `shared_files` row, so the file also appears in the recipient's "Files
Shared With Me" section on the dashboard.

### Group Sharing

The initial share form was a single dropdown -- pick one friend, click Share.
Users quickly wanted to share with multiple friends at once. We replaced the
dropdown with a checkbox list, changed the backend from
`request.form.get("friend_id")` to `request.form.getlist("friend_ids")`, and
added a loop that validates each recipient individually. Duplicate shares are
silently skipped, and the flash message tells the user exactly who received
the file and who was skipped.

## 6. The Frontend: Themes and Templates

ShareLink uses Jinja2 templates with a single `base.html` that provides the
header, navigation, chat widget, toast notification system, and theme
selection. Individual pages extend this base and fill in content blocks.

### Theming

We support four themes: Dark (the default), Light, Solarized, and Cherry
Blossom. Themes are implemented entirely in CSS using custom properties
(`var(--primary)`, `var(--bg)`, etc.) and the `[data-theme]` attribute on
the `<html>` element. A small inline script applies the saved theme from
`localStorage` before the page renders, preventing a flash of the wrong
theme. Adding a new theme requires only a new `[data-theme="name"]` block
in `styles.css` and a new `<option>` in the template.

## 7. The Desktop Shell: Electron and PyInstaller

Packaging a Python web server as a desktop application is not straightforward.
The user should not need Python installed, should not need to run terminal
commands, and should not see a console window.

### PyInstaller

PyInstaller compiles the Flask application and all its dependencies into a
standalone binary. The `--add-data` flag bundles the `templates/` and
`static/` directories, and `--hidden-import` flags capture dynamically
imported packages that PyInstaller's static analysis misses. The resulting
binary is roughly 60 MB.

### Electron

Electron wraps this binary in a native desktop application. `main.js` handles
the lifecycle: it auto-generates a `.env` file with a random `SECRET_KEY` on
first launch, spawns the PyInstaller binary, polls port 5050 until Flask
responds, then opens a BrowserWindow. On quit, Electron sends SIGTERM on
macOS/Linux or uses `taskkill` on Windows. We chose port 5050 because macOS
reserves port 5000 for AirPlay Receiver. The final `.app` bundle is around
340 MB (Electron framework plus PyInstaller binary plus static assets).

## 8. Administration

The admin dashboard (`/admin`) provides a bird's-eye view of the system:
total users, total files, total downloads, encrypted file count, and storage
usage. It lists the top uploaders, displays a user management table where
admins can toggle admin privileges, and shows a browsable file list.

Admin access is controlled by an `is_admin` column in the `users` table and
an `@admin_required` decorator. The first admin must be set manually in the
database; subsequent admins can be promoted through the dashboard.

## 9. Deployment

ShareLink runs in two modes:

**Desktop** -- the Electron-wrapped application described above. The user
downloads a `.app` (macOS) or `.exe` installer (Windows) and runs it. Data
is stored next to the executable.

**Web** -- deployed on PythonAnywhere with a WSGI entry point (`wsgi.py`).
The same Flask app serves over HTTPS at `dben07.pythonanywhere.com`. File
storage is local to the PythonAnywhere filesystem, and the database is a
SQLite file in the project directory.

Environment configuration is handled through a `.env` file. The only required
variable is `SECRET_KEY`; cloud storage credentials are optional. An
`.env.example` template is provided in the repository.

## 10. Challenges and Lessons Learned

**Path resolution across environments.** The same code runs in three
contexts: development (`python app.py`), PyInstaller binary, and
PythonAnywhere. Each resolves file paths differently. We created
`app_paths.py` as a single source of truth, using
`getattr(sys, 'frozen', False)` to detect the PyInstaller environment.
This eliminated an entire class of deployment bugs.

**macOS code signing.** Our first electron-builder attempt failed because
macOS extended attributes on files inside the PyInstaller output triggered
code-signing validation. The fix required stripping extended attributes with
`xattr -cr`, disabling automatic signing in the build config, and setting
environment variables to skip identity discovery. This took several hours to
diagnose.

**Polling versus WebSockets for chat.** We chose polling for simplicity.
The trade-off is a three-second delay on message delivery. For a file-sharing
app with occasional messages this is acceptable, but a production system with
heavy chat usage would benefit from WebSockets.

**SQLite in production.** SQLite works well for single-user desktop mode and
light web traffic. Under concurrent writes from multiple users on
PythonAnywhere, it occasionally raises locking errors. For a larger
deployment, switching to PostgreSQL would require changing only the
connection code in `database.py`.

## 11. Use of Generative AI

We used Claude (Anthropic) extensively as a development assistant through
Claude Code, an AI-powered command-line tool. Claude assisted with feature
implementation (chat system, admin dashboard, group sharing, themes),
debugging platform-specific issues (macOS code signing, PyInstaller hidden
imports), the entire Electron packaging pipeline, PythonAnywhere deployment,
and drafting this report. Every generated snippet was reviewed and tested
before committing. The tool was particularly valuable for boilerplate-heavy
tasks and for diagnosing obscure platform-specific errors where the solution
exists in documentation but is hard to find. All commits that involved Claude
assistance include a `Co-Authored-By` trailer.

## 12. Contributions

**Dylan Bennett** -- Project lead. Core Flask application
(file upload, download, sharing, dashboard). Electron wrapper
and PyInstaller packaging. Cloud storage integration
(Cloudflare R2). Chat/messaging system. Admin dashboard.
Homepage UI. Bug fixes across all components. PythonAnywhere
deployment.

**Lukan Prenderville** -- User registration and login system.
Friend system (add, accept, decline, unfriend). Profile
pictures and settings page. File search and sort
functionality.

**Robin Bastible** -- Password security (salting, bcrypt
hashing, minimum requirements). Login failure message
hardening. File integrity system (SHA-256 checksums on
upload/download). Bulk download integrity checks.
Corruption-safe file preview. Colour themes (Dark, Light,
Solarized, Cherry Blossom).

**Jamie O'Donovan** -- Tailwind CSS dashboard prototype and
exploration. UV package manager support investigation.

---

*ShareLink is open source and available at
<https://github.com/cs-ucc-ie/CS3305-2026-Team-9>.*
