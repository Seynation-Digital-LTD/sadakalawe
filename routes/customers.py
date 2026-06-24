from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from database import get_db, execute_db, query_db
from routes.auth import perm_required
from services.text_utils import tc, sc

bp = Blueprint('customers', __name__, url_prefix='/customers')


@bp.route('/')
@login_required
@perm_required('view_customers')
def list():
    q = request.args.get('q', '').strip()
    branch_filter = request.args.get('branch_id', '')

    sql = """
        SELECT c.*, b.name as branch_name,
               COALESCE((
                   SELECT SUM(d.total) FROM documents d
                   WHERE d.customer_id = c.id AND d.doc_type='invoice'
               ), 0) AS lifetime_spend
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
        name = tc(request.form['name'])
        if not name:
            flash('Customer name is required.', 'danger')
            return render_template('customers/form.html', branches=branches, action='new')

        phone = request.form.get('phone', '').strip()
        tin   = request.form.get('tin', '').strip().upper() or None

        # Duplicate checks
        if phone:
            dup = query_db("SELECT id, name FROM customers WHERE phone=?", (phone,), one=True)
            if dup:
                flash(f'Phone {phone} is already registered to "{dup["name"]}". '
                      f'Check existing customer first.', 'danger')
                return render_template('customers/form.html', branches=branches, action='new')
        dup_name = query_db("SELECT id FROM customers WHERE LOWER(name)=LOWER(?)", (name,), one=True)
        if dup_name:
            flash(f'A customer named "{name}" already exists.', 'danger')
            return render_template('customers/form.html', branches=branches, action='new')

        branch_id = request.form.get('branch_id') or (current_user.branch_id if not current_user.is_admin else None)
        cid = execute_db("""
            INSERT INTO customers (name, phone, email, tin, address, notes, branch_id)
            VALUES (?,?,?,?,?,?,?)
        """, (
            name,
            phone or None,
            request.form.get('email', '').strip().lower() or None,
            tin,
            tc(request.form.get('address', '')),
            sc(request.form.get('notes', '')),
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
        SELECT c.*, b.name as branch_name,
               COALESCE((
                   SELECT SUM(d.total) FROM documents d
                   WHERE d.customer_id = c.id AND d.doc_type='invoice'
               ), 0) AS lifetime_spend,
               (SELECT COUNT(*) FROM documents d
                WHERE d.customer_id = c.id AND d.doc_type='invoice') AS invoice_count
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
        name = tc(request.form['name'])
        if not name:
            flash('Customer name is required.', 'danger')
            return render_template('customers/form.html', customer=customer, branches=branches, action='edit')

        phone = request.form.get('phone', '').strip()
        tin   = request.form.get('tin', '').strip().upper() or None

        # Duplicate checks (exclude current record)
        if phone:
            dup = query_db("SELECT id, name FROM customers WHERE phone=? AND id!=?",
                           (phone, customer_id), one=True)
            if dup:
                flash(f'Phone {phone} is already registered to "{dup["name"]}".', 'danger')
                return render_template('customers/form.html', customer=customer,
                                       branches=branches, action='edit')
        dup_name = query_db("SELECT id FROM customers WHERE LOWER(name)=LOWER(?) AND id!=?",
                            (name, customer_id), one=True)
        if dup_name:
            flash(f'Another customer named "{name}" already exists.', 'danger')
            return render_template('customers/form.html', customer=customer,
                                   branches=branches, action='edit')

        branch_id = request.form.get('branch_id') or None
        execute_db("""
            UPDATE customers SET name=?, phone=?, email=?, tin=?, address=?, notes=?, branch_id=?,
            updated_at=datetime('now') WHERE id=?
        """, (
            name,
            phone or None,
            request.form.get('email', '').strip().lower() or None,
            tin,
            tc(request.form.get('address', '')),
            sc(request.form.get('notes', '')),
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
    name = tc(data.get('name') or '')
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    branch_id = current_user.branch_id or None
    cid = execute_db("""
        INSERT INTO customers (name, phone, address, tin, branch_id)
        VALUES (?, ?, ?, ?, ?)
    """, (
        name,
        (data.get('phone') or '').strip() or None,
        tc(data.get('address') or '') or None,
        (data.get('tin') or '').strip().upper() or None,
        branch_id,
    ))
    return jsonify({'id': cid, 'name': name,
                    'phone': data.get('phone', '').strip()})


@bp.route('/<int:customer_id>/delete', methods=['POST'])
@login_required
@perm_required('manage_customers')
def delete(customer_id):
    customer = query_db("SELECT * FROM customers WHERE id=?", (customer_id,), one=True)
    if not customer:
        flash('Customer not found.', 'danger')
        return redirect(url_for('customers.list'))
    doc_count = query_db("SELECT COUNT(*) AS cnt FROM documents WHERE customer_id=?",
                         (customer_id,), one=True)['cnt']
    if doc_count:
        flash(f'Cannot delete "{customer["name"]}" — they have {doc_count} document(s) in the system. '
              f'Delete those documents first.', 'danger')
        return redirect(url_for('customers.list'))
    execute_db("DELETE FROM customers WHERE id=?", (customer_id,))
    flash(f'Customer "{customer["name"]}" deleted.', 'success')
    return redirect(url_for('customers.list'))


@bp.route('/duplicates')
@login_required
@perm_required('manage_customers')
def duplicates():
    """Find customers that share the same normalised phone or exact name."""
    # Group by normalised phone (strip spaces/dashes/+)
    by_phone = query_db("""
        SELECT REPLACE(REPLACE(REPLACE(REPLACE(phone,' ',''),'-',''),'+',''),'(','') AS norm_phone,
               COUNT(*) AS cnt
        FROM customers
        WHERE phone IS NOT NULL AND phone != ''
        GROUP BY norm_phone
        HAVING cnt > 1
    """)
    phone_groups = []
    for row in by_phone:
        norm = row['norm_phone']
        members = query_db("""
            SELECT c.*, COUNT(d.id) AS doc_count
            FROM customers c
            LEFT JOIN documents d ON d.customer_id = c.id
            WHERE REPLACE(REPLACE(REPLACE(REPLACE(c.phone,' ',''),'-',''),'+',''),'(','') = ?
            GROUP BY c.id ORDER BY c.id
        """, (norm,))
        phone_groups.append({'key': norm, 'members': [dict(m) for m in members]})

    # Group by exact name (case-insensitive)
    by_name = query_db("""
        SELECT LOWER(name) AS norm_name, COUNT(*) AS cnt
        FROM customers
        GROUP BY norm_name
        HAVING cnt > 1
    """)
    name_groups = []
    for row in by_name:
        members = query_db("""
            SELECT c.*, COUNT(d.id) AS doc_count
            FROM customers c
            LEFT JOIN documents d ON d.customer_id = c.id
            WHERE LOWER(c.name) = ?
            GROUP BY c.id ORDER BY c.id
        """, (row['norm_name'],))
        name_groups.append({'key': row['norm_name'], 'members': [dict(m) for m in members]})

    return render_template('customers/duplicates.html',
                           phone_groups=phone_groups, name_groups=name_groups)


@bp.route('/merge', methods=['POST'])
@login_required
@perm_required('manage_customers')
def merge():
    """Merge one or more duplicate customers into a master record."""
    master_id  = request.form.get('master_id', type=int)
    dup_ids    = request.form.getlist('dup_ids[]', type=int)

    if not master_id or not dup_ids:
        flash('Select a master and at least one duplicate to merge.', 'danger')
        return redirect(url_for('customers.duplicates'))

    master = query_db("SELECT * FROM customers WHERE id=?", (master_id,), one=True)
    if not master:
        flash('Master customer not found.', 'danger')
        return redirect(url_for('customers.duplicates'))

    # Fill in missing fields on master from duplicates
    for dup_id in dup_ids:
        dup = query_db("SELECT * FROM customers WHERE id=?", (dup_id,), one=True)
        if not dup:
            continue
        updates = {}
        if not master['email']   and dup['email']:   updates['email']   = dup['email']
        if not master['tin']     and dup['tin']:     updates['tin']     = dup['tin']
        if not master['address'] and dup['address']: updates['address'] = dup['address']
        if dup['notes']:
            merged_notes = ((master['notes'] or '') + '\n' + dup['notes']).strip()
            updates['notes'] = merged_notes
        if updates:
            set_clause = ', '.join(f'{k}=?' for k in updates)
            execute_db(f"UPDATE customers SET {set_clause} WHERE id=?",
                       list(updates.values()) + [master_id])
            master = query_db("SELECT * FROM customers WHERE id=?", (master_id,), one=True)

        # Re-point all records to master
        execute_db("UPDATE documents       SET customer_id=? WHERE customer_id=?", (master_id, dup_id))
        execute_db("UPDATE financing_plans SET customer_id=? WHERE customer_id=?", (master_id, dup_id))
        execute_db("UPDATE tradeins        SET customer_id=? WHERE customer_id=?", (master_id, dup_id))
        execute_db("DELETE FROM customers WHERE id=?", (dup_id,))

    merged_count = len(dup_ids)
    flash(f'Merged {merged_count} duplicate(s) into "{master["name"]}".', 'success')
    return redirect(url_for('customers.view', customer_id=master_id))


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
