// SYNC: pairs with .claude/commands/bug-bash.md — the command owns scope parsing,
// citation verification, report rendering, and the severity tier names; this script owns
// agent prompts, rule blocks, schemas, fan-out, synthesis, and the severity DEFINITIONS
// (SEVERITY_DEFINITIONS). Edit severity labels together.
export const meta = {
  name: 'bug-bash',
  description: 'Parallel forensic bug scanners -> synthesizer; returns verified-candidate findings',
  phases: [
    { title: 'Scan', detail: 'correctness/security/integrity scanners + conditional domain and doc-vs-code' },
    { title: 'Synthesize', detail: 'dedupe, consolidate, severity-classify, cap at 10' },
  ],
}

// args: { scopePath, scopeType, languages, filesScanned, inventoryTotal, inventorySampled,
//         inventoryPath: string, recentChurn: string[], contextFiles: string[],
//         skillsToLoad: string[], runDomainAgent: bool, runDocVsCodeAgent: bool }
// inventoryPath, not an inventory array: 400 paths measure ~16 KB and args is size-capped
// (sidecar rule, .claude/workflows/AGENTS.md). recentChurn and contextFiles stay inline because
// the paired .md caps the two lists to a combined 2,500 serialized bytes — neither is bounded
// by construction, so the cap is what keeps them inline-safe.

// ARGS TRANSIT CONTRACT — canonical in .claude/workflows/AGENTS.md. This preamble is
// duplicated verbatim in all five workflow scripts BY NECESSITY, not by oversight: workflow
// scripts are self-contained and the runtime cannot load a shared module. Do not "DRY" it out.
let A
try {
  A = typeof args === 'string' ? JSON.parse(args) : (args ?? {})
} catch (e) {
  const n = typeof args === 'string' ? args.length : 0
  throw new Error(
    `args failed to parse (${e.message}). Received ${n} chars. The Workflow tool SIZE-CAPS the ` +
    `args string and truncates mid-string; the recovery echo shows it complete even so. ` +
    `Pass large artifacts by FILE PATH, not inline text — see .claude/workflows/AGENTS.md.`,
  )
}
for (const [k, v] of Object.entries(A)) {
  if (typeof v === 'string' && v.length > 8000) {
    log(`WARNING: args.${k} is ${v.length} chars (>8000) — pass it by path instead (.claude/workflows/AGENTS.md)`)
  }
}
// Not redundant with the loop above: that one inspects only string values, so it cannot see
// the array fields (recentChurn, contextFiles, skillsToLoad).
const argsTotal = typeof args === 'string' ? args.length : JSON.stringify(A).length
if (argsTotal > 12000) {
  log(`WARNING: args total ${argsTotal} chars (>12000 tripwire) — see .claude/workflows/AGENTS.md`)
}

// REQUIRED ARGS — throw, do not warn. The size tripwires above catch a payload that is too
// BIG; this catches one that is missing a field entirely. A missing/misnamed inventoryPath
// renders "Read the file at undefined" into every scanner prompt: the scanners get no scan
// list, the run completes, and the report claims a clean scope that was never read. The old
// inline inventory array failed loudly for free; a path does not.
// (Per-script, deliberately AFTER the shared preamble, which stays verbatim across all five.)
if (typeof A.inventoryPath !== 'string' || A.inventoryPath.length === 0) {
  throw new Error(
    `args is missing required field: inventoryPath. Received keys: ` +
    `${Object.keys(A).join(', ') || '(none)'}. See .claude/commands/bug-bash.md for the ` +
    `payload shape.`,
  )
}

// Model policy (deliberate, tunable):
// - fan-out agents (lenses/scanners/critics): pinned 'opus' @ effort 'high' —
//   high-volume parallel work; cost-bounded; misses are re-caught by synthesis + the
//   command's citation pass.
// - synthesizer: pinned 'opus' @ effort 'high' —
//   dedup/severity/drop judgments are the quality bottleneck; worth top-tier.
// agentType is 'readonly-worker' (.claude/agents/readonly-worker.md), not the built-in
// 'general-purpose' — same reasoning capability, but no Write/Edit/NotebookEdit/Artifact/
// Bash grant, so the "MUST NOT modify any file" rule in every scanner prompt is enforced
// by the harness, not just by instruction.
const FANOUT = { model: 'opus', effort: 'high', agentType: 'readonly-worker' }
const SYNTH = { model: 'opus', effort: 'high', agentType: 'readonly-worker' }

const CONFIDENCE_BAR = `CONFIDENCE BAR — every finding MUST satisfy:
1. Precise location — file_path:line_number (or range) resolving to a real file
2. Verbatim evidence — actual code snippet, byte-exact (not paraphrased)
3. Falsifiable trigger — concrete scenario WITH preconditions enumerated
4. Concrete impact — named harm AND named victim
5. Single minimal fix (1-3 sentences with file:line + exact change)
6. Reachability — for security/integrity/contracts: name the entry point reaching the cited code

If you cannot construct a trigger, OR (for security/integrity/contracts) cannot name an entry point reaching the code, DROP the finding silently.`

