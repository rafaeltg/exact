# SOLID Principles -- Deep Reference

Extended coverage of each SOLID principle with comprehensive Python examples, edge cases, and common debates. Read this when implementing complex services, refactoring design debt, or when the user asks for in-depth SOLID guidance.

## Table of Contents

- [Single Responsibility Principle (SRP)](#single-responsibility-principle-srp)
- [Open/Closed Principle (OCP)](#openclosed-principle-ocp)
- [Liskov Substitution Principle (LSP)](#liskov-substitution-principle-lsp)
- [Interface Segregation Principle (ISP)](#interface-segregation-principle-isp)
- [Dependency Inversion Principle (DIP)](#dependency-inversion-principle-dip)

---

## Single Responsibility Principle (SRP)

### Identifying responsibilities

The key question isn't "does this class have one method?" -- it's "how many actors could request changes to this class?" An actor is a person or group with a distinct reason to want the code changed.

**The "reasons to change" heuristic:** List who might ask you to modify the class. If the answer includes "the security team AND the product team AND the ops team," you have multiple responsibilities.

**The "actor" heuristic:** Who depends on this code? If the CFO's report and the CTO's monitoring dashboard both read from the same class, that class serves two actors.

### Multi-scale examples

#### Function-level SRP

```python
# Violation: this function validates AND transforms AND persists
async def handle_user_signup(raw_data: dict) -> User:
    # Validation logic (30 lines)
    if not raw_data.get("email") or "@" not in raw_data["email"]:
        raise ValueError("Invalid email")
    email = raw_data["email"].lower().strip()
    if len(raw_data.get("password", "")) < 8:
        raise ValueError("Password too short")
    hashed = bcrypt.hash(raw_data["password"])
    # ... more validation ...

    # Persistence logic (20 lines)
    user = User(email=email, password_hash=hashed)
    await db.execute(insert(users).values(user.dict()))
    # ... more persistence ...

    # Notification logic (15 lines)
    await smtp.send(to=email, subject="Welcome", body=render_template("welcome.html", user=user))
    return user

# Fix: each concern is a separate function
async def handle_user_signup(raw_data: dict) -> User:
    validated = validate_signup_data(raw_data)
    user = await create_user(validated)
    await send_welcome_email(user)
    return user
```

#### Class-level SRP

```python
# Violation: OrderService handles orders, payments, inventory, AND notifications
class OrderService:
    async def create_order(self, data: OrderCreate) -> Order: ...
    async def process_payment(self, order: Order) -> PaymentResult: ...
    async def update_inventory(self, order: Order) -> None: ...
    async def send_order_confirmation(self, order: Order) -> None: ...
    async def generate_invoice_pdf(self, order: Order) -> bytes: ...
    async def calculate_shipping(self, order: Order) -> ShippingQuote: ...
    async def apply_discount(self, order: Order, code: str) -> Order: ...

# Fix: separate services with clear responsibilities
class OrderService:
    """Orchestrates order lifecycle."""
    def __init__(
        self,
        repository: OrderRepository,
        payment: PaymentService,
        inventory: InventoryService,
        notifications: NotificationService,
    ) -> None: ...

    async def create_order(self, data: OrderCreate) -> Order:
        order = await self._repository.create(data)
        await self._payment.charge(order)
        await self._inventory.reserve(order.items)
        await self._notifications.order_created(order)
        return order

class PaymentService:
    """Handles payment processing."""
    async def charge(self, order: Order) -> PaymentResult: ...
    async def refund(self, order: Order) -> RefundResult: ...

class InventoryService:
    """Manages stock levels."""
    async def reserve(self, items: list[OrderItem]) -> None: ...
    async def release(self, items: list[OrderItem]) -> None: ...
```

#### Module-level SRP

```python
# Violation: user_management.py contains models, services, repositories, AND serializers
# user_management.py (800 lines)
class User: ...
class UserCreate: ...
class UserResponse: ...
class UserRepository: ...
class UserService: ...
class UserSerializer: ...

# Fix: separate modules by concern
# models/user.py -- domain entities
# schemas/user.py -- Pydantic request/response models
# repositories/user.py -- data access
# services/user.py -- business logic
```

### The tension: SRP vs cohesion

Splitting too aggressively creates its own problems. If two pieces of code change together for the same reason, keeping them separate increases coordination cost.

**Signs you've over-split:**

- Two classes that always change together in the same commit
- A class with a single method that just delegates to another class
- You need to read 5 files to understand one business operation
- Constructor parameter lists growing because you split collaborators too fine

**The guideline:** Split when responsibilities are genuinely independent (different actors, different change frequencies). Keep together when operations are tightly cohesive (same actor, same change reason).

---

## Open/Closed Principle (OCP)

### Strategy pattern with Protocols and registries

The most common Python implementation of OCP uses Protocols and a registry pattern:

```python
from typing import Protocol
from decimal import Decimal

class PaymentProcessor(Protocol):
    def process(self, amount: Decimal, details: PaymentDetails) -> Receipt: ...
    def refund(self, receipt: Receipt) -> RefundResult: ...

class StripeProcessor:
    def __init__(self, api_key: str) -> None:
        self._client = stripe.Client(api_key)

    def process(self, amount: Decimal, details: PaymentDetails) -> Receipt:
        charge = self._client.charges.create(amount=int(amount * 100), currency="usd")
        return Receipt(id=charge.id, amount=amount, provider="stripe")

    def refund(self, receipt: Receipt) -> RefundResult:
        self._client.refunds.create(charge=receipt.id)
        return RefundResult(receipt_id=receipt.id, status="refunded")

class PayPalProcessor:
    def process(self, amount: Decimal, details: PaymentDetails) -> Receipt: ...
    def refund(self, receipt: Receipt) -> RefundResult: ...

# Registry: maps payment method to processor -- adding a method means adding an entry
_PROCESSORS: dict[PaymentMethod, PaymentProcessor] = {}

def register_processor(method: PaymentMethod, processor: PaymentProcessor) -> None:
    _PROCESSORS[method] = processor

def get_processor(method: PaymentMethod) -> PaymentProcessor:
    processor = _PROCESSORS.get(method)
    if processor is None:
        raise UnsupportedPaymentMethodError(method)
    return processor
```

Adding a new payment method means writing a new class and registering it -- zero edits to existing code.

### Plugin architecture

For extension points that external code should be able to plug into:

```python
class ExportFormat(Protocol):
    """An export format that can serialize reports."""
    @property
    def name(self) -> str: ...
    @property
    def file_extension(self) -> str: ...
    def export(self, report: Report) -> bytes: ...

class CsvExporter:
    name = "csv"
    file_extension = ".csv"
    def export(self, report: Report) -> bytes: ...

class PdfExporter:
    name = "pdf"
    file_extension = ".pdf"
    def export(self, report: Report) -> bytes: ...

class ExportRegistry:
    def __init__(self) -> None:
        self._formats: dict[str, ExportFormat] = {}

    def register(self, exporter: ExportFormat) -> None:
        self._formats[exporter.name] = exporter

    def get(self, name: str) -> ExportFormat:
        if name not in self._formats:
            raise ValueError(f"Unknown export format: {name}")
        return self._formats[name]

    @property
    def available(self) -> list[str]:
        return list(self._formats.keys())
```

### Template Method vs Strategy

**Template Method** (using inheritance): the base class defines the algorithm skeleton, subclasses override specific steps. Use when the overall algorithm is fixed but individual steps vary.

**Strategy** (using composition): the algorithm is injected as a dependency. Use when you need to swap the entire behavior, especially at runtime.

In Python, prefer Strategy (composition) over Template Method (inheritance) as the default. Inheritance creates tighter coupling. Use Template Method only when the framework demands it or when the algorithm skeleton genuinely won't change.

### When OCP adds unnecessary complexity (YAGNI tension)

OCP tells you to design for extension. YAGNI tells you not to build for hypothetical futures. These principles are in tension, and the resolution is:

- **Apply OCP** when there's concrete evidence the code will be extended (the product roadmap mentions new payment methods, the current code already has 3+ branches in an if/elif)
- **Skip OCP** when extension is purely speculative (the app has one export format and nobody has asked for another)

The cost of adding a Strategy pattern for a single implementation is real: more files, more indirection, more cognitive load. Wait until you have two concrete implementations to design the abstraction.

---

## Liskov Substitution Principle (LSP)

### Behavioral contracts

LSP goes beyond type signatures. A subtype must honor:

1. **Preconditions:** The subtype can accept everything the base type accepts (may be broader, not narrower)
2. **Postconditions:** The subtype must provide everything the base type promises (may be stronger, not weaker)
3. **Invariants:** Properties that the base type maintains must also be maintained by the subtype

```python
class Logger(Protocol):
    """Contract: log() persists the message. It should not silently discard messages."""
    def log(self, level: str, message: str) -> None: ...

# LSP violation: silently drops messages when disk is full
class FileLogger:
    def log(self, level: str, message: str) -> None:
        try:
            self._file.write(f"[{level}] {message}\n")
        except IOError:
            pass  # Silently drops the message -- callers think it was logged

# LSP-compliant: propagates the error so callers know
class FileLogger:
    def log(self, level: str, message: str) -> None:
        try:
            self._file.write(f"[{level}] {message}\n")
        except IOError as e:
            raise LoggingError(f"Failed to write log: {e}") from e
```

### The Rectangle/Square problem and its real-world equivalents

The classic example: `Square` extends `Rectangle`, but setting width independently from height violates the contract. Real-world equivalents:

- `ReadOnlyRepository` extends `Repository` -- `save()` raises `NotImplementedError`
- `GuestUser` extends `User` -- `update_profile()` silently does nothing
- `CachedService` extends `Service` -- returns stale data without clients knowing

The fix is always the same: separate the interfaces so subtypes don't need to fake behavior they don't support.

### Protocol-based design naturally supports LSP

Python's Protocol-based approach avoids many LSP pitfalls because it's structural (duck typing with type safety) rather than nominal (inheritance-based). A class satisfies a Protocol by implementing its methods correctly -- there's no inheritance hierarchy to violate.

```python
class Readable(Protocol):
    async def read(self, id: UUID) -> Entity | None: ...

class Writable(Protocol):
    async def write(self, entity: Entity) -> Entity: ...

class FullRepository(Protocol):
    async def read(self, id: UUID) -> Entity | None: ...
    async def write(self, entity: Entity) -> Entity: ...

# ReadOnlyStore satisfies Readable but NOT Writable -- no LSP violation
class ReadOnlyStore:
    async def read(self, id: UUID) -> Entity | None: ...

# PostgresStore satisfies all three Protocols
class PostgresStore:
    async def read(self, id: UUID) -> Entity | None: ...
    async def write(self, entity: Entity) -> Entity: ...
```

---

## Interface Segregation Principle (ISP)

### Identifying segregation opportunities

Look for these signals:

- **Unused imports in tests:** If your mock needs to implement 10 methods but your test only cares about 2, the interface is too fat
- **`NotImplementedError` stubs:** If implementors raise on methods they don't support, those methods belong in a different interface
- **Consumers that use different subsets:** If module A calls methods 1-3 and module B calls methods 4-6, you have two interfaces masquerading as one

### Protocol composition in Python

Small Protocols compose naturally when a consumer needs multiple capabilities:

```python
class Reader(Protocol):
    async def get(self, id: UUID) -> Entity | None: ...
    async def list(self, filters: Filters) -> list[Entity]: ...

class Writer(Protocol):
    async def create(self, data: CreateData) -> Entity: ...
    async def update(self, id: UUID, data: UpdateData) -> Entity: ...

class Deleter(Protocol):
    async def delete(self, id: UUID) -> None: ...

# Consumer that needs read + write
class UserService:
    def __init__(self, repo: Reader & Writer) -> None:  # Protocol intersection (Python 3.12+)
        self._repo = repo

# Or express it as a new Protocol
class ReadWriteRepository(Reader, Writer, Protocol): ...
```

### The cost of over-segregation

Splitting every interface into single-method Protocols creates noise:

```python
# Over-segregated -- this is harder to work with, not easier
class CanGetById(Protocol):
    async def get(self, id: UUID) -> Entity | None: ...

class CanListAll(Protocol):
    async def list_all(self) -> list[Entity]: ...

class CanCreate(Protocol):
    async def create(self, data: CreateData) -> Entity: ...

class CanUpdate(Protocol):
    async def update(self, id: UUID, data: UpdateData) -> Entity: ...
```

If every consumer needs all four methods, you've added complexity without benefit. Split for real usage differences, not theoretical completeness.

**Rule of thumb:** If you can draw a line where some consumers need methods on one side and other consumers need methods on the other side, split there. If all consumers need everything, keep it together.

---

## Dependency Inversion Principle (DIP)

### The composition root pattern

The composition root is the single place in your application where concrete implementations are wired to their abstractions. Everything else depends only on Protocols.

```python
# composition_root.py -- the ONLY file that knows about concrete implementations
from app.services.user import UserService
from app.repositories.postgres.user import PostgresUserRepository
from app.infrastructure.email.smtp import SmtpEmailSender
from app.config import Settings

def create_user_service(settings: Settings) -> UserService:
    repository = PostgresUserRepository(settings.database_url)
    email_sender = SmtpEmailSender(settings.smtp_host, settings.smtp_port)
    return UserService(repository=repository, email_sender=email_sender)
```

The composition root is at the outermost layer of your application -- the entry point (FastAPI lifespan, CLI main function, script bootstrap). Business logic never imports concrete infrastructure classes.

### DIP in FastAPI

FastAPI's `Depends()` system naturally supports DIP:

```python
from fastapi import Depends, FastAPI
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Composition root: wire concrete implementations
    db_pool = await create_pool(settings.database_url)
    app.state.user_repo = PostgresUserRepository(db_pool)
    app.state.email_sender = SmtpEmailSender(settings.smtp)
    yield
    await db_pool.close()

def get_user_service(request: Request) -> UserService:
    return UserService(
        repository=request.app.state.user_repo,
        email_sender=request.app.state.email_sender,
    )

@router.post("/users")
async def create_user(
    data: UserCreate,
    service: UserService = Depends(get_user_service),
) -> UserResponse:
    user = await service.register(data)
    return UserResponse.model_validate(user)
```

### DIP vs dependency injection

They're related but distinct:

- **Dependency Inversion** is a design principle about the direction of dependencies: high-level modules depend on abstractions, not low-level details
- **Dependency injection** is a technique: passing dependencies into a class rather than having it create them internally

You can do dependency injection without DIP (inject a concrete `PostgresUserRepository` directly). DIP specifically requires that the dependency is on an abstraction (a `UserRepository` Protocol).

### When DIP is overkill

Not every dependency needs an abstraction:

- **Utility functions:** `math.sqrt()`, `json.dumps()`, `datetime.now()` -- these are stable and universal
- **Value objects:** A `Money` dataclass doesn't need a Protocol
- **Data transformations:** Pure functions that take input and produce output without side effects
- **Standard library types:** `list`, `dict`, `pathlib.Path`

Apply DIP at boundaries where implementations might change or where testing requires substitution: databases, HTTP clients, file systems, email services, external APIs.
