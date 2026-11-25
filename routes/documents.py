import html
import re
import secrets
import zipfile
from urllib.parse import quote as urlquote
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, send_file, abort, current_app, session)
from flask_login import login_required, current_user
from database import execute_db, query_db, transaction, audit
from services import stock
from services.access import can_see_branch, own_branch, sees_all_branches
from services.customer_rules import name_error
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


def _pdf_for(doc):
    """Branded PDF for a document row from _fetch_doc_full (one place, used everywhere)."""
    customer = (query_db("SELECT * FROM customers WHERE id=?", (doc['customer_id'],), one=True)
                if doc['customer_id']
                else ({'name': doc['walkin_name']} if doc['walkin_name'] else None))
    items = query_db("SELECT * FROM document_items WHERE document_id=? ORDER BY id", (doc['id'],))
    branch = {'name': doc['branch_name'], 'address': doc['branch_address'],
              'short_code': doc['short_code']}
    return generate_pdf(dict(doc), dict(customer) if customer else None,
                        [dict(i) for i in items], branch, doc['staff_name'])


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


def _can_see(doc):
    return can_see_branch(doc['branch_id'])


def _doc_or_404(doc_id):
    doc = _fetch_doc_full(doc_id)
    if not doc or not _can_see(doc):
        abort(404)
    return doc


def _batch_docs(doc):
    """All documents of the same sale (invoice + proforma + delivery note)."""
    if doc['batch_id']:
        return query_db("SELECT * FROM documents WHERE batch_id=? ORDER BY id", (doc['batch_id'],))
    return [query_db("SELECT * FROM documents WHERE id=?", (doc['id'],), one=True)]


def _customer_problem(customer_id):
    """None if the sale can be recorded against this customer, else a message."""
    if not customer_id:
        return ('Choose the customer from the list, or press "Save" to add them with '
                'their real name and phone number.')
    c = query_db("SELECT id, name, tin FROM customers WHERE id=?", (customer_id,), one=True)
    if not c:
        return 'That customer no longer exists — search again or add them.'
    err = name_error(c['name'], c['tin'])
    if err:
        return (f'The saved customer "{c["name"]}" does not have a proper name. '
                f'Open Customers → {c["name"]} → Edit and enter their real full name first.')
    return None


def _reverse_stock(batch, branch_id, release_units=True):
    """Put back whatever these documents took out of stock. Returns {pid: qty}."""
    ids  = [d['id'] for d in batch]
    held = stock.doc_sold_qty(ids)
    if held:
        stock.reverse_sales(ids, branch_id, release_units=release_units)
        return held
    # Older invoices may have deducted stock without logging a movement.
    inv = next((d for d in batch if d['doc_type'] == 'invoice'), None)
    if inv:
        rows = query_db("SELECT product_id, quantity FROM document_items "
                        "WHERE document_id=? AND product_id IS NOT NULL", (inv['id'],))
        held = stock.qty_by_product([dict(r) for r in rows])
        for pid, qty in held.items():
            stock.put_back(pid, branch_id, qty)
    if release_units:
        stock.release_units_of(ids)
    return held


def _linked_records(ids):
    """Other records that point at these documents — they block a delete."""
    if not ids:
        return []
    ph = ','.join('?' * len(ids))
    found = []
    for table, col, label in [('returns', 'document_id', 'return'),
                              ('financing_plans', 'document_id', 'financing plan'),
                              ('tradeins', 'linked_document_id', 'trade-in'),
                              ('repair_jobs', 'linked_document_id', 'repair job')]:
        n = query_db(f"SELECT COUNT(*) AS n FROM {table} WHERE {col} IN ({ph})", ids, one=True)['n']
        if n:
            found.append(f'{n} {label}{"s" if n > 1 else ""}')
    return found


