import calendar
import re
from datetime import date, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from database import get_db, execute_db, query_db
from services.numbering import get_next_number
from services.text_utils import tc, sc
from routes.auth import perm_required

bp = Blueprint('financing', __name__, url_prefix='/financing')


def _add_months(dt, n):
    month = dt.month - 1 + n
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


@bp.route('/')
@login_required
def list():
    branch_filter = request.args.get('branch_id', '')
    status_filter = request.args.get('status', '')

    sql = """
        SELECT fp.*,
               c.name AS customer_name, c.phone AS customer_phone,
               b.name AS branch_name,
               (SELECT COUNT(*) FROM financing_installments fi
                WHERE fi.plan_id = fp.id AND fi.status = 'overdue') AS overdue_count,
               (SELECT COALESCE(SUM(fi.amount_paid),0) FROM financing_installments fi
                WHERE fi.plan_id = fp.id) AS total_paid
        FROM financing_plans fp
        JOIN customers c ON fp.customer_id = c.id
        JOIN branches b ON fp.branch_id = b.id
        WHERE 1=1
    """
    args = []
    if not current_user.is_admin and current_user.branch_id:
        sql += " AND fp.branch_id = ?"
        args.append(current_user.branch_id)
    elif branch_filter:
        sql += " AND fp.branch_id = ?"
        args.append(branch_filter)
    if status_filter:
        sql += " AND fp.status = ?"
        args.append(status_filter)
    sql += " ORDER BY fp.created_at DESC"

    plans = query_db(sql, args)
    branches = query_db("SELECT * FROM branches ORDER BY name") if current_user.is_admin else []
    return render_template('financing/list.html', plans=plans, branches=branches,
                           branch_filter=branch_filter, status_filter=status_filter)


