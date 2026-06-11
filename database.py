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
    """)


def _run_migrations(db):
    """Add new columns to existing tables without breaking existing data."""
    migrations = [
        "ALTER TABLE documents ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'paid'",
        "ALTER TABLE documents ADD COLUMN amount_paid REAL NOT NULL DEFAULT 0",
        "ALTER TABLE documents ADD COLUMN credit_due_date TEXT",
        "ALTER TABLE products ADD COLUMN low_stock_alert INTEGER NOT NULL DEFAULT 3",
        "ALTER TABLE documents ADD COLUMN walkin_name TEXT",
        "ALTER TABLE documents ADD COLUMN payment_method TEXT NOT NULL DEFAULT 'cash'",
        "ALTER TABLE documents ADD COLUMN batch_id TEXT",
        "ALTER TABLE products ADD COLUMN category_id INTEGER",
        "ALTER TABLE products ADD COLUMN subcategory_id INTEGER",
        # Fix placeholder address on Dar es Salaam branch if it was seeded with the old value
        "UPDATE branches SET address='Kariakoo, Aggrey Street, Dar es Salaam' WHERE short_code='DAR' AND address NOT LIKE '%Aggrey%'",
        "UPDATE branches SET name='Arusha — Bondeni' WHERE short_code='ARU' AND name NOT LIKE '%Bondeni%'",
        "UPDATE branches SET address='Bondeni Street, Opposite Mega Complex, Arusha' WHERE short_code='ARU' AND address NOT LIKE '%Bondeni%'",
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


def _seed_products(db):
    """Seed the default product catalog. Runs once — skips if SDA-prefixed SKUs already exist."""
    if db.execute("SELECT COUNT(*) FROM products WHERE sku LIKE 'SDA-%'").fetchone()[0] > 0:
        return

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
    add(1, 'MacBook Air', 'MacBook Air M2 13" 8GB/256GB', 'Space Grey / Silver / Midnight / Starlight', 2_400_000)
    add(1, 'MacBook Air', 'MacBook Air M2 13" 8GB/512GB', 'Space Grey / Silver / Midnight / Starlight', 2_800_000)
    add(1, 'MacBook Air', 'MacBook Air M2 13" 16GB/512GB', 'Space Grey / Silver / Midnight / Starlight', 3_300_000)
    add(1, 'MacBook Air', 'MacBook Air M3 13" 8GB/256GB', 'Space Grey / Silver / Midnight / Starlight / Sky Blue / Denim', 2_700_000)
    add(1, 'MacBook Air', 'MacBook Air M3 13" 8GB/512GB', 'Space Grey / Silver / Midnight / Starlight / Sky Blue / Denim', 3_100_000)
    add(1, 'MacBook Air', 'MacBook Air M3 13" 16GB/256GB', '', 3_000_000)
    add(1, 'MacBook Air', 'MacBook Air M3 13" 16GB/512GB', '', 3_500_000)
    add(1, 'MacBook Air', 'MacBook Air M3 15" 8GB/256GB', 'Space Grey / Silver / Midnight / Starlight / Sky Blue / Denim', 3_100_000)
    add(1, 'MacBook Air', 'MacBook Air M3 15" 8GB/512GB', '', 3_500_000)
    add(1, 'MacBook Air', 'MacBook Air M3 15" 16GB/512GB', '', 4_000_000)
    add(1, 'MacBook Pro', 'MacBook Pro 14" M3 8GB/512GB', 'Silver / Space Black', 4_200_000)
    add(1, 'MacBook Pro', 'MacBook Pro 14" M3 Pro 18GB/512GB', 'Silver / Space Black', 5_500_000)
    add(1, 'MacBook Pro', 'MacBook Pro 14" M3 Max 36GB/1TB', 'Silver / Space Black', 8_200_000)
    add(1, 'MacBook Pro', 'MacBook Pro 14" M4 16GB/512GB', 'Silver / Space Black', 4_600_000)
    add(1, 'MacBook Pro', 'MacBook Pro 14" M4 Pro 24GB/512GB', 'Silver / Space Black', 6_000_000)
    add(1, 'MacBook Pro', 'MacBook Pro 16" M3 Pro 18GB/512GB', 'Silver / Space Black', 6_500_000)
    add(1, 'MacBook Pro', 'MacBook Pro 16" M3 Max 48GB/1TB', 'Silver / Space Black', 10_500_000)
    add(1, 'MacBook Pro', 'MacBook Pro 16" M4 Pro 24GB/512GB', 'Silver / Space Black', 7_000_000)
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
    ]:
        series = 'iPhone 16 Series'
        add(2, series, model, desc, price)

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
        ('iPhone 14 128GB',       'Midnight / Starlight / Blue / Purple / Red', 1_600_000),
        ('iPhone 14 256GB',       'Midnight / Starlight / Blue / Purple / Red', 1_900_000),
        ('iPhone 14 512GB',       'Midnight / Starlight / Blue / Purple / Red', 2_200_000),
        ('iPhone 14 Plus 128GB',  'Midnight / Starlight / Blue / Purple / Red', 1_900_000),
        ('iPhone 14 Plus 256GB',  'Midnight / Starlight / Blue / Purple / Red', 2_200_000),
        ('iPhone 14 Pro 128GB',   'Space Black / Silver / Gold / Deep Purple', 2_100_000),
        ('iPhone 14 Pro 256GB',   'Space Black / Silver / Gold / Deep Purple', 2_400_000),
        ('iPhone 14 Pro 512GB',   'Space Black / Silver / Gold / Deep Purple', 2_800_000),
        ('iPhone 14 Pro Max 256GB','Space Black / Silver / Gold / Deep Purple', 2_700_000),
        ('iPhone 14 Pro Max 512GB','Space Black / Silver / Gold / Deep Purple', 3_100_000),
    ]:
        add(2, 'iPhone 14 Series', model, desc, price)

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
    add(3, 'Chargers', 'Anker Nano 20W USB-C Charger',             'White / Black, compact 1-port', 45_000)
    add(3, 'Chargers', 'Anker 30W USB-C GaN Charger',              'White / Black, 1-port GaN', 65_000)
    add(3, 'Chargers', 'Anker 45W USB-C GaN Charger',              'White / Black, 1-port', 85_000)
    add(3, 'Chargers', 'Anker 65W GaN Charger (1 port)',           'White / Black', 110_000)
    add(3, 'Chargers', 'Anker 65W GaN Charger (2 ports, USB-C+A)', 'White / Black, dual port', 125_000)
    add(3, 'Chargers', 'Anker Prime 100W GaN Charger (4 ports)',   'White / Black, 2xUSB-C + 2xUSB-A', 175_000)
    add(3, 'Chargers', 'Anker 736 Nano II 100W GaN',               'Black, 3-port compact', 195_000)
    add(3, 'Chargers', 'Anker PowerPort III 63W Duo',              'White, 2xUSB-C', 115_000)

    add(3, 'Power Banks', 'Anker 321 Power Bank 5,200mAh',     '2x USB-A, compact', 55_000)
    add(3, 'Power Banks', 'Anker PowerCore 10,000mAh',         'USB-A + USB-C, slim', 75_000)
    add(3, 'Power Banks', 'Anker PowerCore Slim 10,000mAh',    'USB-C PD 18W', 80_000)
    add(3, 'Power Banks', 'Anker PowerCore 20,000mAh',         'USB-A + USB-C, high capacity', 115_000)
    add(3, 'Power Banks', 'Anker 523 Power Bank 10,000mAh',    'USB-C PD 30W, fast charge', 95_000)
    add(3, 'Power Banks', 'Anker 737 Power Bank 26,800mAh',    '140W two-way fast charge', 280_000)
    add(3, 'Power Banks', 'Anker MagGo Battery Pack 5,000mAh', 'MagSafe compatible, 7.5W wireless', 135_000)

    add(3, 'Cables', 'Anker USB-C to Lightning 1m (MFi)',  'Nylon braided, Apple certified', 35_000)
    add(3, 'Cables', 'Anker USB-C to Lightning 2m (MFi)',  'Nylon braided, Apple certified', 45_000)
    add(3, 'Cables', 'Anker USB-C to USB-C 1m (60W)',      'Nylon braided', 30_000)
    add(3, 'Cables', 'Anker USB-C to USB-C 2m (60W)',      'Nylon braided', 40_000)
    add(3, 'Cables', 'Anker USB-C to USB-C 1m (240W)',     'For MacBook Pro fast charging', 55_000)
    add(3, 'Cables', 'Anker USB-A to USB-C 1m',            'Nylon braided', 25_000)
    add(3, 'Cables', 'Anker USB-A to Micro-USB 1m',        'Nylon braided', 20_000)

    add(3, 'Earbuds & Headphones', 'Anker Soundcore A3i TWS',             'ANC, Bluetooth 5.2, 30hr total', 80_000)
    add(3, 'Earbuds & Headphones', 'Anker Soundcore Life P2 Mini TWS',    'IPX5, 32hr total battery', 90_000)
    add(3, 'Earbuds & Headphones', 'Anker Soundcore Life P3 TWS',         'ANC, 6-mic, 35hr total', 150_000)
    add(3, 'Earbuds & Headphones', 'Anker Soundcore Liberty 4 NC',        'LDAC, ANC, 28hr total', 230_000)
    add(3, 'Earbuds & Headphones', 'Anker Soundcore Liberty 4 Pro',       'LDAC, ANC, AI ClearVoice, 28hr total', 290_000)
    add(3, 'Earbuds & Headphones', 'Anker Soundcore Life Q30 (Over-ear)', 'ANC, Multipoint, 40hr', 140_000)
    add(3, 'Earbuds & Headphones', 'Anker Soundcore Q45 Headphones',      'ANC, LDAC, 50hr', 185_000)
    add(3, 'Earbuds & Headphones', 'Anker Soundcore Space Q45 Headphones','ANC, 50hr, LDAC', 250_000)

    add(3, 'USB Hubs & Docks', 'Anker 332 USB-A Hub (4-port)',        'USB 3.0, compact', 45_000)
    add(3, 'USB Hubs & Docks', 'Anker 543 USB-C Hub (6-in-1)',        '4K HDMI, 100W PD, USB 3.0', 95_000)
    add(3, 'USB Hubs & Docks', 'Anker 7-in-1 USB-C Hub A8346',        '4K HDMI, SD/TF, USB 3.0, PD', 110_000)
    add(3, 'USB Hubs & Docks', 'Anker 555 USB-C Hub (8-in-1)',        '4K HDMI, 100W PD, 1Gbps Ethernet', 140_000)
    add(3, 'USB Hubs & Docks', 'Anker 575 USB-C Docking Station 13-in-1','Dual 4K HDMI, 85W PD, 1Gbps', 320_000)
    add(3, 'USB Hubs & Docks', 'Anker PowerExpand 12-in-1 USB-C Dock', '4K HDMI, DP, 60W PD, SD/TF', 260_000)

    add(3, 'Charging Stations', 'Anker 313 Wireless Charger Pad 10W',     'Qi compatible', 45_000)
    add(3, 'Charging Stations', 'Anker 633 MagGo Wireless Charger',       'MagSafe, 15W for iPhone', 130_000)
    add(3, 'Charging Stations', 'Anker 544 Wireless Charging Station',    '4-in-1: iPhone + AirPods + Watch + device', 175_000)
    add(3, 'Charging Stations', 'Anker 3-in-1 Cube with MagSafe',         'Foldable, 15W MagSafe + Watch + AirPods', 240_000)

    # ── JBL ───────────────────────────────────────────────────────────
    add(4, 'Bluetooth Speakers', 'JBL GO 3',        'IPX67, 5hr battery, 7 colors', 120_000)
    add(4, 'Bluetooth Speakers', 'JBL GO 4',        'IP67, 7hr battery, USB-C charging', 140_000)
    add(4, 'Bluetooth Speakers', 'JBL Clip 4',      'IP67, 10hr battery, carabiner clip', 175_000)
    add(4, 'Bluetooth Speakers', 'JBL Clip 5',      'IP67, 12hr battery, rotatable carabiner', 200_000)
    add(4, 'Bluetooth Speakers', 'JBL Flip 6',      'IP67, 12hr battery, PartyBoost', 380_000)
    add(4, 'Bluetooth Speakers', 'JBL Flip 7',      'IP68, 12hr battery, AI Sound Boost', 420_000)
    add(4, 'Bluetooth Speakers', 'JBL Charge 5',    'IP67, 20hr battery, power bank function', 530_000)
    add(4, 'Bluetooth Speakers', 'JBL Charge 5 Wi-Fi', 'IP67, Wi-Fi + Bluetooth, 20hr', 650_000)
    add(4, 'Bluetooth Speakers', 'JBL Xtreme 3',    'IP67, 15hr battery, PartyBoost', 890_000)
    add(4, 'Bluetooth Speakers', 'JBL Xtreme 4',    'IP67, 24hr battery, Wi-Fi + BT', 980_000)
    add(4, 'Bluetooth Speakers', 'JBL Boombox 3',   'IP67, 24hr battery, massive sound', 1_450_000)
    add(4, 'Bluetooth Speakers', 'JBL Boombox 3 Wi-Fi', 'IP67, Wi-Fi + BT, 24hr', 1_650_000)
    add(4, 'Bluetooth Speakers', 'JBL Pulse 5',     'IP67, 12hr battery, 360° lightshow', 680_000)

    add(4, 'Earphones', 'JBL Tune 130NC TWS',    'ANC, 40hr total, IPX4', 155_000)
    add(4, 'Earphones', 'JBL Tune 230NC TWS',    'ANC, 40hr total, IPX4', 200_000)
    add(4, 'Earphones', 'JBL Live Free 2 TWS',   'Adaptive ANC, 40hr, IPX5', 260_000)
    add(4, 'Earphones', 'JBL Live Beam 3',        'Adaptive ANC, 48hr, IPX5', 390_000)
    add(4, 'Earphones', 'JBL Tour Pro 2',         'Smart case with display, ANC, 40hr', 480_000)

    add(4, 'Headphones', 'JBL Tune 520BT',         'Wireless on-ear, 57hr battery', 130_000)
    add(4, 'Headphones', 'JBL Tune 770NC',          'ANC, 70hr battery, foldable', 220_000)
    add(4, 'Headphones', 'JBL Live 770NC',          'Adaptive ANC, 65hr, foldable', 310_000)
    add(4, 'Headphones', 'JBL Tour One M2',         'Adaptive ANC, 30hr, premium leather', 520_000)
    add(4, 'Headphones', 'JBL Quantum 350 Wireless','40hr battery, gaming headset', 280_000)
    add(4, 'Headphones', 'JBL Quantum 910 Wireless','Spatial sound, ANC, 34hr, gaming', 580_000)

    add(4, 'Soundbars', 'JBL Bar 300',   '5.0ch, 260W, Dolby Atmos, MultiBeam', 650_000)
    add(4, 'Soundbars', 'JBL Bar 500',   '5.1ch, 295W, Dolby Atmos, detachable surround', 950_000)
    add(4, 'Soundbars', 'JBL Bar 800',   '5.1.2ch, 720W, Dolby Atmos, detachable surround', 1_500_000)
    add(4, 'Soundbars', 'JBL Bar 1000',  '7.1.4ch, 880W, Dolby Atmos, detachable surround + up-firing', 2_200_000)

    # ── Accessories ───────────────────────────────────────────────────
    add(5, 'Cases & Covers', 'iPhone 16 Silicone Case (Apple)',      'MagSafe compatible, various colors', 55_000)
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

    db.commit()


def _seed_categories(db):
    categories = [
        (1, 'MacBook',     'bi-laptop',           1),
        (2, 'iPhone',      'bi-phone',             2),
        (3, 'Anker',       'bi-battery-charging',  3),
        (4, 'JBL',         'bi-speaker',           4),
        (5, 'Accessories', 'bi-bag',               5),
        (6, 'Other',       'bi-tag',               6),
    ]
    for cat_id, name, icon, sort_order in categories:
        db.execute(
            "INSERT OR IGNORE INTO product_categories (id, name, icon, sort_order) VALUES (?,?,?,?)",
            (cat_id, name, icon, sort_order)
        )

    subcats = [
        # MacBook
        (1, 'MacBook Air', 1), (1, 'MacBook Pro', 2), (1, 'Mac Accessories', 3),
        # iPhone
        (2, 'iPhone 16 Series', 1), (2, 'iPhone 15 Series', 2), (2, 'iPhone 14 Series', 3),
        (2, 'iPhone SE', 4), (2, 'iPhone Accessories', 5),
        # Anker
        (3, 'Chargers', 1), (3, 'Power Banks', 2), (3, 'Cables', 3),
        (3, 'Earbuds & Headphones', 4), (3, 'USB Hubs & Docks', 5),
        (3, 'Charging Stations', 6), (3, 'Other Anker', 7),
        # JBL
        (4, 'Bluetooth Speakers', 1), (4, 'Earphones', 2),
        (4, 'Headphones', 3), (4, 'Soundbars', 4),
        # Accessories
        (5, 'Cases & Covers', 1), (5, 'Screen Protectors', 2),
        (5, 'Cables & Adapters', 3), (5, 'Storage & Memory', 4),
        (5, 'Bags & Sleeves', 5), (5, 'Other Accessories', 6),
        # Other
        (6, 'Other', 1),
    ]
    for cat_id, name, sort_order in subcats:
        db.execute(
            "INSERT OR IGNORE INTO product_subcategories (category_id, name, sort_order) VALUES (?,?,?)",
            (cat_id, name, sort_order)
        )

    # Auto-migrate existing products: map brand_category text → category_id
    db.execute("""
        UPDATE products
        SET category_id = (SELECT id FROM product_categories WHERE name = brand_category)
        WHERE category_id IS NULL AND brand_category IS NOT NULL
    """)


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
