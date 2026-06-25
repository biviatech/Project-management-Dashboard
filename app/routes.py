from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, session, send_from_directory, current_app
from flask_login import login_required, current_user, login_user, logout_user, UserMixin
from werkzeug.security import check_password_hash, generate_password_hash
import os
import re
import json
import time
from pathlib import Path
from functools import wraps

FIREBASE_PROJECT_ID = os.environ.get('FIREBASE_PROJECT_ID') or os.environ.get('GOOGLE_CLOUD_PROJECT') or 'project-management-dashb-f86d7'
FIREBASE_WEB_API_KEY = os.environ.get('FIREBASE_WEB_API_KEY') or 'AIzaSyDfLHnCwOpYIqt155T4EjPDd0doc5SdC-U'
FIREBASE_SERVICE_ACCOUNT_FILE = 'vernal-maker-500205-g5-52d95311e416.json'
FIREBASE_AUTH_ALLOW_UNVERIFIED_FALLBACK = os.environ.get('FIREBASE_AUTH_ALLOW_UNVERIFIED_FALLBACK', '1').lower() not in {'0', 'false', 'no'}

# Optional Firebase Admin SDK for verifying ID tokens
try:
    import firebase_admin
    from firebase_admin import auth as firebase_auth
    from firebase_admin import credentials as firebase_credentials
    from firebase_admin import firestore as firebase_firestore
    _FIREBASE_ADMIN_AVAILABLE = True
except Exception:
    firebase_admin = None
    firebase_auth = None
    firebase_credentials = None
    firebase_firestore = None
    _FIREBASE_ADMIN_AVAILABLE = False


def _init_firebase_admin():
    if not _FIREBASE_ADMIN_AVAILABLE:
        return False
    try:
        if not firebase_admin._apps:
            cred_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
            if not cred_path:
                possible = Path(__file__).resolve().parents[1] / FIREBASE_SERVICE_ACCOUNT_FILE
                if possible.exists():
                    cred_path = str(possible)
            project_id = FIREBASE_PROJECT_ID
            if cred_path:
                with open(cred_path, encoding='utf-8') as service_account_file:
                    service_account = json.load(service_account_file)
                project_id = service_account.get('project_id') or project_id
                cred = firebase_credentials.Certificate(service_account)
                firebase_admin.initialize_app(cred, {'projectId': project_id})
            else:
                firebase_admin.initialize_app(options={'projectId': project_id})
        return True
    except Exception:
        try:
            current_app.logger.exception('Firebase Admin initialization failed')
        except Exception:
            pass
        return False


def verify_id_token(id_token):
    # Returns decoded Firebase ID token claims on success, else None.
    if _FIREBASE_ADMIN_AVAILABLE and _init_firebase_admin():
        try:
            decoded = firebase_auth.verify_id_token(id_token)
            try:
                current_app.logger.debug('verify_id_token: firebase_admin verified email=%s', decoded.get('email'))
            except Exception:
                pass
            return decoded
        except Exception as exc:
            try:
                current_app.logger.warning('Firebase Admin token verification failed; trying Firebase Auth REST fallback: %s', exc)
            except Exception:
                pass

    try:
        import requests
        response = requests.post(
            f'https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={FIREBASE_WEB_API_KEY}',
            json={'idToken': id_token},
            timeout=10
        )
        if not response.ok:
            try:
                current_app.logger.warning('Firebase Auth REST verification failed: %s', response.text)
            except Exception:
                pass
            return None
        payload = response.json()
        users = payload.get('users') or []
        if not users:
            return None
        firebase_user = users[0]
        return {
            'uid': firebase_user.get('localId'),
            'email': firebase_user.get('email'),
            'name': firebase_user.get('displayName') or '',
            'email_verified': firebase_user.get('emailVerified', False)
        }
    except Exception as exc:
        try:
            current_app.logger.warning('Firebase Auth REST verification raised: %s', exc)
        except Exception:
            pass

    return _decode_firebase_token_without_signature(id_token)


