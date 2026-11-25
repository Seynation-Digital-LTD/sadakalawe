from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required
from database import query_db, execute_db
from routes.auth import admin_required

bp = Blueprint('settings', __name__, url_prefix='/settings')

MAIL_KEYS = ['MAIL_FROM', 'MAIL_USERNAME', 'MAIL_PASSWORD', 'MAIL_SERVER', 'MAIL_PORT']
PASS_PLACEHOLDER = '••••••••'


def get_setting(key, default=''):
    row = query_db("SELECT value FROM app_settings WHERE key=?", (key,), one=True)
    return row['value'] if row else default


def save_setting(key, value):
    execute_db("""
        INSERT INTO app_settings (key, value)
        VALUES (?,?)
        ON CONFLICT(key) DO UPDATE SET
            value      = excluded.value,
            updated_at = datetime('now','localtime')
    """, (key, value))


def get_mail_config():
    """Return merged mail config: DB settings override app config (env vars)."""
    config = {
        'MAIL_SERVER':   current_app.config.get('MAIL_SERVER',   'smtp.gmail.com'),
        'MAIL_PORT':     current_app.config.get('MAIL_PORT',     465),
        'MAIL_USERNAME': current_app.config.get('MAIL_USERNAME', ''),
        'MAIL_PASSWORD': current_app.config.get('MAIL_PASSWORD', ''),
        'MAIL_FROM':     current_app.config.get('MAIL_FROM',     ''),
    }
    try:
        rows = query_db("SELECT key, value FROM app_settings WHERE key LIKE 'MAIL_%'")
        for row in rows:
            if row['value']:   # don't override with empty DB values
                config[row['key']] = row['value']
    except Exception:
        pass   # table may not exist yet on first run before restart
    return config


@bp.route('/', methods=['GET', 'POST'])
@login_required
@admin_required
def index():
    if request.method == 'POST':
        for key in MAIL_KEYS:
            val = request.form.get(key, '').strip()
            if key == 'MAIL_PASSWORD' and val == PASS_PLACEHOLDER:
                continue   # don't wipe with the display placeholder
            if val:
                save_setting(key, val)
        flash('Settings saved.', 'success')
        return redirect(url_for('settings.index'))

    current = {key: get_setting(key) for key in MAIL_KEYS}
    if not current['MAIL_SERVER']:
        current['MAIL_SERVER'] = 'smtp.gmail.com'
    if not current['MAIL_PORT']:
        current['MAIL_PORT'] = '465'
    has_password = bool(current.get('MAIL_PASSWORD'))
    return render_template('settings/index.html',
                           current=current,
                           has_password=has_password,
                           pass_placeholder=PASS_PLACEHOLDER)


@bp.route('/test-email', methods=['POST'])
@login_required
@admin_required
def test_email():
    from services.email_service import send_document_email
    to_email = request.form.get('test_email', '').strip()
    if not to_email:
        flash('Enter an email address for the test.', 'danger')
        return redirect(url_for('settings.index'))

    config = get_mail_config()
    body_html = """
    <div style="font-family:Arial,sans-serif;max-width:480px">
      <div style="background:#F26522;padding:16px 24px;border-radius:8px 8px 0 0">
        <h2 style="color:#fff;margin:0;font-size:17px">Sadakalawe Enterprises</h2>
      </div>
      <div style="background:#fff;border:1px solid #e1bfb3;border-top:none;
                  padding:22px 24px;border-radius:0 0 8px 8px">
        <p style="color:#1b1c1c">This is a test email from Sadakalawe Sales System.</p>
        <p style="color:#5f5e5e">If you received this, your email settings are working correctly.</p>
        <hr style="border:none;border-top:1px solid #e1bfb3;margin:16px 0">
        <p style="color:#9ca3af;font-size:11px;margin:0">
          sadakalawe.com · TIN: 164-334-864
        </p>
      </div>
    </div>
    """
    ok, err = send_document_email(
        to_email=to_email,
        subject='Sadakalawe — Email Test',
        body_html=body_html,
        pdf_bytes=None,
        filename=None,
        app_config=config,
    )
    if ok:
        flash(f'Test email sent to {to_email}. Check the inbox.', 'success')
    else:
        flash(f'Test failed: {err}', 'danger')
    return redirect(url_for('settings.index'))