@bp.route('/new', methods=['GET', 'POST'])
@login_required
@perm_required('create_documents')
def new():
    branches = query_db("SELECT * FROM branches ORDER BY name")
    from_doc_id = request.args.get('from_doc') or None
    prefill_doc = None
    if from_doc_id:
        prefill_doc = query_db("""
            SELECT d.*, COALESCE(c.name, d.walkin_name) AS customer_name,
                   c.phone AS customer_phone, c.id AS cust_id
            FROM documents d
            LEFT JOIN customers c ON d.customer_id = c.id
            WHERE d.id = ?
        """, (from_doc_id,), one=True)

    if request.method == 'POST':
        customer_id   = request.form.get('customer_id') or None
        branch_id     = int(request.form.get('branch_id') or
                            (current_user.branch_id or (branches[0]['id'] if branches else 1)))
        from_doc_post = request.form.get('from_doc_id') or None
        product_desc  = tc(request.form.get('product_description', ''))
        is_iphone     = request.form.get('is_iphone') == '1'
        total_price   = float(request.form.get('total_price', 0) or 0)
        deposit       = float(request.form.get('deposit_amount', 0) or 0)
        num_inst      = int(request.form.get('num_installments', 1) or 1)
        start_str     = request.form.get('start_date', '')
        g_name        = tc(request.form.get('guarantor_name', ''))
        g_phone       = request.form.get('guarantor_phone', '').strip()
        g_id          = request.form.get('guarantor_id', '').strip()
        employer      = tc(request.form.get('employer', ''))
        notes         = sc(request.form.get('notes', ''))

        errors = []
        if not customer_id:
            errors.append('Customer is required.')
        if not product_desc:
            errors.append('Product description is required.')
        if total_price <= 0:
            errors.append('Total price must be greater than 0.')
        if deposit < 0 or deposit >= total_price:
            errors.append('Deposit must be 0 or more but less than the total price.')
        if not (1 <= num_inst <= 60):
            errors.append('Number of installments must be between 1 and 60.')
        if not start_str:
            errors.append('First installment date is required.')
        if is_iphone and not g_name:
            errors.append('Guarantor name is required for iPhone financing (high risk).')
        if is_iphone and not g_phone:
            errors.append('Guarantor phone is required for iPhone financing (high risk).')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('financing/new.html', branches=branches,
                                   prefill_doc=prefill_doc, form=request.form)

        financed      = round(total_price - deposit, 2)
        inst_amount   = round(financed / num_inst, 2)
        risk_level    = 'high' if is_iphone else 'normal'
        start_date    = date.fromisoformat(start_str)
        year          = datetime.now().year
        plan_number   = get_next_number(branch_id, 'financing', year)

        plan_id = execute_db("""
            INSERT INTO financing_plans
            (plan_number, document_id, customer_id, branch_id, product_description,
             total_price, deposit_amount, financed_amount, num_installments,
             installment_amount, start_date, status, risk_level,
             guarantor_name, guarantor_phone, guarantor_id_number, employer, notes, created_by)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (plan_number, from_doc_post, customer_id, branch_id, product_desc,
              total_price, deposit, financed, num_inst, inst_amount,
              start_str, 'active', risk_level,
              g_name or None, g_phone or None, g_id or None,
              employer or None, notes or None, current_user.id))

        for i in range(num_inst):
            due = _add_months(start_date, i)
            execute_db("""
                INSERT INTO financing_installments
                (plan_id, installment_number, due_date, amount_due, status)
                VALUES (?,?,?,?,'pending')
            """, (plan_id, i + 1, due.isoformat(), inst_amount))

        flash(f'Financing plan {plan_number} created successfully.', 'success')
        return redirect(url_for('financing.view', plan_id=plan_id))

    return render_template('financing/new.html', branches=branches,
                           prefill_doc=prefill_doc, form={})


@bp.route('/<int:plan_id>')
@login_required
def view(plan_id):
    plan = query_db("""
        SELECT fp.*, c.name AS customer_name, c.phone AS customer_phone,
               b.name AS branch_name, u.full_name AS staff_name,
               d.doc_number AS linked_doc_number
        FROM financing_plans fp
        JOIN customers c ON fp.customer_id = c.id
        JOIN branches b ON fp.branch_id = b.id
        JOIN users u ON fp.created_by = u.id
        LEFT JOIN documents d ON fp.document_id = d.id
        WHERE fp.id = ?
    """, (plan_id,), one=True)
    if not plan:
        flash('Plan not found.', 'danger')
        return redirect(url_for('financing.list'))

    today = date.today().isoformat()
    # Mark overdue installments
    db = get_db()
    db.execute("""
        UPDATE financing_installments
        SET status = 'overdue'
        WHERE plan_id = ? AND status = 'pending' AND due_date < ?
    """, (plan_id, today))
    db.commit()

    installments = query_db("""
        SELECT fi.*, u.full_name AS paid_by_name
        FROM financing_installments fi
        LEFT JOIN users u ON fi.recorded_by = u.id
        WHERE fi.plan_id = ? ORDER BY fi.installment_number
    """, (plan_id,))

    total_paid = sum(i['amount_paid'] for i in installments)
    remaining  = plan['financed_amount'] - total_paid
    pct_paid   = int(total_paid / plan['financed_amount'] * 100) if plan['financed_amount'] else 0

    return render_template('financing/view.html', plan=plan, installments=installments,
                           total_paid=total_paid, remaining=remaining,
                           pct_paid=pct_paid, today=today)


@bp.route('/<int:plan_id>/pay/<int:inst_id>', methods=['POST'])
@login_required
@perm_required('create_documents')
def record_payment(plan_id, inst_id):
    inst = query_db("SELECT * FROM financing_installments WHERE id=? AND plan_id=?",
                    (inst_id, plan_id), one=True)
    if not inst:
        flash('Installment not found.', 'danger')
        return redirect(url_for('financing.view', plan_id=plan_id))

    amount = float(request.form.get('amount_paid', 0) or 0)
    if amount <= 0:
        flash('Amount must be greater than 0.', 'danger')
        return redirect(url_for('financing.view', plan_id=plan_id))

    method    = request.form.get('payment_method', 'cash')
    paid_date = request.form.get('paid_date', date.today().isoformat())
    notes     = request.form.get('notes', '').strip()
    new_total = inst['amount_paid'] + amount
    status    = 'paid' if new_total >= inst['amount_due'] else 'partial'

    execute_db("""
        UPDATE financing_installments
        SET amount_paid=?, status=?, paid_date=?, payment_method=?, recorded_by=?, notes=?
        WHERE id=?
    """, (new_total, status, paid_date, method, current_user.id, notes or None, inst_id))

    # Auto-complete plan if all paid
    unpaid = query_db("""
        SELECT COUNT(*) AS cnt FROM financing_installments
        WHERE plan_id=? AND status != 'paid'
    """, (plan_id,), one=True)['cnt']
    if unpaid == 0:
        execute_db("UPDATE financing_plans SET status='completed' WHERE id=?", (plan_id,))
        flash('All installments paid — plan marked complete!', 'success')
    else:
        flash(f'Payment of TZS {amount:,.0f} recorded.', 'success')

    return redirect(url_for('financing.view', plan_id=plan_id))


@bp.route('/<int:plan_id>/status', methods=['POST'])
@login_required
def change_status(plan_id):
    new_status = request.form.get('status')
    if new_status not in ('active', 'completed', 'defaulted'):
        flash('Invalid status.', 'danger')
        return redirect(url_for('financing.view', plan_id=plan_id))
    execute_db("UPDATE financing_plans SET status=? WHERE id=?", (new_status, plan_id))
    flash(f'Plan status updated to {new_status}.', 'success')
    return redirect(url_for('financing.view', plan_id=plan_id))