def _render_new(branches, default_branch_id, nonce, form=None):
    """New-document page. On a validation error the staff member's input is kept."""
    prefill_items, prefill_customer = [], None
    if form is not None:
        cols = [form.getlist(k) for k in ('item_description[]', 'item_qty[]', 'item_price[]',
                                          'item_specs[]', 'item_discount[]', 'item_product_id[]')]
        for i, desc in enumerate(cols[0]):
            if not desc.strip():
                continue
            g = lambda c: (cols[c][i] if i < len(cols[c]) else '')
            prefill_items.append({'description': desc, 'qty': g(1) or 1, 'price': g(2),
                                  'specs': g(3), 'discount': g(4) or 0, 'product_id': g(5)})
        cid = form.get('customer_id')
        if cid:
            c = query_db("SELECT id, name, phone FROM customers WHERE id=?", (cid,), one=True)
            if c:
                prefill_customer = dict(c)
        if not prefill_customer and form.get('walkin_name'):
            prefill_customer = {'id': '', 'name': form.get('walkin_name'), 'phone': ''}
        session['doc_form_nonce'] = nonce   # let them fix the problem and resubmit
    return render_template('documents/new.html', branches=branches,
                           vat_rate=VAT_RATE, default_branch_id=default_branch_id,
                           today=date.today().isoformat(), form_nonce=nonce,
                           prefill_items=prefill_items, prefill_customer=prefill_customer,
                           form=form or {})


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

    if not sees_all_branches():
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

        branch_id       = own_branch(request.form.get('branch_id'))
        customer_id     = request.form.get('customer_id', type=int)
        is_vat          = 1 if request.form.get('is_vat') else 0
        notes           = sc(request.form.get('notes', '')) or None
        efd_reference   = request.form.get('efd_reference', '').strip() or None
        validity_days   = request.form.get('validity_days', 7, type=int) or 7
        vat_rate        = request.form.get('vat_rate', VAT_RATE, type=float) or VAT_RATE
        payment_type    = request.form.get('payment_type', 'cash')
        credit_due_date = request.form.get('credit_due_date', '').strip() or None

        # payment_type is either 'credit' or the actual method (cash/card/mpesa/…)
        if payment_type == 'credit':
            payment_status, payment_method = 'credit', 'credit'
        else:
            payment_status, payment_method = 'paid', payment_type

        items  = _parse_items(request.form)
        errors = []
        if not branch_id:
            errors.append('Choose the branch the goods are sold from.')
        problem = _customer_problem(customer_id)
        if problem:
            errors.append(problem)
        if not items:
            errors.append('Please add at least one item.')
        if branch_id and items:
            # Every item must come out of this branch's stock — no selling what isn't there.
            errors += stock.check_sale(items, branch_id)
            if not errors:
                errors += _validate_units(items, branch_id)
        if errors:
            for msg in errors:
                flash(msg, 'danger')
            return _render_new(branches, default_branch_id, submitted_nonce, request.form)

        subtotal   = round(sum(i['line_total'] for i in items), 2)
        vat_amount = round(subtotal * vat_rate / 100, 2) if is_vat else 0
        total      = round(subtotal + vat_amount, 2)
        amount_paid = 0.0 if payment_type == 'credit' else total
        year       = datetime.now().year

        # ── Server-side idempotency: block genuine duplicates ──────────
        # Same staff, same customer, same total, same branch within 2 minutes = a double click.
        dup_check = query_db("""
            SELECT d.id, d.batch_id FROM documents d
            WHERE d.created_by = ? AND d.branch_id = ? AND d.doc_type = 'invoice'
              AND d.total = ? AND d.customer_id = ?
              AND d.created_at >= datetime('now','localtime','-2 minutes')
            ORDER BY d.id DESC LIMIT 1
        """, (current_user.id, branch_id, total, customer_id), one=True)
        if dup_check:
            if dup_check['batch_id']:
                batch_docs = query_db("SELECT id FROM documents WHERE batch_id=? ORDER BY id",
                                      (dup_check['batch_id'],))
                ids_str = ','.join(str(r['id']) for r in batch_docs)
            else:
                ids_str = str(dup_check['id'])
            flash('This sale was already recorded. Showing the existing documents.', 'info')
            return redirect(url_for('documents.result', ids=ids_str))
        # ────────────────────────────────────────────────────────────────

        created_ids = []
        invoice_id  = None
        batch_id    = None   # set from invoice number on first iteration

        # One sale = one all-or-nothing transaction: the three documents, their
        # items, the stock coming off the shelf and the IMEIs marked sold.
        with transaction():
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
                    VALUES (?,?,?,?,NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (doc_number, doc_type, branch_id, customer_id, current_user.id,
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

            # Stock comes off ONCE per sale, carried by the invoice.
            stock.sell(items, branch_id, invoice_id)
            _register_units(items, invoice_id, customer_id)

        ids_str = ','.join(str(i) for i in created_ids)
        return redirect(url_for('documents.result', ids=ids_str))

    form_nonce = secrets.token_hex(16)
    session['doc_form_nonce'] = form_nonce
    return _render_new(branches, default_branch_id, form_nonce)


@bp.route('/result')
@login_required
def result():
    ids_str = request.args.get('ids', '')
    ids  = [int(i) for i in ids_str.split(',') if i.strip().isdigit()]
    docs = [_fetch_doc_full(i) for i in ids]
    docs = [d for d in docs if d and _can_see(d)]
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
            if not doc or not _can_see(doc):
                continue
            pdf_buf = _pdf_for(doc)
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
        if not doc or not _can_see(doc):
            continue
        pdf_buf = _pdf_for(doc)
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
    if not docs or not _can_see(docs[0]):
        flash('Sale batch not found.', 'danger')
        return redirect(url_for('documents.list'))
    ids_str = ','.join(str(d['id']) for d in docs)
    return render_template('documents/batch.html', docs=docs, batch_id=batch_id,
                           ids_str=ids_str, doc_type_labels=DOC_TYPE_LABELS)


@bp.route('/<int:doc_id>')
@login_required
def view(doc_id):
    doc = _fetch_doc_full(doc_id)
    if not doc or not _can_see(doc):
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
    doc = _doc_or_404(doc_id)
    pdf_buf = _pdf_for(doc)
    return send_file(pdf_buf, mimetype='application/pdf',
                     as_attachment=False,
                     download_name=f"{doc['doc_number']}.pdf")


def _delete_docs(docs):
    """Delete documents, putting their stock back. Refuses if anything links to them."""
    ids = [d['id'] for d in docs]
    nums = ', '.join(d['doc_number'] for d in docs)
    blockers = _linked_records(ids)
    if blockers:
        flash(f'Cannot delete {nums}: {", ".join(blockers)} point to this sale. '
              f'Remove or re-link those first.', 'danger')
        return False
    lead = next((d for d in docs if d['doc_type'] == 'invoice'), docs[0])
    with transaction():
        _reverse_stock(docs, lead['branch_id'])
        ph = ','.join('?' * len(ids))
        execute_db(f"DELETE FROM document_items WHERE document_id IN ({ph})", ids)
        execute_db(f"DELETE FROM documents WHERE id IN ({ph})", ids)
        audit('delete', 'document', lead['id'], nums,
              f"total TZS {float(lead['total'] or 0):,.0f}; customer_id {lead['customer_id']}",
              lead['branch_id'])
    flash(f'Deleted: {nums}. Stock put back.', 'success')
    return True


@bp.route('/<int:doc_id>/delete', methods=['POST'])
@login_required
@perm_required('void_documents')
def delete(doc_id):
    doc = _doc_or_404(doc_id)
    batch = _batch_docs(doc)
    # The invoice IS the sale: deleting it takes its proforma and delivery note with it,
    # otherwise they'd be left describing a sale that no longer exists.
    targets = batch if doc['doc_type'] == 'invoice' else [d for d in batch if d['id'] == doc_id]
    if _delete_docs(targets):
        return redirect(url_for('documents.list'))
    return redirect(url_for('documents.view', doc_id=doc_id))


@bp.route('/<int:doc_id>/delete-batch', methods=['POST'])
@login_required
@perm_required('void_documents')
def delete_batch(doc_id):
    """Delete an entire batch (invoice + proforma + delivery note) at once."""
    doc = _doc_or_404(doc_id)
    if _delete_docs(_batch_docs(doc)):
        return redirect(url_for('documents.list'))
    return redirect(url_for('documents.view', doc_id=doc_id))


@bp.route('/<int:doc_id>/edit', methods=['GET', 'POST'])
@login_required
@perm_required('create_documents')
def edit(doc_id):
    """Fix a mistake on a sale. The change is applied to all documents of the sale
    (invoice, proforma, delivery note) and stock is re-calculated against the new items."""
    doc = _doc_or_404(doc_id)

    if not current_user.is_admin and doc['created_by'] != current_user.id:
        flash('You can only edit your own documents.', 'danger')
        return redirect(url_for('documents.view', doc_id=doc_id))

    old_items = query_db("SELECT * FROM document_items WHERE document_id=? ORDER BY id", (doc_id,))
    branches  = query_db("SELECT * FROM branches ORDER BY id")

    def _form_again():
        return render_template('documents/edit.html', doc=doc, items=old_items,
                               branches=branches, vat_rate=VAT_RATE,
                               today=date.today().isoformat())

    if request.method == 'POST':
        parsed_items = _parse_items(request.form)
        customer_id  = request.form.get('customer_id', type=int)
        batch        = _batch_docs(doc)
        branch_id    = doc['branch_id']
        invoice      = next((d for d in batch if d['doc_type'] == 'invoice'), None)

        errors = []
        if query_db(f"SELECT 1 FROM returns WHERE document_id IN ({','.join('?' * len(batch))}) LIMIT 1",
                    [d['id'] for d in batch], one=True):
            errors.append('This sale already has a return logged against it, so it can no longer be '
                          'edited (stock and refunds would no longer add up).')
        if not parsed_items:
            errors.append('At least one item is required.')
        problem = _customer_problem(customer_id)
        if problem:
            errors.append(problem)

        held = stock.doc_sold_qty([d['id'] for d in batch])
        if not held and invoice:
            # Older invoice that took stock without logging a movement.
            held = stock.qty_by_product([dict(r) for r in query_db(
                "SELECT product_id, quantity FROM document_items WHERE document_id=? "
                "AND product_id IS NOT NULL", (invoice['id'],))])
        takes_stock = bool(invoice) or bool(held)
        if parsed_items and takes_stock:
            errors += stock.check_sale(parsed_items, branch_id, giving_back=held)
            # IMEI phones: the exact units sold can't be swapped by editing.
            old_tracked = {pid: q for pid, q in stock.qty_by_product([dict(r) for r in old_items]).items()
                           if stock.is_tracked(pid)}
            new_tracked = {pid: q for pid, q in stock.qty_by_product(parsed_items).items()
                           if stock.is_tracked(pid)}
            if old_tracked != new_tracked:
                errors.append('Items with IMEI numbers (phones, laptops…) cannot be added, removed or '
                              'changed in quantity by editing. Log a Return for the device, or delete '
                              'this sale and record it again picking the right IMEIs.')
        if errors:
            for e in errors:
                flash(e, 'danger')
            return _form_again()

        is_vat         = bool(request.form.get('is_vat'))
        vat_rate_val   = request.form.get('vat_rate', VAT_RATE, type=float) or VAT_RATE
        payment_type   = request.form.get('payment_type', 'cash')
        credit_due_date = request.form.get('credit_due_date') or None
        notes          = request.form.get('notes', '').strip() or None
        efd_reference  = request.form.get('efd_reference', '').strip() or None

        subtotal    = round(sum(i['line_total'] for i in parsed_items), 2)
        vat_amount  = round(subtotal * vat_rate_val / 100, 2) if is_vat else 0.0
        total       = round(subtotal + vat_amount, 2)

        # Money: payments recorded in Credits are real money and are never undone here.
        money_doc = invoice or doc
        recorded  = float(query_db("SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE document_id=?",
                                   (money_doc['id'],), one=True)['s'])
        was_credit = money_doc['payment_status'] in ('credit', 'partial')
        if payment_type == 'credit':
            amount_paid, method = recorded, 'credit'
        elif was_credit:
            if recorded > 0:
                flash('This invoice already has payments recorded — collect the balance under '
                      'Credits instead of switching it to "Pay Now".', 'danger')
                return _form_again()
            amount_paid, method = total, payment_type      # it was in fact paid at the till
        else:
            # Was paid at the till: the customer paid what was charged then. If the
            # total went up, the difference shows up in Credits to be collected.
            amount_paid, method = float(money_doc['amount_paid'] or 0), payment_type
        if amount_paid >= total - 0.01:
            pay_status = 'paid'
        elif amount_paid > 0:
            pay_status = 'partial'
        else:
            pay_status = 'credit'

        with transaction():
            if takes_stock:
                _reverse_stock(batch, branch_id, release_units=False)
            for d in batch:
                execute_db("DELETE FROM document_items WHERE document_id=?", (d['id'],))
                for item in parsed_items:
                    execute_db("""
                        INSERT INTO document_items
                          (document_id, product_id, description, quantity, unit_price, line_total, discount_pct)
                        VALUES (?,?,?,?,?,?,?)
                    """, (d['id'], item['product_id'], item['description'], item['quantity'],
                          item['unit_price'], item['line_total'], item['discount_pct']))
                execute_db("""
                    UPDATE documents SET
                      customer_id=?, walkin_name=NULL, payment_method=?, payment_status=?,
                      amount_paid=?, credit_due_date=?, notes=?, is_vat=?, vat_rate=?,
                      efd_reference=?, subtotal=?, vat_amount=?, total=?,
                      updated_at=datetime('now','localtime')
                    WHERE id=?
                """, (customer_id, method, pay_status, amount_paid,
                      credit_due_date if pay_status != 'paid' else None, notes,
                      1 if is_vat else 0, vat_rate_val, efd_reference,
                      subtotal, vat_amount, total, d['id']))
            if takes_stock:
                stock_doc = invoice or doc
                stock.sell(parsed_items, branch_id, stock_doc['id'])
                ph = ','.join('?' * len(batch))
                execute_db(f"UPDATE device_sales SET customer_id=? WHERE document_id IN ({ph})",
                           [customer_id] + [d['id'] for d in batch])
            audit('edit', 'document', doc_id, doc['doc_number'],
                  f"total {float(doc['total'] or 0):,.0f} → {total:,.0f}; "
                  f"{len(old_items)} → {len(parsed_items)} lines", branch_id)

        others = [d['doc_number'] for d in batch if d['id'] != doc_id]
        flash(f'{doc["doc_number"]} updated'
              + (f' (also {", ".join(others)})' if others else '') + '.', 'success')
        return redirect(url_for('documents.view', doc_id=doc_id))

    return _form_again()


@bp.route('/public/<token>')
def public_pdf(token):
    """Serve a PDF publicly using a share token — no login required."""
    doc = query_db("SELECT * FROM documents WHERE share_token=?", (token,), one=True)
    if not doc:
        abort(404)
    full_doc = _fetch_doc_full(doc['id'])
    pdf_buf = _pdf_for(full_doc)
    return send_file(pdf_buf, mimetype='application/pdf',
                     as_attachment=False,
                     download_name=f"{full_doc['doc_number']}.pdf")


@bp.route('/<int:doc_id>/whatsapp')
@login_required
def whatsapp_share(doc_id):
    """Generate a public share token and open WhatsApp with the PDF link."""
    doc = _doc_or_404(doc_id)

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
        if not doc or not _can_see(doc):
            flash('Document not found.', 'danger')
            return redirect(url_for('documents.list'))
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

        pdf_buf   = _pdf_for(doc)
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
    """Proforma → invoice, or invoice → delivery note — once per sale."""
    source = _doc_or_404(doc_id)
    src_type = source['doc_type']
    if src_type == 'proforma':
        target_type = 'invoice'
    elif src_type == 'invoice':
        target_type = 'delivery_note'
    else:
        flash('Only proformas and invoices can be converted.', 'danger')
        return redirect(url_for('documents.view', doc_id=doc_id))

    batch = _batch_docs(source)
    existing = next((d for d in batch if d['doc_type'] == target_type), None)
    if existing:
        flash(f'This sale already has {DOC_TYPE_LABELS[target_type]} {existing["doc_number"]} '
              f'— no second one created.', 'info')
        return redirect(url_for('documents.view', doc_id=existing['id']))

    items = [dict(r) for r in query_db(
        "SELECT * FROM document_items WHERE document_id=? ORDER BY id", (doc_id,))]
    branch_id = source['branch_id']

    if target_type == 'invoice':
        errors = []
        problem = _customer_problem(source['customer_id'])
        if problem:
            errors.append(problem + ' (Edit the proforma to pick the customer.)')
        errors += stock.check_sale(items, branch_id)
        if any(it['product_id'] and stock.is_tracked(it['product_id']) for it in items):
            errors.append('This quote has items with IMEI numbers. Create the sale from '
                          '"New Document" so you can pick the exact devices.')
        if errors:
            for e in errors:
                flash(e, 'danger')
            return redirect(url_for('documents.view', doc_id=doc_id))

        pay_method    = request.form.get('payment_method', 'cash')
        pay_status    = 'credit' if pay_method == 'credit' else 'paid'
        credit_due    = request.form.get('credit_due_date', '').strip() or None
        amount_paid   = 0.0 if pay_status == 'credit' else float(source['total'])
        actual_method = 'credit' if pay_status == 'credit' else pay_method
    else:
        pay_status    = source['payment_status']
        credit_due    = source['credit_due_date']
        amount_paid   = source['amount_paid']
        actual_method = source['payment_method']
    notes = request.form.get('notes', source['notes'] or '').strip() or None

    with transaction():
        batch_id = source['batch_id']
        if not batch_id:
            batch_id = source['doc_number']
            execute_db("UPDATE documents SET batch_id=? WHERE id=?", (batch_id, doc_id))
        doc_number = get_next_number(branch_id, target_type, date.today().year)
        new_id = execute_db("""
            INSERT INTO documents
              (doc_number, doc_type, branch_id, customer_id, created_by,
               is_vat, vat_rate, efd_reference, subtotal, vat_amount, total,
               notes, validity_days, status, payment_status, payment_method,
               amount_paid, credit_due_date, walkin_name, batch_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            doc_number, target_type, branch_id, source['customer_id'], current_user.id,
            source['is_vat'], source['vat_rate'], None,
            source['subtotal'], source['vat_amount'], source['total'],
            notes, source['validity_days'], 'final',
            pay_status, actual_method, amount_paid, credit_due,
            source['walkin_name'], batch_id,
        ))
        for item in items:
            execute_db("""
                INSERT INTO document_items
                  (document_id, product_id, description, quantity, unit_price, discount_pct, line_total)
                VALUES (?,?,?,?,?,?,?)
            """, (new_id, item['product_id'], item['description'], item['quantity'],
                  item['unit_price'], item.get('discount_pct') or 0, item['line_total']))
        if target_type == 'invoice':
            stock.sell(items, branch_id, new_id)
        audit('convert', 'document', new_id, doc_number,
              f"from {source['doc_number']}", branch_id)

    flash(f'Converted to {DOC_TYPE_LABELS[target_type]}: {doc_number}', 'success')
    return redirect(url_for('documents.view', doc_id=new_id))
