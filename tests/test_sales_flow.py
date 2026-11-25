"""End-to-end checks for the sale → stock → return flow.

Run:  venv/bin/python -m unittest discover -s tests -v
Uses a throwaway database, never data/sadakalawe.db.
"""
import os
import re
import sqlite3
import tempfile
import unittest

_TMP = tempfile.mkdtemp()
os.environ['SADAKALAWE_DB'] = os.path.join(_TMP, 'test.db')

from werkzeug.security import generate_password_hash  # noqa: E402
from app import create_app  # noqa: E402

APP = create_app()
APP.config['TESTING'] = True


def db():
    c = sqlite3.connect(os.environ['SADAKALAWE_DB'])
    c.row_factory = sqlite3.Row
    return c


def q(sql, args=()):
    with db() as c:
        return c.execute(sql, args).fetchall()


def q1(sql, args=()):
    rows = q(sql, args)
    return rows[0] if rows else None


def make_user(username, role='staff', branch_id=1, perms=(), must_change=0):
    with db() as c:
        c.execute("DELETE FROM users WHERE username=?", (username,))
        cur = c.execute(
            "INSERT INTO users (username, password_hash, full_name, role, branch_id, must_change_password) "
            "VALUES (?,?,?,?,?,?)",
            (username, generate_password_hash('pw123456', method='pbkdf2:sha256'),
             username.title() + ' Staff', role, branch_id, must_change))
        for p in perms:
            c.execute("INSERT INTO user_permissions (user_id, permission) VALUES (?,?)", (cur.lastrowid, p))
        return cur.lastrowid


def make_product(model, track_units=0):
    with db() as c:
        cur = c.execute(
            "INSERT INTO products (brand_category, model, price, track_units, category_id) "
            "VALUES ('Accessories', ?, 50000, ?, 5)", (model, track_units))
        pid = cur.lastrowid
        for b in c.execute("SELECT id FROM branches").fetchall():
            c.execute("INSERT OR IGNORE INTO product_stock (product_id, branch_id, quantity) VALUES (?,?,0)",
                      (pid, b[0]))
        return pid


def stock_of(pid, branch_id):
    return q1("SELECT quantity FROM product_stock WHERE product_id=? AND branch_id=?",
              (pid, branch_id))['quantity']


def ledger_matches():
    """Every product_stock row equals the sum of its movements."""
    bad = q("""SELECT ps.product_id, ps.branch_id, ps.quantity,
                      (SELECT COALESCE(SUM(quantity),0) FROM stock_movements m
                        WHERE m.product_id=ps.product_id AND m.branch_id=ps.branch_id) AS led
               FROM product_stock ps
               JOIN products p ON p.id = ps.product_id
               WHERE p.sku IS NULL OR p.sku NOT LIKE 'SDA-%'""")
    return [dict(r) for r in bad if abs(r['quantity'] - r['led']) > 1e-9]


class Base(unittest.TestCase):
    def setUp(self):
        self.c = APP.test_client()

    def login(self, username='admin', password='admin123'):
        return self.c.post('/login', data={'username': username, 'password': password})

    def flashes(self, resp):
        return re.sub(r'\s+', ' ', resp.get_data(as_text=True))

    def customer(self, name='Neema Mollel', phone='0768 111 222'):
        r = self.c.post('/customers/quick-add', json={'name': name, 'phone': phone})
        self.assertEqual(r.status_code, 200, r.get_json())
        return r.get_json()['id']

    def receive(self, pid, branch_id, qty, imeis=''):
        return self.c.post('/stock/adjust', data={
            'product_id': pid, 'branch_id': branch_id, 'movement_type': 'stock_in',
            'quantity': qty, 'imeis': imeis})

    def sell(self, customer_id, lines, branch_id=1, payment_type='cash'):
        page = self.c.get('/documents/new').get_data(as_text=True)
        nonce = re.search(r'name="_form_nonce" value="([^"]+)"', page).group(1)
        data = {'_form_nonce': nonce, 'branch_id': branch_id, 'customer_id': customer_id or '',
                'payment_type': payment_type, 'vat_rate': 18,
                'item_description[]': [], 'item_qty[]': [], 'item_price[]': [],
                'item_product_id[]': [], 'item_discount[]': [], 'item_specs[]': [], 'item_units[]': []}
        for ln in lines:
            data['item_description[]'].append(ln.get('desc', 'Item'))
            data['item_qty[]'].append(ln['qty'])
            data['item_price[]'].append(ln.get('price', 50000))
            data['item_product_id[]'].append(ln.get('pid', ''))
            data['item_discount[]'].append(0)
            data['item_specs[]'].append('')
            data['item_units[]'].append(ln.get('units', ''))
        return self.c.post('/documents/new', data=data, follow_redirects=True)


