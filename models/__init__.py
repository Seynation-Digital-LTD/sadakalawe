from flask_login import UserMixin
from database import get_db


class User(UserMixin):
    def __init__(self, id, username, full_name, role, branch_id, is_active):
        self.id = id
        self.username = username
        self.full_name = full_name
        self.role = role
        self.branch_id = branch_id
        self._is_active = bool(is_active)

    @property
    def is_active(self):
        return self._is_active

    @property
    def is_admin(self):
        return self.role == 'admin'

    @staticmethod
    def get_by_id(user_id):
        db = get_db()
        row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if row:
            return User(row['id'], row['username'], row['full_name'],
                        row['role'], row['branch_id'], row['is_active'])
        return None

    @staticmethod
    def get_by_username(username):
        db = get_db()
        row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if row:
            return User(row['id'], row['username'], row['full_name'],
                        row['role'], row['branch_id'], row['is_active'])
        return None

    def get_password_hash(self):
        db = get_db()
        row = db.execute("SELECT password_hash FROM users WHERE id=?", (self.id,)).fetchone()
        return row['password_hash'] if row else None
