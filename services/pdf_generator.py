"""
Sadakalawe PDF Generator — premium document design.
Matches brand: #F26522 orange, clean white body, strong typography.
"""
import os
from io import BytesIO
from datetime import datetime
from typing import Optional

from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor

# ── Colour palette ─────────────────────────────────────────────────────────
C_ORANGE      = HexColor('#F26522')
C_ORANGE_DK   = HexColor('#D4511A')
C_ORANGE_LT   = HexColor('#FEF0E8')
C_BLACK       = HexColor('#111111')
C_DARK        = HexColor('#2D2D2D')
C_BODY        = HexColor('#444444')
C_MUTED       = HexColor('#888888')
C_RULE        = HexColor('#E0E0E0')
C_ROW_ALT     = HexColor('#F9F9F9')
C_BOX_BG      = HexColor('#F5F6F8')
C_WHITE       = HexColor('#FFFFFF')
C_RED         = HexColor('#C0392B')

# ── Page geometry ───────────────────────────────────────────────────────────
W, H = A4          # 595.27 × 841.89 pt
ML   = 36          # left margin
MR   = W - 36      # right edge
BODY = MR - ML     # 523.27 pt usable width

# ── Logo cache ──────────────────────────────────────────────────────────────
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

    _header(c, document)
    _company(c)
    y = _info_cards(c, document, customer)
    y = _table(c, y, items, document)
    y = _totals(c, y, document)
    if document['doc_type'] in ('invoice', 'proforma'):
        _payment(c, y)
    elif document['doc_type'] == 'delivery_note':
        _signature_line(c, y)
    if document.get('notes'):
        _notes(c, document['notes'])
    _footer(c, branch)

    c.save()
    buf.seek(0)
    return buf


