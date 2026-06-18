"""
Madeni — Credit / Debt Tracking module.
Tracks who owes money, payment history, and customer account statements.
"""
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, send_file, abort)
from flask_login import login_required, current_user
from database import get_db, execute_db, query_db
from services.pdf_generator import generate_statement_pdf, generate_receipt_pdf
from datetime import datetime, date

bp = Blueprint('credits', __name__, url_prefix='/madeni')


def _outstanding_balance(doc_id):
    doc = query_db("SELECT total, amount_paid FROM documents WHERE id=?", (doc_id,), one=True)
    if not doc:
        return 0
    return round(float(doc['total']) - float(doc['amount_paid']), 2)


@bp.route('/')
@login_required
def list():
    """All credit sales — filter by branch, status, overdue."""
    branch_id = request.args.get('branch_id', '')
    status_filter = request.args.get('status', '')   # overdue / partial / credit
    q = request.args.get('q', '').strip()

    sql = """
        SELECT d.id, d.doc_number, d.total, d.amount_paid,
               d.total - d.amount_paid AS balance,
               d.credit_due_date, d.payment_status, d.created_at,
               d.branch_id,
               b.name AS branch_name,
               c.name AS customer_name, c.phone AS customer_phone, c.id AS customer_id
        FROM documents d
        JOIN branches b ON d.branch_id = b.id
        LEFT JOIN customers c ON d.customer_id = c.id
        WHERE d.doc_type = 'invoice'
          AND d.payment_status IN ('credit', 'partial')
    """
    args = []

    if not current_user.is_admin and current_user.branch_id:
        sql += " AND d.branch_id=?"
        args.append(current_user.branch_id)
    elif branch_id:
        sql += " AND d.branch_id=?"
        args.append(branch_id)

    if q:
        sql += " AND (c.name LIKE ? OR d.doc_number LIKE ?)"
        args += [f'%{q}%', f'%{q}%']

    if status_filter == 'overdue':
        sql += " AND d.credit_due_date < DATE('now') AND d.payment_status != 'paid'"
    elif status_filter == 'partial':
        sql += " AND d.payment_status='partial'"
    elif status_filter == 'credit':
        sql += " AND d.payment_status='credit'"

    sql += " ORDER BY d.credit_due_date ASC, d.created_at DESC"
    credits = query_db(sql, args)

    # Summary totals
    total_outstanding = sum(float(c['balance']) for c in credits)
    overdue_count = sum(
        1 for c in credits
        if c['credit_due_date'] and c['credit_due_date'] < date.today().isoformat()
    )

    branches = query_db("SELECT * FROM branches ORDER BY name")
    today = date.today().isoformat()
    return render_template('credits/list.html',
                           credits=credits, branches=branches,
                           total_outstanding=total_outstanding,
                           overdue_count=overdue_count,
                           branch_filter=branch_id, status_filter=status_filter,
                           q=q, today=today)


@bp.route('/<int:doc_id>')
@login_required
def detail(doc_id):
    """Credit sale detail — payment history + record payment form."""
    doc = query_db("""
        SELECT d.*, b.name AS branch_name, c.name AS customer_name,
               c.phone AS customer_phone, c.address AS customer_address,
               c.id AS customer_id, u.full_name AS staff_name
        FROM documents d
        JOIN branches b ON d.branch_id = b.id
        LEFT JOIN customers c ON d.customer_id = c.id
        JOIN users u ON d.created_by = u.id
        WHERE d.id=? AND d.doc_type='invoice'
    """, (doc_id,), one=True)
    if not doc:
        abort(404)

    payments = query_db("""
        SELECT p.*, u.full_name AS recorded_by_name
        FROM payments p
        LEFT JOIN users u ON p.recorded_by = u.id
        WHERE p.document_id=?
        ORDER BY p.payment_date DESC, p.created_at DESC
    """, (doc_id,))

    items = query_db(
        "SELECT * FROM document_items WHERE document_id=? ORDER BY id", (doc_id,))

    balance = round(float(doc['total']) - float(doc['amount_paid']), 2)
    today = date.today().isoformat()
    return render_template('credits/detail.html',
                           doc=doc, payments=payments, items=items,
                           balance=balance, today=today)


