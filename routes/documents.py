import html
import re
import secrets
import zipfile
from urllib.parse import quote as urlquote
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, send_file, abort, current_app, session)
from flask_login import login_required, current_user
from database import execute_db, query_db
from services.numbering import get_next_number
from services.pdf_generator import generate_pdf
from services.email_service import send_document_email
from services.text_utils import tc, sc
from config import VAT_RATE, DOC_TYPE_LABELS
from routes.auth import perm_required
from datetime import datetime, date
from io import BytesIO
from pypdf import PdfWriter, PdfReader


def _wa_phone(phone):
    """Normalise a TZ phone number to WhatsApp format (no + prefix)."""
    if not phone:
        return ''
    p = re.sub(r'[\s\-\(\)+]', '', str(phone))
    if p.startswith('255'):
        return p
    if p.startswith('0') and len(p) >= 10:
        return '255' + p[1:]
    return '255' + p


def _wa_url(doc, items, doc_type_label, customer_phone):
    lines = [
        f"*Sadakalawe Enterprises*",
        f"📄 *{doc_type_label} #{doc['doc_number']}*",
        "",
    ]
    for item in items:
        lines.append(f"• {item['description']} × {item['quantity']:g} — TZS {item['line_total']:,.0f}")
    lines.append("")
    if doc['is_vat']:
        lines.append(f"Subtotal: TZS {doc['subtotal']:,.0f}")
        lines.append(f"VAT (18%): TZS {doc['vat_amount']:,.0f}")
    lines.append(f"*TOTAL: TZS {doc['total']:,.0f}*")
    lines.append("")
    lines.append("Asante kwa kununua Sadakalawe! 🙏")
    lines.append("📞 +255 768 596 006 | sadakalawe.com")
    msg = "\n".join(lines)
    phone = _wa_phone(customer_phone)
    if phone:
        return f"https://wa.me/{phone}?text={urlquote(msg)}"
    return f"https://wa.me/?text={urlquote(msg)}"

bp = Blueprint('documents', __name__, url_prefix='/documents')

DOC_TYPES_ORDER = ['invoice', 'proforma', 'delivery_note']


def _fetch_doc_full(doc_id):
    return query_db("""
        SELECT d.*, b.name AS branch_name, b.short_code, b.address AS branch_address,
               COALESCE(c.name, d.walkin_name) AS customer_name,
               c.phone AS customer_phone,
               c.email AS customer_email, c.tin AS customer_tin,
               c.address AS customer_address, u.full_name AS staff_name,
               COALESCE((
                   SELECT SUM(d2.total) FROM documents d2
                   WHERE d2.customer_id = d.customer_id AND d2.doc_type='invoice'
               ), 0) AS customer_lifetime_spend
        FROM documents d
        JOIN branches b ON d.branch_id = b.id
        LEFT JOIN customers c ON d.customer_id = c.id
        JOIN users u ON d.created_by = u.id
        WHERE d.id=?
    """, (doc_id,), one=True)


def _parse_items(form):
    descriptions = form.getlist('item_description[]')
    specs_list   = form.getlist('item_specs[]')
    quantities   = form.getlist('item_qty[]')
    unit_prices  = form.getlist('item_price[]')
    product_ids  = form.getlist('item_product_id[]')
    discounts    = form.getlist('item_discount[]')
    units_list   = form.getlist('item_units[]')   # comma-separated IMEIs per row
    items = []
    for i, desc in enumerate(descriptions):
        desc = desc.strip()
        if not desc:
            continue
        try:
            qty      = float(quantities[i] or 1)
            price    = float(unit_prices[i] or 0)
            disc_pct = max(0, min(100, float(discounts[i] or 0) if i < len(discounts) else 0))
        except (IndexError, ValueError):
            continue
        specs = specs_list[i].strip() if i < len(specs_list) else ''
        full_desc = (desc + chr(10) + specs) if specs else desc
        discounted_price = round(price * (1 - disc_pct / 100), 2)
        items.append({
            'description':  full_desc,
            'quantity':     qty,
            'unit_price':   price,
            'discount_pct': disc_pct,
            'line_total':   round(qty * discounted_price, 2),
            'product_id':   (product_ids[i] if i < len(product_ids) else None) or None,
            'units':        [x.strip() for x in (units_list[i] if i < len(units_list) else '').split(',') if x.strip()],
        })
    return items


