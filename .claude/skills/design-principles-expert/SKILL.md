---
name: design-principles-expert
description: |
  TRIGGER: explicit design-quality concerns while writing code — "this class does too much", "should I use composition or inheritance", "make this maintainable", SOLID, Clean Code, coupling, cohesion, Tell Don't Ask, Law of Demeter; refactoring for structural clarity.
  EXCLUDE: reviewing existing code for design quality (use design-principles-reviewer); general Python authoring without a design question (use python-quality).
  SIGNAL: the user has a specific structural concern while writing or refactoring, not just "implement this feature." Load alongside language-specific expert skills when both apply.
---

# Design Principles Expert

You can recite SOLID; the problem is *misapplication* — a Strategy pattern for one implementation, a god class that grew "because it was already there", an abstraction that leaks what it should hide. Each principle below is reduced to its **Watch out** — the landmine where competent engineers misapply the principle and create the decay it was meant to prevent. Over-application is itself a landmine: every abstraction costs indirection, and an unjustified one buys nothing.

This skill answers "how should I structure this so it stays maintainable as it evolves?"; language skills (`python-quality`) answer "how do I write this idiomatically?". Load both for implementation work — the language skill owns syntax, this one owns the design reasoning. Check the project for existing conventions first (`AGENTS.md`, architecture docs, established patterns): these guidelines fill gaps — they don't override project decisions.

## When to apply (and when not to)

**Apply rigorously when:** building service layers, domain models, or core business logic that will evolve; designing interfaces (Protocols, abstract classes) other modules depend on; the codebase has multiple contributors and a multi-month lifespan; refactoring code that has become painful to modify.

**Apply lightly when:** writing scripts, one-off tools, or throwaway prototypes; the code is simple enough that abstraction would increase complexity; you're in a spike where the design isn't settled.

**The litmus test:** if adding an abstraction makes the code harder to understand without a clear future benefit, you've over-applied. Principles serve the code, not the other way around.

## SOLID — the misapplication map

Definitions assumed; each entry is the one-line anchor plus the landmine.

- **SRP** — one reason to change, one actor. **Watch out:** SRP does not mean "every class has one method." A `UserRepository` with `create`, `get`, `update`, `delete` has one responsibility — persistence. Those methods are cohesive; don't split them into four classes.
- **OCP** — add behavior by adding code, not editing tested code (e.g., a `PaymentProcessor` Protocol where each new method is a new class, not a new `elif`). **Watch out:** OCP doesn't mean you never modify existing code. It means the design minimizes the need for *foreseeable* extensions. A Strategy pattern for something that genuinely won't vary is YAGNI debt, not compliance.
- **LSP** — subtypes substitutable for their base without breaking callers; the contract is behavioral, not just type signatures. **Watch out:** a `ReadOnlyRepository` extending `Repository` and raising `NotImplementedError` on `save()` violates the parent's promise. Fix by splitting the interface — a `Reader` Protocol and a `Writer` Protocol — not by inheriting and stubbing.
- **ISP** — clients shouldn't depend on interface methods they don't use. **Watch out:** ISP doesn't mean every interface has one method. Split a fat Protocol (a 15-method `DatabaseClient`) only when consumers genuinely use distinct subsets; a CRUD repository interface is cohesive as-is.
- **DIP** — high-level modules depend on abstractions; inject via constructor, wire concretes at the composition root. **Watch out:** not every function call needs an abstraction. Apply DIP at architectural boundaries (service → infrastructure, module → module) — never create a Protocol for a pure utility function.

## Clean Code — the rules that carry weight

- **Small functions at one abstraction level.** A function reads like a table of contents (`validate → persist → notify`). Don't mix `await service.create_user(data)` with `email.split("@")[1].lower()` in the same body — extract the low-level operation.
- **Command-Query Separation.** A function changes state or answers a question, not both. Bend knowingly for factories, atomic read-and-write, and idioms like `dict.pop()` — the point is awareness, not rigidity.
- **No hidden side effects.** A `validate_email()` that also normalizes and writes to a cache lies to every caller. Name the effect (`validate_and_normalize_email`) or, better, split query from transform.
- **Guard clauses.** Flatten nested conditionals with early returns; keep the happy path visible at the left margin.
- **DRY is about knowledge, not text.** Two identical blocks representing *different concepts* (validation for two entities that happen to match today) must NOT be merged — they'll diverge, and premature abstraction is worse than duplication. Rule of Three: tolerate once, note twice, extract on the third occurrence.
- **YAGNI.** No abstractions for hypothetical futures — don't build the `PaymentProcessor` strategy while the app supports only credit cards. When the second case arrives, refactor with two real examples in hand.
- **Error handling stays separate from business logic.** Domain operations raise domain exceptions; each layer handles or translates the layer below; a global handler catches the rest; never use exceptions for flow control.

## Design heuristics

- **Composition over inheritance.** Default to composition; inherit only for true is-a with behavioral substitutability, framework requirements (Pydantic `BaseModel`), or interface-only bases. Prefer Protocols over ABC inheritance. A mixin providing more than a few methods is a service that should be injected.
- **Tell Don't Ask.** `order.begin_processing()` beats reading three fields and mutating the order from outside — state-inspection-then-decision pulls logic out of the object that owns it.
- **Law of Demeter.** `order.customer.address.city` couples the caller to the internal structure of three objects; expose behavior instead (`order.shipping_city()`). **Pragmatic note:** DTOs and Pydantic models are meant to be traversed — the rule targets behavior-rich domain objects.
- **Cohesion vs coupling tension.** If you can't describe a class's responsibility in one sentence without "and", cohesion is low. But splitting a cohesive class to "reduce class size" can *increase* coupling — split for cohesion, never for line count.
- **Smell recognition.** Smells are symptoms to investigate, not automatic refactor triggers. Act soon on: Feature Envy, Shotgun Surgery, Divergent Change, long parameter lists (>4), Primitive Obsession. Lower priority: Data Clumps, Message Chains, Speculative Generality, Middle Man, Refused Bequest.

## Workflow while writing

1. State the class/module's responsibility in one sentence before writing; identify boundaries and the *likely* extension points — design flexibility there, not everywhere.
2. Start concrete, abstract later: write the simplest thing that works; extract the Protocol when the second use case arrives.
3. If you can't find a good name, you don't understand the concept yet — stop and think.
4. More than 3-4 parameters usually means the function does too much or wants a parameter object.
5. Check dependency direction: high-level modules must not import low-level details across a boundary — introduce the abstraction at the boundary.

## Definition of Done (self-check)

Run this before declaring a design finished — gates, not vibes:

- [ ] **Name test:** each function is understandable from its name and signature alone.
- [ ] **SRP test:** each class's responsibility states in one sentence with no "and".
- [ ] **Coupling test:** changing an internal detail would not force callers to change.
- [ ] **Testability test:** the code is testable with simple fakes. *Painful setup is the tell that coupling is too high* — testability is a proxy for design quality, so hard-to-test code almost always has a real structural problem, not just a testing inconvenience.

## Reference files (optional deep-dives)

The sections above are the working content. Load a reference only when the user asks for an in-depth treatment of a specific principle, or when designing a complex module boundary or interface hierarchy warrants the extended examples:

- `references/solid-principles.md` — extended before/after Python examples, edge cases, common debates
- `references/clean-code.md` — function size analysis, abstraction levels, naming, error handling, formatting
- `references/design-heuristics.md` — composition patterns, coupling/cohesion analysis, refactoring catalog, anti-patterns
