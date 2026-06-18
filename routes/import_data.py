import csv
import io
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from database import execute_db, query_db

bp = Blueprint('import_data', __name__, url_prefix='/import')


# ─── helpers ──────────────────────────────────────────────────────────────────

def _norm_headers(row):
    """Return a dict with lowercase, stripped keys."""
    return {k.strip().lower(): v for k, v in row.items()}


def _parse_csv(file_bytes):
    """Parse CSV bytes, return list of dicts (all string values)."""
    text = file_bytes.decode('utf-8-sig', errors='replace')
    reader = csv.DictReader(io.StringIO(text))
    return [dict(r) for r in reader]


def _parse_xlsx(file_bytes):
    """Parse XLSX/XLS bytes, return list of dicts."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(h).strip() if h is not None else '' for h in rows[0]]
    result = []
    for row in rows[1:]:
        d = {}
        for h, v in zip(headers, row):
            d[h] = str(v).strip() if v is not None else ''
        result.append(d)
    wb.close()
    return result


def _parse_vcf(file_bytes):
    """Parse a vCard (.vcf) file, return list of dicts with name/phone/email/address."""
    text = file_bytes.decode('utf-8', errors='replace')
    contacts = []
    current = {}
    in_card = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.upper() == 'BEGIN:VCARD':
            in_card = True
            current = {}
        elif line.upper() == 'END:VCARD':
            if in_card and current.get('name', '').strip():
                contacts.append(current)
            in_card = False
            current = {}
        elif in_card:
            if ':' not in line:
                continue
            prop, _, value = line.partition(':')
            prop_upper = prop.upper().split(';')[0]
            if prop_upper == 'FN':
                current.setdefault('name', value.strip())
            elif prop_upper == 'TEL' and 'phone' not in current:
                # Strip non-digit chars except leading +
                digits = ''
                for i, ch in enumerate(value.strip()):
                    if ch == '+' and i == 0:
                        digits += ch
                    elif ch.isdigit():
                        digits += ch
                current['phone'] = digits
            elif prop_upper == 'EMAIL' and 'email' not in current:
                current['email'] = value.strip()
            elif prop_upper == 'ADR' and 'address' not in current:
                # ADR format: PO Box;Extended;Street;City;Region;Postal;Country
                parts = [p.strip() for p in value.split(';') if p.strip()]
                current['address'] = ', '.join(parts)
    return contacts


def _read_file(f):
    """Read uploaded file and return (data_rows, error_str)."""
    filename = (f.filename or '').lower()
    data = f.read()
    if filename.endswith('.vcf'):
        return _parse_vcf(data), None, 'vcf'
    elif filename.endswith('.csv'):
        return _parse_csv(data), None, 'csv'
    elif filename.endswith(('.xlsx', '.xls')):
        try:
            return _parse_xlsx(data), None, 'xlsx'
        except Exception as e:
            return None, f'Could not parse Excel file: {e}', 'xlsx'
    else:
        return None, 'Unsupported file type. Use CSV, XLSX, or VCF.', None


# ─── routes ───────────────────────────────────────────────────────────────────

@bp.route('/')
@login_required
def index():
    return render_template('import/index.html')


@bp.route('/products', methods=['POST'])
@login_required
def import_products():
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'imported': 0, 'skipped': 0, 'errors': ['No file uploaded']}), 400

    rows, err, fmt = _read_file(f)
    if err:
        return jsonify({'imported': 0, 'skipped': 0, 'errors': [err]}), 400

    branches = query_db("SELECT id FROM branches")

    imported = 0
    skipped  = 0
    errors   = []

    for i, raw in enumerate(rows, start=1):
        row = _norm_headers(raw)

        model = row.get('model', '').strip()
        if not model:
            skipped += 1
            continue

        # Flexible column names
        category_name = (row.get('brand_category') or row.get('category') or '').strip() or 'Other'

        # Look up or fall back category_id
        cat_row = query_db(
            "SELECT id FROM product_categories WHERE LOWER(name)=LOWER(?)",
            (category_name,), one=True
        )
        category_id = cat_row['id'] if cat_row else None
        if not category_id:
            # Try to match partial name
            cat_row = query_db(
                "SELECT id FROM product_categories WHERE LOWER(name) LIKE ?",
                (f'%{category_name.lower()}%',), one=True
            )
            category_id = cat_row['id'] if cat_row else 5  # fallback to Accessories

        # Duplicate check: (LOWER(model), category_id)
        existing = query_db(
            "SELECT id FROM products WHERE LOWER(model)=LOWER(?) AND category_id=?",
            (model, category_id), one=True
        )
        if existing:
            skipped += 1
            continue

        # Parse numeric fields safely
        try:
            price = float(row.get('price', 0) or 0)
        except ValueError:
            price = 0
        try:
            cost_price = float(row.get('cost_price', 0) or 0)
        except ValueError:
            cost_price = 0
        try:
            stock_count = int(float(row.get('stock_count', 0) or 0))
        except ValueError:
            stock_count = 0

        sku         = row.get('sku', '').strip() or None
        description = row.get('description', '').strip() or None

        try:
            pid = execute_db("""
                INSERT INTO products
                  (brand_category, category_id, model, description, price, cost_price,
                   stock_count, sku, is_active)
                VALUES (?,?,?,?,?,?,?,?,1)
            """, (category_name, category_id, model, description, price, cost_price,
                  stock_count, sku))

            # Ensure product_stock rows for all branches
            for b in branches:
                execute_db(
                    "INSERT OR IGNORE INTO product_stock (product_id, branch_id, quantity) VALUES (?,?,0)",
                    (pid, b['id'])
                )
            imported += 1
        except Exception as e:
            errors.append(f'Row {i} ({model}): {e}')
            skipped += 1

    return jsonify({'imported': imported, 'skipped': skipped, 'errors': errors})


@bp.route('/customers', methods=['POST'])
@login_required
def import_customers():
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'imported': 0, 'skipped': 0, 'errors': ['No file uploaded']}), 400

    rows, err, fmt = _read_file(f)
    if err:
        return jsonify({'imported': 0, 'skipped': 0, 'errors': [err]}), 400

    # Branch for imported customers: current user's branch or branch 1 for admin
    branch_id = current_user.branch_id or 1

    imported = 0
    skipped  = 0
    errors   = []

    for i, raw in enumerate(rows, start=1):
        if fmt == 'vcf':
            # vCard rows are already normalised dicts
            row = raw
        else:
            row = _norm_headers(raw)

        name = row.get('name', '').strip()
        if not name:
            skipped += 1
            continue

        phone = (row.get('phone', '') or '').strip()

        # Duplicate check: LOWER(name) + LOWER(phone)
        existing = query_db(
            "SELECT id FROM customers WHERE LOWER(name)=LOWER(?) AND LOWER(COALESCE(phone,''))=LOWER(?)",
            (name, phone), one=True
        )
        if existing:
            skipped += 1
            continue

        email   = (row.get('email', '')   or '').strip() or None
        tin     = (row.get('tin', '')     or '').strip() or None
        address = (row.get('address', '') or '').strip() or None
        notes   = (row.get('notes', '')   or '').strip() or None

        try:
            execute_db("""
                INSERT INTO customers (name, phone, email, tin, address, notes, branch_id)
                VALUES (?,?,?,?,?,?,?)
            """, (name, phone or None, email, tin, address, notes, branch_id))
            imported += 1
        except Exception as e:
            errors.append(f'Row {i} ({name}): {e}')
            skipped += 1

    return jsonify({'imported': imported, 'skipped': skipped, 'errors': errors})