def _validate_units(items, branch_id):
    """For products tracked per unit, every sold unit needs an IMEI picked from stock.

    Returns a list of error messages — empty means the sale is good to record.
    """
    errors = []
    seen = set()
    for item in items:
        if not item['product_id']:
            continue
        p = query_db("SELECT model, track_units FROM products WHERE id=?",
                     (item['product_id'],), one=True)
        if not p or not p['track_units']:
            continue

        qty   = int(abs(item['quantity']))
        units = item['units']
        if len(units) != qty:
            errors.append(
                f'{p["model"]}: select {qty} IMEI{"s" if qty != 1 else ""} '
                f'(you selected {len(units)}).')
            continue

        for imei in units:
            if imei in seen:
                errors.append(f'IMEI {imei} is on this sale twice.')
                continue
            seen.add(imei)
            row = query_db(
                "SELECT status, branch_id FROM device_imeis WHERE imei=? AND product_id=?",
                (imei, item['product_id']), one=True)
            if not row:
                errors.append(f'IMEI {imei} is not in stock for {p["model"]}.')
            elif row['status'] != 'in_stock':
                errors.append(f'IMEI {imei} is already marked {row["status"]}.')
            elif row['branch_id'] != branch_id:
                errors.append(f'IMEI {imei} belongs to another branch.')
    return errors


def _register_units(items, doc_id, customer_id):
    """Record the picked units against the document and mark them sold."""
    for item in items:
        for imei in item['units']:
            unit = query_db("SELECT * FROM device_imeis WHERE imei=?", (imei,), one=True)
            if not unit:
                continue
            execute_db("""
                INSERT INTO device_sales
                  (document_id, customer_id, product_id, imei, serial_number,
                   color, storage, created_by)
                VALUES (?,?,?,?,?,?,?,?)
            """, (doc_id, customer_id, item['product_id'], imei,
                  unit['serial_number'], unit['color'], unit['storage'],
                  current_user.id))
            execute_db("""
                UPDATE device_imeis
                   SET status='sold', sold_document_id=?, sold_at=datetime('now','localtime')
                 WHERE imei=?
            """, (doc_id, imei))


def _deduct_stock(items, branch_id, invoice_id):
    """Deduct sold quantities from per-branch stock and record movements.

    Lines typed by hand (no product_id) have nothing to deduct from, and products
    flagged track_units still need their IMEIs registered on the document — both
    are flagged to the user rather than failing silently.
    """
    untracked = [i['description'] for i in items if not i['product_id']]
    if untracked:
        flash('Stock was not adjusted for hand-typed lines: '
              + ', '.join(untracked)
              + '. Pick items from the catalogue so stock stays accurate.', 'warning')

    for item in items:
        if not item['product_id']:
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


def _restore_invoice_stock(invoice_id):
    """Restore stock when an invoice is deleted/voided."""
    doc = query_db("SELECT branch_id FROM documents WHERE id=?", (invoice_id,), one=True)
    if not doc:
        return
    branch_id = doc['branch_id']
    items = query_db(
        "SELECT product_id, quantity FROM document_items WHERE document_id=? AND product_id IS NOT NULL",
        (invoice_id,))
    for item in items:
        pid = item['product_id']
        qty = abs(item['quantity'])
        execute_db("""
            INSERT INTO product_stock (product_id, branch_id, quantity)
            VALUES (?,?,?)
            ON CONFLICT(product_id, branch_id)
            DO UPDATE SET quantity = quantity + excluded.quantity
        """, (pid, branch_id, qty))
        execute_db("""
            UPDATE products SET
              stock_count = (SELECT COALESCE(SUM(quantity),0)
                             FROM product_stock WHERE product_id=?),
              updated_at  = datetime('now','localtime')
            WHERE id=?
        """, (pid, pid))
    # Release any individually tracked units back into stock. device_sales rows are
    # cascade-deleted with the document, so this has to run before that happens.
    execute_db("""
        UPDATE device_imeis
           SET status='in_stock', sold_document_id=NULL, sold_at=NULL
         WHERE sold_document_id=?
            OR imei IN (SELECT imei FROM device_sales WHERE document_id=? AND imei IS NOT NULL)
    """, (invoice_id, invoice_id))

    # Remove the sale stock movements for this invoice
    execute_db("DELETE FROM stock_movements WHERE reference_doc_id=? AND movement_type='sale'",
               (invoice_id,))


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
        SELECT d.*, b.name AS branch_name,
               COALESCE(c.name, d.walkin_name) AS customer_name,
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
        sql += " AND (d.doc_number LIKE ? OR COALESCE(c.name,d.walkin_name) LIKE ?)"
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

    sql += " ORDER BY d.created_at DESC LIMIT 500"
    docs = query_db(sql, args)

    # Group docs by batch_id so invoice/proforma/DN appear together
    groups = []
    batch_children = {}
    for d in docs:
        bid = d['batch_id']
        if bid:
            if bid not in batch_children:
                batch_children[bid] = []
            batch_children[bid].append(d)
        else:
            groups.append({'lead': d, 'children': [], 'batch_id': None})

    for bid, members in batch_children.items():
        lead = next((m for m in members if m['doc_type'] == 'invoice'), members[0])
        children = [m for m in members if m['id'] != lead['id']]
        groups.append({'lead': lead, 'children': children, 'batch_id': bid})

    groups.sort(key=lambda g: g['lead']['created_at'], reverse=True)

    branches   = query_db("SELECT * FROM branches ORDER BY name")
    staff_list = query_db("SELECT id, full_name FROM users ORDER BY full_name")
    return render_template('documents/list.html', groups=groups, branches=branches,
                           staff_list=staff_list, doc_types=DOC_TYPE_LABELS,
                           q=q, doc_type=doc_type, branch_filter=branch_filter,
                           date_from=date_from, date_to=date_to,
                           staff_filter=staff_filter, pay_status=pay_status)


