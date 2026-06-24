import os

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

BRAND_CATEGORIES = ['MacBook', 'iPhone', 'Anker', 'JBL', 'Accessories', 'Other']

# Customer VIP tiers — ordered highest to lowest
VIP_TIERS = [
    {'name': 'VIP',    'min_spend': 20_000_000, 'color': '#7c3aed', 'bg': '#ede9fe', 'icon': '👑'},
    {'name': 'Gold',   'min_spend':  5_000_000, 'color': '#b45309', 'bg': '#fef3c7', 'icon': '⭐'},
    {'name': 'Silver', 'min_spend':  1_000_000, 'color': '#475569', 'bg': '#f1f5f9', 'icon': '🥈'},
    {'name': 'Bronze', 'min_spend':          0, 'color': '#92400e', 'bg': '#fdf4dc', 'icon': '🥉'},
]

SECRET_KEY = os.environ.get('SECRET_KEY', 'sadakalawe-2026-change-in-production-xK9mP2qR')
DATABASE = os.path.join(BASE_DIR, 'data', 'sadakalawe.db')
BACKUP_DIR = os.path.join(BASE_DIR, 'backups')

MAIL_SERVER   = os.environ.get('MAIL_SERVER',   'smtp.gmail.com')
MAIL_PORT     = int(os.environ.get('MAIL_PORT',   '465'))
MAIL_USERNAME = os.environ.get('MAIL_USERNAME',  '')
MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD',  '')
MAIL_FROM     = os.environ.get('MAIL_FROM',      '')
