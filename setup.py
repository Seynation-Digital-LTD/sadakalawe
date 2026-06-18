"""
py2app setup — builds a fully self-contained Sadakalawe.app bundle.

Usage (only when py2app is installed and fully supported on your macOS):
    pip install py2app
    python setup.py py2app

The simpler approach (no py2app, works on any macOS):
    bash build_app.sh
"""
from setuptools import setup
import os

APP     = ['launcher.py']
VERSION = '1.0.0'

# Include all data files that Flask needs at runtime
DATA_FILES = [
    ('templates',        ['templates']),
    ('static',           ['static']),
    ('models',           ['models']),
    ('routes',           ['routes']),
    ('services',         ['services']),
    ('',                 ['app.py', 'config.py', 'database.py']),
]

OPTIONS = {
    'argv_emulation': False,
    'semi_standalone': False,
    'site_packages':  True,
    'packages': [
        'flask',
        'flask_login',
        'werkzeug',
        'jinja2',
        'click',
        'itsdangerous',
        'markupsafe',
        'reportlab',
        'PIL',
        'apscheduler',
        'openpyxl',
        'qrcode',
        'pytz',
        'six',
        'tzlocal',
        'pkg_resources',
    ],
    'includes': [
        'sqlite3',
        'threading',
        'webbrowser',
        'socket',
        'logging',
        'email',
        'smtplib',
        'ssl',
        'csv',
        'io',
        'json',
        'datetime',
        'decimal',
        'hashlib',
        'uuid',
    ],
    'iconfile': 'static/sadakalawe.icns',
    'plist': {
        'CFBundleName':             'Sadakalawe',
        'CFBundleDisplayName':      'Sadakalawe Sales',
        'CFBundleIdentifier':       'com.sadakalawe.sales',
        'CFBundleVersion':          VERSION,
        'CFBundleShortVersionString': VERSION,
        'CFBundlePackageType':      'APPL',
        'NSHumanReadableCopyright': '© 2026 Sadakalawe Enterprises',
        'LSMinimumSystemVersion':   '12.0',
        'NSHighResolutionCapable':  True,
        'LSUIElement':              False,
        'NSAppTransportSecurity':   {'NSAllowsLocalNetworking': True},
    },
}

setup(
    name    = 'Sadakalawe',
    version = VERSION,
    app     = APP,
    data_files = DATA_FILES,
    options = {'py2app': OPTIONS},
    setup_requires = ['py2app'],
)
