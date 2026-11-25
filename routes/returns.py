from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import login_required, current_user
from database import query_db, execute_db, get_db, transaction, audit
from services import stock as stock_svc
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


def _visible_invoice(doc_id):
    doc = query_db("SELECT * FROM documents WHERE id=? AND doc_type='invoice'", (doc_id,), one=True)
    if not doc:
        return None
    if (not current_user.is_admin and not current_user.can('view_all_branches')
            and current_user.branch_id and doc['branch_id'] != current_user.branch_id):
        return None
    return doc


def _invoice_lines(doc_id):
    """Invoice lines with how many are still returnable."""
    return query_db("""
        SELECT di.*, p.brand_category, COALESCE(p.track_units,0) AS track_units,
               COALESCE((SELECT SUM(ri.quantity) FROM return_items ri
                         WHERE ri.document_item_id = di.id), 0) AS returned,
               -- what the customer actually paid per unit (after discount, with VAT)
               ROUND(CASE WHEN di.quantity > 0 THEN di.line_total * 1.0 / di.quantity ELSE 0 END
                     * (CASE WHEN d.is_vat THEN 1 + d.vat_rate / 100.0 ELSE 1 END), 2) AS paid_unit
        FROM document_items di
        JOIN documents d ON d.id = di.document_id
        LEFT JOIN products p ON p.id = di.product_id
        WHERE di.document_id = ?
        ORDER BY di.id
    """, (doc_id,))


