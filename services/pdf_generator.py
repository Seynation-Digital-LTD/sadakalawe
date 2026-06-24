"""
Sadakalawe PDF Generator.
Design faithfully implements the Stitch 'Pro-Sales Enterprise' design system.

Layout (top → bottom):
  5pt orange bar · Header (badge + ref + logo) · Separator
  Info cards (Bill To / Doc Details)
  Items table
  Bank info + Totals   [invoice/proforma]
  Signature block      [delivery_note]
  Terms & Conditions
  Orange footer
"""
import os
import io as _io
from io import BytesIO
from datetime import datetime
from typing import Optional

from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor

try:
    import qrcode as _qrcode
    from reportlab.lib.utils import ImageReader as _IR

    def _make_qr(data):
        qr = _qrcode.QRCode(
            version=None,
            error_correction=_qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=3,
        )
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = _io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        return _IR(buf)
except ImportError:
    _make_qr = None

# ── Stitch design-system colours ────────────────────────────────────────────
C_ORANGE     = HexColor('#F26522')   # primary-container  (orange brand)
C_ORANGE_DK  = HexColor('#a63b00')   # primary            (dark orange)
C_ORANGE_LT  = HexColor('#ffdbce')   # primary-fixed      (light orange)
C_BG_LOW     = HexColor('#F5F3F3')   # surface-container-low  (alt rows)
C_WHITE      = HexColor('#FFFFFF')   # surface-container-lowest
C_TEXT       = HexColor('#1b1c1c')   # on-surface
C_MUTED      = HexColor('#594138')   # on-surface-variant (warm brown)
C_SECONDARY  = HexColor('#5f5e5e')   # secondary          (cool grey)
C_BORDER     = HexColor('#e1bfb3')   # outline-variant    (warm peach border)
C_RED        = HexColor('#ba1a1a')   # error
C_GREEN      = HexColor('#16a34a')

# ── Page geometry ────────────────────────────────────────────────────────────
W, H = A4       # 595.27 × 841.89 pt
ML   = 40       # left  margin
MR   = W - 40   # right edge
BODY = MR - ML  # ~515 pt

# ── Logo cache ───────────────────────────────────────────────────────────────
_LOGO_CACHE: Optional[bytes] = None
_LOGO_MTIME: float = 0.0


def _logo_bytes() -> Optional[bytes]:
    global _LOGO_CACHE, _LOGO_MTIME
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'logo.png')
    if not os.path.exists(path):
        return None
    mtime = os.path.getmtime(path)
    if _LOGO_CACHE is not None and mtime == _LOGO_MTIME:
        return _LOGO_CACHE
    _LOGO_MTIME = mtime
    with open(path, 'rb') as f:
        _LOGO_CACHE = f.read()
    return _LOGO_CACHE


# ═══════════════════════════════════════════════════════════════════════════
#  PUBLIC
# ═══════════════════════════════════════════════════════════════════════════

def generate_pdf(document, customer, items, branch, created_by_name):
    buf = BytesIO()
    c   = rl_canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Sadakalawe — {document['doc_number']}")

    y = _header(c, document)
    y = _info_cards(c, y, document, customer)
    y = _items_table(c, y, items, document)

    if document['doc_type'] == 'delivery_note':
        _signature_and_notes(c, y, document)
    else:
        y = _bank_and_totals(c, y, document)
        _terms_section(c, y)

    qr_data = (
        f"https://sadakalawe.com/verify"
        f"?doc={document['doc_number']}"
        f"&amt={int(float(document.get('total', 0)))}"
        f"&date={str(document.get('created_at', ''))[:10]}"
        f"&tin=164334864"
    )
    _footer(c, branch, qr_data=qr_data)
    c.save()
    buf.seek(0)
    return buf


