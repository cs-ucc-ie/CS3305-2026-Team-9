# ShareLink: Building a Secure File-Sharing Platform

## CS3305 Team Software Project -- Team 9

**Jamie O'Donovan** -- Student Number: 121776739\
**Luka Nergadze** -- Student Number: 122421516\
**Dylan Bennett** -- Student Number: 123346983\
**Robin Dowd** -- Student Number: 123446296

GitHub: <https://github.com/cs-ucc-ie/CS3305-2026-Team-9>

---

### Academic Honesty Declaration

We, the undersigned members of Team 9, declare that this report and the
accompanying software project are our own original work. All external sources
have been cited. Where generative AI tools were used during development, their
use is disclosed in Section 12 of this report. We have read and understand
UCC's policy on academic integrity and confirm that this submission complies
with it.

Signed:\
Jamie O'Donovan\
Luka Nergadze\
Dylan Bennett\
Robin Dowd

---

\newpage

\newpage

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
stored on WeTransfer's infrastructure.

**Firefox Send (discontinued).** Mozilla once offered an encrypted file-sharing
service that worked through the browser. It was simple and private, but Mozilla
shut it down in 2020 due to abuse. The core idea -- encrypt in the browser,
share a link, let the link expire -- was a strong influence on our design.

**What ShareLink does differently.** Our goal was to combine the best parts of
these tools: the simplicity of WeTransfer's share-a-link model, the privacy of
Firefox Send's client-side encryption, and the social features of a messaging
app. We added a friends list, a real-time chat widget, configurable link
expiration, file previews, and an admin dashboard. The result is a platform
that works both as a hosted web service and as a standalone desktop
application.

\newpage

## 3. Architecture Overview

ShareLink has three layers that combine to create our product:

1. **Flask backend** -- a Python web server that handles all business logic:
   authentication, file storage, sharing, chat, and administration.
2. **SQLite database** -- a single file that stores users, file metadata,
   friendships, shared-file records, chat messages, and notifications.
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

The diagram below illustrates how these layers connect:

```text
+-------------------------------------------------+
|                Electron Shell                   |
|  (main.js: spawns Flask, opens BrowserWindow)   |
+-------------------------------------------------+
                      |
               http://127.0.0.1:5050
                      |
+-------------------------------------------------+
|              Flask Application                  |
|   (app.py: routes, auth, upload, chat, admin)   |
|                                                 |
|   +----------+  +-----------+  +-------------+ |
|   | storage  |  | database  |  |   forms      | |
|   | .py      |  | .py       |  |   .py        | |
|   +----------+  +-----------+  +-------------+ |
+-------------------------------------------------+
        |                  |
  +-----+------+    +-----+------+
  | Local disk |    |  SQLite    |
  | or R2 cloud|    |  .db file  |
  +------------+    +------------+
```

The Flask app sits at the centre. It exposes over twenty routes grouped into
five categories: authentication, file operations, social features, chat API,
and administration. Each category is described in the sections that follow.

\newpage

## 4. The Backend: Flask in Depth

The Flask server is the heart of ShareLink. The single `app.py` file contains
over 1,500 lines of code and more than twenty routes that handle everything
from user registration to real-time chat. Supporting modules -- `database.py`,
`storage.py`, `forms.py`, and `app_paths.py` -- keep the core file focused on
request handling.

### 4.1 Application Initialisation

When the app starts, the following happens in order:

1. `app_paths.py` determines the data directory. If the app is running inside
   a PyInstaller bundle, it uses the directory containing the frozen
   executable. Otherwise, it uses the script's own directory. This lets the
   same code work in development, on PythonAnywhere, and inside the Electron
   app.
2. The `.env` file is loaded using `python-dotenv`. This must happen before
   importing `storage.py`, because the storage module reads
   `USE_CLOUD_STORAGE` at import time to decide whether to initialise the
   boto3 S3 client.
3. The Flask app is created with CSRF protection enabled via Flask-WTF.
4. `database.py`'s `init_db()` function creates all tables if they do not
   exist and runs any pending migrations (for example, adding the
   `profile_picture` column to the `users` table).
5. Three `before_request` hooks are registered:
   - `periodic_cleanup()` deletes expired files at most once per hour.
   - `logged_in_user()` sets `g.user` from the session.
   - `load_profile_picture()` queries the database for the current user's
     avatar and admin status, making them available to every template via
     Flask's `g` object.

### 4.2 Authentication

