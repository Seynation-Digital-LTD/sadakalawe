"""
Reset script — wipes all transaction data for clean handover.
Keeps: branches, product catalog, categories, admin user.
Run: python3 reset_data.py
"""
import sqlite3, os, sys

DB = os.path.join(os.path.dirname(__file__), "data", "sadakalawe.db")

confirm = input("This will DELETE all sales, customers, credits and expenses. Type YES to confirm: ")
if confirm.strip() != "YES":
    print("Aborted.")
    sys.exit(0)

db = sqlite3.connect(DB)
db.execute("PRAGMA journal_mode=WAL")

tables_to_clear = [
    "stock_movements",
    "credit_payments",
    "document_items",
    "documents",
    "doc_number_sequences",
    "customers",
    "credits",
    "expenses",
]

for table in tables_to_clear:
    try:
        db.execute(f"DELETE FROM {table}")
        print(f"Cleared: {table}")
    except Exception as e:
        print(f"Skip {table}: {e}")

# Reset stock to zero
db.execute("UPDATE product_stock SET quantity = 0")
db.execute("UPDATE products SET stock_count = 0")
print("Reset stock to 0")

# Force admin password change on next login
db.execute("UPDATE users SET must_change_password = 1 WHERE role != admin")
print("Set must_change_password for all staff")

db.commit()
db.close()
print("\nDone. Database is clean and ready for handover.")
