from database import get_db
from config import DOC_TYPE_PREFIXES


def get_next_number(branch_id, doc_type, year):
    db = get_db()
    prefix = DOC_TYPE_PREFIXES[doc_type]

    branch = db.execute("SELECT short_code FROM branches WHERE id=?", (branch_id,)).fetchone()
    short_code = branch['short_code']

    db.execute("""
        INSERT INTO doc_sequence (branch_id, doc_type, year, last_sequence)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(branch_id, doc_type, year)
        DO UPDATE SET last_sequence = last_sequence + 1
    """, (branch_id, doc_type, year))

    seq = db.execute("""
        SELECT last_sequence FROM doc_sequence
        WHERE branch_id=? AND doc_type=? AND year=?
    """, (branch_id, doc_type, year)).fetchone()['last_sequence']

    db.commit()
    return f"{prefix}-{short_code}-{year}-{seq:04d}"