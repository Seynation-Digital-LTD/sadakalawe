from flask import Blueprint, render_template, request, jsonify, abort
from flask_login import login_required, current_user
from database import query_db, execute_db

bp = Blueprint('devices', __name__, url_prefix='/devices')


@bp.route('/')
@login_required
def index():
    q = request.args.get('q', '').strip()
    branch_filter = request.args.get('branch_id', '')

    sql = """
        SELECT ds.*,
               p.model       AS product_model,
               p.brand_category,
               c.name        AS customer_name,
               c.phone       AS customer_phone,
               d.doc_number,
               d.created_at  AS sale_date,
               b.name        AS branch_name
        FROM device_sales ds
        JOIN documents d   ON d.id = ds.document_id
        JOIN branches  b   ON b.id = d.branch_id
        LEFT JOIN products p  ON p.id  = ds.product_id
        LEFT JOIN customers c ON c.id  = ds.customer_id
        WHERE 1=1
    """
    args = []

    if q:
        sql += """ AND (ds.imei LIKE ? OR ds.imei2 LIKE ? OR ds.serial_number LIKE ?
                        OR c.name LIKE ? OR p.model LIKE ? OR d.doc_number LIKE ?)"""
        args += [f'%{q}%'] * 6

    if branch_filter:
        sql += " AND d.branch_id=?"
        args.append(branch_filter)

    sql += " ORDER BY ds.created_at DESC LIMIT 200"
    devices = query_db(sql, args)
    branches = query_db("SELECT * FROM branches ORDER BY name")

    return render_template('devices/index.html',
                           devices=devices, q=q,
                           branches=branches,
                           branch_filter=branch_filter)


@bp.route('/register', methods=['POST'])
@login_required
def register():
    """AJAX: register a device sale from the invoice view."""
    data = request.get_json(silent=True) or {}

    doc_id    = data.get('document_id')
    item_id   = data.get('document_item_id')
    product_id = data.get('product_id')
    imei      = (data.get('imei') or '').strip() or None
    imei2     = (data.get('imei2') or '').strip() or None
    serial    = (data.get('serial_number') or '').strip() or None
    color     = (data.get('color') or '').strip() or None
    storage   = (data.get('storage') or '').strip() or None
    notes     = (data.get('notes') or '').strip() or None

    if not doc_id:
        return jsonify(error='document_id required'), 400

    doc = query_db("SELECT * FROM documents WHERE id=?", (doc_id,), one=True)
    if not doc:
        return jsonify(error='Document not found'), 404

    if not imei and not serial:
        return jsonify(error='Enter at least IMEI or serial number'), 400

    # Duplicate IMEI check
    if imei:
        dup = query_db("SELECT id, document_id FROM device_sales WHERE imei=?", (imei,), one=True)
        if dup:
            dup_doc = query_db("SELECT doc_number FROM documents WHERE id=?", (dup['document_id'],), one=True)
            return jsonify(error=f'IMEI {imei} already registered on {dup_doc["doc_number"] if dup_doc else "another invoice"}'), 409

    new_id = execute_db("""
        INSERT INTO device_sales
          (document_id, document_item_id, customer_id, product_id,
           imei, imei2, serial_number, color, storage, notes, created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (doc_id, item_id or None, doc['customer_id'], product_id or None,
          imei, imei2, serial, color, storage, notes, current_user.id))

    # Also update device_imeis status to 'sold' if IMEI is tracked in stock
    if imei:
        execute_db("""
            UPDATE device_imeis
               SET status='sold', sold_document_id=?, sold_at=datetime('now','localtime')
             WHERE imei=?
        """, (doc_id, imei))

    row = query_db("""
        SELECT ds.*, p.model AS product_model
        FROM device_sales ds
        LEFT JOIN products p ON p.id = ds.product_id
        WHERE ds.id=?
    """, (new_id,), one=True)

    return jsonify(
        id=row['id'],
        imei=row['imei'] or '',
        imei2=row['imei2'] or '',
        serial_number=row['serial_number'] or '',
        color=row['color'] or '',
        storage=row['storage'] or '',
        notes=row['notes'] or '',
        product_model=row['product_model'] or '',
    ), 201


@bp.route('/<int:device_id>/delete', methods=['POST'])
@login_required
def delete(device_id):
    row = query_db("SELECT * FROM device_sales WHERE id=?", (device_id,), one=True)
    if not row:
        abort(404)
    # Restore IMEI status in stock tracker
    if row['imei']:
        execute_db("""
            UPDATE device_imeis
               SET status='in_stock', sold_document_id=NULL, sold_at=NULL
             WHERE imei=?
        """, (row['imei'],))
    execute_db("DELETE FROM device_sales WHERE id=?", (device_id,))
    return jsonify(ok=True)


@bp.route('/by-doc/<int:doc_id>')
@login_required
def by_doc(doc_id):
    """Return all registered devices for a given document (AJAX)."""
    rows = query_db("""
        SELECT ds.*, p.model AS product_model, p.brand_category
        FROM device_sales ds
        LEFT JOIN products p ON p.id = ds.product_id
        WHERE ds.document_id=?
        ORDER BY ds.id
    """, (doc_id,))
    return jsonify([dict(r) for r in rows])
