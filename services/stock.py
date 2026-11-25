"""One place for every stock change.

Rules this module enforces:
  * stock never goes below zero: you can only sell / move / write off what the
    branch actually has (check first, then move);
  * every change writes a stock_movements row, so the movement ledger always
    adds up to product_stock;
  * products.stock_count (all branches together) is re-synced after each change;
  * IMEI-tracked products move one physical unit at a time.

Call these inside database.transaction() so a failure undoes everything.
"""
from collections import defaultdict
from flask_login import current_user
from database import query_db, execute_db


def _uid():
    try:
        return current_user.id if current_user.is_authenticated else None
    except Exception:
        return None


def available(product_id, branch_id):
    row = query_db("SELECT quantity FROM product_stock WHERE product_id=? AND branch_id=?",
                   (product_id, branch_id), one=True)
    return float(row['quantity']) if row else 0.0


def _sync_total(product_id):
    execute_db("""
        UPDATE products SET
          stock_count = (SELECT COALESCE(SUM(quantity),0) FROM product_stock WHERE product_id=?),
          updated_at  = datetime('now','localtime')
        WHERE id=?
    """, (product_id, product_id))


def move(product_id, branch_id, signed_qty, movement_type,
         ref_doc_id=None, supplier=None, notes=None):
    """Apply one stock change and log it. Returns the stock_movements id."""
    execute_db("""
        INSERT INTO product_stock (product_id, branch_id, quantity) VALUES (?,?,?)
        ON CONFLICT(product_id, branch_id) DO UPDATE SET quantity = quantity + excluded.quantity
    """, (product_id, branch_id, signed_qty))
    mid = execute_db("""
        INSERT INTO stock_movements
          (product_id, branch_id, movement_type, quantity, reference_doc_id,
           supplier, notes, recorded_by)
        VALUES (?,?,?,?,?,?,?,?)
    """, (product_id, branch_id, movement_type, signed_qty, ref_doc_id,
          supplier, notes, _uid()))
    _sync_total(product_id)
    return mid


def qty_by_product(items):
    """{product_id: total qty} for lines that are linked to the catalogue."""
    need = defaultdict(float)
    for it in items:
        if it.get('product_id'):
            need[int(it['product_id'])] += abs(float(it['quantity']))
    return need


def check_sale(items, branch_id, giving_back=None):
    """Errors for a sale (empty list = OK).

    giving_back: {product_id: qty} already held by the document being edited,
    which goes back on the shelf before the new quantities are taken.
    """
    giving_back = giving_back or {}
    errors = []
    for it in items:
        if not it.get('product_id'):
            errors.append(f'"{it["description"].splitlines()[0]}" is not from the product list. '
                          'Pick every item from the catalogue so it comes out of stock '
                          '(ask the admin to add missing products).')
        q = float(it['quantity'])
        if q <= 0 or q != int(q):
            errors.append(f'"{it["description"].splitlines()[0]}": quantity must be a whole number above 0.')
        if float(it['unit_price']) < 0:
            errors.append(f'"{it["description"].splitlines()[0]}": price cannot be negative.')
    if errors:
        return errors

    for pid, qty in qty_by_product(items).items():
        p = query_db("SELECT model, is_active FROM products WHERE id=?", (pid,), one=True)
        if not p:
            errors.append('One of the items is no longer in the product list.')
            continue
        have = available(pid, branch_id) + giving_back.get(pid, 0)
        if qty > have + 1e-9:
            errors.append(f'Not enough stock for {p["model"]}: this branch has {have:g}, '
                          f'the sale needs {qty:g}. Receive the stock first (Stock → Add / Adjust) '
                          f'or transfer it from another branch.')
    return errors


def sell(items, branch_id, doc_id):
    for pid, qty in qty_by_product(items).items():
        move(pid, branch_id, -qty, 'sale', ref_doc_id=doc_id)


def doc_sold_qty(doc_ids):
    """{product_id: qty} currently taken out of stock by these documents."""
    if not doc_ids:
        return {}
    ph = ','.join('?' * len(doc_ids))
    rows = query_db(f"""
        SELECT product_id, -SUM(quantity) AS q FROM stock_movements
        WHERE movement_type='sale' AND reference_doc_id IN ({ph})
        GROUP BY product_id
    """, list(doc_ids))
    return {r['product_id']: float(r['q']) for r in rows if r['q']}


def reverse_sales(doc_ids, branch_id):
    """Put back on the shelf whatever these documents took out, and drop their
    sale movements (the document no longer sells it). Also releases IMEI units."""
    for pid, qty in doc_sold_qty(doc_ids).items():
        execute_db("""
            INSERT INTO product_stock (product_id, branch_id, quantity) VALUES (?,?,?)
            ON CONFLICT(product_id, branch_id) DO UPDATE SET quantity = quantity + excluded.quantity
        """, (pid, branch_id, qty))
        _sync_total(pid)
    if doc_ids:
        ph = ','.join('?' * len(doc_ids))
        execute_db(f"DELETE FROM stock_movements WHERE movement_type='sale' "
                   f"AND reference_doc_id IN ({ph})", list(doc_ids))
        execute_db(f"""
            UPDATE device_imeis SET status='in_stock', sold_document_id=NULL, sold_at=NULL
             WHERE sold_document_id IN ({ph})
                OR imei IN (SELECT imei FROM device_sales
                            WHERE document_id IN ({ph}) AND imei IS NOT NULL)
        """, list(doc_ids) * 2)
        execute_db(f"DELETE FROM device_sales WHERE document_id IN ({ph})", list(doc_ids))


# ── IMEI units ───────────────────────────────────────────────────────────────

def is_tracked(product_id):
    p = query_db("SELECT track_units FROM products WHERE id=?", (product_id,), one=True)
    return bool(p and p['track_units'])


def parse_imeis(raw):
    return [x.strip() for x in (raw or '').replace(',', '\n').splitlines() if x.strip()]


def check_units_at_branch(product_id, branch_id, imeis):
    """Errors unless every IMEI is in stock, for this product, at this branch."""
    errors, seen = [], set()
    for imei in imeis:
        if imei in seen:
            errors.append(f'IMEI {imei} is listed twice.')
            continue
        seen.add(imei)
        u = query_db("SELECT product_id, branch_id, status FROM device_imeis WHERE imei=?",
                     (imei,), one=True)
        if not u or u['product_id'] != int(product_id):
            errors.append(f'IMEI {imei} is not registered for this product.')
        elif u['status'] != 'in_stock':
            errors.append(f'IMEI {imei} is not in stock (it is {u["status"]}).')
        elif u['branch_id'] != int(branch_id):
            errors.append(f'IMEI {imei} is at another branch.')
    return errors
