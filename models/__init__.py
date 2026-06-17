from flask_login import UserMixin
from database import get_db


# All permissions grouped by section.
# Format: { 'Section Label': [('perm_key', 'Human description'), ...] }
PERMISSIONS = {
    'Documents': [
        ('create_documents',   'Create invoices, proformas and delivery notes'),
        ('download_documents', 'Download / reprint PDF documents'),
        ('view_all_branches',  'View documents from all branches'),
        ('void_documents',     'Void / cancel documents'),
        ('view_sales_amounts', 'See sale totals and revenue figures'),
    ],
    'Customers': [
        ('view_customers',   'View customer list'),
        ('manage_customers', 'Add and edit customers'),
    ],
    'Products & Stock': [
        ('view_products',    'View product catalog'),
        ('manage_products',  'Add and edit products and selling prices'),
        ('manage_stock',     'Receive stock and adjust quantities'),
        ('view_cost_price',  'See buying / cost price of products'),
    ],
    'Reports': [
        ('view_reports',    'View dashboard and sales reports'),
        ('view_expenses',   'View expenses'),
        ('manage_expenses', 'Add and edit expenses'),
    ],
    'System': [
        ('manage_backup', 'Run backups and export data'),
        ('manage_users',  'Manage user accounts'),
    ],
}

# Flat set of all valid permission keys
ALL_PERMISSION_KEYS = {p for perms in PERMISSIONS.values() for p, _ in perms}

# Default permissions granted to new staff accounts
DEFAULT_STAFF_PERMISSIONS = {
    'create_documents',
    'download_documents',
    'view_customers',
    'manage_customers',
    'view_products',
    'view_reports',
}


class User(UserMixin):
    def __init__(self, id, username, full_name, role, branch_id, is_active, must_change_password=0):
        self.id = id
        self.username = username
        self.full_name = full_name
        self.role = role
        self.branch_id = branch_id
        self._is_active = bool(is_active)
        self.must_change_password = bool(must_change_password)
        self._permissions = None  # lazy-loaded

    @property
    def is_active(self):
        return self._is_active

    @property
    def is_admin(self):
        return self.role == 'admin'

    def _load_permissions(self):
        if self._permissions is None:
            db = get_db()
            rows = db.execute(
                "SELECT permission FROM user_permissions WHERE user_id=?", (self.id,)
            ).fetchall()
            self._permissions = {r[0] for r in rows}
        return self._permissions

    def can(self, permission):
        """Return True if this user has the given permission (admins always pass)."""
        if self.is_admin:
            return True
        return permission in self._load_permissions()

    def get_permissions(self):
        """Return set of permission keys for this user."""
        if self.is_admin:
            return set(ALL_PERMISSION_KEYS)
        return self._load_permissions()

    @staticmethod
    def get_by_id(user_id):
        db = get_db()
        row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if row:
            mcp = row['must_change_password'] if 'must_change_password' in row.keys() else 0
            return User(row['id'], row['username'], row['full_name'],
                        row['role'], row['branch_id'], row['is_active'], mcp)
        return None

    @staticmethod
    def get_by_username(username):
        db = get_db()
        row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if row:
            mcp = row['must_change_password'] if 'must_change_password' in row.keys() else 0
            return User(row['id'], row['username'], row['full_name'],
                        row['role'], row['branch_id'], row['is_active'], mcp)
        return None

    def get_password_hash(self):
        db = get_db()
        row = db.execute("SELECT password_hash FROM users WHERE id=?", (self.id,)).fetchone()
        return row['password_hash'] if row else None
