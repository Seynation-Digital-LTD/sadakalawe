import urllib.parse
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from database import query_db
from config import VIP_TIERS

bp = Blueprint('campaigns', __name__, url_prefix='/campaigns')


def _clean_phone(phone):
    if not phone:
        return None
    digits = ''.join(c for c in str(phone) if c.isdigit())
    if digits.startswith('0') and len(digits) >= 9:
        digits = '255' + digits[1:]
    elif digits.startswith('7') or digits.startswith('6'):
        digits = '255' + digits
    return digits if len(digits) >= 10 else None


def _get_tier(spend):
    spend = float(spend or 0)
    for t in VIP_TIERS:
        if spend >= t['min_spend']:
            return t
    return VIP_TIERS[-1]


@bp.route('/')
@login_required
def index():
    branches   = query_db("SELECT id, name FROM branches ORDER BY name")
    categories = query_db("SELECT id, name FROM product_categories ORDER BY sort_order")
    default_msg = (
        "Habari {name}!\n\n"
        "Tuna bidhaa mpya na ofa maalum kwako leo. "
        "Karibu Sadakalawe Enterprises — tunakungojea! 🎉\n\n"
        "📞 +255 768 596 006\n"
        "🌐 www.sadakalawe.com"
    )
    return render_template('campaigns/index.html',
                           branches=branches,
                           categories=categories,
                           vip_tiers=VIP_TIERS,
                           default_msg=default_msg)


@bp.route('/preview', methods=['POST'])
@login_required
def preview():
    """AJAX — filter customers and return list for campaign."""
    data       = request.get_json(force=True) or {}
    tier_names = data.get('tiers', [])
    branch_id  = data.get('branch_id') or None
    cat_ids    = [int(x) for x in data.get('category_ids', []) if x]
    lp_filter  = data.get('last_purchase', 'any')   # '30','60','90','180','never','any'
    phone_only = data.get('has_phone', True)

    conds  = []
    params = []

    if phone_only:
        conds.append("c.phone IS NOT NULL AND trim(c.phone) != ''")

    if branch_id:
        conds.append("c.branch_id = ?")
        params.append(branch_id)
    elif not current_user.is_admin and current_user.branch_id:
        conds.append("c.branch_id = ?")
        params.append(current_user.branch_id)

    where = ("AND " + " AND ".join(conds)) if conds else ""

    sql = f"""
        SELECT DISTINCT
            c.id, c.name, c.phone,
            b.name AS branch_name,
            COALESCE((
                SELECT SUM(d2.total)
                FROM documents d2
                WHERE d2.customer_id=c.id AND d2.doc_type='invoice' AND d2.status='final'
            ),0) AS lifetime_spend,
            (
                SELECT MAX(d3.created_at)
                FROM documents d3
                WHERE d3.customer_id=c.id AND d3.doc_type='invoice' AND d3.status='final'
            ) AS last_purchase_at
        FROM customers c
        LEFT JOIN branches b ON b.id=c.branch_id
        WHERE 1=1 {where}
        ORDER BY c.name
    """
    rows = query_db(sql, params)

    # --- tier filter ---
    if tier_names:
        rows = [r for r in rows if _get_tier(r['lifetime_spend'])['name'] in tier_names]

    # --- last-purchase filter ---
    if lp_filter and lp_filter != 'any':
        from datetime import datetime
        now = datetime.now()
        if lp_filter == 'never':
            rows = [r for r in rows if not r['last_purchase_at']]
        else:
            days = int(lp_filter)
            def _recent(r):
                if not r['last_purchase_at']:
                    return False
                try:
                    d = datetime.fromisoformat(str(r['last_purchase_at'])[:19])
                    return (now - d).days <= days
                except Exception:
                    return False
            rows = [r for r in rows if _recent(r)]

    # --- category filter (bought that category) ---
    if cat_ids:
        buyer_ids = set()
        for cid in cat_ids:
            res = query_db("""
                SELECT DISTINCT d.customer_id
                FROM document_items di
                JOIN documents d ON d.id=di.document_id
                JOIN products p ON p.id=di.product_id
                WHERE p.category_id=?
                  AND d.doc_type='invoice' AND d.status='final'
                  AND d.customer_id IS NOT NULL
            """, (cid,))
            for r2 in res:
                buyer_ids.add(r2['customer_id'])
        rows = [r for r in rows if r['id'] in buyer_ids]

    # Build output
    out = []
    for r in rows:
        phone_clean = _clean_phone(r['phone'])
        tier = _get_tier(r['lifetime_spend'])
        out.append({
            'id':              r['id'],
            'name':            r['name'],
            'phone':           r['phone'] or '',
            'phone_clean':     phone_clean or '',
            'branch':          r['branch_name'] or '',
            'lifetime_spend':  r['lifetime_spend'],
            'tier_name':       tier['name'],
            'tier_color':      tier['color'],
            'tier_icon':       tier['icon'],
            'last_purchase':   (r['last_purchase_at'] or '')[:10],
        })

    return jsonify(customers=out, count=len(out))


@bp.route('/wa-link')
@login_required
def wa_link():
    """Build a WhatsApp link for a single customer with the given message."""
    phone   = request.args.get('phone', '')
    name    = request.args.get('name', '')
    message = request.args.get('message', '')
    msg     = message.replace('{name}', name)
    encoded = urllib.parse.quote(msg)
    digits  = _clean_phone(phone)
    if not digits:
        return jsonify(error='Invalid phone'), 400
    return jsonify(url=f"https://wa.me/{digits}?text={encoded}")
