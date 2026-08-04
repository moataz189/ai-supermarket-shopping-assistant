def make_prepare_retailer_cart(retailer_cart_client):
    async def prepare_retailer_cart(state):
        if retailer_cart_client is None:
            # No Retailer-Cart MCP client configured — callers that don't care about CP8
            # (CP4/CP7's own tests, which choose a retailer without wiring one up) still
            # get a valid final_result; no browser is ever implied or launched here.
            return {"retailer_cart_result": None}

        retailer = state["chosen_retailer"]
        cart = state["retailer_carts"][retailer]
        items = [
            {"name": line["name"], "item_code": line["item_code"], "quantity": line["qty"]}
            for line in cart["items"]
        ]
        result = await retailer_cart_client.prepare_retailer_cart(retailer, items)
        return {"retailer_cart_result": result}

    return prepare_retailer_cart
