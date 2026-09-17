# Design Heuristics -- Deep Reference

Deep coverage of structural design guidance, composition patterns, coupling/cohesion analysis, refactoring strategies, and anti-pattern recognition. Read this when designing new module boundaries, refactoring accumulated design debt, or analyzing existing code structure.

## Table of Contents

- [Composition Patterns](#composition-patterns)
- [Coupling Analysis](#coupling-analysis)
- [Cohesion Analysis](#cohesion-analysis)
- [Refactoring Catalog](#refactoring-catalog)
- [Anti-Patterns Catalog](#anti-patterns-catalog)

---

## Composition Patterns

### Delegation

The simplest composition pattern: forward calls to an internal collaborator.

```python
class CachedUserRepository:
    """Adds caching behavior to any UserRepository implementation."""

    def __init__(self, inner: UserRepository, cache: Cache) -> None:
        self._inner = inner
        self._cache = cache

    async def get(self, user_id: UUID) -> User | None:
        cached = await self._cache.get(f"user:{user_id}")
        if cached is not None:
            return cached
        user = await self._inner.get(user_id)
        if user is not None:
            await self._cache.set(f"user:{user_id}", user, ttl=300)
        return user

    async def create(self, data: UserCreate) -> User:
        user = await self._inner.create(data)
        await self._cache.set(f"user:{user.id}", user, ttl=300)
        return user
```

The `CachedUserRepository` has the same interface as the inner repository. Callers don't know (or care) that caching is involved.

### Decorator pattern

Wrapping an object to add cross-cutting behavior (logging, retry, metrics) without modifying it:

```python
class RetryingEmailSender:
    """Adds retry logic to any EmailSender."""

    def __init__(self, inner: EmailSender, max_retries: int = 3) -> None:
        self._inner = inner
        self._max_retries = max_retries

    async def send(self, to: str, subject: str, body: str) -> None:
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                await self._inner.send(to, subject, body)
                return
            except TransientError as e:
                last_error = e
                await asyncio.sleep(2 ** attempt)
        raise RetryExhaustedError(f"Failed after {self._max_retries} attempts") from last_error

class LoggingEmailSender:
    """Adds logging to any EmailSender."""

    def __init__(self, inner: EmailSender) -> None:
        self._inner = inner

    async def send(self, to: str, subject: str, body: str) -> None:
        log.info("sending_email", to=to, subject=subject)
        await self._inner.send(to, subject, body)
        log.info("email_sent", to=to, subject=subject)

# Decorators compose: retry wraps logging wraps the real sender
sender = RetryingEmailSender(
    LoggingEmailSender(
        SmtpEmailSender(settings.smtp)
    )
)
```

Each decorator adds one concern. They compose in any order.

### Strategy pattern

Swappable algorithms via Protocol + constructor injection:

```python
class PricingStrategy(Protocol):
    def calculate(self, items: list[CartItem]) -> Decimal: ...

class StandardPricing:
    def calculate(self, items: list[CartItem]) -> Decimal:
        return sum(item.price * item.quantity for item in items)

class BulkDiscountPricing:
    def __init__(self, threshold: int, discount_pct: Decimal) -> None:
        self._threshold = threshold
        self._discount_pct = discount_pct

    def calculate(self, items: list[CartItem]) -> Decimal:
        total = sum(item.price * item.quantity for item in items)
        total_quantity = sum(item.quantity for item in items)
        if total_quantity >= self._threshold:
            return total * (1 - self._discount_pct)
        return total

class CartService:
    def __init__(self, pricing: PricingStrategy) -> None:
        self._pricing = pricing

    def get_total(self, items: list[CartItem]) -> Decimal:
        return self._pricing.calculate(items)
```

The pricing algorithm can be swapped without touching `CartService`. Use this when the same operation has multiple implementations that vary by context.

### Observer pattern

Decoupling event producers from consumers:

```python
class EventBus:
    """Simple in-process event bus for decoupling producers from consumers."""

    def __init__(self) -> None:
        self._handlers: dict[type, list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: type[T], handler: Callable[[T], Awaitable[None]]) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: Any) -> None:
        for handler in self._handlers.get(type(event), []):
            await handler(event)

# Usage: OrderService publishes, NotificationService subscribes
# Neither knows about the other
class OrderService:
    def __init__(self, repo: OrderRepository, events: EventBus) -> None:
        self._repo = repo
        self._events = events

    async def complete(self, order_id: UUID) -> Order:
        order = await self._repo.get(order_id)
        order.complete()
        await self._repo.save(order)
        await self._events.publish(OrderCompleted(order_id=order.id, customer_id=order.customer_id))
        return order
```

Use observers when the producer shouldn't know (or care) who reacts to its events. This prevents the "shotgun surgery" smell where adding a new reaction means editing the producer.

### When to use `__getattr__` delegation vs explicit forwarding

Python's `__getattr__` can forward all attribute access to an inner object:

```python
class Wrapper:
    def __init__(self, inner: SomeService) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
```

This is concise but dangerous: it hides the interface, breaks IDE autocompletion, and makes it unclear what methods are available. Use explicit forwarding for public APIs. Reserve `__getattr__` for framework internals where the proxy pattern is well-understood (e.g., lazy loading wrappers).

---

## Coupling Analysis

### Types of coupling (worst to best)

1. **Content coupling:** One module directly modifies another's internal data (`other._private_field = value`). This is the worst form -- any change to the other module's internals breaks you.

2. **Common coupling:** Multiple modules share global/mutable state. Changes to the shared state affect all readers and writers unpredictably.

3. **Control coupling:** One module tells another what to do via a flag (`process(data, mode="fast")`). The caller knows about the callee's internal modes.

4. **Stamp coupling:** Passing a large data structure when only part of it is needed. The callee depends on the structure's shape even though it only uses a few fields.

5. **Data coupling:** Modules communicate through simple, well-defined parameters. Each module depends only on the data it actually uses.

6. **Message coupling:** Modules communicate only through a well-defined protocol/interface with no knowledge of each other's implementation. This is the ideal.

### Measuring coupling informally

- **Count the imports:** A module that imports 15 other modules is highly coupled
- **Count constructor parameters:** A class with 8 dependencies probably does too much
- **Count test setup lines:** If setting up a unit test requires 30 lines of mock configuration, coupling is too high
- **The "change ripple" test:** If changing one module's internal implementation requires changes in 5 other files, coupling is too high

### Stable vs volatile dependencies

Not all coupling is equal. It's fine to depend on stable things:

- **Standard library:** `datetime`, `pathlib`, `collections` -- these won't change
- **Well-established libraries:** `pydantic`, `structlog` -- their APIs are stable
- **Language primitives:** Built-in types, core patterns

Couple loosely to volatile things:

- **Your own infrastructure:** Database clients, HTTP clients, message queues -- wrap behind Protocols
- **External APIs:** Third-party services change without warning -- create an anti-corruption layer
- **Unstable internal modules:** Components that are actively being redesigned

### Breaking circular dependencies

Circular imports (`A imports B, B imports A`) are a structural problem, not just a Python limitation. They indicate tangled responsibilities.

**Common fixes:**

1. **Extract the shared concept:** If A and B both need `Thing`, extract it to a new module `C` that both import

2. **Depend on abstractions:** If A uses B's concrete class, have A depend on a Protocol that B implements. The Protocol lives in A's module (or a shared interfaces module).

3. **Invert the dependency:** If A calls B and B calls A, one direction should use events, callbacks, or dependency injection instead of direct imports

4. **Merge the modules:** If two modules are so intertwined that they can't be separated cleanly, they might be one module that was artificially split

---

## Cohesion Analysis

### Types of cohesion (worst to best)

1. **Coincidental:** Elements are in the same module by accident. A `Utils` class with unrelated static methods.

2. **Logical:** Elements are grouped because they're categorized together ("all validators"), not because they work together.

3. **Temporal:** Elements are grouped because they happen at the same time (startup initialization code) but aren't otherwise related.

4. **Procedural:** Elements are grouped because they follow a sequence, but each step operates on different data.

5. **Communicational:** Elements operate on the same data. A class whose methods all read/write the same fields.

6. **Sequential:** Output of one element is input to the next, and they operate on the same data.

7. **Functional:** All elements contribute to a single, well-defined task. This is the ideal.

### LCOM as an informal heuristic

LCOM (Lack of Cohesion of Methods) measures how many disjoint groups of methods exist based on shared field access. Informally:

- If every method in a class uses every field, cohesion is perfect
- If methods split into two groups that use completely different fields, the class probably has two responsibilities

```python
# Low cohesion: two disjoint groups of methods
class ReportService:
    def __init__(self, db: Database, email: EmailSender) -> None:
        self._db = db        # Used by generate methods
        self._email = email  # Used by send methods

    # Group 1: uses self._db
    def generate_monthly_report(self) -> Report: ...
    def generate_quarterly_report(self) -> Report: ...

    # Group 2: uses self._email
    def send_report_to_team(self, report: Report) -> None: ...
    def send_report_to_executives(self, report: Report) -> None: ...

# Better: separate into ReportGenerator and ReportDistributor
```

### Cohesion vs convenience

A `UserUtils` class is coincidental cohesion disguised as organization:

```python
# Bad: coincidental cohesion
class UserUtils:
    @staticmethod
    def format_name(first: str, last: str) -> str: ...

    @staticmethod
    def validate_email(email: str) -> bool: ...

    @staticmethod
    def calculate_age(birth_date: date) -> int: ...

    @staticmethod
    def generate_avatar_url(user_id: UUID) -> str: ...
```

These functions aren't related -- they just all happen to involve users. Put each one where it belongs: `format_name` in the User model, `validate_email` in the validation module, `calculate_age` as a method on a value object, `generate_avatar_url` in the avatar service.

---

## Refactoring Catalog

Python-focused refactoring moves. Each one addresses a specific code smell.

### Extract Method

**When:** A code block has a comment explaining what it does. The comment is the new function's name.

```python
# Before
async def process_order(order: Order) -> None:
    # Validate inventory
    for item in order.items:
        stock = await get_stock(item.product_id)
        if stock < item.quantity:
            raise InsufficientStockError(item.product_id)

    # Calculate total with discounts
    subtotal = sum(item.price * item.quantity for item in order.items)
    discount = calculate_loyalty_discount(order.customer)
    total = subtotal - discount

    # Process payment
    await charge_customer(order.customer, total)

# After
async def process_order(order: Order) -> None:
    await validate_inventory(order.items)
    total = calculate_order_total(order)
    await charge_customer(order.customer, total)
```

### Replace Conditional with Polymorphism

**When:** An `if/elif` chain switches on type or category.

```python
# Before
def calculate_shipping(order: Order) -> Decimal:
    if order.shipping_type == "standard":
        return Decimal("5.99")
    elif order.shipping_type == "express":
        return Decimal("12.99") + Decimal("0.50") * order.weight
    elif order.shipping_type == "overnight":
        return Decimal("24.99") + Decimal("1.00") * order.weight
    else:
        raise ValueError(f"Unknown shipping type: {order.shipping_type}")

# After
class ShippingCalculator(Protocol):
    def calculate(self, order: Order) -> Decimal: ...

class StandardShipping:
    def calculate(self, order: Order) -> Decimal:
        return Decimal("5.99")

class ExpressShipping:
    def calculate(self, order: Order) -> Decimal:
        return Decimal("12.99") + Decimal("0.50") * order.weight

class OvernightShipping:
    def calculate(self, order: Order) -> Decimal:
        return Decimal("24.99") + Decimal("1.00") * order.weight
```

### Introduce Parameter Object

**When:** 3+ parameters travel together across multiple functions.

```python
# Before: same parameters repeated everywhere
def search_products(category: str, min_price: Decimal, max_price: Decimal, in_stock: bool) -> list[Product]: ...
def count_products(category: str, min_price: Decimal, max_price: Decimal, in_stock: bool) -> int: ...
def export_products(category: str, min_price: Decimal, max_price: Decimal, in_stock: bool) -> bytes: ...

# After: parameter object captures the concept
class ProductFilter(BaseModel):
    category: str
    min_price: Decimal = Decimal("0")
    max_price: Decimal = Decimal("999999")
    in_stock: bool = True

def search_products(filters: ProductFilter) -> list[Product]: ...
def count_products(filters: ProductFilter) -> int: ...
def export_products(filters: ProductFilter) -> bytes: ...
```

### Replace Inheritance with Delegation

**When:** A subclass uses only a fraction of its parent's interface.

```python
# Before: AdminUser inherits everything from User but only uses a few methods
class User:
    def get_profile(self) -> Profile: ...
    def update_email(self, email: str) -> None: ...
    def get_order_history(self) -> list[Order]: ...
    def get_recommendations(self) -> list[Product]: ...

class AdminUser(User):
    def ban_user(self, user_id: UUID) -> None: ...
    def view_reports(self) -> list[Report]: ...

# After: AdminUser delegates to User for shared behavior
class AdminUser:
    def __init__(self, user: User) -> None:
        self._user = user

    def get_profile(self) -> Profile:
        return self._user.get_profile()

    def ban_user(self, user_id: UUID) -> None: ...
    def view_reports(self) -> list[Report]: ...
```

### Extract Interface (Protocol)

**When:** Multiple implementations exist, or testing requires swappable dependencies.

```python
# Before: service directly depends on concrete class
from app.infrastructure.postgres import PostgresUserRepo

class UserService:
    def __init__(self) -> None:
        self._repo = PostgresUserRepo()  # Hard dependency

# After: service depends on Protocol
class UserRepository(Protocol):
    async def get(self, user_id: UUID) -> User | None: ...
    async def create(self, data: UserCreate) -> User: ...

class UserService:
    def __init__(self, repo: UserRepository) -> None:
        self._repo = repo  # Injected, testable, swappable
```

### Move Method

**When:** A method uses more data from another class than its own (Feature Envy).

```python
# Before: Order calculates discount using Customer's data
class Order:
    def calculate_discount(self) -> Decimal:
        if self.customer.tier == "gold" and self.customer.years_active > 2:
            return self.total * Decimal("0.15")
        elif self.customer.tier == "silver":
            return self.total * Decimal("0.10")
        return Decimal("0")

# After: Customer knows its own discount rules
class Customer:
    def discount_rate(self) -> Decimal:
        if self.tier == "gold" and self.years_active > 2:
            return Decimal("0.15")
        elif self.tier == "silver":
            return Decimal("0.10")
        return Decimal("0")

class Order:
    def calculate_discount(self) -> Decimal:
        return self.total * self.customer.discount_rate()
```

### Decompose Conditional

**When:** A complex boolean expression obscures intent.

```python
# Before
if (user.created_at < date.today() - timedelta(days=365)
    and user.total_purchases > 1000
    and user.returns_count / max(user.orders_count, 1) < 0.1
    and not user.is_suspended):
    grant_loyalty_status(user)

# After: each predicate has a name
def is_longstanding_customer(user: User) -> bool:
    return user.created_at < date.today() - timedelta(days=365)

def has_significant_purchases(user: User) -> bool:
    return user.total_purchases > 1000

def has_low_return_rate(user: User) -> bool:
    return user.returns_count / max(user.orders_count, 1) < 0.1

if (is_longstanding_customer(user)
    and has_significant_purchases(user)
    and has_low_return_rate(user)
    and not user.is_suspended):
    grant_loyalty_status(user)
```

---

## Anti-Patterns Catalog

### God Object

One class that knows or does everything. Symptoms: 500+ lines, 20+ methods, imported by half the codebase.

**Why it's harmful:** Every change risks breaking something. Testing requires massive setup. Multiple developers can't work on it without merge conflicts.

**Fix:** Identify the distinct responsibilities (SRP analysis), extract each into its own class, and have the original class delegate or be replaced by an orchestrator.

### Anemic Domain Model

Domain objects are pure data containers with no behavior. All logic lives in services.

```python
# Anemic: Order is just a data bag
class Order:
    status: str
    items: list[OrderItem]
    total: Decimal

class OrderService:
    def cancel(self, order: Order) -> None:
        if order.status != "pending":
            raise ValueError("Can only cancel pending orders")
        order.status = "cancelled"
        # More rules scattered across services...

# Rich: Order encapsulates its own rules
class Order:
    def cancel(self) -> None:
        if self.status != OrderStatus.PENDING:
            raise InvalidStateTransition(self.status, OrderStatus.CANCELLED)
        self._status = OrderStatus.CANCELLED
        self._cancelled_at = datetime.now(UTC)
```

**Why it's harmful:** Business rules get scattered across services, duplicated, and become hard to discover. The domain model doesn't protect its own invariants.

**When it's acceptable:** Some domains are genuinely data-centric (ETL pipelines, report generation). Don't force behavior onto entities that are truly just data.

### Spaghetti Code

No clear structure. Functions call functions call functions with no layering or boundaries. Control flow is unpredictable.

**Fix:** Identify the layers (transport, business logic, data access), enforce dependency direction (outer layers depend on inner layers), and introduce clear module boundaries.

### Golden Hammer

Applying one pattern to every problem. If you have a Strategy pattern hammer, everything looks like a strategy nail.

**Fix:** Choose patterns based on the actual problem, not comfort. Ask: "What specific problem does this pattern solve here?" If you can't answer clearly, you don't need the pattern.

### Lava Flow

Dead code, unused abstractions, and deprecated patterns that nobody dares remove because they might still be needed.

**Fix:** Use tools to identify dead code (`vulture` for Python). Check git blame for when code was last meaningfully changed. If it hasn't been touched in a year and nothing imports it, delete it. Version control preserves history.

### Boat Anchor

Code kept "just in case" that adds maintenance burden without current value. Similar to lava flow but intentionally preserved.

**Fix:** Delete it. If you need it later, git has it. The cost of maintaining unused code (keeping it compiling, updating it during refactors) is higher than the cost of restoring it from history.
