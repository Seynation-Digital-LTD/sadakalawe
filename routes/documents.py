import zipfile
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, send_file, abort)
from flask_login import login_required, current_user
from database import execute_db, query_db
from services.numbering import get_next_number
from services.pdf_generator import generate_pdf
from config import VAT_RATE, DOC_TYPE_LABELS
from datetime import datetime, date
from io import BytesIO

bp = Blueprint('documents', __name__, url_prefix='/documents')

DOC_TYPES_ORDER = ['invoice', 'proforma', 'delivery_note']


def _fetch_doc_full(doc_id):
    return query_db("""
        SELECT d.*, b.name AS branch_name, b.short_code, b.address AS branch_address,
               c.name AS customer_name, c.phone AS customer_phone,
               c.email AS customer_email, c.tin AS customer_tin,
               c.address AS customer_address, u.full_name AS staff_name
        FROM documents d
        JOIN branches b ON d.branch_id = b.id
        LEFT JOIN customers c ON d.customer_id = c.id
        JOIN users u ON d.created_by = u.id
        WHERE d.id=?
    """, (doc_id,), one=True)


def _parse_items(form):
    descriptions = form.getlist('item_description[]')
    quantities   = form.getlist('item_qty[]')
    unit_prices  = form.getlist('item_price[]')
    product_ids  = form.getlist('item_product_id[]')
    items = []
    for i, desc in enumerate(descriptions):
        desc = desc.strip()
        if not desc:
            continue
        try:
            qty   = float(quantities[i] or 1)
            price = float(unit_prices[i] or 0)
        except (IndexError, ValueError):
            continue
        items.append({
            'description': desc,
            'quantity':    qty,
            'unit_price':  price,
            'line_total':  round(qty * price, 2),
            'product_id':  (product_ids[i] if i < len(product_ids) else None) or None,
        })
    return items


def _deduct_stock(items, branch_id, invoice_id):
    """Deduct sold quantities from per-branch stock and record movements."""
    for item in items:
        if not item.get('product_id'):
            continue
        qty = abs(item['quantity'])
        pid = item['product_id']
        # Update product_stock
        execute_db("""
            INSERT INTO product_stock (product_id, branch_id, quantity)
            VALUES (?,?,?)
            ON CONFLICT(product_id, branch_id)
            DO UPDATE SET quantity = MAX(0, quantity - excluded.quantity)
        """, (pid, branch_id, qty))
        # Log movement
        execute_db("""
            INSERT INTO stock_movements
              (product_id, branch_id, movement_type, quantity, reference_doc_id, recorded_by)
            VALUES (?,?,'sale',?,?,?)
        """, (pid, branch_id, -qty, invoice_id, current_user.id))
        # Sync global stock_count
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
    q             = request.args.get('q', '').strip()
    doc_type      = request.args.get('doc_type', '')
    branch_filter = request.args.get('branch_id', '')
    date_from     = request.args.get('date_from', '')
    date_to       = request.args.get('date_to', '')
    staff_filter  = request.args.get('staff_id', '')
    pay_status    = request.args.get('payment_status', '')

    sql = """
        SELECT d.*, b.name AS branch_name, c.name AS customer_name,
               u.full_name AS staff_name
        FROM documents d
        JOIN branches b ON d.branch_id = b.id
        LEFT JOIN customers c ON d.customer_id = c.id
        JOIN users u ON d.created_by = u.id
        WHERE 1=1
    """
    args = []

    if not current_user.is_admin and current_user.branch_id:
        sql += " AND d.branch_id=?"
        args.append(current_user.branch_id)
    elif branch_filter:
        sql += " AND d.branch_id=?"
        args.append(branch_filter)

    if q:
        sql += " AND (d.doc_number LIKE ? OR c.name LIKE ?)"
        args += [f'%{q}%', f'%{q}%']
    if doc_type:
        sql += " AND d.doc_type=?"
        args.append(doc_type)
    if date_from:
        sql += " AND DATE(d.created_at) >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND DATE(d.created_at) <= ?"
        args.append(date_to)
    if staff_filter:
        sql += " AND d.created_by=?"
        args.append(staff_filter)
    if pay_status:
        sql += " AND d.payment_status=?"
        args.append(pay_status)

    sql += " ORDER BY d.created_at DESC LIMIT 300"
    docs       = query_db(sql, args)
    branches   = query_db("SELECT * FROM branches ORDER BY name")
    staff_list = query_db("SELECT id, full_name FROM users ORDER BY full_name")
    return render_template('documents/list.html', docs=docs, branches=branches,
                           staff_list=staff_list, doc_types=DOC_TYPE_LABELS,
                           q=q, doc_type=doc_type, branch_filter=branch_filter,
                           date_from=date_from, date_to=date_to,
                           staff_filter=staff_filter, pay_status=pay_status)


@bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    branches = query_db("SELECT * FROM branches ORDER BY name")
    default_branch_id = current_user.branch_id or (branches[0]['id'] if branches else None)

    if request.method == 'POST':
        branch_id       = int(request.form['branch_id'])
        customer_id     = request.form.get('customer_id') or None
        is_vat          = 1 if request.form.get('is_vat') else 0
        notes           = request.form.get('notes', '').strip() or None
        efd_reference   = request.form.get('efd_reference', '').strip() or None
        validity_days   = int(request.form.get('validity_days', 7) or 7)
        vat_rate        = float(request.form.get('vat_rate', VAT_RATE) or VAT_RATE)
        payment_type    = request.form.get('payment_type', 'cash')  # cash / credit
        credit_due_date = request.form.get('credit_due_date', '').strip() or None

        # payment_status & amount_paid on creation
        if payment_type == 'credit':
            payment_status = 'credit'
            amount_paid    = 0.0
        else:
            payment_status = 'paid'
            amount_paid    = 0.0  # will be set to total below

        items = _parse_items(request.form)
        if not items:
            flash('Weka angalau bidhaa moja.', 'danger')
            return render_template('documents/new.html', branches=branches,
                                   vat_rate=VAT_RATE, default_branch_id=default_branch_id)

        subtotal   = sum(i['line_total'] for i in items)
        vat_amount = round(subtotal * vat_rate / 100, 2) if is_vat else 0
        total      = subtotal + vat_amount
        year       = datetime.now().year

        if payment_type == 'cash':
            amount_paid = total  # fully paid on creation

        created_ids = []
        invoice_id  = None

        for doc_type in DOC_TYPES_ORDER:
            doc_number = get_next_number(branch_id, doc_type, year)
            doc_id = execute_db("""
                INSERT INTO documents
                  (doc_number, doc_type, branch_id, customer_id, created_by,
                   is_vat, vat_rate, efd_reference, subtotal, vat_amount,
                   total, notes, validity_days,
                   payment_status, amount_paid, credit_due_date)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (doc_number, doc_type, branch_id, customer_id, current_user.id,
                  is_vat, vat_rate, efd_reference, subtotal, vat_amount, total,
                  notes, validity_days, payment_status, amount_paid, credit_due_date))

            for item in items:
                execute_db("""
                    INSERT INTO document_items
                      (document_id, product_id, description, quantity, unit_price, line_total)
                    VALUES (?,?,?,?,?,?)
                """, (doc_id, item['product_id'], item['description'],
                      item['quantity'], item['unit_price'], item['line_total']))

            created_ids.append(doc_id)
            if doc_type == 'invoice':
                invoice_id = doc_id

        # Deduct stock once, against the invoice
        if invoice_id:
            _deduct_stock(items, branch_id, invoice_id)

        ids_str = ','.join(str(i) for i in created_ids)
        return redirect(url_for('documents.result', ids=ids_str))

    return render_template('documents/new.html', branches=branches,
                           vat_rate=VAT_RATE, default_branch_id=default_branch_id,
                           today=date.today().isoformat())


@bp.route('/result')
@login_required
def result():
    ids_str = request.args.get('ids', '')
    ids  = [int(i) for i in ids_str.split(',') if i.strip().isdigit()]
    docs = [_fetch_doc_full(i) for i in ids]
    docs = [d for d in docs if d]
    return render_template('documents/result.html', docs=docs,
                           doc_type_labels=DOC_TYPE_LABELS, ids_str=ids_str)


@bp.route('/zip')
@login_required
def download_zip():
    ids_str = request.args.get('ids', '')
    ids = [int(i) for i in ids_str.split(',') if i.strip().isdigit()]

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for doc_id in ids:
            doc = _fetch_doc_full(doc_id)
            if not doc:
                continue
            customer = (query_db("SELECT * FROM customers WHERE id=?",
                                 (doc['customer_id'],), one=True)
                        if doc['customer_id'] else None)
            items  = query_db(
                "SELECT * FROM document_items WHERE document_id=? ORDER BY id", (doc_id,))
            branch = {'name': doc['branch_name'], 'address': doc['branch_address'],
                      'short_code': doc['short_code']}
            pdf_buf = generate_pdf(dict(doc),
                                   dict(customer) if customer else None,
                                   [dict(i) for i in items],
                                   branch, doc['staff_name'])
            zf.writestr(f"{doc['doc_number']}.pdf", pdf_buf.read())

    buffer.seek(0)
    customer_slug = ''
    if ids:
        first = _fetch_doc_full(ids[0])
        if first and first['customer_name']:
            customer_slug = '_' + first['customer_name'].replace(' ', '_')[:20]
    fname = f"Sadakalawe{customer_slug}_{datetime.now().strftime('%Y%m%d')}.zip"
    return send_file(buffer, mimetype='application/zip',
                     as_attachment=True, download_name=fname)


@bp.route('/<int:doc_id>')
@login_required
def view(doc_id):
    doc = _fetch_doc_full(doc_id)
    if not doc:
        flash('Hati haikupatikana.', 'danger')
        return redirect(url_for('documents.list'))
    items = query_db(
        "SELECT * FROM document_items WHERE document_id=? ORDER BY id", (doc_id,))
    payments = query_db(
        "SELECT * FROM payments WHERE document_id=? ORDER BY payment_date DESC", (doc_id,))
    return render_template('documents/view.html', doc=doc, items=items,
                           payments=payments,
                           doc_type_label=DOC_TYPE_LABELS.get(doc['doc_type'], doc['doc_type']))


@bp.route('/<int:doc_id>/pdf')
@login_required
def download_pdf(doc_id):
    doc = _fetch_doc_full(doc_id)
    if not doc:
        abort(404)
    customer = (query_db("SELECT * FROM customers WHERE id=?",
                         (doc['customer_id'],), one=True)
                if doc['customer_id'] else None)
    items  = query_db(
        "SELECT * FROM document_items WHERE document_id=? ORDER BY id", (doc_id,))
    branch = {'name': doc['branch_name'], 'address': doc['branch_address'],
              'short_code': doc['short_code']}
    pdf_buf = generate_pdf(dict(doc),
                           dict(customer) if customer else None,
                           [dict(i) for i in items],
                           branch, doc['staff_name'])
    return send_file(pdf_buf, mimetype='application/pdf',
                     as_attachment=False,
                     download_name=f"{doc['doc_number']}.pdf")


@bp.route('/<int:doc_id>/delete', methods=['POST'])
@login_required
def delete(doc_id):
    if not current_user.is_admin:
        flash('Ruhusa ya admin inahitajika.', 'danger')
        return redirect(url_for('documents.list'))
    doc = query_db("SELECT doc_number FROM documents WHERE id=?", (doc_id,), one=True)
    if doc:
        execute_db("DELETE FROM documents WHERE id=?", (doc_id,))
        flash(f'Hati {doc["doc_number"]} imefutwa.', 'success')
    return redirect(url_for('documents.list'))
