---
description: >
  Write or update docs/specs/<topic>.md — a repository-grounded specification that /plan consumes.
  Subagents collect the evidence and hunt the gaps. The main agent asks the product questions, one
  at a time, and writes the document. Never chooses a behavior answer for the user.
argument-hint: "<topic-slug> <rough request or repository-relative input path>"
allowed-tools: Read, Glob, Grep, Write, Edit, AskUserQuestion, Agent, Task, SendMessage, Skill, Bash(make spec-check*), Bash(make spec-check-ready*), Bash(git status*)
disable-model-invocation: true
---

You write one specification. The specification is the product contract. `/plan` takes every
product decision from it, and from nothing else.

**You delegate the reading and the gap search. You keep the questions and the document.**
Three agents do the work that does not need this conversation:

| Agent | Gives you | Never gives you |
|---|---|---|
| `codebase-pattern-finder` | current behavior and conventions, with `file:line` | a recommendation |
| `web-researcher` | external contracts and prior art, with URLs | a repository fact |
| `spec-gap-finder` | the contract restatement and the gap list | a product answer |

No agent holds a `Write` grant. **You write every byte of the document.**

`.cursor/hooks/spec-guard.py` owns the validation rules. `make spec-check` is authoritative. The
lists below help you write; they never replace a run of the gate.

## Phase 0 — Parse and pin

1. The first token of `$ARGUMENTS` is `<topic>`. The rest is the rough request, or a
   repository-relative input path.
2. **Both parts are required. STOP when either is absent.** Print what is missing. Never infer a
   topic. Never search for an input.
3. **Validate `<topic>` against `^[a-z0-9][a-z0-9._-]*$`. STOP when it fails.** Print the slug.
   The pattern is one path component. An invalid slug writes outside `docs/specs/`.
4. STOP when the input is a path that does not exist. Print the path.
5. The only output path is `docs/specs/<topic>.md`. Write no other file.
6. Read `docs/specs/<topic>.md` when it exists. This run is an update. Phase 5 states what an
   update may not change.
7. Read `AGENTS.md`, the input, and the related documents. Read `docs/spec.md` and
   `docs/architecture.md` when the topic touches the graph, the bounds, or the tools.

## Phase 1 — Ground the request in the repository (fan out)

Send the agents in one block when their questions are independent.

1. **`codebase-pattern-finder`, one agent per area the request touches.** Ask each one for the
   current behavior, the convention, and a `file:line` for every claim. Name the area. Never ask
   for an opinion, a ranking, or a design.
2. **`web-researcher`, only for a fact the repository cannot hold.** A vendor contract, a library
   semantic, a protocol rule, or prior art. The agent has no filesystem access. Give it a
   self-contained question. Do not send it a repository path.
3. Record each returned repository reference as an `E<n>` line: `repo:<path>`,
   `repo:<path>#L<n>`, or `repo:<path>::<symbol>`. Record each returned source as
   `url:https://…`. A decision the user takes alone is `person-decision`.
4. **A reference the gate cannot resolve is a defect.** The path must exist. The line must be
   inside the file. Check a suspect reference with `Read` before you write it. Do not combine
   `#L<n>` and `::<symbol>` in one reference.
5. **Cite tracked files only.** `spec-check-ready` resolves evidence against `HEAD`, not against
   the worktree. A reference to an untracked or ignored file passes `spec-check` and fails later.

## Phase 2 — Write the draft

Write `docs/specs/<topic>.md` with `Status: Draft`. Use the structure in **Document structure**.
Write it in ASD-STE100 Simplified Technical English. Keep instruction sentences to 20 words or
fewer. Keep descriptive sentences to 25 or fewer.

Write the behavior you can prove. Write every gap as an open question. Do not fill a gap.

Run `make spec-check FILE=docs/specs/<topic>.md`. Repair every finding.

## Phase 3 — Find the gaps in the draft

Send ONE `spec-gap-finder`. It runs with fresh context. Its own definition governs how it
searches. Do not re-instruct it beyond the inputs.

Give it four things:

1. The path `docs/specs/<topic>.md`.
2. The evidence reports from Phase 1, in full. It reads code only where they stop.
3. The answers already in `## Decisions`, as the pre-answered decisions it reconciles against.
4. The directories the request touches.

It returns the contract restatement and the gap list.

- **The contract restatement fixes the names.** A spec-given name is immutable for the rest of
  the run, and for `/plan`.
- Every gap it marks `behaviour-affecting` becomes a question in Phase 4.
- A gap it marks `covered by` needs no question. Confirm the cover is explicit.
- Keep the restatement in this conversation. Do not write it to disk. `docs/specs/<topic>.md` is
  the only output.

