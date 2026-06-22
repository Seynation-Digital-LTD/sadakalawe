import calendar
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from database import query_db, execute_db
from routes.auth import admin_required

bp = Blueprint('commissions', __name__, url_prefix='/commissions')


def _month_range(month_str):
    year, mo = map(int, month_str.split('-'))
    last = calendar.monthrange(year, mo)[1]
    return f"{year}-{mo:02d}-01", f"{year}-{mo:02d}-{last:02d}"


@bp.route('/')
@login_required
def index():
    month = request.args.get('month', datetime.now().strftime('%Y-%m'))
    try:
        date_from, date_to = _month_range(month)
    except Exception:
        month = datetime.now().strftime('%Y-%m')
        date_from, date_to = _month_range(month)

    if current_user.is_admin:
        staff = query_db("""
            SELECT u.id, u.full_name, u.commission_rate,
                   b.name AS branch_name,
                   COUNT(DISTINCT d.id)          AS doc_count,
                   COALESCE(SUM(d.total), 0)     AS total_sales
            FROM users u
            LEFT JOIN branches b ON u.branch_id = b.id
            LEFT JOIN documents d
              ON d.created_by = u.id
             AND d.doc_type = 'invoice'
             AND DATE(d.created_at) BETWEEN ? AND ?
            WHERE u.is_active = 1 AND u.role != 'owner'
            GROUP BY u.id
            ORDER BY total_sales DESC
        """, (date_from, date_to))
    else:
        staff = query_db("""
            SELECT u.id, u.full_name, u.commission_rate,
                   b.name AS branch_name,
                   COUNT(DISTINCT d.id)          AS doc_count,
                   COALESCE(SUM(d.total), 0)     AS total_sales
            FROM users u
            LEFT JOIN branches b ON u.branch_id = b.id
            LEFT JOIN documents d
              ON d.created_by = u.id
             AND d.doc_type = 'invoice'
             AND DATE(d.created_at) BETWEEN ? AND ?
            WHERE u.id = ?
            GROUP BY u.id
        """, (date_from, date_to, current_user.id))

    # Build month options: last 12 months
    now = datetime.now()
    months = []
    for i in range(12):
        m = now.month - i
        y = now.year
        while m < 1:
            m += 12
            y -= 1
        months.append(f"{y}-{m:02d}")

    return render_template('commissions/index.html',
                           staff=staff, month=month,
                           date_from=date_from, date_to=date_to,
                           months=months)


@bp.route('/set-rate', methods=['POST'])
@login_required
@admin_required
def set_rate():
    user_id = request.form.get('user_id')
    try:
        rate = float(request.form.get('commission_rate', 0) or 0)
        rate = max(0, min(100, rate))
    except ValueError:
        rate = 0
    execute_db("UPDATE users SET commission_rate=? WHERE id=?", (rate, user_id))
    flash('Commission rate updated.', 'success')
    return redirect(url_for('commissions.index',
                            month=request.form.get('month', '')))