@bp.route('/<int:doc_id>/pay', methods=['POST'])
@login_required
def record_payment(doc_id):
    """Record a payment against a credit sale."""
    doc = query_db(
        "SELECT id, total, amount_paid, payment_status FROM documents WHERE id=?",
        (doc_id,), one=True)
    if not doc:
        abort(404)

    try:
        amount = float(request.form['amount'])
        if amount <= 0:
            raise ValueError
    except (ValueError, KeyError):
        flash('Please enter a valid payment amount.', 'danger')
        return redirect(url_for('credits.detail', doc_id=doc_id))

    payment_date = request.form.get('payment_date') or date.today().isoformat()
    method = request.form.get('payment_method', 'cash')
    reference = request.form.get('reference', '').strip() or None
    notes = request.form.get('notes', '').strip() or None

    balance = float(doc['total']) - float(doc['amount_paid'])
    if amount > balance + 0.01:
        flash(f'Amount exceeds balance (TZS {balance:,.0f}).', 'danger')
        return redirect(url_for('credits.detail', doc_id=doc_id))

    execute_db("""
        INSERT INTO payments (document_id, amount, payment_date, payment_method,
                              reference, notes, recorded_by)
        VALUES (?,?,?,?,?,?,?)
    """, (doc_id, amount, payment_date, method, reference, notes, current_user.id))

    new_paid = float(doc['amount_paid']) + amount
    new_balance = float(doc['total']) - new_paid
    new_status = 'paid' if new_balance <= 0.01 else 'partial'

    execute_db(
        "UPDATE documents SET amount_paid=?, payment_status=?, updated_at=datetime('now','localtime') WHERE id=?",
        (round(new_paid, 2), new_status, doc_id)
    )

    flash(f'Payment of TZS {amount:,.0f} recorded. '
          + ('Fully paid!' if new_status == 'paid'
             else f'Remaining: TZS {new_balance:,.0f}'), 'success')
    next_url = request.form.get('next') or request.args.get('next')
    return redirect(next_url if next_url else url_for('credits.detail', doc_id=doc_id))


@bp.route('/<int:doc_id>/payments/<int:payment_id>/receipt')
@login_required
def payment_receipt(doc_id, payment_id):
    """Download a PDF payment receipt for a specific payment."""
    doc = query_db("""
        SELECT d.*, b.name AS branch_name, b.address AS branch_address,
               c.name AS customer_name, c.phone AS customer_phone, c.address AS customer_address
        FROM documents d
        JOIN branches b ON d.branch_id = b.id
        LEFT JOIN customers c ON d.customer_id = c.id
        WHERE d.id=?
    """, (doc_id,), one=True)
    if not doc:
        abort(404)

    payment = query_db("SELECT * FROM payments WHERE id=? AND document_id=?",
                       (payment_id, doc_id), one=True)
    if not payment:
        abort(404)

    customer = {'name': doc['customer_name'], 'phone': doc['customer_phone'],
                'address': doc['customer_address']} if doc['customer_name'] else None
    branch   = {'name': doc['branch_name'], 'address': doc['branch_address']}

    buf   = generate_receipt_pdf(dict(payment), dict(doc), customer, branch)
    fname = f"Receipt_{doc['doc_number']}_{payment['payment_date']}.pdf"
    return send_file(buf, mimetype='application/pdf',
                     as_attachment=False, download_name=fname)


@bp.route('/customer/<int:customer_id>')
@login_required
def customer_statement(customer_id):
    """All credit history for a customer."""
    customer = query_db("SELECT * FROM customers WHERE id=?", (customer_id,), one=True)
    if not customer:
        abort(404)

    docs = query_db("""
        SELECT d.id, d.doc_number, d.total, d.amount_paid,
               d.total - d.amount_paid AS balance,
               d.credit_due_date, d.payment_status, d.created_at,
               b.name AS branch_name
        FROM documents d
        JOIN branches b ON d.branch_id = b.id
        WHERE d.customer_id=? AND d.doc_type='invoice'
          AND d.payment_status IN ('credit','partial','paid')
        ORDER BY d.created_at DESC
    """, (customer_id,))

    total_sales = sum(float(d['total']) for d in docs)
    total_paid = sum(float(d['amount_paid']) for d in docs)
    total_balance = total_sales - total_paid
    today = date.today().isoformat()

    return render_template('credits/statement.html',
                           customer=customer, docs=docs,
                           total_sales=total_sales,
                           total_paid=total_paid,
                           total_balance=total_balance,
                           today=today)


@bp.route('/customer/<int:customer_id>/statement.pdf')
@login_required
def statement_pdf(customer_id):
    customer = query_db("SELECT * FROM customers WHERE id=?", (customer_id,), one=True)
    if not customer:
        abort(404)

    docs = query_db("""
        SELECT d.id, d.doc_number, d.total, d.amount_paid,
               d.total - d.amount_paid AS balance,
               d.credit_due_date, d.payment_status, d.created_at,
               b.name AS branch_name
        FROM documents d
        JOIN branches b ON d.branch_id = b.id
        WHERE d.customer_id=? AND d.doc_type='invoice'
          AND d.payment_status IN ('credit','partial','paid')
        ORDER BY d.created_at DESC
    """, (customer_id,))

    buf = generate_statement_pdf(dict(customer), [dict(d) for d in docs])
    fname = f"Statement_{customer['name'].replace(' ', '_')[:30]}_{date.today().isoformat()}.pdf"
    return send_file(buf, mimetype='application/pdf',
                     as_attachment=False, download_name=fname)
