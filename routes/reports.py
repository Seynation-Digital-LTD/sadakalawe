from flask import Blueprint, render_template, request, send_file
from flask_login import login_required, current_user
from database import query_db
from datetime import date
import csv
from io import StringIO, BytesIO

bp = Blueprint('reports', __name__)


def _branch_filter(branch_id):
    """Return (sql_clause, args) for branch filtering."""
    if branch_id:
        return " AND branch_id=?", [branch_id]
    return "", []


@bp.route('/dashboard')
@login_required
def dashboard():
    branch_id = (current_user.branch_id if not current_user.is_admin
                 else request.args.get('branch_id', ''))

    def _totals(period_sql, base_args):
        sql = f"""
            SELECT COUNT(*) as count, COALESCE(SUM(total),0) as revenue
            FROM documents
            WHERE doc_type='invoice' AND {period_sql}
        """
        args = list(base_args)
        if branch_id:
            sql += " AND branch_id=?"
            args.append(branch_id)
        return query_db(sql, args, one=True)

    today  = _totals("DATE(created_at)=DATE('now','localtime')", [])
    week   = _totals("DATE(created_at)>=DATE('now','localtime','-6 days')", [])
    month  = _totals("strftime('%Y-%m',created_at)=strftime('%Y-%m','now')", [])
    year   = _totals("strftime('%Y',created_at)=strftime('%Y','now')", [])

    # Branch split this month
    branch_split = query_db("""
        SELECT b.name, b.short_code,
               COUNT(d.id) as count,
               COALESCE(SUM(d.total),0) as revenue
        FROM branches b
        LEFT JOIN documents d ON d.branch_id=b.id
            AND d.doc_type='invoice'
            AND strftime('%Y-%m',d.created_at)=strftime('%Y-%m','now')
        GROUP BY b.id ORDER BY b.name
    """)

    # Outstanding credit summary
    credit_sql = """
        SELECT COUNT(*) as count,
               COALESCE(SUM(total - amount_paid),0) as total_owed,
               COALESCE(SUM(CASE WHEN credit_due_date < DATE('now') THEN total-amount_paid ELSE 0 END),0) as overdue
        FROM documents
        WHERE doc_type='invoice' AND payment_status IN ('credit','partial')
    """
    credit_args = []
    if branch_id:
        credit_sql += " AND branch_id=?"
        credit_args.append(branch_id)
    credit_summary = query_db(credit_sql, credit_args, one=True)

    # Low-stock alerts
    low_stock = query_db("""
        SELECT p.brand_category, p.model, p.low_stock_alert,
               COALESCE(SUM(ps.quantity),0) AS total_stock
        FROM products p
        LEFT JOIN product_stock ps ON ps.product_id=p.id
        WHERE p.is_active=1
        GROUP BY p.id
        HAVING total_stock <= p.low_stock_alert
        ORDER BY total_stock ASC
        LIMIT 6
    """)

    # Top products this month
    tp_sql = """
        SELECT di.description, SUM(di.quantity) as qty, SUM(di.line_total) as revenue
        FROM document_items di
        JOIN documents d ON di.document_id=d.id
        WHERE d.doc_type='invoice'
          AND strftime('%Y-%m',d.created_at)=strftime('%Y-%m','now')
    """
    tp_args = []
    if branch_id:
        tp_sql += " AND d.branch_id=?"
        tp_args.append(branch_id)
    tp_sql += " GROUP BY di.description ORDER BY revenue DESC LIMIT 5"
    top_products = query_db(tp_sql, tp_args)

    # Top customers this month
    tc_sql = """
        SELECT c.name, c.id, COUNT(d.id) as orders,
               COALESCE(SUM(d.total),0) as revenue
        FROM customers c
        JOIN documents d ON d.customer_id=c.id
        WHERE d.doc_type='invoice'
          AND strftime('%Y-%m',d.created_at)=strftime('%Y-%m','now')
    """
    tc_args = []
    if branch_id:
        tc_sql += " AND d.branch_id=?"
        tc_args.append(branch_id)
    tc_sql += " GROUP BY c.id ORDER BY revenue DESC LIMIT 5"
    top_customers = query_db(tc_sql, tc_args)

    # Recent docs
    rec_sql = """
        SELECT d.id, d.doc_number, d.doc_type, d.total, d.payment_status,
               d.created_at, b.name as branch_name, c.name as customer_name
        FROM documents d
        JOIN branches b ON d.branch_id=b.id
        LEFT JOIN customers c ON d.customer_id=c.id
        WHERE 1=1
    """
    rec_args = []
    if branch_id:
        rec_sql += " AND d.branch_id=?"
        rec_args.append(branch_id)
    rec_sql += " ORDER BY d.created_at DESC LIMIT 10"
    recent_docs = query_db(rec_sql, rec_args)

    branches = query_db("SELECT * FROM branches ORDER BY name")

    return render_template('dashboard.html',
                           today=today, week=week, month=month, year=year,
                           branch_split=branch_split, top_products=top_products,
                           top_customers=top_customers, recent_docs=recent_docs,
                           credit_summary=credit_summary, low_stock=low_stock,
                           branches=branches, branch_filter=branch_id)