User registration enforces password complexity: minimum six characters with
at least one digit, one uppercase letter, one lowercase letter, and one
symbol. These rules are enforced twice: once by WTForms validators in
`forms.py` (so the form cannot be submitted without meeting the requirements),
and again server-side in the `change_password` route (which does not go through
WTForms). Passwords are hashed with Werkzeug's `generate_password_hash`
function, which uses PBKDF2 internally. A 32-byte random salt is generated per
user, stored in the `salt` column, and appended to the password before hashing.
This means even two users with the same password will have different hashes.

Login includes rate limiting. An in-memory dictionary maps IP addresses to
lists of timestamps. If an IP accumulates five failed attempts within five
minutes, further login attempts are rejected with a generic error message. The
error messages for wrong username and wrong password are deliberately identical
-- the form says "Username or password incorrect" in both cases -- to prevent
an attacker from enumerating valid usernames.

Session management is straightforward: on successful login, `session["user_id"]`
is set. A `login_required` decorator checks `g.user` and redirects to the login
page if it is `None`. The login page accepts a `next` query parameter so the
user is returned to the page they were trying to reach. The `next` parameter is
validated to ensure it starts with a single slash (not `//`), which prevents
open-redirect attacks.

### 4.3 File Upload

Uploading is the core workflow. The upload page presents a drag-and-drop zone
built with vanilla JavaScript. When the user drops files (or clicks to browse),
the file names are displayed beneath the drop zone. The form also offers three
options:

- **Link expiry**: 24 hours, 7 days, or 30 days. The server validates the
  submitted value against a whitelist of `{24, 168, 720}` hours and defaults
  to 24 if anything unexpected arrives.
- **Password protection**: an optional password that will be required before
  the file can be downloaded or previewed.
- **End-to-end encryption**: if a password is provided, the file is encrypted
  client-side before it ever leaves the browser (more on this in Section 4.5).

When the form is submitted, JavaScript intercepts the submit event. If a
password was provided, the file is encrypted in the browser using the Web
Crypto API before being sent. The upload itself uses `XMLHttpRequest` rather
than `fetch` because XHR provides granular upload progress events -- the user
sees a progress bar showing percentage, uploaded size, and speed in real time.

On the server side, the upload route:

1. Validates that at least one file was selected.
2. Checks each file's extension and MIME type against whitelists. The allowed
   extensions include common document, image, audio, and video formats -- 18
   types in total.
3. If multiple files were selected, bundles them into a single ZIP archive
   using Python's `zipfile` module with `ZIP_DEFLATED` compression.
4. Generates a unique share token using `secrets.token_urlsafe(16)`.
5. Computes a SHA-256 checksum of the file contents.
6. Saves the file to storage (local or cloud, depending on configuration).
7. Creates a database record with the token, original filename, file size,
   upload date, expiry date, checksum, and encryption status.
8. Returns a JSON response to the XHR request containing the redirect URL.

The maximum file size is 100 MB, enforced by Flask's `MAX_CONTENT_LENGTH`
setting.

### 4.4 File Download and Integrity Verification

When someone visits a download link (`/download/<token>`), the server:

1. Looks up the file by its share token.
2. Checks whether the link has expired by comparing the stored `expiry_date`
   against the current time.
3. If the file is password-protected (and not encrypted), renders a password
   form. The entered password is concatenated with the stored salt and checked
   against the stored hash using `check_password_hash`.
4. Recomputes the SHA-256 checksum of the stored file and compares it to the
   checksum recorded at upload time. If they differ, the download is blocked
   and the user sees a corruption warning. This catches bit-rot, incomplete
   writes, and any tampering with the stored file.
5. If the file is encrypted, renders a client-side decryption page instead of
   sending the raw bytes.
6. Otherwise, sends the file as an attachment using Flask's `send_file` or
   the storage module's streaming response.

The same integrity check runs during "Download All as ZIP" operations, which
bundle all of a user's active, non-encrypted files into a single ZIP. Encrypted
files are excluded from bulk downloads because they require client-side
decryption.

### 4.5 End-to-End Encryption

When a user provides a password on upload, the file is encrypted in the browser
before it is transmitted to the server. The server only ever sees encrypted
bytes -- it cannot read the file contents.

The encryption uses the Web Crypto API with the following parameters:

- **Key derivation**: PBKDF2 with 100,000 iterations, SHA-256, and a random
  16-byte salt.
- **Cipher**: AES-256-GCM with a random 12-byte initialisation vector (IV).
- **File layout**: the encrypted output is structured as
  `[16 bytes salt | 12 bytes IV | ciphertext]`. This layout is critical
  because the salt and IV must be extracted before decryption can proceed.

