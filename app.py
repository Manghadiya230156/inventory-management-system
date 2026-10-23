"""
Streamlit UI for the Inventory Management System.
Run:  streamlit run app.py
"""

import sqlite3

import pandas as pd
import streamlit as st

import inventory_system as inv

st.set_page_config(page_title="Inventory Management", page_icon="📦", layout="wide")
inv.init_db()

if "cart" not in st.session_state:
    st.session_state.cart = []          # list of {"id", "name", "price", "qty"}
if "last_invoice" not in st.session_state:
    st.session_state.last_invoice = None



def show_df(data, **kwargs):
    """st.dataframe that works on both old and new Streamlit versions."""
    try:
        st.dataframe(data, width="stretch", **kwargs)           # newer Streamlit
    except TypeError:
        st.dataframe(data, use_container_width=True, **kwargs)  # older Streamlit


def products_df(rows):
    return pd.DataFrame([dict(r) for r in rows]) if rows else pd.DataFrame()


# ----------------------------------------------------------------- sidebar
st.sidebar.title("📦 Inventory")
page = st.sidebar.radio(
    "Go to", ["Dashboard", "Products", "New Sale", "Sales History"], label_visibility="collapsed"
)
st.sidebar.divider()
if st.sidebar.button("Load demo data"):
    inv.load_demo_data()
    st.sidebar.success("Demo data loaded")
    st.rerun()


# --------------------------------------------------------------- dashboard
if page == "Dashboard":
    st.title("Sales Dashboard")

    with inv.get_conn() as conn:
        totals = conn.execute(
            "SELECT COALESCE(SUM(total),0) AS revenue, COUNT(DISTINCT invoice_no) AS orders, "
            "COALESCE(SUM(quantity),0) AS units FROM sales"
        ).fetchone()
        n_products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    low = inv.low_stock_products()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Revenue (before GST)", f"₹{totals['revenue']:,.0f}")
    c2.metric("Orders", totals["orders"])
    c3.metric("Units sold", totals["units"])
    c4.metric("Low-stock items", len(low), f"of {n_products} products", delta_color="off")

    fig = inv.make_dashboard_figure()
    if fig is None:
        st.info("No sales yet. Make a sale, or click **Load demo data** in the sidebar.")
    else:
        st.pyplot(fig)

    if low:
        st.subheader("⚠️ Low stock")
        show_df(products_df(low), hide_index=True)


# ---------------------------------------------------------------- products
elif page == "Products":
    st.title("Products")
    tab_view, tab_add, tab_edit = st.tabs(["View / Search", "Add product", "Edit / Delete"])

    with tab_view:
        q = st.text_input("Search by name or category")
        df = products_df(inv.get_products(q or None))
        if df.empty:
            st.info("No products found.")
        else:
            show_df(df, hide_index=True)

    with tab_add:
        with st.form("add_product", clear_on_submit=True):
            name = st.text_input("Name")
            category = st.text_input("Category", value="General")
            col1, col2, col3 = st.columns(3)
            price = col1.number_input("Price (₹)", min_value=0.0, step=1.0)
            qty = col2.number_input("Quantity", min_value=0, step=1)
            reorder = col3.number_input("Reorder level", min_value=0, value=5, step=1)
            if st.form_submit_button("Add product"):
                if not name.strip():
                    st.error("Name is required.")
                else:
                    try:
                        pid = inv.add_product(name.strip(), category.strip() or "General",
                                              price, int(qty), int(reorder))
                        st.success(f"Added product #{pid}")
                    except sqlite3.IntegrityError:
                        st.error("A product with that name already exists.")

    with tab_edit:
        rows = inv.get_products()
        if not rows:
            st.info("Nothing to edit yet.")
        else:
            options = {f"#{r['id']} - {r['name']}": r["id"] for r in rows}
            pid = options[st.selectbox("Select product", list(options))]
            p = inv.get_product(pid)

            with st.form(f"edit_{pid}"):
                name = st.text_input("Name", value=p["name"])
                category = st.text_input("Category", value=p["category"])
                col1, col2, col3 = st.columns(3)
                price = col1.number_input("Price (₹)", min_value=0.0, value=float(p["price"]), step=1.0)
                qty = col2.number_input("Quantity", min_value=0, value=int(p["quantity"]), step=1)
                reorder = col3.number_input("Reorder level", min_value=0,
                                            value=int(p["reorder_level"]), step=1)
                if st.form_submit_button("Save changes"):
                    try:
                        inv.update_product(pid, name=name.strip(), category=category.strip(),
                                           price=price, quantity=int(qty), reorder_level=int(reorder))
                        st.success("Updated.")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Another product already uses that name.")

            st.divider()
            confirm = st.checkbox("I want to delete this product", key=f"confirm_{pid}")
            if st.button("Delete product", type="primary", disabled=not confirm):
                if inv.delete_product(pid):
                    st.success("Deleted.")
                    st.rerun()
                else:
                    st.error("Can't delete: this product has sales history.")


