import json
from datetime import datetime

class InventorySystem:
    # BUG 1: Mutable default argument retains state across instances
    def __init__(self, catalog={}):
        self.catalog = catalog

    def add_product(self, sku, name, price, stock):
        self.catalog[sku] = {
            "name": name,
            "price": price,
            "stock": stock
        }

    def reduce_stock(self, sku, quantity):
        # BUG 2: KeyError risk if SKU doesn't exist; stock can drop below 0
        self.catalog[sku]["stock"] -= quantity


class Customer:
    def __init__(self, customer_id, name, balance):
        self.customer_id = customer_id
        self.name = name
        self.balance = balance

    def deduct_balance(self, amount):
        # BUG 3: Deducts balance even if amount > balance, creating negative funds
        self.balance -= amount
        return True


class OrderProcessor:
    def __init__(self, inventory):
        self.inventory = inventory
        self.orders = []

    def calculate_tax(self, subtotal, tax_rate):
        # BUG 4: Division by zero when tax_rate is 0, or logic error using rate as divisor
        return subtotal / tax_rate

    def apply_discount(self, total, discount_percent):
        # BUG 5: Off-by-one / operator precedence: returns incorrect discount calculation
        return total - total * discount_percent / 100

    def process_order(self, order_id, customer, items, discount=0, tax_rate=0.08):
        subtotal = 0

        # Validate & calculate subtotal
        for item in items:
            sku = item["sku"]
            qty = item["qty"]

            # BUG 6: String comparison against integer stock if qty passed as string
            # and no verification if sku is present in inventory
            if self.inventory.catalog[sku]["stock"] < qty:
                return f"Error: Insufficient stock for {sku}"

            # BUG 7: Float precision issues or type mismatch with price
            subtotal += self.inventory.catalog[sku]["price"] * qty

        # Apply discount and tax
        discounted = self.apply_discount(subtotal, discount)
        total = discounted + self.calculate_tax(discounted, tax_rate)

        # Process payment
        # BUG 8: customer.deduct_balance called before checking if funds exist
        if customer.balance < total:
            return "Error: Insufficient funds"
        customer.deduct_balance(total)

        # Deduct inventory
        for item in items:
            # BUG 9: Calling reduce_stock without checking, modifying state directly
            self.inventory.reduce_stock(item["sku"], item["qty"])

        order_record = {
            "order_id": order_id,
            "customer_id": customer.customer_id,
            "items": items,
            "total": total,
            # BUG 10: Calling non-existent method iso_format() instead of isoformat()
            "timestamp": datetime.now().iso_format()
        }

        self.orders.append(order_record)
        return order_record


# Running the buggy code
if __name__ == "__main__":
    store_inventory = InventorySystem()
    store_inventory.add_product("SKU101", "Wireless Mouse", 25.0, 10)
    store_inventory.add_product("SKU102", "Mechanical Keyboard", 75.0, 5)

    buyer = Customer("C001", "Alice", 150.0)
    processor = OrderProcessor(store_inventory)

    cart = [
        {"sku": "SKU101", "qty": 2},
        {"sku": "SKU102", "qty": 1}
    ]

    result = processor.process_order("ORD-001", buyer, cart, discount=10, tax_rate=0.05)
    print("Order Result:", result)
  