class CustomerNames(Base):
    def test_informal_names_rejected_and_phone_required(self):
        self.login()
        for bad in ('Mteja', 'Boss', 'Walk In', 'Mama Baraka', 'Juma'):
            r = self.c.post('/customers/quick-add', json={'name': bad, 'phone': '0768000001'})
            self.assertEqual(r.status_code, 400, bad)
        r = self.c.post('/customers/quick-add', json={'name': 'Asha Ally'})
        self.assertEqual(r.status_code, 400)
        r = self.c.post('/customers/quick-add', json={'name': 'Asha Ally', 'phone': '12'})
        self.assertEqual(r.status_code, 400)

    def test_quick_add_reuses_customer_with_same_phone(self):
        self.login()
        a = self.c.post('/customers/quick-add', json={'name': 'Baraka Lyimo', 'phone': '0755 123 456'}).get_json()
        b = self.c.post('/customers/quick-add', json={'name': 'Baraka L Lyimo', 'phone': '+255755123456'}).get_json()
        self.assertEqual(a['id'], b['id'])
        self.assertTrue(b['existing'])
        self.assertEqual(a['phone'], '+255755123456')

    def test_sale_needs_a_saved_customer(self):
        self.login()
        pid = make_product('Cust Test Cable')
        self.receive(pid, 1, 5)
        r = self.sell(None, [{'pid': pid, 'qty': 1}])
        self.assertIn('Choose the customer', self.flashes(r))
        self.assertEqual(stock_of(pid, 1), 5)


