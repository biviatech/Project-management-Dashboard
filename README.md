# Enterprise Tech Project Management Dashboard

## Overview
A modern, full-featured Flask + Firebase dashboard for managing technology projects, teams, deployments, and business growth.

## Core Features Summary

### Dashboard Overview
- Total Projects, Hosted Projects, Local Projects, In Development, Completed Projects
- Project Health Summary with color indicators
- Real-time analytics with Chart.js (Revenue trends, Status distribution)

### Project Management
- Full CRUD for Projects (Create/Edit/Delete)
- Status Tracking (Idea → Planning → In Development → Testing → Hosted → Completed → Archived)
- Categories, Priorities, Progress Tracking (percentage)
- Rich details: Description, Technology Stack, Notes

### Task Management
- Full CRUD for Tasks (sub-collection)
- Kanban Board (Backlog, To Do, In Progress, Testing, Completed) with drag & drop
- Assign tasks, Due Dates, Priorities, Status

### Hosting & Deployment
- Live URLs, Hosting Provider, Domain/SSL Tracking
- Deployment History placeholder
- Local Folder Paths & GitHub/GitLab links

### File & Document Management
- Firebase Storage ready for uploads (Screenshots, PDFs, ZIPs)
- Markdown & Rich Notes support

### Search & Analytics
- Global Search + Filters (Status, Tech, Category)
- Reports: Projects by Status, Task Completion, Progress Metrics

### Additional
- Firebase Auth (Email + Google)
- Dark/Light Mode
- Responsive Design
- Real-time updates via Firestore listeners

## Setup
1. `pip install -r requirements.txt`
2. Replace Firebase config in `app/static/js/script.js`
3. Set `GOOGLE_APPLICATION_CREDENTIALS` to your Firebase service account JSON file.
4. `python run.py`
5. Visit `http://127.0.0.1:5000`
6. Sign in or create an account from `/login` using Firebase Auth.

## Firebase Login Reliability

The permanent secure fix for server login verification is a Firebase service account JSON file.

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS = 'C:\path\to\service-account.json'
python run.py
```

For local development, the app also includes an offline fallback so login does not constantly fail when the server cannot reach Google's token verification endpoints. The browser must still sign in with Firebase first, and the server checks the token project, issuer, expiry, UID, and email. To disable this local fallback for stricter production behavior:

```powershell
$env:FIREBASE_AUTH_ALLOW_UNVERIFIED_FALLBACK = '0'
```

## Archive Password (optional extra protection)

The `/archive` page requires a second password in addition to normal login. Set the environment variable `ARCHIVE_PASSWORD_HASH` to a werkzeug password hash. To generate a hash locally:

```python
from werkzeug.security import generate_password_hash
print(generate_password_hash('your-strong-password'))
```

Then set the value in your environment (Windows PowerShell example):

```powershell
$env:ARCHIVE_PASSWORD_HASH = '<paste-hash-here>'
```

For convenience during development you can also set `ARCHIVE_PASSWORD` (plain text), but this is NOT recommended for production.

### Firestore storage (recommended for Firebase users)

The archive password hash is stored centrally in Firestore.

1. Create a Google service account with Firestore access and download the JSON key.
2. Set the environment variable `GOOGLE_APPLICATION_CREDENTIALS` to the path of the JSON key file, e.g. in PowerShell:

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS = 'C:\path\to\service-account.json'
$env:GOOGLE_APPLICATION_CREDENTIALS = 'vernal-maker-500205-g5-52d95311e416.json'
```

3. From the admin UI (`/archive-admin`) sign in and set the archive password — the server will store only the hash in Firestore under collection `settings` with the document ID `archive_password_hash`.

Firestore must be configured for server-side settings, roles, audit logs, and sessions.

### Role-based access control

This app supports simple role-based access. Roles are looked up from Firestore `users` collection (document ID = user's email) and the server reads the `role` field. Example Firestore document for an admin:

```
Collection: users
Document ID: alice@example.com
{
	"name": "Alice Admin",
	"role": "admin"
}
```

If a role is not set in Firestore, the server uses the `DEFAULT_ROLE` env var (default: `user`). The `/archive-admin` page requires the `admin` role.

## Firebase Rules (Recommended)
Secure your Firestore collections with proper rules for production.

Built as a complete command center for tech entrepreneurs.


2. In project disable duplicate projects from being added or new project. 3. In the health status if it is an project and it loads the health status should show. 4 in tyhe documentation part add place to upload file and make the UI for reading the text or file smart and cool