The encryption flow works as follows:

1. The user types a password into the upload form.
2. JavaScript generates a random 16-byte salt using `crypto.getRandomValues`.
3. The password is imported as raw key material and passed to
   `crypto.subtle.deriveKey` with the PBKDF2 parameters above, producing a
   256-bit AES-GCM key.
4. A random 12-byte IV is generated.
5. The file contents are encrypted with `crypto.subtle.encrypt` using AES-GCM.
6. The salt, IV, and ciphertext are concatenated into a single `Uint8Array`,
   which is wrapped in a `Blob` and uploaded to the server.
7. The form also sends `is_encrypted=1` so the server knows to flag the file.

On download, the reverse happens:

1. The recipient visits the download link and sees a password prompt.
2. After entering the password, JavaScript fetches the encrypted file from the
   server's `/serve/<token>` endpoint.
3. The first 16 bytes are extracted as the salt, the next 12 as the IV, and
   the remainder as the ciphertext.
4. The password and salt are fed through the same PBKDF2 parameters to
   re-derive the AES-GCM key.
5. `crypto.subtle.decrypt` attempts decryption. AES-GCM includes an
   authentication tag, so if the password is wrong, decryption fails with a
   clear error rather than producing garbage output.
6. On success, the decrypted bytes are wrapped in a Blob and triggered as a
   browser download.

The same decryption logic is duplicated in `preview.html` so that encrypted
images, PDFs, videos, and audio files can be previewed in the browser after
decryption. The preview page detects the file type and renders the decrypted
blob using the appropriate HTML element (`<img>`, `<iframe>`, `<video>`, or
`<audio>`).

This design means the server never has access to plaintext file contents or
the encryption key. The password exists only in the user's browser during
encryption and decryption. If the server's storage were compromised, an
attacker would find only encrypted blobs with no way to derive the keys.

### 4.6 The Storage Abstraction

Early on, we knew we might want cloud storage alongside local files.
`storage.py` provides a clean abstraction: four functions -- `save_file()`,
`save_zip()`, `get_file_response()`, and `delete_file()` -- dispatch to either
local filesystem operations or Cloudflare R2 (an S3-compatible service)
depending on the `USE_CLOUD_STORAGE` environment variable.

This was a deliberate decision to keep the rest of the codebase
storage-agnostic. The `app.py` file never calls `os.path.join` or `boto3`
directly for file operations -- it always goes through `storage.py`. Adding a
new storage backend (AWS S3, Google Cloud Storage, etc.) would mean
implementing four functions without touching `app.py`.

The local implementation is straightforward: `save_file` calls
`file.save(path)`, `get_file_response` calls Flask's `send_from_directory`,
and `delete_file` calls `os.remove`.

The cloud implementation uses `boto3` to interact with Cloudflare R2:

- `save_file` calls `client.put_object` with the file bytes.
- `save_zip` creates a temporary file, writes the ZIP locally, uploads it via
  `client.upload_file`, and deletes the temporary file.
- `get_file_response` streams the S3 object body in 8,192-byte chunks,
  wrapping it in a Flask `Response` with appropriate content-type and
  content-disposition headers.
- `delete_file` calls `client.delete_object`.

The boto3 client is lazily initialised: it is only created when
`USE_CLOUD_STORAGE` is `true`, so the `boto3` library does not need to be
installed for local-only deployments.

### 4.7 File Preview

ShareLink supports inline previews for several file types. The `/preview/<token>`
route determines the file type from its extension and passes boolean flags
(`is_image`, `is_pdf`, `is_video`, `is_audio`) to the template.

For non-encrypted files, the template renders the appropriate HTML element
pointing at the `/serve/<token>` endpoint, which streams the raw file with
`as_attachment=False` so the browser displays it inline.

For encrypted files, the preview page shows a password form. After decryption
(using the same PBKDF2 / AES-GCM logic described above), the decrypted bytes
are rendered in a dynamically created element. For example, an encrypted JPEG
is decrypted into a `Blob`, converted to an object URL, and displayed in an
`<img>` tag.

The `/serve/<token>` endpoint includes a security check: it refuses to serve
password-protected non-encrypted files directly, since those require the
password form flow. Encrypted files are allowed through because the raw bytes
are ciphertext and useless without the password.

### 4.8 QR Code Generation

Every uploaded file gets a QR code generated server-side using the `qrcode`
Python library. The QR code encodes the file's download URL and is rendered as
a base64-encoded PNG embedded directly in the success page's `<img>` tag. This
lets users share files by scanning a code with their phone -- useful in
face-to-face sharing scenarios.

