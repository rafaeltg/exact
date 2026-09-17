---
name: design-principles-reviewer
description: |
  TRIGGER: evaluating existing code for SOLID compliance, abstraction quality, coupling, code smells, "should I refactor this", "is this too coupled", design audits of PRs or modules.
  EXCLUDE: writing new code following design principles (use design-principles-expert); pure bug-finding or security review (use the appropriate language reviewer).
  SIGNAL: existing code + structural-quality question — not bugs, but maintainability and design soundness.
---

# Design Principles Reviewer

Evaluate existing code for structural decay: responsibility, coupling, abstraction quality, and extensibility — the slow-burn problems tests don't catch.

## Standards baseline

Before reviewing anything, load the `design-principles-expert` skill. It defines what good design looks like -- SOLID principles, Clean Code fundamentals, design heuristics (composition over inheritance, Tell Don't Ask, Law of Demeter, cohesion/coupling analysis). This skill defines HOW to evaluate design quality; `design-principles-expert` defines WHAT to evaluate against.

Also load the relevant `design-principles-expert` reference files based on what the review needs:

- `references/solid-principles.md` for in-depth SOLID analysis with extended examples
- `references/clean-code.md` for function-level and naming quality
- `references/design-heuristics.md` for structural patterns, coupling analysis, and refactoring guidance

If the project has its own `AGENTS.md`, architecture docs, or established design conventions, those take precedence. The project's patterns may deviate from textbook principles for good reasons.

## Before you review

Design review without understanding intent produces false positives. A "god class" might be an intentional Facade. An "unnecessary abstraction" might exist because of a regulatory requirement. Context prevents you from flagging design decisions as design problems.

**Understand the purpose.** What is this code supposed to do, and what were the design goals? Read the PR description, linked ticket, or architecture decision record. A service class with many dependencies might look like a SRP violation, but it could be the explicit composition root for a bounded context.

**Check existing conventions.** Look for `AGENTS.md`, architecture docs, existing module structure, base classes, established patterns. If the codebase uses a specific layered architecture (routes -> services -> repositories), evaluate within that architecture -- don't suggest a different one unless it's clearly failing.

**Identify the scope.** Is this a new module, a modification to existing code, or a refactor?

- **New module**: focus on abstraction boundaries, interface design, dependency direction, and whether the module fits the existing architecture
- **Modification**: focus on whether the change respects existing design -- or if it introduces coupling, responsibility leaks, or breaks existing contracts
- **Refactor**: verify that design quality actually improved -- refactors that just shuffle code around without reducing coupling or improving cohesion are wasted effort

**Gauge the stakes.** A utility function doesn't need full SOLID analysis. A core domain service that will be extended by 10 teams over 2 years does. Scale your review depth to the code's lifespan and audience.

## Review process -- reading order

Read code in this specific order. The passes are arranged by **design impact**: a structural problem in Pass 1 may invalidate everything below it, so catching it early saves everyone time. Naming nits in Pass 5 should never obscure fundamental design issues from earlier passes.

### Pass 1: Responsibility and boundaries

This is the most important pass. Responsibility violations are the root cause of most design decay -- a class that does too much today will do even more tomorrow.

- **Single Responsibility check**: Can you describe each class's responsibility in one sentence without "and"? If a `UserService` handles registration, email sending, password hashing, AND audit logging, it has at least four reasons to change.
- **Module boundaries**: Do modules represent coherent concepts? Are there files that are "catch-all" buckets (e.g., `utils.py` with 40 unrelated functions, `helpers.py` that grows indefinitely)?
- **Layer violations**: Does business logic live where it belongs? Route handlers containing domain rules, repositories making business decisions, or models performing I/O are all boundary violations.
- **God classes**: Classes with 10+ methods, 8+ dependencies, or 300+ lines are almost always doing too much. But verify: a Repository with many CRUD methods may be cohesive despite its size.
- **Feature Envy**: Methods that use more data from another class than their own belong in the other class. This is one of the strongest signals of misplaced responsibility.

### Pass 2: Dependency structure and coupling

How modules connect to each other determines how hard the code is to change. Tight coupling is the primary driver of "I changed one thing and 12 files broke."

- **Dependency direction**: Do dependencies flow from high-level (business logic) toward low-level (infrastructure), or the wrong way? A service that imports a specific database client directly is coupled to that infrastructure.
- **Dependency Inversion**: Are abstractions (Protocols, interfaces) used at architectural boundaries? Can you test a service by providing a fake, or do you need a real database?
- **Constructor injection vs hidden dependencies**: Are dependencies explicit (passed via constructor) or hidden (imported at module level, created internally)? Hidden dependencies make code untestable and hard to reason about.
- **Coupling hotspots**: Which modules have the most dependents? A change to a highly-coupled module ripples widely. Flag modules with 5+ direct dependents as coupling risks.
- **Circular dependencies**: Do modules import each other? This is always a design problem -- it means the responsibility boundaries are wrong.

### Pass 3: Abstraction quality

Abstractions are the core design tool. Bad abstractions are worse than no abstractions -- they create indirection without providing flexibility.

- **Leaky abstractions**: Does an abstraction expose implementation details? A `CacheService` that requires callers to set Redis-specific TTL parameters leaks its Redis implementation.
- **Over-abstraction (YAGNI)**: Are there Strategy patterns, Factories, or Abstract Base Classes for things that only have one implementation and no foreseeable variation? Each abstraction adds cognitive overhead -- it must earn its place.
- **Under-abstraction**: Are there concrete types hardcoded where a Protocol would allow flexibility? If three services all directly construct an `SmtpEmailClient`, that's three places to change when you switch email providers.
- **Abstraction consistency**: Do similar concepts use the same abstraction pattern? If one service uses Protocol-based injection and another uses module-level singletons, that's inconsistency.
- **Interface Segregation**: Are interfaces focused? A `DatabaseClient` Protocol with 15 methods forces every consumer to depend on all of them. Split when consumers use distinct subsets.

### Pass 4: Extensibility and Open/Closed compliance

Can the code accommodate new requirements without modification? This pass catches designs that will resist change.

- **If/elif chains on type**: A function with `if isinstance(x, A): ... elif isinstance(x, B): ...` violates OCP -- every new type requires editing. Look for polymorphism or strategy patterns.
- **Hardcoded decisions**: Values, types, or behaviors baked into the code that will clearly need to vary. Not everything needs to be configurable (YAGNI), but foreseeable variation points should be extensible.
- **Liskov Substitution**: Do subclasses honor the parent's contract? Subclasses that raise `NotImplementedError` on inherited methods, narrow parameter types, or change return semantics violate LSP.
- **Template Method vs Strategy**: Are there inheritance hierarchies where composition would be clearer? Deep inheritance trees (3+ levels) are almost always a sign that composition should replace inheritance.

### Pass 5: Code-level quality

Now read at the function and variable level for Clean Code quality:

- **Function size and focus**: Functions over 30 lines almost certainly do more than one thing. Can each function be described in one sentence?
- **Abstraction level mixing**: Does a single function contain high-level orchestration AND low-level detail? `process_order()` should call `validate()`, `persist()`, `notify()` -- not inline SQL queries alongside business rule checks.
- **Naming**: Do names communicate intent? Are booleans prefixed with `is_`, `has_`, `can_`? Do class names reflect responsibilities? Vague names like `Manager`, `Handler`, `Processor`, `Helper` often indicate unclear responsibilities.
- **Command-Query Separation**: Do functions either change state (command) or return data (query), not both? Mixed functions are harder to reason about and test.
- **Guard clauses**: Are there deeply nested conditionals (3+ levels) that could be flattened with early returns?
- **DRY vs premature abstraction**: Is there true knowledge duplication (same business rule in multiple places), or just incidental code similarity? Only the former warrants extraction.

### Pass 6: Testability assessment

Design quality and testability are deeply connected. Code that's hard to test almost always has a design problem.

- **Can classes be tested in isolation?** If testing a service requires standing up a database, HTTP server, and message broker, coupling is too high. Dependencies should be injectable fakes.
- **Are there hidden side effects?** Functions that look pure but modify global state, write to files, or call external services are untestable without mocking -- and the need to mock is the signal.
- **Is the public API surface clear?** If tests need to reach into private methods or attributes, the public interface isn't sufficient. Either the interface needs expanding or the tests are testing implementation instead of behavior.
- **Do Protocols exist for boundaries?** Every architectural boundary (service -> repository, service -> external API) should have a Protocol that enables test doubles.

## Severity classification

Every finding gets a severity level. Design review severity is calibrated for long-term impact rather than immediate failure -- the most severe design problems don't cause errors today but make the codebase progressively harder to maintain.

### Critical

Will cause significant design decay if merged, making the codebase materially harder to maintain or extend. These are "fix before merge" issues.

- Circular dependencies between modules
- Business logic embedded in infrastructure layers (route handlers, ORM models) with no separation
- God class with 10+ responsibilities that will only grow

### Major

Significantly harms design quality but won't immediately block development. Should be fixed before merge.

- SRP violation where a class has 3-4 responsibilities
- Missing dependency injection at a key boundary (service directly creates infrastructure)
- If/elif type-checking chain that should use polymorphism

### Minor

Affects design quality without immediate architectural impact. Should ideally be fixed, but won't block a merge.

- Vague naming (`Manager`, `Helper`, `Processor`) that doesn't communicate responsibility
- Mixed abstraction levels within a function
- Minor DRY violation (duplicated logic in 2 places)

### Suggestion

Recommendations for design improvement that are contextual or subjective. Optional for the author.

- Alternative module structure for better cohesion
- Opportunities to apply Tell Don't Ask
- Potential value object extraction for primitive obsession

## Review dimensions

Lenses, applied as relevant to the change:

- **Responsibility** (top priority): each class describable in one sentence without "and" — violations compound into god classes.
- **Coupling:** dependency direction, injection, and dependent count — couple on stable abstractions, not volatile implementations.
- **Abstraction:** right-level indirection that earns its place via testability, extensibility, or clarity — no leaks, no overhead.
- **Extensibility:** new requirements add code rather than modify it — type-switching chains and sealed hierarchies are signals.
- **Cohesion:** elements work toward one purpose so concept changes stay localized.
- **Testability:** if isolation needs complex setup, the design has a coupling/responsibility/abstraction problem.

## Definition of Done (review)

The review is trustworthy only when:

- [ ] You read the PR intent and gauged the stakes (a utility script ≠ a core domain service) — scale review depth to the code's lifespan and audience.
- [ ] You loaded `design-principles-expert` and used its **Watch out** notes as the lens.
- [ ] Every finding names the *consequence* ("this class will be a maintenance bottleneck in 3 months"), not just the principle ("violates SRP") — principle-worship without consequence is not actionable.
- [ ] Every refactoring suggestion states the specific pain it prevents — never "extract this" without the "because".
- [ ] You did not flag intentional patterns the project already chose, and did not over-apply (Protocols on single-impl utilities, SRP on cohesive CRUD repos).
- [ ] Structural findings (coupling, responsibility) lead; naming nits never bury them.

## Output format

Structure your review so authors can act on it efficiently. Design reviews should be clear about *why* a design choice is problematic, not just that it violates a named principle.

### Summary

Start with 2-3 sentences of overall design assessment. What's the structural health of this code? What's the most impactful issue? Be specific about what will happen if the design problems aren't addressed.

Example:
> The payment processing module has a solid service/repository separation and good use of Protocols for external dependencies. Two design issues need attention: `PaymentService` has accumulated responsibility for validation, processing, refund handling, AND notification dispatch -- it should be split before it grows further (major). The refund logic uses isinstance checks on payment types instead of polymorphism, which will require modification every time a new payment type is added (major). The repository layer is clean and well-abstracted.

### Findings

Each finding follows this structure:

```markdown
### [Severity] Brief title

**File:** `path/to/file.py:line_number`
**Principle:** SRP | OCP | LSP | ISP | DIP | Coupling | Cohesion | Clean Code

**Issue:** Clear description of the design problem and WHY it will cause pain.

**Suggestion:** Concrete refactoring approach with enough detail to act on.
```

Rules for findings:

- Include the **Principle** field so findings can be mapped to specific design concepts
- Explain the *consequences* of the design problem, not just name the principle violated. "This class has 8 dependencies" is an observation; "This class has 8 dependencies, meaning any change to any of those 8 services requires retesting this class, and testing it requires setting up all 8 -- this coupling will make feature work progressively slower" is a finding.
- Provide a concrete refactoring suggestion -- not just "apply SRP" but "extract notification logic into a `PaymentNotifier` class and inject it"
- Group related findings (e.g., three instances of Feature Envy in the same class become one finding about misplaced responsibility)
- Order by severity: critical first, suggestions last

### Positive callouts

Call out 2-3 specific design strengths — it reinforces good patterns. "the `OrderRepository` Protocol is cleanly focused on persistence with no domain logic leakage" beats "good use of Protocols."

## Reviewer discipline

The Definition of Done covers stakes, consequence-over-principle, and justified refactors. Beyond that:

- Lead with responsibility (god classes, layer violations), then coupling (circular deps, missing boundary abstractions) — these are root causes; naming nits never come first.
- Be direct about design risk: "this will be a maintenance bottleneck in 3 months" beats "consider SRP." Frame as structural risk, not personal criticism.
- Distinguish "this must change" (critical/major) from "this could be better" (minor/suggestion) — equating a naming nit with a circular dependency erodes trust.
- Flag genuine over-engineering uncertainty for discussion ("this Factory may be premature with one impl — worth deciding if the flexibility justifies the indirection") rather than asserting either way.
- Don't worship principles: the maintainability risk is the point, not the acronym. Citing "violates SRP" without the consequence is not actionable.
- Respect established project patterns over textbook purity — consistency with an imperfect convention usually beats a wholesale redesign in a PR.
- Don't confuse size with complexity: a 200-line cohesive class beats five coupled 40-line ones. Split for cohesion, not line count.
- Don't miss the forest for the trees — a circular dependency outranks function naming.

## Reference checklist

For thorough design reviews, large changes, or unfamiliar codebases, load `references/review-checklist.md`. It contains a detailed per-principle checklist of specific things to verify.

Load it when:

- Doing a comprehensive design audit of a large module
- Reviewing a new service or domain model
- The user explicitly asks for a forensic or exhaustive design review
- The change introduces new architectural patterns or module boundaries
