# Skills: enforce design quality — plan

Spec: this conversation (2026-09-17). Format: FINDINGS → PATCH_PLAN → phases/tasks
(`forensic-assessment/references/output-formats.md`, `phase-slicing`, `task-structuring`). STE.

## Context

The `.claude/skills/` set informs CLEAN/SOLID practice. It does not enforce it. Only four
function-shape numbers (`.cursor/hooks/complexity-guard.py`) and ruff are gates. The two design
skills load least often of the set, contradict the enforced numbers, and duplicate
`python-quality` Review mode. Planning skills do not carry unit composition, so the
implementer's Gate 0 starts from nothing. Two rules that a program can check — no import
cycles, plan references resolve — are checked by no program.

Outcome: one Python skill that carries design guidance inline and loads on every Python
touch; planning skills that pre-satisfy Gate 0; two new mechanical gates in `make check`, the
pre-commit hook, and the agent hooks. Enforcement of *judgment* rules stays with the fresh
reviewer, by design.

User decisions (2026-09-17): delete both design skill directories; include both enforcement
items; Findings → Patches → Tasks format. **`python-quality` keeps an authoritative tone
throughout — no informative or hedged section. Every design rule names the landmine it
prevents.** This overrides the earlier "apply with judgment" gate idea: over-application of a
principle is itself a named landmine, not a disclaimer.

---

## Forensic Assessment: `.claude/skills/` design-quality coverage

**Artifact:** `.claude/skills/{design-principles-expert,design-principles-reviewer,python-quality,task-structuring,phase-slicing}`, `.claude/commands/*.md`, `.claude/settings.json`, `Makefile`
**Cross-references read:** `.cursor/hooks/complexity-guard.py`, `.cursor/hooks.json`, `pyproject.toml`, `scripts/hooks/*`, `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`, `README.md`, `src/exact/**`
**Assessment depth:** multi-source

### Summary

Design guidance exists but is routed weakly, contradicts the one enforced budget, and has no
mechanical backing. 11 findings: 0 critical, 7 major, 3 minor, 1 nit. The baseline tree has 0
import cycles (verified by AST scan with submodule resolution), so a cycle gate can land
without a `src/` change.

### Findings

#### F1: Design guidance loads only on explicit design phrasing [MAJOR]
- **Location:** `.claude/commands/forensic-review.md:246`; `forensic-assessment/references/output-formats.md:110`; `review-pr.md:289`; `bug-bash.md:86`; `devils-advocate.md:97`
- **Evidence:** `design-principles-expert` is named at exactly two sites, both as "name the skill to load during execution". `design-principles-reviewer` is routed only when a path signal ("Graph topology, `Runtime` injection, module boundaries, restructuring") or a keyword matches. `python-quality` is routed on every non-test `.py` (`review-pr.md:287`) and triggers on all Python authoring.
- **Issue:** A diff that decays coupling inside an already-touched node file misses the routing. The expert's Definition of Done never runs during ordinary implementation.
- **Recommendation:** Move the design core inline into `python-quality/SKILL.md`. Delete the two skills. Repoint routing.

#### F2: Posture conflict between the skills to be merged [MAJOR]
- **Location:** `python-quality/SKILL.md:11`; `design-principles-expert/SKILL.md:10-18`
- **Evidence:** "These rules are authoritative." vs "Over-application is itself a landmine … these guidelines fill gaps — they don't override project decisions." and "Apply rigorously when / Apply lightly when / The litmus test".
- **Issue:** The expert's hedged register ("apply lightly", "litmus test", "guidelines fill gaps") cannot enter `python-quality`, whose contract is authoritative. Copied as is, it would be the one informative section in a rule file, and the domain agent (`review-pr.js:414-423`) would treat design as optional. Yet the expert's substance is right: a Strategy for one implementation, a Protocol with no second impl, and a CRUD repository split "for SRP" are real defects.
- **Recommendation:** Rewrite the design content as authoritative landmines. Every rule states the misapplication it forbids and the failure it causes, in the same table shape as § Known breach shapes. Over-application and omission are both named landmines. No hedge words.

#### F3: Design numbers contradict the enforced guard [MAJOR]
- **Location:** guard: `complexity-guard.py:82-85` (CC ≤10, lines ≤40, nesting ≤3, params ≤6). Conflicts: `design-principles-reviewer/SKILL.md` Pass 5 "Functions over 30 lines"; `design-principles-expert/SKILL.md` Workflow step 4 "More than 3-4 parameters"; `expert/references/clean-code.md:48` "30+ line function"; `clean-code.md:83` "3+ arguments … Needs justification"; `reviewer/references/review-checklist.md:75` "Functions are 5-30 lines"; `:78` "Parameter count is 4 or fewer"; `:81` "nesting depth is 2-3"; `:136` ">4 parameters".
- **Issue:** A 35-line, 5-parameter function passes the gate and fails the skill. Two sources of truth.
- **Recommendation:** Reconcile. Cite the guard for every measured metric. Delete or relabel the rest.

#### F4: Unmeasured heuristics stated as thresholds [MINOR]
- **Location:** `reviewer/SKILL.md` Pass 1 "10+ methods, 8+ dependencies, or 300+ lines"; Pass 2 "5+ direct dependents"; Pass 4 "3+ levels"; `design-heuristics.md:194-197` (15 imports / 8 dependencies / 30 lines of mock / 5 files); `:496` "500+ lines, 20+ methods"; `reviewer/references/review-checklist.md:22,23,54,107`.
- **Issue:** No tool in the repo measures class lines, dependents, Protocol method counts, or inheritance depth. A number without a measurement reads as a rule and is applied as taste.
- **Recommendation:** Delete every unmeasured number. Keep the rule as a landmine statement without a count ("a class whose responsibility needs 'and' is split by responsibility, never by line count"). The only numbers in `python-quality` are the guard's four.

#### F5: Reviewer duplicates `python-quality` Review mode and depends on a second skill [MAJOR]
- **Location:** `reviewer/SKILL.md` § Standards baseline ("load the `design-principles-expert` skill"); Passes 1–6 vs `python-quality/SKILL.md` Review Passes 1–5 (Pass 1 already lists "wrong abstractions; dependencies not flowing inward; singletons that block injection; circular deps; layer leaks").
- **Issue:** Two review methods for one language. A reviewer that must load two skills to start is a reviewer that skips one.
- **Recommendation:** Fold reviewer Passes 1–4 into `python-quality` Passes 1–2, Pass 6 into Pass 4, the preamble into "Before review". One method.