### 4.9 Automatic Expiry and Cleanup

Every file has an `expiry_date` stored in the database. A `periodic_cleanup`
function runs as a `before_request` hook, executing at most once per hour. It
queries for all files past their expiry date, deletes the physical files from
storage, removes associated `shared_files` records, nullifies `file_id`
references in chat messages, and finally deletes the database rows. The
function opens its own database connection (rather than using Flask's `g`
object) so it can run safely outside a request context -- for example, on
application startup.

\newpage

## 5. Social Features: Friends and Chat

A file-sharing tool that only generates links is useful but impersonal. We
added a friends system and a chat widget to make ShareLink feel more like a
communication tool.

### 5.1 Friends

Users can search for other users by username and send friend requests. The
`friends` table stores bidirectional relationships with a `status` field
(`pending` or `accepted`) and a `requested_by` field to track who initiated.
The friend request flow handles several edge cases:

- Self-requests are rejected.
- Duplicate requests are detected by querying both directions of the
  relationship (`user_id/friend_id` and `friend_id/user_id`).
- Non-existent usernames produce a clear error.

When a friend request is sent, a notification is created for the recipient.
Accepting a request updates the status to `accepted` and notifies the sender.
Declining deletes the row entirely. Unfriending deletes the friendship row in
both directions.

All sharing and messaging operations verify an active friendship before
proceeding, so there is no way to send files or messages to someone who has not
accepted your request.

### 5.2 Chat

The chat widget lives in `base.html` as a floating panel available on every
page. It is implemented with vanilla JavaScript in `chat.js` (307 lines) and
communicates with the server through four JSON API endpoints:

| Endpoint                        | Method | Purpose                          |
|---------------------------------|--------|----------------------------------|
| `/api/chat/friends`             | GET    | List friends with unread counts  |
| `/api/chat/messages/<friend_id>`| GET    | Fetch conversation messages      |
| `/api/chat/send`                | POST   | Send a text message              |
| `/api/chat/share-file`          | POST   | Share a file in chat             |

The chat uses polling rather than WebSockets. Messages are fetched every three
seconds; the unread badge count is updated every ten seconds. While WebSockets
would provide lower latency, polling was simpler to implement and works
reliably across all deployment environments (PythonAnywhere does not support
WebSockets on free plans).

The polling is incremental: each request includes an `after` parameter set to
the ID of the last message received. The server returns only messages with IDs
greater than this value, so each poll transfers only new messages rather than
the entire conversation history.

Messages can include file attachments. When a user shares a file through the
chat, the server creates both a `messages` row (with a `file_id` reference)
and a `shared_files` row, so the file also appears in the recipient's "Files
Shared With Me" section on the dashboard.

The chat UI includes XSS protection: an `escapeHtml` function replaces `<`,
`>`, `&`, `"`, and `'` with their HTML entity equivalents before inserting
message content into the DOM.

### 5.3 Notifications

A notification system ties together the social features. Notifications are
created server-side whenever a relevant event occurs:

- A friend request is sent or accepted.
- A file is shared with you.
- A new chat message arrives.

Each notification has a message, an optional link, a read status, and a
timestamp. The dashboard displays a notification bell with an unread badge.
Clicking the bell opens a dropdown showing the twenty most recent
notifications. A JavaScript polling loop checks for new notifications and
shows a toast popup when something new arrives.

### 5.4 Group Sharing

The initial share form was a single dropdown -- pick one friend, click Share.
Users quickly wanted to share with multiple friends at once. We replaced the
dropdown with a checkbox list, changed the backend from
`request.form.get("friend_id")` to `request.form.getlist("friend_ids")`, and
added a loop that validates each recipient individually. Duplicate shares are
silently skipped, and the flash message tells the user exactly who received
the file and who was skipped.

\newpage

## 6. The Frontend: Themes and Templates

ShareLink uses Jinja2 templates with a single `base.html` that provides the
header, navigation, chat widget, toast notification system, and theme
selection. Individual pages extend this base and fill in content blocks.

### 6.1 Template Architecture

The template hierarchy is flat: every page template extends `base.html`
directly. There are twenty templates in total:

- **Core pages**: `index.html` (unauthenticated), `Reg_Log_index.html`
  (authenticated home), `dashboard.html`, `settings.html`, `admin.html`
- **Authentication**: `register.html`, `login.html`
- **File operations**: `upload.html`, `success.html`, `preview.html`,
  `download_encrypted.html`, `password_check.html`