def generate_statement_pdf(customer: dict, docs: list) -> BytesIO:
    """Account statement PDF for a customer — lists all credit transactions."""
    buf = BytesIO()
    c   = rl_canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Statement — {customer.get('name', '')}")

    # Orange top bar
    c.setFillColor(C_ORANGE)
    c.rect(0, H - 5, W, 5, fill=1, stroke=0)

    # Header text
    c.setFont('Helvetica-Bold', 18)
    c.setFillColor(C_BLACK)
    c.drawString(ML, H - 40, 'ACCOUNT STATEMENT')
    c.setFont('Helvetica', 8.5)
    c.setFillColor(C_MUTED)
    c.drawString(ML, H - 53, f"Generated: {_fmt_date(datetime.now().isoformat())}")

    # Logo top-right
    logo = _logo_bytes()
    if logo:
        try:
            from reportlab.lib.utils import ImageReader
            c.drawImage(ImageReader(BytesIO(logo)), MR - 140, H - 60,
                        width=140, height=46, preserveAspectRatio=True)
        except Exception:
            pass

    # Company info right
    c.setFont('Helvetica-Bold', 10)
    c.setFillColor(C_DARK)
    c.drawRightString(MR, H - 72, 'SADAKALAWE ENTERPRISES')
    c.setFont('Helvetica', 8)
    c.setFillColor(C_MUTED)
    c.drawRightString(MR, H - 83, 'TIN: 164-334-864  ·  +255 768 596 006')

    # Separator
    c.setStrokeColor(C_RULE)
    c.setLineWidth(0.5)
    c.line(ML, H - 92, MR, H - 92)

    # Customer info box
    y = H - 108
    _rounded_box(c, ML, y - 60, BODY * 0.55, 60, C_BOX_BG)
    _label(c, ML + 14, y - 12, 'CUSTOMER', C_ORANGE)
    c.setFont('Helvetica-Bold', 12)
    c.setFillColor(C_BLACK)
    c.drawString(ML + 14, y - 26, customer.get('name', ''))
    c.setFont('Helvetica', 8.5)
    c.setFillColor(C_BODY)
    for i, val in enumerate([customer.get('phone', ''), customer.get('address', '')]):
        if val:
            c.drawString(ML + 14, y - 38 - i * 11, val)

    # Totals box right
    total_sales   = sum(float(d.get('total', 0)) for d in docs)
    total_paid    = sum(float(d.get('amount_paid', 0)) for d in docs)
    total_balance = total_sales - total_paid

    rx = ML + BODY * 0.6
    rw = BODY * 0.4
    _rounded_box(c, rx, y - 60, rw, 60, C_BOX_BG)
    _label(c, rx + 14, y - 12, 'SUMMARY', C_ORANGE)
    for i, (lbl, val, color) in enumerate([
        ('Total Billed', _tzs(total_sales), C_DARK),
        ('Total Paid',   _tzs(total_paid),  HexColor('#16a34a')),
        ('Balance Due',  _tzs(total_balance), C_ORANGE if total_balance > 0 else HexColor('#16a34a')),
    ]):
        ry = y - 24 - i * 13
        c.setFont('Helvetica', 8)
        c.setFillColor(C_MUTED)
        c.drawString(rx + 14, ry, lbl)
        c.setFont('Helvetica-Bold', 8.5)
        c.setFillColor(color)
        c.drawRightString(rx + rw - 14, ry, val)

    # Table header
    ty = y - 76
    c.setFillColor(C_ORANGE)
    c.rect(ML, ty - 20, BODY, 20, fill=1, stroke=0)
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(C_WHITE)
    cols_w = [BODY * 0.22, BODY * 0.12, BODY * 0.12, BODY * 0.18, BODY * 0.18, BODY * 0.18]
    headers = ['DOC NUMBER', 'DATE', 'BRANCH', 'TOTAL', 'PAID', 'BALANCE']
    cx = ML
    for title, cw in zip(headers, cols_w):
        c.drawString(cx + 6, ty - 13, title)
        cx += cw

    # Table rows
    ty -= 20
    for i, d in enumerate(docs):
        row_h = 18
        if i % 2 == 1:
            c.setFillColor(C_ROW_ALT)
            c.rect(ML, ty - row_h, BODY, row_h, fill=1, stroke=0)
        c.setStrokeColor(C_RULE)
        c.setLineWidth(0.3)
        c.line(ML, ty - row_h, MR, ty - row_h)

        bal = float(d.get('total', 0)) - float(d.get('amount_paid', 0))
        row_data = [
            d.get('doc_number', ''),
            d.get('created_at', '')[:10],
            d.get('branch_name', ''),
            _tzs(d.get('total', 0)),
            _tzs(d.get('amount_paid', 0)),
            _tzs(bal),
        ]
        cx = ML
        for j, (val, cw) in enumerate(zip(row_data, cols_w)):
            if j >= 3:
                c.setFont('Helvetica-Bold', 8.5)
                c.setFillColor(C_ORANGE if (j == 5 and bal > 0) else C_DARK)
                c.drawRightString(cx + cw - 6, ty - 12, str(val))
            else:
                c.setFont('Helvetica', 8.5)
                c.setFillColor(C_BODY)
                c.drawString(cx + 6, ty - 12, str(val)[:22])
            cx += cw
        ty -= row_h
        if ty < 60:
            break

    # Orange footer
    c.setFillColor(C_ORANGE)
    c.rect(0, 0, W, 26, fill=1, stroke=0)
    c.setFont('Helvetica', 7.5)
    c.setFillColor(C_WHITE)
    footer = 'Bondeni Street, Opp Mega Complex, Arusha  ·  +255 768 596 006  ·  www.sadakalawe.com  ·  TIN 164-334-864'
    fw = c.stringWidth(footer, 'Helvetica', 7.5)
    c.drawString((W - fw) / 2, 9, footer)

    c.save()
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════════════════════════════
#  SECTIONS
# ═══════════════════════════════════════════════════════════════════════════

def _header(c, document):
    """Top accent bar + document-type badge."""
    # ── Top accent bar (full-width, 5pt tall) ────────────────────────────
    c.setFillColor(C_ORANGE)
    c.rect(0, H - 5, W, 5, fill=1, stroke=0)

    # ── Document-type badge ──────────────────────────────────────────────
    labels = {
        'invoice':       'INVOICE',
        'proforma':      'PROFORMA  INVOICE',
        'delivery_note': 'DELIVERY  NOTE',
    }
    text = labels.get(document['doc_type'], 'DOCUMENT')
    bw = 195 if document['doc_type'] != 'invoice' else 155
    bh = 34
    bx, by = ML, H - 50
    c.setFillColor(C_ORANGE)
    c.roundRect(bx, by, bw, bh, 6, fill=1, stroke=0)
    c.setFillColor(C_WHITE)
    c.setFont('Helvetica-Bold', 11.5)
    c.drawCentredString(bx + bw / 2, by + 11, text)

    # ── Doc number below badge (small, muted) ────────────────────────────
    c.setFont('Helvetica', 7.5)
    c.setFillColor(C_MUTED)
    c.drawString(ML, by - 12, document['doc_number'])


