"""
Stock Management module.
Per-branch stock tracking, stock-in entries, adjustments, low-stock alerts.
"""
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, jsonify)
from flask_login import login_required, current_user
from database import get_db, execute_db, query_db, transaction, audit
from routes.auth import perm_required
from services import stock as stock_svc
from datetime import datetime

bp = Blueprint('stock', __name__, url_prefix='/stock')


@bp.route('/')
@login_required
def index():
    """Stock overview — all products with current stock per branch."""
    branch_id = request.args.get('branch_id', '')
    q = request.args.get('q', '').strip()
    show_low = request.args.get('low', '')

    if not current_user.is_admin and current_user.branch_id:
        branch_id = str(current_user.branch_id)

    # Build stock overview query
    if branch_id:
        sql = """
            SELECT p.id, p.brand_category, p.model, p.sku, p.price,
                   p.low_stock_alert,
                   COALESCE(ps.quantity, 0) AS stock,
                   b.name AS branch_name, b.id AS branch_id, b.short_code
            FROM products p
            JOIN branches b ON b.id = ?
            LEFT JOIN product_stock ps ON ps.product_id=p.id AND ps.branch_id=?
            WHERE p.is_active=1
        """
        args = [branch_id, branch_id]
        if q:
            sql += " AND (p.model LIKE ? OR p.brand_category LIKE ? OR p.sku LIKE ?)"
            args += [f'%{q}%', f'%{q}%', f'%{q}%']
        if show_low:
            sql += " AND COALESCE(ps.quantity,0) <= p.low_stock_alert"
        sql += " ORDER BY p.brand_category, p.model"
        products = query_db(sql, args)
    else:
        # All branches combined
        sql = """
            SELECT p.id, p.brand_category, p.model, p.sku, p.price,
                   p.low_stock_alert,
                   COALESCE(SUM(ps.quantity), 0) AS stock,
                   'All Branches' AS branch_name, 0 AS branch_id, 'ALL' AS short_code
            FROM products p
            LEFT JOIN product_stock ps ON ps.product_id = p.id
            WHERE p.is_active=1
        """
        args = []
        if q:
            sql += " AND (p.model LIKE ? OR p.brand_category LIKE ? OR p.sku LIKE ?)"
            args += [f'%{q}%', f'%{q}%', f'%{q}%']
        sql += " GROUP BY p.id"
        if show_low:
            sql += " HAVING COALESCE(SUM(ps.quantity),0) <= p.low_stock_alert"
        sql += " ORDER BY p.brand_category, p.model"
        products = query_db(sql, args)

    # Low-stock count for alert badge
    low_stock_count = query_db("""
        SELECT COUNT(DISTINCT p.id) as cnt
        FROM products p
        LEFT JOIN product_stock ps ON ps.product_id=p.id
        WHERE p.is_active=1
        GROUP BY p.id
        HAVING COALESCE(SUM(ps.quantity),0) <= p.low_stock_alert
    """)
    low_count = len(low_stock_count)

    branches = query_db("SELECT * FROM branches ORDER BY name")
    return render_template('stock/index.html',
                           products=products, branches=branches,
                           branch_filter=branch_id, q=q,
                           show_low=show_low, low_count=low_count)


ADJUST_TYPES = {
    'stock_in':       ('Stock in', +1),
    'adjustment_in':  ('Adjustment (+)', +1),
    'adjustment_out': ('Adjustment (−)', -1),
}


def _own_branch(requested):
    """Staff only move stock at their own branch."""
    if not current_user.is_admin and current_user.branch_id:
        return current_user.branch_id
    try:
        return int(requested)
    except (TypeError, ValueError):
        return None