class StockOnSales(Base):
    def setUp(self):
        super().setUp()
        self.login()
        self.cid = self.customer('Neema Mollel', '0768111222')

    def test_cannot_sell_without_stock_or_hand_typed(self):
        pid = make_product('Empty Shelf Charger')
        r = self.sell(self.cid, [{'pid': pid, 'qty': 1}])
        self.assertIn('Not enough stock', self.flashes(r))
        r = self.sell(self.cid, [{'desc': 'Something typed by hand', 'qty': 1}])
        self.assertIn('not from the product list', self.flashes(r))
        self.assertIsNone(q1("SELECT id FROM documents WHERE customer_id=? AND total=50000", (self.cid,)))

    def test_full_sale_lifecycle(self):
        pid = make_product('Lifecycle Power Bank')
        self.receive(pid, 1, 5)
        self.assertEqual(stock_of(pid, 1), 5)

        # sale of 2 → 3 documents, stock taken once
        r = self.sell(self.cid, [{'pid': pid, 'qty': 2}])
        self.assertEqual(r.status_code, 200)
        inv = q1("SELECT * FROM documents WHERE doc_type='invoice' AND customer_id=? ORDER BY id DESC",
                 (self.cid,))
        batch = q("SELECT doc_type FROM documents WHERE batch_id=?", (inv['batch_id'],))
        self.assertEqual(sorted(d['doc_type'] for d in batch), ['delivery_note', 'invoice', 'proforma'])
        self.assertEqual(stock_of(pid, 1), 3)
        self.assertEqual(ledger_matches(), [])

        # oversell blocked
        r = self.sell(self.cid, [{'pid': pid, 'qty': 4, 'price': 1}])
        self.assertIn('Not enough stock', self.flashes(r))
        self.assertEqual(stock_of(pid, 1), 3)

        # edit 2 → 3: stock follows, all three docs updated, ledger still adds up
        r = self.c.post(f'/documents/{inv["id"]}/edit', data={
            'customer_id': self.cid, 'payment_type': 'cash', 'vat_rate': 18,
            'item_description[]': 'Lifecycle Power Bank', 'item_qty[]': 3, 'item_price[]': 50000,
            'item_product_id[]': pid, 'item_discount[]': 0, 'item_specs[]': ''},
            follow_redirects=True)
        self.assertEqual(stock_of(pid, 1), 2)
        self.assertEqual(ledger_matches(), [])
        for d in q("SELECT id, total FROM documents WHERE batch_id=?", (inv['batch_id'],)):
            self.assertEqual(d['total'], 150000)
        self.assertEqual(q1("SELECT payment_status FROM documents WHERE id=?", (inv['id'],))[0], 'partial')

        # no second invoice / delivery note from conversions
        pro = q1("SELECT id FROM documents WHERE batch_id=? AND doc_type='proforma'", (inv['batch_id'],))
        self.c.post(f'/documents/{pro["id"]}/convert', data={'payment_method': 'cash'})
        self.c.post(f'/documents/{inv["id"]}/convert')
        self.assertEqual(len(q("SELECT id FROM documents WHERE batch_id=?", (inv['batch_id'],))), 3)
        self.assertEqual(stock_of(pid, 1), 2)

        # return 1 → back on the shelf; can't return more than sold
        line = q1("SELECT id FROM document_items WHERE document_id=?", (inv['id'],))
        ret = {'document_id': inv['id'], 'reason': 'Defective / not working', 'return_type': 'refund',
               'refund_amount': 50000, 'item_di_id[]': line['id'], 'item_qty[]': 1,
               'item_imeis[]': ''}
        self.c.post('/returns/new', data=ret, follow_redirects=True)
        self.assertEqual(stock_of(pid, 1), 3)
        r = self.c.post('/returns/new', data=dict(ret, **{'item_qty[]': 3}), follow_redirects=True)
        self.assertIn('only 2 left to return', self.flashes(r))
        r = self.c.post('/returns/new', data=dict(ret, document_id=''), follow_redirects=True)
        self.assertIn('Link the invoice', self.flashes(r))
        self.assertEqual(stock_of(pid, 1), 3)
        self.assertEqual(ledger_matches(), [])

        # edit and delete blocked once a return exists
        r = self.c.post(f'/documents/{inv["id"]}/delete-batch', follow_redirects=True)
        self.assertIn('Cannot delete', self.flashes(r))
        self.assertIsNotNone(q1("SELECT id FROM documents WHERE id=?", (inv['id'],)))

    def test_delete_puts_stock_back(self):
        pid = make_product('Delete Me Earbuds')
        self.receive(pid, 1, 4)
        self.sell(self.cid, [{'pid': pid, 'qty': 3, 'price': 70000}])
        inv = q1("SELECT * FROM documents WHERE doc_type='invoice' AND total=70000*3 ORDER BY id DESC")
        self.assertEqual(stock_of(pid, 1), 1)
        self.c.post(f'/documents/{inv["id"]}/delete')
        self.assertIsNone(q1("SELECT id FROM documents WHERE batch_id=?", (inv['batch_id'],)))
        self.assertEqual(stock_of(pid, 1), 4)
        self.assertEqual(ledger_matches(), [])
        self.assertIsNotNone(q1("SELECT id FROM audit_log WHERE action='delete' AND reference LIKE ?",
                                (f'%{inv["doc_number"]}%',)))

    def test_failed_sale_leaves_nothing_behind(self):
        from services import stock as stock_svc
        pid = make_product('Rollback Speaker')
        self.receive(pid, 1, 2)
        before = q1("SELECT COUNT(*) AS n FROM documents")['n']
        seq_before = q("SELECT * FROM doc_sequence")
        orig = stock_svc.sell
        stock_svc.sell = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('power cut'))
        try:
            self.sell(self.cid, [{'pid': pid, 'qty': 1, 'price': 12345}])
        finally:
            stock_svc.sell = orig
        self.assertEqual(q1("SELECT COUNT(*) AS n FROM documents")['n'], before)
        self.assertEqual([tuple(r) for r in q("SELECT * FROM doc_sequence")], [tuple(r) for r in seq_before])
        self.assertEqual(stock_of(pid, 1), 2)


