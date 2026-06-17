from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from database import get_db, execute_db, query_db
from routes.auth import perm_required

bp = Blueprint('customers', __name__, url_prefix='/customers')


@bp.route('/')
@login_required
@perm_required('view_customers')
def list():
    q = request.args.get('q', '').strip()
    branch_filter = request.args.get('branch_id', '')

    sql = """
        SELECT c.*, b.name as branch_name
        FROM customers c LEFT JOIN branches b ON c.branch_id = b.id
        WHERE 1=1
    """
    args = []

    if q:
        sql += " AND (c.name LIKE ? OR c.phone LIKE ? OR c.tin LIKE ?)"
        args += [f'%{q}%', f'%{q}%', f'%{q}%']

    if not current_user.is_admin and current_user.branch_id:
        sql += " AND (c.branch_id = ? OR c.branch_id IS NULL)"
        args.append(current_user.branch_id)
    elif branch_filter:
        sql += " AND c.branch_id = ?"
        args.append(branch_filter)

    sql += " ORDER BY c.name"
    customers = query_db(sql, args)
    branches = query_db("SELECT * FROM branches ORDER BY name")
    return render_template('customers/list.html', customers=customers, branches=branches,
                           q=q, branch_filter=branch_filter)


@bp.route('/new', methods=['GET', 'POST'])
@login_required
@perm_required('manage_customers')
def new():
    branches = query_db("SELECT * FROM branches ORDER BY name")
    if request.method == 'POST':
        name = request.form['name'].strip()
        if not name:
            flash('Customer name is required.', 'danger')
            return render_template('customers/form.html', branches=branches, action='new')

        branch_id = request.form.get('branch_id') or (current_user.branch_id if not current_user.is_admin else None)
        cid = execute_db("""
            INSERT INTO customers (name, phone, email, tin, address, notes, branch_id)
            VALUES (?,?,?,?,?,?,?)
        """, (
            name,
            request.form.get('phone', '').strip(),
            request.form.get('email', '').strip(),
            request.form.get('tin', '').strip(),
            request.form.get('address', '').strip(),
            request.form.get('notes', '').strip(),
            branch_id,
        ))
        flash(f'Customer "{name}" added.', 'success')
        next_url = request.form.get('next_url')
        if next_url:
            return redirect(next_url)
        return redirect(url_for('customers.view', customer_id=cid))
    return render_template('customers/form.html', branches=branches, action='new')


@bp.route('/<int:customer_id>')
@login_required
def view(customer_id):
    customer = query_db("""
        SELECT c.*, b.name as branch_name
        FROM customers c LEFT JOIN branches b ON c.branch_id = b.id
        WHERE c.id=?
    """, (customer_id,), one=True)
    if not customer:
        flash('Customer not found.', 'danger')
        return redirect(url_for('customers.list'))

    docs = query_db("""
        SELECT d.*, b.name as branch_name
        FROM documents d JOIN branches b ON d.branch_id = b.id
        WHERE d.customer_id=?
        ORDER BY d.created_at DESC LIMIT 20
    """, (customer_id,))
    return render_template('customers/view.html', customer=customer, docs=docs)


@bp.route('/<int:customer_id>/edit', methods=['GET', 'POST'])
@login_required
@perm_required('manage_customers')
def edit(customer_id):
    customer = query_db("SELECT * FROM customers WHERE id=?", (customer_id,), one=True)
    if not customer:
        flash('Customer not found.', 'danger')
        return redirect(url_for('customers.list'))
    branches = query_db("SELECT * FROM branches ORDER BY name")

    if request.method == 'POST':
        name = request.form['name'].strip()
        if not name:
            flash('Customer name is required.', 'danger')
            return render_template('customers/form.html', customer=customer, branches=branches, action='edit')

        branch_id = request.form.get('branch_id') or None
        execute_db("""
            UPDATE customers SET name=?, phone=?, email=?, tin=?, address=?, notes=?, branch_id=?,
            updated_at=datetime('now') WHERE id=?
        """, (
            name,
            request.form.get('phone', '').strip(),
            request.form.get('email', '').strip(),
            request.form.get('tin', '').strip(),
            request.form.get('address', '').strip(),
            request.form.get('notes', '').strip(),
            branch_id,
            customer_id,
        ))
        flash('Customer updated.', 'success')
        return redirect(url_for('customers.view', customer_id=customer_id))

    return render_template('customers/form.html', customer=customer, branches=branches, action='edit')


@bp.route('/quick-add', methods=['POST'])
@login_required
def quick_add():
    """AJAX endpoint — create a customer inline from the New Document form."""
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    branch_id = current_user.branch_id or None
    cid = execute_db("""
        INSERT INTO customers (name, phone, address, tin, branch_id)
        VALUES (?, ?, ?, ?, ?)
    """, (
        name,
        (data.get('phone') or '').strip() or None,
        (data.get('address') or '').strip() or None,
        (data.get('tin') or '').strip() or None,
        branch_id,
    ))
    return jsonify({'id': cid, 'name': name,
                    'phone': data.get('phone', '').strip()})


@bp.route('/search')
@login_required
def search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    rows = query_db("""
        SELECT id, name, phone, tin, address FROM customers
        WHERE name LIKE ? OR phone LIKE ? OR tin LIKE ?
        ORDER BY name LIMIT 15
    """, (f'%{q}%', f'%{q}%', f'%{q}%'))
    return jsonify([dict(r) for r in rows])
