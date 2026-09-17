# Workflow Scripts — Agent Instructions

Orchestration scripts for the `Workflow` tool (`.claude/workflows/*.js`), each paired with a
command in `.claude/commands/`. This file is the **canonical home for the `args` transit
contract**. The scripts and the command `.md` files point here; they do not restate it.

## The `args` transit contract

### 1. `args` arrives as a JSON string

The `Workflow` tool delivers `args` to the script as a **JSON string**, not the object you
passed. Parse defensively — and note that `args` is injected by the runtime, so a `const args`
declaration in the script would collide. Bind the parsed value to a different name:

```js
const A = typeof args === 'string' ? JSON.parse(args) : (args ?? {})
```

### 2. That string is size-capped

Over the cap it is **truncated mid-string**, so `JSON.parse` throws
`JSON Parse error: Unterminated string` before any agent spawns. Measured bracket: a
**4,896-byte** payload succeeded; a **17,795-byte** payload failed. The exact cap was
deliberately not measured — the rules below make its value irrelevant.

**Budget: 4,000 bytes total command-side. 12,000 total / 8,000 per string field script-side.**

The two numbers are not alternatives. They guard different things, and only the first one keeps
a payload safe:

- **The command-side total is the real limit: 4,000 bytes of serialized `args`, JSON overhead
  included.** It sits inside the 4,896-byte payload that is measured to succeed. That is one
  data point, not a proof — but it is the only evidence there is, and 4,000 stays inside it
  with room for the measurement error the units caveat below describes. Each command `.md` sets
  its own per-field thresholds. They are a pre-check, not a guarantee of the total. The
  measurement rule below holds the total. Do not raise the total.
- **The script-side 12,000 / 8,000 is a tripwire, not a budget.** It writes a warning after the
  payload already arrived. It does not decide how a payload travels, and it is not known to be
  safe — the true cap can be below both numbers. It is a backstop for an orchestrator that
  ignored the rule above. It is never permission to inline 8,000 bytes.

**Measure the serialized payload. Do not add up field sizes.** Before it calls the script, the
orchestrating command writes the `args` payload it intends to pass to a file in the session
scratchpad. It then measures the exact UTF-8 byte size of that payload serialized:

```bash
jq 'tojson | utf8bytelength' <file>
```

If the size is more than 4,000 bytes, the command makes a field smaller or moves it to a sidecar
(§3). It then measures again. The measurement counts the bytes JSON escaping adds. A sum of raw
field sizes does not. `utf8bytelength` on `tojson` is byte-identical to
`Buffer.byteLength(JSON.stringify(obj))`, and it needs no second process — a command that
implements this rule must grant `Bash(jq*)` in its `allowed-tools` frontmatter, and nothing more.
The command cannot observe the harness's own serialization, so this is a close proxy, not a
byte-identical reproduction (see § Units).

Two honest caveats, neither of which changes what you should do:

- **Units. State every command-side threshold in bytes, never in characters.** The scripts
  measure `String.length` — UTF-16 code units, not bytes. For ASCII the two agree; for prose
  full of em-dashes and curly quotes the real byte count runs higher, so the script warning
  fires later than its name suggests. A *character* cap on a command-side field is worse than
  imprecise, it is unsafe in the wrong direction: 2,000 characters of a file whose section
  rules are drawn with `─` (U+2500, 3 bytes each) is 2,340 bytes, and the 4,000-byte total is
  a **byte** total. Any threshold on an inline `args` field written in characters is a defect —
  convert it. (Thresholds on things that never reach `args`, such as an excerpt length inside a
  sidecar, are out of scope.) One more unit gap to keep in mind: a field cap measures the raw
  value, while the 4,000-byte total measures the payload *after* JSON escaping. Escaping adds
  about one byte for each newline, quote and backslash. The inflation therefore grows with the
  content, and no fixed margin can bound it. The measurement above catches it, because it
  measures the escaped payload. The slack between 4,000 and the measured-safe 4,896 is left for
  the proxy-versus-harness serialization difference. That slack is an **assumption, not a bound**
  — the same fixed-margin reasoning refuted one sentence earlier, and it is unfalsifiable while
  the harness serialization stays unobservable. One case would exceed it: a harness that
  ASCII-escapes non-ASCII turns each em-dash into 6 bytes where the proxy counts 3. Keep prose
  fields small, and do not spend that slack on a bigger field cap.
- **The tripwire may be unreachable.** The true cap sits somewhere in `(4896, 17795]`. If it is
  below 12,000, `JSON.parse` throws in the fail-fast `catch` before the total check ever runs,
  and only the fail-fast message is observed. That is acceptable: both paths point at this
  file, and safety does not rest on the tripwire firing. It rests on the 4,000-byte
  command-side total, which stays inside the measured-safe 4,896 bytes. Measuring the cap
  exactly was rejected — it costs ~16 KB of authored payload per probe, and a command that
  keeps its total under 4,000 never approaches the cap, whatever its value is.

### 3. The sidecar rule

Any artifact whose size is not bounded by construction — a diff, a document under review, a
file inventory, pasted user text — **must not be inlined into `args`**. The orchestrating
command writes it to a file and passes `<name>Path`; the script's prompt instructs the agent to
`Read` that path.

**The rule is size-based, not source-based.** Some commands accept pasted-inline input where no
source file exists (`/devils-advocate`, `/brainstorm`). The test is "can this field
exceed the per-field budget?", not "did it come from a file". A source-based rule would leave
the inline mode broken.

