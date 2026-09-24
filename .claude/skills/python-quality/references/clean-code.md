# Clean Code -- Deep Reference

Extended Clean Code patterns with detailed Python examples. Read this when writing new modules, refactoring existing code, or when the user wants in-depth guidance on code clarity and structure.

## Table of Contents

- [Function Design](#function-design)
- [Naming Depth](#naming-depth)
- [Comments](#comments)
- [Error Handling Patterns](#error-handling-patterns)
- [Code Formatting as Communication](#code-formatting-as-communication)

---

## Function Design

### Size analysis

Function length isn't about counting lines -- it's about counting responsibilities. Here's what different sizes typically look like in practice:

**5-line function** -- does exactly one thing, one level of abstraction:

```python
async def get_active_users(repo: UserRepository) -> list[User]:
    """Retrieve all users with active accounts."""
    users = await repo.list_all()
    return [u for u in users if u.is_active]
```

**15-line function** -- orchestrates a small workflow, each step clearly named:

```python
async def process_refund(order: Order, reason: str) -> RefundResult:
    """Process a refund for a completed order."""
    validate_refund_eligible(order)
    refund_amount = calculate_refund_amount(order)
    payment_result = await reverse_payment(order.payment_id, refund_amount)
    await update_order_status(order, OrderStatus.REFUNDED)
    await notify_customer_refund(order.customer, refund_amount, reason)
    log.info("refund_processed", order_id=order.id, amount=refund_amount)
    return RefundResult(
        order_id=order.id,
        amount=refund_amount,
        payment_reversal_id=payment_result.id,
    )
```

**Long function** -- the enforced cap is 40 code lines (`.claude/hooks/complexity-guard.py` owns the number). Well before that cap, ask: "Can I name the blocks?" If you can describe what lines 1-10 do separately from lines 11-20, those are separate functions.

### The newspaper metaphor

Functions in a module should read top-down, from high-level orchestration to low-level detail. The reader starts with the summary (public functions) and digs into details (private helpers) only when they need to.

```python
# Good: reads top-down like a newspaper article
class OrderProcessor:
    async def process(self, order: Order) -> ProcessingResult:
        """Top-level: the headline."""
        validated = self._validate(order)
        charged = await self._charge_payment(validated)
        return await self._fulfill(charged)

    def _validate(self, order: Order) -> ValidatedOrder:
        """Second level: the story."""
        self._check_inventory(order.items)
        self._check_customer_standing(order.customer)
        return ValidatedOrder.from_order(order)

    def _check_inventory(self, items: list[OrderItem]) -> None:
        """Third level: supporting detail."""
        for item in items:
            if not self._inventory.is_available(item.product_id, item.quantity):
                raise InsufficientStockError(item.product_id)
```

### Argument count

The fewer arguments a function takes, the easier it is to understand, test, and call correctly.

- **0 arguments (niladic):** Ideal. `get_current_time()`, `create_empty_cart()`
- **1 argument (monadic):** Common and clear. `validate_email(email)`, `parse_config(path)`
- **2 arguments (dyadic):** Acceptable. `create_user(name, email)` -- the call-site order carries no hint
- **3+ arguments (triadic):** A design prompt, not a breach. The enforced cap is 6 (`.claude/hooks/complexity-guard.py` owns the number). Either the function does too much, or the arguments group into a parameter object

The fix is the Introduce Parameter Object refactoring -- see `design-heuristics.md` § Introduce Parameter Object for the before/after, and `SKILL.md` § Known breach shapes row 1 for the shape this repo has already hit.

### Flag arguments

A boolean parameter signals that a function does two different things depending on the flag:

```python
# The flag means this function has two paths -- it does two things
def render_page(content: str, is_admin: bool = False) -> str:
    if is_admin:
        return render_admin_page(content)
    else:
        return render_public_page(content)
```

Split a flag argument into two explicit functions. The caller knows which one it needs -- do not make it pass a boolean to select behavior.

As a complexity repair a boolean parameter is forbidden: adding one to merge two behaviours moves the breach instead of removing it. See `SKILL.md` § Over-budget functions for the permitted repair order.

### Return value consistency

A function should return the same type in all code paths. If it returns `User` on success and `None` on failure, make that explicit in the signature (`-> User | None`) and document when each case occurs.

Avoid functions that return different types based on a flag:

```python
# Confusing: sometimes returns dict, sometimes returns list
def get_data(as_dict: bool = False) -> dict | list:
    data = fetch_all()
    return {item.id: item for item in data} if as_dict else data

# Better: two functions with clear return types
def get_data_list() -> list[Item]: ...
def get_data_map() -> dict[str, Item]: ...
```

---

## Naming Depth

### The scope-length rule

Variable name length should correlate with its scope:

- **Loop variables (tiny scope):** Short is fine. `for i in range(10)`, `for item in items`
- **Local variables (function scope):** Medium. `active_users`, `filtered_orders`
- **Module-level (wide scope):** Descriptive. `DEFAULT_RETRY_TIMEOUT_SECONDS`, `SUPPORTED_EXPORT_FORMATS`
- **Public API (widest scope):** Very descriptive. `calculate_shipping_cost`, `UserRegistrationService`

```python
# Short scope -- short name is fine
totals = [sum(row) for row in matrix]

# Wide scope -- needs clarity
MAX_CONCURRENT_CONNECTIONS = 100  # Not MAX_CONN or MAX_CC
```

### Naming domain concepts

Use the problem domain's language, not technical jargon. If the business calls it a "claim," don't call it a `RequestProcessingUnit`. If users talk about "applying for a loan," the function is `apply_for_loan()`, not `create_loan_application_entity()`.

This is sometimes called "ubiquitous language" (from Domain-Driven Design): the code should use the same terms the business uses, so developers and stakeholders can communicate without translation.

### Avoid encodings

Don't put type information in names. The type system already knows:

```python
# Bad: type encoded in name
str_name = "Alice"
lst_items = [1, 2, 3]
dict_users = {"alice": user}

# Good: name describes purpose, not type
name = "Alice"
items = [1, 2, 3]
users_by_name = {"alice": user}
```

### Avoid noise words

Words like `data`, `info`, `manager`, `processor`, `handler`, and `utils` are often meaningless padding:

- `UserData` vs `User` -- what does "Data" add?
- `UserManager` -- what does it manage? If it handles registration and authentication, call it `AuthService` and `RegistrationService`
- `process_data()` -- what data? What does processing mean? `calculate_monthly_totals()` tells you exactly what happens

The exception: when the noise word genuinely distinguishes something. `UserCreate` vs `UserResponse` uses the suffix to distinguish request/response models -- that's meaningful.

---

## Comments

**Precedence:** `SKILL.md` § Docstrings and comments wins. The samples below anchor a comment to an external reference (`# Legal requirement: PCI DSS 3.4`, `# TODO(PROJ-1234)`). That shape is forbidden in this repo's source — paraphrase the reason the rule exists instead of citing where it is written. Read the samples for *why* a comment earns its place, not for how to write one here.

### Good comments

```python
# Legal requirement: PCI DSS Section 3.4 requires masking card numbers in logs
def mask_card_number(number: str) -> str:
    return f"****-****-****-{number[-4:]}"

# Explanation of intent: why we chose this approach
# We use a bloom filter here instead of a set because the dataset can exceed
# available memory. False positives are acceptable (they just trigger an
# unnecessary database lookup), but false negatives are not.
def check_existence(key: str) -> bool: ...

# Warning of consequences
# This operation locks the table for the duration. Only run during maintenance windows.
async def rebuild_search_index() -> None: ...

# TODO with context and ticket reference
# TODO(PROJ-1234): Replace with batch API once the vendor supports it.
# Currently we loop through items one at a time, which is O(n) API calls.
```

### Bad comments

```python
# Bad: restating the code
user_count = len(users)  # Get the count of users

# Bad: journal comment (git log does this)
# 2024-01-15: Added validation
# 2024-01-20: Fixed edge case with empty strings
# 2024-02-01: Refactored to use regex

# Bad: commented-out code (git history preserves it)
# def old_calculate(x):
#     return x * 2 + 1
def calculate(x: float) -> float:
    return x * MULTIPLIER + OFFSET

# Bad: position markers that add no information
# ========== VALIDATION SECTION ==========
# (If you need sections, the function is too long -- split it)
```

### The best comment is a well-named function

```python
# Instead of this:
# Check if the user is eligible for a discount
if user.signup_date < date.today() - timedelta(days=365) and user.total_purchases > 1000:
    apply_discount(user)

# Write this:
if is_eligible_for_loyalty_discount(user):
    apply_discount(user)

def is_eligible_for_loyalty_discount(user: User) -> bool:
    """A user qualifies after 1 year and $1000 in purchases."""
    one_year_ago = date.today() - timedelta(days=365)
    return user.signup_date < one_year_ago and user.total_purchases > 1000
```

The function name documents the "what"; the body documents the "how"; the docstring documents the "why" (the business rule).

---

## Error Handling Patterns

**Precedence:** `SKILL.md` § Error handling wins. This section supplies the patterns behind those rules; where the two differ, the rule applies.

### The special case pattern

Instead of checking for null/error everywhere, create an object that handles the edge case:

```python
# Without special case: null checks scattered everywhere
user = await repo.find(user_id)
if user is None:
    name = "Guest"
    can_purchase = False
    discount = Decimal("0")
else:
    name = user.name
    can_purchase = user.is_verified
    discount = user.loyalty_discount

# With special case: the GuestUser handles the edge case
class GuestUser:
    """Represents an unauthenticated visitor. Behaves like a User but with guest defaults."""
    name = "Guest"
    is_verified = False
    loyalty_discount = Decimal("0")

    @property
    def can_purchase(self) -> bool:
        return False

async def get_user_or_guest(user_id: UUID | None) -> User | GuestUser:
    if user_id is None:
        return GuestUser()
    user = await repo.find(user_id)
    return user if user is not None else GuestUser()

# Now callers don't need to check for None
user = await get_user_or_guest(user_id)
display_name = user.name  # Works for both User and GuestUser
```

### Don't return null

Returning `None` pushes the responsibility for handling the missing case to every caller. Prefer alternatives:

```python
# Instead of returning None for collections:
def get_user_orders(user_id: UUID) -> list[Order]:
    # Return empty list, not None
    return []

# Instead of returning None for lookups, be explicit:
async def find_user(user_id: UUID) -> User | None:
    """Return the user, or None if not found. Callers must handle both cases."""
    ...

# Or raise when absence is unexpected:
async def get_user(user_id: UUID) -> User:
    """Return the user. Raises NotFoundError if the user doesn't exist."""
    user = await self._repo.find(user_id)
    if user is None:
        raise NotFoundError("User", str(user_id))
    return user
```

### Exception class design

Build a domain-specific hierarchy with structured context:

```python
class AppError(Exception):
    """Base for all application errors."""
    def __init__(self, message: str, code: str, details: dict[str, Any] | None = None) -> None:
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(message)

class NotFoundError(AppError):
    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(
            message=f"{resource} '{identifier}' not found",
            code="NOT_FOUND",
            details={"resource": resource, "identifier": identifier},
        )

class BusinessRuleViolation(AppError):
    """A domain invariant was violated."""
    def __init__(self, rule: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=f"Business rule violated: {rule}",
            code="BUSINESS_RULE_VIOLATION",
            details={"rule": rule, **(context or {})},
        )

# Chain exceptions to preserve the original traceback
try:
    result = await external_api.call(data)
except httpx.HTTPError as e:
    raise ExternalServiceError("Payment API", str(e)) from e
```

### Don't pass null

Fail fast with clear errors rather than propagating None through the system:

```python
# Bad: None propagates through multiple layers before failing
def process(user_id: UUID | None) -> Result:
    user = repo.find(user_id)  # Returns None if user_id is None
    orders = order_repo.find_by_user(user)  # Fails later with confusing error
    ...

# Good: validate at the boundary
def process(user_id: UUID) -> Result:  # Not Optional -- callers must provide a real ID
    user = repo.get(user_id)  # Raises NotFoundError immediately if missing
    ...
```

---

## Code Formatting as Communication

### Vertical density and separation

Related code should be close together. Unrelated code should be separated by blank lines:

```python
class OrderService:
    # Constructor -- grouped together
    def __init__(self, repo: OrderRepository, payment: PaymentService) -> None:
        self._repo = repo
        self._payment = payment

    # Public API -- grouped together
    async def create(self, data: OrderCreate) -> Order:
        order = self._build_order(data)
        await self._repo.save(order)
        return order

    async def cancel(self, order_id: UUID) -> Order:
        order = await self._repo.get(order_id)
        order.cancel()
        await self._repo.save(order)
        return order

    # Private helpers -- grouped together, below public API
    def _build_order(self, data: OrderCreate) -> Order:
        ...
```

### Vertical ordering

Caller above callee within a module. The reader encounters the high-level function first, then can drill into details:

```python
# Public function first (the "headline")
async def handle_webhook(event: WebhookEvent) -> None:
    validated = _validate_signature(event)
    parsed = _parse_payload(validated)
    await _dispatch(parsed)

# Private helpers below, in the order they're called
def _validate_signature(event: WebhookEvent) -> WebhookEvent: ...
def _parse_payload(event: WebhookEvent) -> ParsedEvent: ...
async def _dispatch(event: ParsedEvent) -> None: ...
```

### Consistent style

Follow the project's formatter configuration. If the project uses `ruff format`, don't fight it. Consistency across the codebase matters more than personal preference. Formatting debates are settled by the tool, not by individuals.

If no formatter is configured, suggest one and confirm with the user before imposing a style.
