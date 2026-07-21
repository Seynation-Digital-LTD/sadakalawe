"""
Stock Management module.
Per-branch stock tracking, stock-in entries, adjustments, low-stock alerts.
"""
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, jsonify)
from flask_login import login_required, current_user
from database import get_db, execute_db, query_db
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


@bp.route('/adjust', methods=['GET', 'POST'])
@login_required
def adjust():
    """Record stock-in, adjustment, or return."""
    branches = query_db("SELECT * FROM branches ORDER BY name")
    products = query_db(
        "SELECT id, brand_category, model, sku FROM products WHERE is_active=1 ORDER BY brand_category, model")

    default_branch_id = current_user.branch_id or (branches[0]['id'] if branches else None)

    if request.method == 'POST':
        try:
            product_id = int(request.form['product_id'])
            branch_id = int(request.form['branch_id'])
            movement_type = request.form['movement_type']
            quantity = float(request.form['quantity'])
            if quantity <= 0:
                raise ValueError("Quantity must be positive")
        except (ValueError, KeyError) as e:
            flash(f'Please fill in all fields correctly. ({e})', 'danger')
            return render_template('stock/adjust.html', branches=branches,
                                   products=products, default_branch_id=default_branch_id)

        supplier = request.form.get('supplier', '').strip() or None
        notes = request.form.get('notes', '').strip() or None
        imei_raw = request.form.get('imeis', '').strip()
        imeis = [x.strip() for x in imei_raw.replace(',', '\n').splitlines() if x.strip()]

        # Determine signed quantity (+/-) for movements
        if movement_type in ('sale', 'adjustment_out', 'transfer_out'):
            signed_qty = -abs(quantity)
        else:
            signed_qty = abs(quantity)

        db = get_db()
        db.execute("""
            INSERT INTO stock_movements
              (product_id, branch_id, movement_type, quantity, supplier, notes, recorded_by)
            VALUES (?,?,?,?,?,?,?)
        """, (product_id, branch_id, movement_type, signed_qty,
              supplier, notes, current_user.id))
        movement_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Details applied to every unit in this intake batch
        u_color   = request.form.get('unit_color', '').strip() or None
        u_storage = request.form.get('unit_storage', '').strip() or None
        u_cond    = request.form.get('unit_condition', '').strip() or 'new'
        try:
            u_cost = float(request.form.get('unit_cost_price', 0) or 0)
        except ValueError:
            u_cost = 0

        skipped = []
        for imei in imeis:
            try:
                db.execute("""
                    INSERT INTO device_imeis
                      (product_id, branch_id, imei, stock_movement_id,
                       color, storage, condition, cost_price)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (product_id, branch_id, imei, movement_id,
                      u_color, u_storage, u_cond, u_cost))
            except Exception:
                skipped.append(imei)  # duplicate IMEI — already in the system
        db.commit()

        if skipped:
            flash('Already registered, skipped: ' + ', '.join(skipped), 'warning')

        # Update product_stock table
        execute_db("""
            INSERT INTO product_stock (product_id, branch_id, quantity)
            VALUES (?,?,?)
            ON CONFLICT(product_id, branch_id)
            DO UPDATE SET quantity = MAX(0, quantity + excluded.quantity)
        """, (product_id, branch_id, signed_qty))

        # Keep products.stock_count in sync (global total)
        execute_db("""
            UPDATE products SET
              stock_count = (
                SELECT COALESCE(SUM(quantity),0) FROM product_stock WHERE product_id=?
              ),
              updated_at = datetime('now','localtime')
            WHERE id=?
        """, (product_id, product_id))

        product = query_db("SELECT brand_category, model FROM products WHERE id=?",
                           (product_id,), one=True)
        pname = f"{product['brand_category']} {product['model']}" if product else "Product"
        flash(f'Stock updated — {pname} ({movement_type.replace("_"," ")}: {quantity:g}).', 'success')
        return redirect(url_for('stock.index'))

    return render_template('stock/adjust.html', branches=branches,
                           products=products, default_branch_id=default_branch_id)


@bp.route('/transfer', methods=['GET', 'POST'])
@login_required
def transfer():
    """Transfer stock from one branch to another."""
    branches = query_db("SELECT * FROM branches ORDER BY name")
    products = query_db(
        "SELECT id, brand_category, model FROM products WHERE is_active=1 ORDER BY brand_category, model")

    if request.method == 'POST':
        try:
            product_id  = int(request.form['product_id'])
            from_branch = int(request.form['from_branch_id'])
            to_branch   = int(request.form['to_branch_id'])
            quantity    = float(request.form['quantity'])
        except (ValueError, KeyError) as e:
            flash(f'Fill in all fields correctly. ({e})', 'danger')
            return render_template('stock/transfer.html', branches=branches, products=products)

        if from_branch == to_branch:
            flash('Source and destination branches must be different.', 'danger')
            return render_template('stock/transfer.html', branches=branches, products=products)
        if quantity <= 0:
            flash('Quantity must be greater than 0.', 'danger')
            return render_template('stock/transfer.html', branches=branches, products=products)

        # Check available stock at source
        available = query_db(
            "SELECT COALESCE(quantity,0) AS qty FROM product_stock WHERE product_id=? AND branch_id=?",
            (product_id, from_branch), one=True)
        avail_qty = available['qty'] if available else 0
        if quantity > avail_qty:
            flash(f'Not enough stock — only {avail_qty:g} units available at source branch.', 'danger')
            return render_template('stock/transfer.html', branches=branches, products=products)

        notes = request.form.get('notes', '').strip() or None
        db = get_db()

        # Log transfer_out at source
        db.execute("""
            INSERT INTO stock_movements
              (product_id, branch_id, movement_type, quantity, notes, recorded_by)
            VALUES (?,?,'transfer_out',?,?,?)
        """, (product_id, from_branch, -quantity, notes, current_user.id))

        # Log transfer_in at destination
        db.execute("""
            INSERT INTO stock_movements
              (product_id, branch_id, movement_type, quantity, notes, recorded_by)
            VALUES (?,?,'transfer_in',?,?,?)
        """, (product_id, to_branch, quantity, notes, current_user.id))
        db.commit()

        # Update product_stock at both branches
        execute_db("""
            INSERT INTO product_stock (product_id, branch_id, quantity) VALUES (?,?,?)
            ON CONFLICT(product_id, branch_id)
            DO UPDATE SET quantity = MAX(0, quantity - excluded.quantity)
        """, (product_id, from_branch, quantity))

        execute_db("""
            INSERT INTO product_stock (product_id, branch_id, quantity) VALUES (?,?,?)
            ON CONFLICT(product_id, branch_id)
            DO UPDATE SET quantity = quantity + excluded.quantity
        """, (product_id, to_branch, quantity))

        # Sync global stock_count
        execute_db("""
            UPDATE products SET stock_count = (
                SELECT COALESCE(SUM(quantity),0) FROM product_stock WHERE product_id=?
            ) WHERE id=?
        """, (product_id, product_id))

        product = query_db("SELECT brand_category, model FROM products WHERE id=?",
                           (product_id,), one=True)
        from_b  = query_db("SELECT name FROM branches WHERE id=?", (from_branch,), one=True)
        to_b    = query_db("SELECT name FROM branches WHERE id=?", (to_branch,), one=True)
        flash(f'Transferred {quantity:g}× {product["brand_category"]} {product["model"]} '
              f'from {from_b["name"]} → {to_b["name"]}.', 'success')
        return redirect(url_for('stock.index'))

    return render_template('stock/transfer.html', branches=branches, products=products)


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
