# Refactoring Patterns

Authoritative before/after catalog. When a finding's fix matches a pattern below, the Suggestion must use that shape — not a vague paraphrase.

## 1. Loop → comprehension

Use when a loop only accumulates with a simple predicate. Do not use when the loop has side effects or multi-step logic.

```python
# Forbidden
result = []
for item in items:
    if item.active:
        result.append(item.name)

# Required
result = [item.name for item in items if item.active]
```

## 2. Nested conditionals → early return

```python
# Forbidden
def process(user: User | None) -> str | None:
    if user:
        if user.active:
            if user.email:
                return user.email.lower()
    return None


# Required
def process(user: User | None) -> str | None:
    if not user or not user.active or not user.email:
        return None
    return user.email.lower()
```

## 3. Manual data holder → `@dataclass` / Pydantic

```python
# Forbidden for pure data holders
class Point:
    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y


# Required — dataclass for internal values; Pydantic at validating boundaries
from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
    x: float
    y: float
```

## 4. `os.path` → `pathlib.Path`

```python
# Forbidden in new/changed code
path = os.path.join("data", "out.txt")
with open(path) as f:
    data = f.read()

# Required
path = Path("data") / "out.txt"
data = path.read_text()
```

## 5. Raw `dict` at boundary → Pydantic model

```python
# Forbidden at external/service boundaries
async def create_order(payload: dict[str, Any]) -> dict[str, Any]:
    customer_id = payload["customer_id"]
    ...


# Required
class CreateOrderRequest(BaseModel):
    customer_id: UUID
    items: list[OrderItem] = Field(min_length=1)


async def create_order(payload: CreateOrderRequest) -> OrderResponse: ...
```

## 6. Sync I/O in async → `asyncio.to_thread`

```python
# Forbidden
async def read_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


# Required
async def read_config(path: Path) -> dict[str, Any]:
    raw = await asyncio.to_thread(path.read_text)
    return json.loads(raw)
```

## 7. String `+=` in loop → join

```python
# Forbidden
result = ""
for part in parts:
    result += part

# Required
result = "".join(parts)
```

## 8. Module singleton → constructor / Runtime injection

```python
# Forbidden
from exact.tools.exa import exa_client


def search(q: str) -> list[Hit]:
    return exa_client.search(q)


# Required
class ExaClient(Protocol):
    def search(self, q: str) -> list[Hit]: ...


def search(q: str, client: ExaClient) -> list[Hit]:
    return client.search(q)
```

## 9. Magic literal → named constant / enum

```python
# Forbidden when the literal needs decoding or repeats
if role == "admin":
    ...
retry_after = 86400


# Required
class Role(StrEnum):
    ADMIN = "admin"


SECONDS_PER_DAY = 86_400
```

## 10. `isinstance` chain → `match/case`

```python
# Forbidden when a type dispatch chain is the control flow
if isinstance(event, CreatedEvent):
    return f"created {event.id}"
elif isinstance(event, DeletedEvent):
    return "deleted"

# Required
match event:
    case CreatedEvent(id=id):
        return f"created {id}"
    case DeletedEvent():
        return "deleted"
    case _:
        return "unknown"
```

## 11. Over-budget function — repair order

Required order — stop at the first success:

1. Delete dead branches
2. Guard clauses / early returns
3. Move a whole responsibility to a new unit
4. Extract a helper only if it has its own reason to exist

Forbidden:

- Boolean flag merging two behaviours
- State-bag to fake a lower parameter count
- Split that shares most of the caller's locals
