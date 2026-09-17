---
description: >
  Write .claude/artifacts/plan/<topic>/plan.md — a lean, phased, task-level plan that an LLM executes task by
  task. A fresh agent interrogates the spec first. Every behaviour-affecting gap is resolved
  before planning starts. Each resolution lands in assumptions.md. A second fresh agent then
  grounds every path, count and command against the tree. Writes only under .claude/artifacts/plan/<topic>/.
  Never edits src/.
argument-hint: "<topic-slug> <spec path or spec text> [--assume \"<decision>\"]..."
allowed-tools: Read, Glob, Grep, Write, Edit, AskUserQuestion, Skill, Agent, Task, SendMessage, mcp__serena__initial_instructions, mcp__serena__get_symbols_overview, mcp__serena__find_symbol, mcp__serena__find_referencing_symbols, Bash(git check-ignore*), Bash(date*), Bash(mkdir*)
disable-model-invocation: true
---

You write a plan that an LLM executes task by task. The plan is the contract. The executor does
not read the spec, and it does not read this conversation.

**Two skills own the method.** `phase-slicing` owns where the phase lines go.
`task-structuring` owns what a task and a Verify look like. This command owns the
interrogation gate, the output contract, and the grounding review. **Never restate a skill rule
here.** Load the skill at the phase that needs it.

Use `/plan` for work of more than one phase. Such work spans sessions. Plan mode stays correct
for a single-PR change inside one session.

## Phase 0 — Parse, pin, refuse to overwrite

1. Parse `$ARGUMENTS` into three parts:
   - `<topic-slug>` — the first token.
   - The spec — a path to a file, or free text.
   - Zero or more `--assume "<decision>"` entries. These are optional. Each pre-answers a gap.
2. **Both the topic slug and the spec are required. STOP when either is absent.** Print what is
   missing. **Never infer a spec.** Never search for one. Never treat an empty argument as a
   request to look around.
3. STOP when the spec is a path that does not exist. Print the path.
4. **Validate `<topic-slug>`. STOP when it fails.** The slug must match
   `^[a-z0-9][a-z0-9._-]*$`. That pattern is one path component. It admits no `/` and no leading
   dot. Print the slug on a failure. An invalid slug can resolve outside `.claude/artifacts/plan/`. This
   command then writes over source files. The steps below write this value `<topic>`.
5. Run `mkdir -p .claude/artifacts/plan/<topic>`.
6. Run `git check-ignore -q .claude/artifacts/`. The trailing slash is required. `.claude/artifacts/`
   is gitignored on purpose, so a hit is the expected result. On a miss, warn that the directory
   is tracked, and ask whether to continue. A plan is a working artifact. It does not go into the
   repository.
7. **Pin the plan path.** `<plan-path>` is `.claude/artifacts/plan/<topic>/plan.md`. When that file exists,
   ask: resume and fill the gaps, or write `.claude/artifacts/plan/<topic>/plan-<YYYYMMDD>.md`. Set
   `<plan-path>` to the answer. On the dated answer, STOP when that dated file also exists.
   Phases 5, 6 and 7 use `<plan-path>` and no other name. `assumptions.md` is append-only.
   Never renumber an entry. Never rewrite one. `contract.md` and `gaps.md` are regenerated on
   every run.

## Phase 1 — Interrogate the spec

Send ONE `spec-interrogator` subagent (the `Agent` tool; some harness versions name it `Task`).
It runs with fresh context. Its own definition governs how it interrogates. Do not re-instruct it
beyond the inputs and the serena-first rule. Restate that rule for every subagent that navigates
code.

Give it five things:

1. The spec — inline text, or the path.
2. The `--assume` entries, verbatim.
3. `.claude/artifacts/plan/<topic>/decisions.md`, when that exact path exists. Name no other document. Do not
   look for one.
4. `.claude/artifacts/plan/<topic>/assumptions.md`, when that exact path exists. A resumed run must not re-ask
   a settled gap.
5. The directories the spec touches, when you already know them.

It returns the contract restatement and the gap list. It marks each gap `open`, or `covered by`
a pre-answer. Spec-given names from its contract restatement are immutable for the rest of the
run.