@bp.route('/new', methods=['GET', 'POST'])
@login_required
@perm_required('create_documents')
def new():
    branches = query_db("SELECT * FROM branches ORDER BY name")
    default_branch_id = current_user.branch_id or (branches[0]['id'] if branches else None)

    if request.method == 'POST':
        # ── Duplicate-submission guard ──────────────────────────────────
        submitted_nonce = request.form.get('_form_nonce', '')
        stored_nonce    = session.pop('doc_form_nonce', None)
        if not submitted_nonce or submitted_nonce != stored_nonce:
            # Nonce mismatch — this form was already submitted.
            # Find the most recent batch by this user (last 60 s) and redirect.
            recent = query_db("""
                SELECT id FROM documents
                WHERE created_by=? AND created_at >= datetime('now','localtime','-60 seconds')
                ORDER BY id DESC LIMIT 3
            """, (current_user.id,))
            if recent:
                ids_str = ','.join(str(r['id']) for r in recent)
                flash('This form was already submitted — here are your documents.', 'info')
                return redirect(url_for('documents.result', ids=ids_str))
            flash('Form session expired. Please fill in the details again.', 'warning')
            return redirect(url_for('documents.new'))
        # ───────────────────────────────────────────────────────────────

        branch_id       = int(request.form['branch_id'])
        customer_id     = request.form.get('customer_id') or None
        walkin_name     = tc(request.form.get('walkin_name', '')) or None
        is_vat          = 1 if request.form.get('is_vat') else 0
        notes           = sc(request.form.get('notes', '')) or None
        efd_reference   = request.form.get('efd_reference', '').strip() or None
        validity_days   = int(request.form.get('validity_days', 7) or 7)
        vat_rate        = float(request.form.get('vat_rate', VAT_RATE) or VAT_RATE)
        payment_type    = request.form.get('payment_type', 'cash')
        credit_due_date = request.form.get('credit_due_date', '').strip() or None

        # payment_type is either 'credit' or the actual method (cash/card/mpesa/…)
        if payment_type == 'credit':
            payment_status = 'credit'
            payment_method = 'credit'
            amount_paid    = 0.0
        else:
            payment_status = 'paid'
            payment_method = payment_type  # store the specific method
            amount_paid    = 0.0  # set to total below

        items = _parse_items(request.form)
        if not items:
            flash('Please add at least one item.', 'danger')
            return render_template('documents/new.html', branches=branches,
                                   vat_rate=VAT_RATE, default_branch_id=default_branch_id)

        # Unit-tracked products must have their IMEIs picked before the sale is recorded
        unit_errors = _validate_units(items, branch_id)
        if unit_errors:
            for msg in unit_errors:
                flash(msg, 'danger')
            session['doc_form_nonce'] = submitted_nonce  # let them resubmit
            return render_template('documents/new.html', branches=branches,
                                   vat_rate=VAT_RATE, default_branch_id=default_branch_id,
                                   today=date.today().isoformat(),
                                   form_nonce=submitted_nonce)

        subtotal   = sum(i['line_total'] for i in items)
        vat_amount = round(subtotal * vat_rate / 100, 2) if is_vat else 0
        total      = subtotal + vat_amount
        year       = datetime.now().year

        if payment_type != 'credit':
            amount_paid = total  # fully paid on creation for all non-credit methods

        # ── Server-side idempotency: block genuine duplicates ──────────
        # If the same staff created an invoice for the same customer with the
        # same total at this branch within the last 5 minutes, redirect to it.
        dup_check = query_db("""
            SELECT d.id FROM documents d
            WHERE d.created_by = ?
              AND d.branch_id  = ?
              AND d.doc_type   = 'invoice'
              AND d.total      = ?
              AND (d.customer_id = ? OR (d.customer_id IS NULL AND d.walkin_name = ?))
              AND d.created_at >= datetime('now','localtime','-5 minutes')
            ORDER BY d.id DESC LIMIT 1
        """, (current_user.id, branch_id, total,
              customer_id, walkin_name))
        if dup_check:
            # Find the full batch for that invoice
            inv_id = dup_check[0]['id']
            inv_doc = query_db("SELECT batch_id FROM documents WHERE id=?", (inv_id,), one=True)
            if inv_doc and inv_doc['batch_id']:
                batch_docs = query_db(
                    "SELECT id FROM documents WHERE batch_id=? ORDER BY id",
                    (inv_doc['batch_id'],))
                ids_str = ','.join(str(r['id']) for r in batch_docs)
            else:
                ids_str = str(inv_id)
            flash('This sale was already recorded. Showing the existing documents.', 'info')
            return redirect(url_for('documents.result', ids=ids_str))
        # ────────────────────────────────────────────────────────────────

        created_ids = []
        invoice_id  = None
        delivery_note_id = None
        batch_id    = None   # set from invoice number on first iteration

        for doc_type in DOC_TYPES_ORDER:
            doc_number = get_next_number(branch_id, doc_type, year)
            if doc_type == 'invoice':
                batch_id = doc_number   # use invoice number as the shared batch key
            doc_id = execute_db("""
                INSERT INTO documents
                  (doc_number, doc_type, branch_id, customer_id, walkin_name, created_by,
                   is_vat, vat_rate, efd_reference, subtotal, vat_amount,
                   total, notes, validity_days,
                   payment_status, payment_method, amount_paid, credit_due_date, batch_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (doc_number, doc_type, branch_id, customer_id, walkin_name, current_user.id,
                  is_vat, vat_rate, efd_reference, subtotal, vat_amount, total,
                  notes, validity_days, payment_status, payment_method,
                  amount_paid, credit_due_date, batch_id))

            for item in items:
                execute_db("""
                    INSERT INTO document_items
                      (document_id, product_id, description, quantity, unit_price, discount_pct, line_total)
                    VALUES (?,?,?,?,?,?,?)
                """, (doc_id, item['product_id'], item['description'],
                      item['quantity'], item['unit_price'],
                      item.get('discount_pct', 0), item['line_total']))

            created_ids.append(doc_id)
            if doc_type == 'invoice':
                invoice_id = doc_id
            elif doc_type == 'delivery_note':
                delivery_note_id = doc_id

        # Deduct stock ONCE per sale. Goods leave on either the invoice or the
        # delivery note — when both exist they're the same sale, so the invoice
        # carries the movement and the DN must not deduct a second time.
        stock_doc_id = invoice_id or delivery_note_id
        if stock_doc_id:
            _deduct_stock(items, branch_id, stock_doc_id)
            _register_units(items, stock_doc_id, customer_id)

        ids_str = ','.join(str(i) for i in created_ids)
        return redirect(url_for('documents.result', ids=ids_str))

    form_nonce = secrets.token_hex(16)
    session['doc_form_nonce'] = form_nonce
    return render_template('documents/new.html', branches=branches,
                           vat_rate=VAT_RATE, default_branch_id=default_branch_id,
                           today=date.today().isoformat(),
                           form_nonce=form_nonce)


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
@perm_required('download_documents')
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
                        if doc['customer_id']
                        else ({'name': doc['walkin_name']} if doc['walkin_name'] else None))
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


@bp.route('/merged')
@login_required
@perm_required('download_documents')
def download_merged():
    """Download all selected documents as a single merged PDF."""
    ids_str = request.args.get('ids', '')
    ids = [int(i) for i in ids_str.split(',') if i.strip().isdigit()]
    if not ids:
        abort(400)

    writer = PdfWriter()
    customer_name = ''

    for doc_id in ids:
        doc = _fetch_doc_full(doc_id)
        if not doc:
            continue
        customer = (query_db("SELECT * FROM customers WHERE id=?",
                             (doc['customer_id'],), one=True)
                    if doc['customer_id']
                    else ({'name': doc['walkin_name']} if doc['walkin_name'] else None))
        items  = query_db(
            "SELECT * FROM document_items WHERE document_id=? ORDER BY id", (doc_id,))
        branch = {'name': doc['branch_name'], 'address': doc['branch_address'],
                  'short_code': doc['short_code']}
        pdf_buf = generate_pdf(dict(doc),
                               dict(customer) if customer else None,
                               [dict(i) for i in items],
                               branch, doc['staff_name'])
        reader = PdfReader(pdf_buf)
        for page in reader.pages:
            writer.add_page(page)
        if not customer_name and doc['customer_name']:
            customer_name = doc['customer_name']

    buf = BytesIO()
    writer.write(buf)
    buf.seek(0)
    slug = '_' + customer_name.replace(' ', '_')[:20] if customer_name else ''
    fname = f"Sadakalawe{slug}_{datetime.now().strftime('%Y%m%d')}.pdf"
    return send_file(buf, mimetype='application/pdf',
                     as_attachment=True, download_name=fname)


@bp.route('/batch/<batch_id>')
@login_required
def view_batch(batch_id):
    """Show all documents that belong to the same sale batch."""
    docs = query_db("""
        SELECT d.*, b.name AS branch_name,
               COALESCE(c.name, d.walkin_name) AS customer_name
        FROM documents d
        JOIN branches b ON d.branch_id = b.id
        LEFT JOIN customers c ON d.customer_id = c.id
        WHERE d.batch_id=?
        ORDER BY d.doc_type
    """, (batch_id,))
    if not docs:
        flash('Sale batch not found.', 'danger')
        return redirect(url_for('documents.list'))
    ids_str = ','.join(str(d['id']) for d in docs)
    return render_template('documents/batch.html', docs=docs, batch_id=batch_id,
                           ids_str=ids_str, doc_type_labels=DOC_TYPE_LABELS)


@bp.route('/<int:doc_id>')
@login_required
def view(doc_id):
    doc = _fetch_doc_full(doc_id)
    if not doc:
        flash('Document not found.', 'danger')
        return redirect(url_for('documents.list'))
    items = query_db("""
        SELECT di.*, COALESCE(p.brand_category, '') AS brand_category
        FROM document_items di
        LEFT JOIN products p ON p.id = di.product_id
        WHERE di.document_id=? ORDER BY di.id
    """, (doc_id,))
    payments = query_db(
        "SELECT * FROM payments WHERE document_id=? ORDER BY payment_date DESC", (doc_id,))
    # Sibling docs in the same batch (the other 2 related docs from this sale)
    siblings = []
    if doc['batch_id']:
        siblings = query_db("""
            SELECT id, doc_number, doc_type FROM documents
            WHERE batch_id=? AND id!=?
            ORDER BY doc_type
        """, (doc['batch_id'], doc_id))
    label = DOC_TYPE_LABELS.get(doc['doc_type'], doc['doc_type'])
    wa = _wa_url(dict(doc), [dict(i) for i in items], label, doc['customer_phone'])
    return render_template('documents/view.html', doc=doc, items=items,
                           payments=payments, siblings=siblings,
                           doc_type_label=label, wa_url=wa,
                           today=date.today().isoformat())


@bp.route('/<int:doc_id>/pdf')
@login_required
@perm_required('download_documents')
def download_pdf(doc_id):
    doc = _fetch_doc_full(doc_id)
    if not doc:
        abort(404)
    customer = (query_db("SELECT * FROM customers WHERE id=?",
                         (doc['customer_id'],), one=True)
                if doc['customer_id']
                else ({'name': doc['walkin_name']} if doc['walkin_name'] else None))
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
@perm_required('void_documents')
def delete(doc_id):
    doc = query_db("SELECT id, doc_number, doc_type FROM documents WHERE id=?", (doc_id,), one=True)
    if doc:
        if doc['doc_type'] == 'invoice':
            _restore_invoice_stock(doc_id)
        execute_db("DELETE FROM document_items WHERE document_id=?", (doc_id,))
        execute_db("DELETE FROM documents WHERE id=?", (doc_id,))
        flash(f'Document {doc["doc_number"]} deleted.', 'success')
    return redirect(url_for('documents.list'))


@bp.route('/<int:doc_id>/delete-batch', methods=['POST'])
@login_required
@perm_required('void_documents')
def delete_batch(doc_id):
    """Delete an entire batch (invoice + proforma + delivery note) at once."""
    lead = query_db("SELECT id, doc_number, doc_type, batch_id FROM documents WHERE id=?",
                    (doc_id,), one=True)
    if not lead:
        flash('Document not found.', 'danger')
        return redirect(url_for('documents.list'))

    # Gather all docs in the batch
    if lead['batch_id']:
        batch_docs = query_db(
            "SELECT id, doc_number, doc_type FROM documents WHERE batch_id=?",
            (lead['batch_id'],))
    else:
        batch_docs = [lead]

    # Restore stock from the invoice in the batch
    for bdoc in batch_docs:
        if bdoc['doc_type'] == 'invoice':
            _restore_invoice_stock(bdoc['id'])
            break

    # Delete items then documents
    for bdoc in batch_docs:
        execute_db("DELETE FROM document_items WHERE document_id=?", (bdoc['id'],))
    ids = [bdoc['id'] for bdoc in batch_docs]
    placeholders = ','.join('?' * len(ids))
    execute_db(f"DELETE FROM documents WHERE id IN ({placeholders})", ids)

    nums = ', '.join(bdoc['doc_number'] for bdoc in batch_docs)
    flash(f'Deleted: {nums}', 'success')
    return redirect(url_for('documents.list'))


@bp.route('/<int:doc_id>/edit', methods=['GET', 'POST'])
@login_required
@perm_required('create_documents')
def edit(doc_id):
    doc = _fetch_doc_full(doc_id)
    if not doc:
        flash('Document not found.', 'danger')
        return redirect(url_for('documents.list'))

    if not current_user.is_admin and doc['created_by'] != current_user.id:
        flash('You can only edit your own documents.', 'danger')
        return redirect(url_for('documents.view', doc_id=doc_id))

    old_items = query_db("SELECT * FROM document_items WHERE document_id=? ORDER BY id", (doc_id,))
    branches  = query_db("SELECT * FROM branches ORDER BY id")

    if request.method == 'POST':
        parsed_items = _parse_items(request.form)
        if not parsed_items:
            flash('At least one item is required.', 'danger')
            return redirect(url_for('documents.edit', doc_id=doc_id))

        is_vat         = bool(request.form.get('is_vat'))
        vat_rate_val   = float(request.form.get('vat_rate') or VAT_RATE)
        customer_id    = request.form.get('customer_id') or None
        walkin_name    = request.form.get('walkin_name', '').strip() or None
        payment_type   = request.form.get('payment_type', 'cash')
        payment_method = request.form.get('_method', doc['payment_method'] or 'cash')
        credit_due_date = request.form.get('credit_due_date') or None
        notes          = request.form.get('notes', '').strip() or None
        efd_reference  = request.form.get('efd_reference', '').strip() or None

        subtotal    = round(sum(i['line_total'] for i in parsed_items), 2)
        vat_amount  = round(subtotal * vat_rate_val / 100, 2) if is_vat else 0.0
        total       = round(subtotal + vat_amount, 2)
        # Status always follows the money actually received. Editing never changes
        # amount_paid — if the new total is higher than what was paid, the invoice
        # becomes 'partial' and shows up in Credits so the balance gets collected.
        paid_so_far = float(doc['amount_paid'] or 0)
        if doc['doc_type'] != 'invoice':
            pay_status = doc['payment_status']
        elif paid_so_far >= total - 0.01:
            pay_status = 'paid'
        elif paid_so_far > 0:
            pay_status = 'partial'
        else:
            pay_status = 'credit'

        # Restore old stock for invoices before rewriting items
        if doc['doc_type'] == 'invoice':
            for oi in old_items:
                if oi['product_id']:
                    pid = oi['product_id']
                    qty = abs(float(oi['quantity']))
                    execute_db("""
                        INSERT INTO product_stock (product_id, branch_id, quantity) VALUES (?,?,?)
                        ON CONFLICT(product_id, branch_id)
                        DO UPDATE SET quantity = quantity + excluded.quantity
                    """, (pid, doc['branch_id'], qty))
                    execute_db("""
                        UPDATE products SET
                          stock_count=(SELECT COALESCE(SUM(quantity),0)
                                       FROM product_stock WHERE product_id=?),
                          updated_at=datetime('now','localtime')
                        WHERE id=?
                    """, (pid, pid))

        execute_db("DELETE FROM document_items WHERE document_id=?", (doc_id,))
        for item in parsed_items:
            execute_db("""
                INSERT INTO document_items
                  (document_id, product_id, description, quantity, unit_price, line_total, discount_pct)
                VALUES (?,?,?,?,?,?,?)
            """, (doc_id, item['product_id'], item['description'],
                  item['quantity'], item['unit_price'], item['line_total'], item['discount_pct']))

        execute_db("""
            UPDATE documents SET
              customer_id=?, walkin_name=?, payment_method=?, payment_status=?,
              credit_due_date=?, notes=?, is_vat=?, vat_rate=?, efd_reference=?,
              subtotal=?, vat_amount=?, total=?,
              updated_at=datetime('now','localtime')
            WHERE id=?
        """, (customer_id, walkin_name, payment_method, pay_status,
              credit_due_date, notes, 1 if is_vat else 0, vat_rate_val, efd_reference,
              subtotal, vat_amount, total, doc_id))

        if doc['doc_type'] == 'invoice':
            _deduct_stock(parsed_items, doc['branch_id'], doc_id)

        flash(f'{doc["doc_number"]} updated.', 'success')
        return redirect(url_for('documents.view', doc_id=doc_id))

    return render_template('documents/edit.html',
                           doc=doc, items=old_items, branches=branches,
                           vat_rate=VAT_RATE, today=date.today().isoformat())


@bp.route('/public/<token>')
def public_pdf(token):
    """Serve a PDF publicly using a share token — no login required."""
    doc = query_db("SELECT * FROM documents WHERE share_token=?", (token,), one=True)
    if not doc:
        abort(404)
    full_doc = _fetch_doc_full(doc['id'])
    customer = (query_db("SELECT * FROM customers WHERE id=?",
                         (full_doc['customer_id'],), one=True)
                if full_doc['customer_id']
                else ({'name': full_doc['walkin_name']} if full_doc['walkin_name'] else None))
    items  = query_db(
        "SELECT * FROM document_items WHERE document_id=? ORDER BY id", (doc['id'],))
    branch = {'name': full_doc['branch_name'], 'address': full_doc['branch_address'],
              'short_code': full_doc['short_code']}
    pdf_buf = generate_pdf(dict(full_doc),
                           dict(customer) if customer else None,
                           [dict(i) for i in items],
                           branch, full_doc['staff_name'])
    return send_file(pdf_buf, mimetype='application/pdf',
                     as_attachment=False,
                     download_name=f"{full_doc['doc_number']}.pdf")


@bp.route('/<int:doc_id>/whatsapp')
@login_required
def whatsapp_share(doc_id):
    """Generate a public share token and open WhatsApp with the PDF link."""
    doc = _fetch_doc_full(doc_id)
    if not doc:
        abort(404)

    token = doc['share_token']
    if not token:
        token = secrets.token_urlsafe(32)
        execute_db("UPDATE documents SET share_token=? WHERE id=?", (token, doc_id))

    pdf_url = request.host_url.rstrip('/') + url_for('documents.public_pdf', token=token)
    label   = DOC_TYPE_LABELS.get(doc['doc_type'], doc['doc_type'])
    name    = doc['customer_name'] or 'Valued Customer'

    lines = [
        '*Sadakalawe Enterprises*',
        f'Habari {name},',
        '',
        f'Hapa chini ni {label} yako:',
        f'📄 *{doc["doc_number"]}* — TZS {float(doc["total"]):,.0f}',
        '',
        '🔗 Bonyeza hapa kupakua PDF yako:',
        pdf_url,
        '',
        'Asante kwa kununua Sadakalawe! 🙏',
        '+255 768 596 006  |  sadakalawe.com',
    ]
    msg   = '\n'.join(lines)
    phone = _wa_phone(doc['customer_phone'] or '')
    wa    = (f'https://wa.me/{phone}?text={urlquote(msg)}'
             if phone else f'https://wa.me/?text={urlquote(msg)}')
    return redirect(wa)


@bp.route('/<int:doc_id>/email', methods=['POST'])
@login_required
def email_document(doc_id):
    """Email the document PDF to a given address."""
    from routes.settings import get_mail_config
    back = request.form.get('_next') or url_for('documents.view', doc_id=doc_id)
    try:
        doc = _fetch_doc_full(doc_id)
        if not doc:
            abort(404)
        doc = dict(doc)

        mail_config = get_mail_config()
        if not mail_config.get('MAIL_USERNAME') or not mail_config.get('MAIL_PASSWORD'):
            flash('Email not configured — go to Settings (admin sidebar) to enter Gmail credentials.', 'warning')
            return redirect(back)

        to_email = request.form.get('to_email', '').strip()
        message  = request.form.get('message', '').strip()

        if not to_email:
            flash('Please enter an email address.', 'danger')
            return redirect(back)

        customer = (query_db("SELECT * FROM customers WHERE id=?",
                             (doc['customer_id'],), one=True)
                    if doc['customer_id']
                    else ({'name': doc['walkin_name']} if doc['walkin_name'] else None))
        items  = query_db(
            "SELECT * FROM document_items WHERE document_id=? ORDER BY id", (doc_id,))
        branch = {'name': doc['branch_name'], 'address': doc['branch_address'],
                  'short_code': doc['short_code']}

        pdf_buf   = generate_pdf(dict(doc),
                                 dict(customer) if customer else None,
                                 [dict(i) for i in items],
                                 branch, doc['staff_name'])
        pdf_bytes = pdf_buf.read()

        label         = DOC_TYPE_LABELS.get(doc['doc_type'], doc['doc_type'])
        customer_name = html.escape(doc['customer_name'] or 'Valued Customer')
        subject       = f"Sadakalawe Enterprises — {label} {doc['doc_number']}"

        personal_block = ''
        if message:
            personal_block = ('<p style="margin:16px 0;color:#594138">'
                              + html.escape(message).replace('\n', '<br>') + '</p>')

        body_html = f"""
        <div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto">
          <div style="background:#F26522;padding:18px 28px;border-radius:8px 8px 0 0">
            <h2 style="color:#fff;margin:0;font-size:18px">Sadakalawe Enterprises</h2>
          </div>
          <div style="background:#fff;border:1px solid #e1bfb3;border-top:none;padding:24px 28px;border-radius:0 0 8px 8px">
            <p style="color:#1b1c1c;font-size:15px">Dear {customer_name},</p>
            <p style="color:#5f5e5e">Please find attached your <strong>{label}</strong>
               <strong>{doc['doc_number']}</strong> from Sadakalawe Enterprises.</p>
            <div style="background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;padding:14px 18px;margin:18px 0">
              <p style="margin:0 0 6px 0;color:#594138;font-size:13px">Document Summary</p>
              <p style="margin:0;color:#1b1c1c;font-size:20px;font-weight:bold">
                TZS {float(doc.get('total') or 0):,.0f}
              </p>
              <p style="margin:4px 0 0 0;color:#5f5e5e;font-size:12px">
                {label} &middot; {str(doc.get('created_at', ''))[:10]}
              </p>
            </div>
            {personal_block}
            <p style="color:#5f5e5e;font-size:13px">
              If you have any questions, please contact us at
              <a href="tel:+255768596006" style="color:#F26522">+255 768 596 006</a> or reply to this email.
            </p>
            <hr style="border:none;border-top:1px solid #e1bfb3;margin:20px 0">
            <p style="color:#9ca3af;font-size:11px;margin:0">
              Sadakalawe Enterprises &middot; Bondeni Street, Arusha &amp; Kariakoo, Dar es Salaam
              &middot; TIN: 164-334-864 &middot; sadakalawe.com
            </p>
          </div>
        </div>
        """

        ok, err = send_document_email(
            to_email=to_email,
            subject=subject,
            body_html=body_html,
            pdf_bytes=pdf_bytes,
            filename=f"{doc['doc_number']}.pdf",
            app_config=mail_config,
        )

        if ok:
            flash(f'Document emailed to {to_email}.', 'success')
        else:
            flash(f'Email failed: {err}', 'danger')

        return redirect(back)

    except Exception as exc:
        current_app.logger.exception('email_document crashed for doc_id=%s', doc_id)
        flash(f'Unexpected error: {exc}', 'danger')
        return redirect(back)


@bp.route('/<int:doc_id>/convert', methods=['POST'])
@login_required
@perm_required('create_documents')
def convert(doc_id):
    """Convert a proforma → invoice, or invoice → delivery note."""
    source = query_db("""
        SELECT d.*, b.short_code AS branch_code
        FROM documents d JOIN branches b ON d.branch_id = b.id
        WHERE d.id=?
    """, (doc_id,), one=True)
    if not source:
        abort(404)

    src_type = source['doc_type']
    if src_type == 'proforma':
        target_type = 'invoice'
    elif src_type == 'invoice':
        target_type = 'delivery_note'
    else:
        flash('Only proformas and invoices can be converted.', 'danger')
        return redirect(url_for('documents.view', doc_id=doc_id))

    items = query_db(
        "SELECT * FROM document_items WHERE document_id=? ORDER BY id", (doc_id,))

    doc_number = get_next_number(source['branch_id'], target_type, date.today().year)

    # Payment details only relevant for proforma → invoice
    if target_type == 'invoice':
        pay_method     = request.form.get('payment_method', 'cash')
        pay_status     = 'credit' if pay_method == 'credit' else 'paid'
        credit_due     = request.form.get('credit_due_date', '').strip() or None
        amount_paid    = 0.0 if pay_status == 'credit' else float(source['total'])
        actual_method  = request.form.get('credit_method', 'cash') if pay_status == 'credit' else pay_method
        notes          = request.form.get('notes', source['notes'] or '').strip() or None
    else:
        pay_method    = source['payment_method']
        pay_status    = source['payment_status']
        credit_due    = source['credit_due_date']
        amount_paid   = source['amount_paid']
        actual_method = pay_method
        notes         = request.form.get('notes', source['notes'] or '').strip() or None

    new_id = execute_db("""
        INSERT INTO documents
          (doc_number, doc_type, branch_id, customer_id, created_by,
           is_vat, vat_rate, efd_reference, subtotal, vat_amount, total,
           notes, validity_days, status, payment_status, payment_method,
           amount_paid, credit_due_date, walkin_name, batch_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        doc_number, target_type, source['branch_id'], source['customer_id'],
        current_user.id,
        source['is_vat'], source['vat_rate'], None,
        source['subtotal'], source['vat_amount'], source['total'],
        notes, source['validity_days'], 'final',
        pay_status, actual_method, amount_paid, credit_due,
        source['walkin_name'], source['batch_id'],
    ))

    for item in items:
        execute_db("""
            INSERT INTO document_items
              (document_id, product_id, description, quantity, unit_price, discount_pct, line_total)
            VALUES (?,?,?,?,?,?,?)
        """, (new_id, item['product_id'], item['description'],
               item['quantity'], item['unit_price'],
               item['discount_pct'] if 'discount_pct' in item.keys() else 0,
               item['line_total']))

    # Deduct stock when converting proforma → invoice
    if target_type == 'invoice':
        _deduct_stock(items, source['branch_id'], new_id)

    type_labels = {'invoice': 'Invoice', 'delivery_note': 'Delivery Note'}
    flash(f'Converted to {type_labels[target_type]}: {doc_number}', 'success')
    return redirect(url_for('documents.view', doc_id=new_id))