def _company(c):
    """Logo + company details, top-right."""
    logo = _logo_bytes()
    lw, lh = 160, 52
    lx = MR - lw
    ly = H - lh - 14

    if logo:
        try:
            from reportlab.lib.utils import ImageReader
            c.drawImage(ImageReader(BytesIO(logo)), lx, ly,
                        width=lw, height=lh, preserveAspectRatio=True)
        except Exception:
            pass

    # Contact details right-aligned
    c.setFont('Helvetica-Bold', 11)
    c.setFillColor(C_BLACK)
    c.drawRightString(MR, H - lh - 26, 'TIN: 164-334-864')

    c.setFont('Helvetica', 8.5)
    c.setFillColor(C_BODY)
    c.drawRightString(MR, H - lh - 39, '+255 768 596 006')
    c.drawRightString(MR, H - lh - 50, 'www.sadakalawe.com')

    # Thin horizontal separator under header zone
    c.setStrokeColor(C_RULE)
    c.setLineWidth(0.5)
    c.line(ML, H - 160, MR, H - 160)


def _info_cards(c, document, customer) -> float:
    """Two info boxes: Bill-To (left) · Document Details (right)."""
    top = H - 168
    card_h = 90
    gap   = 12

    left_w  = BODY * 0.55
    right_w = BODY - left_w - gap

    # ── Left card: Bill To ───────────────────────────────────────────────
    _rounded_box(c, ML, top - card_h, left_w, card_h, C_BOX_BG)

    y = top - 16
    to_label = 'DELIVER TO' if document['doc_type'] == 'delivery_note' else 'BILL TO'
    _label(c, ML + 14, y, to_label, C_ORANGE)
    y -= 14

    if customer and customer.get('name'):
        c.setFont('Helvetica-Bold', 11)
        c.setFillColor(C_BLACK)
        _text_wrap(c, ML + 14, y, str(customer['name']), 'Helvetica-Bold', 10, left_w - 28)
        y -= 14
        c.setFont('Helvetica', 8.5)
        c.setFillColor(C_BODY)
        for key, prefix in [('address', ''), ('phone', 'Tel: '), ('tin', 'TIN: ')]:
            val = (customer.get(key) or '').strip()
            if val:
                _text_wrap(c, ML + 14, y, prefix + val, 'Helvetica', 8.5, left_w - 28)
                y -= 12
    else:
        c.setFont('Helvetica-Bold', 10)
        c.setFillColor(C_DARK)
        c.drawString(ML + 14, y, 'Walk-in Customer')

    # ── Right card: Doc details ──────────────────────────────────────────
    rx = ML + left_w + gap
    _rounded_box(c, rx, top - card_h, right_w, card_h, C_BOX_BG)

    dy = top - 16
    _label(c, rx + 14, dy, 'DOCUMENT DETAILS', C_ORANGE)
    dy -= 13

    rows = [
        ('No.', document['doc_number']),
        ('Date', _fmt_date(document['created_at'])),
        ('Branch', document.get('branch_name', '')),
    ]
    if document['doc_type'] == 'proforma':
        rows.append(('Valid for', f"{document.get('validity_days', 7)} days"))
    if document.get('is_vat') and document.get('efd_reference'):
        rows.append(('EFD Ref', document['efd_reference']))

    for lbl, val in rows:
        c.setFont('Helvetica', 8)
        c.setFillColor(C_MUTED)
        c.drawString(rx + 14, dy, lbl)
        c.setFont('Helvetica-Bold', 8)
        c.setFillColor(C_DARK)
        c.drawRightString(rx + right_w - 14, dy, str(val)[:32])
        dy -= 12

    # Proforma disclaimer
    if document['doc_type'] == 'proforma':
        notice_y = top - card_h - 14
        c.setFont('Helvetica-Bold', 7.5)
        c.setFillColor(C_RED)
        c.drawString(ML, notice_y, '⚠  This is NOT a Tax Invoice — For quotation purposes only.')
        return notice_y - 10

    return top - card_h - 14