**Write both artifacts to disk. The agent holds no `Write` grant, so you write them.** Put the
contract restatement in `.claude/artifacts/plan/<topic>/contract.md`. Put the gap list in
`.claude/artifacts/plan/<topic>/gaps.md`. Phase 6 audits the plan against both files. An artifact that stays in
this conversation is invisible to a fresh reviewer.

Then reconcile the `open` gaps against **this conversation** only. You do this yourself. The
agent cannot see the conversation. A gap is resolved only when an explicit answer covers it.
Update `gaps.md` with each status you change.

## Phase 2 — Resolve the open gaps (hard gate)

1. Ask about each `open` behaviour-affecting gap with `AskUserQuestion`:
   - One fact per question.
   - At most 4 questions per call, and at most 4 options per question.
   - Put the agent's default first. Label it `(Recommended)`.
   - Repeat the calls until no behaviour-affecting gap is open.
2. Never substitute a default the user did not pick. When `AskUserQuestion` is unavailable, print
   the numbered gap list with the defaults, and **STOP**.
3. Write an entry for **every** gap, not only the ones you asked about. A gap the interrogator
   marked `covered by`, and a gap the conversation settled, each get an entry too. Write them to
   `.claude/artifacts/plan/<topic>/assumptions.md`:

```markdown
## A<n> — <the decision as one declarative sentence>
- **Gap:** <the `Q<n>` id from gaps.md>
- **Question:** <the question as asked>
- **Answer:** <what the user picked, verbatim. For a gap nobody was asked: the value applied>
- **Source:** user-answer | default-approved | pre-answered (--assume) | from-decisions
  | from-conversation | default-applied
- **Impact:** <one line — what this fixes in the implementation>
- **Evidence:** <symbol, file, or `decisions.md § N`, or `none — user decision`>
- **Date:** <YYYY-MM-DD>
```

4. Record a cosmetic gap the same way, with `Source: default-applied`. Do not ask about it.
5. **Do not enter Phase 3 while a behaviour-affecting gap is open.**

Rule 5 always wins. The following is advice, not a gate. A run that opens more than about 12
questions suggests the spec is not ready. Say so, and offer the gap list instead of a plan. Go on
when the user wants the plan anyway.

## Phase 3 — Draw the phases

1. Invoke `Skill(skill="phase-slicing")`. Follow it. Do not repeat its rules here.
2. Produce the phase list, the cross-phase contracts, and the file-ownership map. Work from
   `contract.md`. Call `initial_instructions` and use serena when you must read code for a
   signature the contract does not carry.
3. The skill sends you back when a cross-phase signature will not write. Go back to Phase 2, and
   ask about it there.

## Phase 4 — Decompose into tasks

1. Invoke `Skill(skill="task-structuring")`. Follow it. Do not repeat its rules here.
2. Produce Do, Files, and Verify for every task. Produce the acceptance criteria for every phase.
3. The skill sends you back to the phase boundary when a task will not decompose. Go back to
   Phase 3, and redraw it there.

## Phase 5 — Write the draft

Write `<plan-path>` in ASD-STE100 Simplified Technical English. Keep instruction
sentences to 20 words or fewer. Keep descriptive sentences to 25 or fewer.

### The plan is machine input. Write it lean.

An LLM executes this document. It reads a task, and it acts. It does not need to be persuaded,
introduced, or reminded.

**Every line must change what the executor does. Delete every line that does not.**

Delete these on sight:

- Rationale, background, and motivation. Why the work matters changes no keystroke.
- Benefits, goals prose, and summaries of what an earlier phase did.
- Restated decisions. Cite `A<n>`. Never repeat the content of an entry.
- Restated rules from `AGENTS.md` or from either skill. Cite the file.
- "Note that", "it is important to", "keep in mind", "as mentioned above".
- Alternatives you considered and rejected.
- Any sentence that would still be true if the task were dropped.

Write fields, not paragraphs. `task-structuring` owns what a Do field carries. Add
nothing beyond it.

### Output shape

```markdown
# <Topic> — plan
Spec: <path or "inline">   Assumptions: ./assumptions.md   Date: <YYYY-MM-DD>

## 1. Assumptions in force
<ids only — "A1-A6; A4 governs every timestamp comparison". Never restate an entry.>

## 2. Scope boundaries
<Per phase-slicing, "Scope boundaries at the structure level".>

## 3. Phases
### Phase N — <name>
**Goal:** · **Stop-after-this-phase:** · **Owns files:** · **Provides (cross-phase contract):**
**Acceptance criteria:** <targeted bullets>
- [ ] Full integration gate passes: `<command>`

## 4. Tasks
### Task N.n — <title>
**Do:** · **Files:** create: … | modify: … · **Verify:** `<command>`
```