@bp.route('/adjust', methods=['GET', 'POST'])
@login_required
@perm_required('manage_stock')
def adjust():
    """Receive stock or correct a count. Customer returns go through Returns."""
    branches = query_db("SELECT * FROM branches ORDER BY name")
    products = query_db(
        "SELECT id, brand_category, model, sku, track_units FROM products "
        "WHERE is_active=1 ORDER BY brand_category, model")
    default_branch_id = current_user.branch_id or (branches[0]['id'] if branches else None)

    def _again():
        return render_template('stock/adjust.html', branches=branches,
                               products=products, default_branch_id=default_branch_id)

    if request.method == 'POST':
        try:
            product_id    = int(request.form['product_id'])
            branch_id     = _own_branch(request.form.get('branch_id'))
            movement_type = request.form['movement_type']
            quantity      = float(request.form['quantity'])
            if movement_type not in ADJUST_TYPES:
                raise ValueError('unknown movement type')
            if quantity <= 0 or quantity != int(quantity) or not branch_id:
                raise ValueError('quantity must be a whole number above 0')
        except (ValueError, KeyError) as e:
            flash(f'Please fill in all fields correctly. ({e})', 'danger')
            return _again()

        product = query_db("SELECT * FROM products WHERE id=?", (product_id,), one=True)
        if not product:
            flash('Product not found.', 'danger')
            return _again()
        supplier = request.form.get('supplier', '').strip() or None
        notes    = request.form.get('notes', '').strip() or None
        imeis    = stock_svc.parse_imeis(request.form.get('imeis'))
        sign     = ADJUST_TYPES[movement_type][1]
        tracked  = bool(product['track_units'])

        errors = []
        if sign < 0:
            have = stock_svc.available(product_id, branch_id)
            if quantity > have:
                errors.append(f'Only {have:g} of {product["model"]} at this branch — '
                              f'you cannot remove {quantity:g}.')
            if not notes:
                errors.append('Write the reason for removing stock in Notes (damaged, lost, count error…).')
        if tracked:
            if len(imeis) != int(quantity):
                errors.append(f'{product["model"]} is tracked by IMEI: enter exactly {int(quantity)} '
                              f'IMEI number(s) — you entered {len(imeis)}.')
            elif sign < 0:
                errors += stock_svc.check_units_at_branch(product_id, branch_id, imeis)
            else:
                dupes = [x for x in set(imeis)
                         if query_db("SELECT 1 FROM device_imeis WHERE imei=?", (x,), one=True)]
                if len(set(imeis)) != len(imeis):
                    errors.append('The same IMEI is listed twice.')
                if dupes:
                    errors.append('Already in the system: ' + ', '.join(sorted(dupes)))
        if errors:
            for e in errors:
                flash(e, 'danger')
            return _again()

        u_color   = request.form.get('unit_color', '').strip() or None
        u_storage = request.form.get('unit_storage', '').strip() or None
        u_cond    = request.form.get('unit_condition', '').strip() or 'new'
        try:
            u_cost = float(request.form.get('unit_cost_price', 0) or 0)
        except ValueError:
            u_cost = 0

        with transaction():
            mid = stock_svc.move(product_id, branch_id, sign * quantity, movement_type,
                                 supplier=supplier, notes=notes)
            if tracked and sign > 0:
                for imei in imeis:
                    execute_db("""
                        INSERT INTO device_imeis
                          (product_id, branch_id, imei, stock_movement_id,
                           color, storage, condition, cost_price)
                        VALUES (?,?,?,?,?,?,?,?)
                    """, (product_id, branch_id, imei, mid, u_color, u_storage, u_cond, u_cost))
            elif tracked and sign < 0:
                ph = ','.join('?' * len(imeis))
                execute_db(f"UPDATE device_imeis SET status='removed', notes=? WHERE imei IN ({ph})",
                           [notes] + imeis)
            if sign < 0:
                audit('stock_out', 'product', product_id, product['model'],
                      f'-{quantity:g}: {notes}', branch_id)

        flash(f'Stock updated — {product["model"]} '
              f'({ADJUST_TYPES[movement_type][0]}: {quantity:g}).', 'success')
        return redirect(url_for('stock.index'))

    return _again()