class ImeiUnits(Base):
    def test_receive_transfer_sell_return_by_imei(self):
        self.login()
        cid = self.customer('Joseph Massawe', '0713 222 333')
        pid = make_product('Test iPhone 99', track_units=1)
        r = self.receive(pid, 1, 2, imeis='111')
        self.assertIn('enter exactly 2', self.flashes(r))
        self.receive(pid, 1, 2, imeis='111111\n222222')
        self.assertEqual(stock_of(pid, 1), 2)

        # transfer one to Dar: the IMEI moves too
        r = self.c.post('/stock/transfer', data={'product_id': pid, 'from_branch_id': 1,
                                                  'to_branch_id': 2, 'quantity': 1, 'imeis': '222222'})
        self.assertEqual(stock_of(pid, 2), 1)
        self.assertEqual(q1("SELECT branch_id FROM device_imeis WHERE imei='222222'")[0], 2)

        # sell it in Dar
        self.sell(cid, [{'pid': pid, 'qty': 1, 'units': '222222', 'price': 3000000}], branch_id=2)
        self.assertEqual(q1("SELECT status FROM device_imeis WHERE imei='222222'")[0], 'sold')
        self.assertEqual(stock_of(pid, 2), 0)
        inv = q1("SELECT * FROM documents WHERE doc_type='invoice' AND total=3000000")

        # return it: IMEI back in stock, at the selling branch
        line = q1("SELECT id FROM document_items WHERE document_id=?", (inv['id'],))
        self.c.post('/returns/new', data={'document_id': inv['id'], 'reason': 'Other',
                                          'return_type': 'exchange', 'item_di_id[]': line['id'],
                                          'item_qty[]': 1, 'item_imeis[]': ''})
        self.assertEqual(q1("SELECT status FROM device_imeis WHERE imei='222222'")[0], 'in_stock')
        self.assertEqual(stock_of(pid, 2), 1)
        self.assertEqual(ledger_matches(), [])


class AccessAndLogin(Base):
    def test_staff_cannot_sell_from_another_branch_or_touch_stock(self):
        make_user('darstaff', branch_id=2,
                  perms=('create_documents', 'manage_customers', 'view_customers', 'view_products'))
        self.login()
        pid = make_product('Branch Lock Cable')
        self.receive(pid, 1, 3)    # Arusha
        self.receive(pid, 2, 3)    # Dar
        self.c.get('/logout')
        self.login('darstaff', 'pw123456')
        cid = self.customer('Halima Said', '0789 444 555')
        self.sell(cid, [{'pid': pid, 'qty': 1, 'price': 4321}], branch_id=1)
        doc = q1("SELECT branch_id FROM documents WHERE total=4321 AND doc_type='invoice'")
        self.assertEqual(doc['branch_id'], 2)
        self.assertEqual(stock_of(pid, 1), 3)
        self.assertEqual(stock_of(pid, 2), 2)
        before = stock_of(pid, 2)
        self.receive(pid, 2, 10)                       # no manage_stock permission
        self.assertEqual(stock_of(pid, 2), before)

    def test_login_throttle_and_redirect(self):
        make_user('throttled')
        for _ in range(8):
            self.login('throttled', 'wrong')
        r = self.login('throttled', 'pw123456')
        self.assertIn('Too many wrong passwords', self.flashes(r))
        make_user('redir')
        r = self.c.post('/login?next=https://evil.example', data={'username': 'redir', 'password': 'pw123456'})
        self.assertNotIn('evil.example', r.headers.get('Location', ''))

    def test_must_change_password_does_not_crash(self):
        make_user('newbie', must_change=1)
        self.login('newbie', 'pw123456')
        r = self.c.get('/documents/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/profile', r.headers['Location'])