@bp.route('/reports/sales')
@login_required
def sales_report():
    """Detailed sales report with date range filter."""
    branch_id = (current_user.branch_id if not current_user.is_admin
                 else request.args.get('branch_id', ''))
    date_from = request.args.get('date_from', date.today().replace(day=1).isoformat())
    date_to   = request.args.get('date_to', date.today().isoformat())
    export    = request.args.get('export', '')

    sql = """
        SELECT d.id, d.doc_number, d.created_at, d.total, d.subtotal, d.vat_amount,
               d.payment_status, d.amount_paid,
               d.total - d.amount_paid AS balance,
               b.name AS branch_name, c.name AS customer_name,
               u.full_name AS staff_name
        FROM documents d
        JOIN branches b ON d.branch_id=b.id
        LEFT JOIN customers c ON d.customer_id=c.id
        JOIN users u ON d.created_by=u.id
        WHERE d.doc_type='invoice'
          AND DATE(d.created_at) BETWEEN ? AND ?
    """
    args = [date_from, date_to]
    if branch_id:
        sql += " AND d.branch_id=?"
        args.append(branch_id)
    sql += " ORDER BY d.created_at DESC"
    docs = query_db(sql, args)

    total_rev   = sum(float(d['total']) for d in docs)
    total_paid  = sum(float(d['amount_paid']) for d in docs)
    total_debt  = sum(float(d['balance']) for d in docs)
    cash_count  = sum(1 for d in docs if d['payment_status'] == 'paid')
    credit_count = sum(1 for d in docs if d['payment_status'] in ('credit','partial'))

    if export == 'csv':
        si = StringIO()
        w = csv.writer(si)
        w.writerow(['Doc Number','Date','Branch','Customer','Staff',
                    'Total','Paid','Balance','Status'])
        for d in docs:
            w.writerow([d['doc_number'], d['created_at'][:10], d['branch_name'],
                        d['customer_name'] or 'Walk-in', d['staff_name'],
                        d['total'], d['amount_paid'], d['balance'], d['payment_status']])
        buf = BytesIO(si.getvalue().encode('utf-8-sig'))
        return send_file(buf, mimetype='text/csv', as_attachment=True,
                         download_name=f"Sales_{date_from}_{date_to}.csv")

    branches = query_db("SELECT * FROM branches ORDER BY name")
    return render_template('reports/sales.html',
                           docs=docs, branches=branches,
                           branch_filter=branch_id,
                           date_from=date_from, date_to=date_to,
                           total_rev=total_rev, total_paid=total_paid,
                           total_debt=total_debt,
                           cash_count=cash_count, credit_count=credit_count)


