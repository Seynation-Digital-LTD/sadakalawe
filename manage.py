#!/usr/bin/env python3
"""
Sadakalawe management CLI — run from the repo root.

Usage:
  python3 manage.py create-owner <username> <password>
  python3 manage.py reset-password <username> <new_password>
  python3 manage.py list-users

Examples:
  python3 manage.py create-owner sey Secret999
  python3 manage.py reset-password amina NewPass123
  python3 manage.py list-users
"""
import sys
import os
import sqlite3
from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'sadakalawe.db')


def get_db():
    if not os.path.exists(DB_PATH):
        print(f"ERROR: Database not found at {DB_PATH}")
        sys.exit(1)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def cmd_create_owner(args):
    if len(args) < 2:
        print("Usage: python3 manage.py create-owner <username> <password>")
        sys.exit(1)
    username, password = args[0], args[1]
    if len(password) < 6:
        print("ERROR: Password must be at least 6 characters.")
        sys.exit(1)
    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if existing:
        print(f"ERROR: Username '{username}' already exists. Use reset-password to change their password.")
        db.close()
        sys.exit(1)
    hashed = generate_password_hash(password, method='pbkdf2:sha256')
    db.execute(
        "INSERT INTO users (username, password_hash, full_name, role, is_active) VALUES (?,?,?,?,1)",
        (username, hashed, username, 'owner')
    )
    db.commit()
    db.close()
    print(f"OK: Owner account '{username}' created. Hidden from all admin views.")


def cmd_reset_password(args):
    if len(args) < 2:
        print("Usage: python3 manage.py reset-password <username> <new_password>")
        sys.exit(1)
    username, new_password = args[0], args[1]
    if len(new_password) < 6:
        print("ERROR: Password must be at least 6 characters.")
        sys.exit(1)
    db = get_db()
    row = db.execute("SELECT id, full_name FROM users WHERE username=?", (username,)).fetchone()
    if not row:
        print(f"ERROR: No user with username '{username}' found.")
        db.close()
        sys.exit(1)
    hashed = generate_password_hash(new_password, method='pbkdf2:sha256')
    db.execute(
        "UPDATE users SET password_hash=?, must_change_password=0, session_token=NULL WHERE id=?",
        (hashed, row['id'])
    )
    db.commit()
    db.close()
    print(f"OK: Password reset for {row['full_name']} ({username}). All active sessions cleared.")


def cmd_list_users(args):
    db = get_db()
    rows = db.execute(
        "SELECT username, full_name, role, is_active FROM users ORDER BY full_name"
    ).fetchall()
    db.close()
    print(f"{'USERNAME':<20} {'FULL NAME':<25} {'ROLE':<10} ACTIVE")
    print("-" * 65)
    for r in rows:
        active = "Yes" if r['is_active'] else "No"
        print(f"{r['username']:<20} {r['full_name']:<25} {r['role']:<10} {active}")


COMMANDS = {
    'create-owner':   cmd_create_owner,
    'reset-password': cmd_reset_password,
    'list-users':     cmd_list_users,
}

if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    COMMANDS[sys.argv[1]](sys.argv[2:])
