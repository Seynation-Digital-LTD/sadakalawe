import urllib.parse
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import login_required, current_user
from database import query_db, execute_db, get_db
from services.numbering import get_next_number

bp = Blueprint('repairs', __name__, url_prefix='/repairs')

STATUSES = [
    ('received',       'Received',        '#0ea5e9', '#e0f2fe'),
    ('diagnosed',      'Diagnosed',       '#8b5cf6', '#ede9fe'),
    ('awaiting_parts', 'Awaiting Parts',  '#f59e0b', '#fef3c7'),
    ('in_progress',    'In Progress',     '#f26522', '#fff1ea'),
    ('ready',          'Ready',           '#22c55e', '#dcfce7'),
    ('collected',      'Collected',       '#64748b', '#f1f5f9'),
    ('cancelled',      'Cancelled',       '#ef4444', '#fee2e2'),
]
STATUS_MAP  = {s[0]: {'label': s[1], 'color': s[2], 'bg': s[3]} for s in STATUSES}
STATUS_KEYS = [s[0] for s in STATUSES]


def _next_status(current):
    flow = ['received', 'diagnosed', 'awaiting_parts', 'in_progress', 'ready', 'collected']
    if current in flow:
        idx = flow.index(current)
        if idx + 1 < len(flow):
            return flow[idx + 1]
    return None


def _clean_phone(phone):
    if not phone:
        return None
    digits = ''.join(c for c in str(phone) if c.isdigit())
    if digits.startswith('0') and len(digits) >= 9:
        digits = '255' + digits[1:]
    elif digits.startswith('7') or digits.startswith('6'):
        digits = '255' + digits
    return digits if len(digits) >= 10 else None


def _wa_ready_url(job):
    phone = _clean_phone(job['customer_phone'] or job['walkin_phone'])
    if not phone:
        return None
    name   = job['customer_name'] or job['walkin_name'] or 'Mteja'
    device = f"{job['device_make']} {job['device_model']}"
    msg = (
        f"Habari {name}! ✅\n\n"
        f"Bidhaa yako iko tayari kukusanywa:\n"
        f"📱 {device}\n"
        f"💰 Gharama ya ukarabati: TZS {'{:,.0f}'.format(job['final_cost'] or job['estimated_cost'] or 0)}\n\n"
        f"Karibu Sadakalawe Enterprises kukusanya.\n"
        f"📞 +255 768 596 006"
    )
    return f"https://wa.me/{phone}?text={urllib.parse.quote(msg)}"


@bp.route('/')
@login_required
def list():
    status_filter = request.args.get('status', '')
    branch_filter = request.args.get('branch_id', '')

    conds  = []
    params = []

    if status_filter:
        conds.append("rj.status = ?")
        params.append(status_filter)

    if branch_filter and current_user.is_admin:
        conds.append("rj.branch_id = ?")
        params.append(branch_filter)
    elif not current_user.is_admin and current_user.branch_id:
        conds.append("rj.branch_id = ?")
        params.append(current_user.branch_id)

    where = ("WHERE " + " AND ".join(conds)) if conds else ""

    jobs = query_db(f"""
        SELECT rj.*,
            b.name  AS branch_name,
            c.name  AS customer_name,
            c.phone AS customer_phone,
            u.full_name AS created_by_name
        FROM repair_jobs rj
        LEFT JOIN branches b ON b.id = rj.branch_id
        LEFT JOIN customers c ON c.id = rj.customer_id
        LEFT JOIN users u ON u.id = rj.created_by
        {where}
        ORDER BY rj.created_at DESC
    """, params)

    branches = query_db("SELECT id, name FROM branches ORDER BY name")

    # Count per status for tabs
    counts = {}
    for s_key, *_ in STATUSES:
        r = query_db("SELECT COUNT(*) AS n FROM repair_jobs WHERE status=?", (s_key,), one=True)
        counts[s_key] = r['n'] if r else 0

    return render_template('repairs/list.html',
                           jobs=jobs,
                           statuses=STATUSES,
                           status_map=STATUS_MAP,
                           counts=counts,
                           status_filter=status_filter,
                           branch_filter=branch_filter,
                           branches=branches)


@bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    branches = query_db("SELECT id, name FROM branches ORDER BY name")
    default_branch = current_user.branch_id or (branches[0]['id'] if branches else None)

    if request.method == 'POST':
        f = request.form
        branch_id   = int(f.get('branch_id') or default_branch)
        customer_id = f.get('customer_id') or None
        walkin_name = f.get('walkin_name', '').strip() or None
        walkin_phone= f.get('walkin_phone', '').strip() or None
        device_make = f.get('device_make', '').strip()
        device_model= f.get('device_model', '').strip()
        imei        = f.get('imei', '').strip() or None
        serial      = f.get('serial_number', '').strip() or None
        color       = f.get('color', '').strip() or None
        problem     = f.get('problem', '').strip()
        technician  = f.get('technician', '').strip() or None
        est_cost    = f.get('estimated_cost', '').strip() or None
        est_ready   = f.get('estimated_ready', '').strip() or None
        notes       = f.get('notes', '').strip() or None

        if not device_make or not device_model or not problem:
            flash('Device make, model, and problem description are required.', 'error')
            return render_template('repairs/new.html', branches=branches,
                                   default_branch=default_branch, form=f)

        year       = datetime.now().year
        job_number = get_next_number(branch_id, 'repair', year)

        job_id = execute_db("""
            INSERT INTO repair_jobs
              (job_number, branch_id, customer_id, walkin_name, walkin_phone,
               device_make, device_model, imei, serial_number, color,
               problem, technician, estimated_cost, estimated_ready,
               notes, created_by, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'received')
        """, (job_number, branch_id, customer_id, walkin_name, walkin_phone,
              device_make, device_model, imei, serial, color,
              problem, technician, est_cost, est_ready,
              notes, current_user.id))

        # Log initial status
        execute_db("""
            INSERT INTO repair_status_log (job_id, status, notes, changed_by)
            VALUES (?, 'received', 'Job created', ?)
        """, (job_id, current_user.id))

        flash(f'Repair job {job_number} created.', 'success')
        return redirect(url_for('repairs.view', job_id=job_id))

    return render_template('repairs/new.html', branches=branches,
                           default_branch=default_branch, form={})


