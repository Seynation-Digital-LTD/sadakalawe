from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from database import execute_db, query_db
from config import BRAND_CATEGORIES

bp = Blueprint('products', __name__, url_prefix='/products')


@bp.route('/')
@login_required
def list():
    q = request.args.get('q', '').strip()
    category = request.args.get('category', '')
    show_inactive = request.args.get('inactive', '')

    sql = "SELECT * FROM products WHERE 1=1"
    args = []

    if not show_inactive:
        sql += " AND is_active=1"

    if q:
        sql += " AND (model LIKE ? OR description LIKE ? OR sku LIKE ? OR brand_category LIKE ?)"
        args += [f'%{q}%'] * 4

    if category:
        sql += " AND brand_category=?"
        args.append(category)

    sql += " ORDER BY brand_category, model"
    products = query_db(sql, args)
    return render_template('products/list.html', products=products, categories=BRAND_CATEGORIES,
                           q=q, category=category, show_inactive=show_inactive)


@bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    if request.method == 'POST':
        model = request.form['model'].strip()
        brand_category = request.form['brand_category']
        if not model or not brand_category:
            flash('Model and category are required.', 'danger')
            return render_template('products/form.html', categories=BRAND_CATEGORIES, action='new')

        pid = execute_db("""
            INSERT INTO products (brand_category, model, description, price, stock_count, sku)
            VALUES (?,?,?,?,?,?)
        """, (
            brand_category,
            model,
            request.form.get('description', '').strip(),
            float(request.form.get('price', 0) or 0),
            int(request.form.get('stock_count', 0) or 0),
            request.form.get('sku', '').strip(),
        ))
        flash(f'Product "{model}" added.', 'success')
        return redirect(url_for('products.list'))
    return render_template('products/form.html', categories=BRAND_CATEGORIES, action='new')


@bp.route('/<int:product_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(product_id):
    product = query_db("SELECT * FROM products WHERE id=?", (product_id,), one=True)
    if not product:
        flash('Product not found.', 'danger')
        return redirect(url_for('products.list'))

    if request.method == 'POST':
        model = request.form['model'].strip()
        brand_category = request.form['brand_category']
        is_active = 1 if request.form.get('is_active') else 0

        execute_db("""
            UPDATE products SET brand_category=?, model=?, description=?, price=?,
            stock_count=?, sku=?, is_active=?, updated_at=datetime('now') WHERE id=?
        """, (
            brand_category,
            model,
            request.form.get('description', '').strip(),
            float(request.form.get('price', 0) or 0),
            int(request.form.get('stock_count', 0) or 0),
            request.form.get('sku', '').strip(),
            is_active,
            product_id,
        ))
        flash('Product updated.', 'success')
        return redirect(url_for('products.list'))

    return render_template('products/form.html', product=product, categories=BRAND_CATEGORIES, action='edit')


@bp.route('/search')
@login_required
def search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    rows = query_db("""
        SELECT id, brand_category, model, description, price, stock_count
        FROM products WHERE is_active=1 AND (model LIKE ? OR brand_category LIKE ? OR description LIKE ?)
        ORDER BY brand_category, model LIMIT 20
    """, (f'%{q}%', f'%{q}%', f'%{q}%'))
    return jsonify([dict(r) for r in rows])
