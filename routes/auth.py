import secrets
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from models import User, PERMISSIONS, ALL_PERMISSION_KEYS, DEFAULT_STAFF_PERMISSIONS
from database import get_db, execute_db, query_db
from services.text_utils import tc
from functools import wraps

bp = Blueprint('auth', __name__)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin access required.', 'danger')
            return redirect(url_for('reports.dashboard'))
        return f(*args, **kwargs)
    return decorated


def perm_required(permission):
    """Decorator: requires current_user.can(permission), else redirects with flash."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            if not current_user.can(permission):
                flash("You don't have permission to do that.", 'danger')
                # Avoid loop if the dashboard itself is blocked
                from flask import request as req
                if req.endpoint == 'reports.dashboard':
                    return redirect(url_for('documents.list'))
                return redirect(url_for('reports.dashboard'))
            return f(*args, **kwargs)
        return decorated
    return decorator


def _save_permissions(user_id, form_data):
    """Replace all permissions for a staff user from posted form checkboxes."""
    db = get_db()
    db.execute("DELETE FROM user_permissions WHERE user_id=?", (user_id,))
    for key in ALL_PERMISSION_KEYS:
        if form_data.get(f'perm_{key}'):
            db.execute(
                "INSERT OR IGNORE INTO user_permissions (user_id, permission) VALUES (?,?)",
                (user_id, key)
            )
    db.commit()


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('reports.dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.get_by_username(username)
        if user and user.is_active and check_password_hash(user.get_password_hash(), password):
            # Single-session: invalidate any previous session by rotating the token
            token = secrets.token_hex(32)
            execute_db("UPDATE users SET session_token=? WHERE id=?", (token, user.id))
            session.permanent = True  # keep cookie alive for 30 days (set in app config)
            login_user(user, remember=True)
            session['session_token'] = token
            if user.must_change_password:
                flash('Please set a new password before continuing.', 'warning')
                return redirect(url_for('auth.profile'))
            next_page = request.args.get('next')
            return redirect(next_page or url_for('reports.dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')


@bp.route('/logout')
@login_required
def logout():
    execute_db("UPDATE users SET session_token=NULL WHERE id=?", (current_user.id,))
    logout_user()
    return redirect(url_for('auth.login'))


@bp.route('/users')
@login_required
@admin_required
def users():
    rows = query_db("""
        SELECT u.*, b.name as branch_name,
               (SELECT COUNT(*) FROM user_permissions up WHERE up.user_id = u.id) AS perm_count
        FROM users u LEFT JOIN branches b ON u.branch_id = b.id
        WHERE u.role != 'owner'
        ORDER BY u.full_name
    """)
    return render_template('users/list.html', users=rows)


@bp.route('/users/new', methods=['GET', 'POST'])
@login_required
@admin_required
def user_new():
    branches = query_db("SELECT * FROM branches ORDER BY name")
    if request.method == 'POST':
        username  = request.form['username'].strip()
        full_name = tc(request.form['full_name'])
        password  = request.form['password']
        role      = request.form['role']
        branch_id = request.form.get('branch_id') or None

        existing = query_db("SELECT id FROM users WHERE username=?", (username,), one=True)
        if existing:
            flash('Username already taken.', 'danger')
            return render_template('users/form.html', branches=branches,
                                   permissions=PERMISSIONS,
                                   checked=DEFAULT_STAFF_PERMISSIONS,
                                   action='new')

        mcp = 1 if request.form.get('must_change_password') else 0
        uid = execute_db(
            "INSERT INTO users (username, password_hash, full_name, role, branch_id, must_change_password) VALUES (?,?,?,?,?,?)",
            (username, generate_password_hash(password, method='pbkdf2:sha256'),
             full_name, role, branch_id, mcp)
        )
        if role == 'staff':
            _save_permissions(uid, request.form)
        flash(f'User {full_name} created.', 'success')
        return redirect(url_for('auth.users'))

    return render_template('users/form.html', branches=branches,
                           permissions=PERMISSIONS,
                           checked=DEFAULT_STAFF_PERMISSIONS,
                           action='new')


@bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def user_edit(user_id):
    user = query_db("SELECT * FROM users WHERE id=?", (user_id,), one=True)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('auth.users'))
    # Only the owner role can edit another owner account
    if user['role'] == 'owner' and not current_user.is_owner:
        flash('Access denied.', 'danger')
        return redirect(url_for('auth.users'))
    branches = query_db("SELECT * FROM branches ORDER BY name")

    if request.method == 'POST':
        full_name    = tc(request.form['full_name'])
        role         = request.form['role']
        branch_id    = request.form.get('branch_id') or None
        is_active    = 1 if request.form.get('is_active') else 0
        mcp          = 1 if request.form.get('must_change_password') else 0
        new_password = request.form.get('new_password', '').strip()

        if new_password:
            execute_db(
                "UPDATE users SET full_name=?, role=?, branch_id=?, is_active=?, must_change_password=?, password_hash=? WHERE id=?",
                (full_name, role, branch_id, is_active, mcp,
                 generate_password_hash(new_password, method='pbkdf2:sha256'), user_id)
            )
        else:
            execute_db(
                "UPDATE users SET full_name=?, role=?, branch_id=?, is_active=?, must_change_password=? WHERE id=?",
                (full_name, role, branch_id, is_active, mcp, user_id)
            )
        if role == 'staff':
            _save_permissions(user_id, request.form)
        else:
            # Admin has all permissions implicitly; clear stored rows (not needed)
            get_db().execute("DELETE FROM user_permissions WHERE user_id=?", (user_id,))
            get_db().commit()

        flash('User updated.', 'success')
        return redirect(url_for('auth.users'))

    # Load current permissions for edit form
    existing_perms = {r['permission'] for r in
                      query_db("SELECT permission FROM user_permissions WHERE user_id=?", (user_id,))}
    return render_template('users/form.html', user=user, branches=branches,
                           permissions=PERMISSIONS,
                           checked=existing_perms,
                           action='edit')


@bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def user_delete(user_id):
    if user_id == current_user.id:
        flash("You can't delete your own account.", 'danger')
        return redirect(url_for('auth.users'))

    user = query_db("SELECT * FROM users WHERE id=?", (user_id,), one=True)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('auth.users'))

    if user['role'] == 'owner' and not current_user.is_owner:
        flash('Access denied.', 'danger')
        return redirect(url_for('auth.users'))

    doc_count = query_db("SELECT COUNT(*) AS cnt FROM documents WHERE created_by=?",
                         (user_id,), one=True)['cnt']
    if doc_count:
        flash(f'Cannot delete "{user["full_name"]}" — they created {doc_count} document(s). '
              f'Deactivate the account via Edit instead.', 'danger')
        return redirect(url_for('auth.users'))

    execute_db("DELETE FROM users WHERE id=?", (user_id,))
    flash(f'User "{user["full_name"]}" deleted.', 'success')
    return redirect(url_for('auth.users'))


@bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        action = request.form.get('action', 'password')

        if action == 'details':
            new_username = request.form.get('username', '').strip()
            new_fullname = tc(request.form.get('full_name', ''))
            if not new_username or not new_fullname:
                flash('Username and full name cannot be empty.', 'danger')
            else:
                taken = query_db(
                    "SELECT id FROM users WHERE username=? AND id!=?",
                    (new_username, current_user.id), one=True)
                if taken:
                    flash('That username is already taken.', 'danger')
                else:
                    execute_db(
                        "UPDATE users SET username=?, full_name=? WHERE id=?",
                        (new_username, new_fullname, current_user.id))
                    flash('Profile updated.', 'success')

        else:
            current_password = request.form.get('current_password', '')
            new_password = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_password', '')
            if not new_password or len(new_password) < 6:
                flash('New password must be at least 6 characters.', 'danger')
            elif new_password != confirm_password:
                flash('New passwords do not match.', 'danger')
            elif not check_password_hash(current_user.get_password_hash(), current_password):
                flash('Current password is incorrect.', 'danger')
            else:
                execute_db(
                    "UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?",
                    (generate_password_hash(new_password, method='pbkdf2:sha256'), current_user.id)
                )
                flash('Password changed successfully.', 'success')
                return redirect(url_for('auth.profile'))

    return render_template('users/profile.html', user=current_user)
