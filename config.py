import os
import secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

BRANCHES = {
    'ARU': {
        'id': 1,
        'name': 'Arusha',
        'short_code': 'ARU',
        'address': 'Bondeni Street, Opposite Mega Complex, Arusha',
    },
    'DAR': {
        'id': 2,
        'name': 'Dar es Salaam',
        'short_code': 'DAR',
        'address': 'Kariakoo, Aggrey Street, Dar es Salaam',
    },
}

COMPANY = {
    'name': 'Sadakalawe Enterprises',
    'tin': '164-334-864',
    'phone': '+255 768 596 006',
    'website': 'www.sadakalawe.com',
    'email': 'info@sadakalawe.com',
    'logo': os.path.join(BASE_DIR, 'static', 'logo.png'),
    'bank_name': 'NMB Bank',
    'bank_account': '42710089645',
}

BRAND = {
    'orange': '#F26522',
    'black': '#000000',
    'white': '#FFFFFF',
    'orange_rgb': (242, 101, 34),
    'light_orange_rgb': (255, 235, 220),
}

VAT_RATE = 18.0

DOC_TYPE_PREFIXES = {
    'invoice': 'INV',
    'proforma': 'PRO',
    'delivery_note': 'DN',
    'financing': 'FIN',
    'tradein': 'TI',
    'repair': 'REP',
    'return': 'RET',
}

DOC_TYPE_LABELS = {
    'invoice': 'Invoice',
    'proforma': 'Proforma Invoice',
    'delivery_note': 'Delivery Note',
}

# How a customer can pay — used on New/Edit Document (value, icon, label)
PAYMENT_METHODS = [
    ('cash',          'bi-cash-coin',   'Cash'),
    ('card',          'bi-credit-card', 'Card / POS'),
    ('mpesa',         'bi-phone',       'M-Pesa'),
    ('airtel_money',  'bi-phone',       'Airtel Money'),
    ('mixx_by_yas',   'bi-phone',       'Mixx by Yas'),
    ('halopesa',      'bi-phone',       'Halopesa'),
    ('bank_transfer', 'bi-bank',        'Bank Transfer'),
    ('other',         'bi-three-dots',  'Other'),
]

BRAND_CATEGORIES = ['MacBook', 'iPhone', 'Anker', 'JBL', 'Accessories', 'Other']

# Customer VIP tiers — ordered highest to lowest
VIP_TIERS = [
    {'name': 'VIP',    'min_spend': 20_000_000, 'color': '#7c3aed', 'bg': '#ede9fe', 'icon': '👑'},
    {'name': 'Gold',   'min_spend':  5_000_000, 'color': '#b45309', 'bg': '#fef3c7', 'icon': '⭐'},
    {'name': 'Silver', 'min_spend':  1_000_000, 'color': '#475569', 'bg': '#f1f5f9', 'icon': '🥈'},
    {'name': 'Bronze', 'min_spend':          0, 'color': '#92400e', 'bg': '#fdf4dc', 'icon': '🥉'},
]

# Port the local web app listens on. 8090 rather than the common 8080 so
# Sadakalawe never collides with another app running on the same Mac.
# Override with:  PORT=9000 venv/bin/python launcher.py
PORT = int(os.environ.get('PORT', '8090'))

def _load_secret_key():
    """The key that signs login cookies. Never hardcode it.

    A hardcoded key in a public repo lets anyone forge an admin session, so:
      1. use $SECRET_KEY (set from .env by systemd on the server), else
      2. fall back to a random key persisted in data/secret_key, which is
         gitignored and generated on first run for local development.
    """
    key = os.environ.get('SECRET_KEY')
    if key:
        return key

    key_file = os.path.join(BASE_DIR, 'data', 'secret_key')
    if os.path.exists(key_file):
        with open(key_file) as fh:
            saved = fh.read().strip()
        if saved:
            return saved

    generated = secrets.token_hex(32)
    os.makedirs(os.path.dirname(key_file), exist_ok=True)
    with open(key_file, 'w') as fh:
        fh.write(generated)
    os.chmod(key_file, 0o600)
    return generated


SECRET_KEY = _load_secret_key()
DATABASE = os.path.join(BASE_DIR, 'data', 'sadakalawe.db')
BACKUP_DIR = os.path.join(BASE_DIR, 'backups')

MAIL_SERVER   = os.environ.get('MAIL_SERVER',   'smtp.gmail.com')
MAIL_PORT     = int(os.environ.get('MAIL_PORT',   '465'))
MAIL_USERNAME = os.environ.get('MAIL_USERNAME',  '')
MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD',  '')
MAIL_FROM     = os.environ.get('MAIL_FROM',      '')


# "What's new" popup — shown once to every user after an update.
# To announce the next update: change 'version' and the items. Everyone sees it once.
WHATS_NEW = {
    'version': '2026-11-25b',
    'title': "What's new in Sadakalawe",
    'items': [
        ('bi-box-arrow-in-down', 'Adding stock — fixed',
         'Everyone can receive stock again: Stock Levels → Add / Adjust Stock → Stock In. It goes into '
         'your branch, and you can sell it straight away. The "Stock Count" box on the product form is '
         'gone — a new product asks for its opening stock and branch instead. Stock typed there before '
         'shows on Stock Levels as "not in any branch": press "Put it in a branch". If a sale says '
         '"Not enough stock", it now tells you where the stock is.'),
        ('bi-box-seam', 'Sales now come out of stock',
         'Pick every item from the product list. You can only sell what your branch has in stock — '
         'the search shows "In stock here". Items typed by hand are no longer accepted.'),
        ('bi-person-vcard', 'Real customer names and phone numbers',
         'Every sale needs a saved customer with first and last name and a phone number. '
         'Names like "Mteja", "Boss" or "Walk in" are not accepted. New customer? Press Save — '
         'if the phone is already saved, that customer is used instead of making a duplicate.'),
        ('bi-pencil-square', 'Edits fix all 3 documents',
         'Editing a sale updates the invoice, proforma and delivery note together and corrects the stock.'),
        ('bi-arrow-return-left', 'Returns go through the invoice',
         'Search the invoice under Returns. You can only return what was sold, and the stock goes back automatically.'),
        ('bi-arrow-left-right', 'Stock in and transfers',
         'Phones need one IMEI per unit when receiving or transferring. Transferred phones can be sold at the new branch.'),
    ],
    'admin_items': [
        ('bi-shield-check', 'Stock permission',
         'Every staff member can receive stock and transfer out of their own branch. The '
         '"Receive stock and adjust quantities" permission is only needed for count corrections '
         '(Adjustment + / −) and for clearing stock that is not in a branch.'),
        ('bi-intersect', 'Duplicate Check',
         'New page in the Admin menu: sales entered twice, sales with two invoices, and duplicate '
         'products you can merge (stock and history move across). Duplicate customers are matched by phone in any format.'),
        ('bi-journal-text', 'Activity Log',
         'New page in the Admin menu: who edited, deleted, converted, returned or removed stock.'),
    ],
}
