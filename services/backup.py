import os
import shutil
import csv
import zipfile
from datetime import datetime, timedelta
from io import BytesIO, StringIO
import sqlite3


def run_backup(db_path, backup_dir):
    os.makedirs(backup_dir, exist_ok=True)
    today = datetime.now().strftime('%Y-%m-%d')
    dest = os.path.join(backup_dir, f"sadakalawe_{today}.db")

    if os.path.exists(db_path):
        src_conn = sqlite3.connect(db_path)
        dst_conn = sqlite3.connect(dest)
        src_conn.backup(dst_conn)
        src_conn.close()
        dst_conn.close()

    _prune_old_backups(backup_dir, keep=7)
    return dest


def _prune_old_backups(backup_dir, keep=7):
    files = sorted([
        f for f in os.listdir(backup_dir)
        if f.startswith('sadakalawe_') and f.endswith('.db')
    ])
    while len(files) > keep:
        os.remove(os.path.join(backup_dir, files.pop(0)))


def list_backups(backup_dir):
    if not os.path.exists(backup_dir):
        return []
    files = []
    for f in sorted(os.listdir(backup_dir), reverse=True):
        if f.startswith('sadakalawe_') and f.endswith('.db'):
            path = os.path.join(backup_dir, f)
            size = os.path.getsize(path)
            files.append({
                'filename': f,
                'size_kb': round(size / 1024, 1),
                'date': f.replace('sadakalawe_', '').replace('.db', ''),
            })
    return files


def export_csv(db_path):
    buffer = BytesIO()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    tables = ['branches', 'users', 'customers', 'products', 'documents', 'document_items']

    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for table in tables:
            try:
                rows = conn.execute(f"SELECT * FROM {table}").fetchall()
                if not rows:
                    continue
                sb = StringIO()
                writer = csv.DictWriter(sb, fieldnames=rows[0].keys())
                writer.writeheader()
                for row in rows:
                    writer.writerow(dict(row))
                zf.writestr(f"{table}.csv", sb.getvalue())
            except Exception:
                pass

    conn.close()
    buffer.seek(0)
    return buffer