class PagesRender(Base):
    def test_touched_pages_render(self):
        self.login()
        cid = self.customer('Grace Kimaro', '0744 555 666')
        pid = make_product('Render Check Hub')
        self.receive(pid, 1, 2)
        self.sell(cid, [{'pid': pid, 'qty': 1, 'price': 99999}])
        inv = q1("SELECT id FROM documents WHERE doc_type='invoice' AND total=99999")['id']
        for url in ['/dashboard', '/documents/', '/documents/new', f'/documents/{inv}',
                    f'/documents/{inv}/edit', f'/documents/{inv}/pdf', '/returns/',
                    '/returns/new', f'/returns/new?doc_id={inv}', f'/returns/invoice-items/{inv}',
                    '/stock/', '/stock/adjust', '/stock/transfer', '/stock/movements',
                    '/cash/', '/cash/new', '/customers/', '/customers/new',
                    f'/customers/{cid}/edit', '/settings/activity', '/madeni/',
                    f'/products/search?q=Render&branch_id=1']:
            r = self.c.get(url)
            self.assertEqual(r.status_code, 200, url)
        self.assertEqual(self.c.get('/products/search?q=Render+Check&branch_id=1').get_json()[0]['branch_stock'], 1)


class WhatsNew(Base):
    def test_popup_shows_once(self):
        make_user('popup')
        self.login('popup', 'pw123456')
        self.assertIn('whats-new-modal', self.c.get('/documents/').get_data(as_text=True))
        self.c.post('/whats-new/seen')
        self.assertNotIn('whats-new-modal', self.c.get('/documents/').get_data(as_text=True))


