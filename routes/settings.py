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