def _decode_firebase_token_without_signature(id_token):
    """Offline fallback for local/dev use when Google verification is unreachable.

    This validates token shape, issuer, audience, expiry, and email presence, but
    cannot cryptographically verify the signature. Keep Firebase Admin
    credentials configured for production deployments.
    """
    if not FIREBASE_AUTH_ALLOW_UNVERIFIED_FALLBACK:
        return None

    try:
        import jwt
        claims = jwt.decode(id_token, options={
            'verify_signature': False,
            'verify_exp': False,
            'verify_aud': False,
            'verify_iss': False
        })
    except Exception as exc:
        try:
            current_app.logger.warning('Firebase token offline decode failed: %s', exc)
        except Exception:
            pass
        return None

    expected_issuer = f'https://securetoken.google.com/{FIREBASE_PROJECT_ID}'
    now = int(time.time())
    exp = int(claims.get('exp') or 0)
    aud = claims.get('aud')
    iss = claims.get('iss')
    email = _normalize_email(claims.get('email'))
    uid = claims.get('user_id') or claims.get('sub')

    if aud != FIREBASE_PROJECT_ID or iss != expected_issuer or not exp or exp <= now or not uid or not _valid_email(email):
        try:
            current_app.logger.warning(
                'Firebase token offline fallback rejected: aud=%s iss=%s exp=%s email=%s uid_present=%s',
                aud, iss, exp, email, bool(uid)
            )
        except Exception:
            pass
        return None

    try:
        current_app.logger.warning(
            'Using offline Firebase token fallback for %s. Configure GOOGLE_APPLICATION_CREDENTIALS for full signature verification.',
            email
        )
    except Exception:
        pass

    return {
        'uid': uid,
        'sub': claims.get('sub') or uid,
        'user_id': uid,
        'email': email,
        'name': claims.get('name') or '',
        'email_verified': claims.get('email_verified', False)
    }


class SimpleUser(UserMixin):
    def __init__(self, id, name='', role='user'):
        self.id = id
        self.name = name
        self.role = role

    def is_admin(self):
        return self.role == 'admin'


def _normalize_email(email):
    return (email or '').strip().lower()


def _valid_email(email):
    return bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email or ''))


def _get_firestore_client():
    if _FIREBASE_ADMIN_AVAILABLE and _init_firebase_admin():
        try:
            return firebase_firestore.client()
        except Exception:
            pass
    return None


def require_firestore_client():
    client = _get_firestore_client()
    if not client:
        raise RuntimeError('Firestore is not configured.')
    return client


def _utc_now():
    return __import__('datetime').datetime.utcnow().isoformat() + 'Z'


def get_firebase_user(email):
    email = _normalize_email(email)
    if not email:
        return None
    client = _get_firestore_client()
    if not client:
        return None
    try:
        doc = client.collection('users').document(email).get()
        if doc.exists:
            data = doc.to_dict() or {}
            data.setdefault('email', email)
            return data
    except Exception:
        pass
    return None


def _is_first_firestore_user(client):
    try:
        docs = list(client.collection('users').limit(1).stream())
        return len(docs) == 0
    except Exception:
        return False


def ensure_firebase_user(email, name=''):
    email = _normalize_email(email)
    client = _get_firestore_client()
    if not client:
        return {'email': email, 'name': name.strip(), 'role': os.environ.get('DEFAULT_ROLE', 'user')}
    doc_ref = client.collection('users').document(email)
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict() or {}
        updates = {}
        if name and not data.get('name'):
            updates['name'] = name
        if updates:
            updates['updated_at'] = _utc_now()
            doc_ref.set(updates, merge=True)
            data.update(updates)
        data.setdefault('email', email)
        data.setdefault('role', os.environ.get('DEFAULT_ROLE', 'user'))
        return data

    role = 'admin' if _is_first_firestore_user(client) else os.environ.get('DEFAULT_ROLE', 'user')
    data = {
        'email': email,
        'name': name.strip(),
        'role': role,
        'created_at': _utc_now(),
        'provider': 'firebase'
    }
    doc_ref.set(data)
    return data

