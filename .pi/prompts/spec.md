---
description: Create or update a repository-grounded committed specification.
argument-hint: "<topic-slug> <rough input or path>"
---

Create or update the specification for topic `$1`.

Use the remaining input as the rough request or as a repository-relative input path:
`${@:2}`.

Rules:

1. Use only `docs/specs/$1.md` as the output path.
2. Validate `$1` with `^[a-z0-9][a-z0-9._-]*$` before writing.
3. Read `AGENTS.md`, the input, related documents, implementation, tests, and Make targets.
4. Keep the document `Status: Draft` while a product answer remains open.
5. Ask one product question at a time. Cite repository evidence in each question.
6. Never choose a behavior answer for the user.
7. Write each accepted answer into the `Decisions` section.
8. Repeat the repository comparison after an answer changes behavior.
9. Set `Status: Ready` only when `## Open questions` contains exactly `None.`.
10. Run `make spec-check FILE=docs/specs/$1.md` after each complete write.
11. Do not start `/plan` automatically.

Use this document structure:

```markdown
# <title>

Topic: $1
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
- **Evidence:** <E<n>, repo:path, repo:path#L<n>, repo:path::symbol, url:https://..., or person-decision>

## Repository evidence

- E1: <evidence value>

## Acceptance criteria

- **R1:** <observable pass condition>

## Open questions

None.
```

Run `make spec-check-ready FILE=docs/specs/$1.md` only after the specification is committed and
unchanged from `HEAD`. If questioning is unavailable, leave `Status: Draft`, write the questions,
and stop.
