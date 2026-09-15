from flask import Blueprint, render_template, request, send_file
from flask_login import login_required, current_user
from database import query_db
from routes.auth import perm_required
from datetime import date
import csv
from io import StringIO, BytesIO
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

bp = Blueprint('reports', __name__)

ORANGE = 'FFF26522'
BLACK  = 'FF000000'
WHITE  = 'FFFFFFFF'
LIGHT  = 'FFFFF3EC'

def _branch_filter(branch_id):
    if branch_id:
        return " AND branch_id=?", [branch_id]
    return "", []


def _xlsx_workbook(sheet_name, headers):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    hdr_fill = PatternFill('solid', fgColor=ORANGE)
    hdr_font = Font(bold=True, color=WHITE)
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = hdr_fill
        cell.font = hdr_font
        cell.alignment = Alignment(horizontal='center')
    return wb, ws


def _xlsx_response(wb, filename):
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name=filename)


@bp.route('/dashboard')
@login_required
@perm_required('view_reports')
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

    low_stock = query_db("""
        SELECT p.id, p.brand_category, p.model, p.low_stock_alert,
               COALESCE(SUM(ps.quantity),0) AS total_stock
        FROM products p
        LEFT JOIN product_stock ps ON ps.product_id=p.id
        WHERE p.is_active=1
        GROUP BY p.id
        HAVING total_stock <= p.low_stock_alert
        ORDER BY total_stock ASC
    """)

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
@perm_required('view_reports')
def sales_report():
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

    total_rev    = sum(float(d['total']) for d in docs)
    total_paid   = sum(float(d['amount_paid']) for d in docs)
    total_debt   = sum(float(d['balance']) for d in docs)
    cash_count   = sum(1 for d in docs if d['payment_status'] == 'paid')
    credit_count = sum(1 for d in docs if d['payment_status'] in ('credit','partial'))

    headers = ['Doc Number','Date','Branch','Customer','Staff',
               'Total (TZS)','Paid (TZS)','Balance (TZS)','Status']

    if export == 'csv':
        si = StringIO()
        w = csv.writer(si)
        w.writerow(headers)
        for d in docs:
            w.writerow([d['doc_number'], d['created_at'][:10], d['branch_name'],
                        d['customer_name'] or 'Walk-in', d['staff_name'],
                        d['total'], d['amount_paid'], d['balance'], d['payment_status']])
        buf = BytesIO(si.getvalue().encode('utf-8-sig'))
        return send_file(buf, mimetype='text/csv', as_attachment=True,
                         download_name=f"Sales_{date_from}_{date_to}.csv")

    if export == 'excel':
        wb, ws = _xlsx_workbook('Sales', headers)
        for d in docs:
            ws.append([d['doc_number'], d['created_at'][:10], d['branch_name'],
                       d['customer_name'] or 'Walk-in', d['staff_name'],
                       float(d['total']), float(d['amount_paid']),
                       float(d['balance']), d['payment_status']])
        # Totals row
        row = ws.max_row + 1
        ws.cell(row=row, column=1, value='TOTAL').font = Font(bold=True)
        ws.cell(row=row, column=6, value=total_rev).font = Font(bold=True)
        ws.cell(row=row, column=7, value=total_paid).font = Font(bold=True)
        ws.cell(row=row, column=8, value=total_debt).font = Font(bold=True)
        for col in range(1, len(headers)+1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 18
        return _xlsx_response(wb, f"Sales_{date_from}_{date_to}.xlsx")

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
@perm_required('view_reports')
def debts_report():
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

    headers = ['Customer','Phone','Invoices','Total Sold (TZS)','Paid (TZS)','Balance (TZS)','Earliest Due']

    if export == 'csv':
        si = StringIO()
        w = csv.writer(si)
        w.writerow(headers)
        for d in debtors:
            w.writerow([d['name'], d['phone'], d['credit_count'],
                        d['total_sold'], d['total_paid'], d['balance'], d['earliest_due']])
        buf = BytesIO(si.getvalue().encode('utf-8-sig'))
        return send_file(buf, mimetype='text/csv', as_attachment=True,
                         download_name=f"Debts_{date.today().isoformat()}.csv")

    if export == 'excel':
        wb, ws = _xlsx_workbook('Outstanding Debts', headers)
        for d in debtors:
            ws.append([d['name'], d['phone'] or '', d['credit_count'],
                       float(d['total_sold']), float(d['total_paid']),
                       float(d['balance']), d['earliest_due'] or ''])
        row = ws.max_row + 1
        ws.cell(row=row, column=1, value='TOTAL').font = Font(bold=True)
        ws.cell(row=row, column=6, value=total_outstanding).font = Font(bold=True)
        for col in range(1, len(headers)+1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 20
        return _xlsx_response(wb, f"Debts_{date.today().isoformat()}.xlsx")

    branches = query_db("SELECT * FROM branches ORDER BY name")
    today = date.today().isoformat()
    return render_template('reports/debts.html',
                           debtors=debtors, branches=branches,
                           branch_filter=branch_id,
                           total_outstanding=total_outstanding,
                           today=today)


@bp.route('/reports/stock')
@login_required
@perm_required('view_reports')
def stock_report():
    branch_id  = (current_user.branch_id if not current_user.is_admin
                  else request.args.get('branch_id', ''))
    export     = request.args.get('export', '')
    slow_days  = request.args.get('slow_days', '')  # '' = all, '30','60','90'

    if branch_id:
        sql = """
            SELECT p.id, p.brand_category, p.model, p.sku, p.price,
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
            SELECT p.id, p.brand_category, p.model, p.sku, p.price,
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

    # Slow-moving filter: products with stock > 0 and no sales in last N days
    if slow_days:
        days = int(slow_days)
        sold_ids = {
            row['product_id'] for row in query_db(
                """SELECT DISTINCT di.product_id FROM document_items di
                   JOIN documents d ON di.document_id=d.id
                   WHERE d.doc_type='invoice'
                     AND d.created_at >= DATE('now',?)
                     AND di.product_id IS NOT NULL""",
                [f'-{days} days'])
        }
        products = [p for p in products if p['stock'] > 0 and p['id'] not in sold_ids]

    total_value = sum(float(p['value']) for p in products)
    total_items = sum(float(p['stock']) for p in products)

    headers = ['Category','Model','SKU','Price (TZS)','Stock','Low Alert','Value (TZS)']

    if export == 'csv':
        si = StringIO()
        w = csv.writer(si)
        w.writerow(headers)
        for p in products:
            w.writerow([p['brand_category'], p['model'], p['sku'] or '',
                        p['price'], p['stock'], p['low_stock_alert'], p['value']])
        buf = BytesIO(si.getvalue().encode('utf-8-sig'))
        return send_file(buf, mimetype='text/csv', as_attachment=True,
                         download_name=f"Stock_{date.today().isoformat()}.csv")

    if export == 'excel':
        wb, ws = _xlsx_workbook('Stock', headers)
        for p in products:
            ws.append([p['brand_category'], p['model'], p['sku'] or '',
                       float(p['price']), float(p['stock']),
                       p['low_stock_alert'], float(p['value'])])
        row = ws.max_row + 1
        ws.cell(row=row, column=1, value='TOTAL').font = Font(bold=True)
        ws.cell(row=row, column=5, value=total_items).font = Font(bold=True)
        ws.cell(row=row, column=7, value=total_value).font = Font(bold=True)
        for col in range(1, len(headers)+1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 18
        label = f"_Slow{slow_days}d" if slow_days else ""
        return _xlsx_response(wb, f"Stock{label}_{date.today().isoformat()}.xlsx")

    branches = query_db("SELECT * FROM branches ORDER BY name")
    return render_template('reports/stock.html',
                           products=products, branches=branches,
                           branch_filter=branch_id,
                           total_value=total_value, total_items=total_items,
                           slow_days=slow_days)


@bp.route('/reports/pnl')
@login_required
@perm_required('view_reports')
def pnl_report():
    branch_id = (current_user.branch_id if not current_user.is_admin
                 else request.args.get('branch_id', ''))
    date_from = request.args.get('date_from', date.today().replace(day=1).isoformat())
    date_to   = request.args.get('date_to',   date.today().isoformat())

    b_filter    = " AND d.branch_id=?" if branch_id else ""
    b_filter_e  = " AND branch_id=?"  if branch_id else ""
    b_args      = [branch_id] if branch_id else []

    # ── Revenue ──────────────────────────────────────────────────────────
    rev = query_db(
        f"SELECT COALESCE(SUM(total),0) AS v, COALESCE(SUM(amount_paid),0) AS paid "
        f"FROM documents WHERE doc_type='invoice' AND DATE(created_at) BETWEEN ? AND ? {b_filter_e}",
        [date_from, date_to] + b_args, one=True)
    revenue     = float(rev['v'])
    collected   = float(rev['paid'])
    outstanding = revenue - collected

    # ── COGS: qty * cost_price for tracked products ───────────────────────
    cogs_sql = (
        f"SELECT COALESCE(SUM(di.quantity * p.cost_price), 0) AS cogs, "
        f"       COUNT(DISTINCT CASE WHEN p.cost_price > 0 THEN di.id END) AS costed_lines, "
        f"       COUNT(DISTINCT di.id) AS total_lines "
        f"FROM document_items di "
        f"JOIN documents d ON di.document_id = d.id "
        f"LEFT JOIN products p ON di.product_id = p.id "
        f"WHERE d.doc_type='invoice' AND DATE(d.created_at) BETWEEN ? AND ? {b_filter}"
    )
    cogs_row    = query_db(cogs_sql, [date_from, date_to] + b_args, one=True)
    cogs        = float(cogs_row['cogs'])
    costed_lines  = int(cogs_row['costed_lines'] or 0)
    total_lines   = int(cogs_row['total_lines'] or 0)
    uncosted_lines = total_lines - costed_lines   # lines with no cost price

    gross_profit = revenue - cogs
    gross_margin = (gross_profit / revenue * 100) if revenue > 0 else 0

    # Products missing cost price (for the warning banner)
    missing_cost = query_db(
        "SELECT COUNT(*) AS v FROM products WHERE is_active=1 AND cost_price = 0", one=True)
    missing_cost_count = int(missing_cost['v'])

    # ── Expenses ─────────────────────────────────────────────────────────
    exp = query_db(
        f"SELECT COALESCE(SUM(amount),0) AS v FROM expenses "
        f"WHERE DATE(expense_date) BETWEEN ? AND ? {b_filter_e}",
        [date_from, date_to] + b_args, one=True)
    expenses = float(exp['v'])

    exp_cats = query_db(
        f"SELECT category, COALESCE(SUM(amount),0) AS total FROM expenses "
        f"WHERE DATE(expense_date) BETWEEN ? AND ? {b_filter_e} "
        f"GROUP BY category ORDER BY total DESC",
        [date_from, date_to] + b_args)

    # ── Net profit ────────────────────────────────────────────────────────
    # Gross profit = revenue - COGS  (product margin)
    # Net profit   = gross profit - operating expenses
    net_profit = gross_profit - expenses

    # Cash position = collected - expenses (actual cash flow)
    cash_position = collected - expenses

    # ── Financing & trade-ins ─────────────────────────────────────────────
    fin_row = query_db(
        "SELECT COALESCE(SUM(fi.amount_paid),0) AS v "
        "FROM financing_installments fi JOIN financing_plans fp ON fi.plan_id=fp.id "
        "WHERE fi.status='paid' AND DATE(fi.paid_date) BETWEEN ? AND ?",
        [date_from, date_to], one=True)
    financing_in = float(fin_row['v'])

    ti_row = query_db(
        "SELECT COALESCE(SUM(credit_offered),0) AS v FROM tradeins "
        "WHERE status='accepted' AND DATE(created_at) BETWEEN ? AND ?",
        [date_from, date_to], one=True)
    tradein_credit = float(ti_row['v'])

    # ── Top items by revenue + margin ─────────────────────────────────────
    top_sql = (
        f"SELECT di.description, "
        f"       SUM(di.line_total) AS rev, "
        f"       SUM(di.quantity) AS qty, "
        f"       SUM(di.quantity * COALESCE(p.cost_price, 0)) AS cost "
        f"FROM document_items di "
        f"JOIN documents d ON di.document_id=d.id "
        f"LEFT JOIN products p ON di.product_id=p.id "
        f"WHERE d.doc_type='invoice' AND DATE(d.created_at) BETWEEN ? AND ? {b_filter} "
        f"GROUP BY di.description ORDER BY rev DESC LIMIT 8"
    )
    top_items = query_db(top_sql, [date_from, date_to] + b_args)

    # ── Credit sales ratio ────────────────────────────────────────────────
    inv_counts = query_db(
        f"SELECT COUNT(*) AS total, "
        f"SUM(CASE WHEN payment_status IN ('credit','partial') THEN 1 ELSE 0 END) AS on_credit "
        f"FROM documents WHERE doc_type='invoice' AND DATE(created_at) BETWEEN ? AND ? {b_filter_e}",
        [date_from, date_to] + b_args, one=True)
    credit_ratio = ((inv_counts['on_credit'] or 0) / inv_counts['total'] * 100
                    if inv_counts['total'] else 0)

    # ── Suggestions ───────────────────────────────────────────────────────
    suggestions = []

    if missing_cost_count > 0:
        suggestions.append({
            'icon': 'bi-exclamation-circle', 'color': 'warning',
            'text': f'{missing_cost_count} product(s) have no cost price set — '
                    f'COGS and gross margin are understated. Go to Product Catalog and fill in buying prices.'
        })
    if gross_margin > 0:
        if gross_margin < 15:
            suggestions.append({
                'icon': 'bi-graph-down-arrow', 'color': 'danger',
                'text': f'Gross margin is very thin at {gross_margin:.1f}%. Check supplier prices or consider raising selling prices.'
            })
        elif gross_margin < 25:
            suggestions.append({
                'icon': 'bi-exclamation-triangle', 'color': 'warning',
                'text': f'Gross margin is {gross_margin:.1f}%. Healthy range for electronics retail is 25–40%. Room to improve.'
            })
        else:
            suggestions.append({
                'icon': 'bi-check-circle', 'color': 'success',
                'text': f'Gross margin is {gross_margin:.1f}% — solid. Keep monitoring per-product margins to protect it.'
            })
    if outstanding > 0:
        suggestions.append({
            'icon': 'bi-clock-history', 'color': 'warning',
            'text': f'TZS {outstanding:,.0f} in invoices still unpaid. Follow up to convert outstanding to collected cash.'
        })
    if credit_ratio > 30:
        suggestions.append({
            'icon': 'bi-person-x', 'color': 'warning',
            'text': f'{credit_ratio:.0f}% of invoices this period were on credit. Consider stricter deposit requirements.'
        })
    if expenses > gross_profit * 0.8 and gross_profit > 0:
        suggestions.append({
            'icon': 'bi-graph-down', 'color': 'danger',
            'text': f'Operating expenses (TZS {expenses:,.0f}) are eating most of your gross profit. Review the biggest cost categories.'
        })
    if top_items:
        top = top_items[0]
        top_margin = ((float(top['rev']) - float(top['cost'])) / float(top['rev']) * 100
                      if float(top['rev']) > 0 and float(top['cost']) > 0 else None)
        tip = f' (margin: {top_margin:.0f}%)' if top_margin is not None else ''
        suggestions.append({
            'icon': 'bi-trophy', 'color': 'success',
            'text': f'Top seller: "{top["description"]}" — TZS {float(top["rev"]):,.0f} revenue{tip}. Keep it well stocked.'
        })
    if net_profit < 0 and cogs > 0:
        suggestions.append({
            'icon': 'bi-exclamation-circle-fill', 'color': 'danger',
            'text': f'Net profit is negative (TZS {net_profit:,.0f}). Expenses exceed gross profit — urgent review needed.'
        })

    export = request.args.get('export', '')
    if export == 'excel':
        wb = openpyxl.Workbook()

        # Sheet 1 — Summary
        ws = wb.active
        ws.title = 'P&L Summary'
        hdr_fill = PatternFill('solid', fgColor=ORANGE)
        hdr_font = Font(bold=True, color=WHITE)
        def _sh(ws, row, col, val, bold=False, orange_bg=False):
            c = ws.cell(row=row, column=col, value=val)
            if orange_bg:
                c.fill = hdr_fill
                c.font = hdr_font
            elif bold:
                c.font = Font(bold=True)
            return c

        ws.column_dimensions['A'].width = 32
        ws.column_dimensions['B'].width = 22
        summary_rows = [
            ('Period',          f'{date_from}  →  {date_to}'),
            ('Branch',          branch_id or 'All Branches'),
            ('', ''),
            ('Revenue',         revenue),
            ('Collected',       collected),
            ('Outstanding',     outstanding),
            ('', ''),
            ('Cost of Goods (COGS)', cogs),
            ('Gross Profit',    gross_profit),
            ('Gross Margin',    f'{gross_margin:.1f}%'),
            ('', ''),
            ('Operating Expenses', expenses),
            ('', ''),
            ('NET PROFIT',      net_profit),
            ('Cash Position',   cash_position),
        ]
        for i, (label, value) in enumerate(summary_rows, start=1):
            is_total = label in ('NET PROFIT', 'Gross Profit', 'Revenue')
            _sh(ws, i, 1, label, bold=is_total, orange_bg=is_total)
            _sh(ws, i, 2, value, bold=is_total, orange_bg=is_total)

        # Sheet 2 — Top Items
        ws2 = wb.create_sheet('Top Items')
        for col, h in enumerate(['Item', 'Qty', 'Revenue (TZS)', 'COGS (TZS)', 'Margin (TZS)'], 1):
            c = ws2.cell(row=1, column=col, value=h)
            c.fill = hdr_fill; c.font = hdr_font
        for item in top_items:
            rev_i  = float(item['rev'])
            cost_i = float(item['cost'])
            ws2.append([item['description'], float(item['qty']),
                        rev_i, cost_i, rev_i - cost_i])
        for col in range(1, 6):
            ws2.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 22

        # Sheet 3 — Expenses by Category
        ws3 = wb.create_sheet('Expenses by Category')
        for col, h in enumerate(['Category', 'Total (TZS)'], 1):
            c = ws3.cell(row=1, column=col, value=h)
            c.fill = hdr_fill; c.font = hdr_font
        for cat in exp_cats:
            ws3.append([cat['category'], float(cat['total'])])
        ws3.column_dimensions['A'].width = 30
        ws3.column_dimensions['B'].width = 20

        fname = f"PnL_{date_from}_{date_to}.xlsx"
        return _xlsx_response(wb, fname)

    branches = query_db("SELECT * FROM branches ORDER BY name")
    return render_template('reports/pnl.html',
                           revenue=revenue, collected=collected, outstanding=outstanding,
                           cogs=cogs, costed_lines=costed_lines, total_lines=total_lines,
                           uncosted_lines=uncosted_lines, missing_cost_count=missing_cost_count,
                           gross_profit=gross_profit, gross_margin=gross_margin,
                           expenses=expenses, exp_cats=exp_cats,
                           net_profit=net_profit, cash_position=cash_position,
                           financing_in=financing_in, tradein_credit=tradein_credit,
                           top_items=top_items, credit_ratio=credit_ratio,
                           suggestions=suggestions,
                           branches=branches, branch_filter=branch_id,
                           date_from=date_from, date_to=date_to)


@bp.route('/stock-performance')
@login_required
@perm_required('view_reports')
def stock_performance():
    branch_id   = request.args.get('branch_id', '')
    idle_days   = int(request.args.get('idle_days', 45))
    period      = request.args.get('period', 'month')  # month / quarter / year / all
    sort_by     = request.args.get('sort_by', 'revenue')  # revenue / qty

    # Date range for top sellers
    today = date.today()
    if period == 'month':
        date_from = today.replace(day=1).isoformat()
    elif period == 'quarter':
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        date_from = today.replace(month=q_start_month, day=1).isoformat()
    elif period == 'year':
        date_from = today.replace(month=1, day=1).isoformat()
    else:
        date_from = '2020-01-01'

    branch_clause = ""
    branch_args   = []
    if not current_user.is_admin and current_user.branch_id:
        branch_clause = " AND d.branch_id=?"
        branch_args   = [current_user.branch_id]
    elif branch_id:
        branch_clause = " AND d.branch_id=?"
        branch_args   = [branch_id]

    # ── Top sellers ──────────────────────────────────────────────
    order_col = "revenue DESC" if sort_by == 'revenue' else "units_sold DESC"
    top_sellers = query_db(f"""
        SELECT p.id, p.model, p.brand_category,
               pc.name  AS category_name,
               ps.name  AS subcategory_name,
               SUM(di.quantity)                                    AS units_sold,
               SUM(di.quantity * di.unit_price * (1 - COALESCE(di.discount_pct,0)/100.0))
                                                                   AS revenue,
               p.cost_price,
               SUM(di.quantity) * p.cost_price                    AS cogs,
               p.stock_count
        FROM document_items di
        JOIN documents  d  ON d.id  = di.document_id
        JOIN products   p  ON p.id  = di.product_id
        LEFT JOIN product_categories   pc ON pc.id = p.category_id
        LEFT JOIN product_subcategories ps ON ps.id = p.subcategory_id
        WHERE d.doc_type='invoice'
          AND DATE(d.created_at) >= ?
          {branch_clause}
          AND di.product_id IS NOT NULL
        GROUP BY di.product_id
        ORDER BY {order_col}
        LIMIT 30
    """, [date_from] + branch_args)

    # ── Slow-moving stock ─────────────────────────────────────────
    slow = query_db(f"""
        SELECT p.id, p.model, p.brand_category, p.stock_count, p.cost_price,
               pc.name AS category_name,
               p.stock_count * p.cost_price AS stock_value,
               MAX(d.created_at)            AS last_sold_at,
               CASE
                 WHEN MAX(d.created_at) IS NULL THEN 9999
                 ELSE CAST(julianday('now') - julianday(MAX(d.created_at)) AS INTEGER)
               END AS days_idle
        FROM products p
        LEFT JOIN product_categories pc ON pc.id = p.category_id
        LEFT JOIN document_items di ON di.product_id = p.id
        LEFT JOIN documents d ON d.id = di.document_id
                             AND d.doc_type='invoice'
                             {branch_clause.replace('AND d.branch_id', 'AND d.branch_id')}
        WHERE p.is_active=1
          AND p.stock_count > 0
        GROUP BY p.id
        HAVING days_idle >= ?
        ORDER BY days_idle DESC
        LIMIT 50
    """, branch_args + [idle_days])

    branches = query_db("SELECT * FROM branches ORDER BY name")
    return render_template('reports/stock_performance.html',
                           top_sellers=top_sellers, slow=slow,
                           branches=branches, branch_filter=branch_id,
                           idle_days=idle_days, period=period, sort_by=sort_by,
                           date_from=date_from, today=today.isoformat())