const FALSE_POSITIVE_RULES = `FALSE POSITIVE RULES — discard any finding matching:
1. Linter-catchable  2. Vague quality complaint  3. Subjective preference
4. Theoretical concern with no triggerable scenario  5. Pre-existing TODO/FIXME without active defect
6. Missing tests (unless a context file requires them)  7. Refactoring opportunity without concrete defect
8. Already mitigated upstream (guard/validator/sanitizer above the cited line)
9. Unreachable in current code  10. Defensive coding without active confusion or harm
11. Convention-relative deviation when the codebase has its own consistent pattern`

const ADVERSARIAL_DISCIPLINE = `ADVERSARIAL DISCIPLINE — before submitting each finding, construct the strongest counter-argument:
is there an upstream guard? does a type/validator/sanitizer exclude the input? is the path unreachable?
is the code defensive against an impossible state? could an unread callsite make it safe?
If you cannot defeat the counter-argument with concrete evidence from a file you read, DROP it silently.
A small list of well-defended findings beats a long list of plausible ones.`

// Severity DEFINITIONS live here (single consumer: the synthesizer). The paired .md keeps
// only the tier NAMES + the design-intent parenthetical and points here. Edit both together.
const SEVERITY_DEFINITIONS = `Grounded in three properties only: consequence, reachability, triggerability. No tier accepts "could be a problem" without all three.
- critical — Concrete harm (data loss, unauthorized access, secret exposure, crash on a normal input path, silent corruption). Reachable from a real entry point. Triggerable under normal operation.
- major — Concrete harm (lost-update window, broken contract that breaks a runtime call site, removed safeguard whose absence is reachable). Triggerable under realistic conditions (concurrency, retries, supported edge inputs, failure injection).
- high — Concrete harm (fragile logic on a reachable edge case, doc-vs-code lie that misleads a developer, contract drift not yet observed but reachable). Triggerable under a known-but-uncommon precondition.
- medium and below — DROPPED. Never appear in the report.`

const sharedContext = `TARGET SCOPE: ${A.scopePath}  (type: ${A.scopeType})
LANGUAGES: ${A.languages}
FILES SCANNED: ${A.filesScanned} of ${A.inventoryTotal} (sampled: ${A.inventorySampled})
FILES IN SCOPE — read the list before scanning:
Read the file at ${A.inventoryPath}. It holds one repo-relative path per line and is the
AUTHORITATIVE, CURATED scan list: already filtered against gitignore and already sampled down to
${A.filesScanned} paths. Read it COMPLETELY — Read truncates at 2,000 lines by default, so page
with \`offset\` if the list is longer.
Scan exactly what that file lists. Do NOT Glob to widen the scope — a path absent from the list
was deliberately excluded, and re-deriving your own list defeats the sampling. Prioritize
RECENT_CHURN below. Reading extra files to confirm reachability or an upstream guard is expected
and always allowed; that is not widening scope.

RECENT_CHURN (changed in last 6 months — higher-risk, prioritize):
${A.recentChurn.join('\n') || '(none)'}

CONTEXT FILES (you MAY read these on demand):
${A.contextFiles.join('\n') || '(none)'}

${CONFIDENCE_BAR}

${FALSE_POSITIVE_RULES}

${ADVERSARIAL_DISCIPLINE}

Use Read, Grep, Glob to inspect any file in scope; read extra files to confirm reachability and upstream guards. MUST NOT modify any file. Read-only. Your final message is consumed as data by an orchestration script — return the findings, no prose framing.`

const FINDING_PROPS = {
  title: { type: 'string' },
  file: { type: 'string' },
  start_line: { type: 'integer' },
  end_line: { type: 'integer' },
  category: { type: 'string', enum: ['correctness', 'security', 'integrity', 'contracts', 'domain', 'documentation'] },
  evidence: { type: 'string', description: 'verbatim snippet, byte-exact from the cited file' },
  trigger_scenario: { type: 'string', description: 'concrete scenario with preconditions enumerated' },
  entry_point: { type: 'string', description: "file:line, or 'n/a' for correctness/documentation" },
  impact: { type: 'string', description: 'named harm and named victim' },
  proposed_fix: { type: 'string', description: '1-3 sentences with file:line' },
  domain_skill: { type: 'string' },
}
const FINDING_REQUIRED = ['title', 'file', 'start_line', 'end_line', 'category', 'evidence', 'trigger_scenario', 'entry_point', 'impact', 'proposed_fix']

