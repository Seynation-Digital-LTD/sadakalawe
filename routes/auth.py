from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from models import User
from database import get_db, execute_db, query_db
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


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('reports.dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.get_by_username(username)
        if user and user.is_active and check_password_hash(user.get_password_hash(), password):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('reports.dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')


@bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))


@bp.route('/users')
@login_required
@admin_required
def users():
    rows = query_db("""
        SELECT u.*, b.name as branch_name
        FROM users u LEFT JOIN branches b ON u.branch_id = b.id
        ORDER BY u.full_name
    """)
    return render_template('users/list.html', users=rows)


@bp.route('/users/new', methods=['GET', 'POST'])
@login_required
@admin_required
def user_new():
    branches = query_db("SELECT * FROM branches ORDER BY name")
    if request.method == 'POST':
        username = request.form['username'].strip()
        full_name = request.form['full_name'].strip()
        password = request.form['password']
        role = request.form['role']
        branch_id = request.form.get('branch_id') or None

        existing = query_db("SELECT id FROM users WHERE username=?", (username,), one=True)
        if existing:
            flash('Username already taken.', 'danger')
            return render_template('users/form.html', branches=branches, action='new')

        execute_db(
            "INSERT INTO users (username, password_hash, full_name, role, branch_id) VALUES (?,?,?,?,?)",
            (username, generate_password_hash(password, method='pbkdf2:sha256'), full_name, role, branch_id)
        )
        flash(f'User {full_name} created.', 'success')
        return redirect(url_for('auth.users'))

    return render_template('users/form.html', branches=branches, action='new')


@bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def user_edit(user_id):
    user = query_db("SELECT * FROM users WHERE id=?", (user_id,), one=True)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('auth.users'))
    branches = query_db("SELECT * FROM branches ORDER BY name")

    if request.method == 'POST':
        full_name = request.form['full_name'].strip()
        role = request.form['role']
        branch_id = request.form.get('branch_id') or None
        is_active = 1 if request.form.get('is_active') else 0
        new_password = request.form.get('new_password', '').strip()

        if new_password:
            execute_db(
                "UPDATE users SET full_name=?, role=?, branch_id=?, is_active=?, password_hash=? WHERE id=?",
                (full_name, role, branch_id, is_active, generate_password_hash(new_password, method='pbkdf2:sha256'), user_id)
            )
        else:
            execute_db(
                "UPDATE users SET full_name=?, role=?, branch_id=?, is_active=? WHERE id=?",
                (full_name, role, branch_id, is_active, user_id)
            )
        flash('User updated.', 'success')
        return redirect(url_for('auth.users'))

    return render_template('users/form.html', user=user, branches=branches, action='edit')


@bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        if check_password_hash(current_user.get_password_hash(), current_password):
            execute_db("UPDATE users SET password_hash=? WHERE id=?",
                       (generate_password_hash(new_password, method='pbkdf2:sha256'), current_user.id))
            flash('Password changed successfully.', 'success')
        else:
            flash('Current password is incorrect.', 'danger')
    return render_template('users/profile.html', user=current_user)