def _table(c, start_y: float, items: list, document: dict) -> float:
    """Items table with styled header and clean rows."""
    doc_type = document['doc_type']
    y = start_y - 4

    # ── Column layout ────────────────────────────────────────────────────
    if doc_type == 'delivery_note':
        cols = [('ITEM', BODY - 80, 'left'), ('QTY', 80, 'center')]
    else:
        cols = [
            ('ITEM',       BODY - 60 - 120 - 120, 'left'),
            ('QTY',        60,   'center'),
            ('UNIT PRICE', 120,  'right'),
            ('AMOUNT',     120,  'right'),
        ]

    row_base_h = 22
    hdr_h      = 22

    # ── Header row ───────────────────────────────────────────────────────
    c.setFillColor(C_ORANGE)
    c.rect(ML, y - hdr_h, BODY, hdr_h, fill=1, stroke=0)

    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(C_WHITE)
    cx = ML
    for title, w, align in cols:
        _tbl_header_cell(c, cx, y - hdr_h, w, hdr_h, title, align)
        cx += w
    y -= hdr_h

    # ── Data rows ────────────────────────────────────────────────────────
    for i, item in enumerate(items):
        desc   = str(item.get('description') or '')
        lines  = [l.strip() for l in desc.split('\n') if l.strip()]
        main   = lines[0] if lines else ''
        subs   = lines[1:]
        rh     = max(row_base_h, 15 + len(subs) * 12 + 6)

        # alternating bg
        if i % 2 == 1:
            c.setFillColor(C_ROW_ALT)
            c.rect(ML, y - rh, BODY, rh, fill=1, stroke=0)

        # bottom rule
        c.setStrokeColor(C_RULE)
        c.setLineWidth(0.4)
        c.line(ML, y - rh, MR, y - rh)

        # item name (bold)
        text_y = y - 13
        c.setFont('Helvetica-Bold', 9)
        c.setFillColor(C_BLACK)
        c.drawString(ML + 8, text_y, _clip(main, 60 if doc_type == 'delivery_note' else 52))

        # sub-lines
        for sl in subs:
            text_y -= 12
            c.setFont('Helvetica', 8)
            c.setFillColor(C_BODY)
            c.drawString(ML + 16, text_y, _clip(sl, 58 if doc_type == 'delivery_note' else 50))

        # right-side cells
        qty   = float(item.get('quantity', 1) or 1)
        price = float(item.get('unit_price', 0) or 0)
        total = float(item.get('line_total', 0) or 0)

        cx = ML + cols[0][1]  # after ITEM column

        # QTY
        c.setFont('Helvetica', 9)
        c.setFillColor(C_DARK)
        qty_s = str(int(qty)) if qty == int(qty) else f'{qty:.2f}'
        c.drawCentredString(cx + cols[1][1] / 2, y - 13, qty_s)
        cx += cols[1][1]

        if doc_type != 'delivery_note':
            # UNIT PRICE
            c.setFont('Helvetica', 9)
            c.drawRightString(cx + cols[2][1] - 8, y - 13, _tzs(price))
            cx += cols[2][1]
            # AMOUNT
            c.setFont('Helvetica-Bold', 9)
            c.setFillColor(C_BLACK)
            c.drawRightString(cx + cols[3][1] - 8, y - 13, _tzs(total))

        y -= rh

    # Thick bottom rule for table
    c.setStrokeColor(C_ORANGE)
    c.setLineWidth(1)
    c.line(ML, y, MR, y)

    return y - 6


def _totals(c, y: float, document: dict) -> float:
    """Right-aligned totals block."""
    block_x = MR - 240
    block_w = 240
    line_h  = 18
    y -= 6

    def _tot_row(label, value, bold=False, orange_bg=False):
        nonlocal y
        if orange_bg:
            c.setFillColor(C_ORANGE)
            c.roundRect(block_x - 4, y - line_h - 2, block_w + 4, line_h + 6, 5, fill=1, stroke=0)
            c.setFillColor(C_WHITE)
            font = 'Helvetica-Bold'
            size = 11
        else:
            c.setFillColor(C_DARK if bold else C_BODY)
            font = 'Helvetica-Bold' if bold else 'Helvetica'
            size = 9.5

        c.setFont(font, size)
        c.drawString(block_x, y - line_h + 3, label)
        c.drawRightString(MR, y - line_h + 3, value)
        if not orange_bg:
            c.setStrokeColor(C_RULE)
            c.setLineWidth(0.4)
            c.line(block_x, y - line_h - 1, MR, y - line_h - 1)
        y -= line_h + 4

    # Subtotal
    _tot_row('Subtotal', _tzs(document.get('subtotal', 0)))

    # VAT line
    if document.get('is_vat') and float(document.get('vat_amount', 0) or 0) > 0:
        rate = document.get('vat_rate', 18)
        _tot_row(f'VAT ({rate:.0f}%)', _tzs(document.get('vat_amount', 0)))

    # Grand total
    y -= 4
    _tot_row('GRAND TOTAL', _tzs(document.get('total', 0)), bold=True, orange_bg=True)

    return y - 12