const SCANNER_SCHEMA = {
  type: 'object',
  required: ['findings'],
  additionalProperties: false,
  properties: {
    findings: {
      type: 'array',
      items: { type: 'object', required: FINDING_REQUIRED, additionalProperties: false, properties: FINDING_PROPS },
    },
  },
}

const DOC_VS_CODE_SCHEMA = {
  type: 'object',
  required: ['claims_checked', 'lies'],
  additionalProperties: false,
  properties: {
    claims_checked: { type: 'integer' },
    lies: {
      type: 'array',
      items: { type: 'object', required: FINDING_REQUIRED, additionalProperties: false, properties: FINDING_PROPS },
    },
  },
}

const SYNTH_SCHEMA = {
  type: 'object',
  required: ['findings'],
  additionalProperties: false,
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: [...FINDING_REQUIRED, 'severity', 'locations', 'witnesses'],
        additionalProperties: false,
        properties: {
          ...FINDING_PROPS,
          severity: { type: 'string', enum: ['critical', 'major', 'high'] },
          locations: {
            type: 'array',
            items: {
              type: 'object',
              required: ['file', 'start_line', 'end_line'],
              additionalProperties: false,
              properties: { file: { type: 'string' }, start_line: { type: 'integer' }, end_line: { type: 'integer' } },
            },
          },
          witnesses: { type: 'integer' },
        },
      },
    },
  },
}

const SCANNER_PROMPTS = {
  correctness: `${sharedContext}

Scan for correctness defects (bracketed phrasing is illustrative — apply equivalent reasoning to the actual language/runtime):

- Logic errors — wrong operator, inverted condition, off-by-one, unreachable branch, contradictory predicates, swapped arguments.
- Null / absence dereferences — accessing a value that may legitimately be null/undefined/none without a guard.
- Concurrency hazards — unguarded shared state, ordering assumptions, race windows, missing mutual exclusion, fan-out without join.
- Error suppression — caught errors discarded, failure return values ignored, exceptions swallowed.
- Async lifecycle — operations not awaited/joined when dependent code needs completion; fire-and-forget without a stored reference; orphan operations whose outcome is never observed.
- Type-system bypasses — casts/annotations disabling checks without justification; escape hatches into dynamic typing; suppression directives without an explanatory comment.
- Resource lifecycle — handles, locks, subscriptions, timers, descriptors, connections not released on every exit path.
- Identity vs equality — wrong comparison operator for the value type.
- Time / timezone / encoding — naive cross-zone arithmetic, mixed-encoding strings, locale-dependent parsing.

Set category = "correctness" and entry_point = "n/a" unless reachability is non-obvious.`,

  security: `${sharedContext}

Scan for security defects. Reachability is mandatory — every finding names the entry point connecting external input/state to the cited code:

- Missing/bypassable authn/authz on entry points (name the handler, route, command, callable, or consumer).
- Injection — query, command, markup, template, deserialization, or any case where untrusted input reaches a sink that interprets it.
- Unsanitized input reaching a dangerous sink — crosses a trust boundary without the validation/escaping the sink requires.
- Hardcoded secrets/credentials/keys/tokens in source.
- Weak/misused cryptography — predictable randomness in a security context, broken primitives, missing salt, key reuse, mode misuse.
- Unvalidated outbound requests (SSRF class) — destination influenced by external input without an allow-list.
- Path manipulation (traversal class) — paths from external input without canonicalization/scope enforcement.
- Token/session/cookie misconfig — missing integrity/expiration, predictable IDs, algorithm confusion, missing transport flags.
- Sensitive data exposure — credentials, tokens, PII, stack traces leaking via logs, errors, payloads, telemetry.
- Mass assignment — arbitrary input shapes mapping onto domain models without a field allow-list.

Set category = "security" and entry_point to the entry point file:line. No entry point => unreachable => drop.`,

  'integrity-contracts': `${sharedContext}

Scan for integrity and contract defects. Reachability is mandatory.

Integrity (category = "integrity"): state-machine violations (invalid transitions, missing guards, terminal states with exits); transaction-boundary errors (partial writes without rollback, work outside a needed transaction); lost-update / optimistic-locking errors (concurrent updates without version checks, missing compare-and-set); idempotency failures (retries that double side effects, missing dedup keys); referential-integrity assumptions not actually enforced; schema/model drift across layers; migration ordering hazards (destructive change before consumers updated); pagination/batch/offset arithmetic that corrupts at scale.

Contracts (category = "contracts"): inter-layer/inter-service contract drift (caller expects a shape/path/status/ordering the callee no longer provides); domain-validator drift (same input validated under different rules in different places); response-shape divergence (producer emits what consumers cannot parse). For multi-layer findings, set the primary file/lines to the most authoritative side and describe the other side(s) in evidence.

Set entry_point to the entry point file:line. If unreachable, drop.`,
}