def generate_receipt_pdf(payment: dict, document: dict, customer: dict,
                         branch: dict) -> BytesIO:
    """
    Payment Receipt — issued when a customer pays a credit invoice (fully or partially).
    """
    buf = BytesIO()
    c   = rl_canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Receipt — {document.get('doc_number', '')}")

    # ── Orange top bar ───────────────────────────────────────────────────
    c.setFillColor(C_ORANGE)
    c.rect(0, H - 5, W, 5, fill=1, stroke=0)

    # ── Logo top-right ───────────────────────────────────────────────────
    logo = _logo_bytes()
    if logo:
        try:
            from reportlab.lib.utils import ImageReader
            c.drawImage(ImageReader(BytesIO(logo)), MR - 157, H - 5 - 24 - 46,
                        width=157, height=46, preserveAspectRatio=True)
        except Exception:
            pass

    # ── PAYMENT RECEIPT badge ────────────────────────────────────────────
    CONTENT_TOP = H - 5 - 28
    badge_text  = 'PAYMENT RECEIPT'
    c.setFont('Helvetica-Bold', 15)
    tw = c.stringWidth(badge_text, 'Helvetica-Bold', 15)
    c.setFillColor(C_GREEN if float(document.get('total', 0)) - float(payment.get('amount', 0)) <= 0.01
                   else C_ORANGE)
    c.roundRect(ML, CONTENT_TOP - 32, tw + 36, 32, 8, fill=1, stroke=0)
    c.setFillColor(C_WHITE)
    c.drawString(ML + 18, CONTENT_TOP - 32 + 10, badge_text)

    # Receipt number & date
    rn_y = CONTENT_TOP - 32 - 18
    c.setFont('Helvetica-Bold', 8); c.setFillColor(C_SECONDARY)
    c.drawString(ML, rn_y, 'RECEIPT NO.')
    c.setFont('Helvetica-Bold', 15); c.setFillColor(C_TEXT)
    c.drawString(ML, rn_y - 16, f"RCP-{payment['id']:04d}")
    c.setFont('Helvetica', 8); c.setFillColor(C_SECONDARY)
    c.drawString(ML, rn_y - 30, f"TIN: 164-334-864")

    # Separator
    sep_y = rn_y - 46
    c.setStrokeColor(C_BORDER); c.setLineWidth(0.6)
    c.line(ML, sep_y, MR, sep_y)

    # ── Info cards ───────────────────────────────────────────────────────
    y        = sep_y - 16
    CARD_H   = 90; GAP = 24; CARD_W = (BODY - GAP) / 2; PAD = 16
    card_bot = y - CARD_H

    for x in (ML, ML + CARD_W + GAP):
        c.setFillColor(C_WHITE); c.setStrokeColor(C_BORDER); c.setLineWidth(0.8)
        c.roundRect(x, card_bot, CARD_W, CARD_H, 10, fill=1, stroke=1)

    # Left: received from
    _card_header(c, ML + PAD, y - PAD - 10, CARD_W - PAD * 2, 'RECEIVED FROM')
    cy = y - PAD - 32
    c.setFont('Helvetica-Bold', 12); c.setFillColor(C_TEXT)
    c.drawString(ML + PAD, cy, _clip(customer.get('name', 'Walk-in Customer') if customer else 'Walk-in Customer', 32))
    cy -= 15
    c.setFont('Helvetica', 9); c.setFillColor(C_MUTED)
    if customer and customer.get('phone'):
        c.drawString(ML + PAD, cy, customer['phone']); cy -= 13
    if customer and customer.get('address'):
        c.drawString(ML + PAD, cy, _clip(str(customer['address']), 38))

    # Right: payment details
    rx = ML + CARD_W + GAP
    _card_header(c, rx + PAD, y - PAD - 10, CARD_W - PAD * 2, 'PAYMENT DETAILS')
    method_lbl = _METHOD_LABELS.get(payment.get('payment_method', 'cash'), 'Cash')
    detail_rows = [
        ('Payment Date', payment.get('payment_date', '')),
        ('Method',       method_lbl),
        ('Invoice Ref',  document.get('doc_number', '')),
    ]
    if payment.get('reference'):
        detail_rows.append(('Reference', str(payment['reference'])))
    dy = y - PAD - 28
    for lbl, val in detail_rows:
        c.setFont('Helvetica', 8); c.setFillColor(C_SECONDARY)
        c.drawString(rx + PAD, dy, lbl + ':')
        c.setFont('Helvetica-Bold', 8); c.setFillColor(C_TEXT)
        c.drawRightString(rx + CARD_W - PAD, dy, _clip(str(val), 26))
        dy -= 13

    y = card_bot - 28

    # ── Amount box (large, centered) ─────────────────────────────────────
    BOX_H = 80
    remaining = float(document.get('total', 0)) - float(document.get('amount_paid', 0))
    # remaining after this payment
    remaining_after = remaining  # already updated in DB when we get here

    c.setFillColor(C_BG_LOW); c.setStrokeColor(C_BORDER); c.setLineWidth(0.8)
    c.roundRect(ML, y - BOX_H, BODY, BOX_H, 12, fill=1, stroke=1)

    c.setFont('Helvetica', 10); c.setFillColor(C_SECONDARY)
    c.drawCentredString(W / 2, y - 20, 'AMOUNT RECEIVED')

    c.setFont('Helvetica-Bold', 28); c.setFillColor(C_ORANGE)
    c.drawCentredString(W / 2, y - 52, _tzs(payment['amount']))

    y = y - BOX_H - 20

    # ── Balance status ───────────────────────────────────────────────────
    is_paid_full = remaining_after <= 0.01
    if is_paid_full:
        # Green "PAID IN FULL" stamp
        c.setFont('Helvetica-Bold', 18); c.setFillColor(C_GREEN)
        c.drawCentredString(W / 2, y - 18, '✓  PAID IN FULL')
        y -= 36
    else:
        c.setFont('Helvetica', 10); c.setFillColor(C_SECONDARY)
        c.drawCentredString(W / 2, y - 16, f"Outstanding balance: {_tzs(remaining_after)}")
        y -= 30

    # ── Thank you ────────────────────────────────────────────────────────
    y -= 10
    c.setFont('Helvetica', 9); c.setFillColor(C_MUTED)
    c.drawCentredString(W / 2, y, 'Thank you for your payment! — sadakalawe.com')

    _footer(c, branch)
    c.save(); buf.seek(0)
    return buf