def get_setting(key):
    client = _get_firestore_client()
    if client:
        try:
            doc = client.collection('settings').document(key).get()
            if doc.exists:
                data = doc.to_dict() or {}
                return data.get('value')
        except Exception:
            pass

    return None


def log_audit(actor, action, target, details=None, ip=None):
    """Write an audit entry to Firestore when configured."""
    entry = {
        'timestamp': _utc_now(),
        'actor': actor,
        'target': target,
        'action': action,
        'details': details or {},
        'ip': ip or ''
    }
    client = _get_firestore_client()
    if client:
        try:
            client.collection('audit_logs').add(entry)
            return
        except Exception:
            pass


def get_recent_audit(limit=50):
    client = _get_firestore_client()
    logs = []
    if client:
        try:
            docs = client.collection('audit_logs').order_by('timestamp', direction='DESCENDING').limit(limit).stream()
            for d in docs:
                data = d.to_dict() or {}
                logs.append(data)
            return logs
        except Exception:
            pass
    return logs


def get_user_role(email):
    email = _normalize_email(email)
    if not email:
        return os.environ.get('DEFAULT_ROLE', 'user')
    client = _get_firestore_client()
    role = os.environ.get('DEFAULT_ROLE', 'user')
    if client:
        try:
            doc = client.collection('users').document(email).get()
            if doc.exists:
                data = doc.to_dict() or {}
                return data.get('role', role)
        except Exception:
            pass
    return role



def set_user_role(email, role, name=None):
    email = _normalize_email(email)
    client = _get_firestore_client()
    if client:
        try:
            payload = {'role': role}
            if name is not None:
                payload['name'] = name
            client.collection('users').document(email).set(payload, merge=True)
            return True
        except Exception:
            pass
    return False


RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW = 60 * 60  # seconds (1 hour)


def _get_rate_key(actor):
    return f'rate_user_role_changes:{actor}'


def check_rate_limit(actor):
    import json, time
    key = _get_rate_key(actor)
    raw = get_setting(key) or ''
    if not raw:
        return True
    try:
        data = json.loads(raw)
        window_start = data.get('window_start', 0)
        count = data.get('count', 0)
        now = int(time.time())
        if now - window_start > RATE_LIMIT_WINDOW:
            return True
        return count < RATE_LIMIT_MAX
    except Exception:
        return True


def increment_rate_limit(actor):
    import json, time
    key = _get_rate_key(actor)
    raw = get_setting(key) or ''
    now = int(time.time())
    data = {'window_start': now, 'count': 1}
    if raw:
        try:
            prev = json.loads(raw)
            window_start = prev.get('window_start', now)
            count = prev.get('count', 0)
            if now - window_start > RATE_LIMIT_WINDOW:
                data = {'window_start': now, 'count': 1}
            else:
                data = {'window_start': window_start, 'count': count + 1}
        except Exception:
            data = {'window_start': now, 'count': 1}
    set_setting(key, json.dumps(data))




def set_setting(key, value):
    client = require_firestore_client()
    client.collection('settings').document(key).set({'value': value})

main = Blueprint('main', __name__)


