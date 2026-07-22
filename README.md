# Sadakalawe Sales Management System

Sales management system for Sadakalawe Enterprises — generates branded invoices, proformas, and delivery notes for both branches.

## First-time setup

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

## Running the app

```bash
venv/bin/python3 app.py
```

Then open **http://localhost:8090** in the browser.

The port is set in `config.py` (`PORT`). It is 8090 rather than the
common 8080 so Sadakalawe never clashes with another app on the same Mac.
Override for one run with `PORT=9000 venv/bin/python3 launcher.py`.

## Default login

| Username | Password | Role |
|---|---|---|
| `admin` | `admin123` | Admin |

**Change this password immediately** in Users → Edit.

## Creating staff accounts

1. Log in as admin
2. Go to Users → New User
3. Assign to their branch (Arusha or Dar es Salaam)
4. Set role to Staff

## Document numbering

| Type | Arusha | Dar es Salaam |
|---|---|---|
| Invoice | `INV-ARU-2026-0001` | `INV-DAR-2026-0001` |
| Proforma | `PRO-ARU-2026-0001` | `PRO-DAR-2026-0001` |
| Delivery Note | `DN-ARU-2026-0001` | `DN-DAR-2026-0001` |

Sequences reset each calendar year.

## Backup

Run manual backups from the Backup page. Point the `backups/` folder to a Google Drive sync folder or copy to USB regularly.

The database file is at `data/sadakalawe.db` — copy this file to back up everything.

## Data location

- Database: `data/sadakalawe.db`
- Backups: `backups/`
- Logo: `static/logo.png`