- **Error pages**: `400.html`, `403.html`, `404.html`, `405.html`,
  `413.html`, `418.html`, `500.html`

The `base.html` template handles several cross-cutting concerns:

- **CSRF tokens**: a `<meta>` tag contains the CSRF token for JavaScript to
  read when making AJAX requests.
- **Theme initialisation**: an inline `<script>` runs before the page renders,
  reading the saved theme from `localStorage` and setting a `data-theme`
  attribute on `<html>`. This prevents a flash of the wrong theme on page
  load.
- **Conditional navigation**: the header shows different links depending on
  whether the user is logged in and whether they have admin privileges.
- **Profile picture**: if the user has uploaded an avatar, it appears next to
  their username in the header.

### 6.2 Theming

The theming system is built entirely with CSS custom properties (also known as
CSS variables). The `:root` selector defines the default theme (a Material
Design dark theme), and `[data-theme="..."]` selectors override these
variables for each alternative theme. There are five themes in total:

**Dark** (default). A Material Design-inspired dark theme with `#121212`
background, `#1E1E1E` cards, and blue (`#3b82f6`) accents. The elevation
system uses semi-transparent white overlays at varying opacities (5% to 16%)
to create depth without relying solely on shadows.

**Light**. A clean white theme with `#f5f7fb` background, white cards, and a
subtle radial gradient. Shadows are lighter (8% opacity instead of 40%), and
overlay colours are inverted (semi-transparent black instead of white).

**Solarized**. Uses `#002b36` (base03) as the background with `#268bd2` (blue) as the primary
accent. The palette's carefully calibrated contrast ratios ensure readability
across all contexts.

**Cherry Blossom**. A pink theme with `#ffeaf0` background and
`#e91e63` (hot pink) accents. Overlays use semi-transparent pink instead of
black or white, giving the entire interface a warm tint.

**Dracula**. Uses `#282a36` background with `#bd93f9` (purple) accents and `#ff79c6` (pink) hover states.
The palette includes distinctive colours for success (`#50fa7b` green), danger
(`#ff5555` red), and warnings (`#f1fa8c` yellow).

The theme selector is a `<select>` element in the header. When the user picks
a theme, a `changeTheme()` function updates the `data-theme` attribute and
saves the choice to `localStorage`. Because every colour in the stylesheet
references a CSS variable, the entire interface updates instantly with no page
reload.

The `color-scheme` property is set to `dark` for Dark, Solarized, and Dracula,
and to `light` for Light and Cherry Blossom. This tells the browser to style
its native UI elements (scrollbars, form controls) appropriately.

All theme transitions are animated with a CSS transition on `background-color`
and `color` properties (0.3 seconds ease), so switching themes feels smooth
rather than jarring.

### 6.3 Toast Notifications

The toast system provides ephemeral feedback messages. The `showToast(message,
type)` function creates a `<div>` with a CSS class matching the type (success,
error, info, or warning), animates it in with a slide transition, and
automatically removes it after three seconds. Flash messages from Flask are
rendered through the same system for visual consistency.

### 6.4 The Upload UI

The upload page deserves special mention because it handles several UX
challenges:

- **Drag and drop**: the drop zone listens for `dragenter`, `dragover`,
  `dragleave`, and `drop` events. Visual feedback (a highlighted border)
  indicates when files are being dragged over the zone.
- **Keyboard accessibility**: the drop zone has `tabindex="0"` and responds
  to Enter and Space key presses, opening the file picker for users who
  cannot use a mouse.
- **Progress tracking**: the upload uses XHR rather than `fetch` because XHR's
  `upload.onprogress` event provides real-time byte counts. The progress bar
  shows percentage, uploaded size, upload speed (computed from elapsed time),
  and total size.
- **Encryption feedback**: if a password is set, the progress title changes
  from "Uploading Files..." to "Encrypting Files..." during the encryption
  phase, then to "Uploading Encrypted Files..." during the upload phase.

\newpage

## 7. The Desktop Shell: Electron and PyInstaller

Packaging a Python web server as a desktop application is not straightforward.
The user should not need Python installed, should not need to run terminal
commands, and should not see a console window.

### 7.1 PyInstaller

PyInstaller bundles the Flask application and all its Python dependencies into
a single executable. The spec file configures PyInstaller to include the
`templates/` and `static/` directories as data files. The resulting binary
contains an embedded Python interpreter, all imported modules, and the web
assets. When run, it extracts these to a temporary directory and executes
`app.py`.

### 7.2 Electron

