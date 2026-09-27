
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import json


class InventorySystem:
    # Fix BUG 1: Use None as default parameter to avoid shared mutable state across instances
    def __init__(self, catalog=None):
        self.catalog = catalog if catalog is not None else {}

    def add_product(self, sku: str, name: str, price: float | Decimal, stock: int):
        self.catalog[sku] = {
            "name": name,
            "price": Decimal(str(price)),
            "stock": int(stock),
        }

    def has_stock(self, sku: str, quantity: int) -> bool:
        if sku not in self.catalog:
            return False
        return self.catalog[sku]["stock"] >= quantity

    def reduce_stock(self, sku: str, quantity: int) -> bool:
        # Fix BUG 2: Guard against missing SKUs and negative stock levels
        quantity = int(quantity)
        if not self.has_stock(sku, quantity):
            raise ValueError(f"Insufficient stock or invalid SKU: {sku}")
        self.catalog[sku]["stock"] -= quantity
        return True


class Customer:
    def __init__(self, customer_id: str, name: str, balance: float | Decimal):
        self.customer_id = customer_id
        self.name = name
        self.balance = Decimal(str(balance))

    def deduct_balance(self, amount: Decimal) -> bool:
        # Fix BUG 3: Prevent balance from dropping below zero
        if self.balance < amount:
            raise ValueError("Insufficient balance to complete the transaction.")
        self.balance -= amount
        return True


class OrderProcessor:
    def __init__(self, inventory: InventorySystem):
        self.inventory = inventory
        self.orders = []

    def calculate_tax(self, subtotal: Decimal, tax_rate: Decimal) -> Decimal:
        # Fix BUG 4: Tax should multiply the subtotal by tax_rate, not divide
        return subtotal * tax_rate

    def apply_discount(self, total: Decimal, discount_percent: Decimal) -> Decimal:
        # Fix BUG 5: Explicitly bound discount between 0 and 100% and compute correctly
        if discount_percent < 0 or discount_percent > 100:
            raise ValueError("Discount must be between 0 and 100 percent.")
        discount_amount = total * (discount_percent / Decimal("100"))
        return total - discount_amount

    def process_order(
        self,
        order_id: str,
        customer: Customer,
        items: list[dict],
        discount: float | Decimal = 0,
        tax_rate: float | Decimal = 0.08,
    ):
        discount_dec = Decimal(str(discount))
        tax_rate_dec = Decimal(str(tax_rate))
        subtotal = Decimal("0.00")

        # Fix BUG 6: Verify SKU existence and ensure quantity is cast to int before comparison
        for item in items:
            sku = item.get("sku")
            qty = int(item.get("qty", 0))

            if qty <= 0:
                return f"Error: Invalid quantity '{qty}' for SKU {sku}"

            if not self.inventory.has_stock(sku, qty):
                return f"Error: Insufficient stock or invalid SKU '{sku}'"

            # Fix BUG 7: Use Decimal arithmetic to prevent floating-point precision loss
            unit_price = self.inventory.catalog[sku]["price"]
            subtotal += unit_price * qty

        # Compute totals with banker's/half-up rounding for currency
        discounted = self.apply_discount(subtotal, discount_dec)
        tax = self.calculate_tax(discounted, tax_rate_dec)
        total = (discounted + tax).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Fix BUG 8: Check sufficient funds before attempting deduction
        if customer.balance < total:
            return f"Error: Insufficient funds. Required: {total}, Available: {customer.balance}"

        try:
            # Fix BUG 9: Deduct inventory and balance atomically
            customer.deduct_balance(total)
            for item in items:
                self.inventory.reduce_stock(item["sku"], int(item["qty"]))
        except ValueError as err:
            return f"Error processing order: {err}"

        order_record = {
            "order_id": order_id,
            "customer_id": customer.customer_id,
            "items": items,
            "subtotal": float(subtotal),
            "total": float(total),
            # Fix BUG 10: Correct method name is .isoformat(), not .iso_format()
            "timestamp": datetime.now().isoformat(),
        }

        self.orders.append(order_record)
        return order_record


if __name__ == "__main__":
    store_inventory = InventorySystem()
    store_inventory.add_product("SKU101", "Wireless Mouse", 25.0, 10)
    store_inventory.add_product("SKU102", "Mechanical Keyboard", 75.0, 5)

    buyer = Customer("C001", "Alice", 150.0)
    processor = OrderProcessor(store_inventory)

    cart = [
        {"sku": "SKU101", "qty": 2},  # 2 * 25.0 = 50.0
        {"sku": "SKU102", "qty": 1},  # 1 * 75.0 = 75.0 -> Subtotal: 125.0
    ]

    # Subtotal: 125.0 | 10% Discount: 112.50 | 5% Tax: 5.625 -> Total: 118.13
    result = processor.process_order("ORD-001", buyer, cart, discount=10, tax_rate=0.05)
    print("Order Result:\n", json.dumps(result, indent=2))
    print(f"Remaining Customer Balance: {buyer.balance}")
    print(f"Remaining SKU101 Stock: {store_inventory.catalog['SKU101']['stock']}")