# ---------------------------------------------------------------- new sale
elif page == "New Sale":
    st.title("New Sale")
    in_stock = [r for r in inv.get_products() if r["quantity"] > 0]

    if not in_stock:
        st.warning("No products in stock.")
    else:
        left, right = st.columns([3, 2])

        with left:
            customer = st.text_input("Customer name")
            options = {f"{r['name']}  (₹{r['price']:.2f}, stock {r['quantity']})": r for r in in_stock}
            chosen = options[st.selectbox("Product", list(options))]
            qty = st.number_input("Quantity", min_value=1, max_value=int(chosen["quantity"]), value=1)
            if st.button("Add to cart"):
                in_cart = sum(i["qty"] for i in st.session_state.cart if i["id"] == chosen["id"])
                if in_cart + qty > chosen["quantity"]:
                    st.error("Not enough stock for that quantity.")
                else:
                    st.session_state.cart.append(
                        {"id": chosen["id"], "name": chosen["name"],
                         "price": chosen["price"], "qty": int(qty)}
                    )
                    st.rerun()

        with right:
            st.subheader("Cart")
            if not st.session_state.cart:
                st.caption("Cart is empty.")
            else:
                cart_df = pd.DataFrame(st.session_state.cart)
                cart_df["amount"] = cart_df["price"] * cart_df["qty"]
                show_df(cart_df[["name", "qty", "price", "amount"]], hide_index=True)
                sub = cart_df["amount"].sum()
                st.write(f"Subtotal: **₹{sub:,.2f}**  \nGST (18%): ₹{sub * 0.18:,.2f}  \n"
                         f"Total: **₹{sub * 1.18:,.2f}**")

                b1, b2 = st.columns(2)
                if b2.button("Clear cart"):
                    st.session_state.cart = []
                    st.rerun()
                if b1.button("Checkout", type="primary"):
                    if not customer.strip():
                        st.error("Enter the customer name first.")
                    else:
                        # merge duplicate products before saving
                        merged = {}
                        for i in st.session_state.cart:
                            merged[i["id"]] = merged.get(i["id"], 0) + i["qty"]
                        try:
                            no, lines, ts = inv.create_sale(customer.strip(), list(merged.items()))
                            path = inv.generate_invoice(no, customer.strip(), lines, ts)
                            with open(path, "rb") as f:
                                st.session_state.last_invoice = (no, f.read())
                            st.session_state.cart = []
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))

    if st.session_state.last_invoice:
        no, data = st.session_state.last_invoice
        st.success(f"Sale complete: {no}")
        st.download_button("⬇️ Download invoice (PDF)", data, file_name=f"{no}.pdf",
                           mime="application/pdf")


# ------------------------------------------------------------ sales history
elif page == "Sales History":
    st.title("Sales History")
    with inv.get_conn() as conn:
        df = pd.read_sql_query(
            """SELECT s.invoice_no, s.sold_at, s.customer, p.name AS product,
                      s.quantity, s.unit_price, s.total
               FROM sales s JOIN products p ON p.id = s.product_id
               ORDER BY s.sold_at DESC, s.id DESC""",
            conn,
        )
    if df.empty:
        st.info("No sales recorded yet.")
    else:
        q = st.text_input("Filter by customer or invoice number")
        if q:
            mask = (df["customer"].str.contains(q, case=False)
                    | df["invoice_no"].str.contains(q, case=False))
            df = df[mask]
        show_df(df, hide_index=True)
        st.download_button("Export CSV", df.to_csv(index=False), "sales_history.csv", "text/csv")