@bp.route('/transfer', methods=['GET', 'POST'])
@login_required
@perm_required('manage_stock')
def transfer():
    """Transfer stock (and the IMEI units) from one branch to another."""
    branches = query_db("SELECT * FROM branches ORDER BY name")
    products = query_db(
        "SELECT id, brand_category, model, track_units FROM products "
        "WHERE is_active=1 ORDER BY brand_category, model")

    def _again():
        return render_template('stock/transfer.html', branches=branches, products=products)

    if request.method == 'POST':
        try:
            product_id  = int(request.form['product_id'])
            from_branch = int(request.form['from_branch_id'])
            to_branch   = int(request.form['to_branch_id'])
            quantity    = float(request.form['quantity'])
        except (ValueError, KeyError) as e:
            flash(f'Fill in all fields correctly. ({e})', 'danger')
            return _again()

        product = query_db("SELECT * FROM products WHERE id=?", (product_id,), one=True)
        imeis   = stock_svc.parse_imeis(request.form.get('imeis'))
        errors  = []
        if not product:
            errors.append('Product not found.')
        if from_branch == to_branch:
            errors.append('Source and destination branches must be different.')
        if (not current_user.is_admin and current_user.branch_id
                and from_branch != current_user.branch_id):
            errors.append('You can only send stock out of your own branch.')
        if quantity <= 0 or quantity != int(quantity):
            errors.append('Quantity must be a whole number above 0.')
        if not errors:
            avail_qty = stock_svc.available(product_id, from_branch)
            if quantity > avail_qty:
                errors.append(f'Not enough stock — only {avail_qty:g} units available at source branch.')
            if product['track_units']:
                if len(imeis) != int(quantity):
                    errors.append(f'{product["model"]} is tracked by IMEI: list the {int(quantity)} '
                                  f'IMEI(s) being sent (you listed {len(imeis)}).')
                else:
                    errors += stock_svc.check_units_at_branch(product_id, from_branch, imeis)
        if errors:
            for e in errors:
                flash(e, 'danger')
            return _again()

        notes = request.form.get('notes', '').strip() or None
        with transaction():
            stock_svc.move(product_id, from_branch, -quantity, 'transfer_out', notes=notes)
            stock_svc.move(product_id, to_branch, quantity, 'transfer_in', notes=notes)
            if imeis:
                ph = ','.join('?' * len(imeis))
                execute_db(f"UPDATE device_imeis SET branch_id=? WHERE imei IN ({ph})",
                           [to_branch] + imeis)

        from_b = query_db("SELECT name FROM branches WHERE id=?", (from_branch,), one=True)
        to_b   = query_db("SELECT name FROM branches WHERE id=?", (to_branch,), one=True)
        flash(f'Transferred {quantity:g}× {product["brand_category"]} {product["model"]} '
              f'from {from_b["name"]} → {to_b["name"]}.', 'success')
        return redirect(url_for('stock.index'))

    return _again()


@bp.route('/movements')
@login_required
def movements():
    """Full stock movement history."""
    branch_id = request.args.get('branch_id', '')
    product_id = request.args.get('product_id', '')

    if not current_user.is_admin and current_user.branch_id:
        branch_id = str(current_user.branch_id)

    sql = """
        SELECT sm.*, p.brand_category, p.model, b.name AS branch_name,
               u.full_name AS staff_name
        FROM stock_movements sm
        JOIN products p ON sm.product_id = p.id
        JOIN branches b ON sm.branch_id = b.id
        LEFT JOIN users u ON sm.recorded_by = u.id
        WHERE 1=1
    """
    args = []
    if branch_id:
        sql += " AND sm.branch_id=?"
        args.append(branch_id)
    if product_id:
        sql += " AND sm.product_id=?"
        args.append(product_id)
    sql += " ORDER BY sm.created_at DESC LIMIT 500"

    moves = query_db(sql, args)

    # Fetch IMEIs keyed by movement_id
    move_ids = [m['id'] for m in moves]
    imei_map = {}
    if move_ids:
        placeholders = ','.join('?' * len(move_ids))
        imei_rows = query_db(
            f"SELECT stock_movement_id, imei FROM device_imeis WHERE stock_movement_id IN ({placeholders})",
            move_ids)
        for row in imei_rows:
            imei_map.setdefault(row['stock_movement_id'], []).append(row['imei'])

    branches = query_db("SELECT * FROM branches ORDER BY name")
    products = query_db(
        "SELECT id, brand_category, model FROM products WHERE is_active=1 ORDER BY brand_category, model")

    return render_template('stock/movements.html',
                           moves=moves, branches=branches, products=products,
                           branch_filter=branch_id, product_filter=product_id,
                           imei_map=imei_map)