Bounded-by-construction fields stay inline: scalars, small enumerations, a body already capped
at a stated **byte** count, a list with a stated maximum length. A character count does not
qualify — see § Units. A byte cap makes a field eligible to stay inline. It does not prove the
total is in budget — the measurement in §2 decides that.

### 4. Where the sidecar goes

**The session scratchpad, always.** It is session-scoped, so it needs no cleanup step, and it
cannot collide with a tracked path. Every command here writes its sidecars there.

**A checkout is never an alternative, however disposable it is.** The reviewed change can add a
file at any relative path, so a sidecar write inside a checkout can overwrite tracked content
and break the read-only contract — and the agent then reads the sidecar where it expected the
PR's own file. `/review-pr`'s worktree is disposable and force-removed, and it still does
not qualify; its sidecars live in the scratchpad. That was the one place this rule looked like
it had an exception, so there is now no case in which a directory other than the scratchpad is
the right answer.

### 5. Tell agents to read the file completely

`Read` truncates at 2,000 lines by default. Every Read directive in a prompt must say to read
the file **completely**, paging with `offset` past 2,000 lines. This is now the next silent
truncation boundary after the args cap — a large diff can exceed it.

A sidecar the command serializes itself must be written one field per line — pretty-printed
JSON, not compact JSON. Compact JSON puts the whole payload on line 1, and `offset` cannot page
within a line. Unlike the size bracket above, per-line truncation was **not measured here**;
the pretty-print rule is cheap insurance against it, not a response to an observed failure.

### 6. `${{ … }}` inside `args` is safe

A collision with template interpolation was investigated and **refuted**: a 41-byte probe
carrying `a${{ steps.x }}c` round-tripped intact. Size is the sole failure mechanism. Do not
"fix" this.

### 7. The recovery-echo trap

When a run fails, the `<recovery>` block in the failure notification **echoes `args` back
complete and well-formed**. The truncation happens after that snapshot is taken, so comparing
what you sent against the recovery echo proves nothing. Do not use it to rule size out.

## Fail-fast preamble

Every script replaces its bare `JSON.parse` with the fail-fast + tripwire preamble: a `try`
that rethrows with the received length and the size-cap explanation, a per-string-field warning
above 8,000 chars, and a total-payload warning above 12,000.

**The total check is not redundant with the per-field check.** The per-field loop inspects only
string values, so it misses arrays and objects (`diffStats`, `recentChurn`), and a payload can
reach the total from many small fields none of which trips the per-field warning.

**Neither check observes the 4,000-byte command-side total.** They fire at 8,000 and 12,000 —
two and three times it. Nothing mechanical enforces the real budget: not the scripts, not `make
validate`, not CI. It is held by the payload measurement in §2, by the per-field thresholds each
command `.md` states as a pre-check, and by whoever reviews a change to one. Do not read a silent
run as proof the payload was in budget.

**The preamble is duplicated in all five scripts by necessity, not by oversight.** Workflow
scripts are self-contained — the runtime cannot load a shared module. Do not "DRY" it out.

Neither warning fails the run. That is deliberate: a hard failure on a warning-level condition
would be worse than the truncation it guards against.

## Required-args check

The preamble's tripwires catch a payload that is too **big**. A payload missing a field entirely
is the opposite failure and needs the opposite response: **throw**.

Every sidecar path a script interpolates into a prompt must be presence-checked immediately
after the preamble, and the check must `throw` naming the missing keys and the received keys.
Inlined text failed loudly for free — a `JSON.parse` on a truncated string, or an obviously
empty prompt. A path does not: `Read the file at undefined` renders cleanly, every agent reads
nothing, the run completes, and synthesis reports a confident "no findings" on an artifact
nobody opened. Converting a field to a path therefore **creates** this obligation.

Two rules for writing one:

- **Presence decides the branch, never a companion flag.** Where a payload may arrive inline or
  by path, branch on which key is present. A `<name>Inline: bool` flag restates what key
  presence already encodes and can disagree with it — omitted or mistyped, it silently selects
  the branch whose key is absent. `/devils-advocate` carried exactly that bug.
- **Requirements may be variant-conditional.** Where the paired `.md` tells the orchestrator to
  omit keys that don't apply (`forensic-review`'s variants), the check keys off the variant.
  A key that is genuinely optional stays guarded by a ternary at its use site instead.

These checks are per-script and sit **after** the shared preamble, so the "duplicated verbatim"
claim above stays true of the preamble itself.

## Authoring notes

- `Date.now()`, `Math.random()`, and argless `new Date()` **throw** in workflow scripts (they
  would break resume). Pass timestamps and seeds in via `args`.
- Scripts have no filesystem or Node API access. Only the injected hooks
  (`agent`/`parallel`/`pipeline`/`phase`/`log`/`args`/`budget`/`workflow`) and JS built-ins.
- Prompts the script builds itself are **not** subject to the args cap — it applies only at the
  orchestrator→script boundary. Agent-to-agent hand-offs inside a script need no truncation.
- Each script carries a `// SYNC:` header naming the command `.md` it pairs with and which side
  owns what. Keep both in lockstep.
- `make workflows-check` syntax-checks every script here, host-side (skips with a warning when
  `node` is absent), and `make check` runs it. It catches typos only — see the comment on the
  `workflows-check` target in `Makefile` for the wrapper mechanics and the line-1 constraint it
  imposes on these files.