## Phase 4 — Ask the product questions (hard gate)

1. **Ask one question per `AskUserQuestion` call.** One product fact per question. At most four
   options.
2. **Cite repository evidence in every question.** Give the `E<n>` id, or the `path#L<n>`. A
   question without evidence is a guess.
3. Put the option the gap finder marked `(default)` first. Label it `(Recommended)`.
4. **Never choose a behavior answer for the user.** A default you applied yourself is a defect.
5. Write each accepted answer into `## Decisions` as `D<n>`. Give it the question, the answer, the
   impact, and the evidence. **`Evidence` holds exactly one value.** `E1, E3` fails the gate.
   Cite the strongest single reference.
6. **Repeat the repository comparison after an answer changes behavior.** Send
   `codebase-pattern-finder` again for the affected area. Send the gap finder again when the
   answer opens a new surface. A later answer can contradict an earlier requirement.
7. Keep every unanswered gap as a `### Q<n>` entry in `## Open questions`.
8. When `AskUserQuestion` is unavailable, leave `Status: Draft`, write the `Q<n>` entries, and
   **STOP**. Do not proceed on an unanswered gap.

## Phase 5 — Write and validate

1. Write the complete document after each answer block. Run
   `make spec-check FILE=docs/specs/<topic>.md` after each complete write. Repair every finding
   before the next question.
2. **An update is append-only in its identifiers.** Never renumber `R<n>`, `D<n>`, or `E<n>`.
   Never delete one. Retire a requirement or a decision with `superseded by R<n>` or
   `superseded by D<n>`, and point at a later active entry.
3. **Increase `Revision` when the document differs from `HEAD`.** The gate compares against
   `HEAD` and rejects a stale revision.
4. `TBD`, `TODO`, and "to be decided" are rejected outside a fenced example. An unknown belongs in
   `## Open questions`.
5. Every active requirement needs at least one acceptance criterion, in every status. An
   acceptance criterion may not name a superseded requirement.

## Phase 6 — The Ready gate

1. Set `Status: Ready` only when `## Open questions` holds exactly `None.`
2. `make spec-check-ready FILE=docs/specs/<topic>.md` needs a committed document, a clean tracked
   worktree, and no difference from `HEAD`. Run it only after the commit. It fails before that,
   and the failure is correct.

## Phase 7 — Report

1. Print the path, the `Status`, the `Revision`, the requirement count, the decision count, and
   the open-question count.
2. State the next step. **Do not run it. Do not stage. Do not commit.**
   - "Commit `docs/specs/<topic>.md`, then run `make spec-check-ready FILE=docs/specs/<topic>.md`."
   - "Run `/plan <topic>` after the specification is `Ready` and committed."
3. **Do not start `/plan` automatically.**

## Document structure

```markdown
# <title>

Topic: <topic>
Revision: <positive integer>
Status: Draft | Ready | Superseded
Superseded by: None | docs/specs/<topic>.md

## Goal

<goal>

## Requirements

### R1 — <title>
- **Status:** active | superseded by R<n>
- **Behavior:** <observable behavior>

## Out of scope

- <boundary>

## Decisions

### D1 — <declarative title>
- **Status:** active | superseded by D<n>
- **Question:** <resolved question>
- **Answer:** <selected behavior>
- **Impact:** <affected behavior or interface>
- **Evidence:** <one of: E<n>, repo:path, repo:path#L<n>, repo:path::symbol, url:https://…, person-decision>

## Repository evidence

- E1: <evidence value>

## Acceptance criteria

- **R1:** <observable pass condition>

## Open questions

### Q1 — <open product question>
- **Affects:** R1, D2
- **Evidence:** <one of: E<n>, repo:path#L<n>, url:https://…, person-decision>
```

`## Open questions` holds the `Q<n>` entries, or the single line `None.` It never holds both.
`Affects` is a list: known `R` and `D` identifiers, separated by `, `. `Evidence` is never a
list.

## Remember

- You write **one** file: `docs/specs/<topic>.md`. Never `assumptions.md`, `gaps.md`, or
  `contract.md`. `/plan` owns its own directory.
- The agents read. You ask, and you write.
- A product answer from an agent is a defect. The user owns every behavior decision.
- A gap you filled yourself is a defect. Write it as a `Q<n>` entry.
- An unresolvable evidence reference is a defect. The gate finds it. Find it first.
- `Status: Ready` with an open question is a defect. The gate rejects it.