def _payment(c, y: float):
    """Payment instructions (invoice / proforma), centered."""
    y -= 8
    cx = W / 2

    # Separator
    c.setStrokeColor(C_RULE)
    c.setLineWidth(0.5)
    c.line(ML + 60, y, MR - 60, y)
    y -= 14

    c.setFont('Helvetica', 8)
    c.setFillColor(C_MUTED)
    _centre(c, cx, y, 'Payments can be made via NMB Bank A/C:', 'Helvetica', 8)
    y -= 16

    c.setFont('Helvetica-Bold', 16)
    c.setFillColor(C_BLACK)
    _centre(c, cx, y, '42710089645', 'Helvetica-Bold', 16)
    y -= 15

    c.setFont('Helvetica', 8)
    c.setFillColor(C_MUTED)
    _centre(c, cx, y, 'SADAKALAWE ENTERPRISES', 'Helvetica', 8)


def _signature_line(c, y: float):
    """Recipient signature area for delivery notes."""
    y -= 24
    sig_w = 200
    c.setStrokeColor(C_RULE)
    c.setLineWidth(0.8)
    # Received by
    c.line(ML, y, ML + sig_w, y)
    c.setFont('Helvetica', 7.5)
    c.setFillColor(C_MUTED)
    c.drawString(ML, y - 11, 'Jina na Sahihi ya Mpokeaji')
    # Date line
    c.line(ML + sig_w + 30, y, ML + sig_w + 30 + 120, y)
    c.drawString(ML + sig_w + 30, y - 11, 'Tarehe')


def _notes(c, notes: str):
    """Notes block, positioned just above the footer."""
    y = 56
    c.setFont('Helvetica-Bold', 7.5)
    c.setFillColor(C_MUTED)
    c.drawString(ML, y, 'MAELEZO:')
    c.setFont('Helvetica', 7.5)
    c.setFillColor(C_BODY)
    max_w = BODY - 60
    words, line = notes.split(), ''
    for word in words:
        test = (line + ' ' + word).strip()
        if c.stringWidth(test, 'Helvetica', 7.5) <= max_w:
            line = test
        else:
            c.drawString(ML + 52, y, line)
            y -= 10
            line = word
    if line:
        c.drawString(ML + 52, y, line)


def _footer(c, branch: dict):
    """Orange line + address bar at the very bottom."""
    # Thick orange rule
    c.setFillColor(C_ORANGE)
    c.rect(0, 0, W, 26, fill=1, stroke=0)

    # White text inside orange bar
    c.setFont('Helvetica', 7.5)
    c.setFillColor(C_WHITE)
    addr  = branch.get('address', '')
    line  = f"{addr}   ·   +255 768 596 006   ·   www.sadakalawe.com   ·   TIN 164-334-864"
    fw    = c.stringWidth(line, 'Helvetica', 7.5)
    c.drawString((W - fw) / 2, 9, line)


# ═══════════════════════════════════════════════════════════════════════════
#  DRAW HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _rounded_box(c, x, y, w, h, fill_color, radius=8):
    c.setFillColor(fill_color)
    c.setStrokeColor(C_RULE)
    c.setLineWidth(0.5)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)


def _label(c, x, y, text, color):
    c.setFont('Helvetica-Bold', 7)
    c.setFillColor(color)
    c.drawString(x, y, text)


def _tbl_header_cell(c, x, y, w, h, text, align):
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(C_WHITE)
    ty = y + h / 2 - 4
    if align == 'left':
        c.drawString(x + 8, ty, text)
    elif align == 'right':
        c.drawRightString(x + w - 8, ty, text)
    else:
        c.drawCentredString(x + w / 2, ty, text)


def _text_wrap(c, x, y, text, font, size, max_w):
    words = text.split()
    line  = ''
    for word in words:
        test = f'{line} {word}'.strip()
        if c.stringWidth(test, font, size) <= max_w:
            line = test
        else:
            c.drawString(x, y, line)
            y   -= size + 2
            line = word
    if line:
        c.drawString(x, y, line)


def _centre(c, cx, y, text, font, size):
    w = c.stringWidth(text, font, size)
    c.drawString(cx - w / 2, y, text)


def _clip(text, maxlen):
    return text[:maxlen] + ('…' if len(text) > maxlen else '')


def _tzs(val) -> str:
    try:
        return f"TZS {float(val):,.0f} /="
    except (TypeError, ValueError):
        return 'TZS 0 /='


def _fmt_date(dt_str) -> str:
    months = ['Jan','Feb','Mar','Apr','May','Jun',
              'Jul','Aug','Sep','Oct','Nov','Dec']
    try:
        dt = datetime.fromisoformat(str(dt_str)[:19])
        return f"{dt.day:02d} {months[dt.month - 1]} {dt.year}"
    except Exception:
        return str(dt_str)[:10] if dt_str else ''