def generate_statement_pdf(customer: dict, docs: list) -> BytesIO:
    """Account statement — simple list of all transactions for a customer."""
    buf = BytesIO()
    c   = rl_canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Statement — {customer.get('name', '')}")

    # Top bar
    c.setFillColor(C_ORANGE)
    c.rect(0, H - 5, W, 5, fill=1, stroke=0)

    # Logo top-right
    logo = _logo_bytes()
    if logo:
        try:
            from reportlab.lib.utils import ImageReader
            c.drawImage(ImageReader(BytesIO(logo)), MR - 160, H - 5 - 24 - 46,
                        width=160, height=46, preserveAspectRatio=True)
        except Exception:
            pass

    # Title + customer
    y = H - 5 - 28
    c.setFont('Helvetica-Bold', 18)
    c.setFillColor(C_TEXT)
    c.drawString(ML, y - 16, 'ACCOUNT STATEMENT')
    y -= 32

    c.setFont('Helvetica-Bold', 13)
    c.setFillColor(C_TEXT)
    c.drawString(ML, y - 13, customer.get('name', ''))
    c.setFont('Helvetica', 9)
    c.setFillColor(C_SECONDARY)
    if customer.get('phone'):
        c.drawString(ML, y - 26, customer['phone'])
    y -= 44

    # Separator
    c.setStrokeColor(C_BORDER)
    c.setLineWidth(0.5)
    c.line(ML, y, MR, y)
    y -= 16

    # Totals summary
    total_sales   = sum(float(d.get('total', 0)) for d in docs)
    total_paid    = sum(float(d.get('amount_paid', 0)) for d in docs)
    total_balance = total_sales - total_paid

    # Summary row
    for lbl, val, col in [
        ('Total Billed', _tzs(total_sales), C_TEXT),
        ('Total Paid',   _tzs(total_paid),  C_GREEN),
        ('Balance Due',  _tzs(total_balance), C_ORANGE if total_balance > 0 else C_GREEN),
    ]:
        c.setFont('Helvetica', 9)
        c.setFillColor(C_SECONDARY)
        c.drawString(ML, y, lbl)
        c.setFont('Helvetica-Bold', 9)
        c.setFillColor(col)
        c.drawRightString(ML + 200, y, val)
        y -= 14
    y -= 12

    # Table header
    c.setFillColor(C_ORANGE)
    c.rect(ML, y - 24, BODY, 24, fill=1, stroke=0)
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(C_WHITE)
    cw = [BODY * 0.22, BODY * 0.12, BODY * 0.12, BODY * 0.18, BODY * 0.18, BODY * 0.18]
    hdrs = ['DOCUMENT', 'DATE', 'BRANCH', 'TOTAL', 'PAID', 'BALANCE']
    cx = ML
    for h_txt, cw_ in zip(hdrs, cw):
        c.drawString(cx + 6, y - 15, h_txt)
        cx += cw_
    y -= 24

    for i, d in enumerate(docs):
        if i % 2 == 0:
            c.setFillColor(C_BG_LOW)
            c.rect(ML, y - 18, BODY, 18, fill=1, stroke=0)
        c.setStrokeColor(C_BORDER)
        c.setLineWidth(0.3)
        c.line(ML, y - 18, MR, y - 18)
        bal = float(d.get('total', 0)) - float(d.get('amount_paid', 0))
        row = [d.get('doc_number', ''), d.get('created_at', '')[:10],
               d.get('branch_name', '')[:8], _tzs(d.get('total', 0)),
               _tzs(d.get('amount_paid', 0)), _tzs(bal)]
        cx = ML
        for j, (v, cw_) in enumerate(zip(row, cw)):
            if j >= 3:
                c.setFont('Helvetica-Bold', 8)
                c.setFillColor(C_ORANGE if j == 5 and bal > 0 else C_TEXT)
                c.drawRightString(cx + cw_ - 6, y - 12, str(v))
            else:
                c.setFont('Helvetica', 8)
                c.setFillColor(C_SECONDARY)
                c.drawString(cx + 6, y - 12, str(v)[:22])
            cx += cw_
        y -= 18
        if y < 60:
            break

    _footer(c, {'address': 'Bondeni Street, Opp Mega Complex, Arusha', 'name': 'Arusha'})
    c.save()
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════════════════════════════
#  SECTION RENDERERS
# ═══════════════════════════════════════════════════════════════════════════