phase('Scan')
const specs = [
  { label: 'correctness', prompt: SCANNER_PROMPTS.correctness, schema: SCANNER_SCHEMA },
  { label: 'security', prompt: SCANNER_PROMPTS.security, schema: SCANNER_SCHEMA },
  { label: 'integrity-contracts', prompt: SCANNER_PROMPTS['integrity-contracts'], schema: SCANNER_SCHEMA },
]

if (A.runDomainAgent) {
  specs.push({
    label: `domain (${A.skillsToLoad.join(', ')})`,
    schema: SCANNER_SCHEMA,
    prompt: `${sharedContext}

Load these reviewer skills from .claude/skills/: ${A.skillsToLoad.join(', ')} (read each skill's SKILL.md and follow it).

Each skill encodes a review methodology for a specific domain — the skill is your specification. Execute it end-to-end against the in-scope files it applies to. Surface only domain-specific defects the universal scanners (correctness/security/integrity) would miss for lack of the skill's specialized knowledge; overlaps are deduplicated downstream. Apply the confidence bar (including reachability where implied), the false-positive rules, and adversarial discipline.

Set category = "domain" and set domain_skill = "<skill-name>" on each finding.`,
  })
}

if (A.runDocVsCodeAgent) {
  specs.push({
    label: 'doc-vs-code',
    schema: DOC_VS_CODE_SCHEMA,
    prompt: `${sharedContext}

Two stages:

Stage A — Extract claims. Read every file in CONTEXT FILES. Count each concrete factual claim about the codebase (file locations, command names, behaviors, config keys, env vars, flags, endpoints, build/test commands, conventions, dependency versions). Opinions and forward-looking statements are NOT claims. Track the count as claims_checked.

Stage B — Verify against code. A claim is a LIE when: the file/path/command/flag does not exist or was renamed; the described behavior does not match the implementation; the example would not run as written; the stated convention is contradicted by actual code; the version constraint is inconsistent with the actual dependency. Only claims that would actively mislead a developer into wrong action are LIES.

For each LIE, fill the finding schema this way (the fields are shared with the code scanners): file = the doc path; start_line/end_line = the line range of the misleading text in that doc; title = short label; evidence = the misleading text quoted verbatim; trigger_scenario = the situation in which a developer, following this text, takes the wrong action (this IS the doc-lie's trigger); impact = what they do wrong and who is harmed; proposed_fix = exact replacement wording; entry_point = "n/a"; category = "documentation".`,
  })
}

const results = await parallel(specs.map((s) => () =>
  agent(s.prompt, { label: s.label, phase: 'Scan', schema: s.schema, ...FANOUT })))

const agentsFailed = specs.filter((s, i) => results[i] == null).map((s) => s.label)
let docClaimsChecked = null
const allFindings = []
results.forEach((r, i) => {
  if (r == null) return
  if (specs[i].label === 'doc-vs-code') {
    docClaimsChecked = r.claims_checked
    allFindings.push(...r.lies)
  } else {
    allFindings.push(...r.findings)
  }
})

const base = { docClaimsChecked, skillsLoaded: A.skillsToLoad, agentsFailed }
if (allFindings.length === 0) return { findings: [], ...base }

phase('Synthesize')
log(`${allFindings.length} raw findings from ${specs.length - agentsFailed.length} scanners — synthesizing`)

const synth = await agent(
  `You are the synthesizer for a forensic bug bash on ${A.scopePath}. Raw findings from multiple scanner agents:

${JSON.stringify(allFindings, null, 1)}

${CONFIDENCE_BAR}

${FALSE_POSITIVE_RULES}

Corroboration signal: when two or more scanner agents flagged overlapping line ranges in the same file for the same underlying issue, that is stronger evidence — merge them and note it in witnesses. A single-witness finding with a vague trigger, unclear entry point, or non-verbatim evidence should be dropped.

Tasks: (1) Dedupe overlapping same-file findings into one, keeping the strongest evidence. (2) Consolidate same-root-cause defects across files into one finding with a locations array (primary = most representative); consolidate only when there is one named root cause AND one conceptual fix applied in N places. (3) Re-apply the confidence bar and false-positive rules holistically — you may Read cited files to check upstream guards. (4) Classify severity by consequence + reachability + triggerability only, per these definitions:

${SEVERITY_DEFINITIONS}

medium and below => DROP. (5) Sort by severity (critical -> major -> high), then file, then start_line. (6) Cap at top 10, preferring higher severity then broadest blast radius.

locations is required (one entry for single-location findings). witnesses = number of scanner agents that independently flagged it (1 if single).`,
  { label: 'synthesizer', phase: 'Synthesize', schema: SYNTH_SCHEMA, ...SYNTH },
)

if (synth == null) return { findings: [], ...base, agentsFailed: [...agentsFailed, 'synthesizer'] }
return { findings: synth.findings, ...base }
