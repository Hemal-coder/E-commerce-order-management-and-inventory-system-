from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import threading
from typing import Dict, List, Optional


# ----------------------------------------------------------------------
# Domain Exceptions
# ----------------------------------------------------------------------
class StoreException(Exception):
    """Base exception for inventory and store operations."""


class ProductNotFoundError(StoreException):
    """Raised when an item SKU does not exist in the catalog."""


class InsufficientStockError(StoreException):
    """Raised when requested quantity exceeds available stock."""


class InsufficientFundsError(StoreException):
    """Raised when customer balance cannot cover the order total."""


# ----------------------------------------------------------------------
# Data Models
# ----------------------------------------------------------------------
@dataclass
class Product:
    sku: str
    name: str
    price: Decimal
    stock: int

    def __post_init__(self):
        self.price = Decimal(str(self.price)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.stock = int(self.stock)
        if self.stock < 0:
            raise ValueError(f"Initial stock for {self.sku} cannot be negative.")


@dataclass(frozen=True)
class OrderItem:
    sku: str
    qty: int

    def __post_init__(self):
        qty = int(self.qty)
        if qty <= 0:
            raise ValueError(f"Order quantity must be positive. Received {qty} for SKU {self.sku}.")
        object.__setattr__(self, "qty", qty)


@dataclass
class OrderRecord:
    order_id: str
    customer_id: str
    items: List[dict]
    subtotal: str
    discount: str
    tax: str
    total: str
    timestamp: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


# ----------------------------------------------------------------------
# Core Services
# ----------------------------------------------------------------------
class InventorySystem:
    def __init__(self, catalog: Optional[Dict[str, Product]] = None):
        self._catalog: Dict[str, Product] = catalog if catalog is not None else {}
        self._lock = threading.RLock()

    def add_product(self, sku: str, name: str, price: float | str | Decimal, stock: int) -> None:
        with self._lock:
            self._catalog[sku] = Product(
                sku=sku,
                name=name,
                price=Decimal(str(price)),
                stock=int(stock)
            )

    def get_product(self, sku: str) -> Product:
        with self._lock:
            if sku not in self._catalog:
                raise ProductNotFoundError(f"SKU '{sku}' does not exist in catalog.")
            return self._catalog[sku]

    def verify_availability(self, sku: str, quantity: int) -> None:
        """Validates product existence and stock without mutating state."""
        product = self.get_product(sku)
        if product.stock < quantity:
            raise InsufficientStockError(
                f"Insufficient stock for {sku} ({product.name}). Requested: {quantity}, Available: {product.stock}"
            )

    def reduce_stock(self, sku: str, quantity: int) -> None:
        with self._lock:
            self.verify_availability(sku, quantity)
            self._catalog[sku].stock -= quantity

    def restore_stock(self, sku: str, quantity: int) -> None:
        """Rollback helper to restore inventory state on failed transactions."""
        with self._lock:
            if sku in self._catalog:
                self._catalog[sku].stock += quantity


class Customer:
    def __init__(self, customer_id: str, name: str, balance: float | str | Decimal):
        self.customer_id = customer_id
        self.name = name
        self.balance = Decimal(str(balance)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self._lock = threading.RLock()

    def deduct_balance(self, amount: Decimal) -> None:
        with self._lock:
            amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if self.balance < amount:
                raise InsufficientFundsError(
                    f"Customer {self.customer_id} has insufficient balance (${self.balance}) for total (${amount})."
                )
            self.balance -= amount

    def refund_balance(self, amount: Decimal) -> None:
        with self._lock:
            self.balance += amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class OrderProcessor:
    def __init__(self, inventory: InventorySystem):
        self.inventory = inventory
        self.orders: List[OrderRecord] = []
        self._lock = threading.RLock()

    @staticmethod
    def calculate_tax(amount: Decimal, tax_rate: Decimal) -> Decimal:
        tax = amount * tax_rate
        return tax.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def apply_discount(amount: Decimal, discount_percent: Decimal) -> Decimal:
        discount_amount = (amount * (discount_percent / Decimal("100"))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return amount - discount_amount

    def process_order(
        self,
        order_id: str,
        customer: Customer,
        items: List[OrderItem],
        discount_percent: float | str | Decimal = 0,
        tax_rate: float | str | Decimal = Decimal("0.08"),
    ) -> OrderRecord:
        discount_dec = Decimal(str(discount_percent))
        tax_rate_dec = Decimal(str(tax_rate))

        # Phase 1: Pre-validation & Subtotal Calculation
        subtotal = Decimal("0.00")
        for item in items:
            self.inventory.verify_availability(item.sku, item.qty)
            product = self.inventory.get_product(item.sku)
            subtotal += product.price * Decimal(item.qty)

        discounted_subtotal = self.apply_discount(subtotal, discount_dec)
        tax_amount = self.calculate_tax(discounted_subtotal, tax_rate_dec)
        total_amount = (discounted_subtotal + tax_amount).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # Phase 2: Atomic Execution with Rollback Compensation
        reserved_items: List[OrderItem] = []
        payment_processed = False

        try:
            # 2a: Deduct stock from inventory
            for item in items:
                self.inventory.reduce_stock(item.sku, item.qty)
                reserved_items.append(item)

            # 2b: Deduct funds from customer
            customer.deduct_balance(total_amount)
            payment_processed = True

        except (InsufficientStockError, InsufficientFundsError) as exc:
            # Rollback: revert state changes in reverse order
            if payment_processed:
                customer.refund_balance(total_amount)
            for rollback_item in reversed(reserved_items):
                self.inventory.restore_stock(rollback_item.sku, rollback_item.qty)
            raise exc

        # Phase 3: Finalize and log order record
        record = OrderRecord(
            order_id=order_id,
            customer_id=customer.customer_id,
            items=[asdict(item) for item in items],
            subtotal=str(subtotal),
            discount=str(subtotal - discounted_subtotal),
            tax=str(tax_amount),
            total=str(total_amount),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        with self._lock:
            self.orders.append(record)

        return record


# ----------------------------------------------------------------------
# Execution & Verification
# ----------------------------------------------------------------------
if __name__ == "__main__":
    inventory = InventorySystem()
    inventory.add_product("SKU101", "Wireless Mouse", price="25.00", stock=10)
    inventory.add_product("SKU102", "Mechanical Keyboard", price="75.00", stock=5)

    buyer = Customer(customer_id="C001", name="Alice", balance="150.00")
    processor = OrderProcessor(inventory)

    # Scenario 1: Successful Order
    print("--- Scenario 1: Successful Order ---")
    valid_cart = [
        OrderItem(sku="SKU101", qty=2),  # 25.00 * 2 = 50.00
        OrderItem(sku="SKU102", qty=1),  # 75.00 * 1 = 75.00 (Subtotal = 125.00)
    ]

    order = processor.process_order(
        order_id="ORD-001",
        customer=buyer,
        items=valid_cart,
        discount_percent=10,  # 125 - 12.50 = 112.50
        tax_rate=0.05,        # 112.50 * 0.05 = 5.63 (Total = 118.13)
    )
    print("Order Placed Successfully:")
    print(order.to_json())
    print(f"Alice's Remaining Balance: ${buyer.balance}")
    print(f"SKU101 Remaining Stock: {inventory.get_product('SKU101').stock}")
    print(f"SKU102 Remaining Stock: {inventory.get_product('SKU102').stock}\n")

    # Scenario 2: Rollback on Insufficient Balance
    print("--- Scenario 2: Rollback on Insufficient Balance ---")
    expensive_cart = [
        OrderItem(sku="SKU102", qty=2),  # Alice cannot afford this with her remaining ~$31.87
    ]
    try:
        processor.process_order(
            order_id="ORD-002",
            customer=buyer,
            items=expensive_cart,
            discount_percent=0,
            tax_rate=0.05,
        )
    except InsufficientFundsError as err:
        print(f"Caught expected error: {err}")
        print(f"Alice's Balance Unchanged: ${buyer.balance}")
        print(f"SKU102 Stock Preserved: {inventory.get_product('SKU102').stock}")
        