def _header(c, document) -> float:
    """
    5pt orange bar → logo (top-right) → doc-type badge + ref number (left).
    Returns y of separator line.
    """
    # ── 5pt orange bar ───────────────────────────────────────────────────
    c.setFillColor(C_ORANGE)
    c.rect(0, H - 5, W, 5, fill=1, stroke=0)

    CONTENT_TOP = H - 5 - 28   # 28pt gap below bar

    # ── Logo top-right ───────────────────────────────────────────────────
    logo    = _logo_bytes()
    LOGO_H  = 46               # pt
    LOGO_W  = 157              # pt  (879/258 * 46 ≈ 157)
    logo_y  = CONTENT_TOP - LOGO_H

    if logo:
        try:
            from reportlab.lib.utils import ImageReader
            c.drawImage(ImageReader(BytesIO(logo)),
                        MR - LOGO_W, logo_y,
                        width=LOGO_W, height=LOGO_H,
                        preserveAspectRatio=True)
        except Exception:
            pass

    # ── Doc-type badge ───────────────────────────────────────────────────
    labels = {
        'invoice':       'INVOICE',
        'proforma':      'PROFORMA INVOICE',
        'delivery_note': 'DELIVERY NOTE',
    }
    badge_text = labels.get(document['doc_type'], 'DOCUMENT')
    BADGE_H    = 32
    BADGE_PAD  = 18
    BADGE_FS   = 15

    c.setFont('Helvetica-Bold', BADGE_FS)
    tw         = c.stringWidth(badge_text, 'Helvetica-Bold', BADGE_FS)
    badge_w    = tw + BADGE_PAD * 2

    badge_top  = CONTENT_TOP
    badge_bot  = badge_top - BADGE_H

    c.setFillColor(C_ORANGE)
    c.roundRect(ML, badge_bot, badge_w, BADGE_H, 8, fill=1, stroke=0)
    c.setFillColor(C_WHITE)
    c.setFont('Helvetica-Bold', BADGE_FS)
    c.drawString(ML + BADGE_PAD, badge_bot + 10, badge_text)

    # ── Reference No. ────────────────────────────────────────────────────
    ref_label_y = badge_bot - 18
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(C_SECONDARY)
    c.drawString(ML, ref_label_y, 'REFERENCE NO.')

    ref_num_y   = ref_label_y - 16
    c.setFont('Helvetica-Bold', 16)
    c.setFillColor(C_TEXT)
    c.drawString(ML, ref_num_y, document['doc_number'])

    # ── TIN ──────────────────────────────────────────────────────────────
    tin_y = ref_num_y - 14
    c.setFont('Helvetica', 8)
    c.setFillColor(C_SECONDARY)
    c.drawString(ML, tin_y, 'TIN: 164-334-864')

    # ── Proforma disclaimer ──────────────────────────────────────────────
    sep_y = tin_y - 16
    if document['doc_type'] == 'proforma':
        c.setFont('Helvetica-BoldOblique', 8)
        c.setFillColor(C_RED)
        c.drawString(ML, sep_y + 8,
                     'This is NOT a Tax Invoice — For quotation purposes only.')
        sep_y -= 12

    # ── Separator ────────────────────────────────────────────────────────
    c.setStrokeColor(C_BORDER)
    c.setLineWidth(0.6)
    c.line(ML, sep_y, MR, sep_y)

    return sep_y - 16   # ready for info cards