@bp.route('/reports/debts')
@login_required
def debts_report():
    """Outstanding debts grouped by customer."""
    branch_id = (current_user.branch_id if not current_user.is_admin
                 else request.args.get('branch_id', ''))
    export = request.args.get('export', '')

    sql = """
        SELECT c.id, c.name, c.phone,
               COUNT(d.id) AS credit_count,
               COALESCE(SUM(d.total),0) AS total_sold,
               COALESCE(SUM(d.amount_paid),0) AS total_paid,
               COALESCE(SUM(d.total - d.amount_paid),0) AS balance,
               MIN(d.credit_due_date) AS earliest_due
        FROM customers c
        JOIN documents d ON d.customer_id=c.id
        WHERE d.doc_type='invoice' AND d.payment_status IN ('credit','partial')
    """
    args = []
    if branch_id:
        sql += " AND d.branch_id=?"
        args.append(branch_id)
    sql += " GROUP BY c.id HAVING balance > 0 ORDER BY balance DESC"
    debtors = query_db(sql, args)

    total_outstanding = sum(float(d['balance']) for d in debtors)

    if export == 'csv':
        si = StringIO()
        w = csv.writer(si)
        w.writerow(['Customer','Phone','Invoices','Total Sold','Paid','Balance','Earliest Due'])
        for d in debtors:
            w.writerow([d['name'], d['phone'], d['credit_count'],
                        d['total_sold'], d['total_paid'], d['balance'], d['earliest_due']])
        buf = BytesIO(si.getvalue().encode('utf-8-sig'))
        return send_file(buf, mimetype='text/csv', as_attachment=True,
                         download_name=f"Madeni_{date.today().isoformat()}.csv")

    branches = query_db("SELECT * FROM branches ORDER BY name")
    today = date.today().isoformat()
    return render_template('reports/debts.html',
                           debtors=debtors, branches=branches,
                           branch_filter=branch_id,
                           total_outstanding=total_outstanding,
                           today=today)


@bp.route('/reports/stock')
@login_required
def stock_report():
    """Stock valuation and low-stock report."""
    branch_id = (current_user.branch_id if not current_user.is_admin
                 else request.args.get('branch_id', ''))
    export = request.args.get('export', '')

    if branch_id:
        sql = """
            SELECT p.brand_category, p.model, p.sku, p.price,
                   p.low_stock_alert,
                   COALESCE(ps.quantity,0) AS stock,
                   COALESCE(ps.quantity,0) * p.price AS value
            FROM products p
            LEFT JOIN product_stock ps ON ps.product_id=p.id AND ps.branch_id=?
            WHERE p.is_active=1
            ORDER BY p.brand_category, p.model
        """
        args = [branch_id]
    else:
        sql = """
            SELECT p.brand_category, p.model, p.sku, p.price,
                   p.low_stock_alert,
                   COALESCE(SUM(ps.quantity),0) AS stock,
                   COALESCE(SUM(ps.quantity),0) * p.price AS value
            FROM products p
            LEFT JOIN product_stock ps ON ps.product_id=p.id
            WHERE p.is_active=1
            GROUP BY p.id
            ORDER BY p.brand_category, p.model
        """
        args = []

    products = query_db(sql, args)
    total_value = sum(float(p['value']) for p in products)
    total_items = sum(float(p['stock']) for p in products)

    if export == 'csv':
        si = StringIO()
        w = csv.writer(si)
        w.writerow(['Category','Model','SKU','Price','Stock','Low Alert','Value'])
        for p in products:
            w.writerow([p['brand_category'], p['model'], p['sku'],
                        p['price'], p['stock'], p['low_stock_alert'], p['value']])
        buf = BytesIO(si.getvalue().encode('utf-8-sig'))
        return send_file(buf, mimetype='text/csv', as_attachment=True,
                         download_name=f"Stock_{date.today().isoformat()}.csv")

    branches = query_db("SELECT * FROM branches ORDER BY name")
    return render_template('reports/stock.html',
                           products=products, branches=branches,
                           branch_filter=branch_id,
                           total_value=total_value, total_items=total_items)