Electron wraps this binary in a native desktop application. `main.js` (150
lines) handles the lifecycle:

1. **Environment setup**: on first launch, Electron checks for a `.env` file
   in the user data directory. If one does not exist, it creates one with a
   random `SECRET_KEY` (32 bytes hex), `FLASK_DEBUG=false`, and
   `USE_CLOUD_STORAGE=false`.
2. **Process spawning**: `startFlask()` spawns the PyInstaller binary as a
   child process. Standard output and error are piped to the Electron
   console for debugging.
3. **Health check**: `waitForFlask()` polls `http://127.0.0.1:5050` up to 30
   times at 500ms intervals (15 seconds total). The BrowserWindow is not
   loaded until Flask responds, preventing the user from seeing a blank
   page.
4. **Window creation**: the BrowserWindow is 1200 by 800 pixels with
   `nodeIntegration` disabled and `contextIsolation` enabled for security.
   A persistent session partition (`persist:sharelink`) ensures cookies and
   storage survive between launches.
5. **Shutdown**: when the user closes the window, Electron sends SIGTERM on
   macOS/Linux or uses `taskkill /f /t` on Windows, then exits.

### 7.3 Path Resolution

The `app_paths.py` module is small but critical. It contains a single function,
`get_user_data_dir()`, which returns:

- The directory containing `sys.executable` when running as a PyInstaller
  bundle (because PyInstaller sets `sys.frozen` to `True`).
- The directory containing the script file (`__file__`) in development.

This function is used by `database.py` to locate the SQLite database, by
`app.py` to find the `.env` file and upload directory, and indirectly by
`main.js` (which sets the working directory before spawning Flask). It
ensures that the same codebase works in three different environments --
development, PythonAnywhere, and the Electron app -- without any path
hardcoding.

### 7.4 Bundle Size

The final `.app` bundle is around 340 MB. This is large by desktop application
standards, but unavoidable: it includes the Electron framework (~120 MB), the
Chromium renderer, the Python interpreter, and all Python dependencies
(Flask, bcrypt, boto3, qrcode, Pillow, etc.). No network connection is
required after installation.

\newpage

## 8. Administration

The admin dashboard (`/admin`) provides a bird's-eye view of the system. It
displays a statistics grid showing:

| Statistic          | Source                                         |
|--------------------|------------------------------------------------|
| Total users        | `COUNT(*)` from `users`                        |
| Total files        | `COUNT(*)` from `files`                        |
| Total downloads    | `SUM(download_count)` from `files`             |
| Encrypted files    | `COUNT(*)` where `is_encrypted = 1`            |
| Active files       | `COUNT(*)` where `expiry_date > now()`         |
| Expired files      | Total files minus active files                 |
| Total shares       | `COUNT(*)` from `shared_files`                 |
| Total messages     | `COUNT(*)` from `messages`                     |
| Total friendships  | `COUNT(*)` from `friends` where `accepted`     |
| Storage used       | `SUM(file_size)` from `files`, shown in MB/GB  |

Below the statistics, the dashboard shows a top-ten uploaders table (ranked by
file count, showing total size and downloads), a list of the twenty most recent
uploads, all registered users with their upload counts, and the ten largest
files.

Admin access is controlled by an `is_admin` column in the `users` table and
an `@admin_required` decorator that checks both authentication and admin
status. The first admin must be set manually in the database (by updating the
column directly); subsequent admins can be promoted or demoted through the
dashboard. An admin cannot change their own admin status, preventing
accidental self-demotion.

\newpage

## 9. Deployment

ShareLink runs in two modes:

### 9.1 Desktop

The Electron-wrapped application described in Section 7. The user downloads
a `.app` (macOS) or `.exe` installer (Windows) and runs it. Data is stored
next to the executable. No internet connection is required.

### 9.2 Web

Deployed on PythonAnywhere with a WSGI entry point (`wsgi.py`). The WSGI file
adds the project directory to `sys.path`, changes the working directory so that
relative paths (for the uploads folder and database) resolve correctly, and
imports the Flask app as `application`.

The same Flask app serves over HTTPS at `https://dben07.pythonanywhere.com`. File
storage uses Cloudflare R2 (an S3-compatible object storage service), keeping
the PythonAnywhere filesystem light. The database is a SQLite file in the
project directory.

Environment configuration is handled through a `.env` file. The only required
variable is `SECRET_KEY`; cloud storage credentials (`R2_ACCESS_KEY_ID`,
`R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT_URL`, `R2_BUCKET_NAME`) are optional. An
`.env.example` template is provided in the repository.