def _info_cards(c, start_y: float, document, customer) -> float:
    """Bill-To card (left) + Document Details card (right). Returns y below cards."""
    top      = start_y
    GAP      = 24
    CARD_W   = (BODY - GAP) / 2    # ~245pt each
    PAD      = 16                   # internal card padding
    RADIUS   = 10

    left_x  = ML
    right_x = ML + CARD_W + GAP

    # ── Pre-compute customer name wrapping so we can set CARD_H ─────────
    NAME_FONT = 'Helvetica-Bold'
    NAME_SIZE = 12
    NAME_LINE_H = 15
    avail_name_w = CARD_W - PAD * 2 - 4   # slight buffer from card edge

    name_lines = []
    if customer and customer.get('name'):
        name_lines = _text_wrap(c, str(customer['name']), NAME_FONT, NAME_SIZE, avail_name_w)

    extra_h = max(0, len(name_lines) - 1) * NAME_LINE_H
    CARD_H  = 106 + extra_h
    card_bot = top - CARD_H

    # ── Draw card backgrounds ────────────────────────────────────────────
    for x in (left_x, right_x):
        c.setFillColor(C_WHITE)
        c.setStrokeColor(C_BORDER)
        c.setLineWidth(0.8)
        c.roundRect(x, card_bot, CARD_W, CARD_H, RADIUS, fill=1, stroke=1)

    # ── Left card: Bill To ───────────────────────────────────────────────
    label_text = 'DELIVER TO' if document['doc_type'] == 'delivery_note' else 'BILL TO'
    label_y    = top - PAD - 10
    _card_header(c, left_x + PAD, label_y, CARD_W - PAD * 2, label_text)

    cy = label_y - 22     # below the header line
    if name_lines:
        c.setFont(NAME_FONT, NAME_SIZE)
        c.setFillColor(C_TEXT)
        for line in name_lines:
            c.drawString(left_x + PAD, cy, line)
            cy -= NAME_LINE_H
        cy -= 2   # small extra gap after name block
        c.setFont('Helvetica', 9)
        c.setFillColor(C_MUTED)
        for key in ('address', 'phone', 'tin'):
            val = (customer.get(key) or '').strip()
            if val and cy > card_bot + 8:
                prefix = 'TIN: ' if key == 'tin' else ''
                c.drawString(left_x + PAD, cy, _clip(prefix + val, 40))
                cy -= 13
    else:
        c.setFont('Helvetica', 10)
        c.setFillColor(C_SECONDARY)
        c.drawString(left_x + PAD, cy, 'Walk-in Customer')

    # ── Right card: Document Details ─────────────────────────────────────
    _card_header(c, right_x + PAD, label_y, CARD_W - PAD * 2, 'DOCUMENT DETAILS')

    dy = label_y - 18
    rows = [
        ('Date Issued', _fmt_date(document['created_at'])),
        ('Branch',      document.get('branch_name', '')),
    ]
    if document.get('credit_due_date'):
        rows.append(('Due Date', str(document['credit_due_date'])))
    if document['doc_type'] == 'proforma':
        rows.append(('Valid For', f"{document.get('validity_days', 7)} days"))
    rows.append(('Payment', _payment_label(document)))

    for lbl, val in rows:
        c.setFont('Helvetica', 8)
        c.setFillColor(C_SECONDARY)
        c.drawString(right_x + PAD, dy, lbl + ':')
        c.setFont('Helvetica-Bold', 8)
        c.setFillColor(C_TEXT)
        c.drawRightString(right_x + CARD_W - PAD, dy, _clip(str(val), 26))
        dy -= 13
        if dy < card_bot + 8:
            break

    return card_bot - 20   # gap before table