#### F6: Planning skills do not carry unit composition [MAJOR]
- **Location:** `task-structuring/SKILL.md` § Writing the Do field; § Author checklist. `phase-slicing/SKILL.md` § Cross-phase contracts. `python-quality/SKILL.md` § Gate 0 "Compose units before any body" (unit list; one-job test; budget self-check; extract-first).
- **Evidence:** Do-field rules require file paths, signatures, key logic, and "no task leaves a function over the complexity budget". They do not require the unit list or the one-verb test. Cross-phase contracts require signature, invariants, verification — not a one-sentence responsibility or a fakes-testability statement.
- **Issue:** Gate 0 permits the unit list "in the reply or in a stub file". The plan is the natural home, and the plan does not carry it. The implementer composes units ad hoc at write time.
- **Recommendation:** Require Gate 0 output in every Do field. Require the design DoD in every cross-phase contract that introduces a module or Protocol. Cite `python-quality` anchors; do not restate.

#### F7: Circular imports are "always a design problem" and are measured by nothing [MAJOR]
- **Location:** `reviewer/SKILL.md` Pass 2 and § Critical; `python-quality/SKILL.md` § Imports ("Circular-import pressure is fixed by redesigning boundaries"); `Makefile:175-181` (`check` = lint, format, complexity-check, workflows-check, test); `pyproject.toml:47-58` (ruff select has no cycle rule); `pyproject.toml:22-25` (dev extra = pytest, ruff).
- **Evidence:** Baseline scan of `src/exact` (22 modules, 74 internal edges): 0 cycles when `from exact import prompts` resolves to `exact.prompts`. A scanner that also counts the package-root edge reports 6 false cycles through `exact/__init__.py` → `exact.graph` → nodes → `exact`.
- **Issue:** The most objective design rule in the skill set has no gate. Tool choice matters: the tool must resolve `from pkg import submodule` to the submodule.
- **Recommendation:** Add an import-cycle gate to `make check` and the pre-commit hook. Verify it reports 0 on HEAD before wiring.

#### F8: Plan-artifact checks that a program can run are run by an LLM only [MAJOR]
- **Location:** `plan.md:190-213` Phase 6 table ("Each `Files: modify:` path exists — Glob"; "Each `make` target in a Verify exists — Grep the Makefile"); `task-structuring/SKILL.md` § Author checklist ("Every `TEST=` path starts with `tests/` and names a file that exists"; "Every `K=` filter names a test function that exists"); `.claude/settings.json` (no hook matches `.claude/artifacts/plan/**`).
- **Evidence:** Sample plan grammar (`.claude/artifacts/plan/exa-publication/plan.md:126-182`): `**Files:** create: \`p\` | modify: \`p\`, \`p\`` and `**Verify:** \`make test TEST=tests/x.py K=name\``. Stable, parseable.
- **Issue:** The `fs-readonly-worker` holds no Bash. It verifies by Glob and Grep. A machine does this faster and never skips a row.
- **Recommendation:** Add `plan-guard.py` + `make plan-check FILE=` + a PostToolUse hook on plan writes + a `/plan` Phase 5 step that runs it before Phase 6. Keep the LLM reviewer for symbol and semantic rows.

#### F9: Six routing sites will dangle after deletion [MINOR]
- **Location:** `review-pr.md:289`; `bug-bash.md:86`; `devils-advocate.md:97`; `forensic-review.md:246`; `forensic-assessment/SKILL.md:5`; `forensic-assessment/references/output-formats.md:110`.
- **Issue:** A skill name that resolves to nothing fails silently in a workflow prompt.
- **Recommendation:** Repoint every site in the same commit as the deletion.

#### F10: The reviewer accepts a prose proposal; `python-quality` Review mode assumes a diff [MINOR]
- **Location:** `devils-advocate.md:97` routes documents matching `architecture|coupling|abstraction|design|topology|graph`; `python-quality/SKILL.md` § Before review requires "Read `AGENTS.md` and `pyproject.toml`", "Classified scope: bugfix | feature | refactor".
- **Issue:** After repointing, a document review would start with steps that do not apply.
- **Recommendation:** One line in the merged design section: how Review mode applies to a document.

#### F11: A Claude-only hook breaks the documented mirror [NIT]
- **Location:** `CLAUDE.md` § Claude Code harness ("`.claude/settings.json` … mirrors `.cursor/hooks.json`").
- **Issue:** A new PostToolUse hook without a Cursor `afterFileEdit` twin makes the sentence false.
- **Recommendation:** Add the twin. Update the CLAUDE.md table.

### Scope of this assessment

Not examined: `test-design`, `forensic-assessment` methodology, `fix-findings`, `harden-doc`
content. `.claude/artifacts/**` (gitignored working files). `docs/spec.md` and
`docs/architecture.md` (no topology, bounds, tools, or citation rule changes here).

### Calibration

- **Weakest link:** F7's baseline was computed by an ad-hoc scanner, not by the tool that will
  ship. Task 4.1 re-verifies with the chosen tool before any wiring.
- **Single most-likely 3-month break cause:** the merged `python-quality/SKILL.md` grows past
  what a model reads end-to-end, and the design section at the bottom is skimmed. Task 1.1
  caps the addition at 70 lines and places the design gate before the Forbidden list.
- **Agents/dimensions that returned no findings or failed:** none.

### Statistics

| Severity | Count |
|----------|-------|
| Critical | 0 |
| Major    | 7 |
| Minor    | 3 |
| Nit      | 1 |
| **Total**| **11** |

---

## Patch Plan

**Source:** Forensic Assessment above
**Findings addressed:** F1–F11
**Findings excluded:** none

### Constraints Applied

- Delete both design skill directories (user decision).
- Include both enforcement items (user decision).
- Guard budgets are the single source of numbers. Never restate them in a skill.
- `.claude/artifacts/**` stays gitignored. No plan artifact enters the repository.
- No change to `docs/spec.md` or `docs/architecture.md`: no topology, bound, tool, or
  citation rule moves.

### Patches