@bp.route('/<int:job_id>')
@login_required
def view(job_id):
    job = query_db("""
        SELECT rj.*,
            b.name  AS branch_name,
            c.name  AS customer_name,
            c.phone AS customer_phone,
            u.full_name AS created_by_name
        FROM repair_jobs rj
        LEFT JOIN branches b ON b.id = rj.branch_id
        LEFT JOIN customers c ON c.id = rj.customer_id
        LEFT JOIN users u ON u.id = rj.created_by
        WHERE rj.id = ?
    """, (job_id,), one=True)
    if not job:
        abort(404)

    log = query_db("""
        SELECT sl.*, u.full_name AS user_name
        FROM repair_status_log sl
        LEFT JOIN users u ON u.id = sl.changed_by
        WHERE sl.job_id = ?
        ORDER BY sl.changed_at DESC
    """, (job_id,))

    wa_url    = _wa_ready_url(job) if job['status'] == 'ready' else None
    next_st   = _next_status(job['status'])
    next_info = STATUS_MAP.get(next_st) if next_st else None

    return render_template('repairs/view.html',
                           job=job,
                           log=log,
                           statuses=STATUSES,
                           status_map=STATUS_MAP,
                           next_status=next_st,
                           next_info=next_info,
                           wa_url=wa_url)


@bp.route('/<int:job_id>/update-status', methods=['POST'])
@login_required
def update_status(job_id):
    job = query_db("SELECT * FROM repair_jobs WHERE id=?", (job_id,), one=True)
    if not job:
        abort(404)

    new_status = request.form.get('status', '').strip()
    if new_status not in STATUS_KEYS:
        flash('Invalid status.', 'error')
        return redirect(url_for('repairs.view', job_id=job_id))

    notes      = request.form.get('notes', '').strip() or None
    final_cost = request.form.get('final_cost', '').strip() or None
    diagnosis  = request.form.get('diagnosis', '').strip() or None

    updates = ["status=?", "updated_at=datetime('now','localtime')"]
    params  = [new_status]

    if final_cost:
        updates.append("final_cost=?")
        params.append(float(final_cost))
    if diagnosis:
        updates.append("diagnosis=?")
        params.append(diagnosis)
    if new_status == 'collected':
        updates.append("collected_at=datetime('now','localtime')")

    params.append(job_id)
    get_db().execute(f"UPDATE repair_jobs SET {', '.join(updates)} WHERE id=?", params)
    get_db().commit()

    execute_db("""
        INSERT INTO repair_status_log (job_id, status, notes, changed_by)
        VALUES (?,?,?,?)
    """, (job_id, new_status, notes, current_user.id))

    flash(f"Status updated to {STATUS_MAP[new_status]['label']}.", 'success')
    return redirect(url_for('repairs.view', job_id=job_id))


@bp.route('/<int:job_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(job_id):
    job = query_db("SELECT * FROM repair_jobs WHERE id=?", (job_id,), one=True)
    if not job:
        abort(404)
    if job['status'] in ('collected', 'cancelled'):
        flash('Cannot edit a completed or cancelled job.', 'error')
        return redirect(url_for('repairs.view', job_id=job_id))

    if request.method == 'POST':
        f = request.form
        get_db().execute("""
            UPDATE repair_jobs
            SET device_make=?, device_model=?, imei=?, serial_number=?, color=?,
                problem=?, diagnosis=?, technician=?,
                estimated_cost=?, final_cost=?, estimated_ready=?,
                notes=?, updated_at=datetime('now','localtime')
            WHERE id=?
        """, (
            f.get('device_make','').strip(),
            f.get('device_model','').strip(),
            f.get('imei','').strip() or None,
            f.get('serial_number','').strip() or None,
            f.get('color','').strip() or None,
            f.get('problem','').strip(),
            f.get('diagnosis','').strip() or None,
            f.get('technician','').strip() or None,
            f.get('estimated_cost','').strip() or None,
            f.get('final_cost','').strip() or None,
            f.get('estimated_ready','').strip() or None,
            f.get('notes','').strip() or None,
            job_id,
        ))
        get_db().commit()
        flash('Job updated.', 'success')
        return redirect(url_for('repairs.view', job_id=job_id))

    branches = query_db("SELECT id, name FROM branches ORDER BY name")
    return render_template('repairs/edit.html', job=job, branches=branches)


@bp.route('/customer-search')
@login_required
def customer_search():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    rows = query_db("""
        SELECT id, name, phone FROM customers
        WHERE name LIKE ? OR phone LIKE ?
        LIMIT 10
    """, (f'%{q}%', f'%{q}%'))
    return jsonify([dict(r) for r in rows])
