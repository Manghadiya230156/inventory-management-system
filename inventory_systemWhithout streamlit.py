"""
Inventory Management System
---------------------------
Stack : Python, SQLite3, FPDF (fpdf2), Matplotlib
 
Features
  1. Product CRUD with real-time SQLite updates
  2. Sales / billing with automatic PDF invoice generation
  3. Sales analytics dashboard (Matplotlib)
 
Run:  python inventory_system.py            (interactive menu)
      python inventory_system.py --demo     (load sample data + dashboard)
"""
 
import os
import sqlite3
import sys
from datetime import datetime, timedelta
import random
 
import matplotlib
 
# Use a non-interactive backend when no display is available
if not os.environ.get("DISPLAY") and sys.platform.startswith("linux"):
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
from fpdf import FPDF
 
DB_PATH = "inventory.db"
INVOICE_DIR = "invoices"
DASHBOARD_PATH = "sales_dashboard.png"
STORE_NAME = "My Store"
STORE_ADDRESS = "Ahmedabad, Gujarat, India"
 
 
# --------------------------------------------------------------------------
# Database layer
# --------------------------------------------------------------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
 
 
def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL UNIQUE,
                category      TEXT NOT NULL DEFAULT 'General',
                price         REAL NOT NULL CHECK (price >= 0),
                quantity      INTEGER NOT NULL CHECK (quantity >= 0),
                reorder_level INTEGER NOT NULL DEFAULT 5
            );
 
            CREATE TABLE IF NOT EXISTS sales (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_no  TEXT NOT NULL,
                customer    TEXT NOT NULL,
                product_id  INTEGER NOT NULL,
                quantity    INTEGER NOT NULL CHECK (quantity > 0),
                unit_price  REAL NOT NULL,
                total       REAL NOT NULL,
                sold_at     TEXT NOT NULL,
                FOREIGN KEY (product_id) REFERENCES products(id)
            );
            """
        )
 
 
# --------------------------------------------------------------------------
# Product CRUD
# --------------------------------------------------------------------------
def add_product(name, category, price, quantity, reorder_level=5):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO products (name, category, price, quantity, reorder_level) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, category, price, quantity, reorder_level),
        )
        return cur.lastrowid
 
 
def get_products(search=None):
    with get_conn() as conn:
        if search:
            like = f"%{search}%"
            return conn.execute(
                "SELECT * FROM products WHERE name LIKE ? OR category LIKE ? ORDER BY id",
                (like, like),
            ).fetchall()
        return conn.execute("SELECT * FROM products ORDER BY id").fetchall()
 
 
def get_product(product_id):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
 
 
def update_product(product_id, **fields):
    allowed = {"name", "category", "price", "quantity", "reorder_level"}
    fields = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not fields:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE products SET {set_clause} WHERE id = ?",
            (*fields.values(), product_id),
        )
        return cur.rowcount > 0
 
 
def delete_product(product_id):
    with get_conn() as conn:
        try:
            cur = conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
            return cur.rowcount > 0
        except sqlite3.IntegrityError:
            # Product has sales history; cannot be removed
            return False
 
 
def low_stock_products():
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM products WHERE quantity <= reorder_level ORDER BY quantity"
        ).fetchall()
 
 
# --------------------------------------------------------------------------
# Billing
# --------------------------------------------------------------------------
def next_invoice_no():
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(DISTINCT invoice_no) AS n FROM sales").fetchone()
    return f"INV-{datetime.now():%Y%m}-{row['n'] + 1:04d}"
 
 
def create_sale(customer, items, sold_at=None):
    """
    items: list of (product_id, quantity)
    Deducts stock and records sales in ONE transaction (all or nothing).
    Returns (invoice_no, line_items) where line_items are dicts.
    """
    invoice_no = next_invoice_no()
    sold_at = sold_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []
 
    conn = get_conn()
    try:
        with conn:  # commits on success, rolls back on exception
            for product_id, qty in items:
                prod = conn.execute(
                    "SELECT * FROM products WHERE id = ?", (product_id,)
                ).fetchone()
                if prod is None:
                    raise ValueError(f"Product ID {product_id} not found")
                if qty <= 0:
                    raise ValueError("Quantity must be positive")
                if prod["quantity"] < qty:
                    raise ValueError(
                        f"Insufficient stock for '{prod['name']}' "
                        f"(available {prod['quantity']}, requested {qty})"
                    )
                total = prod["price"] * qty
                conn.execute(
                    "UPDATE products SET quantity = quantity - ? WHERE id = ?",
                    (qty, product_id),
                )
                conn.execute(
                    "INSERT INTO sales (invoice_no, customer, product_id, quantity, "
                    "unit_price, total, sold_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (invoice_no, customer, product_id, qty, prod["price"], total, sold_at),
                )
                lines.append(
                    {"name": prod["name"], "qty": qty, "price": prod["price"], "total": total}
                )
    finally:
        conn.close()
    return invoice_no, lines, sold_at
 
 
class InvoicePDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 18)
        self.cell(0, 10, STORE_NAME, new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 10)
        self.cell(0, 6, STORE_ADDRESS, new_x="LMARGIN", new_y="NEXT")
        self.ln(4)
 
    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, "Thank you for your business!", align="C")
 
 
def generate_invoice(invoice_no, customer, lines, sold_at, gst_rate=0.18):
    os.makedirs(INVOICE_DIR, exist_ok=True)
    pdf = InvoicePDF()
    pdf.add_page()
 
    # Invoice meta
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "INVOICE", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Invoice No : {invoice_no}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Date       : {sold_at}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Customer   : {customer}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
 
    # Table header
    col_w = [80, 25, 40, 45]
    pdf.set_fill_color(230, 230, 230)
    pdf.set_font("Helvetica", "B", 10)
    for w, title in zip(col_w, ["Item", "Qty", "Unit Price", "Amount"]):
        pdf.cell(w, 8, title, border=1, fill=True, align="C")
    pdf.ln()
 
    # Rows
    pdf.set_font("Helvetica", "", 10)
    subtotal = 0
    for ln in lines:
        pdf.cell(col_w[0], 8, ln["name"][:38], border=1)
        pdf.cell(col_w[1], 8, str(ln["qty"]), border=1, align="C")
        pdf.cell(col_w[2], 8, f"{ln['price']:.2f}", border=1, align="R")
        pdf.cell(col_w[3], 8, f"{ln['total']:.2f}", border=1, align="R")
        pdf.ln()
        subtotal += ln["total"]
 
    gst = subtotal * gst_rate
    grand = subtotal + gst
 
    # Totals
    label_w = sum(col_w[:3])
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(label_w, 8, "Subtotal", border=1, align="R")
    pdf.cell(col_w[3], 8, f"{subtotal:.2f}", border=1, align="R")
    pdf.ln()
    pdf.cell(label_w, 8, f"GST ({gst_rate:.0%})", border=1, align="R")
    pdf.cell(col_w[3], 8, f"{gst:.2f}", border=1, align="R")
    pdf.ln()
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(label_w, 9, "Grand Total (INR)", border=1, align="R")
    pdf.cell(col_w[3], 9, f"{grand:.2f}", border=1, align="R")
 
    path = os.path.join(INVOICE_DIR, f"{invoice_no}.pdf")
    pdf.output(path)
    return path
 
 
# --------------------------------------------------------------------------
# Analytics
# --------------------------------------------------------------------------
def build_dashboard(show=True):
    with get_conn() as conn:
        by_product = conn.execute(
            """SELECT p.name, SUM(s.quantity) AS units, SUM(s.total) AS revenue
               FROM sales s JOIN products p ON p.id = s.product_id
               GROUP BY p.id ORDER BY revenue DESC LIMIT 8"""
        ).fetchall()
        by_day = conn.execute(
            """SELECT date(sold_at) AS day, SUM(total) AS revenue
               FROM sales GROUP BY day ORDER BY day"""
        ).fetchall()
        by_category = conn.execute(
            """SELECT p.category, SUM(s.total) AS revenue
               FROM sales s JOIN products p ON p.id = s.product_id
               GROUP BY p.category"""
        ).fetchall()
        stock = conn.execute(
            "SELECT name, quantity, reorder_level FROM products ORDER BY quantity LIMIT 8"
        ).fetchall()
 
    if not by_product:
        print("No sales data yet - make a sale first.")
        return None
 
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    fig.suptitle("Sales Analytics Dashboard", fontsize=16, fontweight="bold")
 
    # 1. Revenue by product
    ax = axes[0][0]
    ax.barh([r["name"] for r in by_product][::-1], [r["revenue"] for r in by_product][::-1],
            color="#4C78A8")
    ax.set_title("Top Products by Revenue")
    ax.set_xlabel("Revenue (INR)")
 
    # 2. Daily sales trend
    ax = axes[0][1]
    ax.plot([r["day"] for r in by_day], [r["revenue"] for r in by_day],
            marker="o", color="#F58518")
    ax.set_title("Daily Sales Trend")
    ax.set_ylabel("Revenue (INR)")
    ax.tick_params(axis="x", rotation=45)
    step = max(1, len(by_day) // 8)
    for i, label in enumerate(ax.get_xticklabels()):
        label.set_visible(i % step == 0)
 
    # 3. Category share
    ax = axes[1][0]
    ax.pie([r["revenue"] for r in by_category], labels=[r["category"] for r in by_category],
           autopct="%1.1f%%", startangle=90)
    ax.set_title("Revenue Share by Category")
 
    # 4. Lowest stock levels vs reorder level
    ax = axes[1][1]
    names = [r["name"] for r in stock]
    x = range(len(names))
    ax.bar(x, [r["quantity"] for r in stock], color="#54A24B", label="In stock")
    ax.plot(x, [r["reorder_level"] for r in stock], "r--o", label="Reorder level")
    ax.set_xticks(list(x))
    ax.set_xticklabels(names, rotation=45, ha="right")
    ax.set_title("Lowest Stock Levels")
    ax.legend()
 
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(DASHBOARD_PATH, dpi=120)
    print(f"Dashboard saved to {DASHBOARD_PATH}")
    if show and matplotlib.get_backend().lower() != "agg":
        plt.show()
    plt.close(fig)
    return DASHBOARD_PATH
 
 
# --------------------------------------------------------------------------
# Demo data
# --------------------------------------------------------------------------
def load_demo_data():
    sample = [
        ("Wireless Mouse", "Electronics", 599, 50, 10),
        ("Mechanical Keyboard", "Electronics", 2499, 30, 8),
        ("USB-C Cable", "Accessories", 199, 100, 20),
        ("Laptop Stand", "Accessories", 999, 25, 5),
        ("Notebook A5", "Stationery", 79, 200, 30),
        ("Gel Pen (Pack of 10)", "Stationery", 120, 150, 25),
        ("Webcam HD", "Electronics", 1799, 20, 5),
        ("Desk Lamp", "Home Office", 899, 40, 8),
    ]
    for name, cat, price, qty, rl in sample:
        try:
            add_product(name, cat, price, qty, rl)
        except sqlite3.IntegrityError:
            pass  # already exists
 
    random.seed(7)
    products = get_products()
    customers = ["Amit Shah", "Priya Patel", "Rahul Mehta", "Neha Joshi", "Karan Desai"]
    for days_ago in range(14, -1, -1):
        for _ in range(random.randint(1, 3)):
            chosen = random.sample(products, k=random.randint(1, 3))
            items = [(p["id"], random.randint(1, 3)) for p in chosen]
            when = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
            try:
                inv, lines, ts = create_sale(random.choice(customers), items, sold_at=when)
                if days_ago == 0:
                    generate_invoice(inv, "Demo Customer", lines, ts)
            except ValueError:
                pass
    print("Demo data loaded.")
 
 
# --------------------------------------------------------------------------
# CLI helpers
# --------------------------------------------------------------------------
def print_products(rows):
    if not rows:
        print("  (no products)")
        return
    print(f"\n{'ID':<4}{'Name':<28}{'Category':<14}{'Price':>10}{'Qty':>6}{'Reorder':>9}")
    print("-" * 71)
    for r in rows:
        flag = "  <-- LOW" if r["quantity"] <= r["reorder_level"] else ""
        print(f"{r['id']:<4}{r['name'][:26]:<28}{r['category'][:12]:<14}"
              f"{r['price']:>10.2f}{r['quantity']:>6}{r['reorder_level']:>9}{flag}")
 
 
def ask(prompt, cast=str, default=None, allow_blank=False):
    while True:
        raw = input(prompt).strip()
        if raw == "" and (allow_blank or default is not None):
            return default
        try:
            return cast(raw)
        except ValueError:
            print("  Invalid input, try again.")
 
 
def menu_add():
    name = ask("Name: ")
    category = ask("Category [General]: ", default="General")
    price = ask("Price: ", float)
    qty = ask("Quantity: ", int)
    reorder = ask("Reorder level [5]: ", int, default=5)
    try:
        pid = add_product(name, category, price, qty, reorder)
        print(f"  Added product #{pid}")
    except sqlite3.IntegrityError as e:
        print(f"  Could not add product: {e}")
 
 
def menu_update():
    pid = ask("Product ID to update: ", int)
    prod = get_product(pid)
    if not prod:
        print("  Not found.")
        return
    print("  Leave blank to keep the current value.")
    name = ask(f"Name [{prod['name']}]: ", default=None, allow_blank=True)
    category = ask(f"Category [{prod['category']}]: ", default=None, allow_blank=True)
    price = ask(f"Price [{prod['price']}]: ", float, default=None, allow_blank=True)
    qty = ask(f"Quantity [{prod['quantity']}]: ", int, default=None, allow_blank=True)
    reorder = ask(f"Reorder level [{prod['reorder_level']}]: ", int, default=None, allow_blank=True)
    ok = update_product(pid, name=name, category=category, price=price,
                        quantity=qty, reorder_level=reorder)
    print("  Updated." if ok else "  Nothing changed.")
 
 
def menu_delete():
    pid = ask("Product ID to delete: ", int)
    if delete_product(pid):
        print("  Deleted.")
    else:
        print("  Could not delete (not found, or it has sales history).")
 
 
def menu_sell():
    customer = ask("Customer name: ")
    items = []
    while True:
        pid = ask("Product ID (blank to finish): ", int, default=None, allow_blank=True)
        if pid is None:
            break
        prod = get_product(pid)
        if not prod:
            print("  Product not found.")
            continue
        qty = ask(f"Quantity for '{prod['name']}' (stock {prod['quantity']}): ", int)
        items.append((pid, qty))
    if not items:
        print("  No items - sale cancelled.")
        return
    try:
        inv, lines, ts = create_sale(customer, items)
    except ValueError as e:
        print(f"  Sale failed: {e}")
        return
    path = generate_invoice(inv, customer, lines, ts)
    print(f"  Sale complete. Invoice saved to {path}")
 
 
def main():
    init_db()
    if "--demo" in sys.argv:
        load_demo_data()
        build_dashboard(show=False)
        return
 
    actions = {
        "1": ("Add product", menu_add),
        "2": ("View all products", lambda: print_products(get_products())),
        "3": ("Search products", lambda: print_products(get_products(ask("Search: ")))),
        "4": ("Update product", menu_update),
        "5": ("Delete product", menu_delete),
        "6": ("New sale + PDF invoice", menu_sell),
        "7": ("Low-stock report", lambda: print_products(low_stock_products())),
        "8": ("Sales dashboard", build_dashboard),
        "9": ("Load demo data", load_demo_data),
        "0": ("Exit", None),
    }
    while True:
        print("\n=== INVENTORY MANAGEMENT SYSTEM ===")
        for key, (label, _) in actions.items():
            print(f" {key}. {label}")
        choice = input("Choose: ").strip()
        if choice == "0":
            print("Goodbye!")
            break
        if choice in actions:
            actions[choice][1]()
        else:
            print("  Invalid choice.")
 
 
if __name__ == "__main__":
    main()
 