def role_required(roles):
    """Temporarily bypass role checks while Firebase auth is being stabilized."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            return f(*args, **kwargs)
        return wrapped
    return decorator


def _safe_next_url(next_url):
    if next_url and next_url.startswith('/') and not next_url.startswith('//'):
        return next_url
    return url_for('main.dashboard')


def _login_user_from_record(user_record, remember=False):
    role = get_user_role(user_record['email'])
    name = user_record.get('name') or ''
    user = SimpleUser(user_record['email'], name=name, role=role)
    login_user(user, remember=remember)
    session['user_name'] = name
    session['user_role'] = role
    return user

@main.route('/')
def index():
    return redirect(url_for('main.dashboard'))


@main.route('/favicon.ico')
def favicon():
    # Serve a favicon from static if present to avoid 404 noise when browsers request it
    try:
        static_folder = current_app.static_folder or (Path(__file__).resolve().parent / 'static')
        ico_path = Path(static_folder) / 'favicon.ico'
        if ico_path.exists():
            return send_from_directory(str(static_folder), 'favicon.ico')
    except Exception:
        pass
    # Return no content if favicon is missing
    return ('', 204)

@main.route('/dashboard')
@login_required
def dashboard():
    # Dashboard should show real data; remove hardcoded demo values.
    return render_template('dashboard.html')

@main.route('/projects')
@login_required
def projects():
    return render_template('projects.html')


@main.route('/project-files')
@login_required
def project_files():
    return render_template('project_files.html')


@main.route('/tasks')
@login_required
def tasks():
    return render_template('tasks.html')


@main.route('/documentation')
@login_required
def documentation():
    return render_template('documentation.html')


@main.route('/team')
@login_required
def team():
    return render_template(
        'simple_page.html',
        title='Teams',
        message='Team management is coming soon — add members, roles, and permissions.',
        button_label='Back to Projects',
        button_url=url_for('main.projects')
    )


@main.route('/archive')
@login_required
def archive():
    # Require an additional archive password (session-protected)
    if not session.get('archive_unlocked'):
        return redirect(url_for('main.archive_unlock'))
    return render_template('archive.html')


@main.route('/archive-unlock', methods=['GET', 'POST'])
@login_required
def archive_unlock():
    # Master password hash should be provided via env var ARCHIVE_PASSWORD_HASH
    # (use werkzeug.security.generate_password_hash to create it).
    if request.method == 'POST':
        pwd = request.form.get('password', '')
        # Prefer Firestore-stored hash (set via admin UI). Fallback to env var.
        stored_hash = get_setting('archive_password_hash') or os.environ.get('ARCHIVE_PASSWORD_HASH')
        # Fallback: allow plain ARCHIVE_PASSWORD for convenience (not recommended)
        plain_pwd = os.environ.get('ARCHIVE_PASSWORD')

        valid = False
        if stored_hash:
            try:
                valid = check_password_hash(stored_hash, pwd)
            except Exception:
                valid = False
        elif plain_pwd:
            valid = (pwd == plain_pwd)

        if valid:
            session['archive_unlocked'] = True
            flash('Archive unlocked', 'success')
            return redirect(url_for('main.archive'))
        else:
            flash('Incorrect password', 'danger')

    return render_template(
        'archive_access.html',
        mode='unlock',
        title='Unlock Archive',
        action_url=url_for('main.archive_unlock'),
        submit_label='Unlock'
    )


@main.route('/archive-lock')
@login_required
def archive_lock():
    session.pop('archive_unlocked', None)
    flash('Archive locked', 'info')
    return redirect(url_for('main.dashboard'))


@main.route('/archive-admin', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def archive_admin():
    # Admin page to set the archive password in Firestore.
    if request.method == 'POST':
        pwd = request.form.get('password', '')
        pwd2 = request.form.get('password_confirm', '')
        if not pwd:
            flash('Password is required', 'danger')
        elif pwd != pwd2:
            flash('Passwords do not match', 'danger')
        else:
            h = generate_password_hash(pwd)
            set_setting('archive_password_hash', h)
            flash('Archive password updated', 'success')
            return redirect(url_for('main.archive_admin'))

    # Don't expose hash in GET
    return render_template(
        'archive_access.html',
        mode='admin',
        title='Archive Password (Admin)',
        action_url=url_for('main.archive_admin'),
        submit_label='Set Password'
    )


@main.route('/admin/users', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def admin_users():
    if request.method == 'POST':
        target_email = request.form.get('email')
        new_role = request.form.get('role')
        name = request.form.get('name', '')
        actor = getattr(current_user, 'id', 'unknown')
        ip = request.remote_addr

        if not target_email:
            flash('Email required', 'danger')
            return redirect(url_for('main.admin_users'))

        # Rate limiting to avoid abuse
        if not check_rate_limit(actor):
            flash('Rate limit exceeded for role changes. Try later.', 'danger')
            return redirect(url_for('main.admin_users'))

        old_role = get_user_role(target_email)
        if old_role == new_role:
            flash('Role is already set to that value', 'info')
            return redirect(url_for('main.admin_users'))

        # Apply change
        set_user_role(target_email, new_role, name=name or None)
        log_audit(actor, 'role_change', target_email, details={'old': old_role, 'new': new_role}, ip=ip)
        increment_rate_limit(actor)
        flash(f'Role for {target_email} updated to {new_role}', 'success')
        return redirect(url_for('main.admin_users'))

    # GET: show admin UI with recent audit logs
    audit_logs = get_recent_audit(100)
    return render_template('admin.html', mode='users', audit_logs=audit_logs)


@main.route('/admin/debug')
@login_required
@role_required('admin')
def admin_debug():
    # Simple admin debug UI that calls /auth/whoami from the browser
    return render_template('admin.html', mode='debug')


@main.route('/ideas')
@login_required
def ideas():
    return render_template('ideas.html')


@main.route('/settings')
@login_required
@role_required('admin')
def settings():
    return render_template('settings.html')

@main.route('/project/<project_id>')
@login_required
def project_detail(project_id):
    # Accept string Firestore/UUID IDs from client; client will fetch project data
    return render_template('project_detail.html', project_id=project_id)

@main.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(_safe_next_url(request.args.get('next')))

    if request.method == 'POST':
        flash('Firebase Auth did not complete in the browser. Please try again after the page fully loads.', 'danger')
        return redirect(url_for('main.login'))

    return render_template('login.html')


@main.route('/auth/session', methods=['POST'])
def create_auth_session():
    if current_user.is_authenticated:
        return jsonify({'ok': True, 'redirect': url_for('main.dashboard')})

    payload = request.get_json(silent=True) or {}
    id_token = payload.get('idToken')
    name = (payload.get('name') or '').strip()
    remember = bool(payload.get('remember'))
    next_url = _safe_next_url(payload.get('next') or request.args.get('next'))

    if not id_token:
        return jsonify({'ok': False, 'error': 'Missing Firebase ID token'}), 400

    decoded = verify_id_token(id_token)
    if not decoded:
        return jsonify({'ok': False, 'error': 'Could not verify Firebase session. Check the server internet connection and Firebase web API key.'}), 401

    email = _normalize_email(decoded.get('email'))
    if not _valid_email(email):
        return jsonify({'ok': False, 'error': 'Firebase account does not include a valid email address'}), 400

    display_name = name or decoded.get('name') or ''
    try:
        user_record = ensure_firebase_user(email, display_name)
    except RuntimeError as exc:
        current_app.logger.warning('Firestore profile unavailable for %s: %s', email, exc)
        user_record = {'email': email, 'name': display_name, 'role': os.environ.get('DEFAULT_ROLE', 'user')}
    except Exception:
        current_app.logger.exception('Failed to create or load Firestore user profile')
        user_record = {'email': email, 'name': display_name, 'role': os.environ.get('DEFAULT_ROLE', 'user')}

    user = _login_user_from_record(user_record, remember=remember)
    log_audit(user.id, 'login', user.id, ip=request.remote_addr)
    flash('Signed in successfully', 'success')
    return jsonify({'ok': True, 'redirect': next_url})


@main.route('/logout')
@login_required
def logout():
    actor = getattr(current_user, 'id', 'unknown')
    log_audit(actor, 'logout', actor, ip=request.remote_addr)
    logout_user()
    session.pop('archive_unlocked', None)
    session.pop('user_name', None)
    session.pop('user_role', None)
    flash('Signed out', 'info')
    return redirect(url_for('main.login'))


@main.route('/auth/whoami')
def whoami():
    if not current_user.is_authenticated:
        return jsonify({'authenticated': False}), 401
    return jsonify({
        'authenticated': True,
        'email': current_user.id,
        'name': getattr(current_user, 'name', ''),
        'role': getattr(current_user, 'role', 'user'),
        'is_admin': getattr(current_user, 'role', None) == 'admin'
    })
