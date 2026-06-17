from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, send_file, current_app)
from flask_login import login_required
from routes.auth import perm_required
from services.backup import run_backup, list_backups, export_csv
import os

bp = Blueprint('backup', __name__, url_prefix='/backup')


@bp.route('/')
@login_required
@perm_required('manage_backup')
def index():
    backups = list_backups(current_app.config['BACKUP_DIR'])
    return render_template('backup.html', backups=backups)


@bp.route('/run', methods=['POST'])
@login_required
@perm_required('manage_backup')
def run():
    try:
        dest = run_backup(current_app.config['DATABASE'], current_app.config['BACKUP_DIR'])
        flash(f'Backup saved: {os.path.basename(dest)}', 'success')
    except Exception as e:
        flash(f'Backup failed: {e}', 'danger')
    return redirect(url_for('backup.index'))


@bp.route('/download/<filename>')
@login_required
@perm_required('manage_backup')
def download(filename):
    backup_dir = current_app.config['BACKUP_DIR']
    path = os.path.join(backup_dir, filename)
    if not os.path.exists(path) or not filename.endswith('.db'):
        flash('File not found.', 'danger')
        return redirect(url_for('backup.index'))
    return send_file(path, as_attachment=True, download_name=filename)


@bp.route('/export-csv')
@login_required
@perm_required('manage_backup')
def export_csv_route():
    try:
        buffer = export_csv(current_app.config['DATABASE'])
        return send_file(buffer, mimetype='application/zip',
                         as_attachment=True, download_name='sadakalawe_export.zip')
    except Exception as e:
        flash(f'Export failed: {e}', 'danger')
        return redirect(url_for('backup.index'))
