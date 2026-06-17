from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from database import execute_db, query_db
from services.numbering import get_next_number
from services.text_utils import tc, sc
from routes.auth import perm_required

bp = Blueprint('tradeins', __name__, url_prefix='/tradeins')

CONDITIONS = [
    ('excellent', 'Excellent — like new'),
    ('good',      'Good — minor wear'),
    ('fair',      'Fair — visible wear'),
    ('poor',      'Poor — heavy wear / cracked'),
    ('broken',    'Broken / not working'),
]

DISPOSITIONS = [
    ('in_stock',    'In stock (for resale)'),
    ('sold',        'Sold'),
    ('refurbished', 'Sent for repair / refurbish'),
    ('returned',    'Returned to customer'),
    ('disposed',    'Disposed'),
]


@bp.route('/')
@login_required
def list():
    branch_filter = request.args.get('branch_id', '')
    status_filter = request.args.get('status', '')
    q = request.args.get('q', '').strip()

    sql = """
        SELECT ti.*, c.name AS customer_name, b.name AS branch_name,
               d.doc_number AS linked_doc_number
        FROM tradeins ti
        JOIN customers c ON ti.customer_id = c.id
        JOIN branches b ON ti.branch_id = b.id
        LEFT JOIN documents d ON ti.linked_document_id = d.id
        WHERE 1=1
    """
    args = []
    if not current_user.is_admin and current_user.branch_id:
        sql += " AND ti.branch_id = ?"
        args.append(current_user.branch_id)
    elif branch_filter:
        sql += " AND ti.branch_id = ?"
        args.append(branch_filter)
    if status_filter:
        sql += " AND ti.status = ?"
        args.append(status_filter)
    if q:
        sql += " AND (c.name LIKE ? OR ti.device_make LIKE ? OR ti.device_model LIKE ? OR ti.device_imei LIKE ?)"
        args += [f'%{q}%'] * 4
    sql += " ORDER BY ti.created_at DESC"

    items = query_db(sql, args)
    branches = query_db("SELECT * FROM branches ORDER BY name") if current_user.is_admin else []
    return render_template('tradeins/list.html', items=items, branches=branches,
                           branch_filter=branch_filter, status_filter=status_filter, q=q,
                           conditions=dict(CONDITIONS))


@bp.route('/new', methods=['GET', 'POST'])
@login_required
@perm_required('create_documents')
def new():
    branches = query_db("SELECT * FROM branches ORDER BY name")
    from_doc_id = request.args.get('from_doc') or None
    prefill_doc = None
    if from_doc_id:
        prefill_doc = query_db("""
            SELECT d.*, COALESCE(c.name, d.walkin_name) AS customer_name, c.id AS cust_id
            FROM documents d LEFT JOIN customers c ON d.customer_id = c.id
            WHERE d.id = ?
        """, (from_doc_id,), one=True)

    if request.method == 'POST':
        customer_id   = request.form.get('customer_id') or None
        branch_id     = int(request.form.get('branch_id') or
                            (current_user.branch_id or (branches[0]['id'] if branches else 1)))
        linked_doc_id = request.form.get('linked_doc_id') or None
        device_make   = tc(request.form.get('device_make', ''))
        device_model  = tc(request.form.get('device_model', ''))
        device_imei   = request.form.get('device_imei', '').strip() or None
        device_color  = tc(request.form.get('device_color', '')) or None
        device_storage = request.form.get('device_storage', '').strip() or None
        condition     = request.form.get('condition', 'good')
        cond_notes    = sc(request.form.get('condition_notes', '')) or None
        assessed_val  = float(request.form.get('assessed_value', 0) or 0)
        credit_off    = float(request.form.get('credit_offered', 0) or 0)
        notes         = sc(request.form.get('notes', '')) or None

        errors = []
        if not customer_id:
            errors.append('Customer is required.')
        if not device_make:
            errors.append('Device make is required (e.g. Apple, Samsung).')
        if not device_model:
            errors.append('Device model is required (e.g. iPhone 14 Pro).')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('tradeins/new.html', branches=branches,
                                   prefill_doc=prefill_doc, form=request.form,
                                   conditions=CONDITIONS)

        year = datetime.now().year
        ti_number = get_next_number(branch_id, 'tradein', year)

        ti_id = execute_db("""
            INSERT INTO tradeins
            (tradein_number, customer_id, branch_id, linked_document_id,
             device_make, device_model, device_imei, device_color, device_storage,
             condition, condition_notes, assessed_value, credit_offered,
             status, disposition, assessed_by)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'pending','in_stock',?)
        """, (ti_number, customer_id, branch_id, linked_doc_id,
              device_make, device_model, device_imei, device_color, device_storage,
              condition, cond_notes, assessed_val, credit_off, current_user.id))

        flash(f'Trade-in {ti_number} recorded.', 'success')
        return redirect(url_for('tradeins.view', ti_id=ti_id))

    return render_template('tradeins/new.html', branches=branches,
                           prefill_doc=prefill_doc, form={}, conditions=CONDITIONS)


@bp.route('/<int:ti_id>')
@login_required
def view(ti_id):
    item = query_db("""
        SELECT ti.*, c.name AS customer_name, c.phone AS customer_phone,
               b.name AS branch_name, u.full_name AS assessed_by_name,
               d.doc_number AS linked_doc_number
        FROM tradeins ti
        JOIN customers c ON ti.customer_id = c.id
        JOIN branches b ON ti.branch_id = b.id
        LEFT JOIN users u ON ti.assessed_by = u.id
        LEFT JOIN documents d ON ti.linked_document_id = d.id
        WHERE ti.id = ?
    """, (ti_id,), one=True)
    if not item:
        flash('Trade-in not found.', 'danger')
        return redirect(url_for('tradeins.list'))
    return render_template('tradeins/view.html', item=item,
                           conditions=dict(CONDITIONS), dispositions=DISPOSITIONS)


@bp.route('/<int:ti_id>/update', methods=['POST'])
@login_required
@perm_required('create_documents')
def update(ti_id):
    action = request.form.get('action', 'status')

    if action == 'status':
        new_status = request.form.get('status')
        if new_status in ('pending', 'accepted', 'rejected', 'completed'):
            execute_db("UPDATE tradeins SET status=? WHERE id=?", (new_status, ti_id))
            flash(f'Status updated to {new_status}.', 'success')

    elif action == 'disposition':
        disposition = request.form.get('disposition', 'in_stock')
        disp_notes  = sc(request.form.get('disposition_notes', '')) or None
        disp_date   = request.form.get('disposition_date') or date.today().isoformat()
        execute_db("""
            UPDATE tradeins SET disposition=?, disposition_notes=?, disposition_date=?,
            status='completed' WHERE id=?
        """, (disposition, disp_notes, disp_date, ti_id))
        flash('Disposition updated.', 'success')

    elif action == 'value':
        assessed_val = float(request.form.get('assessed_value', 0) or 0)
        credit_off   = float(request.form.get('credit_offered', 0) or 0)
        execute_db("""
            UPDATE tradeins SET assessed_value=?, credit_offered=? WHERE id=?
        """, (assessed_val, credit_off, ti_id))
        flash('Valuation updated.', 'success')

    return redirect(url_for('tradeins.view', ti_id=ti_id))