#### P1: Fold the design core inline into `python-quality/SKILL.md` <- F1, F2, F5, F10
- **Target:** `.claude/skills/python-quality/SKILL.md` (299 lines → ≤ 375)
- **Action:** Restructure — add one section and grow six existing ones. Budget: ≤ 70 added lines.
  1. Preamble (L11): unchanged. The skill stays authoritative end to end.
  2. **New** `## Design — landmines`, placed after `## Mode selection` and before `# Implement mode` (shared by both modes). Register: the same as § Known breach shapes — rule, landmine, required composition. No "consider", "usually", "often", "might", "prefer", "apply lightly", "litmus". Content, in order:
     - Scope rule (2 lines): "Applies to every unit under `src/exact/`. Under `scripts/` and in a spike the abstraction rows below add nothing new — the misapplication rows still apply. A design finding names the consequence and the row; the acronym alone is not a finding."
     - `### SOLID — misapplication landmines`: a table `Principle | Landmine (forbidden shape) | Required composition`, one row per principle from expert `SKILL.md:25-31` (lead line + 5 bullets). Both directions per row where the source has them. Examples: SRP — forbidden: splitting a cohesive persistence class into one class per method; required: split by reason to change. OCP — forbidden: a Strategy/Protocol for one implementation (already § Type hints: speculative Protocols); required: `elif` until the second real case, then extract with two examples in hand. LSP — forbidden: a subtype that raises `NotImplementedError` on an inherited method; required: split the Protocol. ISP — forbidden: one-method interfaces cut from a cohesive Protocol; required: split only when consumers use distinct subsets. DIP — forbidden: a Protocol on a pure utility function; required: abstractions at `Runtime`/tool boundaries only.
     - `### Clean Code — required`: expert `:35-41` rewritten as `Required:` / `Forbidden:` pairs (one abstraction level per function; CQS with the three named exceptions; no hidden side effect — name it or split; guard clauses; DRY by knowledge — merging two concepts that match today is forbidden, Rule of Three; YAGNI; domain errors, never exceptions for flow control).
     - `### Structure — required`: expert `:45-49` as rules: composition by default, inheritance only for behavioral is-a, framework base, or interface-only base; Tell Don't Ask; Law of Demeter on behavior-rich objects (Pydantic models and DTOs are traversed — stating that is a rule, not a hedge); a class whose responsibility needs "and" is split by responsibility, never by line count; the smell list as "Act on:" (Feature Envy, Shotgun Surgery, Divergent Change, Primitive Obsession, long parameter lists — cap 6, see [Complexity budgets](#complexity-budgets--landmines)).
     - `### Before the first body — required`: expert `:53-57` as imperatives. Step 4 becomes "A parameter list you cannot name in one breath is a parameter object. The cap is 6."
     - Deep-dive pointer (1 line): `references/solid-principles.md`, `clean-code.md`, `design-heuristics.md` — load for a module boundary or interface hierarchy.
     - Document mode (2 lines): "When the input is a document (design proposal, architecture note, spec section) and not a diff: run Pass 1 and Pass 2 against the structure the document describes, plus the Pass 4 testability question. Passes 3 and 5 need code and are skipped. `file:line` becomes the document heading or quoted line."
  3. Gate 0 → `### Compose units before any body`, step 1: append "— name the responsibility in one sentence without 'and', see [Design — landmines](#design--landmines)".
  4. `## Definition of Done — mandatory gates`: fold the expert's 4 self-checks (expert `:63-66`) as 4 required bullets in the existing list, imperative form ("Every function is understandable from its name and signature alone"; "Every class's responsibility states in one sentence without 'and'"; "No internal change forces a caller change"; "Every unit is testable with `tests/fakes.py` fakes — painful setup is a coupling defect, not a test problem"). No tag, no softener.
  5. Review mode: `## Before review` +2 mandatory items ("State the unit's lifespan and audience — a `scripts/` file gets Passes 3–5 only"; "Read the intent before naming a pattern a defect — an intentional Facade reviewed as a god class is a false finding, and a false finding is a review failure"). `### Pass 1` +3 flag-bullets (a class whose responsibility needs "and"; catch-all `utils.py`/`helpers.py`; Feature Envy; hidden module-level deps in place of `Runtime` injection). `### Pass 2` +3 (leaky abstraction; a Protocol/Strategy/Factory with one implementation, and a concrete client hardcoded where a `Runtime` seam exists; `isinstance` dispatch chains and LSP `NotImplementedError` stubs). `### Pass 4` +2 (painful isolation setup is a coupling finding; a boundary without a fake in `tests/fakes.py`). `### Pass 5` +1 (mixed abstraction levels; `Manager`/`Handler`/`Processor`/`Helper` names; CQS breaks). Severity table: examples appended inside existing cells (Critical: circular deps, business logic in infrastructure; Major: a class with several reasons to change, missing DI at a boundary, type-switch chain; Minor: vague naming, mixed abstraction levels; Suggestion: Tell-Don't-Ask, value-object extraction). `## Reviewer discipline` +2 bullets ("Name the consequence; the acronym alone is not a finding"; "Split for cohesion, never for line count"). `## References` +3 lines.
  6. Do **not** rename `### Complexity budgets — landmines`, `### Known breach shapes — exact`, `## Forbidden — landmines` — they are link targets at `:49-50`, `:96`, `:191`, `:235`. Do not add a `**Principle:**` field to the finding template.
  7. Tone gate on the whole file after the edit: `grep -nEi "\b(consider|usually|often|might|could be|ideally|prefer|apply lightly|litmus|generally|typically|tends? to)\b" .claude/skills/python-quality/SKILL.md` → no hits outside a fenced code block. Rewrite any hit as Required / Forbidden.
- **Rationale:** Addresses F1 (loads with every Python touch), F2 (authoritative landmines, no hedge), F5 (one review method), F10 (document mode stated).

#### P2: Reconcile every number to the guard <- F3, F4
- **Target:** the moved reference files and the merged checklist (P3), plus the inline bullets in P1
- **Action:** Reconcile — the guard (`params ≤6, CC ≤10, length ≤40 code lines, nesting ≤3`) is the only source. Per number:

  | Source | Number | Action |
  |---|---|---|
  | `clean-code.md:48` | 30+ line function | cite guard: "the enforced cap is 40 code lines; well before that, ask 'can I name the blocks?'" |
  | `clean-code.md:83` | 3+ arguments needs justification | cite guard: "3 is a design prompt, not a breach; the cap is 6" |
  | reviewer checklist `:75` / `:78` / `:81` | 5-30 lines / ≤4 params / nesting 2-3 | cite guard: ≤40 / ≤6 / ≤3 "(guard)" |
  | reviewer checklist `:136` | >4 parameters smell | delete the number: "a parameter list that needs a comment to read wants a parameter object" |
  | reviewer checklist `:23` | 8 constructor dependencies | cite guard — `__init__` is a function, `self` excluded, cap 6; a state bag to dodge it is a forbidden repair (`SKILL.md` § Over-budget functions) |
  | reviewer checklist `:22` / `:54` / `:107` | 300 class lines / Protocol 5-7 methods / inheritance 2-3 | delete the number; keep the rule ("a class is split by responsibility, never by line count"; "a Protocol is split when consumers use distinct subsets"; "inheritance only for behavioral is-a, framework base, or interface-only base") |
  | `design-heuristics.md:192-197` | 15 imports / 8 deps / 30 mock lines / 5 files | rewrite the four lines as counted-free rules ("a module that imports most of the package is a coupling hotspot"; "a test that needs a wall of fake setup proves coupling") |
  | `design-heuristics.md:496` | 500+ lines, 20+ methods | delete the numbers; keep "imported by half the codebase" as the symptom |
  | reviewer `SKILL.md:52` / `:62` | 10+ methods, 8+ deps, 300+ lines / 5+ dependents | delete the numbers where folded into Pass 1 |
  | reviewer `SKILL.md:82` / `:92` / `:114` / `:210` | 3+ inheritance levels / 3+ nesting / 10+ responsibilities / 200 vs 40 lines | delete the numbers (covered elsewhere, or keep the sentence without them) |
  | reviewer `SKILL.md:88` | functions over 30 lines | cite guard (40) where folded into Pass 5 |
- **Rationale:** Addresses F3 (no second source of truth) and F4 (the only numbers left are the guard's four).

#### P3: Move references; merge the two review checklists into one <- F1, F5
- **Target:** `python-quality/references/` gains `solid-principles.md`, `clean-code.md`, `design-heuristics.md` (`git mv`); `python-quality/references/review-checklist.md` absorbs `design-principles-reviewer/references/review-checklist.md`
- **Action:** Restructure —
  - `git mv` the three expert reference files. Link-safe: they carry intra-file `#anchor` links only (verified by grep).
  - Merged checklist section order, matching Review Passes 1→5: 1 Responsibility and boundaries (NEW, reviewer `:18-29`); 2 Dependencies and coupling (NEW, `:61-69` + `:114-120`; drop the module-singleton item, cross-link `refactoring-patterns.md` §8); 3 Abstractions and contracts (NEW, `:51-59` + `:41-49`); 4 Extensibility (NEW, `:31-39`); 5 Correctness; 6 Security; 7 Performance; 8 Type safety; 9 Error handling (absorbs `:98`; `:99` duplicates existing `:46` — drop); 10 Pydantic and boundaries; 11 Testing and testability (absorbs `:139-148` minus duplicates `:141`, `:144`); 12 Clean Code and smells (NEW, `:71-97` + `:101-110` + `:122-137`; `:114-120` went to section 2); 13 exact-specific, last. Note: reviewer `:65` is one item covering constructor injection and module singletons — dropping it drops both halves; keep the injection half.
  - **Item register**, required: the checklist header (`review-checklist.md:3`) makes every unchecked applicable item a finding. Sections 1–4 and 12 keep that contract. Each new item is a checkable statement that names its landmine, and the over-application shape is an item of its own (e.g. "- [ ] No Protocol, Strategy, or Factory with a single implementation"; "- [ ] No class split by line count"; "- [ ] No one-method interface cut from a cohesive Protocol"). No item carries a number other than the guard's four. No "consider"/"should ideally" wording — the tone grep from P1 step 7 runs on this file too.
  - Overlap decisions (`refactoring-patterns.md` stays the FIX catalog; design refs keep the WHY):

    | Topic | Decision |
    |---|---|
    | Decompose Conditional (`design-heuristics.md:461`) vs early return (`refactoring-patterns.md` §2) | keep both; one-line cross-link at `:461` |
    | Parameter Object (`design-heuristics.md:361`; `clean-code.md:85-105` fenced sample) | delete the whole fenced block `clean-code.md:85-105` → one line + cross-link to `:361`; cross-link `:361` from Known breach shapes row 1 |
    | Bool flag (`clean-code.md:107`) | keep the WHY; add "as a complexity repair it is forbidden — see `SKILL.md` § Over-budget functions" |
    | Protocol at boundary (`design-heuristics.md:411`; `solid-principles.md:367`) | keep; add one repo line at `:411`: speculative Protocols with no impl are forbidden here |
    | Type/category switch (`design-heuristics.md:328` "Replace Conditional with Polymorphism" — its example dispatches on a string field) vs `isinstance` → `match/case` (`refactoring-patterns.md` §10) | keep both; tie-break at `:328`: closed variant set owned by this module → `match/case` (§10); variants added by other modules → polymorphism or registry |
    | Boolean naming | delete from design-ref prose (`SKILL.md` already requires it); one checkbox stays in merged § 12 |
    | Error handling (`clean-code.md:262-381`) | keep; precedence note at `:262`: `SKILL.md` § Error handling wins |
    | Function size (`clean-code.md:17-48`) | keep the analysis; cite the guard (P2) |
    | Module singleton → injection | delete from the checklist item; cross-link `refactoring-patterns.md` §8 |
    | Comments (`clean-code.md:194-261`) | keep; precedence note at `:194`: its "good comment" samples (`# Legal requirement: PCI DSS 3.4`, `# TODO(PROJ-1234)`) are the spec-anchor shape `SKILL.md` § Docstrings forbids — paraphrase the why here |
- **Rationale:** Addresses F1 (one home), F5 (one checklist, one method).
- **Depends on:** P1 (anchor `#design--landmines` exists)

#### P4: New `python-quality` frontmatter description <- F1
- **Target:** `.claude/skills/python-quality/SKILL.md:1-8`
- **Action:** Rewrite —
  ```yaml
  description: |
    TRIGGER: writing, refactoring, or reviewing Python — implement a module/node/tool, "review this diff", PR audit, bug-hunt, "what's wrong with this code"; design-quality questions on Python or on a proposed structure — SOLID, Clean Code, coupling, cohesion, Tell Don't Ask, Law of Demeter, composition vs inheritance, "this class does too much", "should I refactor this", "is this too coupled", "make this maintainable", design audits of a PR, module, or architecture proposal.
    EXCLUDE: test-only work owned by test-design (still load test-design whenever tests are written or reviewed); non-Python surfaces.
    SIGNAL: Python authoring, or a quality or design question on existing Python or a described structure.
  ```
- **Rationale:** Addresses F1: the deleted skills' TRIGGER phrases route here; `test-design` stays excluded and co-loaded.

#### P5: Delete the two design skill directories <- F1
- **Target:** `.claude/skills/design-principles-expert/`, `.claude/skills/design-principles-reviewer/`
- **Action:** Remove — `git rm -r` both directories after P3 moves their reference files.
- **Rationale:** Addresses F1: one skill owns Python design; two skill descriptions leave every session's context.
- **Depends on:** P1, P3

#### P6: Repoint six routing sites <- F9, F10
- **Target:** `review-pr.md:289`, `bug-bash.md:86`, `devils-advocate.md:97`, `forensic-review.md:246`, `forensic-assessment/SKILL.md:5`, `forensic-assessment/references/output-formats.md:110`
- **Action:** Update —
  - `review-pr.md:289`, `bug-bash.md:86`: delete the third table row. The `.py` row already routes to `python-quality`.
  - `devils-advocate.md:97`: delete row 1 and fold its pattern into row 3, which already maps to `python-quality`: `"pattern": "python|cli|pydantic|langgraph|node|tool|prompt|architecture|coupling|abstraction|design|topology|graph"`. Two rows to one skill would load it twice (`devils-advocate.js:215-217` flatMaps every match).
  - `forensic-review.md:246`, `output-formats.md:110`: `python-quality` for code and structure, `test-design` for tests.
  - `forensic-assessment/SKILL.md:5`: EXCLUDE list drops `design-principles-reviewer`.
- **Rationale:** Addresses F9: nothing dangles. F10: the devils-advocate route lands on a section that states its document mode.
- **Depends on:** P1

#### P7: `task-structuring` Do field carries Gate 0 <- F6
- **Target:** `.claude/skills/task-structuring/SKILL.md` § Writing the Do field (after "Name **every** participating field…"); § Repo-specific Verify rules → Complexity budget bullet; § Author checklist
- **Action:** Add — one paragraph and one checklist item:
  - Do field: "A task that creates or grows a function carries the Gate 0 output of `python-quality` (§ Gate 0 — required before writing): the unit list, one verb per unit, and the budget self-check. Name each unit as a function or type title. A unit that matches a Known breach shape names its helpers first." Cite by anchor. Do not restate the budgets or the shapes.
  - Checklist: "- [ ] Every task that adds or grows a function carries a Gate 0 unit list."
- **Rationale:** Addresses F6: the plan pre-satisfies Gate 0; the implementer composes from the plan, not at write time.

#### P8: `phase-slicing` cross-phase contracts carry the design DoD <- F6
- **Target:** `.claude/skills/phase-slicing/SKILL.md` § Cross-phase contracts (the "For each cross-phase dependency, record:" list); § Author checklist
- **Action:** Add — one list item and one checklist item:
  - "**Design DoD** — when the producing phase introduces a module, class, or Protocol: its responsibility in one sentence without 'and', and the fake in `tests/fakes.py` that exercises it. See `python-quality` § Design — landmines." Cite by anchor `#design--landmines`.
  - Checklist: "- [ ] Every new module, class, or Protocol in a cross-phase contract states its one-sentence responsibility and its test fake."
- **Rationale:** Addresses F6: SRP and testability are decided at the boundary, where they are cheap.
- **Depends on:** P1 (anchor exists)

#### P9: Import-cycle gate <- F7
- **Target:** `pyproject.toml` (dev extra + `[tool.importlinter]`), `uv.lock`, `Makefile` (new `imports-check`; `check`; `.PHONY`), `scripts/hooks/pre-commit` (new step), `AGENTS.md` § Commands, `CONTRIBUTING.md`, `README.md:12`
- **Action:** Add —
  - Tool: `import-linter` (current 2.10, 2026-02). Contract `acyclic_siblings` needs no layer or per-module declaration; `lint-imports` exits non-zero on failure; `TYPE_CHECKING` imports count as edges by default (`exclude_type_checking_imports` stays unset). Ruff cannot substitute — `PLR0401` is unimplemented (astral-sh/ruff#2914). Rejected: pylint `cyclic-import` (drops cycles guarded by `TYPE_CHECKING`, by design); tach (docs do not state whether `forbid_circular_dependencies` scans real imports); pycycle (unmaintained since 2017).
  - Config:
    ```toml
    [tool.importlinter]
    root_package = "exact"

    [[tool.importlinter.contracts]]
    name = "No import cycles inside exact"
    type = "acyclic_siblings"
    ancestors = "exact"
    ```
  - Semantics to record in `CONTRIBUTING.md`: the contract is package-level. At each level it squashes every sibling's subtree and forbids cycles between siblings, then drills into each subpackage. It catches every module-level cycle and also fails on package-to-package indirection that is not a module cycle. Stricter than "no module cycle"; the intended posture.
  - `make imports-check`: `$(UV) lint-imports`. Add to `check` between `complexity-check` and `workflows-check`. Update the `check` help text.
  - `pre-commit`: step 5 `imports-check`, same `section`/`ok`/`err` shape as step 4.
  - Docs: `AGENTS.md` Commands block (+`make imports-check`) and the hooks sentence ("Commits then run `make lint-fix` (with re-stage), `make complexity-check` and `make imports-check`"); `CONTRIBUTING.md` pre-commit list and gate table; `README.md:12` comment.
- **Rationale:** Addresses F7: the one objective design rule in the skill set gets a program behind it. Baseline 0 (verified by AST scan with submodule resolution; Task 4.1 re-verifies with the tool).

#### P10: Plan-artifact guard <- F8, F11
- **Target:** new `.cursor/hooks/plan-guard.py`; new `tests/test_plan_guard.py`; new `scripts/hooks/post-plan.sh`; `Makefile` (new `plan-check` target; `.PHONY`); `.claude/settings.json` (PostToolUse `Write|Edit` entry); `.cursor/hooks.json` (second `afterFileEdit` entry); `CLAUDE.md` § hooks table; `.claude/commands/plan.md` Phase 5 (new final step) and Phase 6 table; `AGENTS.md` § Commands; `CONTRIBUTING.md`
- **Action:** Add —
  - `plan-guard.py <plan.md>`: parse every `**Verify:**` command (inline, bullet, fenced) and every `**Files:**` field. Check: each `TEST=` path starts with `tests/` and exists; each identifier in `K=` (split on `and`/`or`/`not`/parens) is a **substring** of at least one `def test_*` name in the TEST path (pytest `-k` is substring match; `K=test_academic_signal` is valid against `test_academic_signal_is_true_for_spec_heuristics` — `plan.md:162` vs `task-structuring` example) (file, or any file under a TEST directory); each `make <target>` exists as `^<target>:` in `Makefile`; each `modify:` path exists; each `create:` path does not exist. Skip the `<!-- tasks: phase N -->` placeholder check (the `/plan` skeleton write is intentional). Root: `CLAUDE_PROJECT_DIR`, else `git rev-parse --show-toplevel` (mirror `complexity-guard._repo_root`). Exit 2 with one line per finding `path:line → claim → evidence`; exit 0 when clean; exit 0 (fail open) when the file is not under `.claude/artifacts/plan/` or is unreadable; usage error exit 1.
  - `make plan-check FILE=<path>`: runs the guard. `FILE=` required; `.md` only.
  - `post-plan.sh`: stdin JSON → `.tool_input.file_path` (same jq shape as `post-edit.sh`); `case */.claude/artifacts/plan/*.md`; run `make plan-check`; on exit 2 forward the report to stderr and exit 2; else exit 0. Fails open without jq/make.
  - Hooks: Claude `PostToolUse` `Write|Edit` → `scripts/hooks/post-plan.sh` (timeout 20). Cursor `afterFileEdit` → same script.
  - `plan.md` Phase 5: append step 6 — "Run `make plan-check FILE=<plan-path>`. Do not enter Phase 6 while it reports a finding." Phase 6 table: annotate the path and make-target rows "also machine-checked by `make plan-check`".
  - Known limit, stated in the guard's docstring and in `plan.md` step 6: `create:` paths exist once execution starts. An edit to a plan after its Phase 1 lands reports those as findings. The hook reports; it never denies. Read the report against execution state.
- **Rationale:** Addresses F8: path and target rows are checked by a program on every plan write and before the LLM review. F11: the Cursor twin keeps the mirror true.

### Excluded Findings

| Finding | Severity | Reason excluded |
|---------|----------|-----------------|
| — | — | none |

### Execution Notes

- P1–P6 land in one commit. A deleted skill with a live routing site is a silent failure.
- P9 and P10 add Python under `.cursor/hooks/`. That path is in `PYTHON_SRC` (ruff) and is
  not complexity-exempt. Gate 0 applies. Unit lists are in the tasks below.
- Skills to load during execution: `python-quality` for P9/P10 code, `test-design` for their
  tests.

---

## 1. Scope boundaries

- No change under `src/exact/`. The cycle baseline is 0; the gate lands on HEAD as is.
- No change to `docs/spec.md`, `docs/architecture.md`.
- No change to `test-design`, `fix-findings`, `harden-doc`, `forensic-assessment` methodology.
- No edit inside `.claude/artifacts/**`.
- `plan-guard.py` checks paths and make targets only. Symbols named in Do fields stay with the
  `/plan` Phase 6 reviewer.
- The guard budgets stay where they are. No skill restates a number.

## 2. Phases

### Phase 1 — Merge the design skills into `python-quality`
**Goal:** one Python skill carries design guidance inline; the two design skills are gone; nothing routes to them.
**Stop-after-this-phase:** yes — every Python touch loads design guidance; all routes resolve.
**Horizontal constraint:** this phase is **one commit**. The reference `git mv` (Task 1.2) leaves the expert skill pointing at moved files until Task 1.4 deletes it, and a deleted skill with a live routing site fails silently. Tasks 1.1–1.4 are ordered steps inside that commit, each with its own Verify; none is committed alone.
**Owns files:** `.claude/skills/python-quality/**`, `.claude/skills/design-principles-*/**` (deleted), the six routing sites.
**Provides:** anchors `python-quality/SKILL.md#design--landmines` and `#gate-0--required-before-writing` for Phase 2.
**Acceptance criteria:**
- `grep -rn "design-principles" .claude .cursor AGENTS.md CLAUDE.md docs README.md CONTRIBUTING.md | grep -v "^.claude/artifacts/"` prints nothing.
- `python-quality/SKILL.md` has one `## Design — landmines` section in Required/Forbidden register; the only numbers in the file are the guard's four.
- Tone gate: the P1 step 7 grep prints nothing for `SKILL.md` and `references/review-checklist.md` outside fenced code.
- [ ] Full integration gate passes: `make check`

### Phase 2 — Planning skills carry Gate 0 and the design DoD
**Goal:** every plan task and cross-phase contract pre-satisfies the implementer's Gate 0.
**Stop-after-this-phase:** yes.
**Owns files:** `task-structuring/SKILL.md`, `phase-slicing/SKILL.md`.
**Acceptance criteria:**
- Both anchors cited in the two skills exist as headings in `python-quality/SKILL.md`.
- [ ] Full integration gate passes: `make check`

### Phase 3 — Plan-artifact guard
**Goal:** a program checks plan references on every plan write and before `/plan` Phase 6.
**Stop-after-this-phase:** yes.
**Owns files:** `.cursor/hooks/plan-guard.py`, `tests/test_plan_guard.py`, `scripts/hooks/post-plan.sh`, `Makefile`, `.claude/settings.json`, `.cursor/hooks.json`, `CLAUDE.md`, `.claude/commands/plan.md`, `AGENTS.md`, `CONTRIBUTING.md`.
**Acceptance criteria:**
- `make plan-check FILE=.claude/artifacts/plan/exa-publication/plan.md` exits 0 or reports only true findings (inspect).
- A plan with a wrong `TEST=` path makes the hook report on write.
- [ ] Full integration gate passes: `make check`

### Phase 4 — Import-cycle gate
**Goal:** `make check` and the pre-commit hook fail on any cycle inside `exact.*`.
**Stop-after-this-phase:** yes.
**Owns files:** `pyproject.toml`, `uv.lock`, `Makefile`, `scripts/hooks/pre-commit`, `AGENTS.md`, `CONTRIBUTING.md`, `README.md`, plus any tool config file.
**Acceptance criteria:**
- The gate reports 0 cycles on HEAD.
- A scratch cycle (two throwaway modules under `src/exact/`, not committed) makes `make imports-check` exit non-zero; removing them restores 0.
- [ ] Full integration gate passes: `make check`

Ordering: Phase 2 depends on Phase 1 anchors. Phases 3 and 4 are independent of both;
Phase 3 first because it carries the most new code (risk-first).

## 3. Tasks

### Task 1.1 — Design section and Review-mode folds in `python-quality/SKILL.md`
**Do:** Apply P1 steps 1–7 and P4. Source lines: `design-principles-expert/SKILL.md:25-31, 35-41, 45-49, 53-57, 63-66`; `design-principles-reviewer/SKILL.md:27-31, 39, 49-53, 59-63, 69-73, 79-82, 89-91, 99-102, 112-138, 157, 208, 210`. Rewrite every sourced sentence into Required / Forbidden / landmine form; copy no hedge. The current file has one pre-existing hit for the step 7 grep — `SKILL.md:108` "Prefer PEP 695 `type` aliases…" — rewrite it as "Name a reusable type with a PEP 695 `type` alias; assignment aliases are forbidden for that purpose". Apply P2 to the two inline numbers (expert `:49`, `:56`) and to the folded Pass 1/Pass 5 bullets. Heading text for the new section exactly: `## Design — landmines`.
**Files:** modify: `.claude/skills/python-quality/SKILL.md`
**Verify:**
- `wc -l .claude/skills/python-quality/SKILL.md` → ≤ 375
- `grep -c "^## Design — landmines$" .claude/skills/python-quality/SKILL.md` → `1`
- `grep -o '](#[a-z0-9-]*)' .claude/skills/python-quality/SKILL.md | sort -u` — each target heading exists (`complexity-budgets--landmines`, `known-breach-shapes--exact`, `forbidden--landmines`, `design--landmines`)
- P1 step 7 tone grep → no hits outside fenced code
- `grep -nE "\b[0-9]+\+? (lines|methods|arguments|parameters|dependencies|dependents|levels|responsibilities)\b" .claude/skills/python-quality/SKILL.md` → only lines that state `6`, `10`, `40`, or `3` with the guard

### Task 1.2 — Move the three reference files; apply P2 and the overlap notes to them
**Do:** `git mv .claude/skills/design-principles-expert/references/{solid-principles,clean-code,design-heuristics}.md .claude/skills/python-quality/references/`. Then in place: P2 rows for `clean-code.md:48`, `:83`; `design-heuristics.md:192-197` lead line, `:496`; P3 overlap edits at `clean-code.md:85-105`, `:107`, `:194`, `:262`; `design-heuristics.md:328`, `:361`, `:411`, `:461`. Line numbers are pre-edit; work bottom-up per file.
**Files:** create: `.claude/skills/python-quality/references/solid-principles.md`, `.claude/skills/python-quality/references/clean-code.md`, `.claude/skills/python-quality/references/design-heuristics.md` (via `git mv`)
**Verify:**
- `ls .claude/skills/python-quality/references/` lists 6 files
- `grep -rnE "\b(300\+?|500\+?|[0-9]+\+? (lines|methods|arguments|parameters|dependencies|levels))" .claude/skills/python-quality/references/{clean-code,design-heuristics,solid-principles}.md` — every hit is `6`/`10`/`40`/`3` cited with the guard, or an example literal inside a fenced code block

### Task 1.3 — Merge the review checklists
**Do:** Apply P3's 13-section order to `python-quality/references/review-checklist.md`, pulling reviewer checklist `:18-148` in as checkable items in the P3 item register (landmine named; over-application items added). Apply P2 rows for reviewer checklist `:22, :23, :54, :75, :78, :81, :107, :136`. Drop duplicates `:99`, `:141`, `:144`. Cross-link `refactoring-patterns.md` §8 where the module-singleton item was.
**Files:** modify: `.claude/skills/python-quality/references/review-checklist.md`
**Verify:**
- `grep -c "^## " .claude/skills/python-quality/references/review-checklist.md` → `13`
- `grep -c "single implementation" .claude/skills/python-quality/references/review-checklist.md` → ≥ `1` (over-application item present)
- P1 step 7 tone grep on this file → no hits

### Task 1.4 — Delete the two skills and repoint the six routing sites
**Do:** `git rm -r .claude/skills/design-principles-expert .claude/skills/design-principles-reviewer`. Apply P6 to the six sites. In `review-pr.md` and `bug-bash.md` the table keeps two rows.
**Files:** modify: `.claude/commands/review-pr.md`, `.claude/commands/bug-bash.md`, `.claude/commands/devils-advocate.md`, `.claude/commands/forensic-review.md`, `.claude/skills/forensic-assessment/SKILL.md`, `.claude/skills/forensic-assessment/references/output-formats.md`
**Verify:**
- `grep -rn "design-principles" .claude .cursor AGENTS.md CLAUDE.md docs README.md CONTRIBUTING.md | grep -v "^.claude/artifacts/"` → no output
- `make check`

### Task 2.1 — Gate 0 in the Do field
**Do:** Apply P7 to `task-structuring/SKILL.md`. Cite `python-quality/SKILL.md#gate-0--required-before-writing` and `#known-breach-shapes--exact`. Add no number.
**Files:** modify: `.claude/skills/task-structuring/SKILL.md`
**Verify:** `grep -c "Gate 0" .claude/skills/task-structuring/SKILL.md` → `2` (Do-field paragraph and checklist item)

### Task 2.2 — Design DoD in cross-phase contracts
**Do:** Apply P8 to `phase-slicing/SKILL.md`. Cite the Phase 1 design-section anchor.
**Files:** modify: `.claude/skills/phase-slicing/SKILL.md`
**Verify:** `grep -c "Design DoD\|one-sentence responsibility" .claude/skills/phase-slicing/SKILL.md` → `2`

### Task 3.1 — `plan-guard.py` with tests
**Do:** Create `.cursor/hooks/plan-guard.py` per P10. Gate 0 unit list (one verb each; every unit inside the guard budgets):
- `PlanRef(kind, value, line)` frozen dataclass — one reference found in the plan.
- `iter_verify_commands(text) -> Iterator[tuple[int, str]]` — yield (line, command) for inline backtick, bullet, and fenced Verify shapes.
- `iter_files_refs(text) -> Iterator[PlanRef]` — yield `create`/`modify` paths from `**Files:**` lines.
- `parse_test_command(cmd) -> tuple[str | None, list[str]]` — `TEST=` path and `K=` identifiers (split on `and|or|not|(|)`, strip quotes).
- `make_targets(makefile: Path) -> set[str]` — names matching `^[a-zA-Z0-9_.-]+:` at column 0.
- `test_names(path: Path) -> set[str]` — `def test_*` names in a file, or in `*.py` under a directory.
- `check_verify(ref, root, targets) -> list[str]` — findings for one command.
- `check_files(ref, root) -> list[str]` — finding for one path.
- `audit(plan: Path, root: Path) -> list[str]` — orchestrator: read, iterate, collect.
- `_repo_root() -> Path` — `CLAUDE_PROJECT_DIR`, else `git rev-parse --show-toplevel`.
- `main(argv) -> int` — usage 1; not-a-plan-path or unreadable 0; findings 2; clean 0.
Tests in `tests/test_plan_guard.py`, loaded via `importlib.util.spec_from_file_location` as `tests/test_complexity_guard.py:23-34` does; `monkeypatch.setenv("CLAUDE_PROJECT_DIR", tmp_path)`; build a fake tree (`Makefile` with `test:`; `tests/test_x.py` with `def test_a`). Scenarios (spec-scenario names): missing TEST path → finding; K name absent → finding; K is a prefix of a longer test name → clean (substring semantics); K `a or b` both present → clean; unknown make target → finding; modify path missing → finding; create path present → finding; fenced Verify block parsed; bullet Verify parsed; path outside `.claude/artifacts/plan/` → exit 0 no output; clean plan → exit 0.
**Files:** create: `.cursor/hooks/plan-guard.py`, `tests/test_plan_guard.py`
**Verify:** `make test TEST=tests/test_plan_guard.py`

### Task 3.2 — `make plan-check` and the hook script
**Do:** Add `plan-check` to `Makefile` (`.PHONY`; `## Verify plan-artifact references. FILE=<plan.md>`; require `FILE`, `.md` only — a `require_md_file` define modelled on `require_python_file`; run `python3 .cursor/hooks/plan-guard.py "$(FILE)"`). Create `scripts/hooks/post-plan.sh` per P10, same header style and fail-open discipline as `post-edit.sh`; `chmod +x`.
**Files:** modify: `Makefile` | create: `scripts/hooks/post-plan.sh`
**Verify:**
- `printf '{"tool_input":{"file_path":".claude/artifacts/plan/exa-publication/plan.md"}}' | scripts/hooks/post-plan.sh; echo "exit=$?"` → exit 0 or 2 with a report, never a traceback
- `printf '{"tool_input":{"file_path":"src/exact/cli.py"}}' | scripts/hooks/post-plan.sh; echo "exit=$?"` → `exit=0`, no output

### Task 3.3 — Wire the hook and document it
**Do:** `.claude/settings.json`: add a second `PostToolUse` `Write|Edit` hook entry → `"${CLAUDE_PROJECT_DIR:-.}/scripts/hooks/post-plan.sh"`, timeout 20, statusMessage "Checking plan references". `.cursor/hooks.json`: add `{ "command": "scripts/hooks/post-plan.sh", "timeout": 20 }` to `afterFileEdit`. `CLAUDE.md` table: new row `PostToolUse | Write\|Edit | scripts/hooks/post-plan.sh | Reports unresolved paths and make targets in a plan artifact`. `plan.md` Phase 5: step 6 per P10; Phase 6 table: annotate two rows. `AGENTS.md` § Commands: add `make plan-check FILE=path`. `CONTRIBUTING.md` § hooks: one line.
**Files:** modify: `.claude/settings.json`, `.cursor/hooks.json`, `CLAUDE.md`, `.claude/commands/plan.md`, `AGENTS.md`, `CONTRIBUTING.md`
**Verify:**
- `python3 -c "import json;json.load(open('.claude/settings.json'));json.load(open('.cursor/hooks.json'))"`
- `grep -c "post-plan.sh" .claude/settings.json .cursor/hooks.json CLAUDE.md` → `1` each

### Task 4.1 — Add `import-linter` and verify the baseline
**Do:** `uv add --optional dev import-linter` — this repo keeps dev deps in `[project.optional-dependencies] dev` and `make setup` runs `uv sync --extra dev`; `--dev` would create a second list under `[dependency-groups]`. Add the P9 `[tool.importlinter]` block to `pyproject.toml`. Run `uv run lint-imports`. **Stop and report when the contract is BROKEN on HEAD** — the plan assumes 0; a break means either a real cycle (fix under a separate change to `src/`) or package-level indirection the contract rejects (then switch to a module-exact grimp script under `.cursor/hooks/`, with tests, and re-plan this phase). Do not loosen the contract.
**Files:** modify: `pyproject.toml`, `uv.lock`
**Verify:** `uv run lint-imports; echo "exit=$?"` → the contract is reported KEPT and `exit=0`

### Task 4.2 — Wire `imports-check` into `make check` and the pre-commit hook
**Do:** `Makefile`: add `imports-check: ## Fail on any import cycle inside exact` running `$(AT)$(UV) lint-imports`; add to `.PHONY`; insert `@$(MAKE) imports-check` in `check` after `complexity-check`; update `check`'s `##` text to "Lint, format-check, complexity, imports, workflow scripts, tests". `scripts/hooks/pre-commit`: step 5 `imports-check` mirroring step 4.
**Files:** modify: `Makefile`, `scripts/hooks/pre-commit`
**Verify:**
- `make imports-check` → exit 0
- Scratch cycle: `printf 'from exact import _b\n' > src/exact/_a.py; printf 'from exact import _a\n' > src/exact/_b.py; make imports-check; echo "exit=$?"; rm src/exact/_a.py src/exact/_b.py` → non-zero exit while the files exist
- `make check` → exit 0 after the scratch files are removed

### Task 4.3 — Document the gate
**Do:** `AGENTS.md` § Commands: add `make imports-check` line; extend the hooks sentence per P9. `CONTRIBUTING.md`: pre-commit step list (+step), gate table row, and the package-level semantics paragraph from P9. `README.md:12`: comment becomes `# lint + format-check + complexity + imports + tests`.
**Files:** modify: `AGENTS.md`, `CONTRIBUTING.md`, `README.md`
**Verify:** `grep -c "imports-check" AGENTS.md CONTRIBUTING.md Makefile scripts/hooks/pre-commit` → ≥ 1 each

## 4. Verification (end to end)

1. `make check` green after every phase.
2. Phase 1: the acceptance grep prints nothing; open `python-quality/SKILL.md` and confirm the
   design section sits before `# Implement mode`, reads under ~75 added lines, and every
   sentence in it is a rule or a landmine — the tone grep is the floor, a read is the check.
3. Phase 3: write a scratch plan under `.claude/artifacts/plan/_scratch/plan.md` with one bad
   `TEST=` path via the `Write` tool; the hook report appears; fix the path; the report stops.
   Delete the scratch directory.
4. Phase 4: `make imports-check` → 0 cycles. Add `src/exact/_a.py` importing `exact._b` and
   `_b.py` importing `exact._a`; `make imports-check` exits non-zero; delete both; exit 0.
5. Fresh-reviewer pass (AGENTS.md rule) over the whole diff via `/review-pr` dry-run or a
   `readonly-worker` agent with `python-quality` + `test-design` loaded.