class Duplicates(Base):
    def setUp(self):
        super().setUp()
        self.login()

    def test_same_phone_any_format_is_one_customer_group_and_merge_moves_everything(self):
        with db() as c:
            a = c.execute("INSERT INTO customers (name, phone) VALUES ('Peter Kessy', '0766 101 202')").lastrowid
            b = c.execute("INSERT INTO customers (name, phone) VALUES ('Peter Kesi', '+255766101202')").lastrowid
            c.execute("INSERT INTO repair_jobs (job_number, branch_id, customer_id, device_make, device_model, problem) "
                      "VALUES ('REP-T-1', 1, ?, 'Apple', 'iPhone', 'screen')", (b,))
        page = self.c.get('/customers/duplicates').get_data(as_text=True)
        self.assertIn('Peter Kesi', page)
        r = self.c.post('/customers/merge', data={'master_id': a, 'dup_ids[]': [b]}, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(q1("SELECT id FROM customers WHERE id=?", (b,)))
        self.assertEqual(q1("SELECT customer_id FROM repair_jobs WHERE job_number='REP-T-1'")[0], a)

    def test_same_name_different_phone_allowed(self):
        self.c.post('/customers/new', data={'name': 'John Mushi', 'phone': '0711000111'})
        self.c.post('/customers/new', data={'name': 'John Mushi', 'phone': '0711000222'})
        self.assertEqual(q1("SELECT COUNT(*) AS n FROM customers WHERE name='John Mushi'")['n'], 2)
        self.c.post('/customers/new', data={'name': 'Johnny Mushi', 'phone': '+255711000222'})
        self.assertEqual(q1("SELECT COUNT(*) AS n FROM customers WHERE name='Johnny Mushi'")['n'], 0)

    def test_sale_shows_once_on_customer_page(self):
        cid = self.customer('Rehema Swai', '0688 777 888')
        pid = make_product('Once Only Mouse')
        self.receive(pid, 1, 3)
        self.sell(cid, [{'pid': pid, 'qty': 1, 'price': 11111}])
        page = self.c.get(f'/customers/{cid}').get_data(as_text=True)
        self.assertEqual(len(re.findall(r'INV-ARU-\d{4}-\d{4}', page)) > 0, True)
        self.assertNotIn('PRO-ARU', page)
        self.assertNotIn('DN-ARU', page)

    def test_product_merge_keeps_stock_and_history(self):
        cid = self.customer('Musa Laizer', '0622 333 444')
        keep = make_product('Anker 20W Charger')
        dup = make_product('anker 20w  charger')
        self.receive(keep, 1, 2)
        self.receive(dup, 1, 3)
        self.sell(cid, [{'pid': dup, 'qty': 1, 'price': 22222}])
        page = self.c.get('/settings/duplicates').get_data(as_text=True)
        self.assertIn('anker 20w  charger', page)
        self.c.post('/products/merge', data={'keep_id': keep, 'dup_ids[]': [dup]})
        self.assertEqual(stock_of(keep, 1), 4)
        self.assertEqual(q1("SELECT is_active FROM products WHERE id=?", (dup,))[0], 0)
        self.assertIsNotNone(q1("SELECT id FROM document_items WHERE product_id=? AND line_total=22222", (keep,)))
        self.assertEqual(ledger_matches(), [])


class LibraryPaths(Base):
    """The parts that depend on Pillow / ReportLab / pypdf / qrcode / openpyxl."""
    def test_pdfs_excel_and_import(self):
        import io
        import openpyxl
        from pypdf import PdfReader
        self.login()
        cid = self.customer('Lucy Shirima', '0699 121 343')
        pid = make_product('Library Check Speaker')
        self.receive(pid, 1, 3)
        self.sell(cid, [{'pid': pid, 'qty': 1, 'price': 88888}], payment_type='credit')
        inv = q1("SELECT * FROM documents WHERE doc_type='invoice' AND total=88888")
        batch = [r['id'] for r in q("SELECT id FROM documents WHERE batch_id=?", (inv['batch_id'],))]
        self.c.post(f'/madeni/{inv["id"]}/pay', data={'amount': 10000, 'payment_method': 'cash'})
        pay = q1("SELECT id FROM payments WHERE document_id=?", (inv['id'],))

        def pdf_pages(url):
            r = self.c.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertTrue(r.data.startswith(b'%PDF'), url)
            return len(PdfReader(io.BytesIO(r.data)).pages)

        for d in batch:                                   # invoice, proforma, DN (logo + QR)
            self.assertGreaterEqual(pdf_pages(f'/documents/{d}/pdf'), 1)
        self.assertGreaterEqual(pdf_pages('/documents/merged?ids=' + ','.join(map(str, batch))), 3)
        self.assertGreaterEqual(pdf_pages(f'/madeni/customer/{cid}/statement.pdf'), 1)
        r = self.c.get(f'/madeni/{inv["id"]}/payments/{pay["id"]}/receipt')
        self.assertEqual(r.status_code, 200)

        r = self.c.get('/documents/zip?ids=' + ','.join(map(str, batch)))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data.startswith(b'PK'))

        for url in ['/reports/sales?export=excel', '/expenses/?export=excel']:
            r = self.c.get(url)
            self.assertEqual(r.status_code, 200, url)
            openpyxl.load_workbook(io.BytesIO(r.data))     # opens = valid xlsx
        for url in ['/reports/pnl', '/reports/stock', '/reports/debts', '/stock-performance']:
            self.assertEqual(self.c.get(url).status_code, 200, url)

        wb = openpyxl.Workbook()
        wb.active.append(['name', 'phone'])
        wb.active.append(['Daudi Mollel', '0700111222'])
        buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        r = self.c.post('/import/customers/preview',
                        data={'file': (buf, 'customers.xlsx')}, content_type='multipart/form-data')
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:200])


class Seeding(unittest.TestCase):
    def test_restart_keeps_products_and_does_not_recreate_admin(self):
        with db() as c:
            c.execute("UPDATE users SET username='owner_sey' WHERE username='admin'")
            n = c.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            c.execute("DELETE FROM products WHERE id IN (SELECT id FROM products WHERE sku LIKE 'SDA-%' "
                      "AND id NOT IN (SELECT product_id FROM document_items WHERE product_id IS NOT NULL) "
                      "LIMIT 200)")
            left = c.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        self.assertLess(left, n)
        create_app()   # simulate a restart
        self.assertEqual(q1("SELECT COUNT(*) AS n FROM products")['n'], left)
        self.assertIsNone(q1("SELECT id FROM users WHERE username='admin'"))
        self.assertEqual(q1("SELECT name FROM branches WHERE short_code='AR2'")['name'], 'Sadakalawe 2')
        with db() as c:
            c.execute("UPDATE users SET username='admin' WHERE username='owner_sey'")


if __name__ == '__main__':
    unittest.main()