\newpage

## 10. Error Handling

ShareLink registers custom error handlers for seven HTTP status codes, each
rendering a themed template consistent with the rest of the application:

| Code | Meaning                 | When It Fires                          |
|------|-------------------------|----------------------------------------|
| 400  | Bad Request             | Malformed form data or invalid input   |
| 403  | Forbidden               | Accessing another user's resources     |
| 404  | Not Found               | Invalid URL or deleted file            |
| 405  | Method Not Allowed      | GET on a POST-only route               |
| 413  | Payload Too Large       | Upload exceeds 100 MB limit            |
| 418  | I'm a Teapot            | Easter egg                             |
| 500  | Internal Server Error   | Unhandled exception in a route         |

Beyond HTTP errors, the upload route wraps its entire body in a `try/except`
block. If any exception occurs during file processing, the error is logged
with `app.logger.error` (including a full traceback via `exc_info=True`), and
the user receives either a JSON error (for XHR uploads) or a flash message
(for traditional form submissions).

\newpage

## 11. Lessons Learned

### 11.1 SQLite Limitations

SQLite served us well as a single-file database, but its lack of concurrent
write support became noticeable during testing. If two users upload files at
the exact same moment, one write will block until the other completes. For a
team project with modest traffic, this was acceptable. For a production service
with hundreds of concurrent users, we would migrate to PostgreSQL.

### 11.2 Polling vs. WebSockets

The chat widget polls every three seconds. This creates unnecessary network
traffic when no messages are being sent. WebSockets would be more efficient,
but they require a long-lived connection that not all hosting environments
support. PythonAnywhere's free tier, which we used for deployment, does not
support WebSockets. Given the project's scope, polling was the pragmatic
choice.

### 11.3 Client-Side Encryption Tradeoffs

Encrypting files in the browser provides strong privacy guarantees, but it
comes with limitations. Files must fit in memory (the Web Crypto API operates
on `ArrayBuffer` objects), so very large files could cause the browser tab to
crash. A streaming encryption approach using the Streams API would solve this
but would add significant complexity.

### 11.4 Bundle Size

The 340 MB Electron bundle is large. Tools like Tauri (which uses the OS's
native web renderer instead of bundling Chromium) could reduce this to under
30 MB. We chose Electron because of its mature ecosystem and extensive
documentation, but for a future iteration, Tauri would be worth investigating.

\newpage

## 12. Use of Generative AI

We used Claude Code as a development aid throughout the project. Its primary
role was debugging: identifying and fixing issues such as XSS vulnerabilities
in the notification dropdown, missing CSRF tokens, path resolution problems
in the PyInstaller bundle, and import ordering issues with the cloud storage
module.

Claude Code also assisted with:

- Diagnosing the upload route's silent failure when XHR requests received
  redirect responses instead of JSON.
- Rewriting the encrypted file preview logic when we migrated from URL-fragment
  key distribution to password-based PBKDF2 key derivation.
- Reviewing the codebase for submission readiness and identifying dead code.
- Identifying and resolving CSS inconsistencies across the interface.

All AI-generated code was reviewed and tested by team members before being
merged. Claude AI was used to write the framework of the report, this outline was then review by team members and modified to fit within our project needs.

\newpage

## 13. Contributions

### Dylan Bennett

I built the core backend of the application: the initial file upload and
download routes, the SQLite database schema, and the Flask application
structure. From there I added features incrementally -- link expiration with
selectable durations, the user dashboard, and file management operations
(delete, rename, download all as ZIP). I also built the drag-and-drop upload
UI with real-time progress tracking (percentage, speed, and uploaded size) and
added multi-file upload support where selecting multiple files bundles them
into a single ZIP archive server-side.

I implemented the file preview system, which supports inline previews for
images, PDFs, video, and audio files. For encrypted files, the preview page
decrypts the file client-side before rendering it in the appropriate HTML
element. I also added login rate limiting to prevent brute-force attacks and
password complexity rules to enforce strong passwords.

I built the real-time chat system: a floating chat widget available on every
page, backed by four JSON API endpoints and a 307-line `chat.js` module that
polls for new messages every three seconds using incremental fetching. Users
can send text messages and share files directly through the chat. I also
implemented group file sharing, replacing the single-friend dropdown with a
multi-select checkbox list so users can share a file with several friends in
one action, with duplicate-share detection.

