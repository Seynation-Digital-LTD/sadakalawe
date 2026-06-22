from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from database import query_db

bp = Blueprint('upgrade', __name__, url_prefix='/upgrade')

# Default upgrade cycles in months per brand category
DEFAULT_CYCLES = {
    'iPhone':  18,
    'MacBook': 36,
    'iPad':    30,
    'JBL':     24,
    'Anker':   24,
}


def _clean_phone(phone):
    """Normalise TZ phone to wa.me format: 255XXXXXXXXX"""
    if not phone:
        return None
    p = ''.join(c for c in phone if c.isdigit() or c == '+')
    p = p.lstrip('+')
    if p.startswith('0') and len(p) == 10:
        p = '255' + p[1:]
    elif p.startswith('255') and len(p) == 12:
        pass
    else:
        return p  # return as-is, might still work
    return p


@bp.route('/')
@login_required
def index():
    # Per-category cycle overrides from query string
    cycles = {}
    for cat, default in DEFAULT_CYCLES.items():
        try:
            cycles[cat] = int(request.args.get(f'cycle_{cat}', default))
        except (ValueError, TypeError):
            cycles[cat] = default

    branch_filter = request.args.get('branch_id', '')

    # For each customer × brand_category, find the date of their last invoice
    # that included a product from that category
    rows = query_db("""
        SELECT
            c.id           AS customer_id,
            c.name         AS customer_name,
            c.phone,
            b.name         AS branch_name,
            p.brand_category,
            p.model        AS last_model,
            MAX(d.created_at) AS last_purchase,
            CAST(
              (julianday('now') - julianday(MAX(d.created_at)))
              / 30.4375
            AS INTEGER) AS months_since
        FROM customers c
        JOIN documents d  ON d.customer_id = c.id AND d.doc_type = 'invoice'
        JOIN document_items di ON di.document_id = d.id
        JOIN products p   ON p.id = di.product_id
        JOIN branches b   ON b.id = d.branch_id
        WHERE p.brand_category IN ('iPhone','MacBook','iPad','JBL','Anker')
          AND c.phone IS NOT NULL
          {}
        GROUP BY c.id, p.brand_category
        ORDER BY months_since DESC
    """.format("AND d.branch_id=?" if branch_filter else ""),
        (branch_filter,) if branch_filter else ())

    # Filter to only those past their upgrade cycle
    upgrade_list = []
    for r in rows:
        cycle = cycles.get(r['brand_category'], 18)
        if r['months_since'] >= cycle:
            wa_phone = _clean_phone(r['phone'])
            upgrade_list.append({
                'customer_id':   r['customer_id'],
                'customer_name': r['customer_name'],
                'phone':         r['phone'],
                'wa_phone':      wa_phone,
                'branch_name':   r['branch_name'],
                'brand_category': r['brand_category'],
                'last_model':    r['last_model'],
                'last_purchase': r['last_purchase'],
                'months_since':  r['months_since'],
                'cycle':         cycle,
            })

    branches = query_db("SELECT * FROM branches ORDER BY name")

    return render_template('upgrade/index.html',
                           upgrade_list=upgrade_list,
                           cycles=cycles,
                           branches=branches,
                           branch_filter=branch_filter,
                           DEFAULT_CYCLES=DEFAULT_CYCLES)