@bp.route('/units')
@login_required
def units():
    """Unit inventory — every individually tracked device with its own IMEI + details."""
    q          = request.args.get('q', '').strip()
    product_id = request.args.get('product_id', '')
    branch_id  = request.args.get('branch_id', '')
    status     = request.args.get('status', '')

    sql = """
        SELECT di.*,
               p.model AS product_model, p.brand_category, p.price,
               b.name  AS branch_name,
               d.doc_number AS sold_doc_number,
               COALESCE(c.name, d.walkin_name) AS sold_to
        FROM device_imeis di
        LEFT JOIN products  p ON p.id = di.product_id
        LEFT JOIN branches  b ON b.id = di.branch_id
        LEFT JOIN documents d ON d.id = di.sold_document_id
        LEFT JOIN customers c ON c.id = d.customer_id
        WHERE 1=1
    """
    args = []
    if q:
        sql += """ AND (di.imei LIKE ? OR di.serial_number LIKE ?
                        OR p.model LIKE ? OR di.color LIKE ?)"""
        args += [f'%{q}%'] * 4
    if product_id:
        sql += " AND di.product_id=?"
        args.append(product_id)
    if branch_id:
        sql += " AND di.branch_id=?"
        args.append(branch_id)
    if status:
        sql += " AND di.status=?"
        args.append(status)

    sql += " ORDER BY p.model, di.status, di.created_at DESC LIMIT 500"
    rows = query_db(sql, args)

    # Per-product summary so "5 Google Pixels" reads as 5 distinct devices
    summary = query_db("""
        SELECT p.id, p.brand_category, p.model,
               SUM(CASE WHEN di.status='in_stock' THEN 1 ELSE 0 END) AS in_stock,
               SUM(CASE WHEN di.status='sold'     THEN 1 ELSE 0 END) AS sold,
               COUNT(*) AS total
        FROM device_imeis di
        JOIN products p ON p.id = di.product_id
        GROUP BY p.id
        ORDER BY p.brand_category, p.model
    """)

    branches = query_db("SELECT * FROM branches ORDER BY name")
    products = query_db(
        "SELECT id, brand_category, model FROM products WHERE track_units=1 ORDER BY brand_category, model")

    return render_template('stock/units.html',
                           units=rows, summary=summary,
                           branches=branches, products=products,
                           q=q, product_filter=product_id,
                           branch_filter=branch_id, status_filter=status)


@bp.route('/units/<int:unit_id>/edit', methods=['POST'])
@login_required
def unit_edit(unit_id):
    """Update one unit's details (colour, storage, condition, cost, notes, serial)."""
    unit = query_db("SELECT * FROM device_imeis WHERE id=?", (unit_id,), one=True)
    if not unit:
        flash('Unit not found.', 'danger')
        return redirect(url_for('stock.units'))

    try:
        cost = float(request.form.get('cost_price', 0) or 0)
    except ValueError:
        cost = unit['cost_price']

    execute_db("""
        UPDATE device_imeis SET
          serial_number=?, color=?, storage=?, condition=?, cost_price=?, notes=?
        WHERE id=?
    """, (
        request.form.get('serial_number', '').strip() or None,
        request.form.get('color', '').strip() or None,
        request.form.get('storage', '').strip() or None,
        request.form.get('condition', 'new').strip() or 'new',
        cost,
        request.form.get('notes', '').strip() or None,
        unit_id,
    ))
    flash(f'Unit {unit["imei"]} updated.', 'success')
    return redirect(request.referrer or url_for('stock.units'))


@bp.route('/api/units')
@login_required
def api_units():
    """JSON: in-stock units of a product at a branch — used by the invoice screen."""
    product_id = request.args.get('product_id')
    branch_id  = request.args.get('branch_id')
    if not product_id:
        return jsonify([])
    sql = "SELECT id, imei, serial_number, color, storage, condition FROM device_imeis " \
          "WHERE product_id=? AND status='in_stock'"
    args = [product_id]
    if branch_id:
        sql += " AND branch_id=?"
        args.append(branch_id)
    sql += " ORDER BY created_at"
    return jsonify([dict(r) for r in query_db(sql, args)])


@bp.route('/api/product-stock')
@login_required
def api_product_stock():
    """JSON endpoint: current stock of a product at a branch."""
    product_id = request.args.get('product_id')
    branch_id = request.args.get('branch_id')
    if not product_id or not branch_id:
        return jsonify({'quantity': 0})
    row = query_db(
        "SELECT quantity FROM product_stock WHERE product_id=? AND branch_id=?",
        (product_id, branch_id), one=True)
    return jsonify({'quantity': float(row['quantity']) if row else 0})
