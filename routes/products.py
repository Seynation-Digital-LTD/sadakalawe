from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from database import execute_db, query_db
from routes.auth import perm_required

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
               price, cost_price, stock_count, sku)
            VALUES (?,?,?,?,?,?,?,?,?)
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
        ))

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

        execute_db("""
            UPDATE products SET
              brand_category=?, category_id=?, subcategory_id=?,
              model=?, description=?, price=?, cost_price=?, stock_count=?, sku=?,
              is_active=?, updated_at=datetime('now','localtime')
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
            is_active,
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
    rows = query_db("""
        SELECT p.id, p.model, p.description, p.price, p.stock_count,
               pc.name AS category_name,
               ps.name AS subcategory_name
        FROM products p
        LEFT JOIN product_categories   pc ON p.category_id   = pc.id
        LEFT JOIN product_subcategories ps ON p.subcategory_id = ps.id
        WHERE p.is_active=1
          AND (p.model LIKE ? OR p.description LIKE ? OR p.sku LIKE ?
               OR pc.name LIKE ? OR ps.name LIKE ?)
        ORDER BY pc.sort_order, ps.sort_order, p.model
        LIMIT 25
    """, (f'%{q}%',) * 5)
    return jsonify([dict(r) for r in rows])
