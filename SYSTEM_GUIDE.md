# Sadakalawe System Guide
### Complete Technical Documentation — Written for the Owner

> This document explains the entire system from scratch.
> No programming knowledge assumed.
> Read it once to understand. Re-read it when something breaks or when you need to explain it.

---

## Table of Contents

1. [What is Programming?](#1-what-is-programming)
2. [How the Web Works](#2-how-the-web-works)
3. [Python Fundamentals](#3-python-fundamentals)
4. [The Tech Stack — What and Why](#4-the-tech-stack--what-and-why)
5. [The Folder Structure](#5-the-folder-structure)
6. [The Database — How Data is Stored](#6-the-database--how-data-is-stored)
7. [The Request Journey — What Happens on Every Click](#7-the-request-journey--what-happens-on-every-click)
8. [Authentication — How Login Works](#8-authentication--how-login-works)
9. [The Invoice Flow — The Core Feature](#9-the-invoice-flow--the-core-feature)
10. [PDF Generation — How Branded Documents are Made](#10-pdf-generation--how-branded-documents-are-made)
11. [Document Numbering — How INV-ARU-2026-0001 is Generated](#11-document-numbering--how-inv-aru-2026-0001-is-generated)
12. [The Branch System — How Two Shops Work as One](#12-the-branch-system--how-two-shops-work-as-one)
13. [Templates — How HTML Pages are Built](#13-templates--how-html-pages-are-built)
14. [The Backup System](#14-the-backup-system)
15. [The Desktop App Bundle](#15-the-desktop-app-bundle)
16. [Every Package Explained](#16-every-package-explained)
17. [Every File in One Sentence](#17-every-file-in-one-sentence)
18. [The Database Schema — Every Table Explained](#18-the-database-schema--every-table-explained)
19. [Common Patterns Used Everywhere](#19-common-patterns-used-everywhere)
20. [What to Do When Things Break](#20-what-to-do-when-things-break)

---

## 1. What is Programming?

A computer is a machine that follows instructions **exactly and literally**. It does absolutely nothing on its own. Programming is writing those instructions.

The problem: computers only understand electrical signals — represented as 1s and 0s (`10110001 00000001...`). Nobody writes that. So humans invented **programming languages** — human-readable text that gets automatically translated into 1s and 0s.

**Python** is one such language. It reads almost like English:

```python
price = 500000
quantity = 3
total = price * quantity
print(total)   # output: 1500000
```

That is real, working Python code. You are telling the computer:
- Store the number 500000 in a box called `price`
- Store 3 in a box called `quantity`
- Multiply them and store the result in `total`
- Print the result to screen

The word "code" just means "instructions written in a programming language." A "codebase" is the collection of all the files containing code for one project.

---

## 2. How the Web Works

Before understanding the system, you need to understand how a browser and a server talk to each other. This is called the **request-response cycle**.

```
1. Staff opens Chrome and types: localhost:8090
2. Chrome sends a message to the Flask app:
   "GET me the page at / please"
3. Flask receives the message (the REQUEST)
4. Flask runs Python code to prepare the page
5. Flask sends back finished HTML (the RESPONSE)
6. Chrome draws the HTML on screen
```

Every single page load, button click, and form submission follows this same pattern. The browser is always the one that initiates — it ASKS. The Flask app ANSWERS.

### GET vs POST

Every request has a "method" — the type of action being requested.

- **GET** — "I want to SEE something." Visiting a URL, clicking a link.
  - Example: visiting `/customers` to see the customer list.
  - Data travels in the URL: `/customers?branch=ARU`

- **POST** — "I want to SUBMIT something." Clicking Save, Login, Create.
  - Example: submitting the invoice form.
  - Data travels hidden in the request body (not visible in the URL).

### localhost:8090

`localhost` means "this same computer" — not the internet. `8090` is the "port" — think of it as a door number on a building. Your Flask app sits behind door 8090 waiting for requests.

When deployed to a real server on the internet, `localhost` becomes a real domain like `sadakalawe.com`.

---

## 3. Python Fundamentals

You need to understand these building blocks to read any file in the system.

### Variables — Named Storage Boxes

```python
name = "Hassan Ally"     # text — called a STRING (always in quotes)
price = 1500000          # whole number — called an INTEGER
vat_rate = 18.0          # decimal number — called a FLOAT
is_active = True         # yes/no — called a BOOLEAN (True or False)
nothing = None           # empty / no value — called NONE
```

Once you create a variable, you can use its name anywhere instead of typing the value again.

### Lists — Ordered Collections

```python
branches = ["Arusha", "Dar es Salaam", "Nairobi"]

branches[0]    # "Arusha"       ← counting starts at ZERO
branches[1]    # "Dar es Salaam"
branches[-1]   # "Nairobi"      ← -1 means last item

len(branches)  # 3 (number of items)

branches.append("Mombasa")    # add to end
branches[0] = "Arusha (Main)" # change item
```

Square brackets `[]` create and access lists. The number inside brackets is the **index** (position). Always starts at 0, not 1.

### Dictionaries — Labeled Storage

```python
customer = {
    "name": "Hassan Ally",
    "phone": "0712345678",
    "branch_id": 1,
    "is_vip": True
}

customer["name"]          # "Hassan Ally"
customer["branch_id"]     # 1
customer.get("tin", "")   # returns "" if "tin" key doesn't exist (safe access)
```

Dictionaries store key-value pairs. The key (label) is always a string. The value can be anything. Curly brackets `{}` create dictionaries.

In the system, every row from the database comes back as a dictionary-like object. `row["name"]` gets the `name` column from that row.

### Functions — Reusable Named Instructions

```python
def calculate_total(price, quantity, include_vat=False):
    subtotal = price * quantity
    if include_vat:
        return subtotal * 1.18
    return subtotal

# Call the function:
total = calculate_total(500000, 3)           # 1500000
total_with_vat = calculate_total(500000, 3, include_vat=True)  # 1770000
```

`def` = "define a function." The words in the parentheses are **parameters** — inputs the function accepts. `include_vat=False` means that parameter is optional and defaults to False if not provided.

`return` = "send this value back to whoever called me."

### If/Else — Making Decisions

```python
role = "staff"

if role == "admin":
    print("Access to everything")
elif role == "manager":
    print("Access to reports")
else:
    print("Access to your branch only")
```

`==` means "is equal to" (double equals). Single `=` means "assign to."
`!=` means "is NOT equal to."
`>`, `<`, `>=`, `<=` compare numbers.

### Loops — Repeating Instructions

```python
# For loop — repeat for each item in a list
products = ["iPhone 16", "MacBook Air", "AirPods"]
for product in products:
    print(product)
# prints each one

# For loop with index
for i, product in enumerate(products):
    print(f"{i}: {product}")
# 0: iPhone 16
# 1: MacBook Air
# 2: AirPods

# While loop — repeat until condition is false
count = 0
while count < 5:
    print(count)
    count += 1    # same as: count = count + 1
```

### Classes — Blueprints for Objects

```python
class User:
    # __init__ runs when you CREATE an instance
    def __init__(self, username, role, branch_id):
        self.username = username    # store on THIS instance
        self.role = role
        self.branch_id = branch_id
    
    # A method — a function that belongs to the class
    def is_admin(self):
        return self.role == "admin"
    
    def can_see_branch(self, branch_id):
        if self.is_admin():
            return True
        return self.branch_id == branch_id

# Create instances from the blueprint:
user1 = User("amani", "staff", 1)
user2 = User("sey", "admin", None)

user1.is_admin()          # False
user2.is_admin()          # True
user1.can_see_branch(1)   # True
user1.can_see_branch(2)   # False
```

`self` refers to "this specific instance." When you do `self.username = username`, you're saying "store this username ON this particular User object."

### F-Strings — Embedding Values in Text

```python
name = "Hassan"
amount = 1500000
branch = "Arusha"

message = f"Dear {name}, your invoice of TZS {amount:,} from {branch} is ready."
# "Dear Hassan, your invoice of TZS 1,500,000 from Arusha is ready."
```

An f-string starts with `f"`. Anything inside `{}` gets evaluated and inserted. `:,` formats numbers with comma separators. `:04d` pads with leading zeros to 4 digits (`42` → `0042`).

### Imports — Using Other People's Code

```python
import os                          # built-in Python module
from datetime import datetime      # import specific thing from a module
from flask import Flask, request   # import from installed package
from database import query_db      # import from YOUR own file
```

`import` loads code from somewhere else so you can use it. Python has thousands of built-in modules. Packages like Flask, ReportLab are installed separately via `pip install`. Your own files can import from each other.

### Decorators — Labels That Modify Functions

```python
@login_required
def view_customers():
    ...

@app.route('/customers')
def view_customers():
    ...
```

The `@something` above a function is a **decorator**. It wraps the function with extra behavior. `@login_required` means "before running this function, check if the user is logged in — if not, redirect to login." `@app.route('/customers')` means "when someone visits /customers, run this function."

---

## 4. The Tech Stack — What and Why

| Layer | Technology | Why This Choice |
|---|---|---|
| Language | **Python 3** | Owner knows it. Readable. Massive library ecosystem. |
| Web framework | **Flask** | Lightweight, gives full control, easy to understand. Django would be overkill. |
| Database | **SQLite** | Lives in a single file. No server needed. Trivial to backup — copy one file. Perfect for single-shop local use. |
| PDF generation | **ReportLab** | Draw PDFs with exact coordinate control. Perfect branding precision. |
| Frontend HTML | **Jinja2** | Flask's built-in template engine. HTML + Python logic mixed together. |
| Frontend styling | **Bootstrap 5** | Pre-built CSS framework — buttons, tables, forms, responsive layout without writing CSS from scratch. |
| Frontend behaviour | **Vanilla JavaScript** | Small interactive bits (dynamic line items). No React/Vue — kept simple on purpose. |
| Packaging | **py2app** | Wraps everything into a `.app` bundle so staff double-click to start. |
| Scheduling | **APScheduler** | Runs the daily backup job automatically. |

### Why NOT other choices?

- **Not Django** — Django has a built-in admin panel, ORM, and more structure. But it's heavier and harder to customize for specific PDF/document needs.
- **Not MySQL/PostgreSQL** — Those need a separate database server running. SQLite needs nothing extra — it's just a file. Perfect for a shop Mac with no IT team.
- **Not React/Vue** — Those are full JavaScript frameworks. Way more complexity than needed for an internal tool used by a small team.

---

## 5. The Folder Structure

```
sadakalawe/
│
├── app.py              ← ENTRY POINT. Flask starts here. Assembles the whole app.
├── config.py           ← All constants: company info, brand colors, VAT rate.
├── database.py         ← Database connection + entire schema + seed data.
├── manage.py           ← Admin command-line tools (reset data, create users).
├── requirements.txt    ← List of packages to install (pip reads this).
├── .gitignore          ← List of files git should NOT track (DB, venv, secrets).
│
├── models/
│   └── __init__.py     ← The User class. Defines what a logged-in user looks like.
│
├── routes/             ← ONE FILE PER FEATURE. Each handles its URL requests.
│   ├── auth.py         ← /login, /logout, /users, /profile
│   ├── customers.py    ← /customers (list, add, edit, view, search)
│   ├── products.py     ← /products (catalog management)
│   ├── documents.py    ← /documents (create invoice/proforma/delivery note, PDF)
│   ├── reports.py      ← /dashboard, /reports/sales, /reports/stock, /reports/pnl
│   ├── stock.py        ← /stock (movements, transfers, adjustments)
│   ├── credits.py      ← /credits (unpaid sales, debt aging report)
│   ├── financing.py    ← /financing (installment plans)
│   ├── repairs.py      ← /repairs (repair job tracking)
│   ├── tradeins.py     ← /tradeins (device trade-in management)
│   ├── expenses.py     ← /expenses (branch expense recording)
│   ├── cash_recon.py   ← /cash-recon (end-of-day reconciliation)
│   ├── commissions.py  ← /commissions (staff commission tracking)
│   ├── devices.py      ← /devices (IMEI/serial number tracking)
│   ├── returns.py      ← /returns (customer returns)
│   ├── campaigns.py    ← /campaigns (WhatsApp/SMS messaging)
│   ├── upgrade.py      ← /upgrade (device upgrade tracking)
│   ├── settings.py     ← /settings (email config, app settings)
│   ├── backup_routes.py← /backup (manual export triggers)
│   └── import_data.py  ← /import (CSV bulk import)
│
├── services/           ← BUSINESS LOGIC that isn't tied to a specific URL.
│   ├── pdf_generator.py← Draws branded PDFs. The ReportLab artist.
│   ├── numbering.py    ← Generates INV-ARU-2026-0042 style document numbers.
│   ├── email_service.py← Sends emails with PDF attachments via SMTP.
│   ├── backup.py       ← Daily automatic database file copy.
│   └── text_utils.py   ← Small text helpers (truncation, formatting, Swahili).
│
├── templates/          ← HTML FILES. Jinja2 templates sent to browser.
│   ├── base.html       ← MASTER LAYOUT. Navbar, sidebar, footer. All pages extend this.
│   ├── login.html      ← Login page (only page outside base.html)
│   ├── dashboard.html  ← The home dashboard
│   ├── customers/      ← list.html, form.html, view.html
│   ├── products/       ← list.html, form.html
│   ├── documents/      ← new.html, list.html, view.html, result.html, edit.html
│   ├── reports/        ← sales.html, stock.html, pnl.html, debts.html
│   ├── repairs/        ← new.html, list.html, view.html, edit.html
│   └── errors/         ← error.html (shows 404, 500 errors nicely)
│
├── static/             ← FILES SERVED DIRECTLY TO BROWSER. Flask doesn't touch these.
│   ├── css/style.css   ← Custom CSS layered on top of Bootstrap.
│   ├── js/main.js      ← Custom JavaScript running in the browser.
│   ├── logo.png        ← Brand logo — used in UI and embedded in PDFs.
│   └── product_images/ ← Product photo uploads.
│
└── data/
    └── sadakalawe.db   ← THE DATABASE FILE. This is your entire business data.
```

### The Most Important Files

If you only had to know 5 files:

1. **`app.py`** — Where everything connects.
2. **`database.py`** — Where data lives and how you talk to it.
3. **`routes/documents.py`** — The core feature (invoices).
4. **`services/pdf_generator.py`** — What makes the PDFs beautiful.
5. **`templates/base.html`** — The visual shell every page uses.

---

## 6. The Database — How Data is Stored

### What is a Database?

A database is like a very organized spreadsheet system with multiple sheets (called **tables**) that can reference each other.

**A single table looks like this:**

| id | name | phone | branch_id | created_at |
|---|---|---|---|---|
| 1 | Hassan Ally | 0712345678 | 1 | 2026-01-15 |
| 2 | Amina Safari | 0756789012 | 1 | 2026-01-16 |
| 3 | Juma Mnamo | 0787654321 | 2 | 2026-01-20 |

Each **row** is one customer. Each **column** is one piece of information. Every row has an `id` — a unique number the database assigns automatically.

### How Tables Link to Each Other

`branch_id = 1` in the customers table means "this customer belongs to the branch with id=1." You look up id=1 in the branches table to find "Arusha (Bondeni)."

This linking is called a **foreign key**. You store a reference (the ID number) instead of copying the branch name into every customer row. This way, if you rename "Arusha" to "Arusha (Bondeni)", you change it in ONE place and it's updated everywhere.

### SQL — The Language for Talking to Databases

SQL (Structured Query Language) has 4 main commands:

```sql
-- SELECT: Read/get data
SELECT * FROM customers WHERE branch_id = 1 ORDER BY name

-- INSERT: Add new data
INSERT INTO customers (name, phone, branch_id) VALUES ('Hassan', '0712...', 1)

-- UPDATE: Change existing data
UPDATE customers SET phone = '0787654321' WHERE id = 5

-- DELETE: Remove data
DELETE FROM customers WHERE id = 5
```

`*` means "all columns." `WHERE` filters rows. `ORDER BY` sorts results.

### How Python Talks to the Database

```python
# Get all Arusha customers
customers = query_db(
    "SELECT * FROM customers WHERE branch_id = ? ORDER BY name",
    [1]   # the ? gets replaced by 1
)

# customers is now a list of rows:
# [{'id': 1, 'name': 'Hassan Ally', 'phone': '0712...', ...},
#  {'id': 2, 'name': 'Amina Safari', ...}]

# Access individual fields:
first_customer = customers[0]
print(first_customer['name'])    # "Hassan Ally"

# Get one specific customer
customer = query_db(
    "SELECT * FROM customers WHERE id = ?",
    [customer_id],
    one=True    # return just the first row, not a list
)

# Save new data
new_id = execute_db(
    "INSERT INTO customers (name, phone, branch_id) VALUES (?, ?, ?)",
    ['Hassan Ally', '0712345678', 1]
)
# new_id is the automatically assigned ID for this new customer
```

### Why `?` Placeholders Matter (SQL Injection)

**WRONG (dangerous):**
```python
name = request.form['name']  # what if user types: '; DROP TABLE customers; --
query = "SELECT * FROM customers WHERE name = '" + name + "'"
# This would delete your entire customers table!
```

**RIGHT (safe):**
```python
name = request.form['name']
customer = query_db("SELECT * FROM customers WHERE name = ?", [name])
# The ? is treated as DATA, never as SQL code. Completely safe.
```

This attack (injecting SQL through user input) is called **SQL injection** and is one of the most common ways databases get destroyed.

### WAL Mode — Surviving Power Cuts

```python
g.db.execute("PRAGMA journal_mode=WAL")
```

**WAL = Write-Ahead Logging.**

Without WAL, when saving data:
1. SQLite opens the database file
2. Writes the new data directly into it
3. If power dies mid-write → FILE IS CORRUPTED → DATA LOST

With WAL:
1. SQLite writes new data to a separate LOG FILE first
2. Only after that succeeds → updates the main database file
3. If power dies at step 1 → main file is untouched, log is incomplete → safe
4. If power dies at step 2 → log file has complete data → SQLite recovers on next start

**The three SQLite files you'll see:**
- `sadakalawe.db` — the main database
- `sadakalawe.db-wal` — the write-ahead log (normal — means WAL is working)
- `sadakalawe.db-shm` — shared memory file (normal — ignore it)

Never manually delete the `-wal` file while the app is running — that would corrupt the database.

### The Connection Pattern — `get_db()`

```python
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row
    return g.db
```

`g` is Flask's **per-request storage** — a container that lives for exactly one request then disappears. It's not your app's memory (which persists). It's scratch paper for one request.

`g.db` means: "store the database connection on g." First call to `get_db()` creates the connection. Subsequent calls return the same one. When the request ends, Flask automatically calls `close_db()` which closes the connection.

Why do this instead of one global connection? Because multiple staff can be using the app simultaneously. Each request gets its own isolated connection, so they don't interfere with each other.

`row_factory = sqlite3.Row` makes rows behave like dictionaries: `row['name']` instead of `row[0]`.

---

## 7. The Request Journey — What Happens on Every Click

Let's trace a staff member creating an invoice, click by click.

### Step 1: Staff visits `/documents/new`

```
Chrome → GET /documents/new → Flask
```

```python
# routes/documents.py
@bp.route('/documents/new', methods=['GET', 'POST'])
@login_required
def new_document():
    if request.method == 'GET':
        customers = query_db(
            "SELECT * FROM customers WHERE branch_id=? ORDER BY name",
            [current_user.branch_id]
        )
        products = query_db("SELECT * FROM products WHERE is_active=1")
        
        return render_template('documents/new.html',
                               customers=customers,
                               products=products)
```

Flask:
1. Sees `/documents/new` → runs `new_document()`
2. `@login_required` checks session — if not logged in, redirect to login
3. Queries database for customers and products
4. Fills in the HTML template with that data
5. Sends finished HTML back to Chrome

Chrome draws the form.

### Step 2: Staff fills form and clicks "Create Invoice"

```
Chrome → POST /documents/new → Flask
         (with all the form data hidden in the request body)
```

```python
    if request.method == 'POST':
        # Read what the form sent
        doc_type    = request.form['doc_type']       # 'invoice'
        customer_id = request.form.get('customer_id') # '5' (as text)
        is_vat      = 'is_vat' in request.form       # True/False (checkbox)
        
        # Multiple line items come as lists
        descriptions = request.form.getlist('description[]')
        quantities   = request.form.getlist('quantity[]')
        prices       = request.form.getlist('unit_price[]')
        
        # Calculate
        subtotal = 0
        for qty, price in zip(quantities, prices):
            subtotal += float(qty) * float(price)
        
        vat_amount = subtotal * 0.18 if is_vat else 0
        total = subtotal + vat_amount
        
        # Generate document number
        doc_number = get_next_number(current_user.branch_id, doc_type)
        # → "INV-ARU-2026-0042"
        
        # Save the document
        doc_id = execute_db("""
            INSERT INTO documents 
            (doc_number, doc_type, branch_id, customer_id, created_by, 
             subtotal, vat_amount, total, is_vat)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, [doc_number, doc_type, current_user.branch_id, customer_id,
              current_user.id, subtotal, vat_amount, total, 1 if is_vat else 0])
        
        # Save each line item
        for desc, qty, price in zip(descriptions, quantities, prices):
            execute_db("""
                INSERT INTO document_items 
                (document_id, description, quantity, unit_price, line_total)
                VALUES (?,?,?,?,?)
            """, [doc_id, desc, qty, price, float(qty)*float(price)])
        
        # Deduct stock
        # Generate PDF
        # Send to result page
        return redirect(url_for('documents.view_document', doc_id=doc_id))
```

### Step 3: Staff sees the result page

Flask sends them to `/documents/42` (the new document's ID) where they can:
- Download the PDF
- Email it to the customer
- Print it

### The Nonce / Idempotency — Preventing Duplicate Invoices

When the form loads, a hidden field is generated:
```html
<input type="hidden" name="batch_id" value="a7f3b291">
```

`a7f3b291` is a **nonce** — a random string generated once. When the form is submitted:
1. Flask checks: has this `batch_id` been used before?
2. If yes → reject (duplicate submission) → redirect to existing document
3. If no → process, store the `batch_id` in the document record

This prevents the common problem where staff clicks Submit twice (slow internet, impatience) and two identical invoices get created.

---

## 8. Authentication — How Login Works

### The Login Process

```python
# routes/auth.py
@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        # Find the user in the database
        user_row = query_db(
            "SELECT * FROM users WHERE username=? AND is_active=1",
            [username], one=True
        )
        
        if not user_row:
            flash('Username not found.', 'danger')
            return redirect(url_for('auth.login'))
        
        # Check password
        if not check_password_hash(user_row['password_hash'], password):
            flash('Wrong password.', 'danger')
            return redirect(url_for('auth.login'))
        
        # Success — log in
        login_user(User(user_row), remember=True)
        return redirect(url_for('reports.dashboard'))
```

### Why Passwords are Hashed

Passwords are NEVER stored as plain text. Storing `password123` in the database is a catastrophic security failure — if anyone gets the database file, they have everyone's passwords.

Instead:
```python
# When CREATING a user:
generate_password_hash('admin123')
# → "pbkdf2:sha256:600000$xK9mP2q...very long scrambled string..."

# When CHECKING a login:
check_password_hash(stored_hash, 'admin123')
# → True (if the password matches the hash)
# → False (if wrong password)
```

Hashing is **one-way** — you can turn `admin123` into the hash, but you cannot turn the hash back into `admin123`. Even if someone steals the database file, they only get useless scrambled strings. They'd have to try billions of password guesses to crack even one.

### Sessions — How Flask Remembers You Between Requests

HTTP is **stateless** — every request is isolated, like making a phone call with someone who has no memory. Flask uses a **session** to remember you across requests.

When you log in:
1. Flask creates a session cookie (a small encrypted token)
2. The cookie is stored in your browser
3. Every subsequent request sends the cookie automatically
4. Flask decrypts the cookie, sees your user ID, loads your user

The `SECRET_KEY` in config is used to encrypt/decrypt the cookie. That's why it must be kept secret — if someone knows your SECRET_KEY, they can forge session cookies and log in as anyone.

### Single-Session Security

```python
# When logging in, generate a random token
import secrets
token = secrets.token_hex(32)

# Store it in the database and in the session
execute_db("UPDATE users SET session_token=? WHERE id=?", [token, user.id])
session['session_token'] = token

# On every request, verify they match:
if user.session_token != session.get('session_token'):
    logout_user()   # Session invalid — log them out
```

If someone logs in from another device, a new token is generated. The old session (other device) no longer matches and gets logged out. One active session per user at all times.

### Roles and Permissions

```python
# In any route that needs admin:
if current_user.role != 'admin':
    abort(403)   # 403 = "Forbidden"

# In templates:
{% if current_user.role == 'admin' %}
    <a href="/users">Manage Staff</a>
{% endif %}
```

Roles in the system:
- `admin` — the owner. Sees everything across both branches.
- `manager` — branch manager. Sees their branch data + reports.
- `staff` — sales staff. Creates documents for their branch.

---

## 9. The Invoice Flow — The Core Feature

This is the most important feature. Understanding this means understanding the system.

### The Data Model (What Gets Saved)

**One invoice = one `documents` row + multiple `document_items` rows**

```
documents table:
┌────────────────────────────────────────────────────┐
│ id: 42                                             │
│ doc_number: INV-ARU-2026-0042                      │
│ doc_type: invoice                                  │
│ branch_id: 1 (Arusha)                             │
│ customer_id: 5 (Hassan Ally)                       │
│ created_by: 3 (Amani - staff member)               │
│ subtotal: 2980000                                  │
│ vat_amount: 0                                      │
│ total: 2980000                                     │
│ payment_status: paid                               │
│ created_at: 2026-06-15 14:23:11                    │
└────────────────────────────────────────────────────┘

document_items table (3 rows, all with document_id = 42):
┌─────────────────────────────────────────────────┐
│ id: 101 | document_id: 42 | description: iPhone 16 128GB  │
│ quantity: 1 | unit_price: 2200000 | line_total: 2200000   │
├─────────────────────────────────────────────────┤
│ id: 102 | document_id: 42 | description: AirPods Pro      │
│ quantity: 1 | unit_price: 580000 | line_total: 580000      │
├─────────────────────────────────────────────────┤
│ id: 103 | document_id: 42 | description: Tempered Glass   │
│ quantity: 2 | unit_price: 14000 | line_total: 28000        │
└─────────────────────────────────────────────────┘
```

### What Happens to Stock

```python
# For each product in the sale:
execute_db("""
    UPDATE product_stock 
    SET quantity = quantity - ?
    WHERE product_id = ? AND branch_id = ?
""", [quantity_sold, product_id, branch_id])
```

Stock is tracked per product per branch. Selling 1 iPhone in Arusha deducts from Arusha's stock only — Dar es Salaam stock is unaffected.

### IMEI Tracking for Phones

When selling a phone (any product in the Smartphones category), an extra record is created:

```python
execute_db("""
    INSERT INTO device_sales 
    (document_id, product_id, customer_id, imei, color, storage)
    VALUES (?,?,?,?,?,?)
""", [doc_id, product_id, customer_id, imei_number, color, storage])

# The IMEI status is also updated:
execute_db("""
    UPDATE device_imeis SET status = 'sold'
    WHERE imei = ?
""", [imei_number])
```

This is how you can later trace "who bought iPhone with IMEI 354012345678901" — critical for warranty and fraud prevention.

### EFD Toggle — VAT or No VAT

The simple toggle on the form:
```html
<input type="checkbox" name="is_vat" id="is_vat">
```

In Python:
```python
is_vat = 'is_vat' in request.form   # True if checkbox was checked

if is_vat:
    vat_amount = subtotal * (vat_rate / 100)  # 18%
    # PDF will show VAT breakdown
    # A field appears to enter the EFD receipt reference number
else:
    vat_amount = 0
    # PDF shows no VAT — clean standard invoice
```

---

## 10. PDF Generation — How Branded Documents are Made

`services/pdf_generator.py` uses **ReportLab Canvas** — think of it as a robot painter that draws on a blank A4 page following your precise instructions.

### The Coordinate System

```
(0, 842)                        (595, 842)
┌─────────────────────────────────────┐  ← Top of A4 page
│                                     │
│    A4 page = 595 × 842 points       │
│    72 points = 1 inch               │
│                                     │
│                                     │
│                                     │
└─────────────────────────────────────┘  ← Bottom of A4 page
(0, 0)                           (595, 0)
```

**Origin (0,0) is BOTTOM-LEFT.** Y increases upward. So the top of the page is `y = 842`, not `y = 0`. This catches everyone out the first time.

```python
# To draw something 30 points from the top:
y_position = 842 - 30   # = 812
c.drawString(50, 812, "INVOICE")
```

### How a PDF is Built

```python
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from io import BytesIO

def generate_invoice_pdf(doc_id):
    # Load all the data
    doc      = query_db("SELECT * FROM documents WHERE id=?", [doc_id], one=True)
    items    = query_db("SELECT * FROM document_items WHERE document_id=?", [doc_id])
    customer = query_db("SELECT * FROM customers WHERE id=?", [doc['customer_id']], one=True)
    
    # Create a buffer — like a fake file in RAM (memory)
    buffer = BytesIO()
    
    # Create the canvas (blank A4 page)
    width, height = A4    # width=595, height=842
    c = canvas.Canvas(buffer, pagesize=A4)
    
    # ── HEADER BAND ──────────────────────────────────
    # Draw filled orange rectangle: x=0, y=762, w=595, h=80
    c.setFillColorRGB(0.95, 0.40, 0.13)   # orange #F26522 → RGB(242,101,34) → (0.95,0.40,0.13)
    c.rect(0, height-80, width, 80, fill=1, stroke=0)
    
    # Place logo in top-left of band
    c.drawImage('static/logo.png', 20, height-70, width=60, height=50, mask='auto')
    
    # Company name in white
    c.setFillColorRGB(1, 1, 1)    # white
    c.setFont("Helvetica-Bold", 16)
    c.drawString(90, height-40, "SADAKALAWE ENTERPRISES")
    
    # ── DOCUMENT TYPE (right side) ────────────────────
    c.setFillColorRGB(0, 0, 0)    # black
    c.setFont("Helvetica-Bold", 28)
    c.drawRightString(width-30, height-50, "INVOICE")
    
    # ── DOCUMENT META ──────────────────────────────────
    c.setFont("Helvetica", 10)
    c.drawString(30, height-110, f"Invoice No: {doc['doc_number']}")
    c.drawString(30, height-125, f"Date: {doc['created_at'][:10]}")
    
    # ── CUSTOMER INFO ──────────────────────────────────
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30, height-155, "BILL TO:")
    c.setFont("Helvetica", 10)
    c.drawString(30, height-170, customer['name'])
    c.drawString(30, height-183, customer['phone'] or '')
    
    # ── LINE ITEMS TABLE ───────────────────────────────
    y = height - 230   # starting y position for first row
    
    # Table header
    c.setFillColorRGB(0.95, 0.40, 0.13)   # orange header row
    c.rect(30, y-5, width-60, 20, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(35, y, "DESCRIPTION")
    c.drawRightString(width-35, y, "AMOUNT (TZS)")
    
    y -= 25   # move down past header
    
    # One row per item
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 9)
    for item in items:
        c.drawString(35, y, item['description'])
        c.drawString(250, y, f"Qty: {item['quantity']}")
        c.drawRightString(width-35, y, f"{item['line_total']:,.0f}")
        y -= 18   # move down for next row
    
    # ── TOTALS ─────────────────────────────────────────
    y -= 10   # small gap
    c.line(30, y, width-30, y)   # horizontal line
    y -= 15
    
    if doc['is_vat']:
        c.drawString(350, y, "Subtotal:")
        c.drawRightString(width-35, y, f"{doc['subtotal']:,.0f}")
        y -= 15
        c.drawString(350, y, "VAT (18%):")
        c.drawRightString(width-35, y, f"{doc['vat_amount']:,.0f}")
        y -= 15
    
    c.setFont("Helvetica-Bold", 11)
    c.drawString(350, y, "TOTAL TZS:")
    c.drawRightString(width-35, y, f"{doc['total']:,.0f}")
    
    # ── FOOTER ─────────────────────────────────────────
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(0.5, 0.5, 0.5)   # grey
    c.drawCentredString(width/2, 30, "Thank you for your business | sadakalawe.com | +255 768 596 006")
    
    # Finalize the PDF
    c.save()
    
    # Return the raw bytes of the PDF
    return buffer.getvalue()
```

### How the PDF Gets to the Browser

```python
from flask import Response

@bp.route('/documents/<int:doc_id>/pdf')
@login_required
def download_pdf(doc_id):
    pdf_bytes = generate_invoice_pdf(doc_id)
    
    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={'Content-Disposition': 'attachment; filename=invoice-42.pdf'}
    )
```

`Content-Disposition: attachment` tells the browser "download this file" instead of displaying it. Change to `inline` to display in the browser instead of downloading.

---

## 11. Document Numbering — How INV-ARU-2026-0001 is Generated

`services/numbering.py` — this needs to be **atomic** (thread-safe), meaning if two staff create documents at the exact same moment, they cannot get the same number.

### The `doc_sequence` Table

```
branch_id | doc_type | year | last_sequence
    1     | invoice  | 2026 | 41
    1     | proforma | 2026 | 7
    2     | invoice  | 2026 | 18
```

One row per (branch, document type, year) combination. Resets each calendar year.

### The Atomic Increment

```python
def get_next_number(branch_id, doc_type):
    year = datetime.now().year
    prefix = DOC_TYPE_PREFIXES[doc_type]   # 'INV', 'PRO', 'DN', etc.
    
    # Get the branch short code
    branch = query_db("SELECT short_code FROM branches WHERE id=?", [branch_id], one=True)
    code = branch['short_code']   # 'ARU' or 'DAR'
    
    db = get_db()
    
    # UPSERT: Create the row if it doesn't exist (first document of year),
    # or increment if it does — in ONE database operation
    db.execute("""
        INSERT INTO doc_sequence (branch_id, doc_type, year, last_sequence)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(branch_id, doc_type, year) 
        DO UPDATE SET last_sequence = last_sequence + 1
    """, [branch_id, doc_type, year])
    
    # Read the new sequence number
    row = db.execute("""
        SELECT last_sequence FROM doc_sequence
        WHERE branch_id=? AND doc_type=? AND year=?
    """, [branch_id, doc_type, year]).fetchone()
    
    seq = row[0]   # e.g. 42
    
    db.commit()
    
    return f"{prefix}-{code}-{year}-{seq:04d}"
    # → "INV-ARU-2026-0042"
```

**Why is the `ON CONFLICT DO UPDATE` atomic?**

SQLite (and PostgreSQL) handle `INSERT OR UPDATE` as a single locked operation. The database guarantees only one process can increment the sequence at any time. Two simultaneous invoice creations will queue up — one gets 42, the other gets 43. Never the same number.

---

## 12. The Branch System — How Two Shops Work as One

Every important table has `branch_id`:

```sql
customers.branch_id    -- which branch this customer belongs to
documents.branch_id    -- which branch issued this document
product_stock.branch_id -- stock level at this specific branch
users.branch_id        -- which branch this staff member works at
```

### Branch Scoping in Routes

```python
# Staff only see their own branch:
if current_user.role == 'admin':
    customers = query_db("SELECT * FROM customers ORDER BY name")
else:
    customers = query_db(
        "SELECT * FROM customers WHERE branch_id=? ORDER BY name",
        [current_user.branch_id]
    )
```

### Product Stock is Per-Branch

The `product_stock` table is a **junction table** — it connects products to branches with a quantity:

```
product_id | branch_id | quantity
    5      |     1     |    3       ← 3 iPhone 16 in Arusha
    5      |     2     |    1       ← 1 iPhone 16 in Dar es Salaam
    5      |     3     |    0       ← 0 in Arusha Tawi 2
```

When Arusha sells an iPhone, only the `branch_id=1` row decreases. Dar es Salaam is unaffected.

To transfer stock between branches, a `stock_movements` record is created (OUT from source, IN to destination).

---

## 13. Templates — How HTML Pages are Built

### What is HTML?

HTML is the language browsers understand. It describes the structure of a page:

```html
<h1>Big heading</h1>
<p>A paragraph of text.</p>
<a href="/customers">Click here to go to customers</a>
<img src="/static/logo.png" alt="Logo">

<table>
    <tr>
        <td>Hassan</td>
        <td>0712345678</td>
    </tr>
</table>
```

Tags like `<h1>`, `<p>`, `<a>` are the building blocks. The browser interprets these and draws the visual result.

### Jinja2 — HTML + Python Logic

Jinja2 adds Python-like logic to HTML:

```html
<!-- Variable output -->
<h2>Welcome, {{ current_user.full_name }}</h2>
<p>Branch: {{ current_user.branch_id }}</p>

<!-- If/else -->
{% if current_user.role == 'admin' %}
    <a href="/users">Manage Staff</a>
{% endif %}

<!-- Loop -->
<table>
    {% for customer in customers %}
    <tr>
        <td>{{ customer['name'] }}</td>
        <td>{{ customer['phone'] or 'No phone' }}</td>
        <td>{{ customer['created_at'][:10] }}</td>   <!-- first 10 chars = date only -->
    </tr>
    {% empty %}
    <tr><td colspan="3">No customers found.</td></tr>
    {% endfor %}
</table>

<!-- Filter — format numbers -->
TZS {{ total | int | format_number }}
```

`{{ }}` = output a value. `{% %}` = logic (if, for, etc).

### Template Inheritance — The `base.html` Pattern

**base.html** defines the outer shell:

```html
<!DOCTYPE html>
<html>
<head>
    <title>Sadakalawe — {% block title %}{% endblock %}</title>
    <link href="/static/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    <!-- Navbar -->
    <nav class="navbar">
        <span>{{ current_user.full_name }}</span>
        <a href="/logout">Logout</a>
    </nav>
    
    <!-- Main content slot -->
    <div class="container-fluid">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% for category, message in messages %}
            <div class="alert alert-{{ category }}">{{ message }}</div>
            {% endfor %}
        {% endwith %}
        
        {% block content %}
        <!-- Each page fills this in -->
        {% endblock %}
    </div>
    
    <script src="/static/js/main.js"></script>
</body>
</html>
```

**customers/list.html** fills in the slot:

```html
{% extends 'base.html' %}

{% block title %}Customers{% endblock %}

{% block content %}
<div class="d-flex justify-content-between">
    <h1>Customers</h1>
    <a href="/customers/new" class="btn btn-primary">+ Add Customer</a>
</div>

<table class="table">
    {% for c in customers %}
    <tr>
        <td>{{ c['name'] }}</td>
        <td>{{ c['phone'] }}</td>
        <td><a href="/customers/{{ c['id'] }}">View</a></td>
    </tr>
    {% endfor %}
</table>
{% endblock %}
```

`{% extends 'base.html' %}` says: "inherit the base layout, I'm just filling in the content slot." The navbar, CSS, JS — all come from base.html automatically.

### Flashed Messages

```python
# In a route:
flash('Customer saved successfully!', 'success')
return redirect(url_for('customers.list_customers'))
```

`flash()` stores a temporary message for ONE request. After the redirect, base.html picks it up:
```html
{% for category, message in get_flashed_messages(with_categories=true) %}
<div class="alert alert-{{ category }}">{{ message }}</div>
{% endfor %}
```

Categories: `success` (green), `danger` (red), `warning` (yellow), `info` (blue). These are Bootstrap CSS classes.

---

## 14. The Backup System

`services/backup.py` + APScheduler.

### Automatic Daily Backup

```python
from apscheduler.schedulers.background import BackgroundScheduler
import shutil
from datetime import datetime

def start_scheduler(app):
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=lambda: daily_backup(app),
        trigger='cron',
        hour=2,     # 2:00 AM every night
        minute=0
    )
    scheduler.start()

def daily_backup(app):
    with app.app_context():
        today = datetime.now().strftime('%Y-%m-%d')
        src = 'data/sadakalawe.db'
        dst = f'backups/sadakalawe-{today}.db'
        shutil.copy2(src, dst)
        # Also clean up backups older than 30 days
```

`BackgroundScheduler` runs in a separate thread — Python's way of doing two things simultaneously. The scheduler sits in the background counting time, the Flask app handles requests normally, and at 2am the backup function runs without interrupting anything.

### What to Actually Back Up

The `backups/` folder contains dated copies of the database file. To fully recover from a computer failure:
1. Install Python + requirements on a new Mac
2. Copy the project files
3. Copy the latest backup file to `data/sadakalawe.db`
4. Run the app

That's it. The entire business is in that one `.db` file.

### Manual Backup

The Backup page (`/backup`) has a button that runs the backup immediately and also exports all data to CSV/Excel files — useful for sharing data with accountants, importing to other systems, or having a human-readable copy.

---

## 15. The Desktop App Bundle

`Sadakalawe.app` is a **macOS application bundle** — a special folder that macOS disguises as an app icon. Double-clicking it runs code.

```
Sadakalawe.app/
└── Contents/
    ├── MacOS/
    │   └── Sadakalawe    ← compiled executable
    └── Resources/
        └── Sadakalawe.icns  ← the app icon (the orange S logo)
```

### How It Was Built

`py2app` (defined in `setup.py`) packages the entire Python environment:
- Your code
- Python itself
- All installed packages (Flask, ReportLab, etc.)
- The database

Into a single `.app` folder that runs on any Mac without Python installed.

### `launcher.py` — What Runs When Staff Double-Click

```python
import subprocess
import webbrowser
import time
import sys
import os

def main():
    # Start Flask server in background
    server = subprocess.Popen(
        [sys.executable, 'app.py'],
        cwd=os.path.dirname(__file__)
    )
    
    # Wait for it to be ready
    time.sleep(2)
    
    # Open browser automatically
    webbrowser.open('http://localhost:8090')
    
    # Keep running until the user quits the app
    server.wait()

main()
```

From staff's perspective: they double-click the orange icon, a browser window opens, they're in. No terminal, no Python, no configuration. It just works.

---

## 16. Every Package Explained

Packages are code written by other developers that you install and reuse. They live in `venv/lib/python3.9/site-packages/` and are listed in `requirements.txt`.

### Flask `Flask==3.0.3`

The web framework. Does:
- URL routing (`@app.route`)
- Request/response handling (`request.form`, `return Response(...)`)
- Template rendering (`render_template()`)
- Session management (cookies)
- Blueprint system (organizing routes into files)

Without Flask you'd need thousands of lines of code just to receive a web request.

### Flask-Login `Flask-Login==0.6.3`

Handles user sessions. Does:
- `@login_required` decorator
- `current_user` object available everywhere
- `login_user()` / `logout_user()` functions
- "Remember me" functionality
- Redirecting to login when not authenticated

### Werkzeug `Werkzeug==3.0.3`

Flask is built on top of Werkzeug. You use two functions from it directly:
- `generate_password_hash('password')` → scrambled hash
- `check_password_hash(hash, 'password')` → True/False

Also handles HTTP utilities, file uploads, and more under the hood.

### ReportLab `reportlab==4.2.2`

PDF generation engine. Provides:
- `Canvas` — blank page you draw on
- `drawString(x, y, text)` — place text
- `rect(x, y, w, h, fill=1)` — draw rectangle
- `drawImage(path, x, y, w, h)` — embed image
- `setFont(name, size)` — choose font
- `setFillColorRGB(r, g, b)` — set color
- `save()` — finalize the PDF

### Pillow `Pillow==10.4.0`

Image processing library. ReportLab uses it internally to:
- Open and decode `logo.png`
- Resize it for embedding in PDFs
- Handle PNG transparency (`mask='auto'`)

You rarely call Pillow directly — it works in the background when ReportLab processes images.

### APScheduler `APScheduler==3.10.4`

Task scheduler. Runs Python functions on a time-based schedule. Used for:
- Daily database backup at 2am
- Any future scheduled job (low stock alerts, etc.)

`BackgroundScheduler` = runs in a separate thread, doesn't block the web app.

### pypdf `pypdf>=4.0.0`

Reads existing PDF files. Used when:
- Merging PDFs (e.g., batch printing)
- Reading/extracting content from uploaded PDFs

### openpyxl `openpyxl>=3.1.0`

Creates and reads Excel (`.xlsx`) files. Used for:
- Exporting sales reports to Excel
- Importing product/customer data from Excel files

### qrcode `qrcode[pil]>=7.4.2`

Generates QR codes as images. Used for:
- QR code on documents linking to the digital version
- Quick customer lookup by scanning

---

## 17. Every File in One Sentence

| File | Purpose |
|---|---|
| `app.py` | Creates the Flask app, connects all blueprints, registers error handlers, starts the scheduler |
| `config.py` | All constants — company details, brand colors, VAT rate, document prefixes |
| `database.py` | Opens the SQLite connection, defines all 25+ tables, seeds initial data, provides `query_db` and `execute_db` |
| `models/__init__.py` | The `User` class — tells Flask-Login what a logged-in user looks like and how to load one from the database |
| `routes/auth.py` | Login, logout, user list, create user, edit user, change password |
| `routes/customers.py` | List, search, add, edit, view customer profile and their full purchase history |
| `routes/products.py` | Product catalog — list, add, edit, deactivate, manage categories/subcategories |
| `routes/documents.py` | Create/view/edit Invoice/Proforma/Delivery Note, generate PDF, email, download |
| `routes/reports.py` | Dashboard, sales report, stock report, P&L, commissions summary |
| `routes/stock.py` | Record stock arrivals, adjust quantities, transfer between branches, view movement history |
| `routes/credits.py` | View unpaid/partial sales, debt aging report, record payment on credit sale |
| `routes/financing.py` | Create installment plans, track payments, view active/overdue plans |
| `routes/repairs.py` | Log repair jobs, update status, link to device records, generate repair invoices |
| `routes/tradeins.py` | Accept device trade-ins, assess value, link to sale, track disposition |
| `routes/expenses.py` | Record branch expenses, view expense history by category |
| `routes/cash_recon.py` | End-of-day cash counting, compare against system sales, record discrepancies |
| `routes/commissions.py` | View staff sales performance, calculate commissions by period |
| `routes/devices.py` | Browse device sales by IMEI, search serial numbers, view device history |
| `routes/returns.py` | Process customer returns, issue refunds or exchanges, restore stock |
| `routes/campaigns.py` | Send WhatsApp/SMS messages to customers (upgrade prompts, retention) |
| `routes/upgrade.py` | Track device upgrade history — what customers traded in and upgraded to |
| `routes/settings.py` | Configure email server, VAT rate, backup folder, app-wide settings stored in `app_settings` table |
| `routes/backup_routes.py` | Trigger manual backup, export all data to CSV/Excel |
| `routes/import_data.py` | Bulk import customers or products from a CSV file |
| `services/pdf_generator.py` | Draws branded A4 PDFs using ReportLab — invoices, proformas, delivery notes, repair receipts |
| `services/numbering.py` | Generates the next document number atomically — `INV-ARU-2026-0042` |
| `services/email_service.py` | Sends email with PDF attachment using SMTP (Gmail or any mail server) |
| `services/backup.py` | Daily automatic database file copy + weekly snapshot retention |
| `services/text_utils.py` | Text helpers — truncate long names, format currencies, Swahili message templates |
| `templates/base.html` | Master HTML layout — navbar, sidebar, footer, flash messages, Bootstrap CSS/JS |
| `static/logo.png` | The brand logo — used in the UI and embedded in every PDF |
| `static/css/style.css` | Custom CSS overrides and additions on top of Bootstrap |
| `static/js/main.js` | Browser-side JavaScript — dynamic invoice line items, search autocomplete, form helpers |
| `manage.py` | Command-line admin tools: `python manage.py reset` to clear data, `python manage.py adduser` to create staff |

---

## 18. The Database Schema — Every Table Explained

### Core Tables

**`branches`** — The two shops
```
id | name            | short_code | address
1  | Arusha (Bondeni)| ARU        | Bondeni Street...
2  | Dar es Salaam   | DAR        | Kariakoo...
3  | Arusha Tawi 2   | AR2        | TBD
```

**`users`** — Staff accounts
```
id | username | password_hash      | full_name   | role  | branch_id | is_active
1  | admin    | pbkdf2:sha256:...  | Sey         | admin | NULL      | 1
2  | amani    | pbkdf2:sha256:...  | Amani Juma  | staff | 1         | 1
```
`branch_id = NULL` for admin means no branch restriction.

**`customers`** — Customer records
```
id | name         | phone      | tin         | branch_id
1  | Hassan Ally  | 0712345678 | 123-456-789 | 1
```

**`products`** — Product catalog
```
id | brand_category | model              | price    | stock_count | sku
1  | iPhone         | iPhone 16 128GB    | 2200000  | 5           | SDA-027
```

**`product_stock`** — Per-branch stock quantities (junction table)
```
product_id | branch_id | quantity
1          | 1         | 3         ← 3 units in Arusha
1          | 2         | 1         ← 1 unit in Dar
```

### Document Tables

**`documents`** — Each invoice/proforma/delivery note
```
id | doc_number        | doc_type | branch_id | customer_id | total   | payment_status
1  | INV-ARU-2026-0001 | invoice  | 1         | 5           | 2980000 | paid
```

**`document_items`** — Line items within each document
```
id | document_id | description      | quantity | unit_price | line_total
1  | 1           | iPhone 16 128GB  | 1        | 2200000    | 2200000
2  | 1           | AirPods Pro      | 1        | 580000     | 580000
3  | 1           | Tempered Glass   | 2        | 14000      | 28000
```

**`doc_sequence`** — Auto-numbering tracker
```
branch_id | doc_type | year | last_sequence
1         | invoice  | 2026 | 41
```

**`payments`** — Payment records against documents (for credit sales)
```
id | document_id | amount  | payment_date | payment_method
1  | 15          | 500000  | 2026-06-01   | mpesa
```

### Device & Stock Tables

**`device_imeis`** — Every device's IMEI number
```
id | product_id | imei              | status   | branch_id
1  | 1          | 354012345678901  | in_stock | 1
2  | 1          | 354012345678902  | sold     | 1
```

**`device_sales`** — Detailed record of each device sold (IMEI, color, storage, buyer)
```
id | document_id | product_id | customer_id | imei             | color | storage
1  | 42          | 5          | 8           | 354012345678901 | Black | 128GB
```

**`stock_movements`** — Every stock change (IN, OUT, TRANSFER, ADJUSTMENT)
```
id | product_id | branch_id | movement_type | quantity | notes
1  | 5          | 1         | IN            | 10       | Stock from supplier
2  | 5          | 1         | OUT           | -1       | Sold - INV-ARU-0042
```

### Financial Tables

**`financing_plans`** — Installment agreements
```
id | plan_number   | customer_id | total_price | deposit | num_installments | status
1  | FIN-ARU-0001  | 8           | 3000000     | 600000  | 12               | active
```

**`financing_installments`** — Individual payments within a plan
```
id | plan_id | installment_number | due_date   | amount_due | amount_paid | status
1  | 1       | 1                  | 2026-02-01 | 200000     | 200000      | paid
2  | 1       | 2                  | 2026-03-01 | 200000     | 0           | pending
```

**`expenses`** — Branch operating costs
```
id | branch_id | category  | description     | amount | expense_date
1  | 1         | Utilities | Electricity bill| 150000 | 2026-06-01
```

**`cash_reconciliations`** — End-of-day cash counts
```
id | date       | branch_id | cash_counted | cash_sales | total_diff
1  | 2026-06-15 | 1         | 2450000      | 2400000    | 50000
```

### Service Tables

**`repair_jobs`** — Device repair tracking
```
id | job_number   | device_make | device_model    | problem           | status
1  | REP-ARU-0001 | Apple       | iPhone 15 Pro   | Cracked screen    | in_progress
```

**`tradeins`** — Device trade-in records
```
id | tradein_number | customer_id | device_make | assessed_value | credit_offered | status
1  | TI-ARU-0001    | 8           | Apple       | 800000         | 750000         | accepted
```

**`returns`** — Customer return requests
```
id | return_number | document_id | reason              | return_type | refund_amount | status
1  | RET-ARU-0001  | 42          | Defective product   | refund      | 2200000       | approved
```

### Config Tables

**`app_settings`** — Key-value store for dynamic configuration
```
key           | value
mail_server   | smtp.gmail.com
mail_port     | 465
mail_username | info@sadakalawe.com
vat_rate      | 18.0
```

**`user_permissions`** — Granular permissions per user (beyond just role)
```
user_id | permission
2       | view_reports
2       | create_documents
```

---

## 19. Common Patterns Used Everywhere

These are the patterns you'll see repeated in almost every route file. Once you recognize them, the code becomes very predictable.

### Pattern 1: The Standard GET/POST Route

```python
@bp.route('/customers/new', methods=['GET', 'POST'])
@login_required
def new_customer():
    if request.method == 'GET':
        # Show the empty form
        return render_template('customers/form.html')
    
    # POST: process what was submitted
    name  = request.form['name'].strip()
    phone = request.form.get('phone', '').strip()
    
    if not name:
        flash('Name is required.', 'danger')
        return redirect(url_for('customers.new_customer'))
    
    customer_id = execute_db(
        "INSERT INTO customers (name, phone, branch_id) VALUES (?,?,?)",
        [name, phone, current_user.branch_id]
    )
    
    flash('Customer added!', 'success')
    return redirect(url_for('customers.view_customer', customer_id=customer_id))
```

This exact structure — GET shows form, POST processes it — is in every route that handles a create/edit form.

### Pattern 2: Branch Filtering

```python
# Admins see all. Staff see their branch.
if current_user.role == 'admin':
    rows = query_db("SELECT * FROM documents ORDER BY created_at DESC")
else:
    rows = query_db(
        "SELECT * FROM documents WHERE branch_id=? ORDER BY created_at DESC",
        [current_user.branch_id]
    )
```

### Pattern 3: The 404 Check

```python
doc = query_db("SELECT * FROM documents WHERE id=?", [doc_id], one=True)
if not doc:
    abort(404)    # show "page not found" error
```

Always check if a record exists before trying to use it. Someone might bookmark a URL for a deleted record.

### Pattern 4: Permission Check

```python
@bp.route('/users')
@login_required
def list_users():
    if current_user.role != 'admin':
        abort(403)   # "Forbidden"
    
    users = query_db("SELECT * FROM users ORDER BY full_name")
    return render_template('users/list.html', users=users)
```

### Pattern 5: The URL Builder

```python
# NEVER hardcode URLs in Python:
return redirect('/customers/5')    # BAD

# ALWAYS use url_for:
return redirect(url_for('customers.view_customer', customer_id=5))
# url_for figures out the right URL from the function name
```

`url_for('customers.view_customer', customer_id=5)` generates `/customers/5`. If you ever change the URL structure, you change it in ONE place (the route decorator) and `url_for` automatically generates the new URL everywhere.

### Pattern 6: Reading URL Parameters

```python
# URL: /documents/42
@bp.route('/documents/<int:doc_id>')
def view_document(doc_id):
    # doc_id is automatically 42 (as an integer)
    doc = query_db("SELECT * FROM documents WHERE id=?", [doc_id], one=True)

# URL: /customers?branch=1&status=active
@bp.route('/customers')
def list_customers():
    branch = request.args.get('branch')    # '1' (from URL query string)
    status = request.args.get('status', 'all')   # 'active', default 'all'
```

`<int:doc_id>` in the route extracts the number from the URL and passes it as a parameter.
`request.args.get()` reads values from the URL after `?`.

---

## 20. What to Do When Things Break

### The App Won't Start

```bash
# Run it and read the error:
python app.py

# Common causes:
# 1. Missing package → pip install -r requirements.txt
# 2. Database locked → close any other connections, delete .db-wal if app is definitely stopped
# 3. Port in use → change port in app.py, or kill whatever's using 8090
```

### 500 Error (Something Went Wrong)

Check `sadakalawe.log` — every error gets logged there with a full traceback (the chain of function calls that led to the error). The last few lines of the traceback tell you exactly what broke and on what line.

```bash
tail -50 sadakalawe.log   # show last 50 lines of the log
```

### Database Corruption

This shouldn't happen with WAL mode, but if it does:
1. Stop the app
2. Copy the latest backup from `backups/` to `data/sadakalawe.db`
3. Start the app

### "Column not found" Errors

Usually means a migration didn't run. The `_run_migrations()` function in `database.py` adds new columns to existing tables. It runs automatically on app start, but if something prevented it from running:

```bash
python manage.py migrate   # run migrations manually
```

### Staff Locked Out

If an admin account's password is forgotten:

```bash
python manage.py resetpassword admin newpassword123
```

### Database Getting Big / Slow

SQLite handles millions of rows fine. But if queries become slow, it usually means missing indexes. Common queries are already indexed in the schema (on `branch_id`, `created_at`, `customer_id`). Adding more is straightforward if needed.

---

## Quick Reference Card

### The 3 things every route does:
1. **Check auth** — `@login_required` + role check
2. **Talk to database** — `query_db()` for reads, `execute_db()` for writes
3. **Return response** — `render_template()` for HTML, `redirect()` for redirect, `Response()` for files

### The data flow:
```
Browser → Flask Route → database.py → SQLite file
                     ↘ pdf_generator.py → PDF bytes → Browser
                     ↘ render_template → Jinja2 → HTML → Browser
```

### The 5 files that matter most:
1. `app.py` — everything connects here
2. `database.py` — all data lives here
3. `routes/documents.py` — the core feature
4. `services/pdf_generator.py` — the branded PDFs
5. `templates/base.html` — the visual shell

### Key SQL patterns:
```sql
-- Read all
SELECT * FROM customers WHERE branch_id = 1

-- Read one
SELECT * FROM customers WHERE id = 5

-- Create
INSERT INTO customers (name, phone) VALUES ('Hassan', '0712...')

-- Update
UPDATE customers SET phone = '0787...' WHERE id = 5

-- Delete
DELETE FROM customers WHERE id = 5
```

### Key Python patterns:
```python
# Read from DB
row = query_db("SELECT * FROM ...", [args], one=True)
rows = query_db("SELECT * FROM ...", [args])

# Write to DB
new_id = execute_db("INSERT INTO ...", [args])
execute_db("UPDATE ...", [args])

# Return HTML page
return render_template('template.html', key=value)

# Redirect
return redirect(url_for('blueprint.function_name', param=value))

# Show a message
flash('Message text', 'success')  # or 'danger', 'warning', 'info'

# Check if logged in user is admin
if current_user.role != 'admin':
    abort(403)
```

---

*This document was written to be your permanent reference. When you're confused about any part of the system, start here. When you add new features, the patterns in Section 19 are your templates.*

*Last updated: July 2026*