I built the admin dashboard, which displays system-wide statistics (total
users, files, downloads, storage used, encrypted file count), a top-ten
uploaders table, the twenty most recent uploads, and user management with
the ability to promote or demote admins. I also implemented the automatic
expired file cleanup system, which runs as a `before_request` hook at most
once per hour, deleting expired files from storage and cascading the removal
through related database tables.

I added cloud storage support through Cloudflare R2, implementing the
`storage.py` abstraction that lets the app switch between local and cloud
storage via an environment variable. I also implemented the Electron wrapper
(`main.js`) that bundles the Flask server into a native desktop application
using PyInstaller, including the health check polling, automatic `.env`
generation, and platform-aware process cleanup.

I deployed the web version to PythonAnywhere, writing the `wsgi.py` entry
point and configuring the R2 bucket for cloud file storage. I also implemented
the file integrity system using SHA-256 checksums, the QR code generation for
share links, and the end-to-end encryption system using PBKDF2 and AES-256-GCM.

### Luka Nergadze

The first thing I did was ensuring that only registered users could use the
platform. I built the registration and login system using Flask-WTF for form
handling and validation. Dylan further improved this with rate limiting and
password complexity rules.

To enable social features on the platform I implemented a friend system. This
required extending the database with a `friends` table that tracks
relationships between users using a status field to represent pending and
accepted requests. I added routes in `app.py` to cover the full lifecycle of
a friendship -- sending requests, accepting, declining, and unfriending. The
send request route handles edge cases including non-existent users,
self-requests, and duplicate requests. The dashboard was updated both on the
backend (to query and pass friend data to the template) and on the frontend in
`dashboard.html`, where sections were added for friend lists, incoming
requests, and outgoing pending requests.

To improve the usability of the dashboard for files, I added file search and
sorting functionality. Search is handled using SQL `LIKE` queries filtered by
the user's input. The sorting is done by conditionally changing the `ORDER BY`
clause based on the dropdown selection, with options for newest, oldest,
largest, and most downloaded.

I also added a settings page accessible from the dashboard. The main feature I
added to settings is profile picture upload. Images are saved to the
`static/profiles` directory, the filename is stored in a column in the `users`
table, and the picture is loaded on every request by a `before_request` hook so
it appears next to the username across the entire site. I also integrated
profile pictures into the chat -- the `/api/chat/friends` API endpoint was
updated to join the users table and include each friend's profile picture in
the JSON response. The same approach was applied to incoming friend requests
on the dashboard.

I also added a notification system that alerts users to messages, friend
requests, and file shares. A `notifications` table was added to the database.
Two API endpoints were created: one to fetch notifications for the current user
and one to mark them all as read. On the frontend I added a notification bell
with an unread badge to the dashboard, opening a dropdown of notifications on
click. A JavaScript polling loop runs to check for new notifications and
update the badge count, with a toast popup appearing immediately when something
new arrives.

### Jamie O'Donovan

My primary contribution to the development of ShareLink was the frontend user experience. 
I initially implemented this using Tailwind CSS, but determined it was more of a time sink than
it was worth, and moved forward without a frontend or CSS framework. From there, I improved 
the UX using vanilla JavaScript and CSS, with a focus on responsiveness — ensuring
the webapp adapts seamlessly across a range of display resolutions. The stylesheet is organised
into discrete sections (themes, header, cards, forms, buttons, page-specific blocks,responsive
tweaks, chat, and toasts), functioning as a single source of truth for the webapp's visual design. 
UX states are managed through class toggles such as `hidden`, `show`, and status modifier classes,
rather than relying on component libraries.

The key UX behaviours I implemented include:
- Consistent styling across pages (border radius, button sizing, etc.)
- Grid/list toggle for file views
- Default and compact dashboard layout options
- A hamburger menu replacing inline action buttons to conserve space on the dashboard
- An expansion of the theme selector originally implemented by Robin

I also contributed minor fixes when encountering logic errors during development, and added
error pages for standard HTTP responses (403, 404, etc.).

### Robin Dowd

My primary contributions to the project revolved around the security of users files. Our End to End encryption system originally used AES-GCM, placing the code in the shared link to decrypt, however, once we expanded to being able to send files directly, this was no longer sufficient. Instead, we implemented PBKDF2, basing the encryption on the password placed on a file.

I also ensured that passwords and other sensitive data were stored as securely as possible. Passwords are hashed and encrypted, held to minimum standards, and our user input sections are protected from SQL Injection. 

I also expanded the theme selector from just Light and Dark, to having several other themes with room to easily add more.

\newpage

---

*ShareLink is open source and available at
<https://github.com/cs-ucc-ie/CS3305-2026-Team-9>.*
