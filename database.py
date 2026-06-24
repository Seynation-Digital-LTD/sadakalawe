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
    _seed_categories(db)
    _seed_products(db)
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

        CREATE TABLE IF NOT EXISTS expenses (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_id    INTEGER NOT NULL REFERENCES branches(id),
            category     TEXT NOT NULL,
            description  TEXT NOT NULL,
            amount       REAL NOT NULL,
            expense_date TEXT NOT NULL,
            receipt_ref  TEXT,
            recorded_by  INTEGER REFERENCES users(id),
            created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS product_categories (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL UNIQUE,
            icon       TEXT NOT NULL DEFAULT 'bi-tag',
            sort_order INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS product_subcategories (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL REFERENCES product_categories(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            UNIQUE(category_id, name)
        );

        CREATE TABLE IF NOT EXISTS user_permissions (
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            permission TEXT NOT NULL,
            PRIMARY KEY (user_id, permission)
        );

        CREATE TABLE IF NOT EXISTS device_imeis (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id        INTEGER NOT NULL REFERENCES products(id),
            branch_id         INTEGER NOT NULL REFERENCES branches(id),
            imei              TEXT NOT NULL UNIQUE,
            status            TEXT NOT NULL DEFAULT 'in_stock',
            stock_movement_id INTEGER REFERENCES stock_movements(id),
            created_at        TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS device_sales (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id      INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            document_item_id INTEGER REFERENCES document_items(id),
            customer_id      INTEGER REFERENCES customers(id),
            product_id       INTEGER REFERENCES products(id),
            imei             TEXT,
            imei2            TEXT,
            serial_number    TEXT,
            color            TEXT,
            storage          TEXT,
            notes            TEXT,
            created_by       INTEGER REFERENCES users(id),
            created_at       TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS financing_plans (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_number         TEXT NOT NULL UNIQUE,
            document_id         INTEGER REFERENCES documents(id),
            customer_id         INTEGER NOT NULL REFERENCES customers(id),
            branch_id           INTEGER NOT NULL REFERENCES branches(id),
            product_description TEXT NOT NULL,
            total_price         REAL NOT NULL,
            deposit_amount      REAL NOT NULL DEFAULT 0,
            financed_amount     REAL NOT NULL,
            num_installments    INTEGER NOT NULL DEFAULT 1,
            installment_amount  REAL NOT NULL,
            start_date          TEXT NOT NULL,
            status              TEXT NOT NULL DEFAULT 'active',
            risk_level          TEXT NOT NULL DEFAULT 'normal',
            guarantor_name      TEXT,
            guarantor_phone     TEXT,
            guarantor_id_number TEXT,
            employer            TEXT,
            notes               TEXT,
            created_by          INTEGER REFERENCES users(id),
            created_at          TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS financing_installments (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id             INTEGER NOT NULL REFERENCES financing_plans(id) ON DELETE CASCADE,
            installment_number  INTEGER NOT NULL,
            due_date            TEXT NOT NULL,
            amount_due          REAL NOT NULL,
            amount_paid         REAL NOT NULL DEFAULT 0,
            status              TEXT NOT NULL DEFAULT 'pending',
            paid_date           TEXT,
            payment_method      TEXT,
            recorded_by         INTEGER REFERENCES users(id),
            notes               TEXT,
            created_at          TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS cash_reconciliations (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            date             TEXT NOT NULL,
            branch_id        INTEGER NOT NULL REFERENCES branches(id),
            shift            TEXT NOT NULL DEFAULT 'full_day',
            cash_counted     REAL NOT NULL DEFAULT 0,
            cash_sales       REAL NOT NULL DEFAULT 0,
            mpesa_counted    REAL NOT NULL DEFAULT 0,
            mpesa_sales      REAL NOT NULL DEFAULT 0,
            airtel_counted   REAL NOT NULL DEFAULT 0,
            airtel_sales     REAL NOT NULL DEFAULT 0,
            card_counted     REAL NOT NULL DEFAULT 0,
            card_sales       REAL NOT NULL DEFAULT 0,
            other_counted    REAL NOT NULL DEFAULT 0,
            other_sales      REAL NOT NULL DEFAULT 0,
            total_diff       REAL NOT NULL DEFAULT 0,
            status           TEXT NOT NULL DEFAULT 'open',
            notes            TEXT,
            recorded_by      INTEGER REFERENCES users(id),
            created_at       TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS returns (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            return_number    TEXT NOT NULL UNIQUE,
            document_id      INTEGER REFERENCES documents(id),
            customer_id      INTEGER REFERENCES customers(id),
            walkin_name      TEXT,
            branch_id        INTEGER NOT NULL REFERENCES branches(id),
            reason           TEXT NOT NULL,
            return_type      TEXT NOT NULL DEFAULT 'refund',
            refund_amount    REAL NOT NULL DEFAULT 0,
            exchange_notes   TEXT,
            notes            TEXT,
            status           TEXT NOT NULL DEFAULT 'pending',
            processed_by     INTEGER REFERENCES users(id),
            created_by       INTEGER REFERENCES users(id),
            created_at       TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS return_items (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            return_id        INTEGER NOT NULL REFERENCES returns(id) ON DELETE CASCADE,
            document_item_id INTEGER REFERENCES document_items(id),
            product_id       INTEGER REFERENCES products(id),
            description      TEXT NOT NULL,
            quantity         REAL NOT NULL DEFAULT 1,
            unit_price       REAL NOT NULL DEFAULT 0,
            line_total       REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS repair_jobs (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            job_number       TEXT NOT NULL UNIQUE,
            branch_id        INTEGER NOT NULL REFERENCES branches(id),
            customer_id      INTEGER REFERENCES customers(id),
            walkin_name      TEXT,
            walkin_phone     TEXT,
            device_make      TEXT NOT NULL,
            device_model     TEXT NOT NULL,
            imei             TEXT,
            serial_number    TEXT,
            color            TEXT,
            problem          TEXT NOT NULL,
            diagnosis        TEXT,
            status           TEXT NOT NULL DEFAULT 'received',
            technician       TEXT,
            estimated_cost   REAL,
            final_cost       REAL,
            estimated_ready  TEXT,
            collected_at     TEXT,
            linked_document_id INTEGER REFERENCES documents(id),
            device_sale_id   INTEGER REFERENCES device_sales(id),
            notes            TEXT,
            created_by       INTEGER REFERENCES users(id),
            created_at       TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at       TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS repair_status_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id      INTEGER NOT NULL REFERENCES repair_jobs(id) ON DELETE CASCADE,
            status      TEXT NOT NULL,
            notes       TEXT,
            changed_by  INTEGER REFERENCES users(id),
            changed_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS app_settings (
            key         TEXT PRIMARY KEY,
            value       TEXT,
            updated_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS tradeins (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            tradein_number      TEXT NOT NULL UNIQUE,
            customer_id         INTEGER NOT NULL REFERENCES customers(id),
            branch_id           INTEGER NOT NULL REFERENCES branches(id),
            linked_document_id  INTEGER REFERENCES documents(id),
            device_make         TEXT NOT NULL,
            device_model        TEXT NOT NULL,
            device_imei         TEXT,
            device_color        TEXT,
            device_storage      TEXT,
            condition           TEXT NOT NULL DEFAULT 'good',
            condition_notes     TEXT,
            assessed_value      REAL NOT NULL DEFAULT 0,
            credit_offered      REAL NOT NULL DEFAULT 0,
            status              TEXT NOT NULL DEFAULT 'pending',
            disposition         TEXT DEFAULT 'in_stock',
            disposition_notes   TEXT,
            disposition_date    TEXT,
            assessed_by         INTEGER REFERENCES users(id),
            created_at          TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
    """)


def _run_migrations(db):
    """Add new columns to existing tables without breaking existing data."""
    migrations = [
        "ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN session_token TEXT",
        "ALTER TABLE document_items ADD COLUMN discount_pct REAL NOT NULL DEFAULT 0",
        "ALTER TABLE documents ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'paid'",
        "ALTER TABLE documents ADD COLUMN amount_paid REAL NOT NULL DEFAULT 0",
        "ALTER TABLE documents ADD COLUMN credit_due_date TEXT",
        "ALTER TABLE products ADD COLUMN low_stock_alert INTEGER NOT NULL DEFAULT 3",
        "ALTER TABLE documents ADD COLUMN walkin_name TEXT",
        "ALTER TABLE documents ADD COLUMN payment_method TEXT NOT NULL DEFAULT 'cash'",
        "ALTER TABLE documents ADD COLUMN batch_id TEXT",
        "ALTER TABLE products ADD COLUMN category_id INTEGER",
        "ALTER TABLE products ADD COLUMN subcategory_id INTEGER",
        "ALTER TABLE products ADD COLUMN cost_price REAL NOT NULL DEFAULT 0",
        # Fix placeholder address on Dar es Salaam branch if it was seeded with the old value
        "UPDATE branches SET address='Kariakoo, Aggrey Street, Dar es Salaam' WHERE short_code='DAR' AND address NOT LIKE '%Aggrey%'",
        "UPDATE branches SET name='Arusha (Bondeni)' WHERE short_code='ARU' AND name NOT LIKE '%Bondeni%'",
        "UPDATE branches SET address='Bondeni Street, Opposite Mega Complex, Arusha' WHERE short_code='ARU' AND address NOT LIKE '%Bondeni%'",
        "ALTER TABLE documents ADD COLUMN share_token TEXT",
        "ALTER TABLE products ADD COLUMN image_path TEXT",
        "ALTER TABLE products ADD COLUMN barcode TEXT",
        "ALTER TABLE users ADD COLUMN commission_rate REAL NOT NULL DEFAULT 0",
        # app_settings table — added 2026-06-25, safe to re-run (CREATE IF NOT EXISTS)
        """CREATE TABLE IF NOT EXISTS app_settings (
            key        TEXT PRIMARY KEY,
            value      TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )""",
    ]
    for sql in migrations:
        try:
            db.execute(sql)
        except Exception:
            pass  # column/table already exists


def _seed_data(db):
    # Branches — seed if empty
    count = db.execute("SELECT COUNT(*) FROM branches").fetchone()[0]
    if count == 0:
        db.execute("""
            INSERT INTO branches (name, short_code, address) VALUES
            ('Arusha (Bondeni)', 'ARU', 'Bondeni Street, Opposite Mega Complex, Arusha'),
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


def _seed_products(db):
    """Seed the default product catalog. Skips if already seeded (>=200 SDA products)."""
    if db.execute("SELECT COUNT(*) FROM products WHERE sku LIKE 'SDA-%'").fetchone()[0] >= 220:
        return
    db.execute("DELETE FROM products WHERE sku LIKE 'SDA-%'")  # clean partial seeds

    # Build lookup: (category_id, subcat_name) → subcat_id
    rows = db.execute("SELECT id, category_id, name FROM product_subcategories").fetchall()
    sub = {(r[1], r[2]): r[0] for r in rows}
    cat_names = {r[0]: r[1] for r in db.execute("SELECT id, name FROM product_categories").fetchall()}

    n = 0
    def add(cat_id, subcat_name, model, description, price):
        nonlocal n
        n += 1
        subcat_id = sub.get((cat_id, subcat_name))
        db.execute("""
            INSERT OR IGNORE INTO products
              (brand_category, category_id, subcategory_id, model, description, price,
               stock_count, sku, is_active)
            VALUES (?,?,?,?,?,?,0,?,1)
        """, (cat_names[cat_id], cat_id, subcat_id, model, description, price, f'SDA-{n:03d}'))

    # ── MacBook ───────────────────────────────────────────────────────
    add(1, 'Apple MacBook Air','MacBook Air M2 13" 8GB/256GB', 'Space Grey / Silver / Midnight / Starlight', 2_400_000)
    add(1, 'Apple MacBook Air','MacBook Air M2 13" 8GB/512GB', 'Space Grey / Silver / Midnight / Starlight', 2_800_000)
    add(1, 'Apple MacBook Air','MacBook Air M2 13" 16GB/512GB', 'Space Grey / Silver / Midnight / Starlight', 3_300_000)
    add(1, 'Apple MacBook Air','MacBook Air M3 13" 8GB/256GB', 'Space Grey / Silver / Midnight / Starlight / Sky Blue / Denim', 2_700_000)
    add(1, 'Apple MacBook Air','MacBook Air M3 13" 8GB/512GB', 'Space Grey / Silver / Midnight / Starlight / Sky Blue / Denim', 3_100_000)
    add(1, 'Apple MacBook Air','MacBook Air M3 13" 16GB/256GB', '', 3_000_000)
    add(1, 'Apple MacBook Air','MacBook Air M3 13" 16GB/512GB', '', 3_500_000)
    add(1, 'Apple MacBook Air','MacBook Air M3 15" 8GB/256GB', 'Space Grey / Silver / Midnight / Starlight / Sky Blue / Denim', 3_100_000)
    add(1, 'Apple MacBook Air','MacBook Air M3 15" 8GB/512GB', '', 3_500_000)
    add(1, 'Apple MacBook Air','MacBook Air M3 15" 16GB/512GB', '', 4_000_000)
    add(1, 'Apple MacBook Pro','MacBook Pro 14" M3 8GB/512GB', 'Silver / Space Black', 4_200_000)
    add(1, 'Apple MacBook Pro','MacBook Pro 14" M3 Pro 18GB/512GB', 'Silver / Space Black', 5_500_000)
    add(1, 'Apple MacBook Pro','MacBook Pro 14" M3 Max 36GB/1TB', 'Silver / Space Black', 8_200_000)
    add(1, 'Apple MacBook Pro','MacBook Pro 14" M4 16GB/512GB', 'Silver / Space Black', 4_600_000)
    add(1, 'Apple MacBook Pro','MacBook Pro 14" M4 Pro 24GB/512GB', 'Silver / Space Black', 6_000_000)
    add(1, 'Apple MacBook Pro','MacBook Pro 16" M3 Pro 18GB/512GB', 'Silver / Space Black', 6_500_000)
    add(1, 'Apple MacBook Pro','MacBook Pro 16" M3 Max 48GB/1TB', 'Silver / Space Black', 10_500_000)
    add(1, 'Apple MacBook Pro','MacBook Pro 16" M4 Pro 24GB/512GB', 'Silver / Space Black', 7_000_000)
    add(1, 'Mac Accessories', 'Apple Magic Mouse (USB-C)', 'White / Black', 110_000)
    add(1, 'Mac Accessories', 'Apple Magic Keyboard (USB-C)', 'White / Black', 130_000)
    add(1, 'Mac Accessories', 'Apple Magic Trackpad (USB-C)', 'White / Black', 155_000)
    add(1, 'Mac Accessories', 'Apple USB-C Power Adapter 30W', 'White', 90_000)
    add(1, 'Mac Accessories', 'Apple USB-C Power Adapter 67W', 'White', 130_000)
    add(1, 'Mac Accessories', 'Apple USB-C Power Adapter 96W', 'White', 155_000)
    add(1, 'Mac Accessories', 'Apple USB-C Power Adapter 140W', 'White, for MacBook Pro 16"', 180_000)
    add(1, 'Mac Accessories', 'Apple USB-C to MagSafe 3 Cable 2m', 'White', 85_000)

    # ── iPhone ────────────────────────────────────────────────────────
    for model, desc, price in [
        ('iPhone 16 128GB',     'Black / White / Pink / Teal / Ultramarine', 2_200_000),
        ('iPhone 16 256GB',     'Black / White / Pink / Teal / Ultramarine', 2_500_000),
        ('iPhone 16 512GB',     'Black / White / Pink / Teal / Ultramarine', 2_900_000),
        ('iPhone 16 Plus 128GB','Black / White / Pink / Teal / Ultramarine', 2_500_000),
        ('iPhone 16 Plus 256GB','Black / White / Pink / Teal / Ultramarine', 2_800_000),
        ('iPhone 16 Plus 512GB','Black / White / Pink / Teal / Ultramarine', 3_200_000),
        ('iPhone 16 Pro 128GB', 'Black Titanium / White Titanium / Natural Titanium / Desert Titanium', 3_000_000),
        ('iPhone 16 Pro 256GB', 'Black Titanium / White Titanium / Natural Titanium / Desert Titanium', 3_400_000),
        ('iPhone 16 Pro 512GB', 'Black Titanium / White Titanium / Natural Titanium / Desert Titanium', 3_900_000),
        ('iPhone 16 Pro 1TB',   'Black Titanium / White Titanium / Natural Titanium / Desert Titanium', 4_400_000),
        ('iPhone 16 Pro Max 256GB','Black Titanium / White Titanium / Natural Titanium / Desert Titanium', 3_700_000),
        ('iPhone 16 Pro Max 512GB','Black Titanium / White Titanium / Natural Titanium / Desert Titanium', 4_200_000),
        ('iPhone 16 Pro Max 1TB',  'Black Titanium / White Titanium / Natural Titanium / Desert Titanium', 4_700_000),
        ('iPhone 16e 128GB',       'Black / White', 1_500_000),
        ('iPhone 16e 256GB',       'Black / White', 1_750_000),
    ]:
        add(2, 'iPhone 16 Series', model, desc, price)

    for model, desc, price in [
        ('iPhone 17 128GB',          'Black / White / Sky Blue / Teal / Sand', 2_600_000),
        ('iPhone 17 256GB',          'Black / White / Sky Blue / Teal / Sand', 2_900_000),
        ('iPhone 17 512GB',          'Black / White / Sky Blue / Teal / Sand', 3_300_000),
        ('iPhone 17 Air 128GB',      'Black / White / Sky Blue / Ultramarine', 2_800_000),
        ('iPhone 17 Air 256GB',      'Black / White / Sky Blue / Ultramarine', 3_100_000),
        ('iPhone 17 Air 512GB',      'Black / White / Sky Blue / Ultramarine', 3_500_000),
        ('iPhone 17 Pro 256GB',      'Black Titanium / White Titanium / Natural Titanium / Desert Titanium', 3_700_000),
        ('iPhone 17 Pro 512GB',      'Black Titanium / White Titanium / Natural Titanium / Desert Titanium', 4_200_000),
        ('iPhone 17 Pro 1TB',        'Black Titanium / White Titanium / Natural Titanium / Desert Titanium', 4_800_000),
        ('iPhone 17 Pro Max 256GB',  'Black Titanium / White Titanium / Natural Titanium / Desert Titanium', 4_300_000),
        ('iPhone 17 Pro Max 512GB',  'Black Titanium / White Titanium / Natural Titanium / Desert Titanium', 4_800_000),
        ('iPhone 17 Pro Max 1TB',    'Black Titanium / White Titanium / Natural Titanium / Desert Titanium', 5_400_000),
    ]:
        add(2, 'iPhone 17 Series', model, desc, price)

    for model, desc, price in [
        ('iPhone 15 128GB',     'Black / Yellow / Green / Blue / Pink', 1_900_000),
        ('iPhone 15 256GB',     'Black / Yellow / Green / Blue / Pink', 2_200_000),
        ('iPhone 15 512GB',     'Black / Yellow / Green / Blue / Pink', 2_600_000),
        ('iPhone 15 Plus 128GB','Black / Yellow / Green / Blue / Pink', 2_200_000),
        ('iPhone 15 Plus 256GB','Black / Yellow / Green / Blue / Pink', 2_500_000),
        ('iPhone 15 Plus 512GB','Black / Yellow / Green / Blue / Pink', 2_900_000),
        ('iPhone 15 Pro 128GB', 'Black Titanium / White Titanium / Blue Titanium / Natural Titanium', 2_600_000),
        ('iPhone 15 Pro 256GB', 'Black Titanium / White Titanium / Blue Titanium / Natural Titanium', 2_900_000),
        ('iPhone 15 Pro 512GB', 'Black Titanium / White Titanium / Blue Titanium / Natural Titanium', 3_300_000),
        ('iPhone 15 Pro 1TB',   'Black Titanium / White Titanium / Blue Titanium / Natural Titanium', 3_700_000),
        ('iPhone 15 Pro Max 256GB','Black Titanium / White Titanium / Blue Titanium / Natural Titanium', 3_100_000),
        ('iPhone 15 Pro Max 512GB','Black Titanium / White Titanium / Blue Titanium / Natural Titanium', 3_600_000),
        ('iPhone 15 Pro Max 1TB',  'Black Titanium / White Titanium / Blue Titanium / Natural Titanium', 4_100_000),
    ]:
        add(2, 'iPhone 15 Series', model, desc, price)

    for model, desc, price in [
        ('iPhone 14 128GB',        'Midnight / Starlight / Blue / Purple / Red', 1_600_000),
        ('iPhone 14 256GB',        'Midnight / Starlight / Blue / Purple / Red', 1_900_000),
        ('iPhone 14 512GB',        'Midnight / Starlight / Blue / Purple / Red', 2_200_000),
        ('iPhone 14 Plus 128GB',   'Midnight / Starlight / Blue / Purple / Red', 1_900_000),
        ('iPhone 14 Plus 256GB',   'Midnight / Starlight / Blue / Purple / Red', 2_200_000),
        ('iPhone 14 Plus 512GB',   'Midnight / Starlight / Blue / Purple / Red', 2_500_000),
        ('iPhone 14 Pro 128GB',    'Space Black / Silver / Gold / Deep Purple', 2_100_000),
        ('iPhone 14 Pro 256GB',    'Space Black / Silver / Gold / Deep Purple', 2_400_000),
        ('iPhone 14 Pro 512GB',    'Space Black / Silver / Gold / Deep Purple', 2_800_000),
        ('iPhone 14 Pro 1TB',      'Space Black / Silver / Gold / Deep Purple', 3_200_000),
        ('iPhone 14 Pro Max 256GB','Space Black / Silver / Gold / Deep Purple', 2_700_000),
        ('iPhone 14 Pro Max 512GB','Space Black / Silver / Gold / Deep Purple', 3_100_000),
        ('iPhone 14 Pro Max 1TB',  'Space Black / Silver / Gold / Deep Purple', 3_500_000),
    ]:
        add(2, 'iPhone 14 Series', model, desc, price)

    for model, desc, price in [
        ('iPhone 13 mini 128GB',    'Midnight / Starlight / Blue / Pink / Green / Red', 950_000),
        ('iPhone 13 mini 256GB',    'Midnight / Starlight / Blue / Pink / Green / Red', 1_100_000),
        ('iPhone 13 mini 512GB',    'Midnight / Starlight / Blue / Pink / Green / Red', 1_350_000),
        ('iPhone 13 128GB',         'Midnight / Starlight / Blue / Pink / Green / Red', 1_100_000),
        ('iPhone 13 256GB',         'Midnight / Starlight / Blue / Pink / Green / Red', 1_300_000),
        ('iPhone 13 512GB',         'Midnight / Starlight / Blue / Pink / Green / Red', 1_550_000),
        ('iPhone 13 Pro 128GB',     'Graphite / Gold / Silver / Sierra Blue / Alpine Green', 1_500_000),
        ('iPhone 13 Pro 256GB',     'Graphite / Gold / Silver / Sierra Blue / Alpine Green', 1_750_000),
        ('iPhone 13 Pro 512GB',     'Graphite / Gold / Silver / Sierra Blue / Alpine Green', 2_050_000),
        ('iPhone 13 Pro 1TB',       'Graphite / Gold / Silver / Sierra Blue / Alpine Green', 2_400_000),
        ('iPhone 13 Pro Max 128GB', 'Graphite / Gold / Silver / Sierra Blue / Alpine Green', 1_700_000),
        ('iPhone 13 Pro Max 256GB', 'Graphite / Gold / Silver / Sierra Blue / Alpine Green', 2_000_000),
        ('iPhone 13 Pro Max 512GB', 'Graphite / Gold / Silver / Sierra Blue / Alpine Green', 2_300_000),
        ('iPhone 13 Pro Max 1TB',   'Graphite / Gold / Silver / Sierra Blue / Alpine Green', 2_700_000),
    ]:
        add(2, 'iPhone 13 Series', model, desc, price)

    add(2, 'iPhone SE', 'iPhone SE (3rd Gen) 64GB',  'Midnight / Starlight / Red', 1_100_000)
    add(2, 'iPhone SE', 'iPhone SE (3rd Gen) 128GB', 'Midnight / Starlight / Red', 1_300_000)
    add(2, 'iPhone SE', 'iPhone SE (3rd Gen) 256GB', 'Midnight / Starlight / Red', 1_550_000)

    add(2, 'iPhone Accessories', 'AirPods (3rd Gen)',           'White, Lightning charging case', 320_000)
    add(2, 'iPhone Accessories', 'AirPods (3rd Gen USB-C)',     'White, USB-C charging case', 340_000)
    add(2, 'iPhone Accessories', 'AirPods Pro (2nd Gen)',       'White, ANC + Transparency mode, USB-C', 580_000)
    add(2, 'iPhone Accessories', 'AirPods Max (USB-C)',         'Midnight / Starlight / Blue / Orange / Pink', 1_200_000)
    add(2, 'iPhone Accessories', 'Apple MagSafe Charger 1m',   'USB-C connector', 80_000)
    add(2, 'iPhone Accessories', 'Apple MagSafe Charger 2m',   'USB-C connector', 95_000)
    add(2, 'iPhone Accessories', 'MagSafe Battery Pack',        '1460mAh, charges wirelessly', 230_000)
    add(2, 'iPhone Accessories', 'Apple USB-C to Lightning 1m','Official Apple cable', 45_000)
    add(2, 'iPhone Accessories', 'Apple USB-C to Lightning 2m','Official Apple cable', 65_000)
    add(2, 'iPhone Accessories', 'Apple 20W USB-C Power Adapter','White, fast charge for iPhone', 65_000)

    # ── Anker ─────────────────────────────────────────────────────────
    add(3, 'Anker Chargers','Anker Nano 20W USB-C Charger',             'White / Black, compact 1-port', 45_000)
    add(3, 'Anker Chargers','Anker 30W USB-C GaN Charger',              'White / Black, 1-port GaN', 65_000)
    add(3, 'Anker Chargers','Anker 45W USB-C GaN Charger',              'White / Black, 1-port', 85_000)
    add(3, 'Anker Chargers','Anker 65W GaN Charger (1 port)',           'White / Black', 110_000)
    add(3, 'Anker Chargers','Anker 65W GaN Charger (2 ports, USB-C+A)', 'White / Black, dual port', 125_000)
    add(3, 'Anker Chargers','Anker Prime 100W GaN Charger (4 ports)',   'White / Black, 2xUSB-C + 2xUSB-A', 175_000)
    add(3, 'Anker Chargers','Anker 736 Nano II 100W GaN',               'Black, 3-port compact', 195_000)
    add(3, 'Anker Chargers','Anker PowerPort III 63W Duo',              'White, 2xUSB-C', 115_000)

    add(3, 'Anker Power Banks','Anker 321 Power Bank 5,200mAh',     '2x USB-A, compact', 55_000)
    add(3, 'Anker Power Banks','Anker PowerCore 10,000mAh',         'USB-A + USB-C, slim', 75_000)
    add(3, 'Anker Power Banks','Anker PowerCore Slim 10,000mAh',    'USB-C PD 18W', 80_000)
    add(3, 'Anker Power Banks','Anker PowerCore 20,000mAh',         'USB-A + USB-C, high capacity', 115_000)
    add(3, 'Anker Power Banks','Anker 523 Power Bank 10,000mAh',    'USB-C PD 30W, fast charge', 95_000)
    add(3, 'Anker Power Banks','Anker 737 Power Bank 26,800mAh',    '140W two-way fast charge', 280_000)
    add(3, 'Anker Power Banks','Anker MagGo Battery Pack 5,000mAh', 'MagSafe compatible, 7.5W wireless', 135_000)

    add(3, 'Anker Cables','Anker USB-C to Lightning 1m (MFi)',  'Nylon braided, Apple certified', 35_000)
    add(3, 'Anker Cables','Anker USB-C to Lightning 2m (MFi)',  'Nylon braided, Apple certified', 45_000)
    add(3, 'Anker Cables','Anker USB-C to USB-C 1m (60W)',      'Nylon braided', 30_000)
    add(3, 'Anker Cables','Anker USB-C to USB-C 2m (60W)',      'Nylon braided', 40_000)
    add(3, 'Anker Cables','Anker USB-C to USB-C 1m (240W)',     'For MacBook Pro fast charging', 55_000)
    add(3, 'Anker Cables','Anker USB-A to USB-C 1m',            'Nylon braided', 25_000)
    add(3, 'Anker Cables','Anker USB-A to Micro-USB 1m',        'Nylon braided', 20_000)

    add(4, 'Anker Soundcore Earbuds', 'Anker Soundcore A3i TWS',          'ANC, Bluetooth 5.2, 30hr total', 80_000)
    add(4, 'Anker Soundcore Earbuds', 'Anker Soundcore Life P2 Mini TWS', 'IPX5, 32hr total battery', 90_000)
    add(4, 'Anker Soundcore Earbuds', 'Anker Soundcore Life P3 TWS',      'ANC, 6-mic, 35hr total', 150_000)
    add(4, 'Anker Soundcore Earbuds', 'Anker Soundcore Liberty 4 NC',     'LDAC, ANC, 28hr total', 230_000)
    add(4, 'Anker Soundcore Earbuds', 'Anker Soundcore Liberty 4 Pro',    'LDAC, ANC, AI ClearVoice, 28hr total', 290_000)
    add(4, 'Anker Soundcore Headphones', 'Anker Soundcore Life Q30 (Over-ear)', 'ANC, Multipoint, 40hr', 140_000)
    add(4, 'Anker Soundcore Headphones', 'Anker Soundcore Q45 Headphones',       'ANC, LDAC, 50hr', 185_000)
    add(4, 'Anker Soundcore Headphones', 'Anker Soundcore Space Q45 Headphones', 'ANC, 50hr, LDAC', 250_000)

    add(5, 'USB Hubs & Docks','Anker 332 USB-A Hub (4-port)',        'USB 3.0, compact', 45_000)
    add(5, 'USB Hubs & Docks','Anker 543 USB-C Hub (6-in-1)',        '4K HDMI, 100W PD, USB 3.0', 95_000)
    add(5, 'USB Hubs & Docks','Anker 7-in-1 USB-C Hub A8346',        '4K HDMI, SD/TF, USB 3.0, PD', 110_000)
    add(5, 'USB Hubs & Docks','Anker 555 USB-C Hub (8-in-1)',        '4K HDMI, 100W PD, 1Gbps Ethernet', 140_000)
    add(5, 'USB Hubs & Docks','Anker 575 USB-C Docking Station 13-in-1','Dual 4K HDMI, 85W PD, 1Gbps', 320_000)
    add(5, 'USB Hubs & Docks','Anker PowerExpand 12-in-1 USB-C Dock', '4K HDMI, DP, 60W PD, SD/TF', 260_000)

    add(3, 'Anker Wireless Charging','Anker 313 Wireless Charger Pad 10W',     'Qi compatible', 45_000)
    add(3, 'Anker Wireless Charging','Anker 633 MagGo Wireless Charger',       'MagSafe, 15W for iPhone', 130_000)
    add(3, 'Anker Wireless Charging','Anker 544 Wireless Charging Station',    '4-in-1: iPhone + AirPods + Watch + device', 175_000)
    add(3, 'Anker Wireless Charging','Anker 3-in-1 Cube with MagSafe',         'Foldable, 15W MagSafe + Watch + AirPods', 240_000)

    # ── JBL ───────────────────────────────────────────────────────────
    add(4, 'JBL Bluetooth Speakers','JBL GO 3',        'IPX67, 5hr battery, 7 colors', 120_000)
    add(4, 'JBL Bluetooth Speakers','JBL GO 4',        'IP67, 7hr battery, USB-C charging', 140_000)
    add(4, 'JBL Bluetooth Speakers','JBL Clip 4',      'IP67, 10hr battery, carabiner clip', 175_000)
    add(4, 'JBL Bluetooth Speakers','JBL Clip 5',      'IP67, 12hr battery, rotatable carabiner', 200_000)
    add(4, 'JBL Bluetooth Speakers','JBL Flip 6',      'IP67, 12hr battery, PartyBoost', 380_000)
    add(4, 'JBL Bluetooth Speakers','JBL Flip 7',      'IP68, 12hr battery, AI Sound Boost', 420_000)
    add(4, 'JBL Bluetooth Speakers','JBL Charge 5',    'IP67, 20hr battery, power bank function', 530_000)
    add(4, 'JBL Bluetooth Speakers','JBL Charge 5 Wi-Fi', 'IP67, Wi-Fi + Bluetooth, 20hr', 650_000)
    add(4, 'JBL Bluetooth Speakers','JBL Xtreme 3',    'IP67, 15hr battery, PartyBoost', 890_000)
    add(4, 'JBL Bluetooth Speakers','JBL Xtreme 4',    'IP67, 24hr battery, Wi-Fi + BT', 980_000)
    add(4, 'JBL Bluetooth Speakers','JBL Boombox 3',   'IP67, 24hr battery, massive sound', 1_450_000)
    add(4, 'JBL Bluetooth Speakers','JBL Boombox 3 Wi-Fi', 'IP67, Wi-Fi + BT, 24hr', 1_650_000)
    add(4, 'JBL Bluetooth Speakers','JBL Pulse 5',     'IP67, 12hr battery, 360° lightshow', 680_000)

    add(4, 'JBL Earphones & Earbuds','JBL Tune 130NC TWS',    'ANC, 40hr total, IPX4', 155_000)
    add(4, 'JBL Earphones & Earbuds','JBL Tune 230NC TWS',    'ANC, 40hr total, IPX4', 200_000)
    add(4, 'JBL Earphones & Earbuds','JBL Live Free 2 TWS',   'Adaptive ANC, 40hr, IPX5', 260_000)
    add(4, 'JBL Earphones & Earbuds','JBL Live Beam 3',        'Adaptive ANC, 48hr, IPX5', 390_000)
    add(4, 'JBL Earphones & Earbuds','JBL Tour Pro 2',         'Smart case with display, ANC, 40hr', 480_000)

    add(4, 'JBL Headphones','JBL Tune 520BT',         'Wireless on-ear, 57hr battery', 130_000)
    add(4, 'JBL Headphones','JBL Tune 770NC',          'ANC, 70hr battery, foldable', 220_000)
    add(4, 'JBL Headphones','JBL Live 770NC',          'Adaptive ANC, 65hr, foldable', 310_000)
    add(4, 'JBL Headphones','JBL Tour One M2',         'Adaptive ANC, 30hr, premium leather', 520_000)
    add(4, 'JBL Headphones','JBL Quantum 350 Wireless','40hr battery, gaming headset', 280_000)
    add(4, 'JBL Headphones','JBL Quantum 910 Wireless','Spatial sound, ANC, 34hr, gaming', 580_000)

    add(4, 'JBL Soundbars','JBL Bar 300',   '5.0ch, 260W, Dolby Atmos, MultiBeam', 650_000)
    add(4, 'JBL Soundbars','JBL Bar 500',   '5.1ch, 295W, Dolby Atmos, detachable surround', 950_000)
    add(4, 'JBL Soundbars','JBL Bar 800',   '5.1.2ch, 720W, Dolby Atmos, detachable surround', 1_500_000)
    add(4, 'JBL Soundbars','JBL Bar 1000',  '7.1.4ch, 880W, Dolby Atmos, detachable surround + up-firing', 2_200_000)

    # ── Accessories ───────────────────────────────────────────────────
    add(5, 'Cases & Covers', 'iPhone 17 Silicone Case (Apple)',      'MagSafe compatible, various colors', 60_000)
    add(5, 'Cases & Covers', 'iPhone 17 Air Silicone Case (Apple)', 'MagSafe compatible, various colors', 65_000)
    add(5, 'Cases & Covers', 'iPhone 17 Pro Silicone Case (Apple)', 'MagSafe compatible, various colors', 65_000)
    add(5, 'Cases & Covers', 'iPhone 17 Pro Max Silicone Case',     'MagSafe compatible, various colors', 70_000)
    add(5, 'Cases & Covers', 'iPhone 17 Clear Case (Apple)',         'MagSafe compatible', 55_000)
    add(5, 'Cases & Covers', 'iPhone 17 Pro Clear Case (Apple)',     'MagSafe compatible', 60_000)
    add(5, 'Cases & Covers', 'iPhone 17 Silicone Case (Apple)',      'MagSafe compatible, various colors', 55_000)
    add(5, 'Cases & Covers', 'iPhone 16 Pro Silicone Case (Apple)',  'MagSafe compatible, various colors', 60_000)
    add(5, 'Cases & Covers', 'iPhone 16 Pro Max Silicone Case',      'MagSafe compatible, various colors', 65_000)
    add(5, 'Cases & Covers', 'iPhone 15 Silicone Case (Apple)',      'MagSafe compatible', 50_000)
    add(5, 'Cases & Covers', 'iPhone 15 Pro Silicone Case (Apple)',  'MagSafe compatible', 55_000)
    add(5, 'Cases & Covers', 'iPhone 14 Silicone Case (Apple)',      'MagSafe compatible', 45_000)
    add(5, 'Cases & Covers', 'iPhone 16 Clear Case (Apple)',         'MagSafe compatible', 50_000)
    add(5, 'Cases & Covers', 'iPhone 16 Pro Clear Case (Apple)',     'MagSafe compatible', 55_000)
    add(5, 'Cases & Covers', 'iPhone 16 FineWoven Case',             'MagSafe, premium material', 75_000)
    add(5, 'Cases & Covers', 'iPhone 16 Pro FineWoven Case',         'MagSafe, premium material', 80_000)
    add(5, 'Cases & Covers', 'MacBook Air 13" Hard Shell Case',      'Fits M2/M3 models', 40_000)
    add(5, 'Cases & Covers', 'MacBook Air 15" Hard Shell Case',      'Fits M2/M3 models', 45_000)
    add(5, 'Cases & Covers', 'MacBook Pro 14" Hard Shell Case',      'Fits M3/M4 models', 50_000)
    add(5, 'Cases & Covers', 'MacBook Pro 16" Hard Shell Case',      'Fits M3/M4 models', 55_000)

    add(5, 'Screen Protectors', 'iPhone 17 Tempered Glass (2-pack)',          '9H hardness, full cover', 14_000)
    add(5, 'Screen Protectors', 'iPhone 17 Air Tempered Glass (2-pack)',     '9H hardness, full cover', 14_000)
    add(5, 'Screen Protectors', 'iPhone 17 Pro Tempered Glass (2-pack)',     '9H hardness, full cover', 15_000)
    add(5, 'Screen Protectors', 'iPhone 17 Pro Max Tempered Glass (2-pack)', '9H hardness, full cover', 16_000)
    add(5, 'Screen Protectors', 'iPhone 16 Tempered Glass (2-pack)',         '9H hardness, full cover', 12_000)
    add(5, 'Screen Protectors', 'iPhone 16 Pro Tempered Glass (2-pack)',     '9H hardness, full cover', 14_000)
    add(5, 'Screen Protectors', 'iPhone 16 Pro Max Tempered Glass (2-pack)', '9H hardness, full cover', 15_000)
    add(5, 'Screen Protectors', 'iPhone 15 Tempered Glass (2-pack)',         '9H hardness', 10_000)
    add(5, 'Screen Protectors', 'iPhone 15 Pro Tempered Glass (2-pack)',     '9H hardness', 12_000)
    add(5, 'Screen Protectors', 'iPhone 14 Tempered Glass (2-pack)',         '9H hardness', 9_000)
    add(5, 'Screen Protectors', 'MacBook Screen Protector (Anti-Glare)',     'For 13"/14"/15"/16" MacBook', 25_000)
    add(5, 'Screen Protectors', 'iPhone 16 Privacy Screen Protector',       'Anti-spy, 9H', 18_000)

    add(5, 'Cables & Adapters', 'USB-C to 3.5mm Adapter',            'DAC audio adapter', 18_000)
    add(5, 'Cables & Adapters', 'Lightning to 3.5mm Adapter (Apple)','Official Apple adapter', 30_000)
    add(5, 'Cables & Adapters', 'USB-C to HDMI Adapter (4K@60Hz)',   'Supports 4K display output', 40_000)
    add(5, 'Cables & Adapters', 'USB-C to USB-A Adapter',            'USB 3.0', 15_000)
    add(5, 'Cables & Adapters', 'HDMI Cable 2m (4K)',                'High-speed HDMI 2.0', 20_000)
    add(5, 'Cables & Adapters', 'USB-A to Micro-USB Cable 1m',       'Data + charging', 10_000)

    add(5, 'Storage & Memory', 'SanDisk 32GB USB Flash Drive (USB-A)',  'USB 3.0, 130MB/s read', 22_000)
    add(5, 'Storage & Memory', 'SanDisk 64GB USB Flash Drive (USB-A)',  'USB 3.0, 130MB/s read', 38_000)
    add(5, 'Storage & Memory', 'SanDisk 128GB USB Flash Drive (USB-A)', 'USB 3.0, 130MB/s read', 60_000)
    add(5, 'Storage & Memory', 'SanDisk 256GB USB Flash Drive (USB-A)', 'USB 3.0', 95_000)
    add(5, 'Storage & Memory', 'SanDisk 128GB Ultra Dual Drive (USB-C + USB-A)', 'For phones & laptops', 60_000)
    add(5, 'Storage & Memory', 'Samsung 128GB microSDXC (Class 10)',    'A2 U3, 100MB/s read', 42_000)
    add(5, 'Storage & Memory', 'Samsung 256GB microSDXC (Class 10)',    'A2 U3, 100MB/s read', 70_000)
    add(5, 'Storage & Memory', 'SanDisk 512GB Portable SSD (USB-C)',    '520MB/s read, pocket-size', 220_000)
    add(5, 'Storage & Memory', 'SanDisk 1TB Portable SSD (USB-C)',      '520MB/s read, pocket-size', 380_000)
    add(5, 'Storage & Memory', 'Samsung T7 1TB Portable SSD',           '1,050MB/s read, USB-C', 420_000)

    add(5, 'Bags & Sleeves', 'MacBook Neoprene Sleeve 13"',    'Fits 13" MacBook Air / Pro', 30_000)
    add(5, 'Bags & Sleeves', 'MacBook Neoprene Sleeve 14"',    'Fits 14" MacBook Pro', 35_000)
    add(5, 'Bags & Sleeves', 'MacBook Neoprene Sleeve 15"',    'Fits 15" MacBook Air', 35_000)
    add(5, 'Bags & Sleeves', 'MacBook Neoprene Sleeve 16"',    'Fits 16" MacBook Pro', 40_000)
    add(5, 'Bags & Sleeves', 'Laptop Backpack 15" (Waterproof)','Multiple compartments, USB-A port', 75_000)
    add(5, 'Bags & Sleeves', 'Laptop Backpack 17" (Business)', 'Anti-theft, TSA lock, USB-A port', 95_000)
    add(5, 'Bags & Sleeves', 'Laptop Shoulder Bag 13"',        'Slim briefcase style', 55_000)
    add(5, 'Bags & Sleeves', 'Laptop Shoulder Bag 15"',        'Slim briefcase style', 65_000)
    add(5, 'Bags & Sleeves', 'Tech Organizer / Accessories Pouch', 'For cables, chargers, adapters', 30_000)

    # ── Samsung Phones ────────────────────────────────────────────────
    for model, desc, price in [
        ('Samsung Galaxy S25 128GB',       'Black / Blue / White / Mint', 2_200_000),
        ('Samsung Galaxy S25 256GB',       'Black / Blue / White / Mint', 2_500_000),
        ('Samsung Galaxy S25+ 256GB',      'Black / Silver / Navy', 2_800_000),
        ('Samsung Galaxy S25+ 512GB',      'Black / Silver / Navy', 3_100_000),
        ('Samsung Galaxy S25 Ultra 256GB', 'Titanium Black / Silver / White / Blue', 3_600_000),
        ('Samsung Galaxy S25 Ultra 512GB', 'Titanium Black / Silver / White / Blue', 4_000_000),
        ('Samsung Galaxy S25 Ultra 1TB',   'Titanium Black / Silver', 4_600_000),
    ]:
        add(2, 'Samsung Galaxy S25 Series', model, desc, price)

    for model, desc, price in [
        ('Samsung Galaxy S24 128GB',       'Onyx Black / Marble Gray / Cobalt Violet / Amber Yellow', 1_950_000),
        ('Samsung Galaxy S24 256GB',       'Onyx Black / Marble Gray / Cobalt Violet / Amber Yellow', 2_200_000),
        ('Samsung Galaxy S24+ 256GB',      'Onyx Black / Marble Gray / Cobalt Violet', 2_550_000),
        ('Samsung Galaxy S24+ 512GB',      'Onyx Black / Marble Gray', 2_850_000),
        ('Samsung Galaxy S24 Ultra 256GB', 'Titanium Black / Gray / Violet / Yellow', 3_150_000),
        ('Samsung Galaxy S24 Ultra 512GB', 'Titanium Black / Gray / Violet / Yellow', 3_500_000),
        ('Samsung Galaxy S24 Ultra 1TB',   'Titanium Black / Gray', 4_000_000),
    ]:
        add(2, 'Samsung Galaxy S24 Series', model, desc, price)

    for model, desc, price in [
        ('Samsung Galaxy A55 5G 128GB', 'Navy / Lilac / Iceblue / Awesome Lemon', 1_100_000),
        ('Samsung Galaxy A55 5G 256GB', 'Navy / Lilac / Iceblue', 1_280_000),
        ('Samsung Galaxy A35 5G 128GB', 'Navy / Lilac / Iceblue / Awesome Lemon', 850_000),
        ('Samsung Galaxy A35 5G 256GB', 'Navy / Lilac / Iceblue', 980_000),
        ('Samsung Galaxy A25 5G 128GB', 'Blue / Dark Blue / Black / Yellow', 580_000),
        ('Samsung Galaxy A25 5G 256GB', 'Blue / Dark Blue / Black', 700_000),
        ('Samsung Galaxy A15 5G 128GB', 'Blue / Black / Yellow / Light Blue', 450_000),
        ('Samsung Galaxy A06 128GB',    'Black / Blue / Gold', 360_000),
    ]:
        add(2, 'Samsung Galaxy A-Series', model, desc, price)

    for model, desc, price in [
        ('Samsung Galaxy Z Fold6 256GB', 'Navy / Pink / Silver Shadow / Crafted Black', 5_200_000),
        ('Samsung Galaxy Z Fold6 512GB', 'Navy / Pink / Silver Shadow', 5_800_000),
        ('Samsung Galaxy Z Fold6 1TB',   'Navy / Silver Shadow', 6_500_000),
        ('Samsung Galaxy Z Flip6 256GB', 'Crafted Black / Silver Shadow / Yellow / Blue / White', 3_000_000),
        ('Samsung Galaxy Z Flip6 512GB', 'Crafted Black / Silver Shadow / Yellow', 3_400_000),
    ]:
        add(2, 'Samsung Galaxy Z Fold/Flip', model, desc, price)

    # ── Tablets ───────────────────────────────────────────────────────
    add(7, 'Apple iPad (Standard)', 'iPad (10th Gen) Wi-Fi 64GB',       'Blue / Pink / Silver / Yellow', 980_000)
    add(7, 'Apple iPad (Standard)', 'iPad (10th Gen) Wi-Fi 256GB',      'Blue / Pink / Silver / Yellow', 1_380_000)
    add(7, 'Apple iPad (Standard)', 'iPad (10th Gen) Wi-Fi + Cell 64GB','Blue / Pink / Silver / Yellow', 1_380_000)
    add(7, 'Apple iPad (Standard)', 'iPad (10th Gen) Wi-Fi + Cell 256GB','Blue / Pink / Silver / Yellow', 1_800_000)

    add(7, 'Apple iPad Mini',  'iPad mini (7th Gen) Wi-Fi 128GB',       'Blue / Purple / Starlight / Midnight', 1_400_000)
    add(7, 'Apple iPad Mini',  'iPad mini (7th Gen) Wi-Fi 256GB',       'Blue / Purple / Starlight / Midnight', 1_700_000)
    add(7, 'Apple iPad Mini',  'iPad mini (7th Gen) Wi-Fi + Cell 128GB','Blue / Purple / Starlight / Midnight', 1_800_000)
    add(7, 'Apple iPad Mini',  'iPad mini (7th Gen) Wi-Fi + Cell 256GB','Blue / Purple / Starlight / Midnight', 2_100_000)

    add(7, 'Apple iPad Air',   'iPad Air M2 11" Wi-Fi 128GB',           'Blue / Purple / Starlight / Midnight', 1_650_000)
    add(7, 'Apple iPad Air',   'iPad Air M2 11" Wi-Fi 256GB',           'Blue / Purple / Starlight / Midnight', 1_950_000)
    add(7, 'Apple iPad Air',   'iPad Air M2 11" Wi-Fi + Cell 128GB',    'Blue / Purple / Starlight / Midnight', 2_100_000)
    add(7, 'Apple iPad Air',   'iPad Air M2 13" Wi-Fi 128GB',           'Blue / Purple / Starlight / Midnight', 2_200_000)
    add(7, 'Apple iPad Air',   'iPad Air M2 13" Wi-Fi 256GB',           'Blue / Purple / Starlight / Midnight', 2_500_000)
    add(7, 'Apple iPad Air',   'iPad Air M2 13" Wi-Fi + Cell 128GB',    'Blue / Purple / Starlight / Midnight', 2_700_000)

    add(7, 'Apple iPad Pro',   'iPad Pro M4 11" Wi-Fi 256GB',           'Silver / Space Black, OLED display', 2_800_000)
    add(7, 'Apple iPad Pro',   'iPad Pro M4 11" Wi-Fi 512GB',           'Silver / Space Black', 3_400_000)
    add(7, 'Apple iPad Pro',   'iPad Pro M4 11" Wi-Fi 1TB',             'Silver / Space Black', 4_500_000)
    add(7, 'Apple iPad Pro',   'iPad Pro M4 11" Wi-Fi + Cell 256GB',    'Silver / Space Black', 3_400_000)
    add(7, 'Apple iPad Pro',   'iPad Pro M4 13" Wi-Fi 256GB',           'Silver / Space Black, OLED Tandem display', 3_700_000)
    add(7, 'Apple iPad Pro',   'iPad Pro M4 13" Wi-Fi 512GB',           'Silver / Space Black', 4_300_000)
    add(7, 'Apple iPad Pro',   'iPad Pro M4 13" Wi-Fi 1TB',             'Silver / Space Black', 5_500_000)
    add(7, 'Apple iPad Pro',   'iPad Pro M4 13" Wi-Fi + Cell 256GB',    'Silver / Space Black', 4_400_000)

    add(7, 'Samsung Galaxy Tab S', 'Samsung Galaxy Tab S9 FE Wi-Fi 128GB',   '10.9", Exynos 1380', 1_250_000)
    add(7, 'Samsung Galaxy Tab S', 'Samsung Galaxy Tab S9 FE Wi-Fi 256GB',   '10.9", Exynos 1380', 1_450_000)
    add(7, 'Samsung Galaxy Tab S', 'Samsung Galaxy Tab S9 Wi-Fi 128GB',      '11" AMOLED, Snapdragon 8 Gen 2', 1_950_000)
    add(7, 'Samsung Galaxy Tab S', 'Samsung Galaxy Tab S9 Wi-Fi 256GB',      '11" AMOLED, Snapdragon 8 Gen 2', 2_250_000)
    add(7, 'Samsung Galaxy Tab S', 'Samsung Galaxy Tab S9+ Wi-Fi 256GB',     '12.4" AMOLED, Snapdragon 8 Gen 2', 2_550_000)
    add(7, 'Samsung Galaxy Tab S', 'Samsung Galaxy Tab S9 Ultra Wi-Fi 256GB','14.6" AMOLED, Snapdragon 8 Gen 2', 3_100_000)
    add(7, 'Samsung Galaxy Tab A', 'Samsung Galaxy Tab A9+ Wi-Fi 128GB',     '11" LCD, Snapdragon 695', 980_000)
    add(7, 'Samsung Galaxy Tab A', 'Samsung Galaxy Tab A9+ 5G 128GB',        '11" LCD, Snapdragon 695', 1_150_000)

    add(7, 'Lenovo Tab',   'Lenovo Tab P12 Pro Wi-Fi 256GB',  '12.6" AMOLED, Snapdragon 870', 1_650_000)
    add(7, 'Lenovo Tab',   'Lenovo Tab M11 Wi-Fi 128GB',      '11" IPS, Helio G88', 650_000)
    add(7, 'iPad Accessories', 'Apple Pencil (USB-C)',             'Universal, works with iPad 10th gen and later', 220_000)
    add(7, 'iPad Accessories', 'Apple Pencil (2nd Gen)',           'For iPad Pro/Air, wireless charging', 280_000)
    add(7, 'iPad Accessories', 'Apple Pencil Pro',                 'For iPad Pro M4 / iPad Air M2', 360_000)
    add(7, 'iPad Accessories', 'Magic Keyboard for iPad Pro 11"',  'With trackpad, backlit', 820_000)
    add(7, 'iPad Accessories', 'Magic Keyboard for iPad Pro 13"',  'With trackpad, backlit', 980_000)
    add(7, 'iPad Accessories', 'Apple Smart Folio iPad Air 11"',   'Folds to stand, magnetic attachment', 220_000)
    add(7, 'iPad Accessories', 'Apple Smart Folio iPad (10th Gen)','Folds to stand', 165_000)

    # ── Other Laptops ─────────────────────────────────────────────────
    add(1, 'Samsung Galaxy Book', 'Samsung Galaxy Book4 Pro 14" Core Ultra 7 16GB/512GB',  'Moonstone Gray / Platinum Silver', 3_800_000)
    add(1, 'Samsung Galaxy Book', 'Samsung Galaxy Book4 Pro 16" Core Ultra 7 16GB/512GB',  'Moonstone Gray / Platinum Silver', 4_300_000)
    add(1, 'Samsung Galaxy Book', 'Samsung Galaxy Book4 360 13" Core Ultra 5 16GB/512GB',  '2-in-1 touchscreen, S Pen included', 3_300_000)
    add(1, 'Samsung Galaxy Book', 'Samsung Galaxy Book4 Ultra 16" Core Ultra 9 32GB/1TB',  'Moonstone Gray, OLED display', 5_500_000)

    add(1, 'Lenovo ThinkPad', 'Lenovo ThinkPad E14 Gen 5 (AMD) Ryzen 7 16GB/512GB',   'Thunder Black, 14" IPS', 2_500_000)
    add(1, 'Lenovo ThinkPad', 'Lenovo ThinkPad E14 Gen 5 (Intel) Core i7 16GB/512GB', 'Thunder Black, 14" IPS', 2_650_000)
    add(1, 'Lenovo ThinkPad', 'Lenovo ThinkPad X1 Carbon Gen 12 Core Ultra 7 32GB/1TB','Light 1.12kg, 14" IPS', 5_500_000)
    add(1, 'Lenovo ThinkPad', 'Lenovo ThinkPad T14s Gen 5 Core Ultra 7 32GB/512GB',    '14" IPS, enterprise grade', 4_200_000)

    add(1, 'Lenovo IdeaPad', 'Lenovo IdeaPad Slim 5 Gen 9 14" Core i5 16GB/512GB',    'Cloud Grey, 14" IPS', 1_950_000)
    add(1, 'Lenovo IdeaPad', 'Lenovo IdeaPad Slim 5 Gen 9 14" Core i7 16GB/1TB',      'Cloud Grey, 14" IPS', 2_450_000)
    add(1, 'Lenovo IdeaPad', 'Lenovo IdeaPad Slim 5 Gen 9 16" Core i7 16GB/1TB',      'Cloud Grey, 16" IPS', 2_650_000)
    add(1, 'Lenovo IdeaPad', 'Lenovo IdeaPad Flex 5 14" AMD Ryzen 5 16GB/512GB',      '2-in-1 touchscreen', 1_850_000)

    add(1, 'HP Laptops', 'HP Spectre x360 14" Core Ultra 7 16GB/1TB',   '2-in-1 OLED touchscreen, premium', 4_200_000)
    add(1, 'HP Laptops', 'HP Envy x360 14" Core Ultra 5 16GB/512GB',    '2-in-1 OLED touchscreen', 2_900_000)
    add(1, 'HP Laptops', 'HP EliteBook 840 G11 14" Core Ultra 5 16GB/512GB', 'Silver, enterprise, vPro', 3_350_000)
    add(1, 'HP Laptops', 'HP EliteBook 850 G11 15" Core Ultra 7 16GB/512GB', 'Silver, enterprise', 3_800_000)
    add(1, 'HP Laptops', 'HP Pavilion 15 Core i5-12th 8GB/512GB',       'Silver / Warm Gold, everyday use', 1_650_000)
    add(1, 'HP Laptops', 'HP Pavilion 15 Core i7-12th 16GB/512GB',      'Silver, everyday use', 2_100_000)

    add(1, 'Dell Laptops', 'Dell XPS 13 9345 AMD Ryzen 7 16GB/512GB',    '13.4" OLED, thin & light', 3_600_000)
    add(1, 'Dell Laptops', 'Dell XPS 13 9345 AMD Ryzen 9 32GB/1TB',      '13.4" OLED, top config', 4_700_000)
    add(1, 'Dell Laptops', 'Dell XPS 15 9530 Core i7 16GB/512GB',        '15.6" OLED, professional', 4_900_000)
    add(1, 'Dell Laptops', 'Dell XPS 15 9530 Core i9 32GB/1TB',          '15.6" OLED, max config', 6_500_000)
    add(1, 'Dell Laptops', 'Dell Inspiron 15 3530 Core i5 8GB/512GB',    '15.6" IPS, everyday use', 1_550_000)
    add(1, 'Dell Laptops', 'Dell Inspiron 15 3530 Core i7 16GB/512GB',   '15.6" IPS, everyday use', 2_000_000)

    add(1, 'ASUS Laptops', 'ASUS ZenBook 14 OLED Core Ultra 5 16GB/512GB',  'Ponder Blue / Jasper Slate, 2.8K OLED', 2_500_000)
    add(1, 'ASUS Laptops', 'ASUS ZenBook 14X OLED Core Ultra 9 32GB/1TB',   'Inkwell Gray, 2.8K OLED 120Hz', 3_900_000)
    add(1, 'ASUS Laptops', 'ASUS VivoBook 15 OLED Core i5 8GB/512GB',       'Indie Black / Cool Silver, 15.6" OLED', 1_650_000)
    add(1, 'ASUS Laptops', 'ASUS VivoBook 15 Core i7 16GB/512GB',           'Indie Black, 15.6" IPS', 2_050_000)
    add(1, 'ASUS Laptops', 'ASUS ROG Zephyrus G14 AMD Ryzen 9 16GB/512GB',  'Eclipse Gray, gaming 14" QHD 165Hz', 4_500_000)

    # ── Smart Wearables ───────────────────────────────────────────────
    add(6, 'Apple Watch', 'Apple Watch SE (2nd Gen) 40mm GPS Aluminum',  'Midnight / Starlight / Silver + Sport Band', 680_000)
    add(6, 'Apple Watch', 'Apple Watch SE (2nd Gen) 44mm GPS Aluminum',  'Midnight / Starlight / Silver + Sport Band', 760_000)
    add(6, 'Apple Watch', 'Apple Watch Series 10 42mm GPS Aluminum',     'Jet Black / Rose Gold / Silver / Ultramarine / Slate', 1_100_000)
    add(6, 'Apple Watch', 'Apple Watch Series 10 46mm GPS Aluminum',     'Jet Black / Rose Gold / Silver / Ultramarine / Slate', 1_200_000)
    add(6, 'Apple Watch', 'Apple Watch Series 10 42mm GPS + Cell Aluminum','Jet Black / Rose Gold / Silver / Ultramarine', 1_380_000)
    add(6, 'Apple Watch', 'Apple Watch Series 10 46mm GPS + Cell Aluminum','Jet Black / Rose Gold / Silver / Ultramarine', 1_500_000)
    add(6, 'Apple Watch', 'Apple Watch Ultra 2 49mm Titanium GPS+Cell',  'Natural / Black Titanium, rugged', 2_250_000)

    add(6, 'Samsung Galaxy Watch', 'Samsung Galaxy Watch FE 40mm Bluetooth', 'Pink Gold / Black / Silver', 560_000)
    add(6, 'Samsung Galaxy Watch', 'Samsung Galaxy Watch 7 40mm Bluetooth',  'Cream / Green / Gold / Silver', 830_000)
    add(6, 'Samsung Galaxy Watch', 'Samsung Galaxy Watch 7 44mm Bluetooth',  'Green / Gray', 950_000)
    add(6, 'Samsung Galaxy Watch', 'Samsung Galaxy Watch 7 44mm LTE',        'Green / Gray', 1_100_000)
    add(6, 'Samsung Galaxy Watch', 'Samsung Galaxy Watch Ultra 47mm Bluetooth','White / Gray / Yellow', 1_680_000)
    add(6, 'Samsung Galaxy Watch', 'Samsung Galaxy Watch Ultra 47mm LTE',    'White / Gray / Yellow', 1_850_000)

    add(6, 'Garmin', 'Garmin Forerunner 255 GPS Running Watch',     '41mm, 14-day battery, HRV', 950_000)
    add(6, 'Garmin', 'Garmin Forerunner 965 GPS Running Watch',     '47mm, AMOLED, 23-day battery', 1_700_000)
    add(6, 'Garmin', 'Garmin Venu 3 GPS Smartwatch',                '45mm AMOLED, sleep coaching', 1_300_000)
    add(6, 'Garmin', 'Garmin Fenix 7 Pro Solar',                    '47mm, solar charging, expedition', 2_000_000)
    add(6, 'Garmin', 'Garmin Epix Pro Gen 2 51mm Solar',            'AMOLED, expedition, max maps', 2_800_000)

    add(6, 'Fitness Bands', 'Samsung Galaxy Fit3',   'Slim, AMOLED, 13-day battery', 220_000)
    add(6, 'Fitness Bands', 'Xiaomi Smart Band 9',   'AMOLED, 21-day battery, 150+ modes', 150_000)
    add(6, 'Fitness Bands', 'Fitbit Charge 6',       'Google Maps, 7-day battery, ECG', 380_000)
    add(6, 'Fitness Bands', 'Fitbit Inspire 3',      'Slim, 10-day battery, mood tracking', 280_000)

    # ── Cameras & Drones ──────────────────────────────────────────────
    add(8, 'GoPro Action Cameras', 'GoPro HERO13 Black',                   '5.3K60 video, HyperSmooth 6.0, waterproof 10m', 1_150_000)
    add(8, 'GoPro Action Cameras', 'GoPro HERO12 Black',                   '5.3K60 video, HyperSmooth 5.0, waterproof 10m', 950_000)
    add(8, 'GoPro Action Cameras', 'GoPro HERO13 Black Creator Edition',   'Includes Volta battery grip, media mod, light mod', 1_700_000)
    add(8, 'GoPro Action Cameras', 'GoPro HERO13 Mini',                    'Lightweight 86g, 5.3K30, no screen', 850_000)
    add(8, 'GoPro Action Cameras', 'GoPro HERO (2024)',                    '4K30, entry-level, 10m waterproof', 580_000)
    add(8, 'GoPro Action Cameras', 'GoPro 64GB Enduro Battery (2-pack)',  'Long-endurance battery for HERO12/13', 95_000)

    add(8, 'DJI Drones', 'DJI Mini 4 Pro (DJI RC-N2)',        '4K/60fps, 34-min flight, 249g, obstacle avoidance', 2_150_000)
    add(8, 'DJI Drones', 'DJI Mini 4 Pro (DJI RC2)',          '4K/60fps, 34-min, intelligent screen remote', 2_700_000)
    add(8, 'DJI Drones', 'DJI Mini 4 Pro Fly More Combo',     'Includes 3 batteries + charging hub', 3_200_000)
    add(8, 'DJI Drones', 'DJI Air 3 (DJI RC-N3)',             'Dual camera, 4K/100fps HDR, 46-min, obstacle avoidance', 3_100_000)
    add(8, 'DJI Drones', 'DJI Air 3 (DJI RC2)',               'Dual camera, 4K/100fps, intelligent screen remote', 3_700_000)
    add(8, 'DJI Drones', 'DJI Mavic 3 Pro (DJI RC)',          'Triple camera, 5.1K HDR, 43-min, pro-grade', 5_800_000)

    add(8, 'DJI Cameras', 'DJI Osmo Action 5 Pro',     '4K/120fps, 8T HorizonSteady, -20°C cold resistance', 950_000)
    add(8, 'DJI Cameras', 'DJI Osmo Pocket 3',         '1" CMOS, 4K/120fps, motorized gimbal, OLED', 1_500_000)
    add(8, 'DJI Cameras', 'DJI Osmo Mobile 6',         '3-axis phone gimbal stabilizer, ActiveTrack', 370_000)
    add(8, 'DJI Cameras', 'DJI Mic 2 (2 TX + 1 RX)',  'Wireless microphone system for creators', 750_000)
    add(8, 'DJI Cameras', 'DJI Action 2 Dual-Screen Combo', '4K/120fps, tiny modular design', 650_000)

    # ── Sony Audio ────────────────────────────────────────────────────
    add(4, 'Sony Audio', 'Sony WH-1000XM5 Wireless Headphones',       'Black / Platinum Silver, 30hr, LDAC ANC', 980_000)
    add(4, 'Sony Audio', 'Sony WH-1000XM4 Wireless Headphones',       'Black / Silver, 30hr, LDAC ANC', 780_000)
    add(4, 'Sony Audio', 'Sony WF-1000XM5 TWS Earbuds',               'Black / Platinum Silver, LDAC, ANC, 8hr', 850_000)
    add(4, 'Sony Audio', 'Sony WF-C700N TWS Earbuds',                  'Black / White / Lavender / Sage, ANC compact', 420_000)
    add(4, 'Sony Audio', 'Sony WF-C510 TWS Earbuds',                   'Black / White / Green / Orange, 11hr', 190_000)
    add(4, 'Sony Audio', 'Sony SRS-XB100 Bluetooth Speaker',           'Compact, IP67, 16hr battery, 9 colors', 165_000)
    add(4, 'Sony Audio', 'Sony SRS-XE300 Bluetooth Speaker',           'IP67, 24hr, X-Balanced speaker unit', 420_000)
    add(4, 'Sony Audio', 'Sony SRS-XG300 Bluetooth Speaker',           'IP67, 25hr, X-Balanced, light show', 680_000)

    db.commit()


def _seed_categories(db):
    # Use UPSERT so category names/icons update if already seeded with old names
    categories = [
        (1, 'Laptops & Computers',  'bi-laptop-fill',           1),
        (2, 'Smartphones',          'bi-phone-fill',            2),
        (3, 'Power & Charging',     'bi-battery-charging-fill', 3),
        (4, 'Audio & Sound',        'bi-headphones',            4),
        (5, 'Accessories',          'bi-bag-fill',              5),
        (6, 'Smart Wearables',      'bi-watch',                 6),
        (7, 'Tablets',              'bi-tablet-landscape-fill', 7),
        (8, 'Cameras & Drones',     'bi-camera-fill',           8),
    ]
    for cat_id, name, icon, sort_order in categories:
        db.execute("""
            INSERT INTO product_categories (id, name, icon, sort_order) VALUES (?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET name=excluded.name, icon=excluded.icon, sort_order=excluded.sort_order
        """, (cat_id, name, icon, sort_order))

    # Rebuild subcategories only if count doesn't match expected (60 subcats)
    # When rebuilding, also delete SDA products so they re-seed with fresh subcat IDs
    expected_subcats = 60
    current_subcats = db.execute("SELECT COUNT(*) FROM product_subcategories").fetchone()[0]
    if current_subcats == expected_subcats:
        return  # already up-to-date
    db.execute("DELETE FROM product_subcategories")
    db.execute("DELETE FROM products WHERE sku LIKE 'SDA-%'")

    subcats = [
        # Laptops & Computers (1)
        (1, 'Apple MacBook Air', 1), (1, 'Apple MacBook Pro', 2), (1, 'Mac Accessories', 3),
        (1, 'Samsung Galaxy Book', 4), (1, 'Lenovo ThinkPad', 5), (1, 'Lenovo IdeaPad', 6),
        (1, 'HP Laptops', 7), (1, 'Dell Laptops', 8), (1, 'ASUS Laptops', 9), (1, 'Other Laptops', 10),
        # Smartphones (2)
        (2, 'iPhone 16 Series', 1), (2, 'iPhone 15 Series', 2), (2, 'iPhone 14 Series', 3),
        (2, 'iPhone 13 Series', 4), (2, 'iPhone SE', 5), (2, 'iPhone Accessories', 6),
        (2, 'Samsung Galaxy S25 Series', 7), (2, 'Samsung Galaxy S24 Series', 8),
        (2, 'Samsung Galaxy A-Series', 9), (2, 'Samsung Galaxy Z Fold/Flip', 10),
        (2, 'AirPods & Audio', 11), (2, 'Other Phones', 12),
        # Power & Charging (3)
        (3, 'Anker Chargers', 1), (3, 'Anker Power Banks', 2), (3, 'Anker Cables', 3),
        (3, 'Anker Wireless Charging', 4), (3, 'Other Chargers & Power Banks', 5),
        # Audio & Sound (4)
        (4, 'JBL Bluetooth Speakers', 1), (4, 'JBL Soundbars', 2),
        (4, 'JBL Earphones & Earbuds', 3), (4, 'JBL Headphones', 4),
        (4, 'Anker Soundcore Earbuds', 5), (4, 'Anker Soundcore Headphones', 6),
        (4, 'Sony Audio', 7), (4, 'Other Audio', 8),
        # Accessories (5)
        (5, 'Cases & Covers', 1), (5, 'Screen Protectors', 2), (5, 'Cables & Adapters', 3),
        (5, 'USB Hubs & Docks', 4), (5, 'Storage & Memory', 5),
        (5, 'Bags & Sleeves', 6), (5, 'Other Accessories', 7),
        # Smart Wearables (6)
        (6, 'Apple Watch', 1), (6, 'Samsung Galaxy Watch', 2),
        (6, 'Garmin', 3), (6, 'Fitness Bands', 4), (6, 'Other Wearables', 5),
        # Tablets (7)
        (7, 'Apple iPad Pro', 1), (7, 'Apple iPad Air', 2),
        (7, 'Apple iPad (Standard)', 3), (7, 'Apple iPad Mini', 4), (7, 'iPad Accessories', 5),
        (7, 'Samsung Galaxy Tab S', 6), (7, 'Samsung Galaxy Tab A', 7),
        (7, 'Lenovo Tab', 8), (7, 'Other Tablets', 9),
        # Cameras & Drones (8)
        (8, 'GoPro Action Cameras', 1), (8, 'DJI Drones', 2),
        (8, 'DJI Cameras', 3), (8, 'Other Cameras', 4),
    ]
    for cat_id, name, sort_order in subcats:
        db.execute(
            "INSERT INTO product_subcategories (category_id, name, sort_order) VALUES (?,?,?)",
            (cat_id, name, sort_order)
        )

    # Re-map existing seeded products from old subcategory names to new ones
    remap = {
        'MacBook Air': 'Apple MacBook Air', 'MacBook Pro': 'Apple MacBook Pro',
        'Mac Accessories': 'Mac Accessories',
        'iPhone 16 Series': 'iPhone 16 Series', 'iPhone 15 Series': 'iPhone 15 Series',
        'iPhone 14 Series': 'iPhone 14 Series', 'iPhone SE': 'iPhone SE',
        'iPhone Accessories': 'iPhone Accessories',
        'Chargers': 'Anker Chargers', 'Power Banks': 'Anker Power Banks',
        'Cables': 'Anker Cables', 'Charging Stations': 'Anker Wireless Charging',
        'USB Hubs & Docks': 'USB Hubs & Docks',
        'Earbuds & Headphones': 'Anker Soundcore Earbuds',
        'Bluetooth Speakers': 'JBL Bluetooth Speakers', 'Soundbars': 'JBL Soundbars',
        'Earphones': 'JBL Earphones & Earbuds', 'Headphones': 'JBL Headphones',
        'Cases & Covers': 'Cases & Covers', 'Screen Protectors': 'Screen Protectors',
        'Cables & Adapters': 'Cables & Adapters', 'Storage & Memory': 'Storage & Memory',
        'Bags & Sleeves': 'Bags & Sleeves', 'Other Accessories': 'Other Accessories',
    }
    for old_name, new_name in remap.items():
        new_sub = db.execute("""
            SELECT ps.id FROM product_subcategories ps
            WHERE ps.name = ?
        """, (new_name,)).fetchone()
        if new_sub:
            db.execute("UPDATE products SET subcategory_id=? WHERE subcategory_id IN "
                       "(SELECT id FROM product_subcategories WHERE name=?) AND sku LIKE 'SDA-%'",
                       (new_sub[0], old_name))

    # Auto-map brand_category text → new category IDs
    brand_to_cat = {
        'MacBook': 1, 'iPhone': 2, 'Anker': 3, 'JBL': 4,
        'Accessories': 5, 'Other': 5,
        'Laptops & Computers': 1, 'Smartphones': 2,
        'Power & Charging': 3, 'Audio & Sound': 4,
        'Smart Wearables': 6, 'Tablets': 7, 'Cameras & Drones': 8,
    }
    for brand, cat_id in brand_to_cat.items():
        db.execute("""
            UPDATE products SET category_id=? WHERE brand_category=? AND category_id IS NULL
        """, (cat_id, brand))


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
