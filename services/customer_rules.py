"""What counts as a real customer record.

Staff used to type anything in the customer box ("mteja", "boss", "walk in",
"kaka"), which makes the sales log, debts and campaigns useless. A customer now
needs a proper name and a phone number that can actually be called.
"""
import re
from database import query_db
from services.text_utils import tc

# Words that are not names. Lower-case.
PLACEHOLDER_WORDS = {
    'mteja', 'wateja', 'customer', 'customers', 'client', 'walk', 'walkin', 'walk-in',
    'cash', 'unknown', 'none', 'nil', 'null', 'test', 'testing', 'demo', 'sample',
    'n/a', 'xxx', 'xx', 'abc', 'asdf', 'qwerty', 'jina', 'mnunuzi', 'buyer',
    'someone', 'anonymous', 'general', 'retail', 'default', 'noname', 'random',
}
# Titles / nicknames — allowed in front of a name but never count as the name.
TITLE_WORDS = {
    'mr', 'mrs', 'ms', 'miss', 'dr', 'eng', 'prof', 'sir', 'madam', 'mzee', 'mama',
    'baba', 'kaka', 'dada', 'bro', 'sis', 'boss', 'bosi', 'bwana', 'bi', 'rafiki',
    'jamaa', 'brother', 'sister', 'friend', 'uncle', 'aunt', 'anko', 'shangazi',
}
COMPANY_WORDS = {'ltd', 'limited', 'company', 'co', 'enterprises', 'enterprise', 'group',
                 'safaris', 'safari', 'tours', 'lodge', 'hotel', 'school', 'hospital',
                 'bank', 'church', 'ngo', 'foundation', 'agency', 'shop', 'store', 'traders',
                 'investment', 'investments', 'services', 'solutions', 'tech', 'ventures'}


def clean_name(raw):
    return tc(re.sub(r'\s+', ' ', (raw or '').strip())) or ''


def name_error(name, tin=None):
    """Return a message explaining what is wrong with the name, or None if OK."""
    if not name:
        return 'Enter the customer\'s full name.'
    words = re.findall(r"[^\W\d_][^\W\d_'.\-]*", name, re.UNICODE)
    lowered = [w.lower().strip(".'-") for w in words]
    if any(w in PLACEHOLDER_WORDS for w in lowered) or name.lower().replace(' ', '') in ('walkin', 'n/a'):
        return (f'"{name}" is not a real name. Ask the customer for their name '
                f'(first and last name, e.g. "Neema Mollel").')
    real = [w for w in lowered if w not in TITLE_WORDS and len(w) >= 2]
    if any(len(set(w)) == 1 and len(w) >= 2 for w in real):
        return f'"{name}" does not look like a real name.'
    is_company = bool(tin) or any(w in COMPANY_WORDS for w in lowered)
    if is_company:
        if not real:
            return 'Enter the company\'s registered name.'
        return None
    if len(real) < 2:
        return (f'"{name}" is not enough. Enter first and last name '
                f'(e.g. "Neema Mollel"). For a business, add the TIN or the full company name.')
    return None


def normalize_phone(raw):
    """'0768 596 006' / '+255768596006' / '768596006' → '+255768596006'.
    Foreign numbers (tourists) must start with + and are kept as +digits."""
    raw = (raw or '').strip()
    digits = re.sub(r'\D', '', raw)
    if not digits:
        return None
    if raw.startswith('+') and not digits.startswith('255'):
        return '+' + digits if 8 <= len(digits) <= 15 else None
    if digits.startswith('255') and len(digits) == 12:
        local = digits[3:]
    elif digits.startswith('0') and len(digits) == 10:
        local = digits[1:]
    elif len(digits) == 9:
        local = digits
    else:
        return None
    if local[0] not in '267':   # mobile 6x/7x, landline 2x (e.g. 027 Arusha)
        return None
    return '+255' + local


def phone_error(raw):
    if not (raw or '').strip():
        return 'Enter the customer\'s phone number.'
    if not normalize_phone(raw):
        return (f'"{raw}" is not a valid phone number. Use a Tanzanian number like '
                f'0768 596 006, or a foreign number starting with + (e.g. +44 7700 900123).')
    return None


_STRIP = "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(COALESCE(phone,''),' ',''),'-',''),'+',''),'(',''),')','')"


def find_by_phone(raw, exclude_id=None):
    """Existing customer with the same number, whatever format it was saved in."""
    norm = normalize_phone(raw)
    if not norm:
        return None
    digits = norm.lstrip('+')
    key = digits[-9:] if digits.startswith('255') else digits
    sql = f"SELECT * FROM customers WHERE {_STRIP} LIKE ?"
    args = ['%' + key]
    if exclude_id:
        sql += " AND id != ?"
        args.append(exclude_id)
    return query_db(sql + " ORDER BY id LIMIT 1", args, one=True)