def _items_table(c, start_y: float, items: list, document: dict) -> float:
    """
    Orange header + alternating rows matching Stitch table style.
    Returns y below the table.
    """
    y         = start_y
    doc_type  = document['doc_type']
    HDR_H     = 30
    ROW_H     = 28

    # Detect if any item carries a discount so we can add the DISC% column
    has_discount = any(float(item.get('discount_pct', 0) or 0) > 0 for item in items)

    # Column definitions
    if doc_type == 'delivery_note':
        cols = [
            ('ITEM DESCRIPTION', BODY - 80, 'left'),
            ('QTY',              80,         'center'),
        ]
    elif has_discount:
        desc_w = BODY - 60 - 110 - 54 - 90
        cols = [
            ('ITEM DESCRIPTION', desc_w, 'left'),
            ('QTY',              60,     'center'),
            ('UNIT PRICE',       110,    'right'),
            ('DISC%',            54,     'center'),
            ('AMOUNT',           90,     'right'),
        ]
    else:
        desc_w = BODY - 64 - 120 - 110
        cols = [
            ('ITEM DESCRIPTION', desc_w, 'left'),
            ('QTY',              64,     'center'),
            ('UNIT PRICE',       120,    'right'),
            ('AMOUNT',           110,    'right'),
        ]

    # ── Orange header row ────────────────────────────────────────────────
    c.setFillColor(C_ORANGE)
    c.rect(ML, y - HDR_H, BODY, HDR_H, fill=1, stroke=0)

    cx = ML
    for title, cw, align in cols:
        _cell_text(c, cx, y - HDR_H, cw, HDR_H, title, 'Helvetica-Bold', 9, C_WHITE, align, pad=10)
        cx += cw
    y -= HDR_H

    # ── Data rows ────────────────────────────────────────────────────────
    for i, item in enumerate(items):
        desc  = str(item.get('description') or '')
        parts = [p.strip() for p in desc.split('\n') if p.strip()]
        main  = parts[0] if parts else ''
        subs  = parts[1:]
        rh    = max(ROW_H, 16 + len(subs) * 12 + 8)

        bg = C_BG_LOW if i % 2 == 0 else C_WHITE
        c.setFillColor(bg)
        c.rect(ML, y - rh, BODY, rh, fill=1, stroke=0)

        # Row bottom border
        c.setStrokeColor(C_BORDER)
        c.setLineWidth(0.3)
        c.line(ML, y - rh, MR, y - rh)

        # Description (bold main line + light sub-lines)
        text_y = y - 16
        c.setFont('Helvetica-Bold', 9.5)
        c.setFillColor(C_TEXT)
        c.drawString(ML + 10, text_y, _clip(main, 52))
        for sl in subs:
            text_y -= 12
            c.setFont('Helvetica', 8)
            c.setFillColor(C_SECONDARY)
            c.drawString(ML + 18, text_y, _clip(sl, 52))

        # Numeric cells
        qty      = float(item.get('quantity', 1) or 1)
        price    = float(item.get('unit_price', 0) or 0)
        total    = float(item.get('line_total', 0) or 0)
        disc_pct = float(item.get('discount_pct', 0) or 0)
        qty_s    = str(int(qty)) if qty == int(qty) else f'{qty:.2f}'

        col_idx = 0
        cx = ML + cols[col_idx][1]; col_idx += 1

        # QTY
        c.setFont('Helvetica', 9.5)
        c.setFillColor(C_TEXT)
        c.drawCentredString(cx + cols[col_idx][1] / 2, y - 16, qty_s)
        cx += cols[col_idx][1]; col_idx += 1

        if doc_type != 'delivery_note':
            # UNIT PRICE — strikethrough when discounted
            price_x = cx + cols[col_idx][1] - 10
            price_y = y - 16
            if disc_pct > 0:
                c.setFont('Helvetica', 8.5)
                c.setFillColor(C_SECONDARY)
                c.drawRightString(price_x, price_y, _tzs(price))
                tw = c.stringWidth(_tzs(price), 'Helvetica', 8.5)
                mid_y = price_y + 4
                c.setStrokeColor(C_SECONDARY)
                c.setLineWidth(0.7)
                c.line(price_x - tw, mid_y, price_x, mid_y)
            else:
                c.setFont('Helvetica', 9)
                c.setFillColor(C_SECONDARY)
                c.drawRightString(price_x, price_y, _tzs(price))
            cx += cols[col_idx][1]; col_idx += 1

            # DISC% column (only present when has_discount)
            if has_discount:
                disc_cx = cx + cols[col_idx][1] / 2
                if disc_pct > 0:
                    c.setFont('Helvetica-Bold', 9)
                    c.setFillColor(C_ORANGE)
                    c.drawCentredString(disc_cx, y - 16, f'{disc_pct:g}%')
                else:
                    c.setFont('Helvetica', 8)
                    c.setFillColor(C_SECONDARY)
                    c.drawCentredString(disc_cx, y - 16, '—')
                cx += cols[col_idx][1]; col_idx += 1

            # AMOUNT
            c.setFont('Helvetica-Bold', 9.5)
            c.setFillColor(C_TEXT)
            c.drawRightString(cx + cols[col_idx][1] - 10, y - 16, _tzs(total))

        y -= rh

    # Bottom rule
    c.setStrokeColor(C_ORANGE)
    c.setLineWidth(1.0)
    c.line(ML, y, MR, y)

    return y - 18


