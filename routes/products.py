import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from database import execute_db, query_db
from routes.auth import perm_required

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}


def _save_product_image(product_id, file):
    """Save uploaded image file, return relative path or None."""
    if not file or not file.filename:
        return None
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return None
    img_dir = os.path.join(current_app.root_path, 'static', 'product_images')
    os.makedirs(img_dir, exist_ok=True)
    filename = f"{product_id}.{ext}"
    file.save(os.path.join(img_dir, filename))
    return f"product_images/{filename}"


def _delete_old_image(image_path):
    """Delete the old image file from disk if it exists."""
    if not image_path:
        return
    full_path = os.path.join(current_app.root_path, 'static', image_path)
    if os.path.exists(full_path):
        try:
            os.remove(full_path)
        except OSError:
            pass

bp = Blueprint('products', __name__, url_prefix='/products')


def _get_categories():
    return query_db("SELECT * FROM product_categories ORDER BY sort_order")


def _get_subcategories():
    return query_db("SELECT * FROM product_subcategories ORDER BY category_id, sort_order")


def _cat_map(categories):
    return {c['id']: c for c in categories}


@bp.route('/')
@login_required
@perm_required('view_products')
def list():
    q           = request.args.get('q', '').strip()
    cat_id      = request.args.get('cat_id', '')
    subcat_id   = request.args.get('subcat_id', '')
    show_inactive = request.args.get('inactive', '')

    sql = """
        SELECT p.*,
               pc.name  AS category_name,
               pc.icon  AS category_icon,
               ps.name  AS subcategory_name
        FROM products p
        LEFT JOIN product_categories   pc ON p.category_id   = pc.id
        LEFT JOIN product_subcategories ps ON p.subcategory_id = ps.id
        WHERE 1=1
    """
    args = []

    if not show_inactive:
        sql += " AND p.is_active=1"
    if q:
        sql += " AND (p.model LIKE ? OR p.description LIKE ? OR p.sku LIKE ? OR pc.name LIKE ? OR ps.name LIKE ?)"
        args += [f'%{q}%'] * 5
    if cat_id:
        sql += " AND p.category_id=?"
        args.append(cat_id)
    if subcat_id:
        sql += " AND p.subcategory_id=?"
        args.append(subcat_id)

    sql += " ORDER BY pc.sort_order, ps.sort_order, p.model"
    products     = query_db(sql, args)
    categories   = _get_categories()
    subcategories = _get_subcategories()

    # Filter subcategories to only those under selected category (for dropdown)
    filtered_subcats = [s for s in subcategories if not cat_id or str(s['category_id']) == str(cat_id)]

    return render_template('products/list.html',
                           products=products,
                           categories=categories,
                           subcategories=filtered_subcats,
                           all_subcategories=subcategories,
                           q=q, cat_id=cat_id, subcat_id=subcat_id,
                           show_inactive=show_inactive)