@bp.route('/activity')
@login_required
@admin_required
def activity():
    """Who edited, deleted, converted or wrote off what — newest first."""
    rows = query_db("""
        SELECT a.*, u.full_name AS user_name, b.name AS branch_name
        FROM audit_log a
        LEFT JOIN users u ON u.id = a.user_id
        LEFT JOIN branches b ON b.id = a.branch_id
        ORDER BY a.id DESC LIMIT 500
    """)
    return render_template('settings/activity.html', rows=rows)



def _norm_model(model):
    return ''.join(ch for ch in (model or '').lower() if ch.isalnum())


@bp.route('/duplicates')
@login_required
@admin_required
def duplicates():
    """One place to find duplicated sales, sales with two invoices, and duplicate products."""
    # Same staff, same branch, same customer, same total, within 10 minutes = probably a double entry
    pairs = query_db("""
        SELECT a.id AS a_id, a.doc_number AS a_num, a.created_at AS a_at,
               b.id AS b_id, b.doc_number AS b_num, b.created_at AS b_at,
               a.total, COALESCE(c.name, a.walkin_name) AS customer_name,
               br.name AS branch_name, u.full_name AS staff_name
        FROM documents a
        JOIN documents b ON b.doc_type = 'invoice' AND b.id > a.id
             AND b.branch_id = a.branch_id AND b.total = a.total AND b.created_by = a.created_by
             AND COALESCE(b.customer_id, -1) = COALESCE(a.customer_id, -1)
             AND COALESCE(b.walkin_name, '') = COALESCE(a.walkin_name, '')
             AND ABS(julianday(b.created_at) - julianday(a.created_at)) <= 10 / 1440.0
             AND COALESCE(b.batch_id, '') != COALESCE(a.batch_id, '#')
        LEFT JOIN customers c ON c.id = a.customer_id
        JOIN branches br ON br.id = a.branch_id
        JOIN users u ON u.id = a.created_by
        WHERE a.doc_type = 'invoice'
        ORDER BY a.created_at DESC LIMIT 200
    """)
    def _lines(doc_id):
        return [(r['product_id'], r['description'], r['quantity'], r['line_total']) for r in query_db(
            "SELECT product_id, description, quantity, line_total FROM document_items "
            "WHERE document_id=? ORDER BY id", (doc_id,))]
    dup_sales = [dict(p, same_items=_lines(p['a_id']) == _lines(p['b_id'])) for p in pairs]

    # One sale that ended up with two invoices (old proforma → invoice conversion)
    double_invoiced = query_db("""
        SELECT batch_id, GROUP_CONCAT(doc_number, ', ') AS numbers,
               GROUP_CONCAT(id) AS ids, MIN(id) AS first_id, SUM(total) AS counted
        FROM documents WHERE doc_type='invoice' AND batch_id IS NOT NULL
        GROUP BY batch_id HAVING COUNT(*) > 1
        ORDER BY MAX(created_at) DESC
    """)

    # Products whose names only differ in spaces / capitals / punctuation
    groups = {}
    for p in query_db("""
        SELECT p.*, COALESCE(pc.name, p.brand_category) AS category_name,
               (SELECT COUNT(*) FROM document_items di WHERE di.product_id = p.id) AS times_sold
        FROM products p LEFT JOIN product_categories pc ON pc.id = p.category_id
        WHERE p.is_active = 1 ORDER BY p.id
    """):
        groups.setdefault(_norm_model(p['model']), []).append(dict(p))
    dup_products = [g for g in groups.values() if len(g) > 1]

    return render_template('settings/duplicates.html', dup_sales=dup_sales,
                           double_invoiced=double_invoiced, dup_products=dup_products)