def _sold_units(doc_id, product_id):
    """IMEIs sold on this invoice for this product that haven't come back yet."""
    rows = query_db("""
        SELECT imei FROM device_imeis
        WHERE sold_document_id=? AND product_id=? AND status='sold'
    """, (doc_id, product_id))
    return [r['imei'] for r in rows]


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
        reason      = f.get('reason', '').strip()
        return_type = f.get('return_type', 'refund')
        exch_notes  = f.get('exchange_notes', '').strip() or None
        notes       = f.get('notes', '').strip() or None
        try:
            refund_amt = float(f.get('refund_amount', 0) or 0)
        except ValueError:
            refund_amt = -1

        def _again(doc=None, doc_items=None):
            return render_template('returns/new.html', branches=branches,
                                   default_branch=default_branch, return_types=RETURN_TYPES,
                                   reasons=RETURN_REASONS, doc=doc, doc_items=doc_items or [],
                                   form=f)

        doc = _visible_invoice(f.get('document_id', type=int)) if f.get('document_id') else None
        if not doc:
            flash('Link the invoice the goods were sold on. Returns without an invoice are not '
                  'accepted — it is how we know the item was ours and what was paid.', 'danger')
            return _again()

        lines   = {l['id']: l for l in _invoice_lines(doc['id'])}
        di_ids  = f.getlist('item_di_id[]')
        qtys    = f.getlist('item_qty[]')
        imeis_l = f.getlist('item_imeis[]')
        vat_mul = 1 + (float(doc['vat_rate'] or 0) / 100 if doc['is_vat'] else 0)

        errors, items = [], []
        for i, di in enumerate(di_ids):
            line = lines.get(int(di)) if str(di).isdigit() else None
            if not line:
                errors.append('Every returned item must be a line from the linked invoice.')
                continue
            try:
                qty = float(qtys[i] or 0)
            except (IndexError, ValueError):
                qty = 0
            if qty == 0:
                continue
            first = line['description'].splitlines()[0]
            left = float(line['quantity']) - float(line['returned'])
            if qty < 0 or qty != int(qty):
                errors.append(f'{first}: quantity must be a whole number.')
                continue
            if qty > left + 1e-9:
                errors.append(f'{first}: only {left:g} left to return '
                              f'(sold {float(line["quantity"]):g}, already returned {float(line["returned"]):g}).')
                continue
            unit_paid = round(float(line['line_total']) / float(line['quantity']) * vat_mul, 2) \
                if float(line['quantity']) else 0
            units = []
            if line['product_id'] and line['track_units']:
                candidates = _sold_units(doc['id'], line['product_id'])
                units = stock_svc.parse_imeis(imeis_l[i] if i < len(imeis_l) else '')
                if not units and int(qty) == len(candidates):
                    units = candidates
                if len(units) != int(qty) or any(u not in candidates for u in units):
                    errors.append(f'{first}: enter the IMEI of each device coming back '
                                  f'({int(qty)}). Sold on this invoice: {", ".join(candidates) or "none"}.')
                    continue
            items.append({'line': line, 'description': line['description'], 'quantity': qty,
                          'unit_price': unit_paid, 'line_total': round(qty * unit_paid, 2),
                          'product_id': line['product_id'], 'units': units})

        value = round(sum(it['line_total'] for it in items), 2)
        if not errors and not items:
            errors.append('Enter the quantity coming back for at least one item.')
        if not reason:
            errors.append('Choose the reason for the return.')
        if return_type not in dict(RETURN_TYPES):
            errors.append('Choose what happens: refund, exchange or store credit.')
        if return_type == 'exchange':
            refund_amt = 0
        elif refund_amt < 0 or refund_amt > value + 0.5:
            errors.append(f'Refund cannot be more than what the customer paid for these items '
                          f'(TZS {value:,.0f}).')
        if errors:
            for e in errors:
                flash(e, 'danger')
            return _again(doc, _invoice_lines(doc['id']))

        branch_id = doc['branch_id']   # goods go back to the branch that sold them
        with transaction():
            return_number = get_next_number(branch_id, 'return', datetime.now().year)
            ret_id = execute_db("""
                INSERT INTO returns
                  (return_number, document_id, customer_id, walkin_name, branch_id,
                   reason, return_type, refund_amount, exchange_notes, notes,
                   status, processed_by, created_by)
                VALUES (?,?,?,?,?,?,?,?,?,?,'approved',?,?)
            """, (return_number, doc['id'], doc['customer_id'], doc['walkin_name'], branch_id,
                  reason, return_type, refund_amt, exch_notes, notes,
                  current_user.id, current_user.id))
            for it in items:
                execute_db("""
                    INSERT INTO return_items
                      (return_id, document_item_id, product_id,
                       description, quantity, unit_price, line_total, imeis)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (ret_id, it['line']['id'], it['product_id'], it['description'],
                      it['quantity'], it['unit_price'], it['line_total'],
                      ','.join(it['units']) or None))
                if it['product_id']:
                    stock_svc.move(it['product_id'], branch_id, it['quantity'], 'return',
                                   ref_doc_id=doc['id'], notes=return_number)
                if it['units']:
                    ph = ','.join('?' * len(it['units']))
                    execute_db(f"""UPDATE device_imeis SET status='in_stock', sold_document_id=NULL,
                                   sold_at=NULL, branch_id=?, condition='used',
                                   notes=? WHERE imei IN ({ph})""",
                               [branch_id, f'Returned on {return_number}'] + it['units'])
            audit('create', 'return', ret_id, return_number,
                  f"{doc['doc_number']}: {return_type} TZS {refund_amt:,.0f}", branch_id)

        flash(f'Return {return_number} logged and stock restored.', 'success')
        return redirect(url_for('returns.view', ret_id=ret_id))

    # Pre-fill from invoice link
    doc_id = request.args.get('doc_id', type=int)
    doc    = None
    doc_items = []
    if doc_id and _visible_invoice(doc_id):
        doc = query_db("""
            SELECT d.*, COALESCE(c.name, d.walkin_name) AS customer_name,
                   c.id AS cust_id
            FROM documents d
            LEFT JOIN customers c ON c.id = d.customer_id
            WHERE d.id = ?
        """, (doc_id,), one=True)
        doc_items = _invoice_lines(doc_id)

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
          AND (d.doc_number LIKE ? OR COALESCE(c.name, d.walkin_name) LIKE ? OR c.phone LIKE ?)
          AND (? OR d.branch_id = ?)
        ORDER BY d.created_at DESC
        LIMIT 10
    """, (f'%{q}%', f'%{q}%', f'%{q}%',
          1 if (current_user.is_admin or current_user.can('view_all_branches')
                or not current_user.branch_id) else 0,
          current_user.branch_id))
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
    if not _visible_invoice(doc_id):
        return jsonify([])
    out = []
    for r in _invoice_lines(doc_id):
        d = dict(r)
        d['remaining'] = float(r['quantity']) - float(r['returned'])
        d['unit_price'] = r['paid_unit']
        d['sold_imeis'] = _sold_units(doc_id, r['product_id']) if r['track_units'] else []
        out.append(d)
    return jsonify(out)