@bp.route('/new', methods=['GET', 'POST'])
@login_required
@perm_required('manage_products')
def new():
    categories    = _get_categories()
    subcategories = _get_subcategories()

    if request.method == 'POST':
        model       = request.form.get('model', '').strip()
        cat_id      = request.form.get('category_id') or None
        subcat_id   = request.form.get('subcategory_id') or None

        if not model or not cat_id:
            flash('Model and category are required.', 'danger')
            return render_template('products/form.html',
                                   categories=categories, subcategories=subcategories, action='new')

        # Duplicate check
        dup = query_db("SELECT id FROM products WHERE LOWER(model)=LOWER(?) AND category_id=?",
                       (model, cat_id), one=True)
        if dup:
            flash(f'A product "{model}" in this category already exists.', 'danger')
            return render_template('products/form.html',
                                   categories=categories, subcategories=subcategories, action='new')

        # Derive brand_category from selected category name (backward compat)
        cat = query_db("SELECT name FROM product_categories WHERE id=?", (cat_id,), one=True)
        brand_category = cat['name'] if cat else 'Other'

        pid = execute_db("""
            INSERT INTO products
              (brand_category, category_id, subcategory_id, model, description,
               price, cost_price, stock_count, sku, barcode, track_units)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            brand_category,
            int(cat_id),
            int(subcat_id) if subcat_id else None,
            model,
            request.form.get('description', '').strip(),
            float(request.form.get('price', 0) or 0),
            float(request.form.get('cost_price', 0) or 0),
            int(request.form.get('stock_count', 0) or 0),
            request.form.get('sku', '').strip() or None,
            request.form.get('barcode', '').strip() or None,
            1 if request.form.get('track_units') else 0,
        ))

        # Handle image upload
        image_file = request.files.get('image')
        if image_file and image_file.filename:
            img_path = _save_product_image(pid, image_file)
            if img_path:
                execute_db("UPDATE products SET image_path=? WHERE id=?", (img_path, pid))

        # Ensure product_stock rows exist for all branches
        branches = query_db("SELECT id FROM branches")
        for b in branches:
            execute_db(
                "INSERT OR IGNORE INTO product_stock (product_id, branch_id, quantity) VALUES (?,?,0)",
                (pid, b['id'])
            )

        flash(f'Product "{model}" added.', 'success')
        return redirect(url_for('products.list'))

    return render_template('products/form.html',
                           categories=categories, subcategories=subcategories, action='new')


@bp.route('/<int:product_id>/edit', methods=['GET', 'POST'])
@login_required
@perm_required('manage_products')
def edit(product_id):
    product = query_db("""
        SELECT p.*, pc.name AS category_name, ps.name AS subcategory_name
        FROM products p
        LEFT JOIN product_categories   pc ON p.category_id   = pc.id
        LEFT JOIN product_subcategories ps ON p.subcategory_id = ps.id
        WHERE p.id=?
    """, (product_id,), one=True)
    if not product:
        flash('Product not found.', 'danger')
        return redirect(url_for('products.list'))

    categories    = _get_categories()
    subcategories = _get_subcategories()

    if request.method == 'POST':
        model     = request.form.get('model', '').strip()
        cat_id    = request.form.get('category_id') or None
        subcat_id = request.form.get('subcategory_id') or None
        is_active = 1 if request.form.get('is_active') else 0

        # Duplicate check (exclude current product)
        dup = query_db("SELECT id FROM products WHERE LOWER(model)=LOWER(?) AND category_id=? AND id!=?",
                       (model, cat_id, product_id), one=True)
        if dup:
            flash(f'Another product "{model}" in this category already exists.', 'danger')
            return render_template('products/form.html', product=product,
                                   categories=categories, subcategories=subcategories, action='edit')

        cat = query_db("SELECT name FROM product_categories WHERE id=?", (cat_id,), one=True)
        brand_category = cat['name'] if cat else 'Other'

        # Handle image upload on edit
        image_file = request.files.get('image')
        new_image_path = product['image_path'] if product['image_path'] else None
        if image_file and image_file.filename:
            ext = image_file.filename.rsplit('.', 1)[-1].lower() if '.' in image_file.filename else ''
            if ext in ALLOWED_IMAGE_EXTENSIONS:
                _delete_old_image(product['image_path'])
                new_image_path = _save_product_image(product_id, image_file)

        execute_db("""
            UPDATE products SET
              brand_category=?, category_id=?, subcategory_id=?,
              model=?, description=?, price=?, cost_price=?, stock_count=?, sku=?,
              barcode=?, is_active=?, image_path=?, track_units=?,
              updated_at=datetime('now','localtime')
            WHERE id=?
        """, (
            brand_category,
            int(cat_id) if cat_id else None,
            int(subcat_id) if subcat_id else None,
            model,
            request.form.get('description', '').strip(),
            float(request.form.get('price', 0) or 0),
            float(request.form.get('cost_price', 0) or 0),
            int(request.form.get('stock_count', 0) or 0),
            request.form.get('sku', '').strip() or None,
            request.form.get('barcode', '').strip() or None,
            is_active,
            new_image_path,
            1 if request.form.get('track_units') else 0,
            product_id,
        ))
        flash('Product updated.', 'success')
        return redirect(url_for('products.list'))

    return render_template('products/form.html',
                           product=product,
                           categories=categories,
                           subcategories=subcategories,
                           action='edit')


@bp.route('/api/subcategories/<int:cat_id>')
@login_required
def api_subcategories(cat_id):
    rows = query_db(
        "SELECT id, name FROM product_subcategories WHERE category_id=? ORDER BY sort_order",
        (cat_id,)
    )
    return jsonify([{'id': r['id'], 'name': r['name']} for r in rows])


@bp.route('/<int:product_id>/delete', methods=['POST'])
@login_required
@perm_required('manage_products')
def delete(product_id):
    product = query_db("SELECT * FROM products WHERE id=?", (product_id,), one=True)
    if not product:
        flash('Product not found.', 'danger')
        return redirect(url_for('products.list'))
    used = query_db("SELECT COUNT(*) AS cnt FROM document_items WHERE product_id=?",
                    (product_id,), one=True)['cnt']
    if used:
        # Soft delete — keep for document history, just hide from catalog
        execute_db("UPDATE products SET is_active=0 WHERE id=?", (product_id,))
        flash(f'"{product["model"]}" has been used in {used} document(s) — '
              f'it has been deactivated (hidden from catalog) to preserve history.', 'warning')
    else:
        execute_db("DELETE FROM products WHERE id=?", (product_id,))
        flash(f'Product "{product["model"]}" deleted.', 'success')
    return redirect(url_for('products.list'))


@bp.route('/search')
@login_required
def search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    # Stock shown on the sale screen is what THIS branch has — that is what can be sold.
    from services.access import own_branch
    branch_id = own_branch(request.args.get('branch_id'))
    rows = query_db("""
        SELECT p.id, p.model, p.description, p.price, p.stock_count, p.track_units,
               (SELECT COALESCE(quantity,0) FROM product_stock
                 WHERE product_id=p.id AND branch_id=?) AS branch_stock,
               pc.name AS category_name,
               ps.name AS subcategory_name
        FROM products p
        LEFT JOIN product_categories   pc ON p.category_id   = pc.id
        LEFT JOIN product_subcategories ps ON p.subcategory_id = ps.id
        WHERE p.is_active=1
          AND (p.model LIKE ? OR p.description LIKE ? OR p.sku LIKE ?
               OR pc.name LIKE ? OR ps.name LIKE ? OR p.barcode LIKE ?)
        ORDER BY pc.sort_order, ps.sort_order, p.model
        LIMIT 25
    """, (branch_id,) + (f'%{q}%',) * 6)
    return jsonify([dict(r) for r in rows])


# Every table that points at a product — all of them move to the kept product on a merge.
PRODUCT_LINK_TABLES = ('document_items', 'stock_movements', 'device_imeis',
                       'device_sales', 'return_items')


@bp.route('/merge', methods=['POST'])
@login_required
@perm_required('manage_products')
def merge():
    """Merge duplicate products into one: stock is added up, sales history and IMEIs
    move across, and the duplicate is switched off (kept for the record)."""
    from database import transaction, audit
    from services import stock as stock_svc
    keep_id = request.form.get('keep_id', type=int)
    dup_ids = [d for d in request.form.getlist('dup_ids[]', type=int) if d != keep_id]
    keep = query_db("SELECT * FROM products WHERE id=?", (keep_id,), one=True)
    back = url_for('settings.duplicates') + '#products'
    if not keep or not dup_ids:
        flash('Choose the product to keep and at least one duplicate.', 'danger')
        return redirect(back)

    names = []
    with transaction():
        for dup_id in dup_ids:
            dup = query_db("SELECT * FROM products WHERE id=?", (dup_id,), one=True)
            if not dup:
                continue
            for row in query_db("SELECT branch_id, quantity FROM product_stock WHERE product_id=?", (dup_id,)):
                if row['quantity']:
                    stock_svc.put_back(keep_id, row['branch_id'], row['quantity'])
            execute_db("DELETE FROM product_stock WHERE product_id=?", (dup_id,))
            for table in PRODUCT_LINK_TABLES:
                execute_db(f"UPDATE {table} SET product_id=? WHERE product_id=?", (keep_id, dup_id))
            if not keep['cost_price'] and dup['cost_price']:
                execute_db("UPDATE products SET cost_price=? WHERE id=?", (dup['cost_price'], keep_id))
            if dup['track_units']:
                execute_db("UPDATE products SET track_units=1 WHERE id=?", (keep_id,))
            execute_db("UPDATE products SET is_active=0, stock_count=0, "
                       "updated_at=datetime('now','localtime') WHERE id=?", (dup_id,))
            names.append(dup['model'])
        stock_svc._sync_total(keep_id)
        audit('merge', 'product', keep_id, keep['model'], 'merged in: ' + ', '.join(names))

    flash(f'Merged {len(names)} duplicate(s) into "{keep["model"]}". Stock and sales history moved across.',
          'success')
    return redirect(back)
