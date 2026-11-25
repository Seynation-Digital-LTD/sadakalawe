from datetime import date as _date
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from database import query_db, execute_db, get_db

bp = Blueprint('cash_recon', __name__, url_prefix='/cash')

METHODS = ['cash', 'mpesa', 'airtel', 'card', 'other']
METHOD_LABELS = {
    'cash':   'Cash',
    'mpesa':  'M-Pesa',
    'airtel': 'Airtel Money',
    'card':   'Card / POS',
    'other':  'Other',
}
# Map DB payment_method values to our 5 buckets
BUCKET_MAP = {
    'cash':          'cash',
    'card':          'card',
    'mpesa':         'mpesa',
    'airtel_money':  'airtel',
    'mixx_by_yas':   'other',
    'halopesa':      'other',
    'bank_transfer': 'other',
    'other':         'other',
}


def _bucket(method):
    return BUCKET_MAP.get(method or 'cash', 'other')


def _day_sales(branch_id, date_str):
    """Money the system says came in (and went out) for a branch on a day, per method.

      + money taken at the till for that day's invoices (not the later credit payments)
      + credit / partial payments recorded that day (Credits → Record Payment)
      + financing installments paid that day
      − cash refunds given that day
    """
    buckets = {m: 0.0 for m in METHODS}

    # Paid at the moment of sale: amount_paid minus whatever came later through Credits.
    for r in query_db("""
        SELECT d.payment_method,
               d.amount_paid - COALESCE((SELECT SUM(p.amount) FROM payments p
                                         WHERE p.document_id = d.id), 0) AS at_till
        FROM documents d
        WHERE d.doc_type='invoice' AND d.status='final'
          AND DATE(d.created_at) = ? AND d.branch_id = ?
          AND d.payment_method != 'credit'
    """, (date_str, branch_id)):
        buckets[_bucket(r['payment_method'])] += max(0.0, float(r['at_till'] or 0))

    for r in query_db("""
        SELECT p.payment_method, SUM(p.amount) AS amt
        FROM payments p JOIN documents d ON d.id = p.document_id
        WHERE DATE(p.payment_date) = ? AND d.branch_id = ?
        GROUP BY p.payment_method
    """, (date_str, branch_id)):
        buckets[_bucket(r['payment_method'])] += float(r['amt'] or 0)

    for r in query_db("""
        SELECT fi.payment_method, SUM(fi.amount_paid) AS amt
        FROM financing_installments fi JOIN financing_plans fp ON fp.id = fi.plan_id
        WHERE DATE(fi.paid_date) = ? AND fp.branch_id = ? AND fi.amount_paid > 0
        GROUP BY fi.payment_method
    """, (date_str, branch_id)):
        buckets[_bucket(r['payment_method'])] += float(r['amt'] or 0)

    refunds = query_db("""
        SELECT COALESCE(SUM(refund_amount),0) AS amt FROM returns
        WHERE return_type='refund' AND status='approved'
          AND DATE(created_at) = ? AND branch_id = ?
    """, (date_str, branch_id), one=True)['amt']
    buckets['cash'] -= float(refunds or 0)

    return {m: round(v, 2) for m, v in buckets.items()}


@bp.route('/')
@login_required
def index():
    branch_filter = request.args.get('branch_id', '')

    conds  = []
    params = []
    if branch_filter and current_user.is_admin:
        conds.append("cr.branch_id = ?")
        params.append(branch_filter)
    elif not current_user.is_admin and current_user.branch_id:
        conds.append("cr.branch_id = ?")
        params.append(current_user.branch_id)

    where = ("WHERE " + " AND ".join(conds)) if conds else ""

    recons = query_db(f"""
        SELECT cr.*, b.name AS branch_name, u.full_name AS recorded_by_name
        FROM cash_reconciliations cr
        LEFT JOIN branches b ON b.id = cr.branch_id
        LEFT JOIN users u ON u.id = cr.recorded_by
        {where}
        ORDER BY cr.date DESC, cr.created_at DESC
        LIMIT 90
    """, params)

    branches = query_db("SELECT id, name FROM branches ORDER BY name")
    return render_template('cash_recon/index.html',
                           recons=recons,
                           branches=branches,
                           branch_filter=branch_filter,
                           methods=METHODS,
                           method_labels=METHOD_LABELS)


@bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    branches = query_db("SELECT id, name FROM branches ORDER BY name")
    default_branch = current_user.branch_id or (branches[0]['id'] if branches else None)
    today = _date.today().isoformat()

    if request.method == 'POST':
        f          = request.form
        branch_id  = int(f.get('branch_id') or default_branch)
        recon_date = f.get('date', today)
        shift      = f.get('shift', 'full_day')
        notes      = f.get('notes', '').strip() or None

        # System sales for that day
        sales = _day_sales(branch_id, recon_date)

        totals = {}
        grand_counted = 0
        grand_sales   = 0
        for m in METHODS:
            counted  = float(f.get(f'{m}_counted', 0) or 0)
            s        = sales.get(m, 0)
            totals[m] = {'counted': counted, 'sales': s, 'diff': counted - s}
            grand_counted += counted
            grand_sales   += s

        total_diff = grand_counted - grand_sales
        status = 'balanced' if abs(total_diff) < 1 else ('flagged' if abs(total_diff) > 5000 else 'open')

        execute_db("""
            INSERT INTO cash_reconciliations
              (date, branch_id, shift,
               cash_counted,   cash_sales,
               mpesa_counted,  mpesa_sales,
               airtel_counted, airtel_sales,
               card_counted,   card_sales,
               other_counted,  other_sales,
               total_diff, status, notes, recorded_by)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            recon_date, branch_id, shift,
            totals['cash']['counted'],   totals['cash']['sales'],
            totals['mpesa']['counted'],  totals['mpesa']['sales'],
            totals['airtel']['counted'], totals['airtel']['sales'],
            totals['card']['counted'],   totals['card']['sales'],
            totals['other']['counted'],  totals['other']['sales'],
            total_diff, status, notes, current_user.id,
        ))

        label = 'Balanced ✓' if status == 'balanced' else f'Saved (diff TZS {total_diff:+,.0f})'
        flash(f'Reconciliation saved: {label}', 'success')
        return redirect(url_for('cash_recon.index'))

    # Pre-load today's system sales
    branch_id_get = request.args.get('branch_id', default_branch)
    date_get      = request.args.get('date', today)
    sales         = _day_sales(branch_id_get, date_get) if branch_id_get else {}

    return render_template('cash_recon/new.html',
                           branches=branches,
                           default_branch=int(branch_id_get) if branch_id_get else None,
                           today=today,
                           prefill_date=date_get,
                           sales=sales,
                           methods=METHODS,
                           method_labels=METHOD_LABELS)


@bp.route('/sales-for-date')
@login_required
def sales_for_date():
    """AJAX: return system sales by method for date+branch."""
    branch_id  = request.args.get('branch_id')
    date_str   = request.args.get('date', _date.today().isoformat())
    if not branch_id:
        return jsonify({})
    sales = _day_sales(branch_id, date_str)
    return jsonify(sales)
