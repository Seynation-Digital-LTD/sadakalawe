import sqlite3
import os
from flask import g, current_app
from werkzeug.security import generate_password_hash


def get_db():
    if 'db' not in g:
        db_path = current_app.config['DATABASE']
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        g.db = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    _create_tables(db)
    _run_migrations(db)
    _seed_data(db)
    db.commit()


def _create_tables(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS branches (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            short_code  TEXT NOT NULL UNIQUE,
            address     TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            full_name     TEXT NOT NULL,
            role          TEXT NOT NULL DEFAULT 'staff',
            branch_id     INTEGER REFERENCES branches(id),
            is_active     INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS customers (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            phone      TEXT,
            email      TEXT,
            tin        TEXT,
            address    TEXT,
            notes      TEXT,
            branch_id  INTEGER REFERENCES branches(id),
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS products (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            brand_category TEXT NOT NULL,
            model          TEXT NOT NULL,
            description    TEXT,
            price          REAL NOT NULL DEFAULT 0,
            stock_count    INTEGER NOT NULL DEFAULT 0,
            sku            TEXT,
            is_active      INTEGER NOT NULL DEFAULT 1,
            low_stock_alert INTEGER NOT NULL DEFAULT 3,
            created_at     TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at     TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS product_stock (
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            branch_id  INTEGER NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
            quantity   REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (product_id, branch_id)
        );

        CREATE TABLE IF NOT EXISTS documents (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_number      TEXT NOT NULL UNIQUE,
            doc_type        TEXT NOT NULL,
            branch_id       INTEGER NOT NULL REFERENCES branches(id),
            customer_id     INTEGER REFERENCES customers(id),
            created_by      INTEGER NOT NULL REFERENCES users(id),
            created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            is_vat          INTEGER NOT NULL DEFAULT 0,
            vat_rate        REAL NOT NULL DEFAULT 18.0,
            efd_reference   TEXT,
            subtotal        REAL NOT NULL DEFAULT 0,
            vat_amount      REAL NOT NULL DEFAULT 0,
            total           REAL NOT NULL DEFAULT 0,
            notes           TEXT,
            validity_days   INTEGER DEFAULT 7,
            status          TEXT NOT NULL DEFAULT 'final',
            payment_status  TEXT NOT NULL DEFAULT 'paid',
            amount_paid     REAL NOT NULL DEFAULT 0,
            credit_due_date TEXT
        );

        CREATE TABLE IF NOT EXISTS document_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            product_id  INTEGER REFERENCES products(id),
            description TEXT NOT NULL,
            quantity    REAL NOT NULL DEFAULT 1,
            unit_price  REAL NOT NULL DEFAULT 0,
            line_total  REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS doc_sequence (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_id     INTEGER NOT NULL REFERENCES branches(id),
            doc_type      TEXT NOT NULL,
            year          INTEGER NOT NULL,
            last_sequence INTEGER NOT NULL DEFAULT 0,
            UNIQUE(branch_id, doc_type, year)
        );

        CREATE TABLE IF NOT EXISTS payments (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id    INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            amount         REAL NOT NULL,
            payment_date   TEXT NOT NULL,
            payment_method TEXT NOT NULL DEFAULT 'cash',
            reference      TEXT,
            notes          TEXT,
            recorded_by    INTEGER REFERENCES users(id),
            created_at     TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS stock_movements (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id       INTEGER NOT NULL REFERENCES products(id),
            branch_id        INTEGER NOT NULL REFERENCES branches(id),
            movement_type    TEXT NOT NULL,
            quantity         REAL NOT NULL,
            reference_doc_id INTEGER,
            supplier         TEXT,
            notes            TEXT,
            recorded_by      INTEGER REFERENCES users(id),
            created_at       TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
    """)


def _run_migrations(db):
    """Add new columns to existing tables without breaking existing data."""
    migrations = [
        "ALTER TABLE documents ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'paid'",
        "ALTER TABLE documents ADD COLUMN amount_paid REAL NOT NULL DEFAULT 0",
        "ALTER TABLE documents ADD COLUMN credit_due_date TEXT",
        "ALTER TABLE products ADD COLUMN low_stock_alert INTEGER NOT NULL DEFAULT 3",
    ]
    for sql in migrations:
        try:
            db.execute(sql)
        except Exception:
            pass  # column already exists


def _seed_data(db):
    # Branches — seed if empty
    count = db.execute("SELECT COUNT(*) FROM branches").fetchone()[0]
    if count == 0:
        db.execute("""
            INSERT INTO branches (name, short_code, address) VALUES
            ('Arusha — Bondeni', 'ARU', 'Bondeni Street, Opposite Mega Complex, Arusha'),
            ('Arusha — Tawi 2',  'AR2', 'Arusha (Tawi la Pili) — Weka Anwani Hapa'),
            ('Dar es Salaam',    'DAR', 'Kariakoo, Aggrey Street, Dar es Salaam')
        """)
    else:
        # Add second Arusha branch if it doesn't exist yet
        if not db.execute("SELECT id FROM branches WHERE short_code='AR2'").fetchone():
            db.execute("""
                INSERT INTO branches (name, short_code, address)
                VALUES ('Arusha — Tawi 2', 'AR2', 'Arusha (Tawi la Pili) — Weka Anwani Hapa')
            """)

    # Admin user
    if not db.execute("SELECT id FROM users WHERE username='admin'").fetchone():
        db.execute(
            "INSERT INTO users (username, password_hash, full_name, role, branch_id) "
            "VALUES (?,?,?,'admin',NULL)",
            ('admin',
             generate_password_hash('admin123', method='pbkdf2:sha256'),
             'Administrator')
        )

    # Sync product_stock rows — every product should have a row per branch
    branches = db.execute("SELECT id FROM branches").fetchall()
    products = db.execute("SELECT id FROM products").fetchall()
    for p in products:
        for b in branches:
            db.execute(
                "INSERT OR IGNORE INTO product_stock (product_id, branch_id, quantity) VALUES (?,?,0)",
                (p['id'], b['id'])
            )


def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv


def execute_db(query, args=()):
    db = get_db()
    cur = db.execute(query, args)
    db.commit()
    return cur.lastrowid
