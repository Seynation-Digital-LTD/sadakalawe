from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import login_required, current_user
from database import query_db, execute_db, get_db
from services.numbering import get_next_number

bp = Blueprint('returns', __name__, url_prefix='/returns')

RETURN_TYPES  = [('refund', 'Cash Refund'), ('exchange', 'Exchange'), ('credit', 'Store Credit')]
RETURN_REASONS = [
    'Defective / not working',
    'Wrong item received',
    'Customer changed mind',
    'Duplicate purchase',
    'Damaged in transit',
    'Does not match description',
    'Other',
]


def _restore_stock(items, branch_id):
    """Add returned quantities back to stock."""
    for item in items:
        if not item.get('product_id'):
            continue
        qty = abs(item.get('quantity', 1))
        pid = item['product_id']
        execute_db("""
            INSERT INTO product_stock (product_id, branch_id, quantity)
            VALUES (?,?,?)
            ON CONFLICT(product_id, branch_id)
            DO UPDATE SET quantity = quantity + excluded.quantity
        """, (pid, branch_id, qty))
        execute_db("""
            INSERT INTO stock_movements
              (product_id, branch_id, movement_type, quantity, recorded_by)
            VALUES (?,?,'return',?,?)
        """, (pid, branch_id, qty, current_user.id))
        execute_db("""
            UPDATE products SET
              stock_count = (SELECT COALESCE(SUM(quantity),0)
                             FROM product_stock WHERE product_id=?),
              updated_at  = datetime('now','localtime')
            WHERE id=?
        """, (pid, pid))


@bp.route('/')
@login_required
def list():
    branch_filter = request.args.get('branch_id', '')
    status_filter = request.args.get('status', '')

    conds  = []
    params = []
    if branch_filter and current_user.is_admin:
        conds.append("r.branch_id = ?")
        params.append(branch_filter)
    elif not current_user.is_admin and current_user.branch_id:
        conds.append("r.branch_id = ?")
        params.append(current_user.branch_id)
    if status_filter:
        conds.append("r.status = ?")
        params.append(status_filter)

    where = ("WHERE " + " AND ".join(conds)) if conds else ""

    rets = query_db(f"""
        SELECT r.*,
            b.name  AS branch_name,
            COALESCE(c.name, r.walkin_name) AS customer_name,
            d.doc_number AS original_doc_number,
            u.full_name  AS created_by_name
        FROM returns r
        LEFT JOIN branches b  ON b.id  = r.branch_id
        LEFT JOIN customers c ON c.id  = r.customer_id
        LEFT JOIN documents d ON d.id  = r.document_id
        LEFT JOIN users u     ON u.id  = r.created_by
        {where}
        ORDER BY r.created_at DESC
        LIMIT 200
    """, params)

    branches = query_db("SELECT id, name FROM branches ORDER BY name")
    return render_template('returns/list.html',
                           rets=rets,
                           branches=branches,
                           branch_filter=branch_filter,
                           status_filter=status_filter,
                           return_types=dict(RETURN_TYPES))


@bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    branches = query_db("SELECT id, name FROM branches ORDER BY name")
    default_branch = current_user.branch_id or (branches[0]['id'] if branches else None)

    if request.method == 'POST':
        f           = request.form
        branch_id   = int(f.get('branch_id') or default_branch)
        document_id = f.get('document_id') or None
        customer_id = f.get('customer_id') or None
        walkin_name = f.get('walkin_name', '').strip() or None
        reason      = f.get('reason', '').strip()
        return_type = f.get('return_type', 'refund')
        refund_amt  = float(f.get('refund_amount', 0) or 0)
        exch_notes  = f.get('exchange_notes', '').strip() or None
        notes       = f.get('notes', '').strip() or None

        # Parse returned items
        descs    = f.getlist('item_description[]')
        qtys     = f.getlist('item_qty[]')
        prices   = f.getlist('item_price[]')
        prod_ids = f.getlist('item_product_id[]')
        di_ids   = f.getlist('item_di_id[]')

        items = []
        for i, desc in enumerate(descs):
            desc = desc.strip()
            if not desc:
                continue
            try:
                qty   = float(qtys[i]   or 1)
                price = float(prices[i] or 0)
            except (IndexError, ValueError):
                qty, price = 1, 0
            items.append({
                'description':      desc,
                'quantity':         qty,
                'unit_price':       price,
                'line_total':       qty * price,
                'product_id':       (prod_ids[i] if i < len(prod_ids) else None) or None,
                'document_item_id': (di_ids[i]   if i < len(di_ids)   else None) or None,
            })

        if not items:
            flash('Add at least one returned item.', 'error')
            return render_template('returns/new.html', branches=branches,
                                   default_branch=default_branch,
                                   return_types=RETURN_TYPES, reasons=RETURN_REASONS, form=f)

        year          = datetime.now().year
        return_number = get_next_number(branch_id, 'return', year)

        ret_id = execute_db("""
            INSERT INTO returns
              (return_number, document_id, customer_id, walkin_name, branch_id,
               reason, return_type, refund_amount, exchange_notes, notes,
               status, created_by)
            VALUES (?,?,?,?,?,?,?,?,?,?,'pending',?)
        """, (return_number, document_id, customer_id, walkin_name, branch_id,
              reason, return_type, refund_amt, exch_notes, notes, current_user.id))

        for item in items:
            execute_db("""
                INSERT INTO return_items
                  (return_id, document_item_id, product_id,
                   description, quantity, unit_price, line_total)
                VALUES (?,?,?,?,?,?,?)
            """, (ret_id, item['document_item_id'], item['product_id'],
                  item['description'], item['quantity'],
                  item['unit_price'], item['line_total']))

        # Restore stock immediately (pending approval can be added later)
        _restore_stock(items, branch_id)

        # Mark as approved since we restored stock
        get_db().execute("UPDATE returns SET status='approved', processed_by=? WHERE id=?",
                         (current_user.id, ret_id))
        get_db().commit()

        flash(f'Return {return_number} logged and stock restored.', 'success')
        return redirect(url_for('returns.view', ret_id=ret_id))

    # Pre-fill from invoice link
    doc_id = request.args.get('doc_id')
    doc    = None
    doc_items = []
    if doc_id:
        doc = query_db("""
            SELECT d.*, COALESCE(c.name, d.walkin_name) AS customer_name,
                   c.id AS cust_id
            FROM documents d
            LEFT JOIN customers c ON c.id = d.customer_id
            WHERE d.id = ?
        """, (doc_id,), one=True)
        if doc:
            doc_items = query_db("""
                SELECT di.*, p.brand_category
                FROM document_items di
                LEFT JOIN products p ON p.id = di.product_id
                WHERE di.document_id = ?
                ORDER BY di.id
            """, (doc_id,))

    return render_template('returns/new.html',
                           branches=branches,
                           default_branch=default_branch,
                           return_types=RETURN_TYPES,
                           reasons=RETURN_REASONS,
                           doc=doc,
                           doc_items=doc_items,
                           form={})


@bp.route('/<int:ret_id>')
@login_required
def view(ret_id):
    ret = query_db("""
        SELECT r.*,
            b.name  AS branch_name,
            COALESCE(c.name, r.walkin_name) AS customer_name,
            d.doc_number AS original_doc_number,
            u.full_name  AS created_by_name,
            p.full_name  AS processed_by_name
        FROM returns r
        LEFT JOIN branches b  ON b.id  = r.branch_id
        LEFT JOIN customers c ON c.id  = r.customer_id
        LEFT JOIN documents d ON d.id  = r.document_id
        LEFT JOIN users u     ON u.id  = r.created_by
        LEFT JOIN users p     ON p.id  = r.processed_by
        WHERE r.id = ?
    """, (ret_id,), one=True)
    if not ret:
        abort(404)

    items = query_db("""
        SELECT ri.*, p.model AS product_model
        FROM return_items ri
        LEFT JOIN products p ON p.id = ri.product_id
        WHERE ri.return_id = ?
        ORDER BY ri.id
    """, (ret_id,))

    return render_template('returns/view.html',
                           ret=ret, items=items,
                           return_types=dict(RETURN_TYPES))


@bp.route('/invoice-search')
@login_required
def invoice_search():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    rows = query_db("""
        SELECT d.id, d.doc_number, d.total, d.created_at,
               COALESCE(c.name, d.walkin_name) AS customer_name
        FROM documents d
        LEFT JOIN customers c ON c.id = d.customer_id
        WHERE d.doc_type = 'invoice'
          AND (d.doc_number LIKE ? OR COALESCE(c.name, d.walkin_name) LIKE ?)
        ORDER BY d.created_at DESC
        LIMIT 10
    """, (f'%{q}%', f'%{q}%'))
    return jsonify([{
        'id':            r['id'],
        'doc_number':    r['doc_number'],
        'customer_name': r['customer_name'] or '',
        'total':         r['total'],
        'date':          r['created_at'][:10],
    } for r in rows])


@bp.route('/invoice-items/<int:doc_id>')
@login_required
def invoice_items(doc_id):
    items = query_db("""
        SELECT di.id, di.description, di.quantity, di.unit_price, di.line_total,
               di.product_id
        FROM document_items di
        WHERE di.document_id = ?
        ORDER BY di.id
    """, (doc_id,))
    return jsonify([dict(r) for r in items])