def _bank_and_totals(c, start_y: float, document: dict) -> float:
    """
    Left half: Payment Information with orange left-border.
    Right ~40%: Subtotal / VAT / Total.
    Returns y below this section.
    """
    y        = start_y
    SECTION_H = 110   # min height for this block
    HALF     = BODY * 0.52
    RIGHT_X  = ML + HALF + 16
    RIGHT_W  = BODY - HALF - 16

    # ── Bank info (left, with 4pt orange left border) ────────────────────
    # Orange left accent bar
    c.setFillColor(C_ORANGE)
    c.rect(ML, y - SECTION_H, 4, SECTION_H, fill=1, stroke=0)

    bx = ML + 14    # text start after bar
    by = y - 12

    c.setFont('Helvetica-Bold', 9)
    c.setFillColor(C_TEXT)
    c.drawString(bx, by, 'PAYMENT INFORMATION')
    by -= 18

    bank_rows = [
        ('Bank',           'NMB Bank PLC'),
        ('Account Name',   'Sadakalawe Enterprises'),
        ('Account No.',    '42710089645'),
        ('Swift Code',     'NMBTZTZ'),
    ]
    for lbl, val in bank_rows:
        c.setFont('Helvetica', 8.5)
        c.setFillColor(C_SECONDARY)
        c.drawString(bx, by, lbl + ':')
        c.setFont('Helvetica-Bold', 8.5)
        c.setFillColor(C_TEXT)
        c.drawString(bx + 80, by, val)
        by -= 13

    by -= 6
    c.setFont('Helvetica-Oblique', 7.5)
    c.setFillColor(C_SECONDARY)
    c.drawString(bx, by, 'Please use the Invoice Number as the payment reference.')

    # ── Totals (right) ───────────────────────────────────────────────────
    ty = y - 10
    LINE_H = 22

    def tot_row(label, val_str, is_grand=False):
        nonlocal ty
        if is_grand:
            c.setFont('Helvetica-Bold', 17)
            c.setFillColor(C_ORANGE)
            c.drawString(RIGHT_X, ty - LINE_H + 5, label)
            c.drawRightString(RIGHT_X + RIGHT_W, ty - LINE_H + 5, val_str)
        else:
            c.setFillColor(C_BORDER)
            c.setStrokeColor(C_BORDER)
            c.setLineWidth(0.4)
            c.line(RIGHT_X, ty - LINE_H, RIGHT_X + RIGHT_W, ty - LINE_H)
            c.setFont('Helvetica', 9)
            c.setFillColor(C_SECONDARY)
            c.drawString(RIGHT_X, ty - LINE_H + 4, label)
            c.setFont('Helvetica-Bold', 9)
            c.setFillColor(C_TEXT)
            c.drawRightString(RIGHT_X + RIGHT_W, ty - LINE_H + 4, val_str)
        ty -= LINE_H + 4

    tot_row('Subtotal', _tzs(document.get('subtotal', 0)))
    if document.get('is_vat') and float(document.get('vat_amount', 0) or 0) > 0:
        rate = document.get('vat_rate', 18)
        tot_row(f"VAT ({int(rate)}%)", _tzs(document.get('vat_amount', 0)))
    ty -= 4
    tot_row('Total', _tzs(document.get('total', 0)), is_grand=True)

    return min(y - SECTION_H, ty) - 20


def _terms_section(c, y: float):
    """Terms & Conditions block — only if there's room."""
    if y < 110:
        return
    y -= 4

    c.setFont('Helvetica-Bold', 9)
    c.setFillColor(C_TEXT)
    c.drawString(ML, y, 'Terms & Conditions')
    y -= 16

    terms = [
        'Goods remain the property of Sadakalawe Enterprises until paid in full.',
        'Full payment is expected within 14 days of invoice issuance.',
        'A 2% interest charge will be applied to overdue payments monthly.',
    ]
    for term in terms:
        if y < 60:
            break
        c.setFont('Helvetica', 8)
        c.setFillColor(C_SECONDARY)
        c.drawString(ML + 6, y, '•  ' + term)
        y -= 13


def _signature_and_notes(c, y: float, document: dict):
    """Delivery note: signature line + optional notes."""
    y -= 10

    # Signature lines
    SIG_W = 200
    c.setStrokeColor(C_SECONDARY)
    c.setLineWidth(0.8)
    c.line(ML, y, ML + SIG_W, y)
    c.setFont('Helvetica', 8)
    c.setFillColor(C_SECONDARY)
    c.drawString(ML, y - 12, 'Recipient Name & Signature')

    c.line(ML + SIG_W + 32, y, ML + SIG_W + 32 + 130, y)
    c.drawString(ML + SIG_W + 32, y - 12, 'Date Received')

    if document.get('notes'):
        y -= 36
        c.setFont('Helvetica-Bold', 8)
        c.setFillColor(C_TEXT)
        c.drawString(ML, y, 'Notes:')
        c.setFont('Helvetica', 8)
        c.setFillColor(C_SECONDARY)
        c.drawString(ML + 46, y, _clip(str(document['notes']), 80))


