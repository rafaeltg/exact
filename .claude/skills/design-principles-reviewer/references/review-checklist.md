# Design Principles Review Checklist

Detailed per-principle checklist for thorough design reviews. Load this when doing comprehensive audits, reviewing large changes, or evaluating new architectural components.

## Table of Contents

- [Single Responsibility (SRP)](#single-responsibility-srp)
- [Open/Closed (OCP)](#openclosed-ocp)
- [Liskov Substitution (LSP)](#liskov-substitution-lsp)
- [Interface Segregation (ISP)](#interface-segregation-isp)
- [Dependency Inversion (DIP)](#dependency-inversion-dip)
- [Clean Code](#clean-code)
- [Design Heuristics](#design-heuristics)
- [Testability](#testability)

---

## Single Responsibility (SRP)

- [ ] Each class can be described in one sentence without "and"
- [ ] Each class has one reason to change (one actor, one concern)
- [ ] No class exceeds 300 lines (soft limit -- check for multi-responsibility if exceeded)
- [ ] No class has more than 8 constructor dependencies (symptom of too many responsibilities)
- [ ] Route handlers only translate HTTP to domain calls (no business logic inline)
- [ ] Repository classes only handle persistence (no business rules in queries)
- [ ] Models/entities don't perform I/O (no database calls, HTTP requests, or file operations)
- [ ] Utility files (`utils.py`, `helpers.py`) are focused on a single domain, not catch-all buckets
- [ ] Configuration, validation, persistence, and notification are in separate classes (not combined)
- [ ] Each file has a clear theme -- you can predict what's in it from the filename

## Open/Closed (OCP)

- [ ] No if/elif chains switching on type or string-based discriminators that grow with each new variant
- [ ] New features can be added by creating new classes rather than editing existing ones
- [ ] Extension points exist where variation is foreseeable (but not where it's speculative)
- [ ] Strategy/Plugin patterns used where behavior varies by context (payment processors, notification channels, export formats)
- [ ] No isinstance/type-checking chains for dispatch (use polymorphism or protocol-based dispatch)
- [ ] Enum-based dispatch uses a registry or mapping rather than if/elif
- [ ] Base classes are stable -- changes to base don't cascade to all subclasses

## Liskov Substitution (LSP)

- [ ] Subclasses honor the parent's behavioral contract (same preconditions, same postconditions)
- [ ] No subclass raises `NotImplementedError` on an inherited method
- [ ] Subclasses don't narrow parameter types (accept at least what the parent accepts)
- [ ] Subclasses don't widen return types or exceptions beyond the parent's contract
- [ ] Read-only variants don't extend read-write interfaces (separate the Protocols instead)
- [ ] Tests written for the parent pass when run against any subclass
- [ ] No "marker" subclasses that exist only to be isinstance-checked elsewhere

## Interface Segregation (ISP)

- [ ] Protocols/interfaces are focused on a single concern
- [ ] No Protocol has more than 5-7 methods (check if consumers use distinct subsets)
- [ ] Consumers depend only on the interface slice they actually use
- [ ] No implementor raises `NotImplementedError` for interface methods (sign of a fat interface)
- [ ] Related but distinct operations are in separate Protocols (Reader vs Writer, Querier vs Mutator)
- [ ] Cross-cutting concerns (health check, metrics, lifecycle) have their own interfaces
- [ ] No Protocol combines query and command operations that consumers use independently

## Dependency Inversion (DIP)

- [ ] High-level modules (services, domain) don't import low-level modules (database clients, HTTP clients, file I/O)
- [ ] Abstractions (Protocols) exist at architectural boundaries
- [ ] Dependencies are injected via constructor, not created internally or imported as module-level singletons
- [ ] The composition root (where concrete implementations are wired) is separate from business logic
- [ ] No concrete infrastructure type appears in a service class signature (use Protocols)
- [ ] External service integrations are behind Protocols (email, payment, notification, storage)
- [ ] Configuration is injected, not read from environment variables deep inside business logic

## Clean Code

### Functions

- [ ] Functions are 5-30 lines (soft limits -- check if cohesive)
- [ ] Each function does one thing at one level of abstraction
- [ ] No mixing of high-level orchestration with low-level detail in the same function
- [ ] Parameter count is 4 or fewer (consider parameter objects for more)
- [ ] Boolean parameters avoided (they usually mean the function does two things)
- [ ] Guard clauses used for preconditions (early returns instead of deep nesting)
- [ ] Maximum nesting depth is 2-3 levels

### Naming

- [ ] Class names are nouns that reflect responsibility (not `Manager`, `Handler`, `Processor` without context)
- [ ] Function names are verbs that describe what happens
- [ ] Boolean variables/functions prefixed with `is_`, `has_`, `can_`, `should_`
- [ ] No abbreviations or acronyms that aren't universally understood
- [ ] Names communicate intent without requiring implementation knowledge
- [ ] Consistent vocabulary across the codebase (don't mix `create`/`make`/`build` for the same concept)

### Structure

- [ ] Command-Query Separation: functions either change state or return data, not both
- [ ] No hidden side effects (function name reflects all effects)
- [ ] DRY applied to knowledge, not just code (same business rule in one place)
- [ ] No premature abstraction (Rule of Three: extract after 3 occurrences, not 1)
- [ ] Error handling separated from business logic
- [ ] Domain exceptions used instead of generic ValueError/RuntimeError

## Design Heuristics

### Composition and Inheritance

- [ ] Composition preferred over inheritance for behavior reuse
- [ ] Inheritance used only for true "is-a" relationships with behavioral substitutability
- [ ] No inheritance hierarchy deeper than 2-3 levels
- [ ] Mixins used sparingly and provide minimal, focused behavior
- [ ] Protocols preferred over ABC for interface definitions
- [ ] No "diamond problem" or multiple inheritance complexity

### Coupling and Cohesion

- [ ] Modules have high internal cohesion (elements work toward one purpose)
- [ ] Modules have low external coupling (few dependencies, on stable abstractions)
- [ ] No circular dependencies between modules
- [ ] Changes to one concept are localized to one or few modules
- [ ] Shotgun Surgery absent (one change doesn't require edits across many files)
- [ ] Data Clumps extracted into value objects (same field group in multiple places)
- [ ] Feature Envy absent (methods use their own class's data, not another's)

### Tell Don't Ask and Law of Demeter

- [ ] Objects are told what to do rather than queried for state and acted on externally
- [ ] No chain-calling through objects (`a.b.c.d` on behavior-rich domain objects)
- [ ] Decision logic encapsulated in the object that owns the data
- [ ] Methods talk only to immediate friends (own object, parameters, created objects, direct dependencies)
- [ ] DTOs and data containers exempt from Demeter (they're meant to be traversed)

### Code Smells

- [ ] No Primitive Obsession (domain concepts like email, money, date ranges are value objects, not raw strings/numbers)
- [ ] No Speculative Generality (abstractions exist for current needs, not hypothetical future ones)
- [ ] No Middle Man (classes that delegate everything without adding value)
- [ ] No Refused Bequest (subclasses that ignore most parent behavior)
- [ ] No Long Parameter Lists (>4 parameters suggests function does too much)
- [ ] No Message Chains on domain objects (may indicate missing encapsulation)

## Testability

- [ ] All services can be instantiated with fake/stub dependencies
- [ ] No module-level side effects that execute on import
- [ ] Protocols exist at every architectural boundary enabling test doubles
- [ ] Public API surface is sufficient for testing (no need to access private attributes)
- [ ] Pure functions used where possible (no side effects, deterministic)
- [ ] Time, randomness, and I/O are injectable (not called directly from business logic)
- [ ] Complex setup requirements in tests signal design problems (not test problems)
- [ ] Each class has a clear seam for isolation (constructor injection, not hidden dependencies)
