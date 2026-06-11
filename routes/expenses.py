from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from database import execute_db, query_db
from datetime import date

bp = Blueprint('expenses', __name__, url_prefix='/expenses')

CATEGORIES = [
    'Rent',
    'Utilities (Electricity / Water)',
    'Staff Salaries',
    'Transport / Fuel',
    'Internet / Airtime',
    'Marketing & Advertising',
    'Repairs & Maintenance',
    'Purchases / Supplies',
    'Other',
]


@bp.route('/')
@login_required
def list():
    branch_filter   = request.args.get('branch_id', '')
    category_filter = request.args.get('category', '')
    date_from       = request.args.get('date_from', '')
    date_to         = request.args.get('date_to', '')

    sql = """
        SELECT e.*, b.name AS branch_name, u.full_name AS staff_name
        FROM expenses e
        JOIN branches b ON e.branch_id = b.id
        LEFT JOIN users u ON e.recorded_by = u.id
        WHERE 1=1
    """
    args = []

    if not current_user.is_admin and current_user.branch_id:
        sql += " AND e.branch_id=?"
        args.append(current_user.branch_id)
    elif branch_filter:
        sql += " AND e.branch_id=?"
        args.append(branch_filter)

    if category_filter:
        sql += " AND e.category=?"
        args.append(category_filter)
    if date_from:
        sql += " AND e.expense_date >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND e.expense_date <= ?"
        args.append(date_to)

    sql += " ORDER BY e.expense_date DESC, e.id DESC LIMIT 500"
    expenses = query_db(sql, args)

    total = sum(float(e['amount']) for e in expenses)

    # Per-category breakdown for the filtered result set
    cat_totals = {}
    for e in expenses:
        cat_totals[e['category']] = cat_totals.get(e['category'], 0) + float(e['amount'])
    cat_totals = sorted(cat_totals.items(), key=lambda x: x[1], reverse=True)

    branches = query_db("SELECT * FROM branches ORDER BY name")
    return render_template('expenses/list.html',
                           expenses=expenses, branches=branches,
                           categories=CATEGORIES, cat_totals=cat_totals,
                           total=total,
                           branch_filter=branch_filter,
                           category_filter=category_filter,
                           date_from=date_from, date_to=date_to)


@bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    branches = query_db("SELECT * FROM branches ORDER BY name")
    default_branch_id = current_user.branch_id or (branches[0]['id'] if branches else None)

    if request.method == 'POST':
        try:
            branch_id    = int(request.form['branch_id'])
            category     = request.form['category'].strip()
            description  = request.form['description'].strip()
            amount       = float(request.form['amount'])
            expense_date = request.form.get('expense_date') or date.today().isoformat()
            receipt_ref  = request.form.get('receipt_ref', '').strip() or None

            if not description or amount <= 0:
                raise ValueError('Missing fields')
        except (ValueError, KeyError):
            flash('Please fill all required fields correctly.', 'danger')
            return render_template('expenses/form.html', branches=branches,
                                   categories=CATEGORIES,
                                   default_branch_id=default_branch_id,
                                   today=date.today().isoformat(), action='new')

        execute_db("""
            INSERT INTO expenses
              (branch_id, category, description, amount, expense_date, receipt_ref, recorded_by)
            VALUES (?,?,?,?,?,?,?)
        """, (branch_id, category, description, amount, expense_date,
              receipt_ref, current_user.id))
        flash(f'Expense "{description}" (TZS {amount:,.0f}) saved.', 'success')
        return redirect(url_for('expenses.list'))

    return render_template('expenses/form.html', branches=branches,
                           categories=CATEGORIES,
                           default_branch_id=default_branch_id,
                           today=date.today().isoformat(), action='new')


@bp.route('/<int:expense_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(expense_id):
    expense  = query_db("SELECT * FROM expenses WHERE id=?", (expense_id,), one=True)
    if not expense:
        flash('Expense not found.', 'danger')
        return redirect(url_for('expenses.list'))
    branches = query_db("SELECT * FROM branches ORDER BY name")

    if request.method == 'POST':
        try:
            branch_id    = int(request.form['branch_id'])
            category     = request.form['category'].strip()
            description  = request.form['description'].strip()
            amount       = float(request.form['amount'])
            expense_date = request.form.get('expense_date') or date.today().isoformat()
            receipt_ref  = request.form.get('receipt_ref', '').strip() or None
            if not description or amount <= 0:
                raise ValueError
        except (ValueError, KeyError):
            flash('Please fill all required fields correctly.', 'danger')
            return render_template('expenses/form.html', expense=expense,
                                   branches=branches, categories=CATEGORIES,
                                   today=date.today().isoformat(), action='edit')

        execute_db("""
            UPDATE expenses
            SET branch_id=?, category=?, description=?, amount=?,
                expense_date=?, receipt_ref=?
            WHERE id=?
        """, (branch_id, category, description, amount,
              expense_date, receipt_ref, expense_id))
        flash('Expense updated.', 'success')
        return redirect(url_for('expenses.list'))

    return render_template('expenses/form.html', expense=expense,
                           branches=branches, categories=CATEGORIES,
                           today=date.today().isoformat(), action='edit')


@bp.route('/<int:expense_id>/delete', methods=['POST'])
@login_required
def delete(expense_id):
    if not current_user.is_admin:
        flash('Admin access required.', 'danger')
        return redirect(url_for('expenses.list'))
    execute_db("DELETE FROM expenses WHERE id=?", (expense_id,))
    flash('Expense deleted.', 'success')
    return redirect(url_for('expenses.list'))


@bp.route('/api/monthly-totals')
@login_required
def api_monthly_totals():
    """JSON: total expenses per month for dashboard charts."""
    rows = query_db("""
        SELECT strftime('%Y-%m', expense_date) AS month, SUM(amount) AS total
        FROM expenses
        GROUP BY month ORDER BY month DESC LIMIT 12
    """)
    return jsonify([dict(r) for r in rows])