Write no implementation code. Write no commentary outside the document.

### Write it in steps. Never in one call

One large write degrades the end of the document. The last tasks lose fields and become vague.

1. Count the phases. Call that number `N`.
2. First, `Write` the skeleton. It carries the title, the metadata line, § 1, § 2 and § 3.
   § 3 carries every phase block in full. § 4 carries the heading and `N` placeholder lines only.
   A placeholder line is `<!-- tasks: phase N -->`, with the phase number in place of `N`.
3. Then one `Edit` per phase. Each `Edit` replaces one placeholder line. It writes the
   `### Task N.n` blocks of that phase only.
4. Split a phase of more than 6 tasks into two `Edit` calls. Keep the placeholder line at the end
   of the first `Edit`.
5. Never rewrite a part you

## Phase 6 — Grounding review (hard gate)

A plan that asserts a false fact about the tree ships a bug that no gate catches. Audit the plan
before anyone executes it.

1. Send ONE `fs-readonly-worker` subagent (the `Agent` tool; some harness versions name it
   `Task`) with fresh context. The prompt MUST restate the serena-first rule. The agent holds no
   Bash and no web tools, so it verifies by reading this tree only.

   Give it four paths: `<plan-path>`, `assumptions.md`, `contract.md`, and `gaps.md`. Give it the
   checklist below. **Copy the delete-on-sight list from Phase 5 into the prompt, and copy the
   20-word and 25-word STE limits.** A reviewer without the criteria applies its own taste.

   | Check | Method |
   |---|---|
   | Each `Files: modify:` path exists | `Glob` |
   | Each `Files: create:` path does not exist | `Glob` |
   | Each symbol a Do field names exists | `find_symbol` |
   | Each call-site or caller count | `find_referencing_symbols`. **Never `make lint` output** — it does not report call sites |
   | Each `make` target in a Verify exists | `Grep` the `Makefile` for the target |
   | Both skill Author checklists pass | Read the two `SKILL.md` files |
   | Every name matches `contract.md` | Read `contract.md` |
   | Every behaviour-affecting gap in `gaps.md` has an `A<n>` entry | Read `gaps.md` and `assumptions.md` |
   | Every line changes what the executor does | Apply the delete-on-sight list. Quote each line that fails |
   | STE compliance | 20 words for an instruction, 25 for a description |
   | No task placeholder remains | `Grep` the plan for `<!-- tasks: phase` |

2. Require this report format: `task id → claim → evidence → blocking | non-blocking`. **Every
   row above is blocking.** A leanness finding and an STE finding block the same as a wrong path.
3. Apply each fix with `Edit`. Never rewrite the plan. Confirm the fixes once with
   `SendMessage` to the same agent. Send a new agent instead when that agent no longer
   answers.
4. **Refuse to finalize while a blocking finding is open.** An audit after execution is too late.

## Phase 7 — Report

1. Print the four file paths. Print the phase count and the task count. Print the assumption-id
   range, and the count of findings fixed in Phase 6.
2. State the possible next steps. **Do not run them. Do not stage anything. Do not commit. Do not
   open a pull request.**
   - "Run `/forensic-review <plan-path>`. A plan is not trustworthy until
     something adversarial has read it."
   - "Review `.claude/artifacts/plan/<topic>/` before any code. The directory is gitignored. Copy
     what the repository must keep into `docs/`."
   - "Execute Phase 1 of the plan."

## Remember

- You write **only** under `.claude/artifacts/plan/<topic>/`. You never create or edit a file under `src/`.
- You write four files: `contract.md`, `gaps.md`, `assumptions.md`, and `<plan-path>`.
- `assumptions.md` is the single home of every decision the spec did not make. The plan cites the
  ids. The plan never restates an entry.
- The two skills own the method. This file owns the gate, the contract, and the review.
- A gap you answered for the user is a defect. Ask.
- A line that does not change what the executor does is a defect. Delete it.
- One `Write` for the whole plan is a defect. Write the skeleton, then one phase per `Edit`.
