"""A small, real Flask app standing in for a retailer's website in tests.

Exposes just enough of a real e-commerce flow (search, add-to-cart, quantity update, cart
page) for Playwright to drive against — plus a checkout page and a `/debug/checkout-visits`
counter that automated tests use to prove the automation never reaches checkout.
"""

from flask import Flask, request

PRODUCTS = {
    "SKU-MILK": {"name": "Milk 3%", "whole_units_only": False},
    "SKU-BREAD": {"name": "Bread", "whole_units_only": False},
    "SKU-EGGS": {"name": "Eggs (dozen)", "whole_units_only": True},
    "SKU-YOG-A": {"name": "Yogurt", "whole_units_only": False},
    "SKU-YOG-B": {"name": "Yogurt", "whole_units_only": False},
}

MAX_QTY = 10  # simulates a site-side stock/quantity cap the adapter must verify against

BLOCK_TRIGGERS = {
    "TRIGGER_CAPTCHA": "<div data-captcha=\"1\">Are you human? Please solve the puzzle.</div>",
    "TRIGGER_LOGIN": "<div data-login-wall=\"1\">Please log in to continue.</div>",
}


def _cart_status_fragment(item_code: str, qty: float, error: str | None) -> str:
    error_attr = f' data-error="{error}"' if error else ""
    return f"""
    <div data-testid="cart-status" data-item-code="{item_code}" data-cart-qty="{qty}"{error_attr}>
      <form method="post" action="/cart/set_quantity">
        <input type="hidden" name="item_code" value="{item_code}">
        <input type="text" name="quantity" value="{qty}">
        <button data-testid="update-quantity" type="submit">Update</button>
      </form>
    </div>
    """


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["CART"] = {}
    app.config["CHECKOUT_VISITS"] = 0

    @app.route("/")
    def home():
        return "<html><body><h1>Mock Retailer</h1></body></html>"

    @app.route("/search")
    def search():
        query = request.args.get("q", "")

        if query in BLOCK_TRIGGERS:
            return f"<html><body>{BLOCK_TRIGGERS[query]}</body></html>"

        matches = [
            (code, product)
            for code, product in PRODUCTS.items()
            if code == query or query.strip().lower() in product["name"].lower()
        ]

        tiles = "\n".join(
            f"""
            <div data-testid="product-tile" data-item-code="{code}" data-name="{product['name']}">
              <span>{product['name']}</span>
              <form method="post" action="/cart/add">
                <input type="hidden" name="item_code" value="{code}">
                <button data-testid="add-to-cart" type="submit">Add</button>
              </form>
            </div>
            """
            for code, product in matches
        )
        return f"<html><body>{tiles}</body></html>"

    @app.route("/cart/add", methods=["POST"])
    def cart_add():
        item_code = request.form["item_code"]
        product = PRODUCTS.get(item_code)
        if product is None:
            return "not found", 404

        cart = app.config["CART"]
        cart.setdefault(item_code, 0)
        cart[item_code] = 1
        return f"<html><body>{_cart_status_fragment(item_code, 1, None)}</body></html>"

    @app.route("/cart/set_quantity", methods=["POST"])
    def cart_set_quantity():
        item_code = request.form["item_code"]
        quantity = float(request.form["quantity"])
        product = PRODUCTS.get(item_code)
        if product is None:
            return "not found", 404

        cart = app.config["CART"]
        if product["whole_units_only"] and quantity != int(quantity):
            fragment = _cart_status_fragment(
                item_code, cart.get(item_code, 0), "fractional_not_supported"
            )
            return f"<html><body>{fragment}</body></html>"

        quantity = min(quantity, MAX_QTY)
        cart[item_code] = quantity
        return f"<html><body>{_cart_status_fragment(item_code, quantity, None)}</body></html>"

    @app.route("/cart")
    def cart_page():
        cart = app.config["CART"]
        lines = "\n".join(
            f'<div data-testid="cart-line" data-item-code="{code}" data-cart-qty="{qty}"></div>'
            for code, qty in cart.items()
        )
        return f"<html><body>{lines}</body></html>"

    @app.route("/checkout")
    def checkout():
        app.config["CHECKOUT_VISITS"] += 1
        return "<html><body>Checkout — never expected to be visited by automation.</body></html>"

    @app.route("/debug/checkout-visits")
    def debug_checkout_visits():
        return {"count": app.config["CHECKOUT_VISITS"]}

    @app.route("/debug/cart")
    def debug_cart():
        return dict(app.config["CART"])

    @app.route("/debug/reset", methods=["POST"])
    def debug_reset():
        app.config["CART"] = {}
        app.config["CHECKOUT_VISITS"] = 0
        return "", 204

    return app