def _footer(c, branch: dict, qr_data: str = None):
    """Full-width orange footer — company name left, contact right, optional QR top-right."""
    FH = 54
    QR_SIZE = 80

    # QR code just above the footer bar (right-aligned), white background box
    qr_drawn = False
    if qr_data and _make_qr is not None:
        try:
            qr_img = _make_qr(qr_data)
            qr_x = MR - QR_SIZE
            qr_y = FH + 4
            c.setFillColor(C_WHITE)
            c.rect(qr_x - 2, qr_y - 2, QR_SIZE + 4, QR_SIZE + 4, fill=1, stroke=0)
            c.drawImage(qr_img, qr_x, qr_y, width=QR_SIZE, height=QR_SIZE,
                        preserveAspectRatio=True)
            qr_drawn = True
        except Exception:
            pass

    c.setFillColor(C_ORANGE)
    c.rect(0, 0, W, FH, fill=1, stroke=0)

    # Left: company name + address
    c.setFont('Helvetica-Bold', 9.5)
    c.setFillColor(C_WHITE)
    c.drawString(ML, FH - 16, 'Sadakalawe Enterprises')
    c.setFont('Helvetica', 8)
    addr = branch.get('address', 'Bondeni Street, Opp Mega Complex, Arusha')
    c.drawString(ML, FH - 30, addr)

    # Right: phone / website / TIN (shift left to not overlap QR)
    c.setFont('Helvetica', 8)
    c.setFillColor(C_WHITE)
    right_text_x = MR - QR_SIZE - 10 if qr_drawn else MR
    c.drawRightString(right_text_x, FH - 16, '+255 768 596 006  |  info@sadakalawe.com')
    c.drawRightString(right_text_x, FH - 30, 'www.sadakalawe.com  |  TIN: 164-334-864')


# ═══════════════════════════════════════════════════════════════════════════
#  DRAW HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _card_header(c, x, y, width, text):
    """Orange uppercase label + thin orange underline inside a card."""
    c.setFont('Helvetica-Bold', 8.5)
    c.setFillColor(C_ORANGE_DK)
    c.drawString(x, y, text)
    # Thin orange underline
    c.setStrokeColor(C_ORANGE_LT)
    c.setLineWidth(0.8)
    c.line(x, y - 6, x + width, y - 6)


def _cell_text(c, cell_x, cell_y, cell_w, cell_h, text,
               font, size, color, align, pad=8):
    """Draw text inside a table cell."""
    c.setFont(font, size)
    c.setFillColor(color)
    ty = cell_y + cell_h / 2 - 3
    if align == 'left':
        c.drawString(cell_x + pad, ty, text)
    elif align == 'right':
        c.drawRightString(cell_x + cell_w - pad, ty, text)
    else:
        c.drawCentredString(cell_x + cell_w / 2, ty, text)


def _clip(text: str, maxlen: int) -> str:
    return text[:maxlen] + ('…' if len(text) > maxlen else '')


def _text_wrap(c, text: str, font_name: str, font_size: float, max_width: float) -> list:
    """Split text into lines that each fit within max_width."""
    words = str(text).split()
    if not words:
        return ['']
    lines = []
    current = words[0]
    for word in words[1:]:
        test = current + ' ' + word
        if c.stringWidth(test, font_name, font_size) <= max_width:
            current = test
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _tzs(val) -> str:
    try:
        n = float(val)
        return f"TZS {n:,.0f}"
    except (TypeError, ValueError):
        return 'TZS 0'


def _fmt_date(dt_str) -> str:
    months = ['Jan','Feb','Mar','Apr','May','Jun',
              'Jul','Aug','Sep','Oct','Nov','Dec']
    try:
        dt = datetime.fromisoformat(str(dt_str)[:19])
        return f"{dt.day:02d} {months[dt.month - 1]} {dt.year}"
    except Exception:
        return str(dt_str)[:10] if dt_str else ''


_METHOD_LABELS = {
    'cash':          'Cash',
    'card':          'Card / POS',
    'mpesa':         'M-Pesa',
    'airtel_money':  'Airtel Money',
    'mixx_by_yas':   'Mixx by Yas',
    'halopesa':      'Halopesa',
    'bank_transfer': 'Bank Transfer',
    'credit':        'Credit (Pay Later)',
    'other':         'Other',
}


def _payment_label(document) -> str:
    status = document.get('payment_status', 'paid')
    if status == 'credit':
        return 'Credit (Pay Later)'
    if status == 'partial':
        return 'Partially Paid'
    method = document.get('payment_method', 'cash') or 'cash'
    return _METHOD_LABELS.get(method, method.replace('_', ' ').title())


def _status_label(document) -> str:
    status = document.get('payment_status', 'paid')
    return {'paid': 'Paid', 'credit': 'Credit (Unpaid)', 'partial': 'Partially Paid'}.get(status, status.title())
